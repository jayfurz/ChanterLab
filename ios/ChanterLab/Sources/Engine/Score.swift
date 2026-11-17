import Foundation

/// A note of the practice model. Beats are quarter notes from the start.
struct ScoreNote: Decodable {
    let midi: Int
    let startBeat: Double
    let durBeat: Double
    /// Printed measure number.
    let measure: Int
    /// Syllable for the selected verse; a trailing "-" continues the word.
    let lyric: String?

    var endBeat: Double { startBeat + durBeat }
}

struct ScorePart: Decodable, Identifiable {
    /// "S", "A", "T", "B", or "P<index>" beyond the fourth part.
    let voiceKey: String
    let voiceName: String
    let index: Int
    let notes: [ScoreNote]

    var id: Int { index }
}

struct ScoreSection: Decodable, Identifiable, Hashable {
    let title: String
    let measure: Int

    var id: Int { measure }
}

/// A piece as the Rust core parsed it from MusicXML.
struct Score: Decodable {
    let parts: [ScorePart]
    let measureCount: Int
    let maxVerse: Int
    let sections: [ScoreSection]

    struct ParseFailure: LocalizedError {
        let message: String
        var errorDescription: String? { "This score could not be read (\(message))." }
    }

    private struct Failure: Decodable { let error: String }

    /// Parse MusicXML with lyrics for `verse` (1-based).
    static func parse(xml: String, verse: Int) throws -> Score {
        guard let raw = clp_score_parse(xml, UInt32(max(1, verse))) else {
            throw ParseFailure(message: "no result")
        }
        defer { clp_string_free(raw) }
        let data = Data(String(cString: raw).utf8)
        if let failure = try? JSONDecoder().decode(Failure.self, from: data) {
            throw ParseFailure(message: failure.error)
        }
        return try JSONDecoder().decode(Score.self, from: data)
    }

    /// Beat span of all notes in printed measures `from...to`.
    func beatRange(fromMeasure from: Int, toMeasure to: Int) -> ClosedRange<Double> {
        var start = Double.infinity, end = 0.0
        for note in parts.lazy.flatMap(\.notes) where note.measure >= from && note.measure <= to {
            start = min(start, note.startBeat)
            end = max(end, note.endBeat)
        }
        return start.isFinite ? start...max(start, end) : 0...0
    }

    var firstMeasure: Int { parts.lazy.flatMap(\.notes).map(\.measure).min() ?? 1 }
    var lastMeasure: Int { parts.lazy.flatMap(\.notes).map(\.measure).max() ?? 1 }
}

// MARK: lap scoring

enum Verdict: String, Decodable {
    case hit, flat, sharp, missed
}

struct LapReport: Decodable {
    struct Detail: Decodable {
        let index: Int
        let measure: Int?
        let result: Verdict
        let meanCents: Double?
    }
    struct WorstSpot: Decodable, Identifiable {
        let measure: Int
        let bad: Int
        var id: Int { measure }
    }

    let notes: Int
    let hit: Int
    let flat: Int
    let sharp: Int
    let missed: Int
    let hitPct: Int
    let details: [Detail]
    let worst: [WorstSpot]

    struct Target: Encodable {
        let midi: Double
        let startSec: Double
        let endSec: Double
        let measure: Int
    }
    struct Sample: Encodable {
        let tSec: Double
        let midi: Double
    }

    /// Score one lap with the Rust port of the web scorer.
    static func score(targets: [Target], samples: [Sample], strict: Bool) -> LapReport? {
        let encoder = JSONEncoder()
        guard let t = try? encoder.encode(targets), let s = try? encoder.encode(samples),
              let raw = clp_score_lap(String(decoding: t, as: UTF8.self), String(decoding: s, as: UTF8.self), strict)
        else { return nil }
        defer { clp_string_free(raw) }
        return try? JSONDecoder().decode(LapReport.self, from: Data(String(cString: raw).utf8))
    }
}
