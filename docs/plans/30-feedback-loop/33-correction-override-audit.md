# LOOP-03: Correction And Override Audit Lifecycle

Status: blocked on `LOOP-02`. Priority: P1.

Dependencies: reviewer verdicts, golden-fixture process, atomic release tooling.
Blocks: report closure and semantic promotion approval.

Owned files: correction records, override/tombstone tooling, regression linkage.

## Goal

Ensure every confirmed defect resolves through a parser fix, explicit override,
source correction, or documented waiver with a durable audit trail.

## Steps

1. Define correction types and permitted trust transitions.
2. Require source evidence and reviewer identity for manual overrides.
3. Require focused tests for parser fixes and semantic assertions before hashes.
4. Link override files to ledger records without committing protected content.
5. Retire overrides through tracked tombstones when the parser supersedes them.
6. Reopen reports automatically if a later release regresses the evidence.

## Acceptance

No silent force-accept; override and retirement states cannot conflict; every
correction links report, evidence, release, and test/waiver; stale backups cannot
resurrect retired overrides; audit history survives catalog rollback.

