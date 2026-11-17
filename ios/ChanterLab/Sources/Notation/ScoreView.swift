import SwiftUI

/// SMuFL code points in Bravura.
private enum Glyph {
    static let gClef = "\u{E050}", gClef8vb = "\u{E052}", cClef = "\u{E05C}", fClef = "\u{E062}"
    static let noteBreve = "\u{E0A0}", noteWhole = "\u{E0A2}", noteHalf = "\u{E0A3}", noteBlack = "\u{E0A4}"
    static let flag8Up = "\u{E240}", flag8Down = "\u{E241}", flag16Up = "\u{E242}", flag16Down = "\u{E243}"
    static let flat = "\u{E260}", natural = "\u{E261}", sharp = "\u{E262}", doubleSharp = "\u{E263}", doubleFlat = "\u{E264}"
    static let dot = "\u{E1E7}"
    static let restBreve = "\u{E4E2}", restWhole = "\u{E4E3}", restHalf = "\u{E4E4}", restQuarter = "\u{E4E5}"
    static let rest8 = "\u{E4E6}", rest16 = "\u{E4E7}"

    static func timeDigits(_ text: String) -> String {
        String(text.unicodeScalars.compactMap { scalar -> Character? in
            guard let digit = Int(String(scalar)) else { return nil }
            return Character(UnicodeScalar(0xE080 + digit)!)
        })
    }

    static func accidental(_ name: String) -> String? {
        switch name {
        case "sharp": return sharp
        case "flat": return flat
        case "natural": return natural
        case "double-sharp", "sharp-sharp": return doubleSharp
        case "flat-flat", "double-flat": return doubleFlat
        default: return nil
        }
    }
}

/// The engraved score: scrolls by system and follows playback.
struct ScoreView: View {
    let model: PracticeModel
    @State private var layout = ScoreLayout.empty
    @State private var shownSystem = -1
    @State private var lastTouch = Date.distantPast

    private struct LayoutKey: Equatable {
        let width: CGFloat
        let revision: Int
    }

    var body: some View {
        GeometryReader { geo in
            ScrollViewReader { proxy in
                ScrollView(.vertical) {
                    LazyVStack(spacing: 0) {
                        ForEach(layout.systems) { system in
                            SystemView(model: model, layout: layout, system: system)
                                .frame(height: system.height)
                                .id(system.id)
                        }
                    }
                }
                .simultaneousGesture(DragGesture(minimumDistance: 4).onChanged { _ in lastTouch = Date() })
                .task(id: LayoutKey(width: geo.size.width, revision: model.scoreRevision)) {
                    guard let score = model.score else { layout = .empty; return }
                    layout = ScoreLayout(score: score, width: geo.size.width)
                    shownSystem = -1
                }
                .onReceive(Timer.publish(every: 0.2, on: .main, in: .common).autoconnect()) { _ in
                    follow(proxy)
                }
            }
        }
        .background(Theme.background)
        .accessibilityLabel("Score")
    }

    /// Keep the system being sung on screen, unless the reader is scrolling.
    private func follow(_ proxy: ScrollViewProxy) {
        guard model.transport != .stopped || shownSystem == -1,
              Date().timeIntervalSince(lastTouch) > 3,
              let position = layout.position(beat: model.heardBeat), position.system != shownSystem else { return }
        shownSystem = position.system
        withAnimation(.easeInOut(duration: 0.35)) { proxy.scrollTo(position.system, anchor: .top) }
    }
}

/// One line of the score.
private struct SystemView: View {
    let model: PracticeModel
    let layout: ScoreLayout
    let system: ScoreLayout.System

