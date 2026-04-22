//! Region — a contiguous moria span with one genus rooted at one degree.
//!
//! See `docs/ARCHITECTURE.md` §3.2. A region owns the (genus, root_degree,
//! shading) triple for its span; cells are derived from it by laying down
//! the genus's canonical-root-indexed intervals, rotated so that the first
//! step starts from `root_degree`.
//!
//! The region's `start_moria` is the absolute grid position where
//! `root_degree` sits. `end_moria` is exclusive and equals the next region's
//! `start_moria` (contiguity invariant enforced by `TuningGrid`).
//!
//! Open generators like `EnharmonicGa` are not handled by `degree_positions`
//! — their tiling is applied at grid-build time (Task 1.5).

use crate::tuning::{Degree, Genus, Shading, NUM_DEGREES};

/// Offset of Di in a rotated interval sequence whose first degree is `root`.
fn di_offset(root: Degree) -> usize {
    (Degree::Di.index() as i32 - root.index() as i32)
        .rem_euclid(NUM_DEGREES as i32) as usize
}

/// A contiguous moria span with a single genus rooted at a specific degree.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Region {
    /// Absolute start in moria, inclusive. `root_degree` sits here.
    pub start_moria: i32,
    /// Absolute end in moria, exclusive.
    pub end_moria: i32,
    pub genus: Genus,
    /// Which degree sits at `start_moria`.
    pub root_degree: Degree,
    /// Optional local tetrachord override (applied by `TuningGrid`).
    pub shading: Option<Shading>,
}

impl Region {
    /// Intervals rotated so that `rotated_intervals()[0]` is the step from
    /// `root_degree` to its next degree.
    ///
    /// Only meaningful for closed genera. For open generators, this returns
    /// the raw generator sequence unchanged — callers handling
    /// `EnharmonicGa` should use tiling logic instead of `degree_positions`.
    pub fn rotated_intervals(&self) -> Vec<i32> {
        let mut iv = self.genus.intervals();
        if !self.genus.is_closed() {
            return iv;
        }
        let canonical = self.genus.canonical_root();
        let offset = (self.root_degree.index() as i32
            - canonical.index() as i32)
            .rem_euclid(NUM_DEGREES as i32) as usize;
        iv.rotate_left(offset);
        iv
    }

    /// Rotated intervals with the optional shading applied.
    ///
    /// Each shading is anchored to its canonical drop note (Di for Zygos and
    /// Kliton; Ke or Ga for Spathi). The drop note's cumulative position never
    /// changes — only the intervals around it are modified. The resulting slice
    /// always sums to 72 for any closed genus.
    pub fn effective_intervals(&self) -> Vec<i32> {
        let mut iv = self.rotated_intervals();
        let Some(shading) = self.shading else {
            return iv;
        };
        if iv.len() != NUM_DEGREES {
            return iv;
        }

        match shading {
            Shading::Zygos => {
                // Zygos on Di: the four ascending intervals ending at Di become
                // [18, 4, 16, 4] — Di's position is preserved (sum = 42 both
                // before and after for diatonic; any genus with the same Ni→Di
                // span will also be preserved).
                let d = di_offset(self.root_degree);
                if d >= 4 {
                    iv[d - 4] = 18; // Ni→Pa
                    iv[d - 3] = 4;  // Pa→Vou
                    iv[d - 2] = 16; // Vou→Ga
                    iv[d - 1] = 4;  // Ga→Di
                }
            }
            Shading::Kliton => {
                // Kliton on Di: two notes below Di shift; Pa stays fixed.
                // Ga→Di=4, Vou→Ga=12, Pa→Vou=14 (so Pa→Di = 30 preserved).
                let d = di_offset(self.root_degree);
                if d >= 3 {
                    iv[d - 1] = 4;  // Ga→Di
                    iv[d - 2] = 12; // Vou→Ga
                    iv[d - 3] = 14; // Pa→Vou (= 30 - 12 - 4)
                }
            }
            Shading::SpathiKe => Self::apply_spathi(&mut iv, self.root_degree, Degree::Ke),
            Shading::SpathiGa => Self::apply_spathi(&mut iv, self.root_degree, Degree::Ga),
        }

        iv
    }

