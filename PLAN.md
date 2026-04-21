# Byzorgan Web — Implementation Plan

> Architecture and design decisions live in `docs/ARCHITECTURE.md`. This
> document is the implementation sequence. Read ARCHITECTURE.md first.

**Goal:** Customizable Byzantine organ in the browser, with voice pitch
detection + PSOLA correction and a singscope visualization. Rust/WASM core;
WebAudio + Canvas UI; fully client-side.

**Authoritative scale reference:** `docs/BYZANTINE_SCALES_REFERENCE.md`.
Consult for every tuning-related task.

**C++ source to port DSP from:**
`/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/` — notably
`vocproc.{h,cpp}` and `repitcher.{h,cpp}`.

## Ground rules

1. **One interval convention.** Canonical intervals are indexed from each
   genus's canonical root (Pa for HardChromatic, Zo for EnharmonicZo, etc.),
   stored as `[i32; 7]` summing to 72. Cell positions are computed by
   accumulating from `region.start_moria`. There is no "rotate a Ni-indexed
   array" code path — that was the central bug in the previous plan.
2. **Tests first for tuning code.** Every `TuningGrid` operation lands with
   a failing test, then an implementation, then a commit.
3. **Port DSP, don't reinvent.** For pitch detection and PSOLA, the C++
   source is load-bearing. Each algorithmic element (window bias removal,
   alias suppression, log-bin EMA, confidence gates, parabolic LSQ) is
   there to address a specific pathology — don't drop elements without
   replacement.
4. **Commit after each task.** Commit message style:
   `feat|fix|test|docs|refactor|chore: short imperative`.
5. **Skip features the user hasn't asked for.** No harmonization, no MIDI,
   no sample-based organ in v1. No training mode.

---

## Phase 1 — Rust tuning engine

Scale/pthora/accidental model. Entirely pure Rust, no WASM, no browser.
Every task is test-driven.

### 1.1 Project skeleton

- `Cargo.toml` with `[lib] crate-type = ["cdylib", "rlib"]`.
- Two features: `main` (full API) and `worklet` (DSP only).
- Dependencies: `wasm-bindgen` (feature-gated), `rustfft` or `realfft`
  (worklet feature), `serde`/`serde_json` (main feature), `proptest` (dev).
- `src/lib.rs` empty; `core/mod.rs` declares submodules.
- `.gitignore`: `target/`, `pkg/`, `node_modules/`.
- Git init + initial commit.
- Verify: `cargo build --no-default-features`, `cargo test`.

### 1.2 `Degree` and `Genus` with canonical intervals

- `core/tuning/region.rs` (or `degrees.rs` + `genus.rs` if that reads better).
- `Degree { Ni = 0, Pa, Vou, Ga, Di, Ke, Zo }` with `name()`, `shifted_by(i)`
  (wrapping), `canonical_root_for(genus)`.
- `Genus` enum with `intervals() -> [i32; 7]` returning canonical-root
  sequences:
  - `Diatonic`       (Ni) → `[12, 10, 8, 12, 12, 10, 8]`
  - `HardChromatic`  (Pa) → `[6, 20, 4, 12, 6, 20, 4]`
  - `SoftChromatic`  (Ni) → `[8, 14, 8, 12, 8, 14, 8]`
  - `GraveDiatonic`  (Ga) → rotated from the reference-doc Ni-indexed row so
    it starts with `Ga → Di`. Verify via a unit test that
    `sum(intervals) == 72` and the Ni-origin cumulative matches the
    reference doc.
  - `EnharmonicZo`   (Zo) → `[6, 12, 12, 12, 6, 12, 12]`
  - `EnharmonicGa`   (Ga) — **generator form**, see §1.5 below. Omit from
    the closed-scale test.
  - `Custom(Vec<i32>)` — validated to be non-empty, all-positive, sum ≤ 72
    for scale presets (but `EnharmonicGa` is exempt).
- Tests:
  - `canonical_intervals_sum_to_72` for all closed genera.
  - `degree_shifted_by_wraps` over all indices 0..=13.
- Commit.

### 1.3 `Region` and `Cell`

