# BASE-02: Unified Required CI

Status: ready. Priority: P0.

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

