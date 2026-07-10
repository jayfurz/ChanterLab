# Feedback And Correction Loop Orchestrator

Status: blocked on immutable IDs and `TRUST-01`.

Roadmap IDs: `LOOP-01` through `LOOP-04`.

Objective: turn a singer-observed score defect into structured evidence,
review, correction, regression coverage, and a safely promoted catalog release.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`31-report-capture-and-intake.md`](31-report-capture-and-intake.md) | blocked on storage owner decision |
| 2 | [`32-reviewer-workbench.md`](32-reviewer-workbench.md) | blocked on 31 |
| 3 | [`33-correction-override-audit.md`](33-correction-override-audit.md) | blocked on 32 |
| 4 | [`34-semantic-diff-approval.md`](34-semantic-diff-approval.md) | blocked on atomic releases and 33 |

## Owner Gate

Choose local export/manual intake or an authenticated storage service before
implementation. A static client-side app must not acquire an accidental backend.

## Completion Scenario

A singer flags a named measure/voice; the report retains immutable context; a
reviewer compares PDF and output, classifies it, links a correction or parser
fix, adds regression evidence, reviews catalog-wide semantic deltas, promotes a
release atomically, and closes the report with the served release ID.

