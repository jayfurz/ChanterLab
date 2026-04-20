# Byzorgan Web App — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Rewrite the Byzantine Organ as a browser-based web app with a Rust/WASM core (tuning + pitch detection) and a WebAudio + Canvas/JS frontend.

**Architecture:** Rust crate compiled to WASM via wasm-pack, exposing a flat C-style API over wasm-bindgen. Browser loads the WASM module, calls it for all tuning/pitch computation, and uses native WebAudio for sound generation. No server needed — 100% client-side.

**Tech Stack:** Rust + wasm-bindgen + wasm-pack + rustfft | HTML/Canvas/JS + WebAudio API + AudioWorklet

**Reference:** `docs/BYZANTINE_SCALES_REFERENCE.md` — the authoritative source for all scale intervals, shadings, and pthora definitions. Consult it for every tuning-related task.

---

## Key Design Decisions

1. **72-moria base system** — all tuning expressed as moria positions. No hardcoded per-mode tables.
2. **Six scales**: Diatonic, Hard Chromatic, Soft Chromatic, Grave Diatonic, Enharmonic Zo, Enharmonic Ga
3. **Four shadings**: Zygos, Kliton, Spathi A, Spathi B — local tetrachord replacements
4. **Pthora** = drag-drop modulation sign. Pivots a pitch to a different degree/genus, recalculating surrounding intervals.
5. **Accidentals** = fixed ±2/4/6/8 moria offsets on individual cells
6. **Ison** = drone note, manual selection only. NOT voice-driven.
7. **Melos** = melody line. Voice pitch detection drives the melos, NOT the ison.
8. **3-octave internal range** (216 moria). Ni at index 30. Display from low Di to high Di, adjustable with arrow buttons that shift the viewport diatonically.
9. **Degree order**: Ni(0) Pa(1) Vou(2) Ga(3) Di(4) Ke(5) Zo(6)
10. **Interval rotation**: all scales are 7-element interval arrays. Rotate to start from any degree.

---

## Project Structure

```
byzorgan-web/
├── PLAN.md                          # this file
├── Cargo.toml
├── src/
│   └── lib.rs                       # WASM entry, wasm_bindgen exports
├── core/
│   ├── mod.rs
│   ├── degrees.rs                   # Degree enum, names, rotation helpers
│   ├── scales.rs                    # ScaleType, SCALE_INTERVALS, positions()
│   ├── tuning_engine.rs             # TuningEngine: moria_to_hz, build_cells, viewport
│   ├── cell.rs                      # Cell struct, Accidental, Pthora, Shading
│   ├── pthora.rs                    # Pthora application + region recomputation
│   ├── shading.rs                   # Shading application + interval replacement
│   ├── pitch_detector.rs            # PitchDetector using rustfft
│   ├── synth.rs                     # SynthEngine, Voice, IsonState, MelosState
│   └── constants.rs                 # MORIA_PER_OCTAVE, TOTAL_OCTAVES, etc.
├── web/
│   ├── index.html
│   ├── style.css
│   ├── app.js                       # Main app, WASM init, event wiring
│   ├── scale_ladder.js              # Canvas rendering, cell interactions
│   ├── pthora_palette.js            # Drag source for pthora
│   ├── vkeyboard.js                 # Computer keyboard → moria mapping
│   ├── ison_control.js              # Ison degree/octave/volume
│   ├── melos_control.js             # Melos voice input + synth
│   ├── synth_worklet.js             # AudioWorklet for organ sound
│   ├── pitch_worklet.js             # AudioWorklet for voice input
│   └── assets/
│       └── pthora/                  # SVG/PNG symbols from existing repo
├── docs/
│   └── BYZANTINE_SCALES_REFERENCE.md
└── tests/
    ├── degrees_test.rs
    ├── scales_test.rs
    ├── tuning_engine_test.rs
    ├── pthora_test.rs
    ├── shading_test.rs
    ├── pitch_detector_test.rs
    └── integration_test.rs
```

---

## Phase 1 — Rust Core: Degrees, Scales, Tuning Engine

### Task 1.1: Initialize Rust project and git repo

**Objective:** Set up the project skeleton with Cargo.toml, directory structure, and git.

**Files:**
- Create: `byzorgan-web/Cargo.toml`
- Create: `byzorgan-web/src/lib.rs`
- Create: `byzorgan-web/core/mod.rs`

**Step 1: Create project directory and Cargo.toml**

```toml
[package]
name = "byzorgan-core"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
wasm-bindgen = "0.2"

[dependencies.rustfft]
version = "6.2"

[dev-dependencies]
approx = "0.5"

[profile.release]
opt-level = "z"
lto = true
```

**Step 2: Create minimal src/lib.rs**

```rust
pub mod core;

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(2 + 2, 4);
    }
}
```

**Step 3: Create core/mod.rs**

```rust
pub mod constants;
pub mod degrees;
pub mod scales;
```

**Step 4: Create core/constants.rs**

```rust
/// Moria per octave in Byzantine theory
pub const MORIA_PER_OCTAVE: i32 = 72;

/// Total internal range in octaves
pub const TOTAL_OCTAVES: i32 = 3;

/// Total moria span (3 octaves)
pub const TOTAL_MORIA: i32 = MORIA_PER_OCTAVE * TOTAL_OCTAVES; // 216

/// Index offset where Ni sits in the cell array.
/// Di is 30 moria below Ni, so Ni = index 30 in a 0-based array
/// where index 0 = low Di.
pub const NI_BASE_INDEX: i32 = 30;

/// Number of scale degrees
pub const NUM_DEGREES: usize = 7;

/// Base frequency for A4 (Ke at octave 0 when tuned to A=440)
pub const A4_HZ: f64 = 440.0;
```

**Step 5: Initialize git and commit**

```bash
cd /mnt/data/code/byzorgan-web
git init
git add -A
git commit -m "init: project skeleton with Cargo.toml and directory structure"
```

**Step 6: Verify build**

```bash
cd /mnt/data/code/byzorgan-web
cargo build
cargo test
```

Expected: build succeeds, 1 test passes.

---

### Task 1.2: Implement Degree enum with names and rotation

**Objective:** Define the 7 Byzantine degrees with their names and provide a rotation helper.

**Files:**
- Create: `core/degrees.rs`
- Create: `tests/degrees_test.rs`

**Step 1: Write failing test**

