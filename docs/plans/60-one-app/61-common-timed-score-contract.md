# ONEAPP-01: Common Timed-Score Contract

Status: complete — the `contract/` package (v1.0.0 document, validator,
from_musicxml/from_chant adapters, to_scoring/to_scope consumer bridges)
landed via PRs #131/#133/#134; owner approved the contract and its five
recorded judgment calls 2026-07-19. UI migration proceeds under `ONEAPP-02`.
Tracking: issue #127 (closed).

Dependencies: practice v2 semantics, immutable score IDs, current chant compiler
and MusicXML model characterization.

Owned files: new contract/adapters/tests; avoid UI changes in the first commit.

## Goal

Define the smallest shared representation the transport, target lane, recording,
and scoring need, with adapters from Western MusicXML and Byzantine compiled
scores.

## Required Concepts

Immutable score/part/event IDs; time/beat mapping; target pitch supporting
absolute frequency or tuning context; rests/ties; lyrics; sections/measures or
phrase anchors; tempo changes; selected practice part; source-render references;
notation-specific metadata; diagnostics and capability flags.

## Steps

1. Characterize both current data models with fixtures.
2. Separate practice timeline from notation/render representation.
3. Define versioned plain-data contract and capability negotiation.
4. Implement adapters without changing current consumers.
5. Compare adapter timelines with current playback on representative fixtures.
6. Obtain owner/technical approval before UI migration.

## Acceptance

No pitch/timing loss in Western SATB or Byzantine microtonal examples; adapters
are deterministic; unsupported capabilities are explicit; existing renderers
remain independent; contract version/migration and rollback are documented.

