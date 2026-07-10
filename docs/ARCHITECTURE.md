# ChanterLab — Architecture

**Scope note:** this document is the architecture of the legacy Byzantine
chant engine (`web/`) specifically — tuning/pthora model, DSP, and voice
detection. It remains authoritative for that engine and for the Rust/WASM
pitch-detection work as it migrates into the training app. It is not the
architecture of the training-prototype product; see
[`training-prototype/README.md`](../training-prototype/README.md) and
[`docs/choir-training-roadmap.md`](choir-training-roadmap.md) for that.

Byzantine Organ as a browser application. This is a ground-up redesign, not a
line-by-line port, of earlier Byzantine organ tools.

Primary design goal: make the scale / pthora / accidental model as open as the
theory allows, with browser-native voice detection, pitch feedback, and
training-oriented controls.

## References

- `docs/BYZANTINE_SCALES_REFERENCE.md` — scale intervals, shadings, pthora
  families, as Chrysanthine / PMC 1881 theory. Consult for every tuning-related
  decision. These are one tradition's textbook values; see that doc's Scope
  section for what that does and doesn't cover.
- General DSP and pitch-detection literature for cepstral/autocorrelation
  methods, plus browser AudioWorklet constraints.

## 1. Goals and non-goals

### Goals (v1)

1. **Customizable scale engine.** Enable/disable any cell; apply pthora on any
   position (not just canonical degrees); apply any even-moria accidental
   (not just ±2/4/6/8). Canonical scales are presets, not constraints.
2. **Voice pipeline.** Mic → filters → gate → pitch detection → snap to
   nearest enabled cell → drive synth + PSOLA-corrected voice playback.
   Ladder cells light up to match.
3. **Singscope.** Scrolling 2D display of detected voice pitch over time,
   pitch-axis aligned row-for-row with the scale ladder.
4. **100% client-side.** Static deploy to any static host. No server.
5. **Modern browsers, desktop-first.** Chrome/Firefox/Safari latest.

### Non-goals (v1)

- Harmonization (third/fifth up/down). Phase-vocoder path deferred.
- MIDI in/out.
- Sample-based organ; v1 ships additive synthesis. Sample playback is a
  drop-in upgrade behind the voice interface later.
- Audio recording/export.
- Training mode from the C++ app (`TrainingWindow`).

## 2. Runtime topology

```
┌─────────────────────────────────────────────────────────────────────┐
│ Main thread (JS)                                                     │
│  ┌─ UI ──────────────────────────┐  ┌─ Scale engine (WASM) ───────┐ │
│  │ ScaleLadder · PthoraPalette · │  │ TuningGrid                  │ │
│  │ ShadingPalette · Singscope ·  │◄►│   regions, cells,           │ │
│  │ Ison/Keyboard/Mic controls    │  │   pthora, accidentals       │ │
│  └──────────────┬────────────────┘  └─────────────────────────────┘ │
└─────────────────│───────────────────────────────────────────────────┘
                  │ MessagePort postMessage   (cell tables, note events)
                  │
     ┌────────────┴──────────────┐
     ▼                           ▼
┌─────────────────────┐   ┌────────────────────────────────────────┐
│ VoiceWorklet        │   │ SynthWorklet                           │
│  getUserMedia in →  │   │  ison osc                              │
│  HPF → notch →      │   │  melos voices (additive organ)         │
│  gate → ring buffer │   │  corrected-voice mix-in                │
│  → rate-limited FFT │   │                                        │
│  → pitch detection  │   │  (holds its own cell→period table,     │
│  → nearest-cell snap│   │   mirrored from main thread on change) │
│  → PSOLA correction │   │                                        │
└──────────┬──────────┘   └──────────▲─────────────────────────────┘
           │                         │
           │ pitch events            │ corrected-voice audio
           │ (postMessage, 60 Hz)    │ (WebAudio node connection)
           └─────────────────────────┘
```

Three thread contexts:

1. **Main thread:** UI and `TuningGrid`. Fast edits, no realtime constraints.
2. **VoiceWorklet** (AudioWorklet): the whole mic DSP chain. Hard realtime.
3. **SynthWorklet** (AudioWorklet): voice synthesis + mixing. Hard realtime.

