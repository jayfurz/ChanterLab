import AVFoundation
import WebKit
import os

/// Native microphone capture + pitch detection for the web UI.
///
/// The page (training-prototype/scope.js) posts `micStart` / `micStop` /
/// `setProcessing` to the `chanterlabAudio` handler instead of calling
/// getUserMedia; we capture with AVAudioEngine, run the same Rust detector the
/// web build uses, and push `{hz, gateOpen, level}` frames back at ~60 Hz.
final class NativeAudio: NSObject, WKScriptMessageHandler {
    static let handlerName = "chanterlabAudio"

    weak var web: WKWebView?

    private var engine = AVAudioEngine()
    private var sink: AVAudioSinkNode?
    private var pump: Timer?
    private var toneTimer: Timer?
    private var running = false
    private var processing = false
    private var gate: Float = 0.02

    /// Shared with the realtime thread. The audio callback only ever
    /// try-locks, so it can never block on the main thread.
    private final class Shared {
        var lock = os_unfair_lock()
        var tracker: OpaquePointer?
        var frames: [Frame] = []          // capacity reserved up front
        var sinceDetect = 0
        var detectEvery = 800
    }
    private struct Frame { var hz: Float; var gateOpen: Bool; var level: Float }
    private let shared = Shared()

    override init() {
        super.init()
        shared.frames.reserveCapacity(64)
        let nc = NotificationCenter.default
        nc.addObserver(self, selector: #selector(configChanged),
                       name: .AVAudioEngineConfigurationChange, object: nil)
        nc.addObserver(self, selector: #selector(interrupted(_:)),
                       name: AVAudioSession.interruptionNotification, object: nil)
    }

    // MARK: bridge

