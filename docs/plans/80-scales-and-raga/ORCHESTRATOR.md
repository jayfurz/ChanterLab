# Scales App And Raga Practice Orchestrator

Status: active. Owner approved this lane on 2026-07-11 (route option A; RAGA-01
and RAGA-02 greenlit). SCALES-01/RAGA-01/RAGA-02 shipped 2026-07-11 (PRs #109,
#110, #112); the field-test checkpoint below is the remaining gate.

Tracking: epic #126.

Roadmap IDs: `SCALES-01`, `RAGA-01` through `RAGA-04`.

Objective: re-expose the legacy Byzantine scales app (`web/`) on the brand
hosts, then extend it with Indian raga practice — presets, sargam labels, and a
tanpura drone — without touching the locked training-app lanes.

## Why This Lane Exists

The legacy scales app never left the production image; host routing hides it on
chanterlab.com (`server/byzorgan-web-server.py`). Full convergence is
`ONEAPP-02` (Wave 5, blocked). This lane ships practice value now on files no
other active lane owns: `web/` app code and the server routing rule. It also
derisks `ONEAPP-02`: the `/scales/` route is the legacy rollback route that
plan's step 6 assumes, and raga presets exercise the engine's `Genus::Custom`
path end-to-end.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`81-scales-route.md`](81-scales-route.md) | shipped (PR #109); lane field-test gate open |
| 2 | [`82-raga-presets-sargam.md`](82-raga-presets-sargam.md) | shipped (PR #110); lane field-test gate open |
| 3 | [`83-tanpura-drone.md`](83-tanpura-drone.md) | shipped (PR #112); lane field-test gate open |
| 4 | `RAGA-03` sargam/alankar exercises | ready |
| R | `RAGA-04` vakra ragas, gamaka, shruti-true tuning | research, deferred |

## Collision Rules

- This lane owns `web/app.js`, `web/index.html`, `web/style.css`, `web/ui/*`,
  `web/audio/*`, and the raga preset/label modules it adds. It must NOT touch
  `training-prototype/` app files (`js/transport.js`, `js/main.js`, `scope.js`,
  `scoring.js`, training `index.html`/`style.css`).
- `server/byzorgan-web-server.py` changes serialize with any other server or
  entrypoint work.
- Rust `src/` changes are limited to wasm-bindgen exports needed to reach the
  existing `Genus::Custom`; tuning-engine semantics do not change in this lane.
- `web/pkg`/`web/pkg-worklet` are build artifacts (untracked); rebuild locally
  and in CI/Docker, never commit them.
- 82 and 83 both edit `web/app.js` and `web/index.html`: run them sequentially.

## Owner Gates And Checkpoints

- No bundled third-party audio samples without a recorded license decision
  (global rights rule); the tanpura v1 is synthesized.
- Raga preset intervals ship 12-ET-snapped first; shruti-true variants need a
  named source reference before shipping (RAGA-04).
- Field-test checkpoint: the owner's intended raga user reviews preset naming
  (Hindustani/Carnatic), default tanpura tuning, and label behavior before this
  lane is marked done.

## Completion

The lane is complete when the scales app is reachable at `/scales/` on the
brand hosts with regression coverage, raga presets and sargam labels work on
mobile and desktop without disturbing Byzantine behavior, the tanpura holds a
stable tempo-locked cycle against the detected voice, and the field-test
checkpoint is recorded.
