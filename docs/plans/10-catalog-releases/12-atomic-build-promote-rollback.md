# CAT-02: Atomic Build, Promotion, And Rollback

Status: complete 2026-07-10. Priority: P0.

Dependencies: frozen release contract. Blocks: production quality loop and PWA.

Owned files: ingestion/release commands, deployment pointer, validation tests.

## Goal

Build complete catalog candidates outside the served path and make promotion or
rollback a single atomic pointer/rename operation.

## Steps

1. Refactor ingestion output into a unique staging release directory.
2. Refuse promotion until descriptor, manifest, MusicXML, report, and inventory
   validation pass.
3. Generate semantic/count/confidence diffs against the active release.
4. Add an explicit approval boundary before pointer switch.
5. Retain at least the active and previous releases.
6. Add failure injection proving interrupted extraction never becomes active.
7. Smoke the candidate through the real app before and after promotion.
8. Switch back and verify exact prior hashes.

## Constraints

Code deployment and catalog promotion are separate. Never write candidate files
into the active release. Do not delete old releases during the first rollout.

## Acceptance

Interrupted builds are invisible; promotion and rollback are atomic; previous
hashes survive; app reads candidate and previous schemas; overrides/tombstones
are release-scoped; production smoke identifies the served release ID.

## Implementation record (2026-07-10)

- ChanterLab PR #99 merged at `61871cf`; the public-smoke edge fix in PR #100
  merged at `13e5e01`. Infra PR #5 merged publisher/rollback tooling at
  `242137f`; infra PR #6 deployed the exact gated image at `db792e9`.
- `catalog_release.py` implements unique staging, explicit parser/app
  provenance, candidate-bound verification, immutable sealing, actual-file
  revalidation, semantic/count/confidence diffs, exact approval tokens,
  atomic `current`/`previous` symlinks, rollback, and HTTP release smoke.
  `ingest_catalog.py --candidate-dir` redirects every generated artifact and
  refuses a dirty/mismatched parser checkout. Defaults remain compatible for
  nonrelease local workflows.
- Releases contain `out`, release-scoped overrides/tombstones, four approved
  built-ins, verification evidence, descriptor, and a public minimal
  `release.json`. PDFs are shared inputs only and never enter a release/PVC.
- The production publisher accepts only a sealed release, checks every byte
  after transfer, launches the exact target image in a disposable pod bound
  directly to the candidate, and only then replaces one pointer. The server
  exposes only manifest, MusicXML, and the public marker; descriptor, reports,
  state, overrides, and all source material remain denied.
- Failure-injection tests stop immediately before `current` replacement and
  prove the prior target/hash remains active. Synthetic promotion/rollback
  tests restore exact prior MusicXML hashes. The release lifecycle suite grew
  the rights-safe OMR run to 100 passed / 19 skipped; with the private corpus,
  the initial real release recorded 119 passed / 0 skipped / 0 failed.
- Initial production release:
  `rel-20260710T200845Z-d1d822d75972`, fingerprint
  `d1d822d759726913635ce31b854485c2d59d214842f1d763fb04b3bde645b3de`.
  It contains 3,351 manifest MusicXML files, 3,351 reports, 3,793 state
  records, and four built-ins; descriptor/integrity problems are both zero.
- Candidate Docker smoke passed the real desktop/mobile browser gate with
  library selection, voice switching, looping, scoring, and nonblank canvas.
  After GitOps deployment, all three public hostnames reported the exact
  release ID and 3,351 entries; the live desktop/mobile browser gate passed
  with zero unexpected errors. The pod was healthy with zero restarts.
- Production rollback was rehearsed with byte-identical release
  `rel-20260710T202424Z-d1d822d75972`: candidate smoke, atomic promotion, and
  three-host live smoke passed; rollback restored the initial release and all
  three hosts re-reported its exact ID. The rehearsal release is retained as
  `previous`. Legacy PVC `out`/`content` were not deleted during rollout.
- Code deployment and catalog promotion remained separate throughout: the
  sealed pointer was installed while the legacy pod still served its old
  paths; only afterward did GitOps deploy the current-pointer-aware image.
- **Deployment reconciliation (2026-07-10):** infra PR #7 advanced the
  GitOps image pin to app `main` `f275d67`; Argo reconciled infra revision
  `4716630` as `Synced/Healthy`, and the VPS deployment reported one ready
  `f275d67` replica with zero restarts. This is a runtime-image alignment,
  not a catalog reseal: the active immutable descriptor continues to name
  `61871cf`, the app revision used to seal that catalog release.

Operational commands and first-import details are in
`training-prototype/omr/RELEASE_RUNBOOK.md`.
