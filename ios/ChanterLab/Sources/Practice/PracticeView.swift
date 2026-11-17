import SwiftUI

/// Score practice: lane, lap report and transport.
struct PracticeView: View {
    @Bindable var model: PracticeModel
    @State private var showLibrary = false
    @State private var showSettings = false
    @AppStorage("practice.view") private var viewMode = ViewMode.split
    @Environment(\.horizontalSizeClass) private var sizeClass
    /// iPad and other wide layouts.
    private var roomy: Bool { sizeClass == .regular }

    enum ViewMode: String, CaseIterable {
        case split, score, lane

        var title: String {
            switch self {
            case .split: return "Score and lane"
            case .score: return "Score only"
            case .lane: return "Lane only"
            }
        }
        var icon: String {
            switch self {
            case .split: return "rectangle.split.1x2"
            case .score: return "music.note.list"
            case .lane: return "waveform.path"
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Theme.rule)
            ZStack {
                VStack(spacing: 0) {
                    if viewMode != .lane {
                        ScoreView(model: model)
                    }
                    if viewMode == .split { Divider().overlay(Theme.rule) }
                    if viewMode != .score {
                        LaneView(model: model)
                            .frame(maxHeight: viewMode == .split ? (roomy ? 300 : 190) : .infinity)
                    }
                }
                if model.loading { ProgressView().controlSize(.large).tint(.white) }
                if model.score == nil, !model.loading {
                    ContentUnavailableView("No piece loaded", systemImage: "music.note.list",
                                           description: Text("Choose a piece from the library."))
                }
            }
            if model.report != nil { ReportStrip(model: model) }
            Divider().overlay(Theme.rule)
            voices
            transport
        }
        .background(Theme.background.ignoresSafeArea())
        .sheet(isPresented: $showLibrary) { LibraryView(model: model) }
        .sheet(isPresented: $showSettings) {
            PracticeSettings(model: model).presentationDetents([.medium, .large])
        }
        .alert("ChanterLab", isPresented: Binding(get: { model.errorMessage != nil },
                                                  set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
        .task {
            await model.library.loadCatalog()
            await model.loadInitialPiece()
        }
    }

    // MARK: header

    private var header: some View {
        HStack(spacing: 12) {
            Button { showLibrary = true } label: {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Text(model.piece?.title ?? "Library").font(.headline).lineLimit(1)
                        Image(systemName: "chevron.down").font(.caption.weight(.bold))
                    }
                    Text(model.piece?.composer ?? "Choose a piece").font(.caption).foregroundStyle(Theme.dim).lineLimit(1)
                }
                .foregroundStyle(.white)
            }
            .buttonStyle(.plain)

            Spacer(minLength: 4)

            if let sung = model.sungReadout {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text(sung.name).font(.system(size: 20, weight: .bold, design: .rounded))
                    Text(String(format: "%+.0f¢", sung.cents))
                        .font(.system(size: 12, weight: .semibold, design: .rounded)).monospacedDigit()
                    if sung.onTarget { Image(systemName: "checkmark").font(.caption.weight(.bold)) }
                }
                .foregroundStyle(sung.onTarget ? Theme.gold : .white)
            }

