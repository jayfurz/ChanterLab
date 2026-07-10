# TRUST-03: Golden Corpus And Rights-Safe Fixtures

Status: ready after `BASE-02`. Priority: P0/P1.

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

