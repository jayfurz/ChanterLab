# Practice And Audio Orchestrator

Status: ready after `BASE-02`; scoring policy and device releases have owner gates.

Roadmap IDs: `PRACTICE-01` through `PRACTICE-04`, plus `AUDIO-01`.

Objective: deepen repeated practice while preserving the calm interface and the
measured reliability of the current audio path.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`41-transport-characterization-practice.md`](41-transport-characterization-practice.md) | ready after CI |
| 2 | [`42-target-range-transpose.md`](42-target-range-transpose.md) | blocked on 41 |
| 2 | [`43-local-persistence-history.md`](43-local-persistence-history.md) | schema design parallel-safe; UI integration serialized |
| 3 | [`44-scoring-v2.md`](44-scoring-v2.md) | owner policy gate |
| 1 | [`45-audio-reliability-benchmarks.md`](45-audio-reliability-benchmarks.md) | separate lane after CI |

## Collision Rules

Plans touching `transport.js`, `main.js`, `scope.js`, `scoring.js`, `index.html`,
or `style.css` must be sequential unless interfaces and exclusive ownership are
recorded. Audio and scoring share timing samples; freeze that contract before
parallel edits.

## Singer Checkpoint

Every user-facing practice/scoring batch requires owner/singer field testing on
real repertoire before completion. Audio releases additionally require the real
device matrix in `00-acceptance-gates.md`.
