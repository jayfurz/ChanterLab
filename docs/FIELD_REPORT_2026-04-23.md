# Field report — 2026-04-23 regressions & fixes

Five user-reported issues after the Phase-6 build. Diagnoses reference
file:line; each fix is self-contained. Ordered by blast radius, not by
user-report order.

---

## 1. Pthora / shading / toggle don't propagate to the audio engine

**Symptom (user):** "when changing the pthora the voice still snaps to the
original diatonic scale — not the one I colored it to with the pthora or
accidentals."

**Root cause.** `ScaleLadder._onPaletteDrop`, `_onClick`, and the pre-rewrite
`_onDrop` all mutate the grid and then call `this.refresh()`. `refresh()` only
re-reads cells for the canvas — it does **not** call the app-level
`gridChanged()` in `web/app.js:68` that pushes the new tuning table to the
synth and voice worklets, rebuilds the keyboard map, and re-resolves the ison
voice.

Evidence:
- `web/ui/scale_ladder.js:246` (`_onClick`): `toggleCell` + `refresh()` only.
- `web/ui/scale_ladder.js:260` (`_onPaletteDrop`): `applyPthora`/`applyShading`
  + `refresh()` only.
- `web/app.js:68` (`gridChanged`): is what calls `app.engine.updateTuning(...)`
  — but it's a module-local function, not reachable from `ScaleLadder`.

The accidental popup path is fine because `wireAccidentalPopup` calls
`gridChanged()` after `setAccidental` (`web/app.js:229`). Only the ladder-local
paths are broken.

**Fix.** Expose `gridChanged` on the `app` object and have the ladder call it.

```js
// web/app.js, after `const app = { ... }`
app.gridChanged = function gridChanged() {
  app.ladder.refresh();
  if (app.singscope) app.singscope.setRowMap(app.ladder.rowMap);
  const cells = JSON.parse(app.grid.cellsJson());
  app.keyboard.rebuildKeyMap(cells);
  app.engine.updateTuning(cells, app.grid.refNiHz);
  updateIsonVoice(cells);
};
```

Then in `web/ui/scale_ladder.js`, replace every `this.refresh()` that follows
a grid mutation with `this.app.gridChanged()`:
- `_onClick` (toggle)
- `_onPaletteDrop` (pthora, shading)

Leave `refresh()` itself for paint-only callers (resize, detected-cell
highlight).

Also audit `wireControls` — the `ni-hz-slider` handler already calls
`gridChanged()`. `shift-up-btn` / `shift-down-btn` are placeholders. Reset
button: OK.

---

## 2. Organ and mic are mono-routed to the left channel

**Symptom (user):** "the sound only comes out on the left ear, not even the
ison drone."

**Root cause.** Both worklets are instantiated without `outputChannelCount`,
so they default to mono output. Safari / iPadOS WebAudio does not
universally upmix a 1-channel worklet output to the stereo destination the
way Chrome does — it drops the mono into channel 0 and leaves channel 1
empty, which is heard as left-only.

Evidence:
- `web/audio/audio_engine.js:45` creates `synth-processor` with no
  `outputChannelCount`.
- `web/audio/synth_worklet.js:131`: `process` writes only `outputs[0][0]`.
- `voice-processor` at `audio_engine.js:82` same issue, but its output feeds
  the synth's input mix, not the destination, so it's less visible.

**Fix.** Declare stereo outputs explicitly and write both channels.

```js
// web/audio/audio_engine.js:45
this._node = new AudioWorkletNode(this._ctx, 'synth-processor', {
  numberOfInputs: 1,
  outputChannelCount: [2],
});
```

```js
// web/audio/synth_worklet.js, SynthProcessor.process
const out = outputs[0];
const chL = out?.[0];
const chR = out?.[1];
if (!chL) return true;
chL.fill(0);
// ... render voices / ison / mix voiceIn into chL ...
if (chR) chR.set(chL);   // duplicate to right
```

The synth output is intrinsically mono — stereo-izing is just a duplicate.
If we later add stereo detune or a simple haas widener, this is where it
slots in.

Leave `voice-processor` mono for now (single-channel mic → mono monitor);
stereo distribution happens in the synth.

---

## 3. Ni ison at moria=0 silently disables instead of playing

**Symptom (user):** "the Ni ison drone doesn't work (likely too low for the
synth, since Pa and above work)."

**Root cause.** Not frequency-related. `moria=0` is C4 = 261.63 Hz, well
inside the synth's range. The bug is a falsy-check on `cell_id` in the ison
handler:

```js
// web/audio/synth_worklet.js:117
if (!msg.cell_id || msg.volume <= 0) {      // ← !0 === true
  // ... disable ison ...
  return;
}
```

When the user selects Ni / octave 0, `updateIsonVoice` finds the cell at
`moria = 0` and posts `{ cell_id: 0, volume }`. The `!msg.cell_id` branch
fires, the ison is disabled. Pa (moria=12), Vou (moria=22), etc. all work
because their `cell_id` is truthy.

**Fix.** Compare explicitly to null.

```js
// web/audio/synth_worklet.js:117
if (msg.cell_id == null || msg.volume <= 0) {
  if (this._isonVoice) { this._isonVoice.release(); this._isonVoice = null; }
  return;
}
```

Grep the rest of the worklet for the same pattern — `noteOn`/`noteOff` use
`this._tuning.get(msg.cell_id)` with `.get(0)` returning the hz, which is
correct. `ison` is the only broken case.

---

## 4. Voice monitor is too quiet even at max slider

**Symptom (user):** "the vocal playback is too quiet."

**Root cause.** The voice worklet emits the HPF'd mic signal at its natural
level (`voice_worklet.js:611`). At the synth mixer (`synth_worklet.js:151`)
it's multiplied by `_correctionVolume ∈ [0, 1]` with slider default 0.5.
Compared to the additive organ voice, which is normalised to peak sum = 1
per voice and stacks up to 16 voices, the dry mic sits 15–25 dB below the
organ even at `volume = 1.0`.

**Fix.** Apply a fixed pre-gain to the mic path so `volume = 1.0` is roughly
level-matched with a single organ note. A 4× (≈ +12 dB) multiplier is a
reasonable starting point; make it a constant so we can tune it per-device
later without re-plumbing.

```js
// web/audio/synth_worklet.js, top
const VOICE_MIX_GAIN = 4.0;   // pre-gain on mic signal so the slider 0–1
                              // range brackets a useful monitor level

// in process(), when mixing voiceIn:
if (voiceIn) {
  const vol = this._correctionVolume * VOICE_MIX_GAIN;
  for (let i = 0; i < ch.length; i++) ch[i] += voiceIn[i] * vol;
}
```

Guard against clipping if the user sings loud + organ loud: rely on WebAudio
soft-clipping at the destination for now. If it becomes a problem, add a
simple tanh limiter after the mix.

Caveat: iPad mics with `autoGainControl: false` (which we request — see
`audio_engine.js:76`) can still vary wildly between chassis. +12 dB is
a starting point. Expose as a separate "mic gain" slider in Phase 7 polish.

---

## 5. Voice pitch detection doesn't trigger below C4 for bass/baritone

**Symptom (user, self-identified bass/baritone):** "when I sing, it doesn't
seem to pick up my voice until I get to C4."

This is the hardest one to diagnose without instrumenting the detector, so
the fix below is the high-confidence lever plus a list of hypotheses to
test with telemetry.

### Highest-confidence contributor

Issue #1 (tuning table not re-pushed after pthora/shading/toggle) makes the
user think "detection isn't working" when actually detection *is* running —
the snap result is just to an outdated cell set. After fixing #1, re-test
the bass range. It's plausible #5 partially disappears on its own.

### Remaining plausibly-causal issues

If after #1 the bass still fails:

**(a) Tuning table upper bound (smallest period, highest pitch) is used as
`min_lag` in the FFT detector.** See `src/dsp/detector.rs:467` and the JS
mirror. A user on the default grid has enabled cells from Ni(−72, ~130 Hz)
up to Ni(+72, ~523 Hz). `tuning_table[0].period` corresponds to the Ni+72
cell = the highest pitch = ~92 samples. Good. But if the user applies a
pthora that disables or shifts the top register, `min_lag` might grow and
cut off valid lower-pitch lags — unlikely in practice (min_lag is the lower
bound on lag, not upper), but worth confirming with a log line:

```js
// voice_worklet.js _runPitchAndEmit / _processWasm
console.log('min_lag', this._tuning[0]?.period, 'limit', limit);
```

**(b) FFT window is marginal for very low pitches.** `FFTLEN = 2048` (JS) /
`2560` (Rust). At 48 kHz, a 2048-sample window contains only ~3.4 cycles of
an 80 Hz bass note; the autocorrelation peak at lag 600 is weak and easily
killed by the `globalPeak > 0.03` confidence gate
(`src/dsp/detector.rs:395`). The port faithfully mirrors the C++ constants,
so this isn't a regression — but the C++ Byzorgan ran at 44.1 kHz by
default, where the same 2560-sample window gets ~4.5 cycles at 80 Hz.

