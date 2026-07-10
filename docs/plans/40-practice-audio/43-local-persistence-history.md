# PRACTICE-03: Local Preferences, History, And Annotations

Status: ready for schema design after `BASE-02`; UI integration follows plan 41.

Dependencies: stable score/release IDs for durable piece references.

Owned files: local state schema/migration, preference/history modules, UI tests.

## Goal

Preserve useful personal practice state locally without requiring accounts.

## Scope

Recent pieces, favorites, voice, tempo, loop, verse/section, view, volume,
instrument, latency/calibration, scoring strictness/register policy, practice
sessions, and optional conductor-style local annotations.

## Steps

1. Inventory existing localStorage keys and define a versioned schema.
2. Separate device preferences from score-specific state and practice history.
3. Add migrations, corrupt-data fallback, export, clear, and storage limits.
4. Add recent/favorite library views without slowing the 3,000+ item browser.
5. Add history summaries only after scoring-v2 fields stabilize.
6. Keep annotations local until an approved choir/account model exists.

## Acceptance

Existing preferences migrate; stale score releases resolve safely; corrupt data
does not block app load; private state has clear/reset controls; no account or
network is introduced; mobile/library performance stays within budget.

