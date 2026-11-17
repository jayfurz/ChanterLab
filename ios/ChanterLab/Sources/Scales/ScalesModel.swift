import Foundation
import Observation

/// A scale the user can load onto the ladder.
struct ScalePreset: Identifiable, Hashable {
    let label: String
    /// Rust genus name, or "Custom" with `intervals`.
    let genus: String
    let degree: String
    var intervals: [Int] = []

    var id: String { label }
}

enum Tradition: String, CaseIterable, Identifiable {
    case byzantine = "Byzantine"
    case hindustani = "Hindustani"

    var id: String { rawValue }

    /// Same lists, same order, as `BYZANTINE_PRESETS` / `RAGA_PRESETS` in the web app.
    var presets: [ScalePreset] {
        switch self {
        case .byzantine:
            return [
                ScalePreset(label: "Diatonic", genus: "Diatonic", degree: "Ni"),
                ScalePreset(label: "Hard Chromatic", genus: "HardChromatic", degree: "Pa"),
                ScalePreset(label: "Soft Chromatic", genus: "SoftChromatic", degree: "Ni"),
                ScalePreset(label: "Western", genus: "Western", degree: "Ni"),
                ScalePreset(label: "Chromatic 12-ET", genus: "Chromatic12", degree: "Ni"),
                ScalePreset(label: "Chromatic 24-ET", genus: "Chromatic24", degree: "Ni"),
            ]
        case .hindustani:
            // 12-ET-snapped thaats on the 72-moria grid; Sa sits on the reference Ni.
            return [
                ("Bilawal", [12, 12, 6, 12, 12, 12, 6]),
                ("Yaman", [12, 12, 12, 6, 12, 12, 6]),
                ("Kafi", [12, 6, 12, 12, 12, 6, 12]),
                ("Bhairavi", [6, 12, 12, 12, 6, 12, 12]),
                ("Bhairav", [6, 18, 6, 12, 6, 18, 6]),
                ("Todi", [6, 12, 18, 6, 6, 18, 6]),
            ].map { ScalePreset(label: $0.0, genus: "Custom", degree: "Ni", intervals: $0.1) }
        }
    }

    /// Display name for an engine degree. The engine always speaks Byzantine
    /// names; sargam reuses Ni/Pa/Ga for different degrees, so this mapping
    /// must only ever be applied on the way to the screen.
    func label(forDegree degree: String) -> String {
        guard self == .hindustani else { return degree }
        return ["Ni": "Sa", "Pa": "Re", "Vou": "Ga", "Ga": "Ma", "Di": "Pa", "Ke": "Dha", "Zo": "Ni"][degree] ?? degree
    }
}

let voicingNames = ["Sine", "Organ", "Reed", "Flute", "String"]

/// What the singer is doing right now, relative to the ladder.
struct SungPitch: Equatable {
    /// Continuous position on the moria axis.
    var moria: Double
    var hz: Double
    /// Nearest enabled cell and the signed distance to it, in cents.
    var cellMoria: Int
    var cents: Double
}

/// One point of the scrolling pitch trace. `moria == nil` is a gap (silence).
struct TracePoint {
    var time: TimeInterval
    var moria: Double?
}

/// State and behaviour of the scales screen.
@Observable
final class ScalesModel {
    let audio = AudioEngine()
    private var grid: TuningGrid

    private(set) var cells: [Cell] = []
    /// Enabled cells, low to high, by sounding position.
    private(set) var playable: [Cell] = []

    var tradition: Tradition { didSet { if tradition != oldValue { apply(tradition.presets[0]) } } }
    private(set) var presetLabel: String

    var refNiHz: Double { didSet { refNiChanged() } }
    var voicing: Int { didSet { audio.setVoicing(voicing); save() } }
    var volume: Double { didSet { audio.setMaster(Float(volume)); save() } }

    /// Drone: the cell it sits on (nil = off) and its level.
    private(set) var isonMoria: Int?
    var isonVolume: Double { didSet { sendIson(); save() } }

    var metronomeOn = false { didSet { sendMetronome() } }
    var bpm: Double { didSet { sendMetronome(); save() } }
    var beatsPerBar: Int { didSet { sendMetronome(); save() } }

    private(set) var micOn = false
    private(set) var sung: SungPitch?
    private(set) var micLevel: Float = 0
    /// Recent sung pitch, oldest first; read by the scope each frame.
    @ObservationIgnored private(set) var trace: [TracePoint] = []
    static let traceSeconds: TimeInterval = 8

    /// Cells currently held on the keyboard.
    private(set) var held: Set<Int> = []
    var editing = false
    var selectedMoria: Int?
    var errorMessage: String?