```rust
// tests/degrees_test.rs
use byzorgan_core::core::degrees::*;

#[test]
fn degree_names() {
    assert_eq!(Degree::Ni.name(), "Ni");
    assert_eq!(Degree::Pa.name(), "Pa");
    assert_eq!(Degree::Vou.name(), "Vou");
    assert_eq!(Degree::Ga.name(), "Ga");
    assert_eq!(Degree::Di.name(), "Di");
    assert_eq!(Degree::Ke.name(), "Ke");
    assert_eq!(Degree::Zo.name(), "Zo");
}

#[test]
fn degree_index_roundtrip() {
    for i in 0..7 {
        let d = Degree::from_index(i);
        assert_eq!(d as usize, i);
    }
}

#[test]
fn degree_next_prev() {
    assert_eq!(Degree::Ni.next(), Degree::Pa);
    assert_eq!(Degree::Zo.next(), Degree::Ni); // wraps
    assert_eq!(Degree::Pa.prev(), Degree::Ni);
    assert_eq!(Degree::Ni.prev(), Degree::Zo); // wraps
}

#[test]
fn rotate_intervals_forward() {
    let intervals = [12, 10, 8, 12, 12, 10, 8];
    let rotated = rotate_intervals(&intervals, Degree::Pa);
    assert_eq!(rotated, [10, 8, 12, 12, 10, 8, 12]);
}

#[test]
fn rotate_intervals_zero_is_identity() {
    let intervals = [12, 10, 8, 12, 12, 10, 8];
    let rotated = rotate_intervals(&intervals, Degree::Ni);
    assert_eq!(rotated, intervals);
}
```

**Step 2: Run test to verify failure**

```bash
cargo test --test degrees_test
```

Expected: FAIL — module not found.

**Step 3: Implement degrees.rs**

```rust
// core/degrees.rs
use crate::core::constants::NUM_DEGREES;

/// The 7 ascending degrees of the Byzantine scale
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(usize)]
pub enum Degree {
    Ni = 0,
    Pa = 1,
    Vou = 2,
    Ga = 3,
    Di = 4,
    Ke = 5,
    Zo = 6,
}

impl Degree {
    pub fn name(&self) -> &'static str {
        match self {
            Degree::Ni  => "Ni",
            Degree::Pa  => "Pa",
            Degree::Vou => "Vou",
            Degree::Ga  => "Ga",
            Degree::Di  => "Di",
            Degree::Ke  => "Ke",
            Degree::Zo  => "Zo",
        }
    }

    pub fn from_index(i: usize) -> Degree {
        match i % NUM_DEGREES {
            0 => Degree::Ni,
            1 => Degree::Pa,
            2 => Degree::Vou,
            3 => Degree::Ga,
            4 => Degree::Di,
            5 => Degree::Ke,
            6 => Degree::Zo,
            _ => unreachable!(),
        }
    }

    /// Next degree upward (wraps Ni→Ni)
    pub fn next(&self) -> Degree {
        Degree::from_index((*self as usize + 1) % NUM_DEGREES)
    }

    /// Previous degree downward (wraps Ni→Zo)
    pub fn prev(&self) -> Degree {
        Degree::from_index((*self as usize + NUM_DEGREES - 1) % NUM_DEGREES)
    }
}

/// Rotate a 7-element interval array to start from a given degree.
/// Degree::Ni = no rotation, Degree::Pa = rotate left by 1, etc.
pub fn rotate_intervals(intervals: &[i32; 7], start: Degree) -> [i32; 7] {
    let r = start as usize;
    let mut result = [0i32; 7];
    for i in 0..7 {
        result[i] = intervals[(i + r) % 7];
    }
    result
}
```

**Step 4: Update core/mod.rs to include degrees**

Already done in Task 1.1 if mod.rs declares `pub mod degrees;`.

**Step 5: Run tests to verify pass**

```bash
cargo test --test degrees_test
```

Expected: 4 tests pass.

**Step 6: Commit**

```bash
git add core/degrees.rs tests/degrees_test.rs
git commit -m "feat: Degree enum with names, rotation, next/prev"
```

---

### Task 1.3: Implement ScaleType with interval arrays and position computation

**Objective:** Define the six principal scales with their canonical interval sequences and root degrees, and compute cumulative moria positions.

**Files:**
- Create: `core/scales.rs`
- Create: `tests/scales_test.rs`

**Step 1: Write failing test**

```rust
// tests/scales_test.rs
use byzorgan_core::core::scales::*;
use byzorgan_core::core::degrees::*;

#[test]
fn diatonic_positions_from_ni() {
    let pos = ScaleType::Diatonic.positions(Degree::Ni);
    assert_eq!(pos, [0, 12, 22, 30, 42, 54, 64, 72]);
}

#[test]
fn hard_chromatic_positions_from_pa() {
    let pos = ScaleType::HardChromatic.positions(Degree::Pa);
    assert_eq!(pos, [0, 6, 26, 30, 42, 48, 68, 72]);
}

#[test]
fn soft_chromatic_positions_from_ni() {
    let pos = ScaleType::SoftChromatic.positions(Degree::Ni);
    assert_eq!(pos, [0, 8, 22, 30, 42, 50, 64, 72]);
}

#[test]
fn grave_diatonic_positions_from_ni() {
    let pos = ScaleType::GraveDiatonic.positions(Degree::Ni);
    assert_eq!(pos, [0, 6, 22, 30, 42, 52, 64, 72]);
}

#[test]
fn enharmonic_zo_positions_from_zo() {
    let pos = ScaleType::EnharmonicZo.positions(Degree::Zo);
    assert_eq!(pos, [0, 6, 18, 30, 42, 48, 60, 72]);
}

#[test]
fn diatonic_intervals_from_ke() {
    // Ke rotation: [10, 8, 12, 12, 10, 8, 12] → 36-ET: [5,4,6,6,5,4,6]
    let pos = ScaleType::Diatonic.positions(Degree::Ke);
    // Cumulative from Ke: 0, 10, 18, 30, 42, 52, 60, 72
    assert_eq!(pos, [0, 10, 18, 30, 42, 52, 60, 72]);
}

#[test]
fn all_scales_sum_to_72() {
    for scale in ScaleType::all() {
        let intervals = scale.intervals();
        let sum: i32 = intervals.iter().sum();
        assert_eq!(sum, 72, "{:?} intervals sum to {}, expected 72", scale, sum);
    }
}

#[test]
fn all_rotations_sum_to_72() {
    for scale in ScaleType::all() {
        for degree_idx in 0..7 {
            let degree = Degree::from_index(degree_idx);
            let pos = scale.positions(degree);
            assert_eq!(pos[7], 72,
                "{:?} from {:?}: octave position is {}, expected 72",
                scale, degree, pos[7]);
        }
    }
}

#[test]
fn scale_root_degrees() {
    assert_eq!(ScaleType::Diatonic.root(), Degree::Ni);
    assert_eq!(ScaleType::HardChromatic.root(), Degree::Pa);
    assert_eq!(ScaleType::SoftChromatic.root(), Degree::Ni);
    assert_eq!(ScaleType::GraveDiatonic.root(), Degree::Ga);
    assert_eq!(ScaleType::EnharmonicZo.root(), Degree::Zo);
    assert_eq!(ScaleType::EnharmonicGa.root(), Degree::Ga);
}
```

