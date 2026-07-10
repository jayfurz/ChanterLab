# BASE-02: Unified Required CI

Status: complete 2026-07-10. Priority: P0.

Dependencies: canonical branch/deploy model. Blocks: all implementation waves.

Owned files: `.github/workflows/`, rights-safe committed fixtures, test runners.

## Goal

Make a fresh checkout prove the public application baseline and clearly report
what private copyrighted validation did or did not run.

## Scope

1. Run Rust tests, scoring tests, detector A/B thresholds, fake-mic browser
   verification, browser smoke, and rights-safe OMR tests.
2. Add a second committed synthetic or permission-safe score for real switching.
3. Exercise desktop and phone viewports with console/network/page-error budgets
   and nonblank score/scope pixel checks.
4. Publish exact pass/fail/skip counts.
5. Define a private/self-hosted corpus job without exposing artifacts.
6. Mark the workflow required on the chosen branch.

## Non-Goals

CI does not certify iOS routing, audible quality, private corpus correctness when
fixtures are absent, catalog promotion, or rights permission.

## Acceptance

- Fresh checkout performs a real two-score switch.
- Public gates cannot silently pass through missing dependencies or fixtures.
- Private OMR absence is labeled `not corpus verified`, not success.
- Browser gates cover load, library, voice, play/stop, loop, scoring, and error
  budgets at phone and desktop sizes.
- Stable detector thresholds fail on accuracy/cadence/onset/dropout regressions.
- Required status checks are documented and enabled.

## Verification

Run every workflow command locally once, then validate the pull-request workflow
on a clean branch. Include workflow URLs and exact test counts in handoff.

## Completion record (2026-07-10)

Implemented as `.github/workflows/unified-required-ci.yml` (nine jobs: `rust`,
`root-js`, `training-scoring`, `omr-rights-safe`, `omr-private-corpus`,
`detector-thresholds`, `fake-mic-verify`, `browser-gate`, `required-gate`),
landed via [PR #95](https://github.com/jayfurz/ChanterLab/pull/95), merged as
`4679bbb2a12aa9f7d2980492f195235b05c030ad`. Supersedes `training-smoke.yml`
(deleted; its exact `smoke.mjs` invocation now runs inside `browser-gate`).

- **Second committed score:** `training-prototype/content/control_unison_ii.musicxml`
  (id `control2`), distinct key/melody from `control`. `smoke.mjs` and the new
  `training-prototype/tests/browser-gate.mjs` now perform a REAL cross-piece
  switch on every fresh checkout (previously CI-only reselected the same piece).
- **Browser gate:** `browser-gate.mjs` runs the full load -> library
  search+select -> voice switch -> play/stop -> a real loop wrap (proven by
  watching `#posOut` reach the loop-end measure and wrap back, not just that
  the checkbox is checked) -> a real fake-mic scoring lap, at both a desktop
  (1400x900) and phone (390x844, `isMobile`/`hasTouch` emulation) viewport,
  with a genuine per-pixel nonblank check on `#scope` (canvas `getImageData`)
  and a structural nonblank check on `#osmd`'s rendered SVG. Console/network/
  page-error budgets mirror `smoke.mjs`'s existing reconciliation.
- **Detector thresholds:** `detector-ab.mjs` gained a CI gate (previously
  report-only) — thresholds for folded-cents accuracy, octave-error rate,
  voiced coverage, cadence, glide tracking, and onset latency, calibrated from
  a real local run (`accFolded` js/wasm 0.07-4.3¢, octaveRate 0%, cadence
  ~60-62Hz, onset 9.3/36.0ms) with headroom for cross-runner jitter. CPU stays
  informational only, never gated (Audio Gate: not a device number off a
  controlled runner).
- **Fake-mic verification:** `detector-verify.mjs` promoted from "NOT part of
  CI, dev-box only" to a required job (`fake-mic-verify`) — both `js` and
  `wasm` detector modes, real Chromium fake-mic flags, headless.
- **OMR rights-safe counts (this run, no local PDF corpus):** 36 collected,
  17 passed, 19 skipped, 0 failed — exact `pytest -v` summary published to the
  job's step summary every run, not just asserted internally.
- **Private-corpus job:** `omr-private-corpus` runs on `ubuntu-latest` (no
  self-hosted runner is registered for this repo — checked via
  `gh api repos/.../actions/runners`, `total_count: 0`); it checks for
  `training-prototype/omr/pdfs/ingest/` and explicitly publishes
  "NOT CORPUS VERIFIED" (informational, never blocks `required-gate`) rather
  than silently reporting success. Wiring a real self-hosted runner with the
  corpus checked out is a follow-on owner decision, not done here.
- **Container publication gate:** `container-image.yml` now triggers on
  `workflow_run` of `unified-required-ci` completing with
  `conclusion == 'success'`, checks out and tags the image with
  `github.event.workflow_run.head_sha` (the exact validated commit), instead
  of firing independently on every push to `main`.
- **Branch protection:** `main` now requires the single `required-gate` status
  check (`gh api .../branches/main/protection`, `required_status_checks:
  {strict: false, contexts: ["required-gate"]}`, `enforce_admins: false`, no
  PR-review requirement — matches this repo's existing single-maintainer
  workflow; no branch protection existed before this).
- **Post-merge proof:** `Unified Required CI` and `Publish ChanterLab
  Container` both re-ran on the actual merge commit `4679bbb` (not just the
  PR branch), confirming the `workflow_run` chain fires correctly end to end
  on `main` itself.
- **Known follow-up, out of this plan's scope:** `pages.yml`'s own `test` job
  duplicates the `rust`/`root-js` checks (unrelated legacy Pages site,
  deliberately left untouched to avoid touching a separate live deployment
  target). `container-image.yml`'s `workflow_dispatch` manual-SHA override
  path is untested (only the automated `workflow_run` path was exercised for
  real).

