# CAT-03: Backup, Restore, And Generated Statistics

Status: complete 2026-07-10. Priority: P0.

Dependencies: immutable releases. Blocks: operational confidence and cleanup.

Owned files: backup/restore scripts or runbooks, generated nonprivate summaries.

## Goal

Prove the private content system can be restored without resurrecting retired
overrides or relying on undocumented machine state.

## Scope

1. Define backup sets for sources, releases, state, reports, overrides,
   tombstones, pointers, secrets references, and verification evidence.
2. Define retention, encryption, access, integrity checking, and off-machine copy.
3. Restore into a clean location and validate hashes.
4. Promote the restored candidate in staging and roll back.
5. Generate counts/confidence/trust summaries from release metadata.
6. Replace hand-copied catalog totals in current operational docs with generated
   references or dated snapshots.

## Acceptance

Restore requires a documented finite procedure; stale override backups remain
retired; active and previous releases validate; recovery time/data-loss targets
are recorded; generated stats match the active release.

## Handoff

Report backup locations abstractly without secrets, restore evidence, hashes,
recovery timings, failures encountered, and scheduled drill cadence.

## Implementation Record (2026-07-10)

- ChanterLab PR #103 merged the strict backup/restore contract at `99f0d87`:
  versioned mutable hash evidence, production pointer snapshots, exact restore
  materialization, release validation, and generated release statistics.
  Infra PR #8 (`1a957b3`) added the archive transport; PRs #9 (`417f152`) and
  #10 (`6f0a1d4`) hardened staged TrueNAS installation after the first real
  drill exposed read-only release-directory semantics.
- The owner-only (`0700`) additive TrueNAS mirror retains mutable PDFs,
  sources, ingest state/reports, overrides/tombstones, all sealed releases,
  production pointers, and bound verification evidence. `staging/`,
  `.promotion.lock`, and reproducible scratch paths are excluded. Retention is
  permanent with no sweep. File-level encryption is deliberately not added:
  this matches the existing backup convention, the payload has no credentials,
  and any future key belongs in `infra/secrets/`; revisit the waiver if the
  platform storage-encryption baseline changes.
- The timer is enabled daily at 03:00 MST. Target RPO is 24 hours and target
  RTO is 30 minutes. The initial real off-machine drill transferred the exact
  1,953,410,131-byte, 25,555-file archive from TrueNAS in 18 seconds and
  reached strict validation in 24 seconds. The next quarterly drill is due
  2026-10-10.
- The clean restored tree validated two sealed releases with zero mutable-hash,
  release-fingerprint, pointer, or snapshot problems. It restored
  `rel-20260710T200845Z-d1d822d75972` as `current` and
  `rel-20260710T202424Z-d1d822d75972` as `previous`. A promotion to the prior
  release followed by rollback reproduced the original pointer/evidence digest
  exactly, and strict verification passed again afterward.
- `pytest tests/` with the private corpus passed 144 tests locally; the
  required GitHub gate, including the browser gate, passed before PR #103
  merged. Infra `make validate` passed for every archive change. A missing
  local `jsonschema` venv dependency was discovered during the real restore;
  validation correctly failed closed, the dependency is now declared in
  `requirements-release.txt`, and CI installs that declaration in fresh envs.
- Generated active-release summary:
  `rel-20260710T200845Z-d1d822d75972` (app
  `61871cfd1f2dcf41afb0a21a88aea5e4a5763b4c`, generated
  2026-07-10T20:08:45.186826+00:00): 3,351 manifest entries, 3,351 MusicXML,
  3,351 reports, and 3,793 state records. Trust status counts are 3,351
  accepted, 132 review, 300 no-music, 10 Type3, and zero download/extract
  errors; integrity confidence is 99.81% mean, 100% median, 90% minimum, and
  100% maximum.