**Step 2: Run test to verify failure**

```bash
cargo test --test scales_test
```

Expected: FAIL — module not found.

**Step 3: Implement scales.rs**

```rust
// core/scales.rs
use crate::core::degrees::{Degree, rotate_intervals};
use crate::core::constants::NUM_DEGREES;

/// The six principal Byzantine scales
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ScaleType {
    Diatonic,       // Ni
    HardChromatic,  // Pa
    SoftChromatic,  // Ni
    GraveDiatonic,  // Ga
    EnharmonicZo,   // Zo
    EnharmonicGa,   // Ga (tetrachord generator, closed form)
}

/// Canonical interval sequences for each scale (step sizes in moria)
/// See BYZANTINE_SCALES_REFERENCE.md sections 3-4
const SCALE_INTERVALS: [[i32; 7]; 6] = [
    [12, 10,  8, 12, 12, 10,  8],  // Diatonic
    [ 6, 20,  4, 12,  6, 20,  4],  // Hard Chromatic
    [ 8, 14,  8, 12,  8, 14,  8],  // Soft Chromatic
    [ 6, 16,  8, 12, 10, 12,  8],  // Grave Diatonic
    [ 6, 12, 12, 12,  6, 12, 12],  // Enharmonic Zo
    [ 6, 12, 12,  6, 12, 12,  6],  // Enharmonic Ga (closed)
];

/// Root degree for each scale
const SCALE_ROOTS: [Degree; 6] = [
    Degree::Ni,
    Degree::Pa,
    Degree::Ni,
    Degree::Ga,
    Degree::Zo,
    Degree::Ga,
];

impl ScaleType {
    /// All scale types, in enum order
    pub fn all() -> [ScaleType; 6] {
        [
            ScaleType::Diatonic,
            ScaleType::HardChromatic,
            ScaleType::SoftChromatic,
            ScaleType::GraveDiatonic,
            ScaleType::EnharmonicZo,
            ScaleType::EnharmonicGa,
        ]
    }

    /// The canonical root degree for this scale
    pub fn root(&self) -> Degree {
        SCALE_ROOTS[*self as usize]
    }

    /// The interval sequence as defined from the canonical root
    pub fn intervals(&self) -> [i32; 7] {
        SCALE_INTERVALS[*self as usize]
    }

    /// Compute cumulative moria positions for this scale rooted on a given degree.
    /// Returns 8 values: position[0]=0, position[7]=72 (octave).
    pub fn positions(&self, root: Degree) -> [i32; 8] {
        let rotated = rotate_intervals(&self.intervals(), root);
        let mut positions = [0i32; 8];
        for i in 1..=NUM_DEGREES {
            positions[i] = positions[i - 1] + rotated[i - 1];
        }
        positions
    }

    /// Name of this scale for display
    pub fn name(&self) -> &'static str {
        match self {
            ScaleType::Diatonic       => "Diatonic",
            ScaleType::HardChromatic  => "Hard Chromatic",
            ScaleType::SoftChromatic  => "Soft Chromatic",
            ScaleType::GraveDiatonic  => "Grave Diatonic",
            ScaleType::EnharmonicZo   => "Enharmonic (Zo)",
            ScaleType::EnharmonicGa   => "Enharmonic (Ga)",
        }
    }
}
```

**Step 4: Update core/mod.rs**

```rust
pub mod constants;
pub mod degrees;
pub mod scales;
```

**Step 5: Run tests**

```bash
cargo test --test scales_test
```

Expected: 8 tests pass.

**Step 6: Commit**

```bash
git add core/scales.rs tests/scales_test.rs
git commit -m "feat: ScaleType with 6 scales, interval rotation, position computation"
```

---

### Task 1.4: Implement Cell struct and Accidental/Pthora/Shading types

**Objective:** Define the data types that represent individual notes on the ScaleLadder.

**Files:**
- Create: `core/cell.rs`
- Test: inline unit tests in cell.rs

**Step 1: Implement cell.rs**

```rust
// core/cell.rs
use crate::core::degrees::Degree;
use crate::core::scales::ScaleType;

/// Fixed accidental alteration in moria
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Accidental {
    pub moria: i8,  // ±2, ±4, ±6, ±8
}

impl Accidental {
    pub fn sharp(moria: u8) -> Option<Accidental> {
        match moria {
            2 | 4 | 6 | 8 => Some(Accidental { moria: moria as i8 }),
            _ => None,
        }
    }

    pub fn flat(moria: u8) -> Option<Accidental> {
        match moria {
            2 | 4 | 6 | 8 => Some(Accidental { moria: -(moria as i8) }),
            _ => None,
        }
    }
}

/// Tetrachord shadings (χρόαι / Chroai)
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Shading {
    None,
    Zygos,     // 18·4·16·4 on Ga
    Kliton,    // 20·4·4·14 on Ga
    SpathiA,   // 14·12·4 on Ga
    SpathiB,   // 14·4·4·20 on Ga
}

impl Shading {
    /// All available shadings
    pub fn all() -> [Shading; 4] {
        [Shading::Zygos, Shading::Kliton, Shading::SpathiA, Shading::SpathiB]
    }

    /// Display name
    pub fn name(&self) -> &'static str {
        match self {
            Shading::None   => "None",
            Shading::Zygos  => "Zygos",
            Shading::Kliton => "Kliton",
            Shading::SpathiA => "Spathi A",
            Shading::SpathiB => "Spathi B",
        }
    }

    /// The shading's interval replacement sequence
    pub fn intervals(&self) -> &'static [i32] {
        match self {
            Shading::None   => &[],
            Shading::Zygos  => &[18, 4, 16, 4],
            Shading::Kliton => &[20, 4, 4, 14],
            Shading::SpathiA => &[14, 12, 4],
            Shading::SpathiB => &[14, 4, 4, 20],
        }
    }
}

/// A pthora: modulation that reassigns the current pitch as a
/// different degree of a different genus
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pthora {
    pub target_genus: ScaleType,
    pub target_degree: Degree,
}

impl Pthora {
    pub fn new(genus: ScaleType, degree: Degree) -> Pthora {
        Pthora {
            target_genus: genus,
            target_degree: degree,
        }
    }
}

/// One cell in the ScaleLadder — the fundamental display/playback unit
#[derive(Clone, Debug)]
pub struct Cell {
    /// Absolute moria position from the Ni base
    pub moria_from_ni: i32,
    /// Which degree this cell represents (after any pthora/shading)
    pub degree: Degree,
    /// Optional fixed accidental offset
    pub accidental: Option<Accidental>,
    /// Optional pthora modulation applied at this cell
    pub pthora: Option<Pthora>,
    /// Optional tetrachord shading applied starting at this cell
    pub shading: Shading,
    /// Whether this note is playable
    pub enabled: bool,
    /// Whether this is a diatonic degree position (taller on display)
    pub is_degree: bool,
}

impl Cell {
    pub fn new(moria: i32, degree: Degree) -> Cell {
        Cell {
            moria_from_ni: moria,
            degree,
            accidental: None,
            pthora: None,
            shading: Shading::None,
            enabled: true,
            is_degree: true,
        }
    }

    /// Effective moria position including accidental
    pub fn effective_moria(&self) -> i32 {
        let offset = self.accidental.map(|a| a.moria as i32).unwrap_or(0);
        self.moria_from_ni + offset
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accidental_sharp_flat() {
        assert_eq!(Accidental::sharp(4), Some(Accidental { moria: 4 }));
        assert_eq!(Accidental::flat(6), Some(Accidental { moria: -6 }));
        assert_eq!(Accidental::sharp(3), None); // invalid
    }

    #[test]
    fn cell_effective_moria_with_accidental() {
        let mut cell = Cell::new(12, Degree::Pa);
        assert_eq!(cell.effective_moria(), 12);
        cell.accidental = Some(Accidental { moria: -4 });
        assert_eq!(cell.effective_moria(), 8);
    }

    #[test]
    fn shading_intervals() {
        assert_eq!(Shading::Zygos.intervals(), &[18, 4, 16, 4]);
        assert_eq!(Shading::SpathiA.intervals(), &[14, 12, 4]);
    }
}
```

