# TRUST-05: Library Trust And Provenance UI

Status: ready; `TRUST-01` schema v1 and catalog IDs are available. Priority: P1.

Dependencies: immutable IDs and trust vocabulary. Parallel-safe with audit work;
conflicts with feedback-loop library changes.

Owned files: `training-prototype/js/library.js`, current-piece metadata in
`main.js`/`state.js`, `index.html`, `style.css`, browser tests.

## Goal

Show useful provenance and trust without turning the library into a warning
dashboard or implying auto-imported scores are human verified.

## Scope

1. Retain immutable score/release/status fields when loading the manifest.
2. Show restrained labels for auto-imported, verified, known issue, and override.
3. Make source PDF, composer/book/edition, parser release, and known issue
   accessible from the current piece.
4. Add trust/status filtering only if user research shows it aids selection.
5. Preserve windowed-list performance and mobile reachability.

## Acceptance

Labels use approved vocabulary; missing data does not become verified; original
PDF remains one click away; screen reader names are useful; 3,000+ item search
stays within the performance budget; desktop/mobile screenshots have no overlap.