    var body: some View {
        // Observed inputs: read here so the static drawing refreshes when they change.
        let voice = model.voice
        let verdicts = model.showVerdicts ? model.noteVerdicts : [:]
        ZStack {
            Canvas { context, size in
                var engraver = Engraver(context: &context, layout: layout, system: system, score: model.score,
                                        voice: voice, verdicts: verdicts, width: size.width)
                engraver.draw()
            }
            TimelineView(.animation(paused: model.transport != .playing)) { timeline in
                Canvas { context, _ in
                    _ = timeline.date
                    guard model.transport != .stopped,
                          let position = layout.position(beat: model.heardBeat), position.system == system.id,
                          let top = system.staffTops.compactMap({ $0 }).first,
                          let bottom = system.staffTops.compactMap({ $0 }).last else { return }
                    let sp = layout.sp
                    let rect = CGRect(x: position.x - sp * 0.3, y: top - sp, width: sp * 1.8,
                                      height: bottom + sp * 5 - (top - sp))
                    context.fill(Path(roundedRect: rect, cornerRadius: 2), with: .color(Theme.gold.opacity(0.4)))
                }
            }
            .allowsHitTesting(false)
        }
    }
}

/// Draws one system into a canvas.
private struct Engraver {
    var context: GraphicsContext
    let layout: ScoreLayout
    let system: ScoreLayout.System
    let score: Score?
    let voice: Int
    let verdicts: [Int: Verdict]
    let width: CGFloat

    private let sp: CGFloat
    private let lineColor = Color.white.opacity(0.32)
    private let otherInk = Color(red: 0.72, green: 0.74, blue: 0.77)
    private let myInk = Color(red: 0.83, green: 0.69, blue: 0.22)

    init(context: inout GraphicsContext, layout: ScoreLayout, system: ScoreLayout.System, score: Score?,
         voice: Int, verdicts: [Int: Verdict], width: CGFloat) {
        self.context = context
        self.layout = layout
        self.system = system
        self.score = score
        self.voice = voice
        self.verdicts = verdicts
        self.width = width
        sp = layout.sp
    }

    // MARK: primitives

    /// Draw a music glyph with its SMuFL origin (left edge, baseline) at (x, y). Returns its width.
    @discardableResult
    private mutating func glyph(_ text: String, x: CGFloat, y: CGFloat, color: Color, centered: Bool = false) -> CGFloat {
        let resolved = context.resolve(Text(text).font(.custom("Bravura", size: sp * 4)).foregroundStyle(color))
        let size = resolved.measure(in: CGSize(width: 4000, height: 4000))
        let baseline = resolved.firstBaseline(in: size)
        context.draw(resolved, at: CGPoint(x: centered ? x - size.width / 2 : x, y: y - baseline), anchor: .topLeading)
        return size.width
    }

    private func glyphWidth(_ text: String) -> CGFloat {
        context.resolve(Text(text).font(.custom("Bravura", size: sp * 4)))
            .measure(in: CGSize(width: 4000, height: 4000)).width
    }

    private mutating func line(_ x0: CGFloat, _ y0: CGFloat, _ x1: CGFloat, _ y1: CGFloat, color: Color, width: CGFloat) {
        var path = Path()
        path.move(to: CGPoint(x: x0, y: y0))
        path.addLine(to: CGPoint(x: x1, y: y1))
        context.stroke(path, with: .color(color), lineWidth: width)
    }

    // MARK: system

    mutating func draw() {
        guard let score, !system.measures.isEmpty else { return }
        for (index, part) in score.parts.enumerated() where index < system.staffTops.count {
            if let top = system.staffTops[index] { drawStaff(part: part, index: index, top: top) }
        }
        let tops = system.staffTops.compactMap { $0 }
        if tops.count > 1, let first = tops.first, let last = tops.last {
            line(0.5, first, 0.5, last + sp * 4, color: lineColor, width: 1)
        }
    }