**Step 2: Update core/mod.rs**

```rust
pub mod constants;
pub mod degrees;
pub mod scales;
pub mod cell;
```

**Step 3: Run tests**

```bash
cargo test
```

Expected: all previous tests + 3 new cell tests pass.

**Step 4: Commit**

```bash
git add core/cell.rs
git commit -m "feat: Cell, Accidental, Shading, Pthora data types"
```

---

### Task 1.5: Implement TuningEngine — moria_to_hz, build_cells, viewport

**Objective:** The central engine that holds scale state, computes cell arrays, and converts moria to frequency.

**Files:**
- Create: `core/tuning_engine.rs`
- Create: `tests/tuning_engine_test.rs`

**Step 1: Write failing test**

```rust
// tests/tuning_engine_test.rs
use byzorgan_core::core::tuning_engine::*;
use byzorgan_core::core::degrees::Degree;
use byzorgan_core::core::scales::ScaleType;
use byzorgan_core::core::constants::{MORIA_PER_OCTAVE, TOTAL_MORIA, NI_BASE_INDEX};

#[test]
fn moria_to_hz_unison() {
    // Ni at A=440: Ke=A, Ni=C below. Ni = 440 * 2^(-9/12)
    // But our convention: Ni is the base, we set it explicitly
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic); // Ni ≈ C4
    // moria 0 = Ni = base pitch
    let diff = (engine.moria_to_hz(0) - 261.63).abs();
    assert!(diff < 0.01, "moria 0 should equal base pitch");
}

#[test]
fn moria_to_hz_octave() {
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let diff = (engine.moria_to_hz(72) - 261.63 * 2.0).abs();
    assert!(diff < 0.1, "72 moria should be one octave up");
}

#[test]
fn moria_to_hz_negative() {
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let diff = (engine.moria_to_hz(-72) - 261.63 / 2.0).abs();
    assert!(diff < 0.1, "-72 moria should be one octave down");
}

#[test]
fn build_cells_diatonic_count() {
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let cells = engine.cells();
    // Should have cells covering the full 3-octave range
    assert!(cells.len() > 0);
    // First cell should be at low Di (Ni - 30 moria)
    assert_eq!(cells[0].moria_from_ni, -30);
}

#[test]
fn build_cells_diatonic_degree_positions() {
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let cells = engine.cells();
    // Find the Ni cell (should be at moria 0)
    let ni_cells: Vec<_> = cells.iter().filter(|c| c.degree == Degree::Ni && c.is_degree).collect();
    assert!(ni_cells.len() >= 2, "should have at least 2 Ni cells in 3 octaves");
    // First Ni should be at moria 0
    assert_eq!(ni_cells[0].moria_from_ni, 0);
}

#[test]
fn viewport_default() {
    let engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let (start, end) = engine.viewport();
    // Default viewport: low Di (moria -30) to high Di (moria 186)
    assert_eq!(start, -30);
    assert!(end >= 186);
}

#[test]
fn set_scale_changes_cells() {
    let mut engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    let diatonic_cells = engine.cells().to_vec();
    engine.set_scale(ScaleType::HardChromatic);
    let chromatic_cells = engine.cells().to_vec();
    // Different scales should produce different cell positions
    assert_ne!(diatonic_cells, chromatic_cells);
}
```

**Step 2: Run test to verify failure**

```bash
cargo test --test tuning_engine_test
```

**Step 3: Implement tuning_engine.rs**

