import AVFoundation
import os

/// One pitch-detector reading (about 60 per second while the mic is on).
struct PitchFrame {
    var hz: Float
    var gateOpen: Bool
    var level: Float
}

/// The app's single audio engine: the Rust synth on the output side and, when
/// the mic is on, capture feeding the Rust pitch detector.
///
/// Owning both directions in one `AVAudioEngine` is the point of the native
/// app: playback and capture share one session and one voice-processing unit,
/// so turning the mic on cannot pull the hardware format out from under the
/// playback path (the crackle the web build cannot avoid).
///
/// Main thread only, except the two render callbacks.
final class AudioEngine {
    /// Detector readings, delivered on the main thread.
    var onPitch: (([PitchFrame]) -> Void)?
    /// The synth was rebuilt (first start or a sample-rate change) and has no
    /// state: the owner must re-send voicing, volume, drone and metronome.
    var onSynthReset: (() -> Void)?
    var onError: ((String) -> Void)?

    private(set) var micOn = false
    private(set) var running = false
    private(set) var sampleRate: Double = 0
    /// True when the mic is running through Apple's echo canceller (speaker out).
    private(set) var echoCancelling = false

    var gate: Float = 0.02 {
        didSet {
            os_unfair_lock_lock(&shared.lock)
            if let t = shared.tracker { clp_tracker_set_gate(t, gate) }
            os_unfair_lock_unlock(&shared.lock)
        }
    }

    private var engine = AVAudioEngine()
    private var synth: OpaquePointer?
    private var pump: Timer?
    private var toneTimer: Timer?
    private var rebuilding = false

    /// Shared with the capture thread, which only ever try-locks.
    private final class Shared {
        var lock = os_unfair_lock()
        var tracker: OpaquePointer?
        var frames: [PitchFrame] = []
        var sinceDetect = 0
        var detectEvery = 800
    }
    private let shared = Shared()

    init() {
        shared.frames.reserveCapacity(64)
        let nc = NotificationCenter.default
        nc.addObserver(self, selector: #selector(configChanged),
                       name: .AVAudioEngineConfigurationChange, object: nil)
        nc.addObserver(self, selector: #selector(interrupted(_:)),
                       name: AVAudioSession.interruptionNotification, object: nil)
        nc.addObserver(self, selector: #selector(routeChanged(_:)),
                       name: AVAudioSession.routeChangeNotification, object: nil)
    }

    // MARK: synth (safe before start: calls are dropped until a synth exists)

    func noteOn(id: Int, hz: Double, velocity: Float = 0.8) {
        ensureRunning()
        clp_synth_note_on(synth, Int32(id), Float(hz), velocity)
    }
    func noteOff(id: Int) { clp_synth_note_off(synth, Int32(id)) }
    func retune(id: Int, hz: Double) { clp_synth_retune(synth, Int32(id), Float(hz)) }
    func allNotesOff() { clp_synth_all_notes_off(synth) }
    func setIson(hz: Double, volume: Float) {
        if volume > 0 { ensureRunning() }
        clp_synth_ison(synth, Float(hz), volume)
    }
    func setVoicing(_ index: Int) { clp_synth_set_voicing(synth, UInt8(index)) }
    func setMaster(_ level: Float) { clp_synth_set_master(synth, level) }
    func setMetronome(bpm: Double, volume: Float, beatsPerBar: Int) {
        if bpm > 0 { ensureRunning() }
        clp_synth_metronome(synth, Float(bpm), volume, UInt8(beatsPerBar))
    }

    // MARK: lifecycle

    /// Start output if it is not running yet (first note, drone or metronome).
    func ensureRunning() {
        if !running { rebuild() }
    }

    /// Stop everything and release the audio session (app backgrounded while idle).
    func suspend() {
        guard running, !micOn else { return }
        teardown()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func setMic(_ on: Bool) {
        guard on != micOn else { return }
        guard on else {
            micOn = false
            rebuild()
            return
        }
        if Self.debugToneHz != nil {
            micOn = true
            rebuild()
            return
        }
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            DispatchQueue.main.async {
                guard let self else { return }
                guard granted else {
                    self.onError?("Microphone access is off. Allow it in Settings → ChanterLab.")
                    return
                }
                self.micOn = true
                self.rebuild()
            }
        }
    }

    /// DEBUG aid: `CHANTERLAB_TONE=<hz>` feeds a sine to the detector instead of
    /// opening the mic, so the capture path can be exercised on a simulator
    /// (whose audio input is unavailable over SSH).
    private static var debugToneHz: Float? {
        #if DEBUG
        if let s = ProcessInfo.processInfo.environment["CHANTERLAB_TONE"], let hz = Float(s) { return hz }
        #endif
        return nil
    }

    private static var headphonesConnected: Bool {
        let wired: Set<AVAudioSession.Port> = [.headphones, .bluetoothA2DP, .bluetoothLE, .bluetoothHFP,
                                               .usbAudio, .lineOut, .airPlay, .carAudio]
        return AVAudioSession.sharedInstance().currentRoute.outputs.contains { wired.contains($0.portType) }
    }

    private func teardown() {
        pump?.invalidate(); pump = nil
        toneTimer?.invalidate(); toneTimer = nil
        engine.stop()
        running = false
        os_unfair_lock_lock(&shared.lock)
        if let t = shared.tracker { clp_tracker_free(t) }
        shared.tracker = nil
        shared.frames.removeAll(keepingCapacity: true)
        os_unfair_lock_unlock(&shared.lock)
    }

