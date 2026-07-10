# CAT-01: Catalog Release Contract

Status: ready. `BASE-00` completed at `e77ffa7`. Priority: P0.

Dependencies: baseline commit. Blocks: atomic promotion, trust ledger, reports.

Owned files: new release schema/tooling docs and narrowly scoped ingest helpers.

## Goal

Define immutable identities and contents for catalog releases before changing
where ingestion writes.

## Required Contract

- Release ID derived from time plus code/input identity, not a mutable label.
- Parser and application git SHA.
- Catalog input hash and source inventory hashes.
- Manifest schema version and compatibility policy.
- State, MusicXML, reports, summary, overrides, and tombstone inventories/hashes.
- Trust/status counts and confidence distributions.
- Approved waivers and verification evidence.
- Parent release ID for semantic diff and rollback.

## Steps

1. Inventory current manifest/state/report consumers and path assumptions.
2. Draft schema plus current/previous compatibility rules.
3. Add schema validation and deterministic serialization tests.
4. Generate a release descriptor from the current catalog without promotion.
5. Obtain owner approval before treating the schema as stable.

## Acceptance

The same inputs produce the same content hashes; all manifest entries resolve to
parseable MusicXML and reports; current app can read current and previous schema;
private paths are not leaked; descriptor validation fails closed.

## Handoff

Report schema, examples using nonprivate data, compatibility matrix, migrations,
test evidence, and owner-approved frozen version.