```rust
// core/tuning_engine.rs
use crate::core::cell::Cell;
use crate::core::constants::{MORIA_PER_OCTAVE, TOTAL_MORIA, NI_BASE_INDEX, NUM_DEGREES};
use crate::core::degrees::Degree;
use crate::core::scales::ScaleType;

/// The central tuning engine. Holds scale state and computes cell arrays.
pub struct TuningEngine {
    /// Frequency of the base Ni in Hz
    base_pitch_hz: f64,
    /// Current scale type
    scale: ScaleType,
    /// The 3-octave cell array
    cells: Vec<Cell>,
    /// Viewport start in moria (relative to Ni)
    viewport_start: i32,
    /// Viewport end in moria (relative to Ni)
    viewport_end: i32,
}

impl TuningEngine {
    pub fn new(base_pitch_hz: f64, scale: ScaleType) -> TuningEngine {
        let mut engine = TuningEngine {
            base_pitch_hz,
            scale,
            cells: Vec::new(),
            viewport_start: -30,  // low Di
            viewport_end: 186,    // high Di
        };
        engine.rebuild_cells();
        engine
    }

    /// Convert moria offset from Ni to frequency in Hz
    pub fn moria_to_hz(&self, moria: i32) -> f64 {
        self.base_pitch_hz * 2.0_f64.powf(moria as f64 / MORIA_PER_OCTAVE as f64)
    }

    /// Get the current cell array
    pub fn cells(&self) -> &[Cell] {
        &self.cells
    }

    /// Get the current viewport (start_moria, end_moria) relative to Ni
    pub fn viewport(&self) -> (i32, i32) {
        (self.viewport_start, self.viewport_end)
    }

    /// Set the scale and rebuild cells
    pub fn set_scale(&mut self, scale: ScaleType) {
        self.scale = scale;
        self.rebuild_cells();
    }

    /// Get the current scale type
    pub fn scale(&self) -> ScaleType {
        self.scale
    }

    /// Set the base pitch frequency (Ni)
    pub fn set_base_pitch(&mut self, hz: f64) {
        self.base_pitch_hz = hz;
    }

    /// Get the base pitch frequency
    pub fn base_pitch(&self) -> f64 {
        self.base_pitch_hz
    }

    /// Shift viewport down by one diatonic degree
    pub fn shift_viewport_down(&mut self) {
        let interval = self.interval_at_moria(self.viewport_start, going_up: false);
        self.viewport_start -= interval;
        self.viewport_end -= interval;
    }

    /// Shift viewport up by one diatonic degree
    pub fn shift_viewport_up(&mut self) {
        let interval = self.interval_at_moria(self.viewport_start, going_up: true);
        self.viewport_start += interval;
        self.viewport_end += interval;
    }

    /// Rebuild the full 3-octave cell array from current scale
    fn rebuild_cells(&mut self) {
        self.cells.clear();

        // Build cells for each octave
        for octave in -1..=1 {
            let base_moria = octave * MORIA_PER_OCTAVE;
            let positions = self.scale.positions(Degree::Ni);

            // Add degree cells (7 per octave)
            for (i, &pos) in positions.iter().enumerate() {
                if i == NUM_DEGREES { break; } // skip the octave repeat
                let moria = base_moria + pos;
                let degree = Degree::from_index(i);
                let mut cell = Cell::new(moria, degree);
                cell.is_degree = true;
                self.cells.push(cell);
            }

            // Add non-degree cells between each pair of degrees
            // These represent the 72 moria positions that are NOT degree positions
            // We'll add cells at 2-moria granularity for the accidentals
            for i in 0..NUM_DEGREES {
                let start_moria = base_moria + positions[i];
                let end_moria = base_moria + positions[i + 1];
                let interval = end_moria - start_moria;

                // Add intermediate cells at 2-moria steps
                // Skip moria positions that are exactly on a degree
                let mut m = start_moria + 2;
                while m < end_moria {
                    let mut cell = Cell::new(m, Degree::from_index(i));
                    cell.is_degree = false;
                    cell.enabled = false; // non-degree cells disabled by default
                    self.cells.push(cell);
                    m += 2;
                }
            }
        }

        // Sort by moria position
        self.cells.sort_by_key(|c| c.moria_from_ni);

        // Add the low Di cell (30 moria below Ni)
        // Ni is at moria 0. Going down: Zo=-8, Ke=-18, Di=-30
        // This is already handled by the octave=-1 loop since
        // positions from Ni include Ni at 0, and Di at 42.
        // octave=-1: base_moria=-72, Di at -72+42 = -30. Correct!
    }

    /// Get the interval at a given moria position going up or down
    fn interval_at_moria(&self, moria: i32, going_up: bool) -> i32 {
        let positions = self.scale.positions(Degree::Ni);
        // Normalize moria to within one octave
        let normalized = ((moria % MORIA_PER_OCTAVE) + MORIA_PER_OCTAVE) % MORIA_PER_OCTAVE;

        // Find which degree position we're at or near
        for i in 0..NUM_DEGREES {
            if positions[i] == normalized {
                if going_up {
                    return positions[i + 1] - positions[i];
                } else {
                    return positions[i] - positions[i.saturating_sub(1)];
                }
            }
        }
        // Default: whole tone
        12
    }
}
```

**Step 4: Update core/mod.rs**

```rust
pub mod constants;
pub mod degrees;
pub mod scales;
pub mod cell;
pub mod tuning_engine;
```

**Step 5: Run tests and iterate**

```bash
cargo test
```

**Step 6: Commit**

```bash
git add core/tuning_engine.rs tests/tuning_engine_test.rs
git commit -m "feat: TuningEngine with moria_to_hz, build_cells, viewport"
```

---

### Task 1.6: Implement Pthora engine

**Objective:** Apply a pthora to a cell, recomputing the surrounding region with the new genus intervals.

**Files:**
- Create: `core/pthora.rs`
- Create: `tests/pthora_test.rs`

**Step 1: Write failing test**

```rust
// tests/pthora_test.rs
use byzorgan_core::core::tuning_engine::*;
use byzorgan_core::core::degrees::Degree;
use byzorgan_core::core::scales::ScaleType;
use byzorgan_core::cell::Pthora;

#[test]
fn pthora_on_di_changes_intervals() {
    // Start in Diatonic. Apply HardChromatic pthora on Di.
    // Di's position stays the same, but intervals after Di become hard chromatic.
    let mut engine = TuningEngine::new(261.63, ScaleType::Diatonic);

    // Di is at moria 42 in diatonic from Ni
    let di_cells_before: Vec<_> = engine.cells().iter()
        .filter(|c| c.degree == Degree::Di && c.is_degree && c.moria_from_ni == 42)
        .collect();
    assert!(!di_cells_before.is_empty(), "should find Di at moria 42");

    // Apply HardChromatic·Pa pthora on Di
    // This says "the pitch at Di is now Pa of HardChromatic"
    engine.apply_pthora(42, Pthora::new(ScaleType::HardChromatic, Degree::Pa));

    // After pthora, cells above Di should follow HardChromatic intervals from Pa
    // HardChromatic from Pa: Pa=0, Vou=6, Ga=26, Di=30, Ke=42
    // So from Di (which is now Pa), the next degree up should be at Di+6=48
    let di_cell: Vec<_> = engine.cells().iter()
        .filter(|c| c.is_degree && c.moria_from_ni > 42)
        .take(3)
        .collect();

    // The cell after Di should be at 48 (Di + 6, HardChrom Pa→Vou)
    assert!(di_cell[0].moria_from_ni == 48,
        "expected first cell after Di at 48, got {}",
        di_cell[0].moria_from_ni);
}

#[test]
fn pthora_region_stops_at_another_pthora() {
    // If two pthorae are applied, the second one's region starts fresh
    let mut engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    engine.apply_pthora(42, Pthora::new(ScaleType::HardChromatic, Degree::Pa));
    engine.apply_pthora(72, Pthora::new(ScaleType::SoftChromatic, Degree::Ni));

    // Cells between 42 and 72 should be HardChromatic
    // Cells above 72 should be SoftChromatic
}

#[test]
fn pthora_pivot_preserves_pitch() {
    // The cell where pthora is applied keeps its moria position
    let mut engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    engine.apply_pthora(42, Pthora::new(ScaleType::HardChromatic, Degree::Pa));

    let cell = engine.cells().iter().find(|c| c.moria_from_ni == 42 && c.is_degree);
    assert!(cell.is_some(), "Di cell at 42 should still exist");
    assert_eq!(cell.unwrap().moria_from_ni, 42);
}
```

