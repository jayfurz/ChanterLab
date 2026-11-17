import SwiftUI

/// The scales screen: ladder + scope, pitch readout, transport bar.
struct ScalesView: View {
    @Bindable var model: ScalesModel
    @State private var showSettings = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Theme.rule)
            LadderView(model: model)
            if model.editing { CellInspector(model: model) }
            Divider().overlay(Theme.rule)
            controls
        }
        .background(Theme.background.ignoresSafeArea())
        .sheet(isPresented: $showSettings) {
            ScalesSettings(model: model)
                .presentationDetents([.medium, .large])
        }
        .alert("ChanterLab", isPresented: Binding(get: { model.errorMessage != nil },
                                                  set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    // MARK: header

    private var header: some View {
        HStack(spacing: 12) {
            Menu {
                Picker("Tradition", selection: $model.tradition) {
                    ForEach(Tradition.allCases) { Text($0.rawValue).tag($0) }
                }
                Divider()
                ForEach(model.tradition.presets) { preset in
                    Button {
                        model.apply(preset)
                    } label: {
                        if preset.label == model.presetLabel {
                            Label(preset.label, systemImage: "checkmark")
                        } else {
                            Text(preset.label)
                        }
                    }
                }
            } label: {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Text(model.presetLabel).font(.headline).lineLimit(1).minimumScaleFactor(0.7)
                        Image(systemName: "chevron.down").font(.caption.weight(.bold))
                    }
                    Text("\(model.tradition.label(forDegree: "Ni")) = \(ScalesModel.noteName(hz: model.refNiHz))")
                        .font(.caption)
                        .foregroundStyle(Theme.dim)
                }
                .foregroundStyle(.white)
            }

            Spacer(minLength: 8)
            PitchReadout(model: model)
            Spacer(minLength: 8)

            Button {
                model.editing.toggle()
                if !model.editing { model.selectedMoria = nil }
            } label: {
                Image(systemName: model.editing ? "pencil.circle.fill" : "pencil.circle")
                    .font(.title2)
                    .foregroundStyle(model.editing ? Theme.gold : .white)
            }
            .accessibilityLabel("Edit scale")

            Button { showSettings = true } label: {
                Image(systemName: "slider.horizontal.3").font(.title3).foregroundStyle(.white)
            }
            .accessibilityLabel("Settings")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .frame(height: 60)
    }

    // MARK: bottom bar

    private var controls: some View {
        HStack(spacing: 10) {
            BarButton(title: model.micOn ? "Mic on" : "Mic", icon: model.micOn ? "mic.fill" : "mic",
                      active: model.micOn) {
                model.setMic(!model.micOn)
            }
            BarButton(title: "Drone", icon: "waveform", active: model.isonMoria != nil) {
                // Off → on at the reference Ni; edit mode picks any other key.
                model.toggleIson(at: model.isonMoria ?? 0)
            }
            BarButton(title: "\(Int(model.bpm))", icon: "metronome", active: model.metronomeOn) {
                model.metronomeOn.toggle()
            }
            Slider(value: $model.volume, in: 0...1) {
                Text("Volume")
            } minimumValueLabel: {
                Image(systemName: "speaker.fill").font(.caption).foregroundStyle(Theme.dim)
            } maximumValueLabel: {
                Image(systemName: "speaker.wave.3.fill").font(.caption).foregroundStyle(Theme.dim)
            }
            .tint(Theme.gold)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Theme.panel)
    }
}

private struct BarButton: View {
    let title: String
    let icon: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                Image(systemName: icon).font(.system(size: 17, weight: .semibold))
                Text(title).font(.system(size: 10, weight: .medium)).monospacedDigit()
            }
            .frame(width: 54, height: 44)
            .foregroundStyle(active ? Color.black : Color.white)
            .background(active ? Theme.gold : Theme.key, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

/// Note name, cents and a tuning needle for the sung pitch.
private struct PitchReadout: View {
    let model: ScalesModel

    var body: some View {
        if let sung = model.sung, let cell = model.cell(at: sung.cellMoria) {
            let color = Theme.tuning(cents: sung.cents)
            VStack(spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(model.label(for: cell))
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                    Text(String(format: "%+.0f¢", sung.cents))
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(color)
                }
                GeometryReader { geo in
                    let half = geo.size.width / 2
                    ZStack {
                        Capsule().fill(Theme.rule)
                        Rectangle().fill(Theme.dim).frame(width: 1)
                        Circle().fill(color).frame(width: 8, height: 8)
                            .offset(x: half * CGFloat(max(-1, min(1, sung.cents / 50))))
                    }
                }
                .frame(width: 96, height: 8)
            }
            .foregroundStyle(.white)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text("\(model.label(for: cell)), \(Int(sung.cents)) cents"))
        } else if model.micOn {
            VStack(spacing: 4) {
                Text("Sing").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.dim)
                // Input level, so a silent readout is distinguishable from a dead mic.
                Capsule().fill(Theme.rule).frame(width: 96, height: 4)
                    .overlay(alignment: .leading) {
                        Capsule().fill(Theme.trace)
                            .frame(width: 96 * CGFloat(min(1, model.micLevel * 6)), height: 4)
                    }
            }
        }
    }
}