    private mutating func drawStaff(part: ScorePart, index: Int, top: CGFloat) {
        let mine = index == voice
        let ink = mine ? myInk : otherInk
        for i in 0..<5 {
            line(0, top + CGFloat(i) * sp, width, top + CGFloat(i) * sp, color: lineColor, width: max(0.6, sp * 0.13))
        }

        // Clef, key signature, time signature.
        var clef = system.clefs[index]
        var x = sp * 0.7
        let clefGlyph: String
        switch clef.sign {
        case "F": clefGlyph = Glyph.fClef
        case "C": clefGlyph = Glyph.cClef
        default: clefGlyph = clef.octaveChange < 0 ? Glyph.gClef8vb : Glyph.gClef
        }
        x += glyph(clefGlyph, x: x, y: top + sp * CGFloat(5 - clef.line), color: ink) + sp * 0.5
        x = drawKey(fifths: system.fifths[index], clef: clef, x: x, top: top, color: ink)
        if let time = system.times[index] { drawTime(time, x: x + sp * 0.3, top: top, color: ink) }

        // Number the line when it starts a new printed measure (chant splits one
        // numbered measure into several unbarred ones; those are not renumbered).
        let firstIndex = system.measures[0].index
        let number = part.staff[firstIndex].number
        if top == system.staffTops.compactMap({ $0 }).first, firstIndex > 0,
           number != part.staff[firstIndex - 1].number {
            context.draw(Text("\(number)").font(.system(size: sp * 1.4)).foregroundStyle(Theme.dim),
                         at: CGPoint(x: sp * 0.5, y: top - sp * 3.2), anchor: .topLeading)
        }

        // Lyrics sit on one line per staff, below the lowest note or stem on this system.
        var lowest = top + sp * 4 + sp * 2.0
        for measure in system.measures {
            let measureClef = layout.clefAt[index][measure.index]
            for event in part.staff[measure.index].events where !event.isRest {
                guard let low = event.heads.map(\.pos).min(), let high = event.heads.map(\.pos).max() else { continue }
                let lowY = top + sp * 4 - CGFloat(low - measureClef.bottomLine) * sp / 2
                let up = event.stemUp ?? (Double(low + high) / 2 - Double(measureClef.bottomLine) < 4)
                let stemmed = event.kind != "whole" && event.kind != "breve"
                lowest = max(lowest, lowY + (up || !stemmed ? sp * 0.6 : sp * 3.6))
            }
        }
        let lyricY = min(lowest + sp * 0.7, top + sp * 4 + sp * 5.2)

        var ties: [Int: (point: CGPoint, below: Bool)] = [:]
        for measure in system.measures {
            let staffMeasure = part.staff[measure.index]
            clef = layout.clefAt[index][measure.index]
            if measure.index != system.measures[0].index, let time = layout.timeAt[index][measure.index] {
                drawTime(time, x: measure.x0 + sp * 0.6, top: top, color: ink)
            }
            drawEvents(staffMeasure.events, in: measure, part: part, clef: clef, top: top, lyricY: lyricY,
                       mine: mine, ink: ink, ties: &ties)
            drawBarline(staffMeasure.barline, x: measure.x1, top: top)
        }
        // A tie still open at the end of the line continues on the next one.
        for (_, tie) in ties {
            drawTie(from: tie.point, to: CGPoint(x: width - sp * 0.3, y: tie.point.y), below: tie.below, color: ink)
        }
    }

    private mutating func drawKey(fifths: Int, clef: ScoreClef, x: CGFloat, top: CGFloat, color: Color) -> CGFloat {
        guard fifths != 0 else { return x }
        // Staff positions (0 = bottom line) in treble clef; other clefs shift.
        let sharps = [8, 5, 9, 6, 3, 7, 4], flats = [4, 7, 3, 6, 2, 5, 1]
        let shift = clef.sign == "F" ? -2 : clef.sign == "C" ? -1 : 0
        var x = x
        for i in 0..<min(abs(fifths), 7) {
            let position = (fifths > 0 ? sharps[i] : flats[i]) + shift
            glyph(fifths > 0 ? Glyph.sharp : Glyph.flat, x: x, y: top + sp * 4 - CGFloat(position) * sp / 2, color: color)
            x += sp * 1.05
        }
        return x + sp * 0.3
    }

