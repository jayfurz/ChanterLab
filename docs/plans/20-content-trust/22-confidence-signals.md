# TRUST-02: Multidimensional Confidence Signals

Status: ready; `TRUST-01` schema v1 approved 2026-07-11. Priority: P0/P1.

Dependencies: ledger schema. Blocks: trust UI, review prioritization, uploads.

Owned files: parser reporting/confidence modules and focused OMR tests. Exclusive
lock on `vector_extract.py` if changes there are unavoidable.

## Goal

Replace measure-integrity shorthand with explicit signals that identify why a
score is trusted or needs review.

## Signals

Measure consistency, voice topology, staff/system confidence, unresolved music
glyphs, pitch/accidental ambiguity, tie/beam ambiguity, whole-rest normalization,
divisi decisions/drops, lyric coverage/borrowing/contamination, event drops or
duplicates, page-selection confidence, and override status.

## Steps

1. Inventory existing stats/warnings and map each to a stable signal name.
2. Define raw evidence separately from policy thresholds.
3. Preserve the existing integrity field during migration.
4. Add signal-level semantic fixtures for known failure classes.
5. Run full private corpus and compare distributions before policy changes.
6. Propose acceptance/review policy as a separate owner-reviewed configuration.

## Acceptance

Signals are deterministic, versioned, explainable, and independently testable;
no score changes status merely because fields were added; policy changes produce
an explicit candidate diff; unexplained distribution shifts block completion.
