import SwiftUI

/// The scrolling practice lane: the singer's notes as gold bars with their
/// words, the other parts faintly behind, and the sung pitch traced over them.
/// Time runs left to right past a fixed "now" line; pitch is vertical.
struct LaneView: View {
    let model: PracticeModel

    @Environment(\.horizontalSizeClass) private var sizeClass
    /// Scroll speed: a little faster on wide screens so notes are not cramped.
    private var pointsPerSecond: CGFloat { sizeClass == .regular ? 96 : 68 }
    private let nowFraction: CGFloat = 0.33

    static let verdictColors: [Verdict: Color] = [
        .hit: Color(red: 0.31, green: 0.62, blue: 0.18),
        .flat: Color(red: 0.18, green: 0.50, blue: 0.77),
        .sharp: Color(red: 0.88, green: 0.48, blue: 0.11),
        .missed: Color(red: 0.64, green: 0.31, blue: 0.31),
    ]

    var body: some View {
        TimelineView(.animation(paused: model.transport != .playing && !model.micOn)) { timeline in
            Canvas { context, size in
                // Reading the date ties the canvas to the timeline; without it
                // SwiftUI sees an unchanged view and never redraws.
                _ = timeline.date
                draw(&context, size)
            }
        }
        .background(Theme.background)
        .accessibilityLabel("Practice lane")
    }

    private func draw(_ context: inout GraphicsContext, _ size: CGSize) {
        let total = model.windowSeconds
        guard total > 0 else { return }
        let heard = model.heardTime
        let nowX = size.width * nowFraction

        // Pitch axis: the singer's range plus a margin, at least 14 semitones.
        var low = Double(model.midiRange.lowerBound) - 4, high = Double(model.midiRange.upperBound) + 4
        if high - low < 14 {
            let pad = (14 - (high - low)) / 2
            low -= pad; high += pad
        }
        let lyricBand: CGFloat = 20
        let plot = size.height - lyricBand
        let perSemitone = plot / CGFloat(high - low)
        func y(_ midi: Double) -> CGFloat { plot - CGFloat(midi - low) * perSemitone }
        func x(_ time: Double) -> CGFloat { nowX + CGFloat(time - heard) * pointsPerSecond }

        // Semitone grid, brighter and labelled at each C.
        for midi in Int(low.rounded(.up))...Int(high.rounded(.down)) {
            let isC = ((midi % 12) + 12) % 12 == 0
            var line = Path()
            line.move(to: CGPoint(x: 0, y: y(Double(midi))))
            line.addLine(to: CGPoint(x: size.width, y: y(Double(midi))))
            context.stroke(line, with: .color(.white.opacity(isC ? 0.16 : 0.05)), lineWidth: 1)
            if isC {
                context.draw(Text(PracticeModel.noteName(midi: midi)).font(.system(size: 10)).foregroundStyle(Theme.dim),
                             at: CGPoint(x: 4, y: y(Double(midi)) - 7), anchor: .leading)
            }
        }

        // Which laps are on screen.
        let visibleFrom = heard - Double(nowX / pointsPerSecond)
        let visibleTo = heard + Double((size.width - nowX) / pointsPerSecond)
        let laps: ClosedRange<Int> = model.loops
            ? max(0, Int(visibleFrom / total))...max(0, Int(visibleTo / total))
            : 0...0
        let barHeight = min(14, max(6, perSemitone * 0.8))

        for lap in laps {
            let offset = Double(lap) * total
            if model.loops {
                var end = Path()
                end.move(to: CGPoint(x: x(offset + total), y: 0))
                end.addLine(to: CGPoint(x: x(offset + total), y: plot))
                context.stroke(end, with: .color(.white.opacity(0.25)), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            }
            // Other parts first, so the singer's bars sit on top.
            for mine in [false, true] {
                for note in model.lane where (note.part == model.voice) == mine {
                    let x0 = x(note.start + offset), x1 = x(note.end + offset)
                    if x1 < 0 { continue }
                    if x0 > size.width { break }
                    let rect = CGRect(x: x0, y: y(Double(note.midi)) - barHeight / 2,
                                      width: max(2, x1 - x0 - 1.5), height: barHeight)
                    let bar = Path(roundedRect: rect, cornerRadius: 3)
                    guard mine else {
                        context.fill(bar, with: .color(Color(red: 0.60, green: 0.63, blue: 0.65).opacity(0.22)))
                        continue
                    }
                    let active = x0 <= nowX && nowX < x1 && model.transport == .playing
                    var color = active ? Color(red: 1.0, green: 0.85, blue: 0.37) : Theme.gold
                    // The last scored lap colours the bars already sung.
                    if model.showVerdicts, !active, x1 <= nowX || model.transport != .playing,
                       let verdict = model.verdicts[note.targetIndex], let tint = Self.verdictColors[verdict] {
                        color = tint
                    }
                    if active {
                        context.fill(Path(roundedRect: rect.insetBy(dx: -3, dy: -3), cornerRadius: 5),
                                     with: .color(color.opacity(0.25)))
                    }
                    context.fill(bar, with: .color(color))
                    if let lyric = note.lyric {
                        context.draw(Text(lyric).font(.system(size: sizeClass == .regular ? 14 : 11)).foregroundStyle(active ? .white : Theme.dim),
                                     at: CGPoint(x: x0, y: plot + lyricBand / 2), anchor: .leading)
                    }
                }
            }
        }

        // The sung trace: cyan, gold while it sits on the note being sung.
        var segment = Path()
        var penDown = false
        var segmentOnTarget = false
        func flush() {
            guard penDown else { return }
            context.stroke(segment, with: .color(segmentOnTarget ? Theme.gold : Theme.trace),
                           style: StrokeStyle(lineWidth: segmentOnTarget ? 3 : 2.2, lineCap: .round, lineJoin: .round))
            segment = Path(); penDown = false
        }
        var previousTime = -Double.infinity
        for sample in model.samples {
            guard let midi = sample.midi, sample.time >= visibleFrom - 1 else { flush(); continue }
            let local = model.loops ? sample.time.truncatingRemainder(dividingBy: total) : sample.time
            let target = model.lane.first { $0.part == model.voice && $0.start <= local && local < $0.end }
            var shown = midi
            var onTarget = false
            if let target {
                // Draw the voice in the octave of its target so it lands on the bar.
                shown = midi - 12 * ((midi - Double(target.midi)) / 12).rounded()
                onTarget = abs(shown - Double(target.midi)) <= 0.5
            }
            let point = CGPoint(x: x(sample.time), y: y(min(high, max(low, shown))))
            if !penDown || onTarget != segmentOnTarget || sample.time - previousTime > 0.18 {
                flush()
                segment.move(to: point); penDown = true; segmentOnTarget = onTarget
            } else {
                segment.addLine(to: point)
            }
            previousTime = sample.time
        }
        flush()

        var now = Path()
        now.move(to: CGPoint(x: nowX, y: 0))
        now.addLine(to: CGPoint(x: nowX, y: size.height))
        context.stroke(now, with: .color(.white.opacity(0.55)), lineWidth: 1.5)
    }
}