    private mutating func drawTime(_ time: ScoreTime, x: CGFloat, top: CGFloat, color: Color) {
        let upper = Glyph.timeDigits(time.beats), lower = Glyph.timeDigits(time.beatType)
        let centre = x + max(glyphWidth(upper), glyphWidth(lower)) / 2
        glyph(upper, x: centre, y: top + sp, color: color, centered: true)
        glyph(lower, x: centre, y: top + sp * 3, color: color, centered: true)
    }

    private mutating func drawBarline(_ style: String, x: CGFloat, top: CGFloat) {
        let bottom = top + sp * 4
        let thin = max(0.8, sp * 0.16)
        switch style {
        case "none":
            break
        case "light-heavy":
            line(x - sp * 0.95, top, x - sp * 0.95, bottom, color: lineColor, width: thin)
            line(x - sp * 0.25, top, x - sp * 0.25, bottom, color: lineColor, width: sp * 0.5)
        case "light-light":
            line(x - sp * 0.5, top, x - sp * 0.5, bottom, color: lineColor, width: thin)
            line(x, top, x, bottom, color: lineColor, width: thin)
        default:
            line(x, top, x, bottom, color: lineColor, width: thin)
        }
    }

    // MARK: notes

    private struct Stemmed {
        let event: ScoreEvent
        let x: CGFloat
        let up: Bool
        let stemX: CGFloat
        let start: CGFloat
        /// Where the stem would end on its own; beams may lengthen it.
        var end: CGFloat
    }

    private mutating func drawEvents(_ events: [ScoreEvent], in measure: ScoreLayout.Measure, part: ScorePart,
                                     clef: ScoreClef, top: CGFloat, lyricY: CGFloat, mine: Bool, ink: Color,
                                     ties: inout [Int: (point: CGPoint, below: Bool)]) {
        let bottomY = top + sp * 4
        let middleY = top + sp * 2
        func y(_ pos: Int) -> CGFloat { bottomY - CGFloat(pos - clef.bottomLine) * sp / 2 }
        var group: [Stemmed] = []

        for event in events {
            let x = measure.x(beat: event.startBeat)
            if event.isRest {
                drawRest(event, x: x, top: top, color: ink)
                continue
            }
            let heads = event.heads.sorted { $0.pos < $1.pos }
            let headGlyph: String
            switch event.kind {
            case "breve": headGlyph = Glyph.noteBreve
            case "whole": headGlyph = Glyph.noteWhole
            case "half": headGlyph = Glyph.noteHalf
            default: headGlyph = Glyph.noteBlack
            }
            let headWidth = glyphWidth(headGlyph)
            let lowest = heads[0].pos, highest = heads[heads.count - 1].pos
            let average = Double(lowest + highest) / 2 - Double(clef.bottomLine)
            let up = event.stemUp ?? (average < 4)

            // Ledger lines.
            let ledgerWidth = max(0.8, sp * 0.16)
            for pos in stride(from: clef.bottomLine - 2, through: lowest, by: -2) {
                line(x - sp * 0.35, y(pos), x + headWidth + sp * 0.35, y(pos), color: lineColor, width: ledgerWidth)
            }
            if highest >= clef.bottomLine + 10 {
                for pos in stride(from: clef.bottomLine + 10, through: highest, by: 2) {
                    line(x - sp * 0.35, y(pos), x + headWidth + sp * 0.35, y(pos), color: lineColor, width: ledgerWidth)
                }
            }

            for head in heads {
                let headY = y(head.pos)
                var color = ink
                if mine, let verdict = verdicts[head.note], let tint = LaneView.verdictColors[verdict] { color = tint }
                glyph(headGlyph, x: x, y: headY, color: color)
                if let name = head.accidental, let accidental = Glyph.accidental(name) {
                    glyph(accidental, x: x - glyphWidth(accidental) - sp * 0.25, y: headY, color: ink)
                }
                for dot in 0..<event.dots {
                    // A dot never sits on a line: move it into the space above.
                    let onLine = (head.pos - clef.bottomLine) % 2 == 0
                    glyph(Glyph.dot, x: x + headWidth + sp * (0.45 + 0.6 * CGFloat(dot)),
                          y: headY - (onLine ? sp / 2 : 0), color: ink)
                }
                // Ties curve away from the stem.
                if head.tieStop {
                    let end = CGPoint(x: x - sp * 0.15, y: headY)
                    if let open = ties.removeValue(forKey: head.note) {
                        drawTie(from: open.point, to: end, below: open.below, color: ink)
                    } else {
                        drawTie(from: CGPoint(x: max(system.contentX - sp, x - sp * 3), y: headY), to: end, below: up, color: ink)
                    }
                }
                if head.tieStart {
                    ties[head.note] = (CGPoint(x: x + headWidth + sp * 0.15, y: headY), up)
                }
                if head.pos == lowest, !head.tieStop, part.notes.indices.contains(head.note),
                   part.notes[head.note].ownLyric, let lyric = part.notes[head.note].lyric {
                    context.draw(Text(lyric).font(.system(size: layout.lyricFont.pointSize))
                        .foregroundStyle(Color.white.opacity(mine ? 0.92 : 0.6)),
                                 at: CGPoint(x: x - sp * 0.1, y: lyricY), anchor: .topLeading)
                }
            }

            guard event.kind != "whole", event.kind != "breve" else { continue }
            let stemThickness = max(0.8, sp * 0.12)
            let stemX = up ? x + headWidth - stemThickness / 2 : x + stemThickness / 2
            let start = up ? y(lowest) - sp * 0.17 : y(highest) + sp * 0.17
            // Stems are 3.5 spaces and always reach the middle line.
            let end = up ? min(y(highest) - sp * 3.5, middleY) : max(y(lowest) + sp * 3.5, middleY)
            let stemmed = Stemmed(event: event, x: x, up: up, stemX: stemX, start: start, end: end)

            switch event.beams.first {
            case "begin":
                flush(&group, color: ink)
                group = [stemmed]
            case "continue" where !group.isEmpty:
                group.append(stemmed)
            case "end" where !group.isEmpty:
                group.append(stemmed)
                drawBeamed(group, color: ink)
                group = []
            default:
                flush(&group, color: ink)
                drawStem(stemmed, color: ink, flagged: true)
            }
        }
        flush(&group, color: ink)
    }

