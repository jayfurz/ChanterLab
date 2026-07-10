# Catalog release descriptor — schema v1 (CAT-01)

Status: schema drafted, tooling implemented, **not yet owner-approved as
stable** (see docs/plans/10-catalog-releases/11-release-contract.md, step 5).
Do not build CAT-02's atomic promotion on this schema until that approval is
recorded here.

## What this is

A **release descriptor** is a small, immutable JSON document that describes
one snapshot of the local OMR ingest catalog: what code produced it, what it
contains, and whether it's internally consistent — without moving, copying,
or promoting anything. Generating one is always safe to run against a live
`out/ingest/` directory; it only reads.

This is deliberately narrower than full catalog promotion (CAT-02). CAT-01's
job is to define *what a release IS* — a stable identity and content
contract — before CAT-02 changes *where ingestion writes* to build on it.

Build one:

```sh
cd training-prototype/omr
.venv/bin/python release_descriptor.py                 # print to stdout
.venv/bin/python release_descriptor.py --out rel.json   # write to a file
.venv/bin/python release_descriptor.py --strict         # nonzero exit on
                                                         # any validation
                                                         # problem
```

On a fresh checkout (the common case — `out/` and `pdfs/` are gitignored,
copyrighted-derived material, never committed) this still produces a valid
descriptor: every count is honestly `0`, `catalog_present`/`manifest.present`
are `false`, nothing is fabricated. See `tests/fixtures/release_descriptor/`
for a worked example against small synthetic (non-copyrighted) data, and
`tests/fixtures/release_descriptor/example_descriptor.json` for its exact
output.

## Field reference

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Always `1` for this document. See Compatibility below. |
| `release_id` | string | `rel-<UTC timestamp>-<catalog_input_hash prefix>`. Derived from time + input identity — never a mutable human label, never hand-edited. |
| `parent_release_id` | string \| null | The release this one supersedes, for semantic diff/rollback. `null` for the first release, or when generating a standalone descriptor with no promotion history yet (CAT-01's own tooling always passes `null` unless `--parent` is given — CAT-02 owns actually tracking release lineage). |
| `generated_at` | string (ISO 8601 UTC) | When this descriptor was built. Informational only — never used for identity or content hashing. |
| `code.repo_git_sha` | string \| null | `git rev-parse HEAD` of this repo at build time. |
| `code.parser_git_sha` | string \| null | Currently always equal to `repo_git_sha` (parser and app live in one monorepo commit today). Recorded as a distinct field for forward compatibility if the OMR pipeline ever ships as a separately-versioned package. |
| `code.app_git_sha` | string \| null | Same as `parser_git_sha` today, same forward-compatibility reasoning. |
| `input.catalog_present` | bool | Whether `pdfs/survey/catalog.json` (the cached upstream Antiochian catalog) exists locally. |
| `input.catalog_input_hash` | string \| null | sha256 of the canonicalized (sorted-keys, no whitespace) catalog JSON. `null` if absent. |
| `input.source_inventory` | array | One entry per ingest-state record: `{id, source_url, pdf_sha256}`. `source_url` is the public Antiochian blob URL (same value already published in `manifest.json`'s `pdfUrl`). `pdf_sha256` proves which source bytes were used **without** revealing where they live on this machine — the local relative path is deliberately never included. |
| `input.source_inventory_hash` | string | sha256 of the canonicalized inventory array. |
| `manifest.present` / `.entry_count` / `.hash` | | Whether `manifest.json` exists, its entry count, and a canonical-content hash. |
| `musicxml.count` / `.hash` / `.per_entry` | | Per-manifest-entry sha256 of the emitted `.musicxml` file (or `null` if missing — see `manifest_validation`), plus a combined hash of the whole map. |
| `reports.count` / `.hash` / `.per_entry` | | Same, for each entry's `<id>.report.json`. Report *content* is never embedded — only its hash — because `*.report.json` is never served publicly (`server/byzorgan-web-server.py`'s allowlist explicitly excludes it). |
| `state.present` / `.record_count` / `.hash` | | Whether `ingest_state.json` exists, how many records, and a whole-file hash. State content (which includes the local `pdf` path) is never embedded, only hashed. |
| `overrides.count` / `.hash` / `.per_stem` / `.tombstones` | | Per-stem sha256 of each hand-edited override MusicXML file, and the tombstone list from `overrides/RETIRED`. |
| `trust.status_counts` | object | Count per ingest status (`accepted`, `review`, `no_music`, `type3`, `download_error`, `extract_error`). |
| `trust.confidence` | object | `mean_integrity_pct`/`median_integrity_pct`/`min_integrity_pct`/`max_integrity_pct` over **accepted** items only. All `null` when there are no accepted items. |
| `waivers` | array | Approved exceptions to normal gates. **Always `[]` today** — no waiver mechanism exists anywhere in the codebase yet. The field exists now so a future TRUST-01/RIGHTS-01 waiver system never needs a breaking schema bump to add it. |
| `verification.regression_suite` | object | `{passed, skipped, failed, recorded}` — the OMR pytest regression suite's result, if the caller supplied it via `--verified-passed/--verified-skipped/--verified-failed`. `recorded: false` and all counts `null` when not supplied — this descriptor never claims verification happened when it didn't. |
| `manifest_validation.checked` / `.problems` | | Acceptance criterion "all manifest entries resolve to parseable MusicXML and reports", checked directly: every listed entry's `.musicxml` is confirmed to exist and parse as XML, and its `.report.json` is confirmed to exist and parse as JSON. `problems` is a list of human-readable strings; empty means every listed entry resolved cleanly. |
| `compatibility.min_reader_schema_version` | int | The oldest schema version a reader must understand to safely consume this descriptor. |

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

## What this deliberately does NOT do (CAT-01 scope boundary)

- Does not change where `ingest_catalog.py` writes, or add any staging
  directory, pointer, or promotion mechanism — that is CAT-02
  (`docs/plans/10-catalog-releases/12-atomic-build-promote-rollback.md`).
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
proves this with a deliberately "leaky" fixture).