Communication:

- Main → Worklets: `MessagePort.postMessage` (scale updates, note on/off).
  Low-rate, JSON-compatible payloads.
- Worklets → Main: `MessagePort.postMessage` (detected pitch, gate state,
  cell highlights). Throttled to ~60 Hz.
- Audio data: native WebAudio graph. Voice worklet's output connects to the
  synth worklet (for corrected-voice playback) and optionally to destination
  (direct monitoring).

Uses separate voice-analysis, synth, and UI responsibilities connected by
`MessagePort`; AudioWorklet provides the real-time audio callback.

## 3. Core abstractions (Rust, in `chanterlab-core`)

### 3.1 TuningGrid — the single source of truth

```rust
pub struct TuningGrid {
    ref_ni_hz: f64,                      // base Ni frequency; default 130.81 (C3)
    low_moria: i32,                      // range start, default -72
    high_moria: i32,                     // range end,   default +146 (exclusive)
    regions: Vec<Region>,                // sorted ascending by start_moria, contiguous
    events: Vec<TuningEvent>,            // append-only semantic-drop log (§3.5)
    next_event_id: EventId,
    overrides: HashMap<i32, CellOverride>, // per-moria user state (accidental, enabled)
}
```

Cells are *derived* from regions + events + overrides. Mutations operate on
those; cells are recomputed by `cells()` as needed. Nothing in the UI owns
cell state.

### 3.2 Region

```rust
pub struct Region {
    pub start_moria: i32,          // absolute; inclusive
    pub end_moria: i32,            // absolute; exclusive; == next region's start_moria
    pub genus: Genus,
    pub anchor_moria: i32,         // absolute moria where anchor_degree sits
    pub anchor_degree: Degree,     // which degree is pinned at anchor_moria
    pub active_rules: Vec<EventId>, // chroa/pthora events applied to this region
}
```

A contiguous span where a single genus is active. The musical **anchor**
(`anchor_moria` / `anchor_degree`) is *independent of* `start_moria`, so a
pthora can re-root the region from a drop point in its interior without making
that point a boundary.

Created by:
- **Initialization:** one region spanning `[low_moria, high_moria)` (snapped
  outward to octave boundaries) using the user's chosen preset.
- **Applying a pthora on moria M:** *re-anchor the containing region in place*
  to the resolved `(anchor_moria, anchor_degree)` and record a
  `PthoraReanchor` event. The region is **not** split; cells on both sides of
  M are reinterpreted out to the existing boundaries.
- **Removing a pthora (`remove_pthora`):** merge the region into its left
  neighbor, extending the neighbor's `end_moria`.

### 3.3 Genus and interval storage — one convention

```rust
pub enum Genus {
    Diatonic,            // closed octave scale, canonical root Ni
    Western,             // 12-TET major in 72-moria form, root Ni — non-Byzantine preset
    HardChromatic,       // cyclic 4-step phase, canonical root Pa
    SoftChromatic,       // cyclic 4-step phase, canonical root Ni
    GraveDiatonic,       // closed octave scale, canonical root Ga
    EnharmonicZo,        // closed octave scale, canonical root Zo
    EnharmonicGa,        // 30-moria generator (6·12·12), root Ga; see SCALES_REFERENCE §4.2
    Custom { name: String, intervals: Vec<i32>, canonical_root: Degree },
}
```

Genera fall into three shapes, distinguished by `is_closed()` /
`is_chromatic_cycle()` / `is_tiled_generator()`:

- **Closed octave scales** (`Diatonic`, `Western`, `GraveDiatonic`,
  `EnharmonicZo`): a 7-interval sequence summing to 72.
- **Cyclic chromatic phases** (`HardChromatic`, `SoftChromatic`): a 4-step
  cycle that repeats every four scale degrees rather than closing at the
  octave, e.g. `HardChromatic.intervals() == [6, 20, 4, 12]`.
- **Tiled generators** (`EnharmonicGa`): a short interval sequence
  (`[6, 12, 12]`) repeated across the region span, running past the octave.

