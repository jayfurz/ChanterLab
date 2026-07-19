# One-App Convergence Orchestrator

Status: active. ONEAPP-01 completed and owner-approved 2026-07-19; ONEAPP-02
is gated only on practice scoring v1 (#44) stabilizing.

Roadmap IDs: `ONEAPP-01` through `ONEAPP-03`.

Objective: give Byzantine and Western scores one library/transport/practice
experience while preserving notation-specific theory, rendering, and timing.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`61-common-timed-score-contract.md`](61-common-timed-score-contract.md) | complete (owner approved 2026-07-19; PRs #131/#133/#134) |
| 2 | [`62-byzantine-practice-integration.md`](62-byzantine-practice-integration.md) | ready once scoring v1 (#44) stabilizes |
| 3 | [`63-wasm-dsp-psola-integration.md`](63-wasm-dsp-psola-integration.md) | evidence-gated, may remain deferred |

## Hard Constraint

Do not flatten Byzantine relative/microtonal semantics into Western MIDI or
force Western multipart assumptions into chant. The common layer is a timed
practice contract, not a universal notation model.

## Completion

Both score types open from one library, use one transport/practice/scoring shell,
retain correct notation and tuning semantics, and pass their original regression
suites. Legacy surfaces remain rollback-capable through migration.

