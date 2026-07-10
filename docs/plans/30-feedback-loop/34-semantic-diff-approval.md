# LOOP-04: Semantic Catalog Diff And Approval

Status: blocked on `CAT-02` and `LOOP-03`. Priority: P1.

Dependencies: immutable staged releases, ledger, corrections. Blocks: routine
safe parser rollout.

Owned files: release comparison engine, approval report/UI, promotion gate.

## Goal

Explain catalog changes musically before promotion rather than relying on hashes
or accepted counts.

## Diff Dimensions

Pieces added/removed/changed; notes and durations; part/voice topology; measures;
ties, beams, accidentals, divisi; lyrics/verses/sections; warnings/confidence;
status/trust; overrides/tombstones; manifest metadata and source identity.

## Steps

1. Define normalized MusicXML/ledger comparison semantics.
2. Group identical change signatures to expose systemic effects.
3. Link expected changes to reports/tests/corrections.
4. Block unexplained accepted-to-review, voice collapse, integrity decrease, or
   large churn.
5. Produce human-readable and machine-readable approval artifacts.
6. Require approval before the atomic promotion command can run.

## Acceptance

The Bortniansky-style change reads as named musical improvements, not only bytes;
unchanged formatting is distinguishable from semantics; waivers are explicit;
rollback diff is empty against the previous release; approval identity is stored.

