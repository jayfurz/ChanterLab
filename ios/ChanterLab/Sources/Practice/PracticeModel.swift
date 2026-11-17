import Foundation
import Observation

/// One-euro filter (Casiez et al.): smooths jitter when the value is steady
/// and follows quickly when it moves. Same parameters as the web scope.
struct OneEuroFilter {
    var minCutoff = 2.0
    var beta = 1.0
    var dCutoff = 1.0
    private var last: Double?
    private var lastDerivative = 0.0

    private static func alpha(cutoff: Double, dt: Double) -> Double {
        let tau = 1 / (2 * .pi * cutoff)
        return 1 / (1 + tau / dt)
    }

    mutating func reset() { last = nil; lastDerivative = 0 }

    mutating func filter(_ x: Double, dt: Double) -> Double {
        guard let previous = last else { last = x; return x }
        let dt = (dt > 0 && dt <= 0.25) ? dt : 1.0 / 60
        let rawDerivative = (x - previous) / dt
        let aD = Self.alpha(cutoff: dCutoff, dt: dt)
        lastDerivative += aD * (rawDerivative - lastDerivative)
        let a = Self.alpha(cutoff: minCutoff + beta * abs(lastDerivative), dt: dt)
        let y = previous + a * (x - previous)
        last = y
        return y
    }
}

/// A note of the loop window, in seconds from the window start.
struct LaneNote {
    let part: Int
    /// Index in the part's `notes` (what the engraved heads point at).
    let noteIndex: Int
    /// Index among the selected part's window notes (matches scoring details); -1 for other parts.
    let targetIndex: Int
    let midi: Int
    let start: Double
    let end: Double
    let measure: Int
    let lyric: String?
}

/// A sung pitch sample on the unwrapped practice clock. `midi == nil` breaks the trace.
struct SungSample {
    let time: Double
    let midi: Double?
}

/// Score practice: load a piece, play the other parts, follow the singer.
@Observable
final class PracticeModel {
    enum Transport { case stopped, playing, paused }

    let audio: AudioEngine
    let library: Library

    // MARK: piece

    private(set) var piece: Piece?
    private(set) var score: Score?
    /// Bumped whenever `score` is replaced, so the engraving is laid out again.
    private(set) var scoreRevision = 0
    private(set) var loading = false
    var errorMessage: String?
    @ObservationIgnored private var xml: String?

    /// Index of the singer's own part.
    var voice = 0 { didSet { if voice != oldValue { rebuildWindow(restart: true) } } }
    var verse = 1 { didSet { if verse != oldValue { reparse() } } }
    var bpm = 70.0 { didSet { if bpm != oldValue { rebuildWindow(restart: true) } } }
    /// Practice transpose in semitones: moves what is played and what is scored.
    var transpose = 0 { didSet { if transpose != oldValue { rebuildWindow(restart: true) } } }
    var loopOn = false { didSet { if loopOn != oldValue { rebuildWindow(restart: true) } } }
    var loopFrom = 1 { didSet { if loopFrom != oldValue { rebuildWindow(restart: true) } } }
    var loopTo = 1 { didSet { if loopTo != oldValue { rebuildWindow(restart: true) } } }
    /// Play the singer's own part too (off: the other parts only).
    var hearMine = false { didSet { rescheduleIfPlaying() } }
    var strict: Bool { didSet { defaults.set(strict, forKey: "practice.strict") } }
    /// Voice response: how late a sung note reaches the detector, in ms.
    var responseMs: Double { didSet { defaults.set(responseMs, forKey: "practice.responseMs") } }
    /// Extra playback delay to add on top of what the system reports, in ms.
    var syncMs: Double { didSet { defaults.set(syncMs, forKey: "practice.syncMs") } }
    var showVerdicts = true
    /// Accompaniment sound: the triangle synth or the sampled "ah" voices.
    var sampledVoices: Bool {
        didSet {
            defaults.set(sampledVoices, forKey: "practice.sampledVoices")
            rescheduleIfPlaying()
        }
    }
    /// Recording mix: 0 accompaniment only … 1 voice only.
    var recordBalance: Double {
        didSet {
            defaults.set(recordBalance, forKey: "practice.recordBalance")
            audio.recorder.balance = Float(recordBalance)
        }
    }

    // MARK: recording

    private(set) var recording = false
    private(set) var recordingStarted: Date?
    /// The last finished recording, ready to share.
    private(set) var recordingURL: URL?
    @ObservationIgnored private var wantsRecording = false

