import UIKit

/// Where everything in a score goes: measures broken into systems that fit a
/// width, with one x per rhythmic position shared by every staff so the parts
/// line up vertically.
///
/// All lengths are in points; `sp` is one staff space.
struct ScoreLayout {
    struct Column {
        let beat: Double
        var x: CGFloat
    }

    struct Measure {
        /// Index into each part's `staff`.
        let index: Int
        let startBeat: Double
        let endBeat: Double
        var x0: CGFloat
        var x1: CGFloat
        var columns: [Column]

        /// x of a rhythmic position inside the measure (exact for a column,
        /// interpolated between columns otherwise).
        func x(beat: Double) -> CGFloat {
            guard let first = columns.first else { return x0 }
            if beat <= first.beat { return first.x }
            for (a, b) in zip(columns, columns.dropFirst()) where beat < b.beat {
                return a.x + CGFloat((beat - a.beat) / (b.beat - a.beat)) * (b.x - a.x)
            }
            let last = columns[columns.count - 1]
            guard endBeat > last.beat else { return last.x }
            return last.x + CGFloat((beat - last.beat) / (endBeat - last.beat)) * (x1 - last.x)
        }
    }

    struct System: Identifiable {
        let id: Int
        var measures: [Measure]
        /// Top line of each staff, from the system's top.
        let staffTops: [CGFloat]
        let height: CGFloat
        /// Clef, key and (when it is to be printed) time signature in force at the start.
        let clefs: [ScoreClef]
        let fifths: [Int]
        let times: [ScoreTime?]
        /// Where the notes start, after clef and signatures.
        let contentX: CGFloat

        var startBeat: Double { measures.first?.startBeat ?? 0 }
        var endBeat: Double { measures.last?.endBeat ?? 0 }
    }

    let sp: CGFloat
    let width: CGFloat
    let systems: [System]
    /// Per part, per measure: clef and key in force, and a time signature to print there.
    let clefAt: [[ScoreClef]]
    let fifthsAt: [[Int]]
    let timeAt: [[ScoreTime?]]
    let lyricFont: UIFont

    static let empty = ScoreLayout(sp: 6.5, width: 0, systems: [], clefAt: [], fifthsAt: [], timeAt: [],
                                   lyricFont: .systemFont(ofSize: 11))

    private init(sp: CGFloat, width: CGFloat, systems: [System], clefAt: [[ScoreClef]], fifthsAt: [[Int]],
                 timeAt: [[ScoreTime?]], lyricFont: UIFont) {
        self.sp = sp; self.width = width; self.systems = systems
        self.clefAt = clefAt; self.fifthsAt = fifthsAt; self.timeAt = timeAt; self.lyricFont = lyricFont
    }

