# Catalog Release Orchestrator

Status: `CAT-01` complete and schema v1 approved 2026-07-10. `CAT-02` is
ready. `BASE-00` completed at `e77ffa7`.

Roadmap IDs: `CAT-01` through `CAT-03`, plus `RIGHTS-01` publication controls.

Objective: replace mutable live-tree ingestion with immutable, identifiable,
validated, atomically promoted, and restorable catalog releases.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`11-release-contract.md`](11-release-contract.md) | complete 2026-07-10; schema v1 approved |
| 2 | [`12-atomic-build-promote-rollback.md`](12-atomic-build-promote-rollback.md) | ready |
| 3 | [`13-backup-restore-generated-stats.md`](13-backup-restore-generated-stats.md) | blocked on 12 |
| 4 | [`14-publication-rights-controls.md`](14-publication-rights-controls.md) | owner/legal gate; design parallel-safe |

## Collision Rule

Plans 11-13 all touch catalog/ingest paths and must be sequential. Rights policy
research may run in parallel but publication enforcement integrates only after
the release schema is frozen.

## Completion

Build a candidate without changing production, validate it, compare it, promote
with one atomic operation, smoke it, roll back to exact previous hashes, restore
from backup in a clean location, and regenerate the published statistics.