**Step 2: Implement pthora.rs**

The pthora algorithm:

```
1. Record the pivot cell's absolute moria (M)
2. The pthora says: pitch at M = target_degree of target_genus
3. Compute target_genus positions from target_degree
4. Upward: replace cells above M using new intervals
5. Downward: replace cells below M using new intervals (going backward)
6. Stop at region boundaries: another pthora, or scale edge
```

**Step 3: Add `apply_pthora` method to TuningEngine**

This will modify `tuning_engine.rs` to call into `pthora.rs`.

**Step 4: Run tests and iterate**

**Step 5: Commit**

```bash
git add core/pthora.rs tests/pthora_test.rs
git commit -m "feat: Pthora engine — modulation pivot with region recomputation"
```

---

### Task 1.7: Implement Shading engine

**Objective:** Apply tetrachord shadings that locally replace intervals.

**Files:**
- Create: `core/shading.rs`
- Create: `tests/shading_test.rs`

**Step 1: Write failing test**

```rust
// tests/shading_test.rs
use byzorgan_core::core::tuning_engine::*;
use byzorgan_core::core::degrees::Degree;
use byzorgan_core::core::scales::ScaleType;
use byzorgan_core::cell::Shading;

#[test]
fn zygos_on_ga_replaces_intervals() {
    // Diatonic from Ni: Ga=30, Di=42, Ke=54, Zo=64
    // Zygos replaces with: 18·4·16·4
    // So Ga=30, next=30+18=48, next=48+4=52, next=52+16=68, next=68+4=72
    let mut engine = TuningEngine::new(261.63, ScaleType::Diatonic);
    engine.apply_shading(30, Shading::Zygos); // apply on Ga at moria 30

    // After shading, Di should have moved from 42 to 48
    let ga_cell = engine.cells().iter().find(|c| c.moria_from_ni == 30 && c.is_degree);
    assert!(ga_cell.is_some());
    let di_cell = engine.cells().iter().filter(|c| c.is_degree && c.moria_from_ni > 30).next();
    assert_eq!(di_cell.unwrap().moria_from_ni, 48);
}
```

**Step 2: Implement shading.rs**

**Step 3: Add `apply_shading` method to TuningEngine**

**Step 4: Run tests and iterate**

**Step 5: Commit**

```bash
git add core/shading.rs tests/shading_test.rs
git commit -m "feat: Shading engine — tetrachord interval replacement"
```

---

### Task 1.8: Implement PitchDetector

**Objective:** Port the pitch detection algorithm using rustfft.

**Files:**
- Create: `core/pitch_detector.rs`
- Create: `tests/pitch_detector_test.rs`

**Step 1: Write failing test**

```rust
// tests/pitch_detector_test.rs
use byzorgan_core::core::pitch_detector::PitchDetector;

#[test]
fn detect_sine_wave_440() {
    let mut detector = PitchDetector::new(44100.0, 2048);
    // Generate a 440 Hz sine wave
    let samples: Vec<f64> = (0..2048)
        .map(|i| (2.0 * std::f64::consts::PI * 440.0 * i as f64 / 44100.0).sin())
        .collect();

    let result = detector.detect(&samples);
    assert!(result.is_some(), "should detect pitch in sine wave");
    let pitch = result.unwrap();
    assert!((pitch.hz - 440.0).abs() < 5.0, "expected ~440 Hz, got {}", pitch.hz);
    assert!(pitch.confidence > 0.8, "confidence should be high for clean sine");
}

#[test]
fn detect_returns_none_for_silence() {
    let mut detector = PitchDetector::new(44100.0, 2048);
    let samples = vec![0.0f64; 2048];
    let result = detector.detect(&samples);
    assert!(result.is_none() || result.unwrap().confidence < 0.3);
}
```

**Step 2: Implement pitch_detector.rs**

Key algorithm (ported from vocproc.cpp):
1. Apply window function (Hanning)
2. FFT using rustfft
3. Autocorrelation via inverse FFT of magnitude spectrum
4. Find peak in autocorrelation within frequency range
5. Parabolic interpolation for sub-sample accuracy

**Step 3: Run tests**

**Step 4: Commit**

```bash
git add core/pitch_detector.rs tests/pitch_detector_test.rs
git commit -m "feat: PitchDetector using rustfft with autocorrelation"
```

---

### Task 1.9: Implement SynthEngine with Ison and Melos

**Objective:** Manage active voices, ison state, and melos state.

**Files:**
- Create: `core/synth.rs`
- Create: `tests/synth_test.rs`

**Step 1: Write failing test**

```rust
// tests/synth_test.rs
use byzorgan_core::core::synth::*;
use byzorgan_core::core::degrees::Degree;

#[test]
fn ison_frequency() {
    let ison = IsonState::new(Degree::Di, 0);
    // Di is 42 moria above Ni
    // If Ni = 261.63 Hz, Di = 261.63 * 2^(42/72)
    let base_hz = 261.63;
    let expected = base_hz * 2.0_f64.powf(42.0 / 72.0);
    let diff = (ison.frequency_hz(base_hz) - expected).abs();
    assert!(diff < 0.1);
}

#[test]
fn melos_add_remove_voice() {
    let mut melos = MelosState::new();
    melos.note_on(42, 0.8); // Di
    assert_eq!(melos.active_voices().len(), 1);
    assert_eq!(melos.active_voices()[0].moria, 42);

    melos.note_off(42);
    assert_eq!(melos.active_voices().len(), 0);
}

#[test]
fn ison_independent_of_melos() {
    let mut melos = MelosState::new();
    melos.note_on(42, 0.8);
    let ison = IsonState::new(Degree::Ni, 0);
    // Ison should still be Ni, unaffected by melos
    assert_eq!(ison.degree, Degree::Ni);
}
```

**Step 2: Implement synth.rs**

