# CAT-02: Atomic Build, Promotion, And Rollback

Status: blocked on `CAT-01`. Priority: P0.

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

