//! TuningGrid — the authoritative tuning state.
//!
//! See `docs/ARCHITECTURE.md` §3.1. The grid owns:
//!
//! - `ref_ni_hz`: reference frequency for Ni at moria 0.
//! - `low_moria` / `high_moria`: visible cell window (exclusive end).
//! - `regions`: contiguous, ascending; each owns a (genus, root_degree,
//!   shading) triple for its span. Regions may extend past the visible
//!   window to align root_degree naturally (e.g. on a Ni position).
//!
//! Cells are *derived*. Nothing outside the grid stores cell state.
//! `cells()` materializes the ladder: one cell every 2 moria inside
//! `[low_moria, high_moria)`, with `degree: Some(..)` set on the positions
//! that sit on the region's rotated scale.
//!
//! Open generators like `EnharmonicGa` are skipped by `cells()` for now;
//! their tiling lands in Task 1.5.

use std::collections::HashMap;

use crate::tuning::{Cell, Degree, Genus, Region};

/// Default reference frequency: middle C (C4).
pub const DEFAULT_REF_NI_HZ: f64 = 261.63;
/// Default visible range: 3 octaves below Ni to 3 octaves above.
pub const DEFAULT_LOW_MORIA: i32 = -108;
pub const DEFAULT_HIGH_MORIA: i32 = 108;

/// Moria span of a full octave.
const OCTAVE_MORIA: i32 = 72;
/// Cell spacing in moria for non-degree slots.
const CELL_STEP: i32 = 2;

/// Convert a moria offset to a frequency given a reference Ni frequency.
///
/// `moria=0` yields `ref_ni_hz`; every 72 moria doubles it.
pub fn moria_to_hz(ref_ni_hz: f64, moria: i32) -> f64 {
    ref_ni_hz * 2.0_f64.powf(moria as f64 / OCTAVE_MORIA as f64)
}

/// The authoritative tuning state. See module docs.
#[derive(Clone, Debug, PartialEq)]
pub struct TuningGrid {
    pub ref_ni_hz: f64,
    pub low_moria: i32,
    pub high_moria: i32,
    regions: Vec<Region>,
}

impl TuningGrid {
    /// Default grid: Diatonic rooted at Ni, middle-C reference, 3-octave
    /// visible range centered on moria 0.
    pub fn new_default() -> Self {
        Self::with_preset(
            DEFAULT_REF_NI_HZ,
            DEFAULT_LOW_MORIA,
            DEFAULT_HIGH_MORIA,
            Genus::Diatonic,
            Degree::Ni,
        )
    }

    /// Build a single-region grid with the given preset.
    ///
    /// `start_moria` and `end_moria` are snapped outward to multiples of 72
    /// so the region's `root_degree` lands naturally on the 72-moria Ni
    /// lattice (see module docs). Panics if the preset genus is not closed —
    /// open generators (`EnharmonicGa`) need dedicated tiling.
    pub fn with_preset(
        ref_ni_hz: f64,
        low_moria: i32,
        high_moria: i32,
        genus: Genus,
        root_degree: Degree,
    ) -> Self {
        assert!(
            genus.is_closed(),
            "with_preset requires a closed genus; got {}",
            genus.name()
        );
        assert!(low_moria < high_moria, "low_moria must be < high_moria");
        let start_moria = floor_to_multiple(low_moria, OCTAVE_MORIA);
        let end_moria = ceil_to_multiple(high_moria, OCTAVE_MORIA);
        let region = Region {
            start_moria,
            end_moria,
            genus,
            root_degree,
            shading: None,
        };
        Self {
            ref_ni_hz,
            low_moria,
            high_moria,
            regions: vec![region],
        }
    }

    pub fn regions(&self) -> &[Region] {
        &self.regions
    }

    /// Frequency at a given moria using `self.ref_ni_hz`.
    pub fn moria_to_hz(&self, moria: i32) -> f64 {
        moria_to_hz(self.ref_ni_hz, moria)
    }