    /// Spathi helper: set the two intervals adjacent to `on` to 4, then
    /// recalculate the ±2 intervals so the ±2 anchor notes stay fixed.
    fn apply_spathi(iv: &mut [i32], root: Degree, on: Degree) {
        let d = (on.index() as i32 - root.index() as i32)
            .rem_euclid(NUM_DEGREES as i32) as usize;
        // Need at least one interval below and one above the drop note,
        // plus one more on each side for the anchor recalculation.
        if d < 2 || d + 2 > NUM_DEGREES {
            return;
        }
        let old_below = iv[d - 1]; // interval into `on` from below
        let old_above = iv[d];     // interval from `on` going up
        iv[d - 1] = 4;
        iv[d] = 4;
        // Preserve the node two below `on` by absorbing the change into iv[d-2].
        iv[d - 2] += old_below - 4;
        // Preserve the node two above `on` by absorbing the change into iv[d+1].
        if d + 1 < NUM_DEGREES {
            iv[d + 1] += old_above - 4;
        }
    }

    /// The seven `(degree, absolute_moria)` pairs for one octave starting at
    /// `start_moria`, with any shading applied. Panics (debug) if the genus
    /// is open.
    pub fn degree_positions(&self) -> [(Degree, i32); NUM_DEGREES] {
        debug_assert!(
            self.genus.is_closed(),
            "degree_positions requires a closed genus; got {}",
            self.genus.name()
        );
        let iv = self.effective_intervals();
        let mut out = [(Degree::Ni, 0i32); NUM_DEGREES];
        let mut acc = 0i32;
        for i in 0..NUM_DEGREES {
            out[i] = (
                self.root_degree.shifted_by(i as i32),
                self.start_moria + acc,
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
        Region {
            start_moria: start,
            end_moria: end,
            genus: Genus::Diatonic,
            root_degree: Degree::Ni,
            shading: None,
        }
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
        let r = Region {
            start_moria: 0,
            end_moria: 72,
            genus: Genus::Diatonic,
            root_degree: Degree::Pa,
            shading: None,
        };
        assert_eq!(
            r.rotated_intervals(),
            vec![10, 8, 12, 12, 10, 8, 12]
        );
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

    /// HardChromatic stored from Pa; placing it with root_degree=Pa needs
    /// zero rotation, and the canonical cumulatives appear verbatim.
    #[test]
    fn hard_chromatic_rooted_at_pa_is_identity() {
        let r = Region {
            start_moria: 12,
            end_moria: 84,
            genus: Genus::HardChromatic,
            root_degree: Degree::Pa,
            shading: None,
        };
        assert_eq!(r.rotated_intervals(), Genus::HardChromatic.intervals());
        let pos = r.degree_positions();
        let moria: Vec<i32> = pos.iter().map(|(_, m)| *m).collect();
        // Pa=12, Vou=18, Ga=38, Di=42, Ke=54, Zo=60, Ni'=80.
        assert_eq!(moria, vec![12, 18, 38, 42, 54, 60, 80]);
    }

    /// GraveDiatonic is stored from Ga; placing it with root_degree=Ga is
    /// identity. Rooting it at Ni requires rotating *right by 3 degrees*
    /// (Ni is three degrees behind Ga), i.e., left by 4.
    #[test]
    fn grave_diatonic_rotated_to_ni() {
        let canonical = Genus::GraveDiatonic.intervals();
        // Canonical from Ga: Ga→Di=12, Di→Ke=10, Ke→Zo=12, Zo→Ni'=8,
        // Ni'→Pa'=6, Pa'→Vou'=16, Vou'→Ga'=8.
        assert_eq!(canonical, vec![12, 10, 12, 8, 6, 16, 8]);
        let r = Region {
            start_moria: 0,
            end_moria: 72,
            genus: Genus::GraveDiatonic,
            root_degree: Degree::Ni,
            shading: None,
        };
        // Ni sits 3 degrees after Ga in the cycle Ga→Di→Ke→Zo→Ni, so rotate
        // left by 4 in the canonical sequence to bring Ni-relative steps to
        // the front. intervals[4] = 6 (Ni→Pa), then 16 (Pa→Vou), 8 (Vou→Ga),
        // 12 (Ga→Di), 10 (Di→Ke), 12 (Ke→Zo), 8 (Zo→Ni').
        assert_eq!(
            r.rotated_intervals(),
            vec![6, 16, 8, 12, 10, 12, 8]
        );
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
                let r = Region {
                    start_moria: 0,
                    end_moria: 72,
                    genus: g.clone(),
                    root_degree: root,
                    shading: None,
                };
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
            let r = Region {
                start_moria: 0,
                end_moria: 72,
                genus: g.clone(),
                root_degree: g.canonical_root(),
                shading: None,
            };
            assert_eq!(r.rotated_intervals(), g.intervals(), "{}", g.name());
        }
    }

    fn diatonic_shaded(shading: Shading) -> Region {
        Region {
            start_moria: 0,
            end_moria: 72,
            genus: Genus::Diatonic,
            root_degree: Degree::Ni,
            shading: Some(shading),
        }
    }

    /// Zygos on Di: replaces the four ascending intervals ending at Di with
    /// [18,4,16,4]. Di stays at 42; upper intervals are unchanged.
    #[test]
    fn zygos_on_di_intervals() {
        let iv = diatonic_shaded(Shading::Zygos).effective_intervals();
        assert_eq!(iv, vec![18, 4, 16, 4, 12, 10, 8]);
        assert_eq!(iv.iter().sum::<i32>(), 72);
        // Di position (sum of first 4) = 18+4+16+4 = 42 (same as unshaded).
        assert_eq!(iv[..4].iter().sum::<i32>(), 42);
    }

    /// Kliton on Di: Pa stays fixed (Ni→Pa=12 unchanged), two notes below
    /// Di shift. Pa→Di span remains a perfect fourth (30 moria).
    #[test]
    fn kliton_on_di_intervals() {
        let iv = diatonic_shaded(Shading::Kliton).effective_intervals();
        assert_eq!(iv, vec![12, 14, 12, 4, 12, 10, 8]);
        assert_eq!(iv.iter().sum::<i32>(), 72);
        // Ni→Pa unchanged.
        assert_eq!(iv[0], 12);
        // Pa→Di = 14+12+4 = 30 (perfect fourth preserved).
        assert_eq!(iv[1] + iv[2] + iv[3], 30);
    }

    /// SpathiKe: Di→Ke and Ke→Zo become 4; Ga→Di and Zo→Ni' are recalculated
    /// so Ga (pos 30) and Ni' (pos 72) stay fixed.
    #[test]
    fn spathi_ke_intervals() {
        let iv = diatonic_shaded(Shading::SpathiKe).effective_intervals();
        assert_eq!(iv, vec![12, 10, 8, 20, 4, 4, 14]);
        assert_eq!(iv.iter().sum::<i32>(), 72);
        // Ga position unchanged at 30.
        assert_eq!(iv[..3].iter().sum::<i32>(), 30);
    }

    /// SpathiGa: Vou→Ga and Ga→Di become 4; Pa→Vou and Di→Ke are recalculated
    /// so Pa (pos 12) and Ke (pos 54) stay fixed.
    #[test]
    fn spathi_ga_intervals() {
        let iv = diatonic_shaded(Shading::SpathiGa).effective_intervals();
        assert_eq!(iv, vec![12, 14, 4, 4, 20, 10, 8]);
        assert_eq!(iv.iter().sum::<i32>(), 72);
        // Pa position unchanged at 12.
        assert_eq!(iv[0], 12);
        // Ke position unchanged at 54.
        assert_eq!(iv[..5].iter().sum::<i32>(), 54);
    }
}
