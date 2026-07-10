# PROD-01: Product Root, Documentation, And Module Boundaries

Status: documentation ready; directory/product rename blocked on owner decision.

Priority: P2. Dependencies: branch/deploy consolidation.

Owned files: root/product docs first; later path-safe module extraction under
exclusive ownership.

## Goal

Make the repository describe and organize the product that is actually shipped,
then characterize module boundaries before refactoring.

## Steps

1. Update root README, architecture, run/test/deploy instructions, and the
   relationship between choir and Byzantine surfaces.
2. Mark historical prototype documents accurately without deleting evidence.
3. Inventory imports, URLs, symlinks, service paths, workflows, and generated
   paths tied to `training-prototype`.
4. Present rename/graduation options and obtain owner approval.
5. Characterize `transport.js` and main app responsibilities in tests before
   extracting modules.
6. Move one responsibility at a time with behavior-preserving commits.

## Acceptance

Fresh contributor instructions work; docs do not report stale catalog totals;
rename, if approved, has redirect/symlink/rollback coverage; each refactor commit
is behavior-neutral and browser/audio gates remain green.

