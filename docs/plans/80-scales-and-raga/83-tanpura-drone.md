# RAGA-02: Tanpura Drone

Status: in-progress (owner greenlit 2026-07-11). Priority: P2.

Dependencies: sequenced after `RAGA-01` (shared `web/app.js`/`web/index.html`
edits). Blocks: nothing. Parallel-safe: no — sequential within this lane.

Owned files: `web/audio/audio_engine.js`, `web/audio/synth_worklet.js` (only
if pluck envelopes need worklet support), `web/app.js`, `web/index.html`,
`web/style.css` (control group), any new `web/ui/tanpura.js` module.

## Goal

A tempo-locked four-pluck tanpura cycle the singer can hold a raga against:
first string selectable (Pa / Ma / Ni for Pa-less ragas), then Sa, Sa, lower
Sa — with tempo and volume controls, coexisting with (not replacing) the ison.

## Owner Decisions

- v1 is synthesized (plucked envelope + slow jawari-like shimmer on the
  existing synth path). No bundled third-party samples without a recorded
  license decision — global rights rule.
- Off by default; independent volume; usable alongside metronome and voice
  monitor.
- Mode-scoped (owner, 2026-07-11): the tanpura exists only in Hindustani
  mode and the ison only in Byzantine mode; a hidden drone must never keep
  sounding, so switching modes stops the other tradition's drone.

## Scope And Non-Goals

The drone and its controls only. Non-goals: sampled/recorded tanpura audio,
raga-specific string tunings beyond the Pa/Ma/Ni selector, gamaka, any
training-prototype change.

## Steps

1. Frequency source: derive string pitches from the current scale anchor
   (Reference Sa) so the drone retunes with presets and reference changes.
2. Pluck synthesis: sharp attack, long decay, mild inharmonic shimmer;
   reuse the existing voicing/envelope machinery where possible.
3. Scheduling: tempo-locked lookahead scheduler (metronome pattern) driving
   the Pa–Sa–Sa–Sa(low) cycle; tempo control; drift-free over minutes.
4. UI: a Tanpura control group (toggle, first-string Pa/Ma/Ni, tempo, volume)
   in the settings/mobile-more region, mirroring ison controls.
5. Verify on desktop and iOS Safari (audio unlock, background-tab throttling);
   confirm no feedback interaction with mic monitor defaults.

## Acceptance

Cycle pitches track Reference Sa and the active preset (including after preset
switches); timing stays stable while singing with detection running; toggle,
string selector, tempo, and volume behave predictably; ison and metronome are
unaffected; CI green; field-test checkpoint feedback recorded.

## Verification And Rollback

Verification: manual timing/pitch check against the singscope; PR includes a
short recording or screenshot evidence. Rollback: revert the PR; the feature
is an additive module plus controls.