    func userContentController(_ controller: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "micStart":
            processing = body["processing"] as? Bool ?? false
            if let g = body["gate"] as? Double { gate = Float(g) }
            requestMicThenStart()
        case "micStop":
            stop()
        case "setProcessing":
            let next = body["processing"] as? Bool ?? false
            if next != processing {
                processing = next
                if running { stop(); start() }
            }
        default:
            break
        }
    }

    private func send(_ fn: String, _ json: String) {
        web?.evaluateJavaScript(
            "window.__chanterlabNativeAudio&&window.__chanterlabNativeAudio.\(fn)(\(json))",
            completionHandler: nil)
    }

    private func report(error: String) {
        let escaped = error.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        send("onState", "{\"error\":\"\(escaped)\"}")
    }

    /// Audio thread: push samples and emit a frame every ~1/60 s, whatever IO
    /// buffer size the route gives us. Only try-locks; never allocates.
    private static func feed(_ shared: Shared, _ samples: UnsafePointer<Float>, _ n: Int) {
        guard os_unfair_lock_trylock(&shared.lock) else { return }
        defer { os_unfair_lock_unlock(&shared.lock) }
        guard let tracker = shared.tracker else { return }
        var offset = 0
        while offset < n {
            let take = min(n - offset, shared.detectEvery - shared.sinceDetect)
            clp_tracker_push(tracker, samples + offset, take)
            offset += take
            shared.sinceDetect += take
            if shared.sinceDetect >= shared.detectEvery {
                shared.sinceDetect = 0
                let hz = clp_tracker_detect_hz(tracker)
                if shared.frames.count < 64 {
                    shared.frames.append(Frame(hz: hz,
                                               gateOpen: clp_tracker_gate_open(tracker),
                                               level: clp_tracker_level(tracker)))
                }
            }
        }
    }

    // MARK: lifecycle

    private func requestMicThenStart() {
        if debugToneHz != nil { start(); return }
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            DispatchQueue.main.async {
                guard let self else { return }
                granted ? self.start() : self.report(error: "Microphone access was denied")
            }
        }
    }

    /// DEBUG aid: `CHANTERLAB_TONE=<hz>` in the environment feeds a sine to the
    /// detector instead of opening the mic, so detector + bridge can be verified
    /// on a simulator (whose audio input is unavailable over SSH).
    private var debugToneHz: Float? {
        #if DEBUG
        if let s = ProcessInfo.processInfo.environment["CHANTERLAB_TONE"], let hz = Float(s) { return hz }
        #endif
        return nil
    }

    private func resetTracker(sampleRate: Float) {
        os_unfair_lock_lock(&shared.lock)
        if let old = shared.tracker { clp_tracker_free(old) }
        shared.tracker = clp_tracker_new(sampleRate, gate)
        shared.frames.removeAll(keepingCapacity: true)
        shared.sinceDetect = 0
        shared.detectEvery = max(128, Int(sampleRate / 60))
        os_unfair_lock_unlock(&shared.lock)
    }

    private func startPump() {
        let timer = Timer(timeInterval: 1.0 / 120, repeats: true) { [weak self] _ in self?.drain() }
        RunLoop.main.add(timer, forMode: .common)
        pump = timer
    }

    private func startDebugTone(_ hz: Float) {
        let sampleRate: Float = 48_000
        resetTracker(sampleRate: sampleRate)
        var phase: Float = 0
        var block = [Float](repeating: 0, count: 480)
        let shared = self.shared
        let timer = Timer(timeInterval: 0.01, repeats: true) { _ in
            for i in block.indices {
                block[i] = 0.3 * sinf(phase)
                phase += 2 * .pi * hz / sampleRate
                if phase > 2 * .pi { phase -= 2 * .pi }
            }
            block.withUnsafeBufferPointer { NativeAudio.feed(shared, $0.baseAddress!, $0.count) }
        }
        RunLoop.main.add(timer, forMode: .common)
        toneTimer = timer
        running = true
        send("onState", "{\"sampleRate\":\(sampleRate)}")
        startPump()
    }

    private func start() {
        guard !running else { return }
        if let hz = debugToneHz { startDebugTone(hz); return }
        do {
            let session = AVAudioSession.sharedInstance()
            // Speaker mode keeps Apple's echo canceller (so the accompaniment
            // stays out of the pitch tracker); headphones mode takes the raw mic.
            try session.setCategory(.playAndRecord,
                                    mode: processing ? .voiceChat : .measurement,
                                    options: [.defaultToSpeaker, .allowBluetoothA2DP, .mixWithOthers])
            try? session.setPreferredIOBufferDuration(0.005)
            try session.setActive(true)

            engine = AVAudioEngine()
            let input = engine.inputNode
            try? input.setVoiceProcessingEnabled(processing)
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                report(error: "No audio input available")
                return
            }
            let sampleRate = Float(format.sampleRate)

            resetTracker(sampleRate: sampleRate)

            let shared = self.shared
            let sink = AVAudioSinkNode { _, frameCount, bufferList -> OSStatus in
                guard let data = bufferList.pointee.mBuffers.mData else { return noErr }
                NativeAudio.feed(shared, UnsafePointer(data.assumingMemoryBound(to: Float.self)), Int(frameCount))
                return noErr
            }
            engine.attach(sink)
            engine.connect(input, to: sink, format: format)
            self.sink = sink
            try engine.start()
            running = true
            send("onState", "{\"sampleRate\":\(format.sampleRate)}")
            startPump()
        } catch {
            report(error: error.localizedDescription)
        }
    }

    private func stop() {
        pump?.invalidate(); pump = nil
        toneTimer?.invalidate(); toneTimer = nil
        guard running else { return }
        running = false
        engine.stop()
        if let sink { engine.detach(sink) }
        sink = nil
        os_unfair_lock_lock(&shared.lock)
        if let t = shared.tracker { clp_tracker_free(t) }
        shared.tracker = nil
        shared.frames.removeAll(keepingCapacity: true)
        os_unfair_lock_unlock(&shared.lock)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    /// Main thread: hand the frames the audio thread produced to the page.
    private func drain() {
        os_unfair_lock_lock(&shared.lock)
        let frames = shared.frames
        shared.frames.removeAll(keepingCapacity: true)
        os_unfair_lock_unlock(&shared.lock)
        for f in frames {
            send("onPitch", "{\"hz\":\(f.hz.isFinite ? f.hz : 0),\"gateOpen\":\(f.gateOpen),\"level\":\(f.level.isFinite ? f.level : 0)}")
        }
    }

    // MARK: route / interruption

    /// Route or sample-rate change (headphones plugged, Bluetooth, a call):
    /// the engine stops itself; rebuild on the new format.
    @objc private func configChanged() {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running else { return }
            self.stop(); self.start()
        }
    }

    @objc private func interrupted(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running else { return }
            self.stop(); self.start()
        }
    }
}
