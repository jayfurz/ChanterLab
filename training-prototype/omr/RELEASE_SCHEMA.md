# Catalog release descriptor — schema v1 (CAT-01)

Status: schema v1 approved as stable on 2026-07-10 after independent review,
synthetic mutation testing, the full OMR suite, and read-only validation of
all 3,351 published catalog entries. CAT-02 may build on this contract.

## What this is

A **release descriptor** is a small, immutable JSON document that describes
one snapshot of the local OMR ingest catalog: what code produced it, what it
contains, whether it's internally consistent, and whether it's safe to
promote — without moving, copying, or promoting anything. Generating one is
always safe to run against a live `out/ingest/` directory; it only reads.

This is deliberately narrower than full catalog promotion (CAT-02). CAT-01's
job is to define *what a release IS* — a stable identity and content
contract — before CAT-02 changes *where ingestion writes* to build on it.

Build one:

```sh
cd training-prototype/omr
.venv/bin/python release_descriptor.py                 # print to stdout
.venv/bin/python release_descriptor.py --out rel.json   # write to a file
.venv/bin/python release_descriptor.py --strict         # nonzero exit on
                                                         # any STRUCTURAL
                                                         # validation problem
.venv/bin/python release_descriptor.py \
    --parser-sha <sha> --app-sha <sha>                  # explicit provenance
                                                         # — see "code" below
```

`--strict`'s exit code reflects **structural validity** (`validate_descriptor()`
— JSON Schema conformance plus the semantic checks below), not promotability.
A structurally valid descriptor can still be `readiness.promotable: false` —
see Readiness below. `--strict` never fails on that; check `readiness`
yourself if you need to gate on it.

On a fresh checkout (the common case — `out/` and `pdfs/` are gitignored,
copyrighted-derived material, never committed) this still produces a valid
descriptor: every count is honestly `0`, `catalog_present`/`manifest.present`
are `false`, nothing is fabricated — and `readiness.promotable` is `false`
with a clear reason. See `tests/fixtures/release_descriptor/` for a worked
example against small synthetic (non-copyrighted) data, whose path
conventions were confirmed to match the real local catalog by direct
inspection, and
`tests/fixtures/release_descriptor/example_descriptor.json` for its exact
output.

