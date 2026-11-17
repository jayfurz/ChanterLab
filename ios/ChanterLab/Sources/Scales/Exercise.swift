import Foundation

/// A sung drill: hold each target degree, in tune, until its bar fills.
/// Same drills, tolerance and scoring as the web app's exercise mode.
struct Exercise: Identifiable, Hashable {
    struct Step: Hashable {
        let label: String
        let degree: String
        /// Octaves above the reference Ni.
        let octave: Int
        let holdSeconds: Double
    }

    let id: String
    let title: String
    /// Label of the Byzantine preset the drill is sung on.
    let preset: String
    let isonDegree: String
    /// In-tune window, ± moria.
    let tolerance: Double
    let steps: [Step]

    static let all: [Exercise] = {
        let scale = ["Ni", "Pa", "Vou", "Ga", "Di", "Ke", "Zo"]
        let ascent = scale.map { Step(label: $0, degree: $0, octave: 0, holdSeconds: 1.4) }
            + [Step(label: "Ni′", degree: "Ni", octave: 1, holdSeconds: 1.6)]
        let descent = [Step(label: "Ni′", degree: "Ni", octave: 1, holdSeconds: 1.4)]
            + scale.dropFirst().reversed().map { Step(label: $0, degree: $0, octave: 0, holdSeconds: 1.4) }
            + [Step(label: "Ni", degree: "Ni", octave: 0, holdSeconds: 1.6)]
        let chromatic = ["Pa", "Vou", "Ga", "Di", "Ga", "Vou", "Pa"]
            .map { Step(label: $0, degree: $0, octave: 0, holdSeconds: 1.8) }
        return [
            Exercise(id: "match-ni", title: "Match Ni", preset: "Diatonic", isonDegree: "Ni", tolerance: 4,
                     steps: [Step(label: "Hold Ni", degree: "Ni", octave: 0, holdSeconds: 4)]),
            Exercise(id: "diatonic-ascent", title: "Diatonic Ascent", preset: "Diatonic", isonDegree: "Ni",
                     tolerance: 4, steps: ascent),
            Exercise(id: "diatonic-descent", title: "Diatonic Descent", preset: "Diatonic", isonDegree: "Ni",
                     tolerance: 4, steps: descent),
            Exercise(id: "hard-chromatic-pa", title: "Hard Chromatic Pa", preset: "Hard Chromatic",
                     isonDegree: "Pa", tolerance: 4, steps: chromatic),
        ]
    }()
}

/// Progress through one exercise.
struct ExerciseRun {
    struct StepStats {
        var voiced = 0.0
        var inTune = 0.0
        var absError = 0.0
    }

    let exercise: Exercise
    private(set) var stepIndex = 0
    private(set) var stats: [StepStats]
    var running = false
    private(set) var finished = false
    /// Signed distance from the target in moria, while singing.
    private(set) var liveError: Double?

    init(_ exercise: Exercise) {
        self.exercise = exercise
        stats = Array(repeating: StepStats(), count: exercise.steps.count)
    }

    var step: Exercise.Step? { exercise.steps.indices.contains(stepIndex) ? exercise.steps[stepIndex] : nil }

    var progress: Double {
        guard let step else { return 1 }
        return min(1, stats[stepIndex].voiced / step.holdSeconds)
    }

    /// In-tune share of voiced time, less 4 points per moria of average error beyond 1.
    var score: Int {
        let voiced = stats.reduce(0) { $0 + $1.voiced }
        guard voiced > 0 else { return 0 }
        let inTunePct = stats.reduce(0) { $0 + $1.inTune } / voiced * 100
        let averageError = stats.reduce(0) { $0 + $1.absError } / voiced
        return Int((inTunePct - max(0, averageError - 1) * 4).clamped(to: 0...100).rounded())
    }

    var verdict: String {
        switch score {
        case 90...: return "Excellent"
        case 75...: return "Passing"
        case 55...: return "Developing"
        default: return "Needs reps"
        }
    }

    /// Feed `dt` seconds of singing at `hz` against a target at `targetHz`
    /// (nil when the singer is silent). Returns true when the exercise just finished.
    mutating func sing(hz: Double?, targetHz: Double, dt: Double) -> Bool {
        guard running, !finished, let step else { return false }
        guard let hz, hz > 0, targetHz > 0 else { liveError = nil; return false }
        // Any octave counts: fold the error into ±36 moria.
        var error = 72 * log2(hz / targetHz)
        error -= 72 * (error / 72).rounded()
        liveError = error
        stats[stepIndex].voiced += dt
        stats[stepIndex].absError += abs(error) * dt
        if abs(error) <= exercise.tolerance { stats[stepIndex].inTune += dt }
        guard stats[stepIndex].voiced >= step.holdSeconds else { return false }
        liveError = nil
        if stepIndex + 1 < exercise.steps.count {
            stepIndex += 1
            return false
        }
        running = false
        finished = true
        return true
    }
}

private extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double { Swift.min(range.upperBound, Swift.max(range.lowerBound, self)) }
}
