# PRACTICE-02: Target Replay, Range, And Transposition

Status: blocked on `PRACTICE-01`. Priority: P1.

Dependencies: characterized transport. Blocks: advanced singer preferences.

Owned files: model/voices/transport UI and focused MusicXML/playback tests.

## Goal

Let singers hear a target, preview only their part, detect uncomfortable range,
and optionally practice a consistently transposed score.

## Steps

1. Define visual-versus-sounding transposition behavior and owner approve it.
2. Add target-note replay without starting the transport.
3. Add selected-part-only preview distinct from normal muted-part practice.
4. Derive part range and compare with an optional singer range preference.
5. Apply transposition consistently to playback, target lane, scoring, display
   labels, recording mix, and saved practice state.
6. Preserve the source PDF and original-key metadata.

## Acceptance

No mismatch exists between audible pitch, scope target, scoring target, and UI;
range warning is advisory; reset restores source pitch; loops/verses/sections and
recording remain correct; transposition is explicit in saved/shared context.