    /// Find the region that contains `moria`, if any.
    pub fn region_at(&self, moria: i32) -> Option<(usize, &Region)> {
        self.regions
            .iter()
            .enumerate()
            .find(|(_, r)| r.contains(moria))
    }

    /// Materialize the ladder cells in `[low_moria, high_moria)`.
    ///
    /// Every even moria yields a cell; positions matching the region's
    /// rotated scale get `degree: Some(..)` and `enabled: true`. Non-degree
    /// cells start disabled — the UI lights them up by user action.
    pub fn cells(&self) -> Vec<Cell> {
        let mut cells = Vec::new();
        for (idx, region) in self.regions.iter().enumerate() {
            if !region.genus.is_closed() {
                continue;
            }
            let degree_map = self.build_degree_map(region);
            let start = region.start_moria.max(self.low_moria);
            let end = region.end_moria.min(self.high_moria);
            // Align to the cell grid (start_moria is even by construction;
            // low_moria is assumed even).
            let mut m = align_up(start, CELL_STEP);
            while m < end {
                let degree = degree_map.get(&m).copied();
                let enabled = degree.is_some();
                cells.push(Cell {
                    moria: m,
                    degree,
                    accidental: 0,
                    enabled,
                    region_idx: idx,
                });
                m += CELL_STEP;
            }
        }
        cells.sort_by_key(|c| c.moria);
        cells
    }

    /// Tile the region's degree positions across its span.
    fn build_degree_map(&self, region: &Region) -> HashMap<i32, Degree> {
        let mut map = HashMap::new();
        let octave = region.degree_positions();
        let mut offset = 0;
        while region.start_moria + offset < region.end_moria {
            for &(degree, base) in &octave {
                let m = base + offset;
                if m >= region.start_moria && m < region.end_moria {
                    map.insert(m, degree);
                }
            }
            offset += OCTAVE_MORIA;
        }
        map
    }
}

impl Default for TuningGrid {
    fn default() -> Self {
        Self::new_default()
    }
}

/// Largest multiple of `m` ≤ `n`. `m` must be positive.
fn floor_to_multiple(n: i32, m: i32) -> i32 {
    n.div_euclid(m) * m
}

/// Smallest multiple of `m` ≥ `n`. `m` must be positive.
fn ceil_to_multiple(n: i32, m: i32) -> i32 {
    let q = n.div_euclid(m);
    let r = n.rem_euclid(m);
    if r == 0 {
        q * m
    } else {
        (q + 1) * m
    }
}

