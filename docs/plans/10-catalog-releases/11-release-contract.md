# CAT-01: Catalog Release Contract

Status: implemented 2026-07-10, awaiting owner approval (step 5) before the
schema is treated as stable. `BASE-00` completed at `e77ffa7`. Priority: P0.

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

## Implementation record (2026-07-10, pending owner approval)

Implemented as `training-prototype/omr/release_descriptor.py` (read-only —
does not change where `ingest_catalog.py` writes) plus
`training-prototype/omr/RELEASE_SCHEMA.md` (the full field reference and
compatibility policy) and `training-prototype/omr/schema/release_descriptor.schema.json`
(a formal JSON Schema reference copy; the enforced validator in code is
hand-rolled to avoid a new pip dependency).

- **Contract fields:** release_id (time + input-identity hash, not a mutable
  label), parent_release_id, parser/app git SHA (currently always equal —
  one monorepo commit — recorded as distinct fields for forward
  compatibility), catalog input hash + source inventory hashes, manifest
  schema version (`1`) + compatibility policy, MusicXML/report/state/override
  inventories and hashes, tombstones (from `overrides/RETIRED`), trust status
  counts + confidence distribution, waivers (always `[]` — no waiver
  mechanism exists anywhere yet), verification evidence (only recorded when
  explicitly supplied — never claims a check ran when it didn't).
- **Determinism:** proven by test, not just asserted — the same fixture
  inputs produce identical content hashes across two builds a month apart in
  wall-clock time (only `release_id`/`generated_at` differ, exactly as
  intended).
- **Fails closed:** `validate_descriptor()` flags every required-field
  omission, wrong `schema_version`, malformed `release_id`, and any
  `manifest_validation` problem. A private-local-path leak scanner rejects
  any string value matching `pdfs/ingest/`, `pdfs/survey/`, `.venv/`, or a
  local home-directory-style absolute path anywhere in the tree — proven
  with a fixture deliberately built to try to leak one.
- **All manifest entries resolve:** `manifest_validation` checks every
  manifest-listed entry's `.musicxml` exists and parses as XML and its
  `.report.json` exists and parses as JSON; proven against fixtures with a
  deliberately missing/corrupt file of each kind.
- **Fresh-checkout case:** proven directly — an empty `omr_dir` (the real
  state of every CI/public checkout, since `out/`/`pdfs/` are gitignored)
  produces an honest all-zero, still-schema-valid descriptor.
- **Test evidence:** `training-prototype/omr/tests/test_release_descriptor.py`,
  31 new tests, all against synthetic hand-made fixtures (never real
  copyrighted data) — 48 passed, 19 skipped (pre-existing, PDF-corpus-gated)
  in the full `training-prototype/omr` suite. Picked up automatically by the
  existing `omr-rights-safe` CI job (BASE-02) with zero new pip dependencies,
  so no `.github/workflows/` change was needed.
- **Example:** `training-prototype/omr/tests/fixtures/release_descriptor/example_descriptor.json`,
  generated from the checked-in synthetic fixture (safe to read — contains
  no real catalog data). Its `code.*_git_sha` reflects whatever commit was
  current when it was generated; illustrative, not asserted by tests.
- **Compatibility matrix:** none yet — only schema v1 exists. Policy for
  future versions is documented in RELEASE_SCHEMA.md (additive fields never
  bump `schema_version`; breaking changes do, plus a migration note here
  when that first happens). "Current app can read current and previous
  schema" is satisfied trivially today because no app-facing consumer reads
  descriptors yet — `manifest.json`'s own shape/path is unchanged.
- **Not done here, by design:** no staging directory, pointer, or promotion
  mechanism (CAT-02); no publication-eligibility/attribution enforcement
  (RIGHTS-01, which depends on this schema existing first).

**Awaiting explicit owner approval before this schema is treated as
stable** — CAT-02 should not build atomic promotion on it until that
approval is recorded here.
