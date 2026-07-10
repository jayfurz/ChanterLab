# CAT-03: Backup, Restore, And Generated Statistics

Status: ready; `CAT-02` completed 2026-07-10. Priority: P0.

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