            if !model.sections.isEmpty {
                Menu {
                    ForEach(model.sections) { section in
                        Button("\(section.title)  ·  m \(section.measure)") { model.select(section) }
                    }
                    Divider()
                    Button("Whole piece") { model.loopWholePiece() }
                } label: {
                    Image(systemName: "list.bullet.indent").font(.title3).foregroundStyle(.white)
                }
                .accessibilityLabel("Sections")
            }
            Menu {
                Picker("View", selection: $viewMode) {
                    ForEach(ViewMode.allCases, id: \.self) { Label($0.title, systemImage: $0.icon).tag($0) }
                }
            } label: {
                Image(systemName: viewMode.icon).font(.title3).foregroundStyle(.white)
            }
            .accessibilityLabel("View")
            Button { showSettings = true } label: {
                Image(systemName: "slider.horizontal.3").font(.title3).foregroundStyle(.white)
            }
            .accessibilityLabel("Practice settings")
        }
        .padding(.horizontal, 14)
        .frame(height: 60)
    }

    // MARK: voices

    private var voices: some View {
        HStack(spacing: 8) {
            if let score = model.score, score.parts.count > 1 {
                Text("I sing").font(.caption).foregroundStyle(Theme.dim)
                ForEach(score.parts) { part in
                    let selected = part.index == model.voice
                    Button { model.voice = part.index } label: {
                        // Full names where there is room; S A T B on a phone.
                        Text(part.voiceKey.count > 2 ? "Part \(part.index + 1)" : roomy ? part.voiceName : part.voiceKey)
                            .font(.system(size: 13, weight: .semibold))
                            .lineLimit(1)
                            .padding(.horizontal, 10)
                            .frame(height: 30)
                            .foregroundStyle(selected ? Color.black : Color.white)
                            .background(selected ? Theme.gold : Theme.key, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
            RecordControls(model: model)
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .background(Theme.panel)
    }

    // MARK: transport

    private var transport: some View {
        HStack(spacing: 10) {
            Button {
                model.transport == .playing ? model.pause() : model.play()
            } label: {
                Image(systemName: model.transport == .playing ? "pause.fill" : "play.fill")
                    .font(.system(size: 22, weight: .bold))
                    .frame(width: 64, height: 46)
                    .foregroundStyle(.black)
                    .background(Theme.gold, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(model.score == nil)
            .accessibilityLabel(model.transport == .playing ? "Pause" : "Play")

            Button { model.stop() } label: {
                Image(systemName: "stop.fill")
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 46, height: 46)
                    .foregroundStyle(.white)
                    .background(Theme.key, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(model.transport == .stopped)
            .accessibilityLabel("Stop")

            VStack(alignment: .leading, spacing: 2) {
                Text("m \(model.currentMeasure)").font(.system(size: 15, weight: .semibold, design: .rounded)).monospacedDigit()
                Text(model.loopOn ? "loop \(model.loopFrom)–\(model.loopTo)" : "\(Int(model.bpm)) bpm")
                    .font(.caption2).foregroundStyle(Theme.dim).monospacedDigit()
            }
            .foregroundStyle(.white)
            .frame(minWidth: 64, alignment: .leading)

            Spacer(minLength: 0)

            Button { model.loopOn.toggle() } label: {
                Image(systemName: "repeat")
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 46, height: 46)
                    .foregroundStyle(model.loopOn ? Color.black : Color.white)
                    .background(model.loopOn ? Theme.gold : Theme.key, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Loop")

            Button { model.setMic(!model.micOn) } label: {
                Image(systemName: model.micOn ? "mic.fill" : "mic")
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 46, height: 46)
                    .foregroundStyle(model.micOn ? Color.black : Color.white)
                    .background(model.micOn ? Theme.gold : Theme.key, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(model.micOn ? "Turn microphone off" : "Turn microphone on")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Theme.panel)
    }
}

/// Record button with a running clock, and a share button for the last take.
private struct RecordControls: View {
    let model: PracticeModel

    var body: some View {
        HStack(spacing: 8) {
            if let started = model.recordingStarted {
                TimelineView(.periodic(from: started, by: 1)) { context in
                    let seconds = max(0, Int(context.date.timeIntervalSince(started)))
                    Text(String(format: "%d:%02d", seconds / 60, seconds % 60))
                        .font(.system(size: 13, weight: .semibold, design: .rounded)).monospacedDigit()
                        .foregroundStyle(.red)
                }
            } else if let url = model.recordingURL {
                ShareLink(item: url) {
                    Image(systemName: "square.and.arrow.up")
                        .font(.system(size: 15, weight: .semibold))
                        .frame(width: 34, height: 30)
                        .foregroundStyle(.white)
                        .background(Theme.key, in: Capsule())
                }
                .accessibilityLabel("Share recording")
            }
            Button { model.toggleRecording() } label: {
                Image(systemName: model.recording ? "stop.circle.fill" : "record.circle")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(model.recording ? Color.red : Color.white)
                    .frame(width: 34, height: 30)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(model.recording ? "Stop recording" : "Record")
        }
    }
}

/// Result of the last lap, with the measures that most need work.
private struct ReportStrip: View {
    let model: PracticeModel

    var body: some View {
        if let report = model.report {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.status).font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                    HStack(spacing: 8) {
                        count(report.hit, "in tune", .hit)
                        count(report.flat, "flat", .flat)
                        count(report.sharp, "sharp", .sharp)
                        count(report.missed, "missed", .missed)
                    }
                }
                Spacer(minLength: 4)
                ForEach(report.worst) { spot in
                    Button { model.focus(measure: spot.measure) } label: {
                        Text("m \(spot.measure)")
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            .padding(.horizontal, 8)
                            .frame(height: 28)
                            .foregroundStyle(.white)
                            .background(Theme.key, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Practise measure \(spot.measure)")
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(Theme.panel)
        }
    }

    private func count(_ n: Int, _ label: String, _ verdict: Verdict) -> some View {
        HStack(spacing: 3) {
            Circle().fill(LaneView.verdictColors[verdict] ?? .gray).frame(width: 7, height: 7)
            Text("\(n) \(label)").font(.caption2).foregroundStyle(Theme.dim).monospacedDigit()
        }
    }
}

/// Tempo, loop, key and timing settings for practice.
struct PracticeSettings: View {
    @Bindable var model: PracticeModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Tempo and key") {
                    LabeledContent("Tempo") {
                        Stepper("\(Int(model.bpm)) bpm", value: $model.bpm, in: 30...160, step: 2).monospacedDigit()
                    }
                    LabeledContent("Transpose") {
                        Stepper(model.transpose == 0 ? "As written" : String(format: "%+d semitones", model.transpose),
                                value: $model.transpose, in: -12...12)
                    }
                    if let score = model.score, score.maxVerse > 1 {
                        Picker("Verse", selection: $model.verse) {
                            ForEach(1...score.maxVerse, id: \.self) { Text("Verse \($0)").tag($0) }
                        }
                    }
                }
                if let score = model.score {
                    Section("Loop") {
                        Toggle("Repeat", isOn: $model.loopOn)
                        Stepper("From measure \(model.loopFrom)", value: $model.loopFrom,
                                in: score.firstMeasure...max(score.firstMeasure, model.loopTo))
                        Stepper("To measure \(model.loopTo)", value: $model.loopTo,
                                in: min(model.loopFrom, score.lastMeasure)...score.lastMeasure)
                        Button("Whole piece") { model.loopWholePiece() }
                    }
                }
                Section {
                    Picker("Accompaniment", selection: $model.sampledVoices) {
                        Text("Synth").tag(false)
                        Text("Voices").tag(true)
                    }
                    Toggle("Also play my part", isOn: $model.hearMine)
                    Picker("Scoring", selection: $model.strict) {
                        Text("Relaxed (±50¢)").tag(false)
                        Text("Strict (±35¢)").tag(true)
                    }
                    Toggle("Colour notes by result", isOn: $model.showVerdicts)
                } header: {
                    Text("Sound and scoring")
                }
                Section {
                    LabeledContent("Mix") {
                        HStack {
                            Text("Music").font(.caption).foregroundStyle(.secondary)
                            Slider(value: $model.recordBalance, in: 0...1)
                            Text("Voice").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                } header: {
                    Text("Recording")
                } footer: {
                    Text("Sets how loud the accompaniment and your voice are in the recorded file. It does not change what you hear.")
                }
                Section {
                    LabeledContent("Voice response") {
                        Stepper("\(Int(model.responseMs)) ms", value: $model.responseMs, in: 0...400, step: 5).monospacedDigit()
                    }
                    LabeledContent("Playback sync") {
                        Stepper("\(Int(model.syncMs)) ms", value: $model.syncMs, in: -100...300, step: 5).monospacedDigit()
                    }
                } header: {
                    Text("Timing")
                } footer: {
                    Text("If your trace lands late on the bars although you sang on time, raise Voice response. If the bars pass the line before you hear them, raise Playback sync.")
                }
            }
            .navigationTitle("Practice")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .preferredColorScheme(.dark)
    }
}

/// The piece catalog, searchable and grouped by service.
struct LibraryView: View {
    let model: PracticeModel
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var tone: Int?
    @State private var expanded: Set<String> = []

    /// Huge groups start collapsed; a search opens everything.
    private static let collapsedByDefault: Set<String> = ["Menaion", "Theotokia"]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            toneChip(nil, "All tones")
                            ForEach(1...8, id: \.self) { toneChip($0, "Tone \($0)") }
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 6, leading: 14, bottom: 6, trailing: 0))
                }
                if let error = model.library.catalogError {
                    Section {
                        Text(error).font(.footnote).foregroundStyle(.secondary)
                        Button("Try again") { Task { await model.library.loadCatalog() } }
                    }
                }
                ForEach(model.library.groups(query: query, tone: tone), id: \.name) { group in
                    let open = !query.isEmpty || tone != nil || expanded.contains(group.name)
                        || !Self.collapsedByDefault.contains(group.name) && !expanded.contains("-" + group.name)
                    Section {
                        if open {
                            ForEach(group.pieces) { piece in row(piece) }
                        }
                    } header: {
                        Button {
                            // Track both directions: opening a collapsed group, closing an open one.
                            if Self.collapsedByDefault.contains(group.name) {
                                expanded.formSymmetricDifference([group.name])
                            } else {
                                expanded.formSymmetricDifference(["-" + group.name])
                            }
                        } label: {
                            HStack {
                                Text(group.name)
                                Text("\(group.pieces.count)").foregroundStyle(.secondary)
                                Spacer()
                                Image(systemName: open ? "chevron.down" : "chevron.right").font(.caption)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Title, composer, tone")
            .overlay {
                if model.library.loadingCatalog, model.library.pieces.count < 10 { ProgressView() }
            }
            .navigationTitle("Library")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
        .preferredColorScheme(.dark)
    }

    private func toneChip(_ value: Int?, _ title: String) -> some View {
        Button { tone = value } label: {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .padding(.horizontal, 10)
                .frame(height: 30)
                .foregroundStyle(tone == value ? Color.black : Color.white)
                .background(tone == value ? Theme.gold : Theme.key, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func row(_ piece: Piece) -> some View {
        Button {
            dismiss()
            Task { await model.load(piece) }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(piece.title).font(.body).foregroundStyle(.white).lineLimit(2)
                    Text([piece.composer, piece.arrangement, piece.sub].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                if piece.id == model.piece?.id {
                    Image(systemName: "checkmark").foregroundStyle(Theme.gold)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