- `core/tuning/region.rs`: `Region { start_moria, end_moria, genus,
  root_degree, shading }`.
- `core/tuning/cell.rs`: `Cell { moria, degree, accidental, enabled,
  region_idx }`, `effective_moria()`.
- `Region::degree_positions()` returns the 7 cell moria within the region,
  starting from `start_moria + 0`, stepping by `genus.intervals()` starting
  at offset 0 (since stored canonically).
- Tests: given a `Region { start_moria: 0, genus: Diatonic, root_degree: Ni,
  shading: None }`, `degree_positions() == [0, 12, 22, 30, 42, 54, 64]`.
  Same for a Pa-rooted HardChromatic region.

### 1.4 `TuningGrid` — single region baseline

- `core/tuning/grid.rs`: `TuningGrid { ref_ni_hz, low_moria, high_moria,
  regions, overrides }`.
- Constructor `TuningGrid::new(preset: Genus, ref_ni_hz: f64)` creates one
  region spanning `[low_moria, high_moria)` rooted such that Ni sits at
  moria 0. (If preset isn't rooted on Ni, pick the canonical root and
  offset so the canonical root sits at the nearest multiple of 72 below
  moria 0 — or just root at moria 0 and let the UI label accordingly.
  Decide early, test either way.)
- `moria_to_hz(moria)` free function + method.
- `cells()` materializes the cell list: degree cells from every region
  within `[low_moria, high_moria)`, plus 2-moria-step non-degree cells
  between them. Non-degree cells start `enabled = false`.
- `cells()` overlays any `overrides` entry onto matching cells.
- Tests:
  - Default Diatonic grid: 7 degree cells per octave over 3 octaves → 21
    degree cells in `[−108, 108)`.
  - Non-degree cell count matches (intervals filled at 2-moria step).
  - `cell_count_when_reference_changes` doesn't change; only `hz` does.

### 1.5 `EnharmonicGa` generator tiling

- Special-case `Region` positioning for `Genus::EnharmonicGa`:
  - Generator = `[6, 12, 12]`, tiled repeatedly from `start_moria`.
  - Stops when cumulative ≥ region span; the final segment is truncated.
- Test: generator tiling at `start_moria = 0` over a 72-moria span yields
  the positions expected in the reference doc §4.2.

### 1.6 Pthora application (region split)

