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
    /// The syllable is printed under this part's own staff (not borrowed for the lane).
    let ownLyric: Bool

    var endBeat: Double { startBeat + durBeat }
}

// MARK: engraving

/// A notehead as engraved.
struct ScoreHead: Decodable {
    /// Diatonic position: octave × 7 + step, C = 0 (C4 is 28).
    let pos: Int
    let accidental: String?
    let tieStart: Bool
    let tieStop: Bool
    /// Index into the part's `notes`.
    let note: Int
}

/// A note, chord or rest as engraved.
struct ScoreEvent: Decodable {
    let startBeat: Double
    let durBeat: Double
    /// "breve", "whole", "half", "quarter", "eighth" or "16th".
    let kind: String
    let dots: Int
    let stemUp: Bool?
    let beams: [String]
    /// Empty for a rest.
    let heads: [ScoreHead]

    var isRest: Bool { heads.isEmpty }
}

struct ScoreClef: Decodable, Equatable {
    let sign: String
    let line: Int
    let octaveChange: Int

    static let treble = ScoreClef(sign: "G", line: 2, octaveChange: 0)

    /// Diatonic position of the bottom staff line.
    var bottomLine: Int {
        let anchor: Int
        switch sign {
        case "F": anchor = 24   // F3
        case "C": anchor = 28   // C4
        default: anchor = 32    // G4
        }
        return anchor - (line - 1) * 2 + 7 * octaveChange
    }
}

struct ScoreTime: Decodable, Equatable {
    let beats: String
    let beatType: String
    let visible: Bool
}

/// One measure of one staff, with only the attributes that change in it.
struct ScoreMeasure: Decodable {
    let number: Int
    let startBeat: Double
    let endBeat: Double
    let clef: ScoreClef?
    let fifths: Int?
    let time: ScoreTime?
    let barline: String
    let newSystem: Bool
    let events: [ScoreEvent]
}

struct ScorePart: Decodable, Identifiable {
    /// "S", "A", "T", "B", or "P<index>" beyond the fourth part.
    let voiceKey: String
    let voiceName: String
    let index: Int
    let notes: [ScoreNote]
    /// The part as engraved, measure by measure.
    let staff: [ScoreMeasure]

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
