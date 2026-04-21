//! Byzantine genera (scale families).
//!
//! Every genus carries an interval sequence stored **canonical-root-indexed**:
//! `intervals()[0]` is the step from the genus's canonical root to the next
//! degree. For example, `Genus::HardChromatic.intervals()[0]` is Pa → Vou = 6
//! moria, because Pa is HardChromatic's canonical root.
//!
//! This single convention is the whole point of the redesign — there is no
//! "Ni-indexed" or "root-indexed" split; everything is canonical-root-indexed,
//! and rotation (if needed) happens at the `Region` boundary where the user
//! places the genus.
//!
//! See `BYZANTINE_SCALES_REFERENCE.md` §3–§4 for the authoritative interval
//! values.

use crate::tuning::Degree;

/// A scale family — the interval "color" from which specific scales are built.
///
/// Closed genera have a 7-interval sequence summing to 72 moria. Open genera
/// (`EnharmonicGa`) carry a generator tetrachord that tiles across the region
/// span; see `BYZANTINE_SCALES_REFERENCE.md` §4.2.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Genus {
    /// Octave Natural Diatonic, canonical root Ni.
    Diatonic,
    /// Hard Chromatic, canonical root Pa.
    HardChromatic,
    /// Soft Chromatic, canonical root Ni.
    SoftChromatic,
    /// Grave Diatonic (Mode Plagal III diatonic), canonical root Ga.
    GraveDiatonic,
    /// Grave Enharmonic from Zo, canonical root Zo.
    EnharmonicZo,
    /// Grave Enharmonic from Ga — generator form, canonical root Ga.
    /// Not a closed 7-interval scale; see `is_closed`.
    EnharmonicGa,
    /// User-defined interval sequence.
    ///
    /// `intervals` is stored canonical-root-indexed: the first element is the
    /// step from `canonical_root` to its next degree.
    Custom {
        name: String,
        intervals: Vec<i32>,
        canonical_root: Degree,
    },
}

impl Genus {
    /// The degree that sits at `intervals()[0]`'s source position.
    pub fn canonical_root(&self) -> Degree {
        match self {
            Genus::Diatonic => Degree::Ni,
            Genus::HardChromatic => Degree::Pa,
            Genus::SoftChromatic => Degree::Ni,
            Genus::GraveDiatonic => Degree::Ga,
            Genus::EnharmonicZo => Degree::Zo,
            Genus::EnharmonicGa => Degree::Ga,
            Genus::Custom { canonical_root, .. } => *canonical_root,
        }
    }

    /// Canonical-root-indexed interval sequence in moria.
    ///
    /// For closed 7-element scales, sums to 72.
    /// For the `EnharmonicGa` generator, returns the 30-moria tetrachord
    /// `[6, 12, 12]` which is tiled across a region span — see
    /// `BYZANTINE_SCALES_REFERENCE.md` §4.2.
    pub fn intervals(&self) -> Vec<i32> {
        match self {
            // Diatonic from Ni: Ni→Pa=12, Pa→Vou=10, Vou→Ga=8, Ga→Di=12,
            // Di→Ke=12, Ke→Zo=10, Zo→Ni'=8.
            Genus::Diatonic => vec![12, 10, 8, 12, 12, 10, 8],
            // Hard Chromatic from Pa: Pa→Vou=6, Vou→Ga=20, Ga→Di=4,
            // Di→Ke=12, Ke→Zo=6, Zo→Ni'=20, Ni'→Pa'=4.
            Genus::HardChromatic => vec![6, 20, 4, 12, 6, 20, 4],
            // Soft Chromatic from Ni: Ni→Pa=8, Pa→Vou=14, Vou→Ga=8,
            // Ga→Di=12, Di→Ke=8, Ke→Zo=14, Zo→Ni'=8.
            Genus::SoftChromatic => vec![8, 14, 8, 12, 8, 14, 8],
            // Grave Diatonic from Ga: Ga→Di=12, Di→Ke=10, Ke→Zo=12,
            // Zo→Ni'=8, Ni'→Pa'=6, Pa'→Vou'=16, Vou'→Ga'=8.
            Genus::GraveDiatonic => vec![12, 10, 12, 8, 6, 16, 8],
            // Grave Enharmonic from Zo: Zo→Ni=6, Ni→Pa=12, Pa→Vou=12,
            // Vou→Ga=12, Ga→Di=6, Di→Ke=12, Ke→Zo'=12.
            Genus::EnharmonicZo => vec![6, 12, 12, 12, 6, 12, 12],
            // Grave Enharmonic from Ga — tetrachord generator (not closed).
            Genus::EnharmonicGa => vec![6, 12, 12],
            Genus::Custom { intervals, .. } => intervals.clone(),
        }
    }

    /// True iff this is a closed 7-interval scale summing to exactly 72 moria.
    pub fn is_closed(&self) -> bool {
        let iv = self.intervals();
        iv.len() == 7 && iv.iter().sum::<i32>() == 72
    }

