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

    /// Set or clear the shading on the region containing `moria`.
    ///
    /// Returns `false` if no region contains `moria`.
    pub fn apply_shading(&mut self, moria: i32, shading: Option<crate::tuning::Shading>) -> bool {
        if let Some(idx) = self.regions.iter().position(|r| r.contains(moria)) {
            self.regions[idx].shading = shading;
            true
        } else {
            false
        }
    }

    /// Apply a pthora at `moria`: split the containing region at `moria` and
    /// let `[moria, end)` adopt `(new_genus, target_degree)`.
    ///
    /// Returns `false` if `moria` is not covered by any region.
    ///
    /// If `moria` equals a region's `start_moria`, the split produces a
    /// zero-width left remnant which is discarded — only the right half is
    /// kept. This cleanly replaces an existing pthora boundary.
    pub fn apply_pthora(&mut self, moria: i32, new_genus: Genus, target_degree: Degree) -> bool {
        let Some(idx) = self.regions.iter().position(|r| r.contains(moria)) else {
            return false;
        };
        let old = self.regions.remove(idx);
        // Build the two halves, discarding a zero-width left remnant.
        if old.start_moria < moria {
            self.regions.insert(
                idx,
                Region {
                    start_moria: old.start_moria,
                    end_moria: moria,
                    genus: old.genus,
                    root_degree: old.root_degree,
                    shading: old.shading,
                },
            );
            self.regions.insert(
                idx + 1,
                Region {
                    start_moria: moria,
                    end_moria: old.end_moria,
                    genus: new_genus,
                    root_degree: target_degree,
                    shading: None,
                },
            );
        } else {
            // moria == old.start_moria: replace in-place.
            self.regions.insert(
                idx,
                Region {
                    start_moria: moria,
                    end_moria: old.end_moria,
                    genus: new_genus,
                    root_degree: target_degree,
                    shading: None,
                },
            );
        }
        true
    }

    /// Remove the pthora at `moria` (i.e. remove the region *starting* at
    /// `moria`). Merges the removed region into its left neighbor.
    ///
    /// Returns `false` if no region starts at `moria`, or if the region to
    /// remove is the first region (nothing to merge into).
    ///
    /// The merge absorbs the removed region's span into the left neighbor's
    /// end_moria without changing the neighbor's genus or root_degree.
    pub fn remove_pthora(&mut self, moria: i32) -> bool {
        let Some(idx) = self
            .regions
            .iter()
            .position(|r| r.start_moria == moria)
        else {
            return false;
        };
        if idx == 0 {
            return false;
        }
        let removed = self.regions.remove(idx);
        self.regions[idx - 1].end_moria = removed.end_moria;
        true
    }

    /// Materialize the ladder cells in `[low_moria, high_moria)`.
    ///
    /// Every even moria yields a cell. For closed genera, positions matching
    /// the region's rotated scale get `degree: Some(..)` and `enabled: true`;
    /// non-degree slots start disabled. For `EnharmonicGa` regions the
    /// generator is tiled across the span (see `build_generator_map`).
    pub fn cells(&self) -> Vec<Cell> {
        let mut cells = Vec::new();
        for (idx, region) in self.regions.iter().enumerate() {
            let degree_map = if region.genus.is_closed() {
                self.build_degree_map(region)
            } else {
                self.build_generator_map(region)
            };
            let start = region.start_moria.max(self.low_moria);
            let end = region.end_moria.min(self.high_moria);
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

    /// Tile the closed genus's degree positions across the region span,
    /// returning a map from absolute moria → Degree.
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

    /// Tile the `EnharmonicGa` generator `[6, 12, 12]` across the region span.
    ///
    /// Each generator step lands on an absolute moria position. These
    /// positions are assigned sequential degree names starting from
    /// `region.root_degree`, cycling through all seven degrees as the
    /// generator repeats. This naming is a convention for the UI — the true
    /// tonal identity of each position comes from the tetrachord structure,
    /// not the named degree.
    ///
    /// Non-generator even-moria positions fall in the map as `None` (not
    /// inserted) so the caller marks them disabled.
    fn build_generator_map(&self, region: &Region) -> HashMap<i32, Degree> {
        let generator = region.genus.intervals();
        let mut map = HashMap::new();
        let mut m = region.start_moria;
        let mut step_idx: i32 = 0;
        while m < region.end_moria {
            let degree = region.root_degree.shifted_by(step_idx);
            map.insert(m, degree);
            // Advance to the next generator step, cycling through the
            // generator slice.
            let gen_step = generator[(step_idx as usize) % generator.len()];
            m += gen_step;
            step_idx += 1;
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
    use crate::tuning::Shading;

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

    // ── EnharmonicGa tiling tests ──────────────────────────────────────────

    fn enharmonic_ga_grid(low: i32, high: i32) -> TuningGrid {
        // Build directly since with_preset refuses open genera.
        let start = floor_to_multiple(low, OCTAVE_MORIA);
        let end = ceil_to_multiple(high, OCTAVE_MORIA);
        TuningGrid {
            ref_ni_hz: DEFAULT_REF_NI_HZ,
            low_moria: low,
            high_moria: high,
            regions: vec![Region {
                start_moria: start,
                end_moria: end,
                genus: Genus::EnharmonicGa,
                root_degree: Degree::Ga,
                shading: None,
            }],
        }
    }

    /// Generator steps from Ga land at 0, 6, 18, 30 (=30 moria / tetrachord).
    #[test]
    fn enharmonic_ga_first_tetrachord_positions() {
        let g = enharmonic_ga_grid(0, 72);
        let cells = g.cells();
        let enabled_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.enabled)
            .map(|c| c.moria)
            .collect();
        // From start_moria=0 (snapped from low_moria=0), generator:
        // 0 (Ga), +6=6, +12=18, +12=30, +6=36, +12=48, +12=60, +6=66 (exits at 72)
        assert_eq!(enabled_moria, vec![0, 6, 18, 30, 36, 48, 60, 66]);
    }

    /// Enabled cells form the 6·12·12 tiling pattern.
    #[test]
    fn enharmonic_ga_tiling_pattern() {
        let g = enharmonic_ga_grid(0, 72);
        let enabled: Vec<i32> = g.cells().iter().filter(|c| c.enabled).map(|c| c.moria).collect();
        let diffs: Vec<i32> = enabled.windows(2).map(|w| w[1] - w[0]).collect();
        // Generator [6,12,12] cycling: 6,12,12, 6,12,12, 6,12 (before 72 ends it)
        assert_eq!(diffs, vec![6, 12, 12, 6, 12, 12, 6]);
    }

    /// Non-generator cells (between generator positions) are disabled.
    #[test]
    fn enharmonic_ga_non_generator_cells_disabled() {
        let g = enharmonic_ga_grid(0, 72);
        let cells = g.cells();
        // All cells exist at 2-moria granularity; only generator positions enabled.
        assert_eq!(cells.len(), 36); // (72-0)/2
        for cell in &cells {
            if [0, 6, 18, 30, 36, 48, 60, 66].contains(&cell.moria) {
                assert!(cell.enabled, "generator pos {} should be enabled", cell.moria);
                assert!(cell.degree.is_some(), "generator pos {} should have degree", cell.moria);
            } else {
                assert!(!cell.enabled, "gap pos {} should be disabled", cell.moria);
                assert!(cell.degree.is_none(), "gap pos {} should have no degree", cell.moria);
            }
        }
    }

    /// Root Ga sits at start_moria; the degree sequence cycles from Ga.
    #[test]
    fn enharmonic_ga_degree_sequence_from_ga() {
        let g = enharmonic_ga_grid(0, 72);
        let degree_cells: Vec<(i32, Degree)> = g
            .cells()
            .into_iter()
            .filter(|c| c.degree.is_some())
            .map(|c| (c.moria, c.degree.unwrap()))
            .collect();
        // Sequential cycling from Ga: Ga, Di, Ke, Zo, Ni, Pa, Vou, Ga (wraps).
        let expected = vec![
            (0,  Degree::Ga),
            (6,  Degree::Di),
            (18, Degree::Ke),
            (30, Degree::Zo),
            (36, Degree::Ni),
            (48, Degree::Pa),
            (60, Degree::Vou),
            (66, Degree::Ga),
        ];
        assert_eq!(degree_cells, expected);
    }

    // ── Pthora application tests ───────────────────────────────────────────

    /// Applying a pthora mid-region produces two contiguous regions.
    #[test]
    fn apply_pthora_splits_region() {
        let mut g = TuningGrid::new_default();
        assert_eq!(g.regions().len(), 1);
        // Drop HardChromatic from Pa at moria=30 (where Ga sits in Diatonic).
        let ok = g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
        assert!(ok);
        assert_eq!(g.regions().len(), 2);
        let r0 = &g.regions()[0];
        let r1 = &g.regions()[1];
        // Left remnant keeps Diatonic.
        assert_eq!(r0.genus, Genus::Diatonic);
        assert_eq!(r0.start_moria, -144);
        assert_eq!(r0.end_moria, 30);
        // Right region starts the pthora.
        assert_eq!(r1.genus, Genus::HardChromatic);
        assert_eq!(r1.root_degree, Degree::Pa);
        assert_eq!(r1.start_moria, 30);
        assert_eq!(r1.end_moria, 144);
    }

    /// Applying at a region's own start_moria replaces (no zero-width remnant).
    #[test]
    fn apply_pthora_at_start_moria_replaces() {
        let mut g = TuningGrid::new_default();
        let original_start = g.regions()[0].start_moria;
        g.apply_pthora(original_start, Genus::SoftChromatic, Degree::Ni);
        assert_eq!(g.regions().len(), 1);
        assert_eq!(g.regions()[0].genus, Genus::SoftChromatic);
        assert_eq!(g.regions()[0].start_moria, original_start);
    }

    /// Applying a second pthora within the newly created region splits it again.
    #[test]
    fn apply_pthora_twice_gives_three_regions() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(0, Genus::HardChromatic, Degree::Pa);
        g.apply_pthora(42, Genus::SoftChromatic, Degree::Ni);
        assert_eq!(g.regions().len(), 3);
        // Contiguity invariant.
        let r = g.regions();
        assert_eq!(r[0].end_moria, r[1].start_moria);
        assert_eq!(r[1].end_moria, r[2].start_moria);
        assert_eq!(r[2].start_moria, 42);
        assert_eq!(r[2].genus, Genus::SoftChromatic);
    }

    /// `apply_pthora` returns false when moria is outside any region.
    #[test]
    fn apply_pthora_outside_region_returns_false() {
        let mut g = TuningGrid::new_default();
        let out_of_range = g.regions()[0].end_moria + 10;
        assert!(!g.apply_pthora(out_of_range, Genus::Diatonic, Degree::Ni));
        assert_eq!(g.regions().len(), 1);
    }

    /// remove_pthora merges the removed region into its left neighbor.
    #[test]
    fn remove_pthora_merges_into_left_neighbor() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
        assert_eq!(g.regions().len(), 2);
        let end = g.regions()[1].end_moria;
        g.remove_pthora(30);
        assert_eq!(g.regions().len(), 1);
        assert_eq!(g.regions()[0].genus, Genus::Diatonic);
        assert_eq!(g.regions()[0].end_moria, end);
    }

    /// remove_pthora on the first region (nothing to merge into) returns false.
    #[test]
    fn remove_pthora_on_first_region_returns_false() {
        let mut g = TuningGrid::new_default();
        let first_start = g.regions()[0].start_moria;
        assert!(!g.remove_pthora(first_start));
        assert_eq!(g.regions().len(), 1);
    }

    /// remove_pthora returns false if no region starts at moria.
    #[test]
    fn remove_pthora_no_region_at_moria_returns_false() {
        let mut g = TuningGrid::new_default();
        assert!(!g.remove_pthora(99));
    }

    /// After apply+remove, cells() output matches the original grid.
    #[test]
    fn pthora_apply_then_remove_restores_cells() {
        let original_cells = TuningGrid::new_default().cells();
        let mut g = TuningGrid::new_default();
        g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
        g.remove_pthora(30);
        assert_eq!(g.cells(), original_cells);
    }

    /// Cells immediately around the pthora boundary use the correct genus.
    #[test]
    fn pthora_boundary_cells_use_correct_genus() {
        let mut g = TuningGrid::new_default();
        // Place HardChromatic from Pa at moria=12 (Pa in the Diatonic octave).
        g.apply_pthora(12, Genus::HardChromatic, Degree::Pa);
        let cells = g.cells();

        // moria=0 is in the Diatonic region (region 0) — should be Ni.
        let c0 = cells.iter().find(|c| c.moria == 0).unwrap();
        assert_eq!(c0.degree, Some(Degree::Ni));
        assert_eq!(c0.region_idx, 0);

        // moria=12 is start of HardChromatic region — should be Pa.
        let c12 = cells.iter().find(|c| c.moria == 12).unwrap();
        assert_eq!(c12.degree, Some(Degree::Pa));
        assert_eq!(c12.region_idx, 1);

        // moria=18 in HardChromatic (Pa+6=Vou).
        let c18 = cells.iter().find(|c| c.moria == 18).unwrap();
        assert_eq!(c18.degree, Some(Degree::Vou));
    }

    // ── Shading tests ──────────────────────────────────────────────────────

    /// Zygos on Diatonic from Ni: Ga stays at 30, Di→48, Ke→52, Zo→68, Ni'→72.
    #[test]
    fn zygos_shading_shifts_degrees_correctly() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Zygos));
        let cells = g.cells();
        let degree_cells: Vec<(i32, Degree)> = cells
            .iter()
            .filter(|c| c.degree.is_some())
            .map(|c| (c.moria, c.degree.unwrap()))
            .collect();
        // Zygos [18,4,16,4] from Ga=30: Di=48, Ke=52, Zo=68. Ni' at 72 is
        // outside [0,72) so only 5 degree cells appear.
        let expected = vec![
            (0, Degree::Ni),
            (12, Degree::Pa),
            (22, Degree::Vou),
            (30, Degree::Ga),
            (48, Degree::Di),
            (52, Degree::Ke),
            (68, Degree::Zo),
        ];
        assert_eq!(degree_cells, expected);
    }

    /// After applying Zygos, effective_intervals still sums to 72.
    #[test]
    fn shaded_intervals_sum_to_72() {
        let r = Region {
            start_moria: 0,
            end_moria: 72,
            genus: Genus::Diatonic,
            root_degree: Degree::Ni,
            shading: Some(Shading::Zygos),
        };
        assert_eq!(r.effective_intervals().iter().sum::<i32>(), 72);

        let r2 = Region { shading: Some(Shading::Kliton), ..r.clone() };
        assert_eq!(r2.effective_intervals().iter().sum::<i32>(), 72);

        let r3 = Region { shading: Some(Shading::SpathiB), ..r.clone() };
        assert_eq!(r3.effective_intervals().iter().sum::<i32>(), 72);

        let r4 = Region { shading: Some(Shading::SpathiA), ..r.clone() };
        assert_eq!(r4.effective_intervals().iter().sum::<i32>(), 72);
    }

    /// SpathiA closing interval is auto-adjusted: Zo stays at Ga+30,
    /// Zo→Ni' is recomputed as 72 - (sum before that step).
    #[test]
    fn spathi_a_closing_interval_auto_adjusted() {
        let r = Region {
            start_moria: 0,
            end_moria: 72,
            genus: Genus::Diatonic,
            root_degree: Degree::Ni,
            shading: Some(Shading::SpathiA),
        };
        let iv = r.effective_intervals();
        // SpathiA: iv[3..6] = [14,12,4], iv[6] = 72-12-10-8-14-12-4 = 12.
        assert_eq!(iv[3], 14);
        assert_eq!(iv[4], 12);
        assert_eq!(iv[5], 4);
        assert_eq!(iv[6], 12);
        assert_eq!(iv.iter().sum::<i32>(), 72);
    }

    /// apply_shading returns false when moria is outside all regions.
    #[test]
    fn apply_shading_outside_region_returns_false() {
        let mut g = TuningGrid::new_default();
        assert!(!g.apply_shading(9999, Some(Shading::Zygos)));
    }

    /// Clearing shading (None) restores the unshaded cells.
    #[test]
    fn clearing_shading_restores_cells() {
        let unshaded = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni).cells();
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Kliton));
        g.apply_shading(0, None);
        assert_eq!(g.cells(), unshaded);
    }
}