    /// (Re)build the session and graph for the current mic state and route.
    private func rebuild() {
        rebuilding = true
        defer { rebuilding = false }
        teardown()

        let captureMic = micOn && Self.debugToneHz == nil
        do {
            let session = AVAudioSession.sharedInstance()
            if captureMic {
                try session.setCategory(.playAndRecord, mode: .default,
                                        options: [.defaultToSpeaker, .allowBluetoothA2DP])
            } else {
                try session.setCategory(.playback, mode: .default, options: [])
            }
            try? session.setPreferredIOBufferDuration(0.005)
            try session.setActive(true)

            engine = AVAudioEngine()

            // Speaker out: keep Apple's echo canceller so the synth and drone
            // stay out of the pitch tracker. Headphones: take the raw mic.
            let useEchoCanceller = captureMic && !Self.headphonesConnected
            var inputFormat: AVAudioFormat?
            if captureMic {
                let input = engine.inputNode
                try? input.setVoiceProcessingEnabled(useEchoCanceller)
                if useEchoCanceller {
                    input.voiceProcessingOtherAudioDuckingConfiguration =
                        .init(enableAdvancedDucking: false, duckingLevel: .min)
                }
                let format = input.outputFormat(forBus: 0)
                guard format.sampleRate > 0, format.channelCount > 0 else {
                    throw NSError(domain: "ChanterLab", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "No audio input available"])
                }
                inputFormat = format
            }
            echoCancelling = useEchoCanceller

            var rate = engine.outputNode.inputFormat(forBus: 0).sampleRate
            if rate <= 0 { rate = session.sampleRate }
            if synth == nil || rate != sampleRate {
                if let old = synth { clp_synth_free(old) }
                synth = clp_synth_new(Float(rate))
                sampleRate = rate
                onSynthReset?()
            }

            guard let synth,
                  let mono = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1) else { return }
            let source = AVAudioSourceNode(format: mono) { _, _, frameCount, bufferList -> OSStatus in
                let buffers = UnsafeMutableAudioBufferListPointer(bufferList)
                guard let out = buffers.first?.mData else { return noErr }
                clp_synth_render(synth, out.assumingMemoryBound(to: Float.self), Int(frameCount))
                return noErr
            }
            engine.attach(source)
            engine.connect(source, to: engine.mainMixerNode, format: mono)

            if let inputFormat {
                resetTracker(sampleRate: Float(inputFormat.sampleRate))
                let shared = self.shared
                let sink = AVAudioSinkNode { _, frameCount, bufferList -> OSStatus in
                    guard let data = bufferList.pointee.mBuffers.mData else { return noErr }
                    AudioEngine.feed(shared, UnsafePointer(data.assumingMemoryBound(to: Float.self)), Int(frameCount))
                    return noErr
                }
                engine.attach(sink)
                engine.connect(engine.inputNode, to: sink, format: inputFormat)
            }

            try engine.start()
            running = true

            if micOn {
                if let hz = Self.debugToneHz { startDebugTone(hz) }
                startPump()
            }
        } catch {
            micOn = false
            running = false
            onError?(error.localizedDescription)
        }
    }

    // MARK: capture

    private func resetTracker(sampleRate: Float) {
        os_unfair_lock_lock(&shared.lock)
        if let old = shared.tracker { clp_tracker_free(old) }
        shared.tracker = clp_tracker_new(sampleRate, gate)
        shared.frames.removeAll(keepingCapacity: true)
        shared.sinceDetect = 0
        shared.detectEvery = max(128, Int(sampleRate / 60))
        os_unfair_lock_unlock(&shared.lock)
    }

    /// Capture thread: push samples and emit a reading every ~1/60 s whatever
    /// the IO buffer size. Only try-locks; never allocates.
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
                    shared.frames.append(PitchFrame(hz: hz.isFinite ? hz : 0,
                                                    gateOpen: clp_tracker_gate_open(tracker),
                                                    level: clp_tracker_level(tracker)))
                }
            }
        }
    }

    private func startPump() {
        let timer = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in self?.drain() }
        RunLoop.main.add(timer, forMode: .common)
        pump = timer
    }

    private func drain() {
        os_unfair_lock_lock(&shared.lock)
        let frames = shared.frames
        shared.frames.removeAll(keepingCapacity: true)
        os_unfair_lock_unlock(&shared.lock)
        if !frames.isEmpty { onPitch?(frames) }
    }

    private func startDebugTone(_ hz: Float) {
        let rate: Float = 48_000
        resetTracker(sampleRate: rate)
        var phase: Float = 0
        var block = [Float](repeating: 0, count: 480)
        let shared = self.shared
        let timer = Timer(timeInterval: 0.01, repeats: true) { _ in
            for i in block.indices {
                block[i] = 0.3 * sinf(phase)
                phase += 2 * .pi * hz / rate
                if phase > 2 * .pi { phase -= 2 * .pi }
            }
            block.withUnsafeBufferPointer { AudioEngine.feed(shared, $0.baseAddress!, $0.count) }
        }
        RunLoop.main.add(timer, forMode: .common)
        toneTimer = timer
    }

    // MARK: route / interruption

    /// The hardware format changed (a route or sample-rate change): the engine
    /// has stopped itself, so rebuild on the new format.
    @objc private func configChanged() {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running, !self.rebuilding else { return }
            self.rebuild()
        }
    }

    /// Headphones plugged or unplugged with the mic on: the echo canceller
    /// should follow the route.
    @objc private func routeChanged(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
              let reason = AVAudioSession.RouteChangeReason(rawValue: raw),
              reason == .newDeviceAvailable || reason == .oldDeviceUnavailable else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running, self.micOn, !self.rebuilding,
                  self.echoCancelling == Self.headphonesConnected else { return }
            self.rebuild()
        }
    }

    @objc private func interrupted(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running else { return }
            self.rebuild()
        }
    }
}