    /// Start or stop recording the accompaniment together with the microphone.
    func toggleRecording() {
        if recording { finishRecording(); return }
        wantsRecording = true
        if micOn, audio.running { beginRecording() } else { setMic(true) }
    }

    /// The audio graph was rebuilt: a requested recording can start once the mic is live.
    func audioStateChanged() {
        if wantsRecording, !recording, audio.micOn, audio.running { beginRecording() }
    }

    private func beginRecording() {
        wantsRecording = false
        let day = ISO8601DateFormatter.string(from: Date(), timeZone: .current, formatOptions: [.withFullDate])
        let name = "chanterlab-\(piece?.id ?? "practice")-\(day).m4a"
            .replacingOccurrences(of: "/", with: "-")
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        do {
            audio.recorder.balance = Float(recordBalance)
            try audio.recorder.start(url: url)
            recording = true
            recordingStarted = Date()
            recordingURL = nil
        } catch {
            errorMessage = "Recording could not start: \(error.localizedDescription)"
        }
    }

    func finishRecording() {
        wantsRecording = false
        guard recording else { return }
        recordingURL = audio.recorder.stop()
        recording = false
        recordingStarted = nil
    }

    /// The engine closed the recording itself (the audio route changed).
    func recordingInterrupted() {
        guard recording else { return }
        recordingURL = audio.recorder.url
        recording = false
        recordingStarted = nil
    }

    var sections: [ScoreSection] {
        if let catalog = piece?.sections, catalog.count >= 2 { return catalog }
        return score?.sections ?? []
    }

    // MARK: transport state

    private(set) var transport = Transport.stopped
    private(set) var micOn = false
    private(set) var lap = 0
    private(set) var report: LapReport?
    private(set) var bestPct: Int?
    private(set) var status = ""
    /// Verdict per target index for the last scored lap.
    private(set) var verdicts: [Int: Verdict] = [:]
    /// Measure under the playhead, for the position readout.
    private(set) var currentMeasure = 1
    private(set) var sungReadout: (name: String, cents: Double, onTarget: Bool)?

    /// Notes of the loop window for every part, sorted by start.
    @ObservationIgnored private(set) var lane: [LaneNote] = []
    /// Length of the loop window in seconds.
    @ObservationIgnored private(set) var windowSeconds = 0.0
    @ObservationIgnored private(set) var windowStartBeat = 0.0

    /// Where the singer is in the score, in beats from its start.
    var heardBeat: Double {
        guard windowSeconds > 0 else { return windowStartBeat }
        let heard = max(0, heardTime)
        let local = loops ? heard.truncatingRemainder(dividingBy: windowSeconds) : min(heard, windowSeconds)
        return windowStartBeat + local / secondsPerBeat
    }

    /// Result of the last scored lap for a note of the singer's part, by note index.
    var noteVerdicts: [Int: Verdict] {
        var result: [Int: Verdict] = [:]
        for note in lane where note.targetIndex >= 0 {
            if let verdict = verdicts[note.targetIndex] { result[note.noteIndex] = verdict }
        }
        return result
    }
    /// Lowest and highest MIDI in the selected part (drives the lane's pitch range).
    @ObservationIgnored private(set) var midiRange = 48...72
    @ObservationIgnored private(set) var samples: [SungSample] = []

    @ObservationIgnored private var originFrame: Int64 = 0
    @ObservationIgnored private var pausedAt = 0.0
    @ObservationIgnored private var scheduledUntil = 0.0
    @ObservationIgnored private var lapsScored = 0
    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var recent: [Double] = []
    @ObservationIgnored private var smoother = OneEuroFilter()
    @ObservationIgnored private var lastSampleTime = 0.0
    private let defaults = UserDefaults.standard

    private static let lookahead = 0.3
    private static let startDelay = 0.1
    private static let partVelocity: Float = 0.5

    init(audio: AudioEngine, library: Library) {
        self.audio = audio
        self.library = library
        strict = defaults.bool(forKey: "practice.strict")
        responseMs = defaults.object(forKey: "practice.responseMs") as? Double ?? 65
        syncMs = defaults.object(forKey: "practice.syncMs") as? Double ?? 0
        sampledVoices = defaults.bool(forKey: "practice.sampledVoices")
        recordBalance = defaults.object(forKey: "practice.recordBalance") as? Double ?? 0.5

        #if DEBUG
        // Simulator checks: CHANTERLAB_AUTOPLAY=1 starts playback (and the mic,
        // with CHANTERLAB_TONE) once the first piece has loaded.
        if ProcessInfo.processInfo.environment["CHANTERLAB_AUTOPLAY"] == "1" { autoplay = true }
        // CHANTERLAB_RECORD=<seconds> records that long after autoplay starts.
        if let s = ProcessInfo.processInfo.environment["CHANTERLAB_RECORD"], let seconds = Double(s) {
            autoRecordSeconds = seconds
        }
        #endif
    }