```rust
// core/synth.rs
use crate::core::degrees::Degree;
use crate::core::constants::MORIA_PER_OCTAVE;

/// Ison (drone) state — manual selection only, never voice-driven
#[derive(Clone, Debug)]
pub struct IsonState {
    pub degree: Degree,
    pub octave: i32,
    pub volume: f64,
    pub enabled: bool,
}

impl IsonState {
    pub fn new(degree: Degree, octave: i32) -> IsonState {
        IsonState {
            degree,
            octave,
            volume: 0.5,
            enabled: true,
        }
    }

    /// Moria offset from base Ni for this ison degree + octave
    pub fn moria_offset(&self) -> i32 {
        // Map degree to its position in the diatonic scale from Ni
        let degree_moria = match self.degree {
            Degree::Ni  => 0,
            Degree::Pa  => 12,
            Degree::Vou => 22,
            Degree::Ga  => 30,
            Degree::Di  => 42,
            Degree::Ke  => 54,
            Degree::Zo  => 64,
        };
        degree_moria + self.octave * MORIA_PER_OCTAVE
    }

    /// Frequency in Hz given the base Ni frequency
    pub fn frequency_hz(&self, base_ni_hz: f64) -> f64 {
        base_ni_hz * 2.0_f64.powf(self.moria_offset() as f64 / MORIA_PER_OCTAVE as f64)
    }
}

/// A single synth voice
#[derive(Clone, Debug)]
pub struct Voice {
    pub moria: i32,
    pub velocity: f64,
}

/// Melos (melody) state — can be driven by keyboard or voice
#[derive(Clone, Debug)]
pub struct MelosState {
    voices: Vec<Voice>,
    pub voice_input_active: bool,
    pub detected_moria: Option<i32>,
    pub detected_confidence: f64,
}

impl MelosState {
    pub fn new() -> MelosState {
        MelosState {
            voices: Vec::new(),
            voice_input_active: false,
            detected_moria: None,
            detected_confidence: 0.0,
        }
    }

    pub fn note_on(&mut self, moria: i32, velocity: f64) {
        // Don't duplicate
        if !self.voices.iter().any(|v| v.moria == moria) {
            self.voices.push(Voice { moria, velocity });
        }
    }

    pub fn note_off(&mut self, moria: i32) {
        self.voices.retain(|v| v.moria != moria);
    }

    pub fn active_voices(&self) -> &[Voice] {
        &self.voices
    }

    /// Update from voice detection (mic input)
    pub fn update_voice(&mut self, moria: i32, confidence: f64) {
        if confidence > 0.8 {
            self.detected_moria = Some(moria);
            self.detected_confidence = confidence;
        }
    }
}
```

**Step 3: Run tests**

**Step 4: Commit**

```bash
git add core/synth.rs tests/synth_test.rs
git commit -m "feat: SynthEngine with IsonState (drone) and MelosState (melody)"
```

---

### Task 1.10: WASM bindgen exports

**Objective:** Expose the Rust API to JavaScript via wasm-bindgen.

**Files:**
- Modify: `src/lib.rs`

**Step 1: Update src/lib.rs**

```rust
pub mod core;

use wasm_bindgen::prelude::*;
use core::tuning_engine::TuningEngine;
use core::degrees::Degree;
use core::scales::ScaleType;
use core::cell::{Pthora, Shading};

#[wasm_bindgen]
pub struct WasmEngine {
    inner: TuningEngine,
}

#[wasm_bindgen]
impl WasmEngine {
    #[wasm_bindgen(constructor)]
    pub fn new(base_pitch_hz: f64, scale_type: u8) -> WasmEngine {
        let scale = match scale_type {
            0 => ScaleType::Diatonic,
            1 => ScaleType::HardChromatic,
            2 => ScaleType::SoftChromatic,
            3 => ScaleType::GraveDiatonic,
            4 => ScaleType::EnharmonicZo,
            5 => ScaleType::EnharmonicGa,
            _ => ScaleType::Diatonic,
        };
        WasmEngine {
            inner: TuningEngine::new(base_pitch_hz, scale),
        }
    }

    pub fn moria_to_hz(&self, moria: i32) -> f64 {
        self.inner.moria_to_hz(moria)
    }

    pub fn set_scale(&mut self, scale_type: u8) {
        let scale = match scale_type {
            0 => ScaleType::Diatonic,
            1 => ScaleType::HardChromatic,
            2 => ScaleType::SoftChromatic,
            3 => ScaleType::GraveDiatonic,
            4 => ScaleType::EnharmonicZo,
            5 => ScaleType::EnharmonicGa,
            _ => ScaleType::Diatonic,
        };
        self.inner.set_scale(scale);
    }

    pub fn cell_count(&self) -> usize {
        self.inner.cells().len()
    }

    pub fn cell_moria(&self, index: usize) -> i32 {
        self.inner.cells().get(index).map(|c| c.moria_from_ni).unwrap_or(0)
    }

    pub fn cell_enabled(&self, index: usize) -> bool {
        self.inner.cells().get(index).map(|c| c.enabled).unwrap_or(false)
    }

    pub fn cell_is_degree(&self, index: usize) -> bool {
        self.inner.cells().get(index).map(|c| c.is_degree).unwrap_or(false)
    }

    pub fn cell_degree_index(&self, index: usize) -> u8 {
        self.inner.cells().get(index).map(|c| c.degree as u8).unwrap_or(0)
    }

    pub fn toggle_cell(&mut self, index: usize) {
        if let Some(cell) = self.inner.cells_mut().get_mut(index) {
            cell.enabled = !cell.enabled;
        }
    }

    pub fn apply_pthora(&mut self, cell_index: usize, genus: u8, degree: u8) {
        // Will be implemented after pthora engine is complete
    }

    pub fn apply_shading(&mut self, cell_index: usize, shading: u8) {
        // Will be implemented after shading engine is complete
    }
}
```

**Step 2: Run cargo test (native tests still pass)**

**Step 3: Commit**

```bash
git add src/lib.rs
git commit -m "feat: wasm-bindgen exports for WasmEngine"
```

---

### Task 1.11: Build WASM and verify in browser

**Objective:** Confirm the WASM module builds and loads.

**Step 1: Install wasm-pack if not present**

```bash
cargo install wasm-pack
```

**Step 2: Build**

```bash
wasm-pack build --target web
```

**Step 3: Create minimal test HTML**

```html
<!-- web/test.html -->
<!DOCTYPE html>
<html>
<head><title>Byzorgan WASM Test</title></head>
<body>
<h1>Byzorgan WASM Test</h1>
<div id="output"></div>
<script type="module">
import init, { WasmEngine } from './pkg/byzorgan_core.js';
async function run() {
    await init();
    const engine = new WasmEngine(261.63, 0);
    const hz = engine.moria_to_hz(42);
    document.getElementById('output').textContent =
        `Diatonic, Di (42 moria) = ${hz.toFixed(2)} Hz`;
}
run();
</script>
</body>
</html>
```