    /// Display name for UI.
    pub fn name(&self) -> &str {
        match self {
            Genus::Diatonic => "Diatonic",
            Genus::HardChromatic => "Hard Chromatic",
            Genus::SoftChromatic => "Soft Chromatic",
            Genus::GraveDiatonic => "Grave Diatonic",
            Genus::EnharmonicZo => "Enharmonic (Zo)",
            Genus::EnharmonicGa => "Enharmonic (Ga)",
            Genus::Custom { name, .. } => name,
        }
    }

    /// All built-in (non-custom) genera.
    pub fn all_builtin() -> [Genus; 6] {
        [
            Genus::Diatonic,
            Genus::HardChromatic,
            Genus::SoftChromatic,
            Genus::GraveDiatonic,
            Genus::EnharmonicZo,
            Genus::EnharmonicGa,
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every closed built-in genus must sum to exactly 72 moria.
    #[test]
    fn closed_genera_sum_to_72() {
        for g in Genus::all_builtin() {
            if g.is_closed() {
                let sum: i32 = g.intervals().iter().sum();
                assert_eq!(sum, 72, "{} intervals sum to {}", g.name(), sum);
            }
        }
    }

    /// The closed genera: Diatonic, HardChromatic, SoftChromatic,
    /// GraveDiatonic, EnharmonicZo (5 of the 6 built-ins).
    #[test]
    fn enharmonic_ga_is_the_only_open_builtin() {
        let all = Genus::all_builtin();
        let closed_count = all.iter().filter(|g| g.is_closed()).count();
        let open_count = all.iter().filter(|g| !g.is_closed()).count();
        assert_eq!(closed_count, 5);
        assert_eq!(open_count, 1);
        assert_eq!(
            all.iter().find(|g| !g.is_closed()).unwrap(),
            &Genus::EnharmonicGa
        );
    }

    /// Canonical roots match `BYZANTINE_SCALES_REFERENCE.md` §3–§4.
    #[test]
    fn canonical_roots() {
        assert_eq!(Genus::Diatonic.canonical_root(), Degree::Ni);
        assert_eq!(Genus::HardChromatic.canonical_root(), Degree::Pa);
        assert_eq!(Genus::SoftChromatic.canonical_root(), Degree::Ni);
        assert_eq!(Genus::GraveDiatonic.canonical_root(), Degree::Ga);
        assert_eq!(Genus::EnharmonicZo.canonical_root(), Degree::Zo);
        assert_eq!(Genus::EnharmonicGa.canonical_root(), Degree::Ga);
    }

    /// Reference doc §8: cumulative positions from the canonical root must
    /// match the summary table.
    #[test]
    fn canonical_cumulatives_match_reference() {
        let cases: &[(Genus, &[i32])] = &[
            (Genus::Diatonic,       &[0, 12, 22, 30, 42, 54, 64, 72]),
            (Genus::HardChromatic,  &[0,  6, 26, 30, 42, 48, 68, 72]),
            (Genus::SoftChromatic,  &[0,  8, 22, 30, 42, 50, 64, 72]),
            // GraveDiatonic cumulative from Ga: 0, 12, 22, 34, 42, 48, 64, 72.
            // Converting to Ni-origin (since Ga is at moria 30 below, i.e.
            // the Ga→Ga octave begins at 30 above Ni) is done in Region tests.
            (Genus::GraveDiatonic,  &[0, 12, 22, 34, 42, 48, 64, 72]),
            (Genus::EnharmonicZo,   &[0,  6, 18, 30, 42, 48, 60, 72]),
        ];
        for (genus, expected) in cases {
            let mut cum = vec![0i32];
            let mut acc = 0i32;
            for step in genus.intervals() {
                acc += step;
                cum.push(acc);
            }
            assert_eq!(
                cum.as_slice(),
                *expected,
                "{} cumulative mismatch",
                genus.name()
            );
        }
    }

    /// Enharmonic-Ga generator is the 30-moria tetrachord `[6, 12, 12]`.
    #[test]
    fn enharmonic_ga_generator() {
        assert_eq!(Genus::EnharmonicGa.intervals(), vec![6, 12, 12]);
        assert!(!Genus::EnharmonicGa.is_closed());
    }

    /// Custom genus carries user-supplied data.
    #[test]
    fn custom_genus_preserves_data() {
        let g = Genus::Custom {
            name: "My Mode".into(),
            intervals: vec![10, 10, 10, 10, 10, 10, 12],
            canonical_root: Degree::Di,
        };
        assert_eq!(g.name(), "My Mode");
        assert_eq!(g.canonical_root(), Degree::Di);
        assert_eq!(g.intervals(), vec![10, 10, 10, 10, 10, 10, 12]);
        assert!(g.is_closed());
    }
}
