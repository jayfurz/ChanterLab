# One-App Convergence Orchestrator

Status: deferred until the practice shell, content contracts, and production
baseline are stable.

Roadmap IDs: `ONEAPP-01` through `ONEAPP-03`.

Objective: give Byzantine and Western scores one library/transport/practice
experience while preserving notation-specific theory, rendering, and timing.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`61-common-timed-score-contract.md`](61-common-timed-score-contract.md) | blocked on stable practice/scoring contracts |
| 2 | [`62-byzantine-practice-integration.md`](62-byzantine-practice-integration.md) | blocked on 61 |
| 3 | [`63-wasm-dsp-psola-integration.md`](63-wasm-dsp-psola-integration.md) | evidence-gated, may remain deferred |

## Hard Constraint

Do not flatten Byzantine relative/microtonal semantics into Western MIDI or
force Western multipart assumptions into chant. The common layer is a timed
practice contract, not a universal notation model.

## Completion

Both score types open from one library, use one transport/practice/scoring shell,
retain correct notation and tuning semantics, and pass their original regression
suites. Legacy surfaces remain rollback-capable through migration.