## Field reference

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Always `1` for this document. See Compatibility below. |
| `release_id` | string | `rel-<UTC timestamp>-<content_fingerprint prefix, 12 hex chars>`. Derived from time + a canonical content fingerprint — never a mutable human label, never hand-edited. |
| `content_fingerprint` | string (64 hex chars) | sha256 over parser/app provenance, the raw catalog input hash, every content-section hash (source inventory, manifest, MusicXML, reports, state, overrides), and the tombstone list. **The** identity of "what this release actually contains" — the same content always produces the same fingerprint; different content collides only with cryptographically negligible probability. `validate_descriptor()` recomputes it and checks that `release_id`'s suffix is its first 12 hex characters. |
| `parent_release_id` | string \| null | The release this one supersedes, for semantic diff/rollback. `null` for the first release, or when generating a standalone descriptor with no promotion history yet (CAT-01's own tooling always passes `null` unless `--parent` is given — CAT-02 owns actually tracking release lineage). |
| `generated_at` | string (ISO 8601 UTC) | When this descriptor was built. Informational only — never used for identity or content hashing. |
| `code.builder_git_sha` | string \| null | git SHA of the code checkout that is **actually running `release_descriptor.py` right now** — derived from this file's own location (`__file__`), never from `--omr-dir`. These can genuinely differ: you can point `--omr-dir` at data produced by a completely different checkout. |
| `code.builder_dirty` | bool \| null | `true` if the builder's git tree has uncommitted changes at build time; `null` if it couldn't be determined. A promotable descriptor requires this to be exactly `false` — see Readiness. |
| `code.parser_git_sha` | string \| null | git SHA of the code that actually **produced** the on-disk MusicXML/reports being described. **Never inferred from `builder_git_sha`** — the ingestion run that produced this data may have happened days or weeks before this descriptor is built, at a different commit. Explicit only (`--parser-sha`), or `null`/unknown. Every historical local catalog has this as `null` today — `ingest_catalog.py` itself doesn't record its own git SHA at ingestion time yet (a real gap; wiring that up is a natural CAT-02 follow-up, not done here). |
| `code.app_git_sha` | string \| null | git SHA of the app code this release is intended for. Same reasoning and same default (`null`) as `parser_git_sha`. |
| `input.catalog_present` | bool | Whether `pdfs/survey/catalog.json` (the cached upstream Antiochian catalog — the raw API response body, a flat JSON array) exists locally. |
| `input.catalog_input_hash` | string \| null | sha256 of the canonicalized (sorted-keys, no whitespace) catalog JSON, shape-agnostic. `null` if absent. |
| `input.source_inventory` | array | One entry per ingest-state record: `{id, source_url, pdf_sha256}`. `source_url` is the public Antiochian blob URL (same value already published in `manifest.json`'s `pdfUrl`). `pdf_sha256` proves which source bytes were used **without** revealing where they live on this machine — resolved and containment-checked against `omr_dir/pdfs/ingest/`; a path that fails containment is rejected (see `integrity`) and hashed as `null`, never followed. |
| `input.source_inventory_hash` | string | sha256 of the canonicalized inventory array. |
| `manifest.present` / `.entry_count` / `.hash` | | Whether `manifest.json` exists, its entry count, and a canonical-content hash. **Manifest-published (`accepted`) entries only** — see the scope note below. |
| `musicxml.count` / `.hash` / `.per_entry` | | Per-manifest-entry sha256 of the emitted `.musicxml` file, resolved relative to `omr_dir` (the manifest's `musicxml` field is `"out/ingest/<id>.musicxml"`, not a bare filename) and containment-checked against `omr_dir/out/ingest/`; `null` if missing or if the path fails containment (see `integrity`/`manifest_validation`). **Manifest-published entries only** — `ingest_state.json` tracks a larger private working set (`review`/`no_music`/etc. items also have MusicXML on disk) that this section does not enumerate. |
| `reports.count` / `.hash` / `.per_entry` | | Same, for each entry's `<id>.report.json` (always at a fixed `out/ingest/<id>.report.json` location by convention — there's no stored path field to trust here, but `<id>` itself must still be a "simple" single-segment token before it's safe to interpolate into a filename; see `integrity`). Report *content* is never embedded — only its hash — because `*.report.json` is never served publicly (`server/byzorgan-web-server.py`'s allowlist explicitly excludes it). **Manifest-published entries only**, same scope note as `musicxml`. |
| `state.present` / `.record_count` / `.hash` | | Whether `ingest_state.json` exists, how many records **(the full private working set — all statuses, not just published)**, and a whole-file hash. State content (which includes the local `pdf` path) is never embedded, only hashed. |
| `overrides.count` / `.hash` / `.per_stem` / `.tombstones` | | Per-stem sha256 of each hand-edited override MusicXML file, and the tombstone list from `overrides/RETIRED`. |
| `trust.status_counts` | object | Count per ingest status (`accepted`, `review`, `no_music`, `type3`, `download_error`, `extract_error`) — over the full working set in `state`. |
| `trust.confidence` | object | `mean_integrity_pct`/`median_integrity_pct`/`min_integrity_pct`/`max_integrity_pct` over **accepted** items only. All `null` when there are no accepted items. |
| `waivers` | array | Approved exceptions to normal gates. **Always `[]` today** — no waiver mechanism exists anywhere in the codebase yet. The field exists now so a future TRUST-01/RIGHTS-01 waiver system never needs a breaking schema bump to add it. |
| `verification.regression_suite` | object | `{passed, skipped, failed, recorded}` — the OMR pytest regression suite's result, if the caller supplied it via `--verified-passed/--verified-skipped/--verified-failed`. A recorded run requires all three nonnegative counts. `recorded: false` and all counts `null` when not supplied — this descriptor never claims verification happened when it didn't. |
| `manifest_validation.checked` / `.problems` | | Acceptance criterion "all manifest entries resolve to parseable MusicXML and reports", checked directly: every listed entry's `.musicxml` is confirmed to exist and parse as XML (after passing the containment check) and its `.report.json` is confirmed to exist and parse as JSON. `problems` is a list of human-readable strings; empty means every listed entry resolved cleanly. |
| `integrity.problems` | array of string | Path-safety and cross-record consistency problems: path traversal or absolute paths in `musicxml`/`pdf` fields, duplicate manifest ids, non-simple ids (containing a path separator — unsafe to build a filename from), and tombstone/active-override conflicts (a stem present in both `overrides/*.musicxml` and `overrides/RETIRED` — `apply_overrides()` silently skips it, which almost always means the file should have been deleted). Distinct from `manifest_validation`, which is about file existence/parseability, not path safety. |
| `compatibility.min_reader_schema_version` | int | The oldest schema version a reader must understand to safely consume this descriptor. |
| `readiness.promotable` / `.reasons` | bool, array of string | See Readiness below. |

## Readiness / promotability

A **structurally valid** descriptor (passes `validate_descriptor()`) is not
automatically **promotable**. `readiness.promotable` is `false`, with a
human-readable reason in `readiness.reasons`, whenever any of the following
holds:

- No local catalog input present (`input.catalog_present == false`).
- Manifest is empty (`manifest.entry_count == 0`).
- Parser or app provenance is unknown (`code.parser_git_sha`/`app_git_sha`
  is `null`) — see the field reference above for why this is `null` on
  every local catalog today, and why that's honest, not a bug.
- Builder tree is not confirmed clean (`code.builder_dirty` is `true` or
  `null` — only an exact `false` counts).
- Verification wasn't recorded, or reported any failing test.
- `manifest_validation.problems` or `integrity.problems` is non-empty.

This is deliberately permissive about what stays **structurally valid** (an
empty-catalog descriptor is still schema-valid, useful for diagnostics — see
the fresh-checkout example above) while being strict about what CAT-02 should
ever treat as promotable. CAT-02 is expected to refuse promotion outright on
`promotable: false`.

## Compatibility policy

There is only one schema version today (`1`); this policy governs *future*
changes, not a migration that exists yet:

- **Additive, non-breaking:** a new optional field, or a new key inside an
  existing object, does **not** bump `schema_version`. Readers must ignore
  unknown fields rather than fail on them.
- **Breaking:** removing a field, renaming a field, or changing a field's
  type or meaning bumps `schema_version` and requires a documented migration
  note here plus a compatibility-matrix entry (added the first time this
  actually happens).
- **`compatibility.min_reader_schema_version`** lets a reader detect
  "I don't understand this" without guessing from `schema_version` alone —
  a producer can bump `schema_version` for additive reasons while keeping
  `min_reader_schema_version` unchanged, telling old readers "you can still
  safely read this."
- The current app (`training-prototype/js/library.js`) does not read
  release descriptors at all yet — it reads `manifest.json` directly, which
  this schema does not change the shape or path of. "Current app can read
  current and previous schema" (CAT-01 acceptance) is satisfied trivially
  today because nothing app-facing changed; it becomes a real constraint
  once CAT-02/a consumer actually reads descriptors.

## Enforcement

`schema/release_descriptor.schema.json` is the **authoritative** structural
contract, enforced at runtime via the `jsonschema` package
(`validate_descriptor()` calls `jsonschema.validate()` against it). Semantic
checks JSON Schema cannot express run separately in Python: aggregate
inventory counts/hashes and the content fingerprint are recomputed,
`release_id` and readiness are checked against that evidence, timestamps are
checked without optional format dependencies, and every value is scanned for
private local paths. All checks must pass for `validate_descriptor()` to
return no problems.

## What this deliberately does NOT do (CAT-01 scope boundary)

- Does not change where `ingest_catalog.py` writes, or add any staging
  directory, pointer, or promotion mechanism — that is CAT-02
  (`docs/plans/10-catalog-releases/12-atomic-build-promote-rollback.md`).
  CAT-02 should also wire `ingest_catalog.py` itself to record its own git
  SHA at ingestion time, so `parser_git_sha` stops being `null` by default
  for freshly-ingested content.
- Does not enforce publication eligibility/attribution completeness — that
  is RIGHTS-01 (`docs/plans/10-catalog-releases/14-publication-rights-controls.md`),
  which explicitly depends on this schema existing first.
- Does not touch production catalog data, `out/ingest/`, or
  `ingest_state.json` — every function in `release_descriptor.py` is
  read-only.

## Rights boundary this schema must never cross

Per `omr/SOURCES.md` and RIGHTS-01: the extracted MusicXML catalog,
`manifest.json`, and the built-in `content/*.musicxml` pieces are
publication-safe; the raw source PDFs, rendered pages, and OMR intermediates
are not, and must never be committed or exposed. A release descriptor must
never contain a local filesystem path into `pdfs/ingest/`, `pdfs/survey/`,
or any `.venv/` — `release_descriptor.validate_descriptor()` scans every
string value in a built descriptor for exactly these patterns and reports a
validation problem if one is found (`tests/test_release_descriptor.py`
proves this with fixtures deliberately built to try to leak one, including
real path-traversal and absolute-path attempts against the `musicxml`/`pdf`
fields).
