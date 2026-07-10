# ONEAPP-02: Byzantine Mode In The Shared Practice Shell

Status: blocked on `ONEAPP-01`. Priority: P3.

Dependencies: common contract and stable production shell.

Owned files: adapters, shared shell/library routing, Byzantine renderer/practice
integration tests. Exclusive cross-app lane.

## Goal

Open Byzantine material from the same library and use the shared transport,
scope, recording, preferences, and appropriate scoring without losing tuning,
ison, pthora, martyria, glyph, or phrase semantics.

## Steps

1. Add score-type routing and capability-driven controls.
2. Adapt compiled chant timelines to the common contract.
3. Embed the existing Byzantine renderer as the notation-specific view.
4. Map microtonal target frequencies and ison without MIDI rounding.
5. Reuse shared practice state only where semantics match.
6. Preserve legacy route until production comparison and rollback pass.

## Acceptance

Western and Byzantine regression suites pass; microtonal frequencies match
tuning references; irrelevant SATB controls disappear; shared controls remain
predictable; mobile/desktop/accessibility gates pass; old route rollback works.

