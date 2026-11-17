import SwiftUI

enum Theme {
    static let background = Color(red: 0.078, green: 0.082, blue: 0.102)
    static let panel = Color(red: 0.118, green: 0.125, blue: 0.157)
    static let key = Color(red: 0.165, green: 0.176, blue: 0.220)
    static let keyHeld = Color(red: 0.86, green: 0.68, blue: 0.30)
    static let gold = Color(red: 0.86, green: 0.68, blue: 0.30)
    static let trace = Color(red: 0.30, green: 0.85, blue: 0.95)
    static let dim = Color.white.opacity(0.45)
    static let rule = Color.white.opacity(0.10)

    /// Green when in tune, through amber, to orange when a quarter-tone out.
    static func tuning(cents: Double) -> Color {
        switch abs(cents) {
        case ..<10: return Color(red: 0.35, green: 0.85, blue: 0.50)
        case ..<25: return Color(red: 0.95, green: 0.80, blue: 0.30)
        default: return Color(red: 0.95, green: 0.50, blue: 0.25)
        }
    }
}

/// The scale ladder (left) with the sung-pitch scope scrolling behind it.
/// Both share one vertical moria axis, so a sung note lines up with its key.
struct LadderView: View {
    @Bindable var model: ScalesModel

    @Environment(\.horizontalSizeClass) private var sizeClass
    private var pointsPerMoria: CGFloat { sizeClass == .regular ? 9 : 7 }
    private var ladderWidth: CGFloat { sizeClass == .regular ? 150 : 104 }
    private let margin: CGFloat = 28

    private var visible: [Cell] { model.editing ? model.cells : model.playable }
    private var topMoria: Int { (model.cells.map(\.effectiveMoria).max() ?? 144) }
    private var bottomMoria: Int { (model.cells.map(\.effectiveMoria).min() ?? -72) }
    private var height: CGFloat { CGFloat(topMoria - bottomMoria) * pointsPerMoria + 2 * margin }

    private func y(_ moria: Double) -> CGFloat { margin + (CGFloat(topMoria) - CGFloat(moria)) * pointsPerMoria }

    /// Key height: as tall as the tightest spacing on the ladder allows.
    private var keyHeight: CGFloat {
        let positions = model.playable.map(\.effectiveMoria)
        let gap = zip(positions.dropFirst(), positions).map { $0 - $1 }.filter { $0 > 0 }.min() ?? 12
        return min(34, max(14, CGFloat(gap) * pointsPerMoria - 3))
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical) {
                ZStack(alignment: .topLeading) {
                    scope
                    intervals
                    keys
                    // Scroll target: middle of the octave above the reference Ni.
                    VStack(spacing: 0) {
                        Color.clear.frame(height: y(36))
                        Color.clear.frame(height: 1).id("home")
                        Spacer(minLength: 0)
                    }
                }
                .frame(height: height)
            }
            .scrollIndicators(.hidden)
            .onAppear { proxy.scrollTo("home", anchor: .center) }
            .onChange(of: model.sung?.cellMoria) { _, moria in
                // Keep the singer's note on screen without fighting manual scrolling.
                guard let moria, model.held.isEmpty else { return }
                followTarget = moria
            }
            .onChange(of: followTarget) { _, moria in
                guard let moria, let cell = model.cell(at: moria) else { return }
                let now = Date()
                guard now.timeIntervalSince(lastFollow) > 1.2 else { return }
                lastFollow = now
                withAnimation(.easeInOut(duration: 0.5)) {
                    proxy.scrollTo("cell-\(cell.moria)", anchor: .center)
                }
            }
        }
        .background(Theme.background)
    }

    @State private var followTarget: Int?
    @State private var lastFollow = Date.distantPast

    // MARK: keys

    private var keys: some View {
        ForEach(visible) { cell in
            let h = cell.enabled ? keyHeight : 12
            KeyView(model: model, cell: cell, height: h)
                .frame(width: cell.enabled ? ladderWidth - 16 : 44, height: h)
                .id("cell-\(cell.moria)")
                .placed(x: 8, y: y(Double(cell.effectiveMoria)) - h / 2)
        }
    }

    /// Moria distance between neighbouring keys, written in the gap.
    private var intervals: some View {
        let cells = model.playable
        return ForEach(Array(zip(cells.dropFirst(), cells)), id: \.0.moria) { upper, lower in
            let gap = upper.effectiveMoria - lower.effectiveMoria
            if gap >= 6 {
                Text("\(gap)")
                    .font(.system(size: 10, weight: .medium, design: .rounded))
                    .foregroundStyle(Theme.dim)
                    .frame(width: 24, height: 12)
                    .placed(x: ladderWidth - 4,
                            y: y(Double(upper.effectiveMoria + lower.effectiveMoria) / 2) - 6)
            }
        }
    }

    // MARK: scope

    private var scope: some View {
        TimelineView(.animation(paused: !model.micOn)) { timeline in
            Canvas { context, size in
                let left = ladderWidth + 24
                let nowX = size.width - 28
                let span = nowX - left

                for cell in model.playable {
                    let lineY = y(Double(cell.effectiveMoria))
                    var line = Path()
                    line.move(to: CGPoint(x: left, y: lineY))
                    line.addLine(to: CGPoint(x: size.width, y: lineY))
                    let isIson = cell.moria == model.isonMoria
                    context.stroke(line, with: .color(isIson ? Theme.gold.opacity(0.5) : Theme.rule),
                                   lineWidth: isIson ? 1.5 : 1)
                }

                guard model.micOn else { return }
                let now = timeline.date.timeIntervalSinceReferenceDate
                var path = Path()
                var penDown = false
                for point in model.trace {
                    guard let moria = point.moria else { penDown = false; continue }
                    let x = nowX - CGFloat((now - point.time) / ScalesModel.traceSeconds) * span
                    guard x >= left else { penDown = false; continue }
                    let p = CGPoint(x: x, y: y(moria))
                    if penDown { path.addLine(to: p) } else { path.move(to: p); penDown = true }
                }
                context.stroke(path, with: .color(Theme.trace),
                               style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))

                if let sung = model.sung {
                    let color = Theme.tuning(cents: sung.cents)
                    let centre = CGPoint(x: nowX, y: y(sung.moria))
                    context.fill(Path(ellipseIn: CGRect(x: centre.x - 6, y: centre.y - 6, width: 12, height: 12)),
                                 with: .color(color))
                    // Pointer at the ladder edge, level with the voice.
                    var pointer = Path()
                    pointer.move(to: CGPoint(x: ladderWidth - 6, y: centre.y))
                    pointer.addLine(to: CGPoint(x: ladderWidth + 6, y: centre.y - 6))
                    pointer.addLine(to: CGPoint(x: ladderWidth + 6, y: centre.y + 6))
                    pointer.closeSubpath()
                    context.fill(pointer, with: .color(color))
                }
            }
        }
        .frame(height: height)
        .allowsHitTesting(false)
    }
}

