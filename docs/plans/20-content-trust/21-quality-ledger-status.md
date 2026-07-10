# TRUST-01: Quality Ledger And Status Schema

Status: blocked on `CAT-01`. Priority: P0.

Dependencies: immutable release/score identity. Blocks: reports, review UI,
provenance UI, human audit.

Owned files: new ledger schema/storage, release integration, schema tests.

## Goal

Record what is known about every score without conflating structural acceptance
with human verification.

## Required Fields

- Immutable score/source/release IDs and parser SHA.
- Source hash, title/composer/book/edition/PDF provenance.
- Status: auto-imported, human-verified, known-issue, review-required,
  manual-override, or retired.
- Confidence vector reference and warning summary.
- Reviewer/evidence timestamps without exposing private identities publicly.
- Override and tombstone history.
- Parent/previous score identity for diffs.

## Steps

1. Inventory current state/manifest/override semantics.
2. Define transitions, authorized actors, and invalid states.
3. Define compatibility and migration for the active catalog.
4. Add deterministic validation and transition tests.
5. Generate a candidate ledger and reconcile every manifest entry.
6. Obtain owner approval before promotion.

## Acceptance

Every active score has exactly one valid status; transitions are audited; manual
overrides and retired overrides cannot conflict; missing provenance fails the
appropriate publication gate; current and previous schema remain readable.