    @ObservationIgnored private var autoplay = false
    @ObservationIgnored private var autoRecordSeconds: Double?

    // MARK: loading

    /// Load the last piece, or the default one, once the catalog is known.
    func loadInitialPiece() async {
        guard piece == nil, !loading else { return }
        let wanted = [defaults.string(forKey: "practice.piece"), Library.preferredFirstPiece, Library.bundledID]
        guard let first = wanted.compactMap({ $0 }).compactMap(library.piece(id:)).first else { return }
        await load(first)
        // No network on first run: fall back to the piece shipped in the app.
        if score == nil, let bundled = library.piece(id: Library.bundledID), bundled != first {
            errorMessage = nil
            await load(bundled)
        }
    }

    func load(_ piece: Piece) async {
        stop()
        finishRecording()
        loading = true
        defer { loading = false }
        do {
            let xml = try await library.musicXML(for: piece)
            let score = try Score.parse(xml: xml, verse: 1)
            guard score.parts.contains(where: { !$0.notes.isEmpty }) else {
                throw Score.ParseFailure(message: "it has no notes")
            }
            self.xml = xml
            self.piece = piece
            self.score = score
            scoreRevision += 1
            // A shift or loop chosen for one piece means nothing in the next.
            verse = 1
            transpose = 0
            loopOn = false
            loopFrom = score.firstMeasure
            loopTo = score.lastMeasure
            if voice >= score.parts.count { voice = 0 }
            report = nil; verdicts = [:]; bestPct = nil; status = ""
            rebuildWindow(restart: false)
            defaults.set(piece.id, forKey: "practice.piece")
            if autoplay {
                autoplay = false
                loopOn = ProcessInfo.processInfo.environment["CHANTERLAB_LOOP"] == "1"
                if loopOn { loopTo = min(score.lastMeasure, loopFrom + 1) }
                setMic(true)
                play()
                if let seconds = autoRecordSeconds {
                    toggleRecording()
                    DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
                        self?.finishRecording()
                        if let url = self?.recordingURL { print("CHANTERLAB_RECORDING \(url.path)") }
                    }
                }
            }
        } catch {
            errorMessage = "\(piece.title): \(error.localizedDescription)"
        }
    }

    private func reparse() {
        guard let xml, let parsed = try? Score.parse(xml: xml, verse: verse) else { return }
        score = parsed
        scoreRevision += 1
        rebuildWindow(restart: false)
    }

    /// Jump to a section: loop from its first measure to the one before the next section.
    func select(_ section: ScoreSection) {
        guard let score else { return }
        let next = sections.first { $0.measure > section.measure }
        stop()
        loopFrom = section.measure
        loopTo = max(section.measure, (next?.measure ?? score.lastMeasure + 1) - 1)
        loopOn = true
    }

    /// Loop the measures around a trouble spot.
    func focus(measure: Int) {
        guard let score else { return }
        stop()
        loopFrom = max(score.firstMeasure, measure - 1)
        loopTo = min(score.lastMeasure, measure + 1)
        loopOn = true
    }

    func loopWholePiece() {
        guard let score else { return }
        stop()
        loopOn = false
        loopFrom = score.firstMeasure
        loopTo = score.lastMeasure
    }

    // MARK: window

    private var secondsPerBeat: Double { 60 / bpm }

    private func rebuildWindow(restart: Bool) {
        guard let score else { lane = []; windowSeconds = 0; return }
        let wasPlaying = transport == .playing
        if restart, transport != .stopped { stop() }

        let from = min(loopFrom, loopTo), to = max(loopFrom, loopTo)
        let beats = score.beatRange(fromMeasure: from, toMeasure: to)
        let spb = secondsPerBeat
        var notes: [LaneNote] = []
        for part in score.parts {
            var targetIndex = 0
            for (noteIndex, note) in part.notes.enumerated()
            where note.startBeat >= beats.lowerBound && note.startBeat < beats.upperBound {
                let mine = part.index == voice
                notes.append(LaneNote(part: part.index,
                                      noteIndex: noteIndex,
                                      targetIndex: mine ? targetIndex : -1,
                                      midi: note.midi + transpose,
                                      start: (note.startBeat - beats.lowerBound) * spb,
                                      end: (note.endBeat - beats.lowerBound) * spb,
                                      measure: note.measure,
                                      lyric: note.lyric))
                if mine { targetIndex += 1 }
            }
        }
        lane = notes.sorted { $0.start < $1.start }
        windowSeconds = (beats.upperBound - beats.lowerBound) * spb
        windowStartBeat = beats.lowerBound
        let mine = lane.filter { $0.part == voice }.map(\.midi)
        midiRange = (mine.min() ?? 55)...(mine.max() ?? 67)
        verdicts = [:]
        currentMeasure = from
        if restart, wasPlaying { play() }
    }

    private func rescheduleIfPlaying() {
        guard transport == .playing else { return }
        audio.clearScheduled()
        scheduledUntil = max(scheduledUntil - Self.lookahead, playhead)
    }

    // MARK: clock

    /// Seconds of playback since the transport started, not wrapped by the loop.
    private var playhead: Double {
        guard transport == .playing, audio.sampleRate > 0 else { return pausedAt }
        return Double(Int64(audio.frames) - originFrame) / audio.sampleRate
    }

    /// The playhead as the singer hears it: playback minus output latency.
    var heardTime: Double {
        guard transport == .playing else { return pausedAt }
        return playhead - audio.outputLatency - syncMs / 1000
    }

    /// Whether the lane repeats (looping) or runs once.
    var loops: Bool { loopOn && windowSeconds > 0 }

    // MARK: transport

    func play() {
        guard score != nil, windowSeconds > 0, transport != .playing else { return }
        audio.ensureRunning()
        guard audio.sampleRate > 0 else { return }
        if transport == .stopped {
            pausedAt = 0
            samples.removeAll()
            lapsScored = 0
            lap = 0
            verdicts = [:]
            status = ""
        }
        originFrame = Int64(audio.frames) + Int64((Self.startDelay - pausedAt) * audio.sampleRate)
        scheduledUntil = pausedAt
        transport = .playing
        let timer = Timer(timeInterval: 0.04, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        tick()
    }

    func pause() {
        guard transport == .playing else { return }
        let at = max(0, heardTime)
        halt()
        pausedAt = at
        transport = .paused
    }

    func stop() {
        guard transport != .stopped else { return }
        let wasPlaying = transport == .playing
        let at = heardTime
        halt()
        if wasPlaying || !samples.isEmpty { scoreLap(lapsScored, upTo: at) }
        pausedAt = 0
        transport = .stopped
        currentMeasure = min(loopFrom, loopTo)
    }

    private func halt() {
        timer?.invalidate(); timer = nil
        audio.clearScheduled()
    }

    /// The engine was rebuilt on a new clock: playback cannot continue seamlessly.
    func audioClockReset() {
        if transport == .playing { pause() }
    }

    private func tick() {
        guard transport == .playing else { return }
        let now = playhead
        schedule(upTo: now + Self.lookahead)

        let heard = heardTime
        let total = windowSeconds
        if loops {
            // Score a lap once the singer's (response-delayed) samples for it are all in.
            let settled = heard - responseMs / 1000
            while settled >= Double(lapsScored + 1) * total { scoreLap(lapsScored, upTo: nil) }
            lap = max(0, Int(heard / total))
        } else if heard >= total + 0.3 {
            stop()
            return
        }
        let local = loops ? heard.truncatingRemainder(dividingBy: total) : heard
        if let note = lane.last(where: { $0.start <= local }), note.measure != currentMeasure {
            currentMeasure = note.measure
        }
    }

    /// Hand the synth every note starting before `horizon` that it does not have yet.
    private func schedule(upTo horizon: Double) {
        let total = windowSeconds
        let from = scheduledUntil
        guard horizon > from, total > 0 else { return }
        let lastLap = loops ? Int(horizon / total) : 0
        let firstLap = loops ? Int(from / total) : 0
        let rate = audio.sampleRate
        let single = (score?.parts.count ?? 0) <= 1
        for lapIndex in firstLap...lastLap {
            let offset = Double(lapIndex) * total
            for note in lane {
                let start = note.start + offset
                if start < from { continue }
                if start >= horizon { break }
                // The singer's own part is silent unless asked for; a one-part
                // chant has nothing else to play, so there it is the melody.
                if note.part == voice && !hearMine && !single { continue }
                let frame = originFrame + Int64(start * rate)
                guard frame >= 0 else { continue }
                audio.scheduleNote(hz: 440 * pow(2, Double(note.midi - 69) / 12),
                                   velocity: Self.partVelocity,
                                   startFrame: UInt64(frame),
                                   seconds: max(0.05, (note.end - note.start) * 0.95),
                                   voicing: sampledVoices && audio.voicesReady ? 6 : 5)
            }
        }
        scheduledUntil = horizon
    }

    // MARK: mic

    func setMic(_ on: Bool) {
        micOn = on
        if !on { sungReadout = nil; recent.removeAll(); smoother.reset() }
        audio.setMic(on)
    }

    /// The mic could not start (permission or hardware).
    func micFailed() { micOn = false }

    func ingest(_ frames: [PitchFrame]) {
        guard micOn else { return }
        let heard = heardTime
        var latest: Double?
        for (i, frame) in frames.enumerated() {
            // Frames arrive in a burst; spread them back over the time they cover.
            let time = heard - responseMs / 1000 - Double(frames.count - 1 - i) / 60
            guard frame.gateOpen, frame.hz > 0 else {
                recent.removeAll(); smoother.reset()
                if samples.last?.midi != nil { samples.append(SungSample(time: time, midi: nil)) }
                latest = nil
                continue
            }
            // Median of three raw readings drops single-frame octave blips.
            recent.append(Double(frame.hz))
            if recent.count > 3 { recent.removeFirst() }
            let median = recent.sorted()[recent.count / 2]
            let midi = smoother.filter(69 + 12 * log2(median / 440), dt: time - lastSampleTime)
            lastSampleTime = time
            latest = midi
            // While stopped or paused the clock stands still: show, do not record.
            if transport == .playing { samples.append(SungSample(time: time, midi: midi)) }
        }
        // Keep what the lane can still show plus the lap being sung.
        let keepFrom = min(heard - 12, Double(lapsScored) * max(windowSeconds, 0.001) - 1)
        if let first = samples.firstIndex(where: { $0.time >= keepFrom }), first > 64 {
            samples.removeFirst(first)
        }

        guard let midi = latest else { sungReadout = nil; return }
        let name = Self.noteName(midi: Int(midi.rounded()))
        let local = loops ? heard.truncatingRemainder(dividingBy: windowSeconds) : heard
        if let target = lane.first(where: { $0.part == voice && $0.start <= local && local < $0.end }) {
            let octaves = ((midi - Double(target.midi)) / 12).rounded()
            let cents = (midi - 12 * octaves - Double(target.midi)) * 100
            sungReadout = (name, cents, abs(cents) <= 50)
        } else {
            sungReadout = (name, (midi - midi.rounded()) * 100, false)
        }
    }

    // MARK: scoring

    /// Score lap `index`. `upTo` cuts the lap short when the singer stopped early.
    private func scoreLap(_ index: Int, upTo end: Double?) {
        let total = windowSeconds
        guard total > 0 else { return }
        let offset = loops ? Double(index) * total : 0
        let limit = end.map { $0 - offset } ?? total
        lapsScored = index + 1
        let targets = lane
            .filter { $0.part == voice && $0.start < limit }
            .map { LapReport.Target(midi: Double($0.midi), startSec: $0.start, endSec: $0.end, measure: $0.measure) }
        let sung = samples.compactMap { sample -> LapReport.Sample? in
            guard let midi = sample.midi, sample.time >= offset, sample.time < offset + total else { return nil }
            return LapReport.Sample(tSec: sample.time - offset, midi: midi)
        }
        // Nothing sung at all is not a lap of misses; leave the last result showing.
        guard !targets.isEmpty, !sung.isEmpty,
              let result = LapReport.score(targets: targets, samples: sung, strict: strict) else { return }
        report = result
        verdicts = Dictionary(uniqueKeysWithValues: result.details.map { ($0.index, $0.result) })
        bestPct = max(bestPct ?? 0, result.hitPct)
        status = loops
            ? "Lap \(index + 1): \(result.hitPct)% · best \(bestPct ?? result.hitPct)%"
            : "\(result.hit) of \(result.notes) notes in tune (\(result.hitPct)%)"
        appendHistory(result, lap: index + 1)
    }

    private func appendHistory(_ result: LapReport, lap: Int) {
        var history = defaults.array(forKey: "practice.history") as? [[String: Any]] ?? []
        history.append(["ts": Date().timeIntervalSince1970, "piece": piece?.id ?? "", "voice": voice,
                        "from": loopFrom, "to": loopTo, "lap": lap, "strict": strict,
                        "notes": result.notes, "hit": result.hit, "flat": result.flat,
                        "sharp": result.sharp, "missed": result.missed])
        defaults.set(Array(history.suffix(200)), forKey: "practice.history")
    }

    static func noteName(midi: Int) -> String {
        let names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"]
        return "\(names[((midi % 12) + 12) % 12])\(midi / 12 - 1)"
    }
}