/// Edit-mode strip for the selected key.
private struct CellInspector: View {
    let model: ScalesModel

    private let genera = [("Diatonic", "Diatonic"), ("Hard Chromatic", "HardChromatic"),
                          ("Soft Chromatic", "SoftChromatic"), ("Western", "Western")]
    private let degrees = ["Ni", "Pa", "Vou", "Ga", "Di", "Ke", "Zo"]
    private let chroai = [("Zygos", "Zygos"), ("Kliton", "Kliton"), ("Spathi", "Spathi"),
                          ("Enharmonic (ajem)", "Enharmonic"), ("General sharp", "DiesisGeniki"),
                          ("General flat", "YfesisGeniki")]

    var body: some View {
        Group {
            if let moria = model.selectedMoria, let cell = model.cell(at: moria) {
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(cell.enabled ? model.label(for: cell) : "Off").font(.headline)
                        Text(String(format: "%.1f Hz", model.hz(of: cell)))
                            .font(.caption2).monospacedDigit().foregroundStyle(Theme.dim)
                    }
                    .frame(minWidth: 58, alignment: .leading)

                    chip("−2") { model.shiftAccidental(at: moria, by: -2) }
                    chip("+2") { model.shiftAccidental(at: moria, by: 2) }
                    chip(cell.enabled ? "Disable" : "Enable") { model.toggleEnabled(at: moria) }
                    if cell.enabled {
                        chip("Drone", active: model.isonMoria == moria) { model.toggleIson(at: moria) }
                    }
                    Menu {
                        if model.tradition == .byzantine {
                            ForEach(genera, id: \.1) { name, genus in
                                Menu(name) {
                                    ForEach(degrees, id: \.self) { degree in
                                        Button("as \(degree)") {
                                            model.applyPthora(at: moria, genus: genus, degree: degree)
                                        }
                                    }
                                }
                            }
                            if cell.degree != nil {
                                Menu("Chroa") {
                                    ForEach(chroai, id: \.1) { name, shading in
                                        Button(name) { model.applyShading(shading, at: moria) }
                                    }
                                    Divider()
                                    Button("Clear chroa") { model.applyShading("", at: moria) }
                                }
                            }
                            Divider()
                        }
                        Button("Reset this key") { model.resetCell(at: moria) }
                    } label: {
                        Image(systemName: "ellipsis.circle").font(.title3).foregroundStyle(.white)
                    }
                    Spacer(minLength: 0)
                }
            } else {
                Text("Tap a key to retune it, change the scale from there, or put the drone on it.")
                    .font(.footnote)
                    .foregroundStyle(Theme.dim)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(Theme.panel)
    }

    private func chip(_ title: String, active: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .padding(.horizontal, 10)
                .frame(height: 32)
                .foregroundStyle(active ? Color.black : Color.white)
                .background(active ? Theme.gold : Theme.key, in: Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// Reference pitch, sound and metronome settings.
struct ScalesSettings: View {
    @Bindable var model: ScalesModel
    @Environment(\.dismiss) private var dismiss

    /// Common reference pitches for the base note, A2 … A3.
    private let references: [(String, Double)] = (45...57).map { midi in
        let hz = 440 * pow(2, Double(midi - 69) / 12)
        return (ScalesModel.noteName(hz: hz), hz)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Reference \(model.tradition.label(forDegree: "Ni"))") {
                    Picker("Note", selection: Binding(
                        get: { references.min { abs($0.1 - model.refNiHz) < abs($1.1 - model.refNiHz) }?.1 ?? model.refNiHz },
                        set: { model.refNiHz = $0 })) {
                        ForEach(references, id: \.1) { name, hz in Text(name).tag(hz) }
                    }
                    Stepper(value: $model.refNiHz, in: 60...400, step: 0.5) {
                        Text(String(format: "%.1f Hz", model.refNiHz)).monospacedDigit()
                    }
                }
                Section("Sound") {
                    Picker("Voice", selection: $model.voicing) {
                        ForEach(voicingNames.indices, id: \.self) { Text(voicingNames[$0]).tag($0) }
                    }
                    LabeledContent("Drone level") { Slider(value: $model.isonVolume, in: 0.05...1) }
                }
                Section("Metronome") {
                    Stepper(value: $model.bpm, in: 30...240, step: 1) {
                        Text("\(Int(model.bpm)) beats per minute").monospacedDigit()
                    }
                    Picker("Accent every", selection: $model.beatsPerBar) {
                        Text("No accent").tag(0)
                        ForEach(2...7, id: \.self) { Text("\($0) beats").tag($0) }
                    }
                }
                Section {
                    Button("Reset scale to \(model.presetLabel)") {
                        if let preset = model.tradition.presets.first(where: { $0.label == model.presetLabel }) {
                            model.apply(preset)
                        }
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .preferredColorScheme(.dark)
    }
}
