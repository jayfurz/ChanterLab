# Agent Check-In Protocol

Status: required for every pickup plan.

Use this format in this chat:

```text
CHECK-IN [plan-id] [gate]
Status:
Baseline: branch, code SHA, catalog release/hash
Owned files:
Changed:
Evidence: commands plus pass/fail/skip counts
Corpus delta:
Risks or waivers:
Decision needed:
Next:
```

## Required Check-Ins

1. **Start:** confirm plan, dependencies, baseline, owned files, dirty-tree
   state, expected risks, and whether private/device gates are available.
2. **Diagnosis:** explain root cause or current architecture and predict product,
   schema, corpus, and compatibility impact before risky edits.
3. **Implementation:** summarize the diff and focused test evidence. Report
   skips explicitly.
4. **Corpus/release gate:** provide exact changed pieces, trust/status movement,
   confidence changes, accepted/review counts, waivers, and rollback proof.
5. **Completion:** list commits, release ID if any, production smoke evidence,
   residual risks, and follow-up plans.

## Mandatory Pause Conditions

Pause and request a decision when:

- Corpus churn is unexplained.
- A formerly accepted score moves to review without an understood cause.
- A voice collapse, integrity decrease, or unexplained byte change appears.
- Copyrighted or secret material is staged for commit or public artifacts.
- Another agent edits an owned file.
- A schema change lacks backward compatibility or rollback.
- A required private-corpus or real-device gate cannot run.
- A plan needs a backend, account model, vendor, branch switch, rename, public
  rights declaration, or material UX/scoring-policy decision.
- The proposed fix requires weakening a confidence or rejection guard.

## Owner Checkpoints

Explicit approval is required before default/deployment branch changes, catalog
schema promotion, public-rights declarations, issue-storage architecture,
scoring/register semantics, product/directory renames, analytics collection,
uploads/authentication, public sharing, raster-OMR investment, or multipart
assessment investment.

