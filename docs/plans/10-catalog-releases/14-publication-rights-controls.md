# RIGHTS-01: Publication And Attribution Controls

Status: core permission confirmed 2026-07-10; implementation steps below still
open. Priority: P0/P1.

Owner confirmed 2026-07-10 (see
[`training-prototype/omr/SOURCES.md`](../../../training-prototype/omr/SOURCES.md)):
permission covers public serving of the extracted MusicXML catalog
(`omr/out/ingest/*.musicxml`, `manifest.json`, the built-in
`content/*.musicxml` pieces) through the training app — already the case at
chanterlab.com. This does not extend to raw source PDFs/pages/OMR
intermediates, which remain local-only. This confirmation unblocks the
BASE-01 VPS-migration catalog-custody work; it does not by itself satisfy the
steps below (attribution completeness, takedown procedure, release validator
enforcement) — those remain open implementation work.

Dependencies: release contract for enforcement integration. Parallel-safe with
catalog implementation during policy clarification only.

Owned files: rights policy docs, release publication validator, attribution UI
contract. Do not edit parser behavior.

## Goal

Translate permission and provenance requirements into enforceable release gates.

## Steps

1. Inventory source/edition/composer/book/PDF attribution and permission evidence.
2. Record what may be served, linked, stored privately, or never published.
3. Define takedown/contact and incident procedures.
4. Add publication eligibility and attribution completeness to release metadata.
5. Fail publication when required permission/provenance is absent.
6. Verify every public library row and current-piece view retains attribution.

## Constraints

Public availability is not permission. This plan does not provide legal advice
or open user uploads. Never place permission documents containing private data
in public artifacts without review.

## Acceptance

Owner records the controlling permission decision; release validator enforces
eligibility; attribution is complete and tested; takedown can disable a piece
without rebuilding unrelated scores; private artifacts remain private.