Options:
- Bump `FFTLEN` to 4096 (JS) / 5120 (Rust). Doubles window length → roughly
  √2 better low-pitch confidence, costs one extra FFT pair per detect (~1ms
  on modern hardware).
- Or lower the `globalPeak` threshold from 0.03 to ~0.015 when the candidate
  peak lag is in the bass range. Two-tier threshold. Trickier; adds a knob.

Preferred: bump FFTLEN. One-line change in each detector + retest.

**(c) HPF cutoff.** `CascadedHpf` corner ~32 Hz (two cascaded stages of the
Butterworth at `vocproc.cpp:665-666`). Attenuation at 80 Hz is small — on
the order of 2–3 dB total across both stages. Not a suspect.

**(d) Gate threshold.** Default `0.01` linear ≈ −40 dBFS. iPad mic at normal
singing distance clears this by 20+ dB. Not a suspect unless the user is
very far from the mic.

### Proposed sequence

1. Ship fix #1, retest bass — see if the problem self-resolves.
2. If not, add a one-shot telemetry message in the voice worklet that posts
   `{ min_lag, limit, global_peak, second_peak_ratio, period_24_8 }` on
   every detect call. Run it once with bass input, read the log, decide
   between (a/b).
3. If (b): bump FFTLEN to 4096 in JS and 5120 in Rust. Rebuild the worklet
   bundle with `wasm-pack build --target no-modules --features worklet`.

---

## 6 (bonus). Drop target is invisible during drag

**Symptom (user):** "coloring the scale with the pthora palette is hard
because it doesn't show me where exactly the pthora is landing."

Not a bug per se — the palette rewrite from HTML5 drag to pointer events
(yesterday) traded the browser's native `:drop-target` affordance for a
floating ghost. No cell preview is shown.

**Fix.** Add a hover signal to `pointer_drag.js`: on every `pointermove` past
the threshold, dispatch `byzorgan:palette-hover` on the closest
`targetSelector` with `{ clientX, clientY }` (and `byzorgan:palette-hover` /
`null` when the pointer leaves the target). The `ScaleLadder` listens and
renders a hover band on the cell under the pointer (same row-map hit-test
as `_onPaletteDrop`).

Sketch:

```js
// web/ui/pointer_drag.js, in onMove after positionGhost:
const hoverTarget = hitTestTarget(me.clientX, me.clientY, targetSelector);
if (hoverTarget !== lastHoverTarget) {
  if (lastHoverTarget) {
    lastHoverTarget.dispatchEvent(new CustomEvent('byzorgan:palette-hover', {
      detail: { payload: data, clientX: null, clientY: null, leaving: true },
    }));
  }
  lastHoverTarget = hoverTarget;
}
if (hoverTarget) {
  hoverTarget.dispatchEvent(new CustomEvent('byzorgan:palette-hover', {
    detail: { payload: data, clientX: me.clientX, clientY: me.clientY },
  }));
}
```

```js
// web/ui/scale_ladder.js constructor:
canvas.addEventListener('byzorgan:palette-hover', e => this._onPaletteHover(e));

_onPaletteHover(e) {
  const { clientY, leaving } = e.detail;
  if (leaving) {
    this._hoverCell = null;
  } else {
    const rect = this.canvas.getBoundingClientRect();
    this._hoverCell = this._hitTest(clientY - rect.top);
  }
  this._paint();
}
```

Then in `_paint`, if `_hoverCell` is set, overlay a thick border (pthora
region tint for pthora drops, accent for shading drops). The payload type
is available via `e.detail.payload.type`, so the preview can even show the
final region colour.

---

## Implementation order

1. **#1 (gridChanged routing)** — most impactful, smallest diff. Fixes the
   "doesn't follow my pthora" complaint and is a prerequisite for diagnosing
   #5 cleanly.
2. **#3 (Ni ison `!cell_id` bug)** — one-character fix (`!` → `== null`).
3. **#2 (stereo routing)** — two files, small diff. Restores right-ear
   audio.
4. **#4 (voice monitor gain)** — one constant + one multiplication.
5. **#6 (drop hover preview)** — UX polish, not a bug. ~30 lines.
6. **#5 (bass detection)** — revisit only after #1 lands and is retested.
   Add telemetry first; don't FFTLEN-bump blindly.

Total code surface if all five ship: ~80 lines across 4 files, no Rust
change unless #5 escalates to the FFTLEN bump.