    /// A beam group that never closed: draw its notes with flags instead.
    private mutating func flush(_ group: inout [Stemmed], color: Color) {
        for stemmed in group { drawStem(stemmed, color: color, flagged: true) }
        group = []
    }

    private mutating func drawStem(_ stemmed: Stemmed, color: Color, flagged: Bool) {
        line(stemmed.stemX, stemmed.start, stemmed.stemX, stemmed.end, color: color, width: max(0.8, sp * 0.12))
        guard flagged else { return }
        let flag: String?
        switch stemmed.event.kind {
        case "eighth": flag = stemmed.up ? Glyph.flag8Up : Glyph.flag8Down
        case "16th": flag = stemmed.up ? Glyph.flag16Up : Glyph.flag16Down
        default: flag = nil
        }
        if let flag { glyph(flag, x: stemmed.stemX - sp * 0.06, y: stemmed.end, color: color) }
    }

    private mutating func drawBeamed(_ group: [Stemmed], color: Color) {
        guard let first = group.first, let last = group.last, group.count > 1, last.stemX > first.stemX else {
            for stemmed in group { drawStem(stemmed, color: color, flagged: true) }
            return
        }
        let up = first.up
        // The beam follows the outer notes, with a gentle slope, and is pushed
        // out until every stem is at least its natural length.
        let rise = max(-sp * 1.25, min(sp * 1.25, last.end - first.end))
        func lineY(_ x: CGFloat, _ base: CGFloat) -> CGFloat {
            base + rise * (x - first.stemX) / (last.stemX - first.stemX)
        }
        var base = first.end
        for stemmed in group {
            let at = lineY(stemmed.stemX, base)
            if up, at > stemmed.end { base -= at - stemmed.end }
            if !up, at < stemmed.end { base += stemmed.end - at }
        }
        let thickness = sp * 0.5
        let inward: CGFloat = up ? 1 : -1

        func bar(from x0: CGFloat, to x1: CGFloat, level: Int) -> Path {
            let offset = CGFloat(level) * sp * 0.75 * inward
            var path = Path()
            path.move(to: CGPoint(x: x0, y: lineY(x0, base) + offset))
            path.addLine(to: CGPoint(x: x1, y: lineY(x1, base) + offset))
            path.addLine(to: CGPoint(x: x1, y: lineY(x1, base) + offset + thickness * inward))
            path.addLine(to: CGPoint(x: x0, y: lineY(x0, base) + offset + thickness * inward))
            path.closeSubpath()
            return path
        }

        for stemmed in group {
            // Stems of mixed direction inside one beam all go the beam's way.
            let start = stemmed.up == up ? stemmed.start : (up ? stemmed.start - sp * 0.34 : stemmed.start + sp * 0.34)
            line(stemmed.stemX, start, stemmed.stemX, lineY(stemmed.stemX, base), color: color, width: max(0.8, sp * 0.12))
        }
        context.fill(bar(from: first.stemX, to: last.stemX, level: 0), with: .color(color))

        // Second beam for sixteenths: full segments between neighbours, stubs for hooks.
        for (i, stemmed) in group.enumerated() where stemmed.event.beams.count > 1 {
            switch stemmed.event.beams[1] {
            case "begin", "continue":
                if i + 1 < group.count, group[i + 1].event.beams.count > 1 {
                    context.fill(bar(from: stemmed.stemX, to: group[i + 1].stemX, level: 1), with: .color(color))
                }
            case "forward hook":
                context.fill(bar(from: stemmed.stemX, to: stemmed.stemX + sp * 1.1, level: 1), with: .color(color))
            case "backward hook":
                context.fill(bar(from: stemmed.stemX - sp * 1.1, to: stemmed.stemX, level: 1), with: .color(color))
            default:
                break
            }
        }
    }

