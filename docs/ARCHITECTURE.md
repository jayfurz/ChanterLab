# Byzorgan Web — Architecture

Byzantine Organ as a browser application. This is a ground-up redesign, not a
port, of the C++ Byzorgan r138 desktop app at
`/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/`.

Primary design goal: make the scale / pthora / accidental model as open as the
theory allows, while preserving the pedagogical voice-detection and
pitch-correction loop that is the distinctive feature of the original.

## Authoritative references

- `docs/BYZANTINE_SCALES_REFERENCE.md` — scale intervals, shadings, pthora
  families. Consult for every tuning-related decision.
- `/mnt/data/code/byzorgan-source/ARCHITECTURE.md` — DSP/threading reference
  for the C++ app (§6 in particular is the centerpiece for pitch detection).
- `/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/vocproc.{h,cpp}` —
  pitch-detection source; line ranges cited inline below.
- `/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/repitcher.{h,cpp}` —
  PSOLA source.

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

Mirrors the C++ app's `VocProc` + `Synthesizer` + `AudioMixer` split
(`byzorgan-source/ARCHITECTURE.md` §4–§5). `MessagePort` replaces Qt queued
signals; AudioWorklet replaces the RtAudio callback.

## 3. Core abstractions (Rust, in `byzorgan-core`)

### 3.1 TuningGrid — the single source of truth

```rust
pub struct TuningGrid {
    ref_ni_hz: f64,                      // base Ni frequency; default 261.63
    low_moria: i32,                      // range start, default -108 (3 octaves total)
    high_moria: i32,                     // range end,   default +108
    regions: Vec<Region>,                // sorted ascending by start_moria, contiguous
    overrides: HashMap<i32, CellOverride>, // per-moria user state (accidental, enabled)
}
```

Cells are *derived* from regions + overrides. Mutations operate on regions
and overrides; cells are recomputed (or incrementally updated) as needed.
Nothing in the UI owns cell state.

### 3.2 Region

```rust
pub struct Region {
    pub start_moria: i32,          // absolute; inclusive; equal to root_degree's position
    pub end_moria: i32,            // absolute; exclusive; == next region's start_moria
    pub genus: Genus,
    pub root_degree: Degree,       // which degree sits at start_moria
    pub shading: Option<Shading>,
}
```

A contiguous span where a single genus is active, rooted at a specific
degree at its start boundary.

Created by:
- **Initialization:** one region spanning `[low_moria, high_moria)` using the
  user's chosen preset.
- **Applying a pthora on moria M:** split the existing region at M; insert a
  new region `[M, next_boundary)` with the pthora's `(genus, degree)`.
- **Removing a pthora:** merge neighbors if their `(genus, root_degree)`
  agree; otherwise prompt the user.

### 3.3 Genus and interval storage — one convention

```rust
pub enum Genus {
    Diatonic,
    HardChromatic,
    SoftChromatic,
    GraveDiatonic,
    EnharmonicZo,
    EnharmonicGa,         // generator, see BYZANTINE_SCALES_REFERENCE §4.2
    Custom(Vec<i32>),
}
```

**Canonical intervals are stored once, indexed from the genus's canonical
root.** For example, `HardChromatic.intervals() == [6, 20, 4, 12, 6, 20, 4]`
where `intervals[0]` is `Pa → Vou` — because Pa is HardChromatic's canonical
root. There is no "rotation." A region's cell positions are computed:

```
for i in 0..7:
    cell_moria = region.start_moria + sum(intervals[0..i])
    cell_degree = region.root_degree.shifted_by(i)  // wraps Ni→Pa→Vou→Ga→Di→Ke→Zo→Ni'
```

This collapses the tangled rotation math from the original PLAN.md. `Region`
carries `root_degree`, which names which degree sits at `start_moria`.

`EnharmonicGa` is a 30-moria tetrachord generator (`6·12·12`) that tiles
across the region span. It's not a closed 7-interval sequence; model it by
repeating the generator and letting it run past the octave, with the closing
segment adjusted at region boundaries.

### 3.4 Cell and accidental

```rust
pub struct Cell {
    pub moria: i32,                // scale-derived grid position
    pub degree: Option<Degree>,    // Some if this cell is a degree
    pub accidental: i32,           // even; 0 = none; any ±2k accepted
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

### 3.5 Pthora and shading

```rust
pub struct Pthora {
    pub genus: Genus,
    pub target_degree: Degree,    // what the drop point becomes
}

