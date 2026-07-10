# LOOP-02: Reviewer PDF/Score Workbench

Status: blocked on `LOOP-01`. Priority: P1.

Dependencies: report intake and quality ledger. Blocks: audited corrections.

Owned files: reviewer-only UI/tooling, PDF crop/render helpers, review schema.

## Goal

Make a report quick to verify against the source while retaining evidence and
avoiding exposure of copyrighted artifacts.

## Scope

1. Queue reports by severity, duplicates, confidence, and affected family.
2. Show original PDF region, rendered MusicXML, voice/measure events, warnings,
   parser release, and report context side by side.
3. Support verdicts: confirmed, not reproducible, engraving ambiguity, app bug,
   metadata bug, duplicate, or deferred.
4. Link related scores/failure clusters and capture reviewer notes/evidence.
5. Produce correction/parser tickets with immutable references.

## Acceptance

Review actions are audited and reversible; private assets are access-controlled
and excluded from public artifacts; named measure navigation is accurate;
duplicate linking preserves the canonical report; keyboard and zoom workflows
are practical for repeated review.