**Canonical intervals are stored once, indexed from the genus's canonical
root.** `intervals()[0]` is the step from `canonical_root` to its next degree
(Pa→Vou for HardChromatic, because Pa is its canonical root). There is no
Ni-indexed "rotation" code path. Closed-genus cell positions are computed in
`Region::degree_positions` by accumulating `rotated_intervals()` from the
region's `anchor_degree`:

```
for i in 0..7:
    cell_moria  = region.anchor_moria + sum(rotated_intervals[0..i])
    cell_degree = region.anchor_degree.shifted_by(i)  // Ni→Pa→Vou→Ga→Di→Ke→Zo→Ni'
```

`Region` carries `anchor_degree` (which degree sits at `anchor_moria`),
independent of `start_moria`. Cyclic and tiled genera are laid out by
`TuningGrid::build_generator_map` instead, walking the generator step-by-step
in both directions from the anchor.

### 3.4 Cell and accidental

```rust
pub struct Cell {
    pub moria: i32,                  // scale-derived grid position
    pub degree: Option<Degree>,      // Some if this cell is a degree
    pub chromatic_phase: Option<u8>, // phase 0..3 for cyclic chromatic genera
    pub accidental: i32,             // even; 0 = none; any ±2k accepted
    pub enabled: bool,
    pub region_idx: usize,
}

impl Cell {
    pub fn effective_moria(&self) -> i32 {
        self.moria + self.accidental
    }
}
```

Accidentals are unbounded in the data model. UI offers ±2/±4/±6/±8 as
one-click defaults and a custom-value input for larger shifts.

Cells at non-degree positions are filled in at 2-moria granularity between
degrees, disabled by default. This gives the user the full Byzantine
accidental space to light up à la carte.

### 3.5 Semantic drops and the event log

Palette interactions arrive as a `SymbolDrop` (the typed input) and are
recorded in the grid's append-only `events: Vec<TuningEvent>` log. Each cell
rebuild replays the events active on a region, so state is reconstructible and
removable by id:

```rust
pub enum SymbolDrop {
    Pthora { drop_moria, drop_degree, genus, target_degree, target_phase },
    Chroa  { drop_moria, drop_degree, symbol: Shading },
    Geniki { drop_moria, drop_degree, shift: i32 },   // ±6 general accidental
    ClearChroa { drop_moria, drop_degree },
}

pub enum TuningEventKind {
    PthoraReanchor(PthoraRule),     // re-roots the containing region in place
    ChroaPatch(ChroaRule),          // local tetrachord override on the region
    GenikiModulator(ModulatorRule), // shifts every occurrence of a degree
}

pub enum Shading { Zygos, Kliton, Spathi, Enharmonic }
```

**Pthora is generalized:** the engine accepts any `(genus, degree)` drop on
any `moria`. Rather than splitting the region at the drop point, a pthora
**re-anchors the containing region** (`anchor_moria` / `anchor_degree`) so
cells on both sides of the drop are reinterpreted. Chromatic-cycle pthorae
also resolve a `target_phase` (which step of the 4-step cycle the drop lands
on).

**Chroa (shading)** patches the region's per-degree interval steps
(`apply_chroa_patch`), preserving the drop note's absolute position. **Geniki**
is a global ±6 shift applied to every cell of a given degree. All three are
stored as events keyed to the region's `active_rules`; removing an event (or
`ClearChroa`) restores the prior anchor where one was recorded.

### 3.6 Frequency mapping

```rust
pub fn moria_to_hz(ref_ni_hz: f64, moria: i32) -> f64 {
    ref_ni_hz * 2.0_f64.powf(moria as f64 / 72.0)
}
```

The only tuning math in the system. Cell frequency is
`moria_to_hz(ref_ni_hz, cell.effective_moria())`.

### 3.7 Worker tuning table

Worklets need a fast `cell_id → period_samples` table for realtime. Main
thread computes on any grid change:

