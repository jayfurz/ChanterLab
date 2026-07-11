# TRUST-01: Quality Ledger And Status Schema

Status: complete 2026-07-11; Quality Ledger Schema v1 owner-approved as
written and implemented by ChanterLab PR #105 (`b2fc8a3`) and infra PR #16
(`872d11b`). The separate owner production approval promoted its first
ledger-bearing release, `rel-20260711T155237Z-a3fdb875e54f`. Priority: P0.

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
6. Record owner approval of the schema, then require a separate exact-release
   approval before any promotion.

## Acceptance

Every active score has exactly one valid status; transitions are audited; manual
overrides and retired overrides cannot conflict; missing provenance fails the
appropriate publication gate; current and previous schema remain readable.

## Implementation Record (2026-07-11)

- App implementation commit: `61c29df` (`feat(omr): add private quality ledger
  snapshots`). It adds the private append-only journal,
  `schema/quality_ledger.schema.json`, immutable release snapshots, descriptor
  hash binding, transition validation, parent score identity, durable
  review-required withholding/reapproval, strict backup hashing, candidate
  source/artifact verification, and a nonpublic aggregate release-stat
  summary. No UI or public release-marker contract changed.
- The retired-override parser is centralized so inline `#` comments have the
  same meaning in ingestion, descriptor validation, and ledger reconciliation.
  A tombstoned override remains distinct from a retired score.
- Rights-safe evidence from a fresh no-PDF worktree: `157 passed, 19 skipped`.
  Private-corpus evidence: `176 passed, 0 skipped`. The focused suite
  includes source-PDF drift before/during finalization, candidate-artifact
  drift, journal cleanup/tree-shape, direct URL containment, withholding and
  reapproval, manual-override history, and concurrent journal writer locking.
- Read-only real-catalog reconciliation covered all 3,351 published entries:
  3,351 active `auto-imported`, zero fabricated human-verification records,
  and no provenance/hash problems. Existing ingest outcome counts remain
  separate: 3,351 accepted, 132 review, 300 no_music, 10 type3.
- A non-promoted final real candidate sealed and validated as
  `rel-20260711T075217Z-49ce9c8023ed`; its 3,351-record ledger hash is
  `969881951a7d3a5724d78de66a5ea97275635856745236a03b82c23c75efc0a7` and
  is bound into the descriptor content fingerprint
  `49ce9c8023ededed0a06cb7b7a7aa207d948c2d022c281e548fb4c5a1c578ec6`.
  Its candidate artifact inventory hash is
  `9364af28932c9b1695894d3f631e2ddf0860a436f48a82038a2d639c11548b82`,
  and its source inventory hash is
  `1791a00bae3e47ee4ac998a8a46865f28e226b658b1ba557029c85b01f61934a`.
  Its 3,793 state records each carry a candidate-input PDF hash; the sealed
  tree has three required ingest metadata files plus 3,351 manifest MusicXML
  and 3,351 manifest report files, and exactly `trust/quality-ledger.json` as
  private ledger content. No production pointer, served catalog, or source
  corpus changed.
- Infra companion commit `e74c11a` conditionally archives
  `quality-ledger/ledger.json`, validates the exact `trust/` tree on publish,
  and requires the clean canonical `main` validator checkout and image tag to
  match the descriptor app SHA. The live timer and dirty infra checkout remain
  untouched.

### Approval Record (2026-07-11)

The owner approved Quality Ledger Schema v1 as written; ChanterLab PR #105 and
infra PR #16 were then merged at `b2fc8a3` and `872d11b`. That approval did not
authorize a catalog promotion. Create the initial private journal only for a
real review event and run the archive/restore drill with it present. The
non-promoted candidate recorded above is tied to app SHA `61c29df`, so it must
not be promoted after the merge; a future promotion must build and verify a new
candidate from merged `main` and use its separate exact-release approval token.

### Production Promotion Record (2026-07-11)

- The owner separately approved production. A fresh candidate was built from
  clean `main@9cd53e3697c5d127fa7abfceab7cc09beffff7d6`, verified against the
  private corpus (`176 passed, 0 skipped`), sealed, and strictly validated as
  `rel-20260711T155237Z-a3fdb875e54f`.
- The descriptor binds app and parser SHA
  `9cd53e3697c5d127fa7abfceab7cc09beffff7d6`, content fingerprint
  `a3fdb875e54fd6a35a53aa9495d55f9aca9822e733e4075de161d90a795fd7da`,
  and the immutable ledger snapshot SHA-256
  `614552bd115d2b7f9636928407cbe32ab258af6b5b8ebddede7dcdac2911c8b8`.
  It contains 3,358 active `auto-imported` records, 3,358 published
  MusicXML/reports, and 3,793 state records; no mutable journal was sealed.
- Semantic review found seven stale review-cache recoveries and 47 published
  score corrections. All 3,793 PDF hashes were unchanged. Historical-parser
  reproduction traced every score change to the already-reviewed chord-dot,
  divisi, and above-staff lyric fixes; no unexplained parser or environment
  drift remained.
- The matching GitOps image
  `git.lab.alwaysdobetterllc.com/jfursov/chanterlab-web:9cd53e3697c5d127fa7abfceab7cc09beffff7d6`
  was healthy before promotion. A disposable read-only candidate pod passed,
  then public smoke passed on `chanterlab.com`, `www.chanterlab.com`, and
  `byz.alwaysdobetterllc.com`. Each serves 3,358 entries and the exact release
  marker. The previous release
  `rel-20260710T200845Z-d1d822d75972` remains the rollback target.
- The public boundary was checked after promotion: release descriptor, ledger
  snapshot, ingest state, and report paths return `404` on all three hosts.

### Archive Follow-up

The ledger-aware archive script is merged in infra, but this session does not
have authorized Beast SSH access to install it or trigger the post-promotion
archive service. No archive transport, TrueNAS snapshot, or new restore drill
is claimed here. From an authorized Beast session, atomically install the
single script, trigger the service once, and record the resulting
release-snapshot and hash-manifest evidence.
