# BASE-00: Land Current OMR Fixes

Status: done at `e77ffa7`. Priority: P0.

Dependencies: completed human review. Blocks: every OMR/catalog plan.

Owned files: `training-prototype/omr/vector_extract.py`, `ingest_catalog.py`,
`tests/test_fixes.py`, `tests/expectations.json`, `overrides/RETIRED`.

## Goal

Commit the reviewed chord-dot, overlapping divisi voice, above-staff lyric,
semantic tests, Bortniansky fixture, and durable override-retirement work.

## Scope

1. Reconfirm the worktree contains only the reviewed changes.
2. Run focused and full OMR regression tests with exact pass/skip counts.
3. Confirm no private PDF, generated MusicXML, crop, token, or screenshot is
   tracked.
4. Commit in logical parser units with tests in the same commit.
5. Record the final commit SHAs and catalog evidence in the completion check-in.

## Non-Goals

No new parser behavior, broad refactor, reimport architecture, or catalog schema
change. Do not re-bless additional pieces.

## Acceptance

- `git diff --check` passes before commit.
- OMR suite reports 36 passing locally with no unexplained skip.
- The Bortniansky fixture semantically asserts all three fixes and is byte-locked.
- A restored stale override is rejected by the tracked tombstone.
- Broad sampled outputs have no unexplained change.
- The served piece is the verified extraction and no longer marked overridden.

## Verification

```sh
cd training-prototype/omr
./.venv/bin/python -m pytest tests/ -q
cd ../..
git diff --check
git status --short
```

## Handoff

Report commits, test counts, broad-sample size/delta, manifest counts, override
state, generated/private files excluded, and any residual warning.

Completion record: the reviewed split landed as `7be4d13` (chord dots),
`6815071` (divisi voice 2), and `e77ffa7` (above-staff lyrics, byte fixture,
retired-override guard).
