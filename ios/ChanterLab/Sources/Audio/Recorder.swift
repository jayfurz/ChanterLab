import AVFoundation

/// Records the accompaniment and the microphone into one AAC file.
///
/// The audio callbacks only push samples into two lock-free rings; a writer
/// queue drains them, mixes at the chosen balance and encodes. Nothing here
/// changes the audio graph, so recording cannot disturb playback or capture.
final class Recorder {
    /// What the audio threads see. `on` is the only field that changes.
    final class Tap {
        let music: OpaquePointer
        let mic: OpaquePointer
        var on = false

        init() {
            // Four seconds at 48 kHz: far more than the writer ever lets build up.
            music = clp_ring_new(192_000)
            mic = clp_ring_new(192_000)
        }
    }

    let tap = Tap()

    /// Set by the audio engine whenever the graph is (re)built.
    var musicRate = 48_000.0
    /// 0 when the microphone is not running.
    var micRate = 0.0
    /// Output latency + input latency: how much later the singer's response
    /// arrives than the accompaniment that prompted it.
    var roundTripLatency = 0.0

    /// 0 = accompaniment only, 1 = voice only, 0.5 = both at full level.
    var balance: Float = 0.5

    private(set) var isRecording = false
    private(set) var url: URL?
    private(set) var startedAt: Date?
    /// Called on the main thread when a recording ends on its own (route change).
    var onInterrupted: (() -> Void)?

    private var file: AVAudioFile?
    private var format: AVAudioFormat?
    private var timer: DispatchSourceTimer?
    private let queue = DispatchQueue(label: "chanterlab.recorder")
    /// Mic samples not yet mixed, and the fractional read position into them.
    private var pending: [Float] = []
    private var micPosition = 0.0
    private var musicScratch = [Float](repeating: 0, count: 16_384)
    private var micScratch = [Float](repeating: 0, count: 16_384)

    /// Start writing to `url` (an .m4a path). Throws if the file cannot be created.
    func start(url: URL) throws {
        guard !isRecording else { return }
        let rate = musicRate
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1) else {
            throw NSError(domain: "ChanterLab", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Recording format is unavailable"])
        }
        try? FileManager.default.removeItem(at: url)
        let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: rate,
                                       AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 128_000]
        let file = try AVAudioFile(forWriting: url, settings: settings,
                                   commonFormat: .pcmFormatFloat32, interleaved: false)
        self.file = file
        self.format = format
        self.url = url
        startedAt = Date()
        micPosition = 0
        pending.removeAll(keepingCapacity: true)

        // Empty anything stale, then delay the accompaniment by the round trip
        // so the voice lines up with what the singer was hearing.
        drain(tap.music); drain(tap.mic)
        let delay = [Float](repeating: 0, count: Int(max(0, min(0.5, roundTripLatency)) * rate))
        if !delay.isEmpty { clp_ring_push(tap.music, delay, delay.count) }

        isRecording = true
        tap.on = true
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 0.05, repeating: 0.05)
        timer.setEventHandler { [weak self] in self?.pump(final: false) }
        timer.resume()
        self.timer = timer
    }

    /// Finish the file. Returns its URL, or nil if nothing was being recorded.
    @discardableResult
    func stop(interrupted: Bool = false) -> URL? {
        guard isRecording else { return nil }
        tap.on = false
        isRecording = false
        timer?.cancel(); timer = nil
        queue.sync {
            pump(final: true)
            file = nil // closes and finalizes the file
        }
        startedAt = nil
        if interrupted { DispatchQueue.main.async { [weak self] in self?.onInterrupted?() } }
        return url
    }

    private func drain(_ ring: OpaquePointer) {
        var scratch = [Float](repeating: 0, count: 8192)
        while clp_ring_pop(ring, &scratch, scratch.count) > 0 {}
    }

    /// Writer queue: mix what both rings hold and append it to the file.
    private func pump(final: Bool) {
        guard let file, let format else { return }
        let micOn = micRate > 0
        // Mic samples per output frame (the two sides may run at different rates).
        let ratio = micOn ? micRate / musicRate : 1

        // Take everything the mic has captured so far.
        if micOn {
            while true {
                let got = clp_ring_pop(tap.mic, &micScratch, micScratch.count)
                if got == 0 { break }
                pending.append(contentsOf: micScratch[0..<got])
            }
        }

        while true {
            var frames = min(clp_ring_len(tap.music), musicScratch.count)
            // Interpolating frame i reads mic samples floor(p) and floor(p) + 1.
            let fromMic = max(0, Int((Double(pending.count - 1) - micPosition) / ratio))
            if micOn, !final { frames = min(frames, fromMic) }
            guard frames > 0,
                  let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)),
                  let out = buffer.floatChannelData?[0] else { return }
            let got = clp_ring_pop(tap.music, &musicScratch, frames)
            guard got > 0 else { return }

            let musicGain = min(1, 2 * (1 - balance)), micGain = min(1, 2 * balance)
            for i in 0..<got {
                var voice: Float = 0
                let position = micPosition + Double(i) * ratio
                let index = Int(position)
                if index + 1 < pending.count {
                    let a = pending[index], b = pending[index + 1]
                    voice = a + (b - a) * Float(position - Double(index))
                }
                out[i] = max(-1, min(1, musicScratch[i] * musicGain + voice * micGain))
            }
            if micOn {
                micPosition += Double(got) * ratio
                let used = min(pending.count, Int(micPosition))
                pending.removeFirst(used)
                micPosition -= Double(used)
            }
            buffer.frameLength = AVAudioFrameCount(got)
            try? file.write(from: buffer)
        }
    }
}
