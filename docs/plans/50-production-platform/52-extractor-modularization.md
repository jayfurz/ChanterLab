# PROD-02: Vector Extractor Modularization

Status: blocked on `TRUST-02` and `TRUST-03`. Priority: P2.

Dependencies: confidence instrumentation and expanded semantic corpus.

Owned files: OMR extractor modules/tests. Exclusive OMR lane.

## Goal

Reduce the risk of the large extractor without changing emitted semantics.

## Proposed Boundaries

PDF/font/path ingestion; staff/system geometry; glyph normalization; event and
voice reconciliation; lyrics/sections; MusicXML emission; reporting/confidence.

## Steps

1. Record import graph, globals, data structures, and deterministic ordering.
2. Add characterization tests for internal stage contracts.
3. Extract one pure or low-coupling stage per commit.
4. Require byte-identical full private corpus unless a separately reviewed
   semantic fix is intentionally included.
5. Keep CLI and ingest callers compatible through the migration.
6. Measure runtime/memory and avoid abstraction in hot geometry loops without
   evidence.

## Acceptance

Each commit is corpus byte-identical or separately justified; determinism holds
across hash seeds; public/private tests pass; no circular imports; stage contracts
and extension points are documented; rollback is normal git reversion.

