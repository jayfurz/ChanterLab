//! Region — a contiguous moria span with one genus pinned to one anchor.
//!
//! A region's span (`start_moria` / `end_moria`) is independent of the pitch
//! anchor used to build cells. This lets a pthora repaint an existing section
//! bidirectionally from the drop point without forcing the drop point to become
//! a new region boundary.
//!
//! Closed genera are represented as interval steps keyed by their source
//! degree. `TuningGrid` walks those steps upward and downward from the anchor,
//! applying any active semantic events on the way.
//!
//! Open generators like `EnharmonicGa` are not handled by `degree_positions`
//! — their tiling is applied at grid-build time.

use crate::tuning::{Degree, EventId, Genus, NUM_DEGREES};

/// A contiguous moria span with a single genus anchored at a specific pitch.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Region {
    /// Absolute span start in moria, inclusive.
    pub start_moria: i32,
    /// Absolute end in moria, exclusive.
    pub end_moria: i32,
    pub genus: Genus,
    /// Absolute moria where `anchor_degree` sits.
    pub anchor_moria: i32,
    /// Which degree is pinned at `anchor_moria`.
    pub anchor_degree: Degree,
    /// Semantic events active across this region.
    #[cfg_attr(feature = "serde", serde(default))]
    pub active_rules: Vec<EventId>,
}

impl Region {
    /// Convenience constructor for a plain region without active semantic
    /// rules.
    pub fn new(
        start_moria: i32,
        end_moria: i32,
        genus: Genus,
        anchor_moria: i32,
        anchor_degree: Degree,
    ) -> Self {
        Self {
            start_moria,
            end_moria,
            genus,
            anchor_moria,
            anchor_degree,
            active_rules: Vec::new(),
        }
    }

    /// Closed-genus interval steps keyed by source degree.
    pub fn base_steps_by_degree(&self) -> Option<[i32; NUM_DEGREES]> {
        if !self.genus.is_closed() {
            return None;
        }
        let intervals = self.genus.intervals();
        let mut by_degree = [0i32; NUM_DEGREES];
        for (i, step) in intervals.into_iter().enumerate() {
            let source = self.genus.canonical_root().shifted_by(i as i32);
            by_degree[source.index()] = step;
        }
        Some(by_degree)
    }

    /// Intervals rotated so that `rotated_intervals()[0]` is the step from
    /// `anchor_degree` to its next degree.
    ///
    /// Only meaningful for closed genera. For open generators, this returns
    /// the raw generator sequence unchanged — callers handling
    /// `EnharmonicGa` should use tiling logic instead of `degree_positions`.
    pub fn rotated_intervals(&self) -> Vec<i32> {
        if let Some(by_degree) = self.base_steps_by_degree() {
            (0..NUM_DEGREES)
                .map(|i| by_degree[self.anchor_degree.shifted_by(i as i32).index()])
                .collect()
        } else {
            self.genus.intervals()
        }
    }

    /// The seven `(degree, absolute_moria)` pairs for one octave starting at
    /// `anchor_moria`. Panics (debug) if the genus is open.
    pub fn degree_positions(&self) -> [(Degree, i32); NUM_DEGREES] {
        debug_assert!(
            self.genus.is_closed(),
            "degree_positions requires a closed genus; got {}",
            self.genus.name()
        );
        let iv = self.rotated_intervals();
        let mut out = [(Degree::Ni, 0i32); NUM_DEGREES];
        let mut acc = 0i32;
        for i in 0..NUM_DEGREES {
            out[i] = (
                self.anchor_degree.shifted_by(i as i32),
                self.anchor_moria + acc,
            );
            acc += iv[i];
        }
        out
    }

    /// The moria span of this region.
    pub fn span(&self) -> i32 {
        self.end_moria - self.start_moria
    }