    private mutating func drawRest(_ event: ScoreEvent, x: CGFloat, top: CGFloat, color: Color) {
        let (text, y): (String, CGFloat)
        switch event.kind {
        case "breve": (text, y) = (Glyph.restBreve, top + sp * 2)
        case "whole": (text, y) = (Glyph.restWhole, top + sp)
        case "half": (text, y) = (Glyph.restHalf, top + sp * 2)
        case "eighth": (text, y) = (Glyph.rest8, top + sp * 2)
        case "16th": (text, y) = (Glyph.rest16, top + sp * 2)
        default: (text, y) = (Glyph.restQuarter, top + sp * 2)
        }
        glyph(text, x: x, y: y, color: color)
        for dot in 0..<event.dots {
            glyph(Glyph.dot, x: x + glyphWidth(text) + sp * (0.4 + 0.6 * CGFloat(dot)), y: top + sp * 1.5, color: color)
        }
    }

    private mutating func drawTie(from start: CGPoint, to end: CGPoint, below: Bool, color: Color) {
        guard end.x > start.x else { return }
        let direction: CGFloat = below ? 1 : -1
        let y0 = start.y + direction * sp * 0.7, y1 = end.y + direction * sp * 0.7
        let depth = min(sp * 1.4, max(sp * 0.7, (end.x - start.x) * 0.18)) * direction
        let c1 = CGPoint(x: start.x + (end.x - start.x) * 0.25, y: y0 + depth)
        let c2 = CGPoint(x: start.x + (end.x - start.x) * 0.75, y: y1 + depth)
        var path = Path()
        path.move(to: CGPoint(x: start.x, y: y0))
        path.addCurve(to: CGPoint(x: end.x, y: y1), control1: c1, control2: c2)
        // Return a little shallower to give the curve its swell in the middle.
        path.addCurve(to: CGPoint(x: start.x, y: y0),
                      control1: CGPoint(x: c2.x, y: c2.y - direction * sp * 0.28),
                      control2: CGPoint(x: c1.x, y: c1.y - direction * sp * 0.28))
        context.fill(path, with: .color(color))
    }
}