/// One key on the ladder: hold to play, or tap to select while editing.
private struct KeyView: View {
    let model: ScalesModel
    let cell: Cell
    let height: CGFloat

    private var held: Bool { model.held.contains(cell.moria) }
    private var sung: Bool { model.sung?.cellMoria == cell.moria }
    private var selected: Bool { model.editing && model.selectedMoria == cell.moria }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: min(8, height / 2.5), style: .continuous)
        ZStack {
            shape.fill(fill)
            if cell.enabled {
                HStack(spacing: 4) {
                    Text(model.label(for: cell))
                        .font(.system(size: min(16, height * 0.62), weight: .semibold, design: .rounded))
                    if cell.accidental != 0 {
                        Text(cell.accidental > 0 ? "+\(cell.accidental)" : "−\(-cell.accidental)")
                            .font(.system(size: min(11, height * 0.5), weight: .medium, design: .rounded))
                            .foregroundStyle(held ? Color.black.opacity(0.6) : Theme.gold)
                    }
                    if model.isonMoria == cell.moria {
                        Image(systemName: "waveform")
                            .font(.system(size: min(11, height * 0.5), weight: .bold))
                            .foregroundStyle(held ? Color.black.opacity(0.6) : Theme.gold)
                    }
                }
                .foregroundStyle(held ? Color.black : Color.white)
            }
        }
        .overlay(shape.strokeBorder(border, lineWidth: selected || sung ? 2 : 0))
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if model.editing { return }
                    model.press(cell)
                }
                .onEnded { _ in
                    if model.editing {
                        model.selectedMoria = model.selectedMoria == cell.moria ? nil : cell.moria
                    } else {
                        model.release(cell)
                    }
                }
        )
        .accessibilityLabel(Text(model.label(for: cell)))
        .accessibilityAddTraits(.isButton)
    }

    private var fill: Color {
        if !cell.enabled { return Color.white.opacity(selected ? 0.25 : 0.08) }
        if held { return Theme.keyHeld }
        if let sung = model.sung, sung.cellMoria == cell.moria {
            return Theme.tuning(cents: sung.cents).opacity(0.35)
        }
        return Theme.key
    }

    private var border: Color {
        if selected { return Theme.gold }
        if let sung = model.sung, sung.cellMoria == cell.moria { return Theme.tuning(cents: sung.cents) }
        return .clear
    }
}

private extension View {
    /// Put the view's top-left corner at (x, y) inside a `.topLeading` ZStack.
    /// Unlike `offset`, this moves the layout frame, so `scrollTo` can find it.
    func placed(x: CGFloat, y: CGFloat) -> some View {
        alignmentGuide(.leading) { _ in -x }
            .alignmentGuide(.top) { _ in -y }
    }
}
