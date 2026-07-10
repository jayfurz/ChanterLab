# CAT-01: Catalog Release Contract

Status: complete 2026-07-10; schema v1 approved as stable after independent
review and real-catalog validation. `BASE-00` completed at `e77ffa7`. Priority: P0.

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

## Implementation record (2026-07-10, approved and complete)

Implemented as `training-prototype/omr/release_descriptor.py` (read-only —
does not change where `ingest_catalog.py` writes) plus
`training-prototype/omr/RELEASE_SCHEMA.md` (the full field reference,
readiness policy, and compatibility policy) and
`training-prototype/omr/schema/release_descriptor.schema.json` (the
**authoritative** JSON Schema, enforced at runtime via the `jsonschema`
package).

**Amended after an owner review round that caught a real correctness bug**:
the first version resolved `manifest.json`'s `musicxml` field (which is
`"out/ingest/<id>.musicxml"`, relative to `omr_dir`) against `out_dir`
instead — a doubled path that would have silently hashed nothing for every
real entry. The original synthetic fixture happened to use the same wrong
convention, so tests passed despite being wrong; only running against the
real local catalog caught it. Fixed, and the fixture now matches production
path conventions exactly (confirmed by direct inspection of the real
catalog, not re-derived from source alone).

- **Contract fields:** `release_id` (time + a canonical `content_fingerprint`,
  not a mutable label), `parent_release_id`, provenance (see below), catalog
  input hash + source inventory hashes, manifest schema version (`1`) +
  compatibility policy, MusicXML/report/state/override inventories and
  hashes, tombstones (from `overrides/RETIRED`), trust status counts +
  confidence distribution, waivers (always `[]` — no waiver mechanism exists
  anywhere yet), verification evidence (only recorded when explicitly
  supplied), `integrity`/`manifest_validation` problem lists, and an explicit
  `readiness.promotable` gate with reasons.
- **Content fingerprint:** a single sha256 covering parser/app provenance,
  the raw catalog input hash, every content-section hash, and tombstones — the actual "same content, same
  identity" property, proven by test to (a) stay identical across builds a
  month apart in wall-clock time and (b) change when either the on-disk
  content OR the supplied parser SHA changes (provenance is part of the
  content identity, not decoration).
- **Provenance corrected:** `code.builder_git_sha`/`builder_dirty` are always
  derived from the actual running `release_descriptor.py` checkout (never
  from `--omr-dir`, which may point at data from a different checkout
  entirely). `code.parser_git_sha`/`app_git_sha` are **never inferred** from
  the builder SHA — explicit only (`--parser-sha`/`--app-sha`), `null`
  otherwise. Every real local catalog has these as `null` today, honestly,
  because `ingest_catalog.py` doesn't record its own git SHA at ingestion
  time yet — a real gap, noted as CAT-02 follow-up work, not papered over.
- **Path safety:** every manifest `musicxml` path and every state `pdf` path
  is resolved relative to `omr_dir` and required to stay contained within
  `omr_dir/out/ingest` / `omr_dir/pdfs/ingest` respectively — traversal,
  absolute paths, duplicate manifest ids, non-simple ids (path separators —
  unsafe to build a `<id>.report.json` filename from), and
  tombstone/active-override conflicts are all detected and reported under
  `integrity.problems`, proven with fixtures built to attempt each one.
- **Readiness/promotable gate:** a structurally valid descriptor can still be
  `readiness.promotable: false` — empty catalog, unknown provenance, a dirty
  builder tree, unrecorded/failed verification, or any
  `manifest_validation`/`integrity` problem all force it, each proven by
  test. An empty-catalog descriptor stays structurally valid for
  diagnostics; only promotability, not validity, is affected.
- **Manifest-published-only scope, made explicit:** `musicxml`/`reports`
  cover manifest-published (`accepted`) entries only — `state` is the full
  private working set (all statuses). Documented in both
  `RELEASE_SCHEMA.md` and the module/schema docstrings, not just implied.
- **Validation fails closed:** `schema/release_descriptor.schema.json`
  is enforced via the `jsonschema` package (new dependency, added to
  `training-prototype/omr/tests/README.md` and to
  `.github/workflows/unified-required-ci.yml`'s `omr-rights-safe` and
  `omr-private-corpus` pip-install steps — both authorized by the owner).
  Semantic checks JSON Schema can't express run on top in Python: aggregate
  inventory hashes/counts, the content fingerprint, and readiness are
  recomputed; release ID and timestamp consistency are checked; and every
  value is scanned for private paths. A serialized descriptor cannot claim
  different evidence while remaining valid.
- **Determinism:** proven by test — same fixture inputs produce identical
  `content_fingerprint` and every section hash across builds a month apart
  in wall-clock time (only `release_id`/`generated_at` differ, exactly as
  intended).
- **Test evidence:** `training-prototype/omr/tests/test_release_descriptor.py`,
  71 tests (up from 31), all against synthetic hand-made fixtures whose path
  conventions match real production data — 88 passed, 19 skipped
  (pre-existing, PDF-corpus-gated) in the full `training-prototype/omr`
  suite. Picked up automatically by the existing `omr-rights-safe` CI job.
- **Real-catalog validation (2026-07-10, read-only, no writes):** ran
  `release_descriptor.py --omr-dir /mnt/data/code/byzorgan-web/training-prototype/omr --strict`
  against the actual live local catalog — **valid, zero validation
  problems.** Manifest: 3,351 entries, all 3,351 resolving to a real
  MusicXML hash. Reports: 3,351, all hashed. `manifest_validation`: 3,351
  checked, 0 problems — every published entry's MusicXML parses and its
  report.json parses. `integrity`: 0 problems (no duplicate/non-simple ids,
  no path escapes, no tombstone conflicts — matches direct inspection
  showing zero active override files today). State: 3,793 records
  (`accepted` 3351, `review` 132, `no_music` 300, `type3` 10,
  `download_error`/`extract_error` 0). Confidence over accepted items: mean
  99.81%, median 100.0%, range 90.0–100.0%. Overrides: 0 active, 1 tombstone
  (`13c_cherubic_hymn-bortniansky-7`, matching the tracked `RETIRED` file).
  `readiness.promotable: false` — honestly, because `parser_git_sha`/
  `app_git_sha` weren't supplied and the builder tree had uncommitted work
  at the time (both expected in this state, neither a defect). `git status`
  on the real repo directory confirmed unchanged before/after (only the
  same two untracked files that predate this session).
- **Example:** `training-prototype/omr/tests/fixtures/release_descriptor/example_descriptor.json`,
  regenerated from the synthetic fixture with the new fields. Illustrative,
  not asserted by tests.
- **Compatibility matrix:** none yet — only schema v1 exists. "Current app
  can read current and previous schema" is satisfied trivially today because
  no app-facing consumer reads descriptors yet.
- **Not done here, by design:** no staging directory, pointer, or promotion
  mechanism (CAT-02, which should also wire `ingest_catalog.py` to record
  its own git SHA at ingestion time so `parser_git_sha` stops defaulting to
  unknown for freshly-ingested content); no publication-eligibility/
  attribution enforcement (RIGHTS-01, which depends on this schema existing
  first).

**Schema v1 approval recorded 2026-07-10.** The final review added
fail-closed recomputation of serialized inventory hashes/counts, the content
fingerprint, and readiness; included the raw catalog input in release
identity; and reran the complete synthetic and real-catalog evidence above.
CAT-02 is unblocked and may build atomic promotion on this contract.