```
for each enabled cell:
    hz = moria_to_hz(ref_ni_hz, cell.effective_moria())
    period_fixed = ((sample_rate / hz) * 256) as u32    // 24.8 fixed-point
emit flat arrays (cell_ids, periods) to both worklets via postMessage
```

The DSP layer never reasons about moria directly; it receives periods in
samples for each enabled cell.

## 4. DSP pipeline (voice path)

The voice path is browser-native. Every stage below addresses a known pathology
in pitch detection; do not drop one without measuring the substitute.

### 4.1 Preprocessing (per sample)

1. Two cascaded 2nd-order highpass biquads, ~50 Hz corner (kill DC and
   rumble).
2. Optional notch filter for 50/60 Hz mains hum, with user-selectable
   frequency and width.
3. Ring buffers:
   - `audio_raw[8192]` — filtered signal for FFT analysis (≥ `FFTLEN`,
     power-of-2 for bitwise wrap).
   - PSOLA holds its own buffer of comb-filtered signal locked to the
     currently detected fundamental.
4. Envelope + **asymmetric hysteretic noise gate**:
   `gate_off_amp = gate_on_amp * 15/16`. Gate state controls whether pitch
   detection runs — the single most effective optimization is not running
   DSP during silence.

### 4.2 FFT pitch detection

`FftDetector` (cepstral FFT detection using `realfft`) is the **sole** pitch
detector. It covers the full vocal range — tested 80 Hz–1200 Hz, including
deep bass and harmonic-rich low voices. Every element listed is load-bearing:

1. **Hann window** over the last `FFTLEN` (= 5120) samples of `audio_raw`.
   5120 (doubled from 2560) gives ~8.5 cycles at 80 Hz for confident
   bass-range cepstrum peaks.
2. **Forward FFT → power spectrum → sqrt → inverse DCT** (square-root
   cepstrum). Sharper than plain autocorrelation for voiced speech.
3. **Window-bias removal** via precomputed `fft_corr`. At init, run the same
   pipeline on the Hann window itself; divide each lag at detection time.
   Without this, the window's own autocorrelation dominates at low lags.
4. **Integer-ratio alias suppression.** For `k ∈ {2, 3, 5, 7}`, subtract
   interpolated `fft_tdata[i/k]` from `fft_tdata[i]`, iterating `i` from
   `limit` downward so subtractions use corrected upstream values. Kills the
   octave-error problem.
5. **Log-bin EMA** `fft_tavg[aindex] *= 0.75` per detection, neighbor
   spreading `1/1.1^k²`. Recency bias without hard lock.
6. **Two-tier confidence gates:** accept iff `global_peak > 0.03` AND
   `second_peak / global_peak < min(global_peak * 0.6 + 0.14, 0.5)`. Below
   C4 the ambiguity limit is relaxed (up to 0.65) since low voices often
   project a stronger overtone than the fundamental.
7. **Parabolic least-squares** sub-sample interpolation using `s20`/`s42`
   moments over bins above half-amplitude.
8. Output: **24.8 fixed-point period**, clamped to
   `[sample_rate/1200, sample_rate/60]`.

There is no separate time-domain detector. The `realfft` plan is built
synchronously in `FftDetector::new`, so there is no async warm-up window to
cover, and the FFT path already spans the whole range. When the worklet WASM
is unavailable, `web/audio/voice_worklet.js` provides a pure-JS mirror of the
same cepstrum pipeline as the fallback.

### 4.4 Nearest-cell snap

`TuningGrid::nearest_enabled_cell(period_samples, last_cell_id) -> (primary, neighbor, neighbor_vel)`:

- Period-sorted index of enabled cells for O(log n) lookup.
- **`last_cell_id` hysteresis:** halve the distance to the currently-held
  cell. Kills note-edge jitter.
- Returns a neighbor cell + proportional velocity for the half-lit adjacent
  UI feedback.

If no cell is enabled in range, emits a gate-closed event — DSP treats this
as silence.

### 4.5 PSOLA correction

Experimental PSOLA-style correction. Inputs: raw or comb-filtered voice and
current `(actual_period, target_period)`. Output: pitch-shifted voice stream at
`target_period`, routed into SynthWorklet for playback alongside the organ
voice.