    init(score: Score, width: CGFloat, sp: CGFloat = 6.5) {
        let parts = score.parts
        let measureCount = parts.map(\.staff.count).min() ?? 0
        let lyricFont = UIFont.systemFont(ofSize: sp * 1.75)
        guard measureCount > 0, width > 40 else {
            self.init(sp: sp, width: width, systems: [], clefAt: [], fifthsAt: [], timeAt: [], lyricFont: lyricFont)
            return
        }

        // Clef, key and printed time signature in force at every measure.
        var clefAt: [[ScoreClef]] = [], fifthsAt: [[Int]] = [], timeAt: [[ScoreTime?]] = []
        for part in parts {
            var clef = ScoreClef.treble, fifths = 0
            var clefs: [ScoreClef] = [], keys: [Int] = [], times: [ScoreTime?] = []
            for measure in part.staff.prefix(measureCount) {
                if let c = measure.clef { clef = c }
                if let f = measure.fifths { fifths = f }
                clefs.append(clef); keys.append(fifths)
                times.append(measure.time.flatMap { $0.visible ? $0 : nil })
            }
            clefAt.append(clefs); fifthsAt.append(keys); timeAt.append(times)
        }

        // Natural (unstretched) width of every measure and the offsets of its columns.
        let leftPad = sp * 1.2, rightPad = sp * 0.8
        struct Natural { var width: CGFloat; var offsets: [(beat: Double, x: CGFloat)]; var start: Double; var end: Double }
        var naturals: [Natural] = []
        for m in 0..<measureCount {
            let start = parts.map { $0.staff[m].startBeat }.min() ?? 0
            let end = parts.map { $0.staff[m].endBeat }.max() ?? start
            var beats = Set<Double>()
            for part in parts { for event in part.staff[m].events { beats.insert(event.startBeat) } }
            let sorted = beats.sorted()
            // A printed time signature in mid-system needs room before the notes.
            let signature: CGFloat = m > 0 && timeAt.contains { $0[m] != nil } ? sp * 3 : 0
            var x = leftPad + signature
            var offsets: [(Double, CGFloat)] = []
            for (i, beat) in sorted.enumerated() {
                let next = i + 1 < sorted.count ? sorted[i + 1] : max(end, beat + 0.25)
                // Longer values get more room, on a logarithmic scale.
                var columnWidth = sp * (2.4 + 1.3 * CGFloat(log2(max(next - beat, 0.25) / 0.25)))
                var hasAccidental = false
                for part in parts {
                    for event in part.staff[m].events where event.startBeat == beat {
                        if event.heads.contains(where: { $0.accidental != nil }) { hasAccidental = true }
                        if event.dots > 0 { columnWidth = max(columnWidth, sp * 3.6) }
                        // Syllables must not run into the next one.
                        if let head = event.heads.first, !head.tieStop, part.notes.indices.contains(head.note),
                           part.notes[head.note].ownLyric, let lyric = part.notes[head.note].lyric {
                            let textWidth = (lyric as NSString).size(withAttributes: [.font: lyricFont]).width
                            columnWidth = max(columnWidth, textWidth + sp * 0.9)
                        }
                    }
                }
                if hasAccidental { x += sp * 1.1 }
                offsets.append((beat, x))
                x += columnWidth
            }
            naturals.append(Natural(width: x + rightPad, offsets: offsets, start: start, end: end))
        }

        // Vertical layout is the same for every system.
        let hasLyrics = parts.map { part in part.notes.contains { $0.ownLyric } }
        var staffTops: [CGFloat] = []
        var y = sp * 4
        for index in parts.indices {
            staffTops.append(y)
            y += sp * 4 + sp * (hasLyrics[index] ? 7.2 : 5) + sp * 3.2
        }
        let systemHeight = y - sp * 1.5

        func prefixWidth(at m: Int, first: Bool) -> CGFloat {
            let key = CGFloat(fifthsAt.map { abs($0[m]) }.max() ?? 0)
            let time: CGFloat = first && timeAt.contains { $0[m] != nil } ? sp * 3 : 0
            return sp * 4.2 + (key > 0 ? key * sp * 1.05 + sp * 0.6 : 0) + time
        }

        // Greedy line breaking, then stretch each line to the full width.
        var systems: [System] = []
        var m = 0
        while m < measureCount {
            let first = m == 0
            let contentX = prefixWidth(at: m, first: first)
            let available = width - contentX - sp * 0.5
            var end = m
            var natural: CGFloat = 0
            while end < measureCount {
                let w = naturals[end].width
                if end > m, natural + w > available { break }
                natural += w
                end += 1
            }
            let isLast = end == measureCount
            // Fill the line; the last one stays natural unless it is nearly full or overfull.
            var scale = available / max(natural, 1)
            if isLast, scale > 1.15 { scale = 1 }
            scale = min(scale, 1.8)

            var x = contentX
            var laid: [Measure] = []
            for index in m..<end {
                let n = naturals[index]
                let w = n.width * scale
                laid.append(Measure(index: index, startBeat: n.start, endBeat: n.end, x0: x, x1: x + w,
                                    columns: n.offsets.map { Column(beat: $0.beat, x: x + $0.x * scale) }))
                x += w
            }
            systems.append(System(id: systems.count, measures: laid, staffTops: staffTops, height: systemHeight,
                                  clefs: clefAt.map { $0[m] }, fifths: fifthsAt.map { $0[m] },
                                  times: first ? timeAt.map { $0[m] } : timeAt.map { _ in nil },
                                  contentX: contentX))
            m = end
        }

        self.init(sp: sp, width: width, systems: systems, clefAt: clefAt, fifthsAt: fifthsAt, timeAt: timeAt,
                  lyricFont: lyricFont)
    }

    /// The system and x position of a beat, for the playback cursor.
    func position(beat: Double) -> (system: Int, x: CGFloat)? {
        guard let last = systems.last else { return nil }
        let system = systems.first { beat < $0.endBeat } ?? last
        guard let measure = system.measures.first(where: { beat < $0.endBeat }) ?? system.measures.last else { return nil }
        return (system.id, measure.x(beat: beat))
    }

    /// The system holding a printed measure number.
    func system(containingMeasure number: Int, in score: Score) -> Int? {
        guard let staff = score.parts.first?.staff else { return nil }
        return systems.first { system in
            system.measures.contains { staff.indices.contains($0.index) && staff[$0.index].number == number }
        }?.id
    }
}