    private let defaults = UserDefaults.standard
    @ObservationIgnored private var smoothedMoria: Double?

    init() {
        let d = UserDefaults.standard
        let grid = d.string(forKey: "grid").flatMap(TuningGrid.init(json:)) ?? TuningGrid()
        self.grid = grid
        tradition = Tradition(rawValue: d.string(forKey: "tradition") ?? "") ?? .byzantine
        presetLabel = d.string(forKey: "preset") ?? "Diatonic"
        refNiHz = grid.refNiHz
        voicing = d.object(forKey: "voicing") as? Int ?? 1
        volume = d.object(forKey: "volume") as? Double ?? 0.8
        isonVolume = d.object(forKey: "isonVolume") as? Double ?? 0.35
        bpm = d.object(forKey: "bpm") as? Double ?? 80
        beatsPerBar = d.object(forKey: "beatsPerBar") as? Int ?? 4
        reloadCells()

        audio.onSynthReset = { [weak self] in self?.resendSynthState() }
        audio.onPitch = { [weak self] frames in self?.ingest(frames) }
        audio.onError = { [weak self] message in
            self?.errorMessage = message
            self?.micOn = false
        }

        #if DEBUG
        // Simulator checks: CHANTERLAB_PRESET=<label> loads a scale, CHANTERLAB_EDIT=1
        // opens edit mode, CHANTERLAB_AUTOMIC=1 turns the mic on at launch.
        let env = ProcessInfo.processInfo.environment
        if let label = env["CHANTERLAB_PRESET"],
           let preset = Tradition.allCases.flatMap(\.presets).first(where: { $0.label == label }) {
            apply(preset)
        }
        if env["CHANTERLAB_EDIT"] == "1" {
            editing = true
            selectedMoria = 12
        }
        if ProcessInfo.processInfo.environment["CHANTERLAB_AUTOMIC"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in self?.setMic(true) }
        }
        #endif
    }

    // MARK: grid

    private func reloadCells() {
        cells = grid.cells
        playable = cells.filter(\.enabled).sorted { $0.effectiveMoria < $1.effectiveMoria }
        if let ison = isonMoria, !playable.contains(where: { $0.moria == ison }) { isonMoria = nil }
        if let sel = selectedMoria, !cells.contains(where: { $0.moria == sel }) { selectedMoria = nil }
    }

    /// The grid's pitches moved: retune whatever is sounding, then persist.
    private func gridChanged() {
        reloadCells()
        for moria in held {
            if let cell = cell(at: moria), cell.enabled {
                audio.retune(id: moria, hz: hz(of: cell))
            } else {
                audio.noteOff(id: moria)
                held.remove(moria)
            }
        }
        sendIson()
        save()
    }

    func cell(at moria: Int) -> Cell? { cells.first { $0.moria == moria } }
    func hz(of cell: Cell) -> Double { grid.hz(moria: cell.effectiveMoria) }

    func apply(_ preset: ScalePreset) {
        // A preset replaces the whole ladder: start from a clean grid so earlier
        // pthorae and accidentals do not leak into the new scale.
        let fresh = TuningGrid()
        fresh.refNiHz = refNiHz
        let ok = preset.genus == "Custom"
            ? fresh.applyCustomGenus(at: 0, degree: preset.degree, name: "Raga \(preset.label)",
                                     intervals: preset.intervals, root: "Ni")
            : fresh.applyPthora(at: 0, genus: preset.genus, degree: preset.degree)
        guard ok else {
            errorMessage = "Could not load \(preset.label)."
            return
        }
        grid = fresh
        presetLabel = preset.label
        selectedMoria = nil
        gridChanged()
    }

    /// Change the genus from `moria` upward (a pthora), keeping the rest of the ladder.
    func applyPthora(at moria: Int, genus: String, degree: String) {
        if grid.applyPthora(at: moria, genus: genus, degree: degree) { gridChanged() }
    }

    func shiftAccidental(at moria: Int, by delta: Int) {
        guard let cell = cell(at: moria) else { return }
        grid.setAccidental(at: moria, cell.accidental + delta)
        gridChanged()
    }

    func toggleEnabled(at moria: Int) {
        grid.toggleCell(at: moria)
        gridChanged()
    }

    func resetCell(at moria: Int) {
        grid.clearOverride(at: moria)
        gridChanged()
    }

    private func refNiChanged() {
        guard refNiHz.isFinite, refNiHz > 0, refNiHz != grid.refNiHz else { return }
        grid.refNiHz = refNiHz
        gridChanged()
    }

    // MARK: playing

    func press(_ cell: Cell) {
        guard cell.enabled, !held.contains(cell.moria) else { return }
        held.insert(cell.moria)
        audio.noteOn(id: cell.moria, hz: hz(of: cell))
    }

    func release(_ cell: Cell) {
        guard held.remove(cell.moria) != nil else { return }
        audio.noteOff(id: cell.moria)
    }

    func toggleIson(at moria: Int) {
        isonMoria = isonMoria == moria ? nil : moria
        sendIson()
    }

    private func sendIson() {
        if let moria = isonMoria, let cell = cell(at: moria), cell.enabled {
            audio.setIson(hz: hz(of: cell), volume: Float(isonVolume))
        } else {
            audio.setIson(hz: 0, volume: 0)
        }
    }

    private func sendMetronome() {
        audio.setMetronome(bpm: metronomeOn ? bpm : 0, volume: 0.7, beatsPerBar: beatsPerBar)
    }

    private func resendSynthState() {
        audio.setVoicing(voicing)
        audio.setMaster(Float(volume))
        sendIson()
        sendMetronome()
        held.removeAll()
    }

    /// Silence everything this screen is producing (another screen takes over audio).
    func quiet() {
        if micOn { setMic(false) }
        metronomeOn = false
        isonMoria = nil
        sendIson()
        for moria in held { audio.noteOff(id: moria) }
        held.removeAll()
    }

    /// True when nothing would be audible, so the engine can stop in the background.
    var idle: Bool { !micOn && isonMoria == nil && !metronomeOn && held.isEmpty }

    // MARK: mic

    func setMic(_ on: Bool) {
        micOn = on
        if !on {
            sung = nil
            micLevel = 0
            smoothedMoria = nil
        }
        audio.setMic(on)
    }

    private func ingest(_ frames: [PitchFrame]) {
        guard micOn else { return }
        let now = Date.timeIntervalSinceReferenceDate
        for (i, frame) in frames.enumerated() {
            // Frames arrive in a burst; spread them back over the time they cover.
            let t = now - Double(frames.count - 1 - i) / 60
            micLevel = frame.level
            guard frame.gateOpen, frame.hz > 0 else {
                smoothedMoria = nil
                if trace.last?.moria != nil { trace.append(TracePoint(time: t, moria: nil)) }
                continue
            }
            let raw = 72 * log2(Double(frame.hz) / refNiHz)
            // Light smoothing within a note; a jump of more than a semitone is a
            // new note and is taken as-is.
            if let prev = smoothedMoria, abs(raw - prev) < 6 {
                smoothedMoria = prev + 0.35 * (raw - prev)
            } else {
                smoothedMoria = raw
            }
            trace.append(TracePoint(time: t, moria: smoothedMoria))
        }
        let cutoff = now - Self.traceSeconds - 0.5
        if let first = trace.firstIndex(where: { $0.time >= cutoff }), first > 0 {
            trace.removeFirst(first)
        }

        guard let moria = smoothedMoria,
              let nearest = playable.min(by: { abs(Double($0.effectiveMoria) - moria) < abs(Double($1.effectiveMoria) - moria) })
        else {
            if sung != nil { sung = nil }
            return
        }
        sung = SungPitch(moria: moria,
                         hz: refNiHz * pow(2, moria / 72),
                         cellMoria: nearest.moria,
                         cents: (moria - Double(nearest.effectiveMoria)) * 1200 / 72)
    }

    // MARK: labels

    func label(for cell: Cell) -> String {
        if let degree = cell.degree { return tradition.label(forDegree: degree) }
        if let step = cell.etStep { return step == 0 ? tradition.label(forDegree: "Ni") : String(step) }
        return "·"
    }

    /// Nearest equal-tempered note name for a frequency, e.g. "C3 +12".
    static func noteName(hz: Double) -> String {
        guard hz > 0 else { return "" }
        let midi = 69 + 12 * log2(hz / 440)
        let nearest = Int(midi.rounded())
        let cents = Int(((midi - Double(nearest)) * 100).rounded())
        let names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"]
        let name = "\(names[((nearest % 12) + 12) % 12])\(nearest / 12 - 1)"
        return cents == 0 ? name : "\(name) \(cents > 0 ? "+" : "−")\(abs(cents))"
    }

    // MARK: persistence

    private func save() {
        if let json = grid.json { defaults.set(json, forKey: "grid") }
        defaults.set(tradition.rawValue, forKey: "tradition")
        defaults.set(presetLabel, forKey: "preset")
        defaults.set(voicing, forKey: "voicing")
        defaults.set(volume, forKey: "volume")
        defaults.set(isonVolume, forKey: "isonVolume")
        defaults.set(bpm, forKey: "bpm")
        defaults.set(beatsPerBar, forKey: "beatsPerBar")
    }
}