    /// True iff `moria` falls within `[start_moria, end_moria)`.
    pub fn contains(&self, moria: i32) -> bool {
        moria >= self.start_moria && moria < self.end_moria
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn diatonic_at_ni(start: i32, end: i32) -> Region {
        Region::new(start, end, Genus::Diatonic, start, Degree::Ni)
    }

    /// A Diatonic region rooted at Ni reproduces the canonical cumulative
    /// positions from reference §8.
    #[test]
    fn diatonic_at_ni_degree_positions() {
        let r = diatonic_at_ni(0, 72);
        let pos = r.degree_positions();
        let moria: Vec<i32> = pos.iter().map(|(_, m)| *m).collect();
        assert_eq!(moria, vec![0, 12, 22, 30, 42, 54, 64]);
        let degrees: Vec<Degree> = pos.iter().map(|(d, _)| *d).collect();
        assert_eq!(
            degrees,
            vec![
                Degree::Ni,
                Degree::Pa,
                Degree::Vou,
                Degree::Ga,
                Degree::Di,
                Degree::Ke,
                Degree::Zo,
            ]
        );
    }

    /// A Diatonic region rooted at Pa (first mode plagal) rotates the Ni-
    /// indexed intervals left by one: step[0] becomes Pa→Vou = 10.
    #[test]
    fn diatonic_rotated_to_pa() {
        let r = Region::new(0, 72, Genus::Diatonic, 0, Degree::Pa);
        assert_eq!(r.rotated_intervals(), vec![10, 8, 12, 12, 10, 8, 12]);
        let pos = r.degree_positions();
        let moria: Vec<i32> = pos.iter().map(|(_, m)| *m).collect();
        // Pa=0, Vou=10, Ga=18, Di=30, Ke=42, Zo=52, Ni'=60, (Pa'=72).
        assert_eq!(moria, vec![0, 10, 18, 30, 42, 52, 60]);
        let degrees: Vec<Degree> = pos.iter().map(|(d, _)| *d).collect();
        assert_eq!(
            degrees,
            vec![
                Degree::Pa,
                Degree::Vou,
                Degree::Ga,
                Degree::Di,
                Degree::Ke,
                Degree::Zo,
                Degree::Ni,
            ]
        );
    }

    /// HardChromatic stored from Pa; placing it with anchor_degree=Pa needs
    /// zero rotation, and the canonical cumulatives appear verbatim.
    #[test]
    fn hard_chromatic_rooted_at_pa_is_identity() {
        let r = Region::new(12, 84, Genus::HardChromatic, 12, Degree::Pa);
        assert_eq!(r.rotated_intervals(), Genus::HardChromatic.intervals());
        let pos = r.degree_positions();
        let moria: Vec<i32> = pos.iter().map(|(_, m)| *m).collect();
        // Pa=12, Vou=18, Ga=38, Di=42, Ke=54, Zo=60, Ni'=80.
        assert_eq!(moria, vec![12, 18, 38, 42, 54, 60, 80]);
    }

    /// GraveDiatonic is stored from Ga; placing it with anchor_degree=Ga is
    /// identity. Rooting it at Ni requires rotating *right by 3 degrees*
    /// (Ni is three degrees behind Ga), i.e., left by 4.
    #[test]
    fn grave_diatonic_rotated_to_ni() {
        let canonical = Genus::GraveDiatonic.intervals();
        // Canonical from Ga: Ga→Di=12, Di→Ke=10, Ke→Zo=12, Zo→Ni'=8,
        // Ni'→Pa'=6, Pa'→Vou'=16, Vou'→Ga'=8.
        assert_eq!(canonical, vec![12, 10, 12, 8, 6, 16, 8]);
        let r = Region::new(0, 72, Genus::GraveDiatonic, 0, Degree::Ni);
        // Ni sits 3 degrees after Ga in the cycle Ga→Di→Ke→Zo→Ni, so rotate
        // left by 4 in the canonical sequence to bring Ni-relative steps to
        // the front. intervals[4] = 6 (Ni→Pa), then 16 (Pa→Vou), 8 (Vou→Ga),
        // 12 (Ga→Di), 10 (Di→Ke), 12 (Ke→Zo), 8 (Zo→Ni').
        assert_eq!(r.rotated_intervals(), vec![6, 16, 8, 12, 10, 12, 8]);
    }

    #[test]
    fn span_and_contains() {
        let r = diatonic_at_ni(-36, 36);
        assert_eq!(r.span(), 72);
        assert!(r.contains(-36));
        assert!(r.contains(0));
        assert!(r.contains(35));
        assert!(!r.contains(36));
        assert!(!r.contains(-37));
    }

    /// Rotated intervals always sum to 72 for any closed genus and any root.
    #[test]
    fn rotated_intervals_sum_to_72_for_all_closed_genera() {
        for g in Genus::all_builtin() {
            if !g.is_closed() {
                continue;
            }
            for root in Degree::ALL {
                let r = Region::new(0, 72, g.clone(), 0, root);
                let sum: i32 = r.rotated_intervals().iter().sum();
                assert_eq!(
                    sum,
                    72,
                    "{} rooted at {} sums to {}",
                    g.name(),
                    root.name(),
                    sum
                );
            }
        }
    }

    /// For any closed genus placed at its canonical root, rotated_intervals
    /// should equal the raw canonical sequence (no rotation needed).
    #[test]
    fn rooting_at_canonical_root_is_identity() {
        for g in Genus::all_builtin() {
            if !g.is_closed() {
                continue;
            }
            let r = Region::new(0, 72, g.clone(), 0, g.canonical_root());
            assert_eq!(r.rotated_intervals(), g.intervals(), "{}", g.name());
        }
    }

    /// A region can have a span boundary and musical anchor at different
    /// moria values.
    #[test]
    fn region_anchor_independent_from_start() {
        let r = Region::new(-36, 72, Genus::Diatonic, 0, Degree::Ni);
        assert_eq!(r.start_moria, -36);
        assert_eq!(r.anchor_moria, 0);
        assert_eq!(r.anchor_degree, Degree::Ni);
    }
}