**Step 4: Serve and verify**

```bash
cd web && python3 -m http.server 8080
```

Open browser, confirm frequency displays correctly.

**Step 5: Commit**

```bash
git add web/ pkg/
git commit -m "feat: WASM build verified, test HTML page"
```

---

## Phase 2 — WebAudio Synth

### Task 2.1: Create synth AudioWorklet

**Objective:** AudioWorklet that plays notes at given frequencies with organ timbre.

**Files:**
- Create: `web/synth_worklet.js`
- Create: `web/melos_control.js`

**Key implementation:**
- Custom `AudioWorkletProcessor` subclass
- Manages a pool of oscillators (additive synthesis with harmonics 1-8)
- Receives messages: `{ type: "noteOn", frequency, velocity }`, `{ type: "noteOff", frequency }`
- Organ timbre via harmonics with decreasing amplitude

### Task 2.2: Create ison drone

**Objective:** Continuous drone oscillator at the selected ison degree.

**Files:**
- Create: `web/ison_control.js`

**Key implementation:**
- Dedicated OscillatorNode for ison
- User selects degree + octave from dropdowns
- Frequency computed from WASM `moria_to_hz(ison_moria)`
- Volume control
- NOT connected to voice input

### Task 2.3: Wire keyboard input to melos synth

**Objective:** Map computer keyboard keys to moria positions and trigger synth notes.

**Files:**
- Create: `web/vkeyboard.js`

**Key implementation:**
- QWERTY row → diatonic degree positions
- Number row → chromatic positions between degrees
- Key press → `wasm.moria_to_hz(moria)` → `synthWorklet.postMessage({type:"noteOn",...})`
- Key release → `synthWorklet.postMessage({type:"noteOff",...})`

### Task 2.4: Voice input pipeline

**Objective:** Microphone → AudioWorklet → WASM pitch detection → update melos.

**Files:**
- Create: `web/pitch_worklet.js`

**Key implementation:**
- `getUserMedia()` → `MediaStreamAudioSourceNode`
- AudioWorklet processes frames, sends `Float32Array` to main thread
- Main thread calls `WasmEngine.detect_pitch(samples)`
- Detected moria updates melos display

---

## Phase 3 — ScaleLadder UI

### Task 3.1: Canvas-based ScaleLadder renderer

**Objective:** Draw the 2-octave cell grid with degree/non-degree cells.

**Files:**
- Create: `web/scale_ladder.js`
- Modify: `web/style.css`

**Key implementation:**
- Canvas element, draw cells as vertical strips
- Degree cells are taller, non-degree cells are shorter
- Enabled cells are filled, disabled are hollow
- Degree labels (Ni, Pa, Vou, etc.) below cells
- Arrow buttons at top/bottom for viewport shift

### Task 3.2: Cell interaction — toggle enable/disable

**Objective:** Click a cell to toggle its enabled state.

**Key implementation:**
- Canvas click handler → determine cell index from x coordinate
- Call `wasm.toggle_cell(index)`
- Redraw canvas

### Task 3.3: Right-click accidental menu

**Objective:** Right-click a cell to apply an accidental (±2, ±4, ±6, ±8).

**Key implementation:**
- Context menu on right-click
- Select moria offset → call `wasm.set_accidental(index, moria)`
- Redraw with accidental badge

### Task 3.4: Pthora palette and drag-and-drop

**Objective:** Draggable pthora buttons that modulate a cell when dropped.

**Files:**
- Create: `web/pthora_palette.js`

**Key implementation:**
- Panel with pthora buttons organized by family (Diatonic, Chromatic, Enharmonic)
- Each button has `draggable="true"` and carries genus+degree in data attributes
- Drop handler on ScaleLadder canvas → call `wasm.apply_pthora(cell_index, genus, degree)`
- Affected region highlighted with colored tint
- Uses existing SVG/PNG assets from `byzorgan-code-r138-trunk/`

### Task 3.5: Shading palette and drag-and-drop

**Objective:** Draggable shading buttons that apply tetrachord modifications.

**Key implementation:**
- Panel with shading buttons (Zygos, Kliton, Spathi A, Spathi B)
- Drop on a degree cell → replace the tetrachord intervals starting from that cell
- Call `wasm.apply_shading(cell_index, shading_type)`

---

## Phase 4 — Integration and Polish

### Task 4.1: Wire everything together in app.js

**Objective:** Main entry point that initializes WASM, WebAudio, and all UI components.

### Task 4.2: Presets — save/load scale configurations

**Objective:** Serialize the current scale + pthora + shadings + accidentals to JSON and restore.

### Task 4.3: Copy pthora assets from existing repo

**Objective:** Port SVG/PNG pthora symbols from `byzorgan-code-r138-trunk/` to `web/assets/pthora/`.

### Task 4.4: Responsive layout and styling

**Objective:** Make the UI work on different screen sizes with clean styling.

### Task 4.5: Build and deploy script

**Objective:** Automated build script that runs `wasm-pack build` and prepares the `web/` directory.

---

## Testing Strategy

- **Unit tests (Rust):** Every module has tests in `tests/` directory. Run with `cargo test`.
- **WASM integration:** Test HTML page in `web/test.html` that exercises the WASM API.
- **Manual testing checklist:**
  - [ ] All 6 scales produce correct cumulative positions for all 7 degree rotations
  - [ ] Pthora correctly recomputes surrounding cells
  - [ ] Two pthorae create correct non-overlapping regions
  - [ ] Each shading produces correct interval replacements
  - [ ] Accidentals correctly offset moria
  - [ ] moria_to_hz is accurate to within 1 cent
  - [ ] Pitch detection works with sine waves at known frequencies
  - [ ] Ison does NOT respond to voice input
  - [ ] Melos DOES respond to voice input
  - [ ] ScaleLadder displays correct 2-octave span from Di to Di
  - [ ] Arrow buttons shift viewport diatonically
  - [ ] Cells can be enabled/disabled by clicking
  - [ ] Pthora drag-and-drop applies modulation
  - [ ] Keyboard keys trigger correct moria positions

## Commit Convention

```
feat:     new feature
fix:      bug fix
test:     adding or updating tests
docs:     documentation changes
refactor: code restructuring
chore:    build, tooling, dependencies
```

## Reference

- **Scale intervals:** See `docs/BYZANTINE_SCALES_REFERENCE.md`
- **Old source code:** `/mnt/data/code/byzorgan-source/byzorgan-code-r138-trunk/`
- **Pthora assets:** In the old repo's resource/image directories