/// Smallest multiple of `step` ≥ `n`. `step` must be positive.
fn align_up(n: i32, step: i32) -> i32 {
    ceil_to_multiple(n, step)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moria_to_hz_at_zero_is_reference() {
        assert!((moria_to_hz(261.63, 0) - 261.63).abs() < 1e-9);
    }

    #[test]
    fn moria_to_hz_doubles_per_octave() {
        assert!((moria_to_hz(261.63, 72) - 523.26).abs() < 1e-6);
        assert!((moria_to_hz(261.63, -72) - 130.815).abs() < 1e-6);
        assert!((moria_to_hz(261.63, 144) - 1046.52).abs() < 1e-5);
    }

    #[test]
    fn moria_to_hz_matches_equal_temperament_on_72_per_octave() {
        // 72 moria per octave ⇒ 2^(m/72). Compare against exponential.
        let f0 = 440.0;
        for m in [-108, -36, 0, 36, 72, 108] {
            let expected = f0 * 2.0_f64.powf(m as f64 / 72.0);
            let got = moria_to_hz(f0, m);
            assert!((got - expected).abs() < 1e-9, "moria={}", m);
        }
    }

    #[test]
    fn floor_and_ceil_to_multiple() {
        assert_eq!(floor_to_multiple(-108, 72), -144);
        assert_eq!(floor_to_multiple(0, 72), 0);
        assert_eq!(floor_to_multiple(71, 72), 0);
        assert_eq!(floor_to_multiple(72, 72), 72);
        assert_eq!(floor_to_multiple(73, 72), 72);

        assert_eq!(ceil_to_multiple(108, 72), 144);
        assert_eq!(ceil_to_multiple(0, 72), 0);
        assert_eq!(ceil_to_multiple(1, 72), 72);
        assert_eq!(ceil_to_multiple(72, 72), 72);
        assert_eq!(ceil_to_multiple(-108, 72), -72);
    }

    #[test]
    fn default_grid_single_region_snapped_to_octave_boundaries() {
        let g = TuningGrid::new_default();
        assert_eq!(g.regions().len(), 1);
        let r = &g.regions()[0];
        assert_eq!(r.start_moria, -144);
        assert_eq!(r.end_moria, 144);
        assert_eq!(r.genus, Genus::Diatonic);
        assert_eq!(r.root_degree, Degree::Ni);
        assert_eq!(r.shading, None);
    }

    /// Default grid has cells at every even moria in [-108, 108).
    #[test]
    fn default_grid_cell_count() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        let expected = (108 - (-108)) / 2;
        assert_eq!(cells.len(), expected as usize);
        assert_eq!(cells.first().unwrap().moria, -108);
        assert_eq!(cells.last().unwrap().moria, 106);
    }

    /// Ni appears at every multiple of 72 inside the visible range.
    #[test]
    fn default_grid_ni_positions() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        let ni_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.degree == Some(Degree::Ni))
            .map(|c| c.moria)
            .collect();
        assert_eq!(ni_moria, vec![-72, 0, 72]);
    }

    /// All seven degrees appear in each octave of the visible range,
    /// with the canonical Ni-indexed cumulatives.
    #[test]
    fn default_grid_degrees_match_reference() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        // Expected degree positions in the [0, 72) octave.
        let expected: &[(i32, Degree)] = &[
            (0, Degree::Ni),
            (12, Degree::Pa),
            (22, Degree::Vou),
            (30, Degree::Ga),
            (42, Degree::Di),
            (54, Degree::Ke),
            (64, Degree::Zo),
        ];
        for (m, d) in expected {
            let cell = cells.iter().find(|c| c.moria == *m).expect("cell at moria");
            assert_eq!(cell.degree, Some(*d), "moria {}", m);
            assert!(cell.enabled, "degree cell at moria {} must be enabled", m);
        }
    }

    /// Non-degree cells start disabled.
    #[test]
    fn non_degree_cells_start_disabled() {
        let g = TuningGrid::new_default();
        for cell in g.cells() {
            if cell.degree.is_none() {
                assert!(!cell.enabled, "non-degree cell at {} should be disabled", cell.moria);
            }
        }
    }

    /// Cells are sorted and unique.
    #[test]
    fn cells_are_sorted_and_unique() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        for pair in cells.windows(2) {
            assert!(pair[0].moria < pair[1].moria);
        }
    }

    /// All cells point to region 0 in a single-region grid.
    #[test]
    fn cells_reference_correct_region() {
        let g = TuningGrid::new_default();
        for cell in g.cells() {
            assert_eq!(cell.region_idx, 0);
        }
    }

    /// A HardChromatic preset rooted at Pa produces Pa at moria 0 because
    /// the region start snaps to a multiple of 72 and the genus is
    /// identity-rotated when rooted at its canonical root.
    #[test]
    fn hard_chromatic_preset_places_pa_at_octave_multiples() {
        let g = TuningGrid::with_preset(
            261.63,
            -72,
            72,
            Genus::HardChromatic,
            Degree::Pa,
        );
        let cells = g.cells();
        let pa_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.degree == Some(Degree::Pa))
            .map(|c| c.moria)
            .collect();
        // start_moria snaps to -72 (multiple of 72). Pa sits at -72, 0.
        assert_eq!(pa_moria, vec![-72, 0]);
    }

    #[test]
    fn region_at_finds_containing_region() {
        let g = TuningGrid::new_default();
        let (idx, r) = g.region_at(0).expect("region at 0");
        assert_eq!(idx, 0);
        assert_eq!(r.start_moria, -144);
        assert!(g.region_at(200).is_none());
    }
}
