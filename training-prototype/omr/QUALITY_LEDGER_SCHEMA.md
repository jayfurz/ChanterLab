# Quality Ledger Schema v1

Status: approved stable v1 (owner approval recorded 2026-07-11). This approval
authorizes merging the held implementation changes; it does not authorize a
ledger-bearing catalog promotion.

The ingest pipeline's `accepted` status is a structural publication outcome.
It is not evidence of human review. TRUST-01 records review state separately
without changing `manifest.json`, `release.json`, or any public API.

## Storage and privacy

The ignored private journal is `quality-ledger/ledger.json`. It contains only
append-only status events. `catalog_release.py new` and `import-existing`
copy it into the candidate, so sealing never reads a mutable source journal
after the candidate has started.

Sealing reconciles candidate inputs and the copied journal into
`trust/quality-ledger.json` inside the immutable release. The release
descriptor's optional `quality_ledger` section records the snapshot's schema,
counts, status distribution, and canonical body hash. That hash is part of
the release `content_fingerprint`. The mutable journal is deleted from the
candidate immediately before the sealed release is validated; a sealed
ledger-bearing tree contains exactly `trust/quality-ledger.json`, never a
copy of `quality-ledger/`.

The web server remains deny-by-default. It serves neither the private journal,
the release descriptor, nor `trust/quality-ledger.json`. Actor and evidence
references must be opaque tokens, not names, email addresses, local paths,
score excerpts, or free-form review notes.

The journal directory is created owner-only (`0700`), its JSON and lock file
are owner-readable only (`0600`), and transition appends hold an advisory
single-writer lock. This is defense in depth for private local state; the web
server denial remains the network boundary.

## Identity

- `catalog_id`: the existing logical manifest ID. It is a stable lookup key,
  not an immutable score revision.
- `source_id`: `source-` plus the SHA-256 of canonical public source URL and
  source-PDF SHA-256.
- `score_id`: `score-` plus the SHA-256 of canonical `catalog_id`, `source_id`,
  and emitted MusicXML SHA-256.
- `previous_score_id`: the parent release's active score revision for the same
  `catalog_id`, when the current bytes represent a new revision.

Neither immutable identity includes a release ID. This avoids circular
identity: a body is hashed first; the descriptor then binds that hash; only
then does the snapshot wrapper record its release ID and fingerprint.

## Snapshot shape

`schema/quality_ledger.schema.json` is the authoritative structural schema.
The wrapper is:

```json
{
  "schema_version": 1,
  "release_id": "rel-...",
  "release_content_fingerprint": "<sha256>",
  "ledger_hash": "<sha256 of canonical body>",
  "summary": {
    "schema_version": 1,
    "record_count": 1,
    "active_count": 1,
    "status_counts": {
      "auto-imported": 1,
      "human-verified": 0,
      "known-issue": 0,
      "review-required": 0,
      "manual-override": 0,
      "retired": 0
    },
    "hash": "<same canonical body hash>"
  },
  "records": []
}
```

Each record contains immutable source/score identity, parser SHA, active flag,
current and initial trust status, public source/PDF provenance, emitted
MusicXML/report hashes, legacy integrity reference and warning count,
override/tombstone state, and audited transition history. `edition` is `null`
until a source provides it honestly. Warning prose is not copied; v1 stores
only `warning_count` and `warning_summary: {"count": N}`. TRUST-02 owns a
real multidimensional confidence vector.

`override_history.active_override_sha256` exists only while an active
`manual-override` is applied. `last_override_sha256` retains the final
override hash when that revision becomes `review-required` or `retired`, so
historical override provenance is not misrepresented as a still-active file.

The initial migration produces exactly one active record for each manifest
entry. A non-overridden entry starts `auto-imported`; a current override starts
`manual-override`. It never infers `human-verified` from an ingest status,
integrity percentage, accepted count, or an override. Non-manifest ingest
records (`review`, `no_music`, `type3`, download/extract errors) are not
fabricated into trust records.

Fresh candidate ingestion records a source-PDF SHA-256 immediately before and
after parser execution and rejects a changed file. `import-existing` records
the source bytes observed when the migration candidate begins; it proves no
later drift, but cannot retroactively prove the bytes used by legacy output.

## Statuses and transitions

| Status | Meaning | Active manifest entry? |
|---|---|---|
| `auto-imported` | Parser output passed existing publication guards. | Yes |
| `human-verified` | A reviewer/owner supplied explicit evidence. | Yes |
| `known-issue` | An evidenced issue is known but publication remains allowed. | Yes |
| `review-required` | Withheld from the manifest pending review. | No |
| `manual-override` | Current active override bytes are authoritative. | Yes |
| `retired` | Historical score revision is terminal. | No |

`manual-override` is derived from the candidate override inventory and its
exact hash; it cannot be written by a journal event. `RETIRED` in
`overrides/` means a retired override file, not a retired score. An active
score with a tombstoned old override remains an active score, normally
`auto-imported`.

Allowed journal transitions are:

| From | To | Authority |
|---|---|---|
| `auto-imported` | `human-verified`, `known-issue`, `review-required`, `retired` | reviewer/owner; owner for `retired` |
| `human-verified` | `known-issue`, `review-required`, `retired` | reviewer/owner; owner for `retired` |
| `known-issue` | `human-verified`, `review-required`, `retired` | reviewer/owner; owner for `retired` |
| `review-required` | `human-verified`, `known-issue`, `retired` | reviewer/owner; owner for `retired` |
| `manual-override` | `review-required`, `retired` | reviewer/owner; owner for `retired` |
| `retired` | none | terminal |

Every event includes its exact `catalog_id`, `source_id`, `score_id`, expected
prior status, timezone-aware timestamp, actor role/reference, and one or more
opaque evidence references. Events must be chronological per score identity.
When MusicXML or source bytes change, the score gets a new `score_id`, starts
again at `auto-imported`, and retains only `previous_score_id`; a stale event
does not silently apply to the new revision.

To withhold or retire a score, append the `review-required` or owner `retired`
event before candidate ingest. Candidate manifest generation automatically
excludes that exact immutable revision, and sealing prunes all non-manifest
MusicXML/reports so a guessed URL cannot retrieve it. A later
`human-verified` or `known-issue` event from a held snapshot allows the same
bytes to reappear in the next candidate. The ledger retains non-active history
only for `review-required` or `retired`.

## Journal operations

Create a journal only when a real review event is ready to record:

```sh
cd training-prototype/omr
.venv/bin/python quality_ledger.py init --journal quality-ledger/ledger.json
```

Append a transition from a sealed snapshot. The command resolves an active
score, or the unique held `review-required` revision, to its exact immutable
identities and prior status before writing:

```sh
.venv/bin/python quality_ledger.py transition \
  --journal quality-ledger/ledger.json \
  --snapshot out/release-store/releases/<release-id>/trust/quality-ledger.json \
  --catalog-id <catalog-id> \
  --to-status human-verified \
  --actor-role reviewer --actor-ref reviewer-42 \
  --evidence-kind source-review --evidence-ref review-20260710-001
```

This updates only ignored private state. A new candidate must be built and
verified before the event can appear in a sealed release.

## Compatibility and backup

`quality_ledger` is additive in release descriptor schema v1. Existing sealed
releases without it remain readable and validate as legacy releases. Every new
candidate seal writes and validates a bound snapshot; a missing or tampered
snapshot blocks validation and promotion.

The mutable journal is a CAT-03 hashed backup set. The snapshot needs no
special transport path because it is inside the existing sealed release tree.
Restores reject a missing, mutated, or unexpected mutable journal file.