- `Pthora { genus, target_degree }`.
- `TuningGrid::apply_pthora(moria: i32, pthora: Pthora)`:
  - Find the region containing `moria`. If `moria == region.start_moria`,
    mutate in place. Otherwise split: truncate the existing region at
    `moria`, insert a new region starting at `moria`.
  - New region's `end_moria` = original region's `end_moria` (or the next
    downstream region's `start_moria`).
  - Regions stay contiguous and sorted.
- `TuningGrid::remove_pthora(region_idx)`:
  - Merge with the preceding region, or with the following if preceding
    genus/root don't match. Document the merge heuristic in code.
- Tests:
  - Applying HardChromatic·Pa pthora at moria 42 on a Diatonic·Ni grid:
    cells at and above 42 follow HardChromatic intervals from Pa.
  - Two pthorae → three regions. Cells between boundaries follow the
    middle region's intervals.
  - Applying pthora at a non-degree moria (say 8 on a Diatonic grid):
    works; the new region's `start_moria` is 8.

### 1.7 Shading application

- `Shading` enum + `Shading::intervals()`.
- `TuningGrid::set_region_shading(region_idx, shading)`:
  - Stores on the region; when cells are derived, the first tetrachord's
    intervals are replaced with `shading.intervals()`.
- Tests:
  - Zygos on a Diatonic region starting with Ga at moria 30: the next
    three cells sit at 48, 52, 68 (then the rest of the scale continues
    from 72). Matches reference §5.1.
  - Removing shading restores original intervals.

### 1.8 Accidentals and cell overrides

- `CellOverride { accidental: i32, enabled: bool }`.
- `TuningGrid::set_accidental(moria, offset)` — validates `offset.abs() % 2
  == 0`. No upper bound.
- `TuningGrid::set_enabled(moria, bool)`.
- `Cell::effective_moria()` applies the override.
- Tests:
  - Setting `accidental = +10` on a cell shifts its `effective_moria` and
    its `moria_to_hz` accordingly. Larger-than-original bounds work.
  - `set_enabled(false)` on a degree cell: cell stays in the grid but
    `enabled == false`; cannot be triggered by keyboard or voice.

### 1.9 Serialization

- `serde` derives on `TuningGrid`, `Region`, `CellOverride`, `Genus`,
  `Pthora`, `Shading`.
- `TuningGrid::to_json()` / `from_json(s)` round-trip test.
- Custom genus intervals round-trip.

### 1.10 WASM main-thread bundle

- `src/lib.rs` under feature `main`:
  - `WasmGrid` wrapping `TuningGrid`.
  - Constructors: `new(preset_index, ref_ni_hz)`.
  - Mutators: `set_ref_ni_hz`, `set_preset`, `apply_pthora`, `remove_pthora`,
    `set_region_shading`, `set_accidental`, `toggle_enabled`.
  - Queries: `cell_count`, `cell(index)` returns a flat struct (moria,
    effective_moria, hz, degree_index, enabled, region_idx), `region_count`,
    `region(index)`.
  - `tuning_table()` → two `Float32Array`s `(cell_ids, periods_24_8_fixed)`
    for a given sample rate. This is what the worklets consume.
  - `serialize()` / `deserialize()` on JSON.
- Build: `wasm-pack build --target web --features main`.
- Verify in a scratch HTML page that a Diatonic preset yields the expected
  Hz values for Ni and Di.

---

## Phase 2 — Browser UI (no audio)

Everything user-facing except sound. Tests are manual, but keep the scale
engine wired through WASM (no redundant JS logic).

### 2.1 App shell

- `web/index.html` with a main grid: header · ladder · singscope · palettes
  · controls.
- `web/style.css` base.
- `web/app.js`: load WASM, construct a default `WasmGrid`, expose it on a
  global app state object.

### 2.2 ScaleLadder canvas

- `web/ui/scale_ladder.js`: Canvas element, paints cells top-to-bottom
  (high moria at top).
- Each cell row is tall enough to contain its label (degree cells ~24px,
  non-degree ~12px).
- Fill/outline based on `enabled`. Degree cells show martyria syllable +
  octave marker.
- Resize observer, re-render on window resize.

### 2.3 Click-to-toggle

- Canvas click → compute `cell_index` from y-coordinate → call
  `WasmGrid::toggle_enabled(moria)` → redraw.

### 2.4 Right-click accidental menu

- Position a small popup with ±2/4/6/8 buttons, a "custom" numeric input
  (even integers only), and a "clear" button.
- On select: `WasmGrid::set_accidental(moria, offset)`, redraw.
- Badge rendering on the cell.

### 2.5 Pthora palette

- `web/ui/pthora_palette.js`: panel of draggable icons. Data attribute
  carries `(genus_index, degree_index)`.
- Copy SVG/PNG pthora assets from
  `/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/` (find them
  under the resource directories, e.g. alongside `audio.qrc`).
- HTML5 drag-and-drop: dragstart sets `DataTransfer`; ladder dragover
  accepts; drop fires `WasmGrid::apply_pthora(moria, genus, degree)`.
- Visual: tint the affected region a unique color per pthora family.

### 2.6 Shading palette

- Same pattern, for the 4 shadings. Drop target = degree cells only
  (reject others on dragover).

### 2.7 Controls panel

- Preset selector: radio buttons for 6 canonical genera + "Custom".
- Base Ni frequency slider: 200–550 Hz, default 261.63.
- Viewport shift: up/down arrow buttons shifting `low_moria`/`high_moria`
  by one diatonic step.
- Reset button: clear all pthorae, overrides, shading.

### 2.8 Preset save/load UI

- Use `WasmGrid::serialize()` → LocalStorage under a user-chosen name.
- List + load + delete saved presets.

---

## Phase 3 — Synth and keyboard (audio begins here)

### 3.1 SynthWorklet scaffold

- `web/audio/synth_worklet.js`: `AudioWorkletProcessor` subclass. Accepts
  messages: `{type: "noteOn", cell_id, velocity}`, `{type: "noteOff",
  cell_id}`, `{type: "tuning_table", cell_ids, periods}`.
- Main thread creates the `AudioContext` on user gesture (first click),
  loads the worklet module, wires it to `destination`.
- At initialization, main thread posts the current tuning table.

### 3.2 Additive organ voice

- `core/synth/additive.rs` (Rust): `Voice { phase, freq, env, harmonics }`.
  Renders into a buffer.
- Expose via worklet WASM bundle (`worklet` feature) — or prototype in JS
  first, port to Rust once correct. Recommend JS prototype → Rust port:
  faster iteration on timbre.
- `K = 8` harmonics, `alpha = 1.2`. Envelope: 5 ms attack, sustain,
  80 ms release.
- Max 16 voices, round-robin allocation with release-first stealing.

### 3.3 Keyboard routing

- `web/ui/vkeyboard.js`: listen for `keydown`/`keyup` on window.
- Configurable map (default: QWERTY home row → diatonic degrees, upper row
  → non-degree cells). User-editable in v2.
- Key press → `synthWorklet.port.postMessage({type: "noteOn", cell_id,
  velocity})`. Ladder lights the active cell.

### 3.4 Ison drone

- Separate control cluster: degree + octave + volume.
- Implemented as a persistent voice in the synth worklet tagged `ison`,
  with slightly tweaked harmonic weighting.
- User toggle, volume slider.

---

## Phase 4 — Voice pipeline DSP

The meat of the port. Each task touches the C++ source directly; reference
line numbers in commit messages.

### 4.1 Worklet WASM bundle

- `src/worklet.rs` with `#[wasm_bindgen]` exports for just the DSP
  primitives.
- Build script produces both bundles in one invocation.
- Main thread fetches the worklet `.wasm` as `ArrayBuffer` and posts to
  the worklet at init; worklet instantiates.

### 4.2 Mic wiring

- `web/audio/voice_worklet.js` scaffold.
- Main thread: `navigator.mediaDevices.getUserMedia({audio: true})` on user
  gesture, wrap in `MediaStreamSource`, connect to `VoiceWorklet`.
- `VoiceWorklet` just buffers for now and posts RMS to main thread. Verify
  signal flow.

### 4.3 Filters

- `core/dsp/filters.rs`: biquad HPF (2nd order, cascaded ×2). Coefficients
  from `vocproc.cpp:665-666`.
- `NotchFilter` port of `vocproc.h:23-46`. `setPeriod`, `setAmp`, `doSample`.
- Unit tests: step response / sine passthrough at 500 Hz; HPF should
  attenuate a 30 Hz tone by ≥40 dB.

### 4.4 Envelope + hysteretic gate

- `core/dsp/gate.rs`: rolling `loAmp`/`hiAmp` per 512-sample block,
  EMA-smoothed to `currentAmp`. Asymmetric thresholds:
  `gate_off_amp = gate_on_amp * 15/16`.
- Emits `gate_open: bool` and `level_db: i32`.
- Tests: synthetic envelope (ramp up → hold → ramp down) triggers open at
  `gate_on_amp` and close at the lower threshold.

### 4.5 Time-domain detector (warm-up path)

- `core/dsp/detector.rs`: `TimeDomainDetector` per
  `vocproc.cpp:846-879, 1131-1176`.
- Peak-state machine, log-histogram keyed to enabled cells, decay per
  2048-sample block.
- Test: synthetic sine at 440 Hz for 4096 samples → detected period
  within 1% of `sample_rate / 440`.

### 4.6 FFT detector (default path)

Break into sub-tasks; each lands in its own commit with a dedicated test:

- 4.6.a FFT setup via `realfft`: 2560-point forward + inverse plans,
  Hann window.
- 4.6.b `calcSpectrum`: last 2560 samples → windowed → FFT → `|X|²` →
  `sqrt` → inverse DCT via `realfft` (or `rustfft` with symmetry).
- 4.6.c `fft_corr` window-bias precomputation at init; divide per-lag on
  every detection. Test: running the pipeline on silence (tiny noise)
  produces no systematic peak at low lags.
- 4.6.d Alias suppression at `k ∈ {2, 3, 5, 7}`, iterating `i` downward.
  Test: synthetic 220 Hz + 440 Hz harmonic stack detects 220, not 440.
- 4.6.e Log-bin EMA + neighbor spreading (`*= 0.75`, `1/1.1^k²`). Test:
  constant pitch gains over 10 cycles; transient noise does not.
- 4.6.f Confidence gates (`global_peak > 0.03`, adaptive `second/global`).
  Test: white noise input → no detections emitted.
- 4.6.g Parabolic LSQ sub-sample interpolation. Test: synthetic pitch at
  exactly between two bins resolves to within 0.1 bin.

### 4.7 Nearest-cell snap

- `core/tuning/grid.rs`: `nearest_enabled_cell(period, last_cell_id) ->
  (primary, neighbor, neighbor_velocity)`.
- Build a sorted `(period, cell_id)` index from the tuning table; update
  on every tuning-table push.
- `lastKey` hysteresis: halve distance to `last_cell_id`.
- Test: given three enabled cells at periods 100, 120, 150, input period
  110 snaps to 100 if `last = 100` (because of hysteresis), else to 120.

### 4.8 Pitch events to main thread

- Throttle to ~60 Hz with a sample counter.
- Event: `{type: "pitch", moria, confidence, gate_open, neighbor_moria,
  neighbor_velocity}`.
- Main thread updates ladder highlight on receipt.

---

## Phase 5 — Singscope

### 5.1 Canvas scaffold

- `web/ui/singscope.js`: canvas positioned immediately right of the
  scale ladder, sharing Y-coordinate mapping.
- Horizontal scroll buffer (circular).

### 5.2 Pitch polyline

- On pitch event: append `(timestamp, moria, confidence)`.
- RequestAnimationFrame loop: scroll buffer, draw polyline. Color
  interpolates with confidence.
- Gate-closed samples render as breaks.

### 5.3 Cell background bands

- Faint tint on rows corresponding to enabled cells. Updated when ladder
  changes.

### 5.4 Snap polyline (prepared for Phase 6)

- Even before PSOLA lands, we can overlay the nearest-cell snap target
  from Phase 4.7 events. Visualizes what correction would do.

---

## Phase 6 — PSOLA pitch correction

### 6.1 RepitchPSOLA port

- `core/dsp/psola.rs`: port of `RepitchPSOLA::convertSamples`
  (`repitcher.cpp`). Per-epoch overlap-add, cross-fade between source
  periods and target periods.
- Consumes the comb-filtered voice buffer from `VoiceWorklet`.
- Output: buffer of shifted samples at `target_period`.

### 6.2 Routing corrected audio

- `VoiceWorklet` outputs corrected audio on a separate `AudioNode` output
  channel (WebAudio worklets support multi-output).
- Connect to `SynthWorklet` as an input channel, mixed with the organ.

### 6.3 Controls

- Correction enable/disable toggle.
- Portamento slider (slews `target_period`).
- Voice monitoring dry/wet slider.

---

## Phase 7 — Polish

- Responsive layout, mobile-friendly (pthora palette collapses to a menu
  on narrow screens).
- Dark theme default; light theme option.
- Keyboard shortcuts list in a help overlay.
- Build script: `./build.sh` → `wasm-pack build` both bundles, copy into
  `web/dist/`, produce a deployable static bundle.
- Deploy notes in `README.md`.

---

## Testing strategy

- **Rust unit/property tests** run on every commit.
- **Rust DSP tests** against synthetic signals (see Phase 4 sub-tests).
- **WASM smoke test**: a scratch HTML page loaded headlessly verifies the
  grid constructs and exports a tuning table.
- **Manual perceptual checklist** for phases 2, 3, 5, 6.

## Phase ordering notes

- Phases 1 and 2 can overlap once `WasmGrid` basics exist.
- Phase 3 can start as soon as 1.10 lands.
- Phase 4 depends on nothing in 2/3 except the WASM bundle infrastructure
  from 1.10.
- Phase 5 depends on 4.7/4.8 (pitch events) but can be scaffolded earlier
  against fake events.
- Phase 6 depends on 4 + 3 (needs voice pipeline output + synth to mix in).
