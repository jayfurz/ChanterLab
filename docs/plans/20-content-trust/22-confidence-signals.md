# TRUST-02: Multidimensional Confidence Signals

Status: complete 2026-07-11; implemented by `fd8ff5d`. Priority: P0/P1.

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

## Implementation Record

The parser report now carries the versioned `omr-confidence-vector-v1` contract
with 12 independently named signals and stable warning codes. Each signal keeps
raw evidence separate from policy. The existing `integrity_pct` field and the
`legacy-measure-integrity-v1` acceptance policy remain unchanged; adopting a
new acceptance policy or changing the approved quality-ledger schema reference
requires a separate reviewed decision.

Focused and private-corpus verification passed 184 tests with no failures or
skips. A clean full extraction produced the same 3,358 accepted, 125 review,
300 no-music, and 10 type-3 outcomes as the sealed production release. Its
manifest and all 3,793 state records were object-identical, all 3,358 served
MusicXML files were byte-identical, and every sealed legacy report field was
identical after excluding only the additive confidence fields and counters.

The corpus comparison also established the first signal baseline. Measure
consistency had a median of 1.0 and mean of 0.990002; glyph coverage had a
median of 1.0 and mean of 0.997133; lyric attachment had a median of 1.0 and
mean of 0.994696. Page-selection coverage had a median of 1.0 and mean of
0.778185, reflecting deliberate page selection rather than transcription
quality. Nonzero evidence appeared in 50 divisi reports, 333 pitch/accidental
reports, and 1,604 dropped/duplicate-event reports. These are descriptive
baselines, not acceptance thresholds.

The verified candidate was audit-only and was neither sealed nor promoted.