pub enum Shading {
    Zygos,     // 18·4·16·4 from Ga
    Kliton,    // 20·4·4·14 from Ga
    SpathiA,   // 14·12·4 from Ga
    SpathiB,   // 14·4·4·20 from Ga
}
```

**Pthora is generalized:** the engine accepts any `(genus, degree)` drop on
any `moria`, not only canonical degrees. The UI palette exposes the common
families; the engine doesn't care.

**Shading** is stored per-region as an optional local tetrachord override,
applied every time the region's cells are rebuilt.

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

Mirrors C++ `VocProc::setKeyTuning(key, period)`
(`byzorgan-source/ARCHITECTURE.md` §5.1) — DSP never reasons about moria,
only periods in samples.

## 4. DSP pipeline (voice path)

Ported faithfully from `vocproc.cpp`. Section numbers below cross-reference
`byzorgan-source/ARCHITECTURE.md` §6. The C++ code is load-bearing — every
one of these elements addresses a known pathology in pitch detection. Don't
drop any without testing the substitute.

### 4.1 Preprocessing (per sample)

1. Two cascaded 2nd-order highpass biquads, ~50 Hz corner (kill DC and
   rumble). Port coefficients from `vocproc.cpp:665-666`.
2. Optional notch filter for 50/60 Hz mains hum, with user-selectable
   frequency and width. Port of `NotchFilter` inline in `vocproc.h:23-46`.
3. Ring buffers:
   - `audio_raw[4096]` — filtered signal for FFT analysis.
   - `audio_in[16384]` — comb-filtered signal locked to the currently
     detected fundamental; source for PSOLA.
4. Envelope + **asymmetric hysteretic noise gate**:
   `gate_off_amp = gate_on_amp * 15/16`. Gate state controls whether pitch
   detection runs — the single most effective optimization is not running
   DSP during silence.

### 4.2 FFT pitch detection (default)

Port of `pitchDetection()` in `vocproc.cpp:1202-1348` using `rustfft` or
`realfft`. Every element listed is load-bearing:

1. **Hann window** over the last 2560 samples of `audio_raw`.
2. **Forward FFT → power spectrum → sqrt → inverse DCT** (square-root
   cepstrum). Sharper than plain autocorrelation for voiced speech.
3. **Window-bias removal** via precomputed `fft_corr`. At init, run the same
   pipeline on the Hann window itself; divide each lag at detection time
   (`vocproc.cpp:1218-1223`). Without this, the window's own autocorrelation
   dominates at low lags.
4. **Integer-ratio alias suppression.** For `k ∈ {2, 3, 5, 7}`, subtract
   interpolated `fft_tdata[i/k]` from `fft_tdata[i]`, iterating `i` from
   `limit` downward so subtractions use corrected upstream values
   (`vocproc.cpp:1227-1237`). Kills the octave-error problem.
5. **Log-bin EMA** `fft_tavg[aindex] *= 0.75` per detection, neighbor
   spreading `1/1.1^k²`. Recency bias without hard lock.
6. **Two-tier confidence gates:** accept iff `global_peak > 0.03` AND
   `second_peak / global_peak < min(global_peak * 0.6 + 0.14, 0.5)`.
   Clarity threshold relaxes when the winner is strong.
7. **Parabolic least-squares** sub-sample interpolation using `s20`/`s42`
   moments over bins above half-amplitude (`vocproc.cpp:1295-1329`).
8. Output: **24.8 fixed-point period**, clamped to
   `[sample_rate/1200, sample_rate/60]`.

### 4.3 Time-domain fallback

Port of `checkPeriod()` + `doSimpleDetection()`
(`vocproc.cpp:846-879, 1131-1176`). Peak-state machine with adaptive
threshold (`threshold = (peakHigh*2 + peakLow)/3`), log-spaced histogram
over the active key set, half-life decay (`hits >>= 1`) each 2048 samples.

Keep the fallback for low-end mobile and as the pre-warm path while the
FFT plan initializes.

### 4.4 Nearest-cell snap

`TuningGrid::nearest_enabled_cell(period_samples, last_cell_id) -> (primary, neighbor, neighbor_vel)`:

- Period-sorted index of enabled cells for O(log n) lookup.
- **`last_cell_id` hysteresis:** halve the distance to the currently-held
  cell. Kills note-edge jitter (port of `processPeriod`'s `lastKey` bias,
  `vocproc.cpp:1008-1129`).
- Returns a neighbor cell + proportional velocity for the half-lit adjacent
  UI feedback from the original.

If no cell is enabled in range, emits a gate-closed event — DSP treats this
as silence.

### 4.5 PSOLA correction

Port of `RepitchPSOLA` (`repitcher.cpp`). Inputs: raw or comb-filtered voice
and current `(actual_period, target_period)`. Output: pitch-shifted voice
stream at `target_period`, routed into SynthWorklet for playback alongside
the organ voice.

### 4.6 FFT scheduling

C++ defers the FFT to `AudioThread`'s Qt event loop via `postEvent`
(ARCHITECTURE.md §6.3). AudioWorklet has no external event loop. We run the
FFT inline in the worklet with the C++ rate limiter intact: a 2560-point
FFT runs ~every 256 samples (`FFT_DETECT_BLOCK_SIZE`) — tens of microseconds
on modern hardware, safely under a 128-sample (`render quantum`) budget.

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
Chromatic / Enharmonic). Assets exist in `byzorgan-source/`; port to
`web/assets/pthora/`. Drop fires `TuningGrid::apply_pthora(moria, pthora)`
and the ladder redraws. The affected region can optionally carry a tint.

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
- Base Ni frequency slider (default 261.63 Hz).
- Ison: degree selector, octave ±, volume.
- Mic: enable toggle, input device picker, gate threshold, correction
  toggle.
- Keyboard routing (QWERTY → cells).
- Viewport shift arrows (move the ladder/singscope up/down the range).

## 7. Crate and repo layout

```
byzorgan-web/
├── Cargo.toml
├── src/
│   ├── lib.rs                 # main-thread wasm_bindgen exports
│   └── worklet.rs             # worklet-bundle wasm_bindgen exports
├── core/
│   ├── mod.rs
│   ├── tuning/
│   │   ├── mod.rs
│   │   ├── grid.rs            # TuningGrid
│   │   ├── region.rs          # Region, Genus (+ interval tables)
│   │   ├── cell.rs            # Cell, Accidental
│   │   ├── pthora.rs
│   │   └── shading.rs
│   ├── dsp/
│   │   ├── mod.rs
│   │   ├── filters.rs         # biquad HPF, NotchFilter, CombFilter
│   │   ├── gate.rs            # envelope + hysteretic gate
│   │   ├── detector.rs        # FFT + time-domain detectors
│   │   └── psola.rs
│   └── synth/
│       ├── mod.rs
│       └── additive.rs
├── web/
│   ├── index.html
│   ├── style.css
│   ├── app.js                 # entry; WASM init; UI wiring
│   ├── ui/
│   │   ├── scale_ladder.js
│   │   ├── pthora_palette.js
│   │   ├── shading_palette.js
│   │   ├── singscope.js
│   │   ├── controls.js
│   │   └── vkeyboard.js
│   ├── audio/
│   │   ├── voice_worklet.js
│   │   └── synth_worklet.js
│   └── assets/
│       └── pthora/
├── docs/
│   ├── ARCHITECTURE.md        # this file
│   └── BYZANTINE_SCALES_REFERENCE.md
└── tests/
    ├── tuning/*.rs
    ├── dsp/*.rs
    └── integration/*.rs
```

The crate compiles to **two WASM bundles** via `wasm-pack` with different
feature flags:

- `byzorgan-core` (feature `main`): full `TuningGrid` + `Genus` + serialization.
- `byzorgan-core` (feature `worklet`): only DSP primitives + frequency math,
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

## 10. Suggested reading order when porting DSP

From `byzorgan-source/ARCHITECTURE.md` §9:

1. `vocproc.h` — signal surface and data layout.
2. `vocproc.cpp::writeData` — per-sample hot path.
3. `vocproc.cpp::pitchDetection` — FFT detector algorithm.
4. `vocproc.cpp::processPeriod` — nearest-key logic.
5. `repitcher.h` + `repitcher.cpp::RepitchPSOLA::convertSamples` — PSOLA.

Skip the Qt glue (QIODevice, mutexes, signals). Replace with Rust types and
`postMessage`.