### 4.6 FFT scheduling

AudioWorklet has no external event loop, so the FFT runs inline in the
worklet, rate-limited: a `FFTLEN`-point (5120) FFT runs every
`FFT_DETECT_BLOCK_SIZE` (= 128) samples — tens of microseconds on modern
hardware, comfortably inside one 128-sample render-quantum budget. The
host calls `detectPitch` at that cadence whenever the gate is open.

`pitch_detect_event_count` rate-scaler (`PITCH_DETECTION_RATE_SCALE`) is
preserved for low-end environments, defaulting to 1.

## 5. Synth

Additive synthesis per voice:

```
voice(f, t) = sum_{k=1..K} (1/k^alpha) * sin(2 * pi * k * f * t) * env(t)
```

- `K = 8`, `alpha ≈ 1.2` gives a reasonable organ-like roll-off.
- Envelope: fast attack, flat sustain, slow release. Organ-like, not piano.
- Max ~16 simultaneous voices.
- Ison runs as a persistent voice with slightly different harmonic
  weighting (more fundamental, less upper partials) for drone character.

The voice function is pluggable behind a trait. Replacing additive with a
sample player later is a local change — same `note_on / note_off` interface.

## 6. UI

### 6.1 Scale ladder

Vertical 1D column. Not a 2D piano roll — the time axis lives in the
singscope. Rows:

- Degree cells: wider, labeled with martyria syllable + octave marker.
- Non-degree cells: narrower, unlabeled until enabled.
- Enabled cells: filled. Disabled: hollow outline.
- Active (playing): strong highlight.
- Voice-detected: secondary highlight; neighbor cell half-lit for the
  proportional-velocity feedback.
- Accidental: small ± badge with the moria offset.

Interactions:
- Click a cell → toggle `enabled`.
- Right-click a cell → accidental menu (±2/4/6/8 buttons + custom field).
- Drop target for pthora palette.
- Drop target for shading palette (degree cells only).

### 6.2 Pthora palette

Panel of draggable SVG/PNG icons, organized by family (Diatonic /
Chromatic / Enharmonic). Assets live under `web/assets/pthora/`. Drop fires
`TuningGrid::apply_pthora(moria, pthora)` and the ladder redraws. The affected
region can optionally carry a tint.

### 6.3 Shading palette

Panel of 4 shadings (Zygos, Kliton, Spathi A, Spathi B). Drop on a degree
cell → set the containing region's `shading` field.

### 6.4 Singscope

Scrolling 2D canvas, immediately right of the scale ladder, sharing its
Y axis:

- **Y axis:** moria, aligned row-for-row with the ladder.
- **X axis:** time, scrolling right-to-left. Speed configurable.
- **Pitch polyline:** detected voice pitch, continuous; color varies with
  confidence.
- **Snap polyline:** correction target, stepped at cell boundaries.
- **Cell background bands:** faint tint on enabled-cell rows for visual
  anchoring.
- **Gate state:** pitch line dims/breaks when gate closes.

Fed by throttled pitch events from VoiceWorklet (~60 Hz). Pure presentation;
DSP is agnostic to the view.

### 6.5 Controls panel

- Genus preset selector.
- Base Ni frequency slider (default 130.81 Hz).
- Ison: degree selector, octave ±, volume.
- Mic: enable toggle, input device picker, gate threshold, correction
  toggle.
- Keyboard routing (QWERTY → cells).
- Viewport shift arrows (move the ladder/singscope up/down the range).

## 7. Crate and repo layout

The crate is a single flat `src/` tree (no nested `core/` crate). Rust tests
live inline as `#[cfg(test)] mod tests` next to the code they cover — there is
no separate top-level `tests/` directory. The synth is implemented in JS
(`web/audio/`), not Rust.

