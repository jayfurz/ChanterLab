# TRUST-03: Golden Corpus And Rights-Safe Fixtures

Status: complete 2026-07-11. Priority: P0/P1.

Dependencies: required CI. Parallel-safe with ledger design under disjoint files.

Owned files: OMR tests, synthetic/permission-safe fixtures, expectation metadata.

## Goal

Cover parser behavior by engraving feature and semantic truth, including cases
that can run in public CI and private copyrighted edge cases.

## Scope

1. Build a feature matrix: font family, 1/2/4 staves, shared voices, chords,
   dots, rests, beams, flags, ties, accidentals, divisi, verses, above/below
   lyrics, rubrics, sections, layout switches, and refusal cases.
2. Map existing fixtures and identify gaps.
3. Create minimal rights-safe PDFs or document permission for committed inputs.
4. Add semantic assertions before byte hashes.
5. Keep private fixtures referenced by source hash and local path only.
6. Add a documented process for turning a confirmed field defect into a fixture.

## Acceptance

Public CI exercises every high-risk decision class feasible synthetically;
private tests report exact availability; each golden piece states why it exists;
hash re-blessing cannot bypass semantic checks; no protected artifact is tracked.

## Verification

Run the suite once with all private fixtures and once in a clean public-style
checkout, recording pass and skip counts for both.

## Implementation Record

`tests/golden_fixtures.json` now defines the versioned feature matrix, fixture
purpose, rights boundary, and source sha256 for all 11 private golden pieces.
It covers every requested feature. All high-risk decision classes feasible
without protected engraving run in public semantic tests; mid-piece layout
switching is explicitly private-only and covered by three real pieces.

Public fixtures construct four-part MusicXML models and assert chords, dots,
rests, beams, flags, ties, accidentals, divisi voice 2, verses, sections,
staff ownership, font routing, and lyric/rubric decisions by meaning rather
than byte hash. Blank and prose-only PDFs are generated at test time and must
be refused with exit code 3 and no output artifacts. No binary fixture or
protected derivative is tracked.

Verification on 2026-07-11 passed 200 tests with all private PDFs present and
passed 170 (as of closing commit a73b4b9; later unrelated merges grew the
suite) with exactly 30 declared private-only skips after removing the
private corpus from the checkout. The documented defect workflow requires a
semantic regression before re-blessing; `--bless` cannot modify or bypass the
public semantic tests.