```
chanterlab/
├── Cargo.toml                 # one crate, features: main | worklet | serde
├── src/
│   ├── lib.rs                 # main-thread wasm_bindgen exports (JsTuningGrid)
│   ├── worklet.rs             # worklet-bundle wasm_bindgen exports (VoiceProcessor)
│   ├── tuning/
│   │   ├── mod.rs
│   │   ├── grid.rs            # TuningGrid + nearest_enabled_cell + tuning_table
│   │   ├── region.rs          # Region (span + anchor)
│   │   ├── genus.rs           # Genus + interval tables
│   │   ├── degree.rs          # Degree (Ni..Zo) + shifted_by
│   │   ├── cell.rs            # Cell, CellOverride
│   │   ├── pthora.rs          # SymbolDrop, PthoraRule
│   │   ├── shading.rs         # Shading
│   │   └── event.rs           # TuningEvent, TuningEventKind, ChroaRule, ModulatorRule
│   └── dsp/
│       ├── mod.rs
│       ├── filters.rs         # BiquadHpf/CascadedHpf, NotchFilter
│       ├── gate.rs            # envelope + hysteretic gate
│       ├── detector.rs        # FftDetector (cepstral FFT)
│       └── psola.rs           # PsolaRepitcher
├── web/
│   ├── index.html · app.js · style.css
│   ├── ui/                    # scale_ladder, pthora_palette, shading_palette,
│   │                         # singscope, vkeyboard, metronome, note_indicator, …
│   ├── audio/                 # audio_engine, voice_worklet, synth_worklet (JS DSP/synth)
│   ├── score/                 # glyph score editor, parser, compiler, timing, + node tests
│   └── fonts/neanes/          # bundled Neanes notation font (own license)
└── docs/
    ├── ARCHITECTURE.md        # this file
    ├── BYZANTINE_SCALES_REFERENCE.md
    └── …                      # proposals + testing guides
```

The crate compiles to **two WASM bundles** via `wasm-pack` (see `Makefile`),
each with `--no-default-features`:

- feature `main`: full `TuningGrid` + `Genus` + serialization (`JsTuningGrid`).
- feature `worklet`: only DSP primitives + frequency math (`VoiceProcessor`),
  for use inside the AudioWorklet.

## 8. Cross-cutting concerns

### 8.1 Sample rate

WebAudio picks `AudioContext.sampleRate` (44.1k or 48k typically). All
DSP constants that depend on it are derived at worklet init from
`sampleRate` (standard in `AudioWorkletGlobalScope`). Never hard-code.

### 8.2 WASM in the worklet

AudioWorklet modules have no `fetch()` for WASM. Approach:

1. Main thread fetches the worklet-bundle `.wasm` as an `ArrayBuffer`.
2. `audioWorklet.addModule(workletUrl)` loads the JS.
3. Main thread `postMessage`s the `ArrayBuffer` to the worklet at init.
4. Worklet calls `WebAssembly.instantiate(buf)` and holds the instance.

Same pattern for both worklets. One WASM binary, shared across them (each
worklet gets its own instance).

### 8.3 State sync

Single authoritative `TuningGrid` on the main thread. Worklets hold
projections (period tables, not regions). On every grid mutation the main
thread recomputes the projection and pushes it. Worklets apply atomically
at the start of the next render quantum.

### 8.4 Persistence

`TuningGrid::serialize()` → JSON. LocalStorage for the active state; named
user presets as LocalStorage keys. No server component.

## 9. Testing

- **Rust unit tests** (`cargo test`): cell computation, pthora application,
  shading, accidentals, `moria_to_hz`. Every tuning operation.
- **Rust property tests** (`proptest`): grid invariants — cells sorted,
  regions contiguous, `sum(region_span) == high_moria - low_moria`.
- **Rust DSP tests:** synthetic signals (pure sines, harmonic stacks,
  vocal-like noise-modulated tones) at known frequencies. Expected
  accuracy: period to within 0.5% at SNR ≥ 20 dB.
- **WASM integration** via `wasm-bindgen-test` headless-browser harness.
- **UI manual checklist** — correctness here is largely perceptual.

## 10. DSP Implementation Notes

Build DSP changes from documented signal-processing techniques and local
measurements. Avoid line-by-line translation from third-party source trees.

Skip desktop-framework glue (QIODevice, mutexes, signals). Replace with Rust types and
`postMessage`.
