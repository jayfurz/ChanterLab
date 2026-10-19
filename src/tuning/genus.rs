//! Byzantine genera (scale families).
//!
//! Closed octave genera carry an interval sequence stored
//! **canonical-root-indexed**:
//! `intervals()[0]` is the step from the genus's canonical root to the next
//! degree.
//!
//! Soft and hard chromatic are different: they are cyclic four-step systems
//! that repeat by fourth/fifth relationships, not octave systems. Their
//! interval sequences are anchored at a pthora drop point and repeat every
//! four scale degrees.
//!
//! This keeps octave scales and chromatic cycles distinct: octave scales rotate
//! by degree, while chromatic cycles walk phase-by-phase from the pthora
//! anchor.
//!
//! See `BYZANTINE_SCALES_REFERENCE.md` §3–§4 for the authoritative interval
//! values.

use crate::tuning::Degree;

/// A scale family — the interval "color" from which specific scales are built.
///
/// Closed genera have a 7-interval sequence summing to 72 moria. Cyclic
/// chromatic genera and open generators carry shorter interval sequences that
/// tile across the region span.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum Genus {
    /// Octave Natural Diatonic, canonical root Ni.
    Diatonic,
    /// Western major scale in 72-moria form, canonical root Ni.
    Western,
    /// Hard Chromatic, canonical phase root Pa.
    HardChromatic,
    /// Soft Chromatic, canonical phase root Ni.
    SoftChromatic,
    /// Grave Diatonic (Mode Plagal III diatonic), canonical root Ga.
    GraveDiatonic,
    /// Grave Enharmonic from Zo, canonical root Zo.
    EnharmonicZo,
    /// Grave Enharmonic from Ga — generator form, canonical root Ga.
    /// Not a closed 7-interval scale; see `is_closed`.
    EnharmonicGa,
    /// Equal temperament: `divisions` equal steps per octave (12 or 24),
    /// every step a note. Not degree-based; cells carry no Ni–Zo names.
    EqualTemperament { divisions: i32 },
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
            Genus::Western => Degree::Ni,
            Genus::HardChromatic => Degree::Pa,
            Genus::SoftChromatic => Degree::Ni,
            Genus::GraveDiatonic => Degree::Ga,
            Genus::EnharmonicZo => Degree::Zo,
            Genus::EnharmonicGa => Degree::Ga,
            Genus::EqualTemperament { .. } => Degree::Ni,
            Genus::Custom { canonical_root, .. } => *canonical_root,
        }
    }

    /// Canonical-root-indexed interval sequence in moria.
    ///
    /// For closed 7-element scales, sums to 72.
    /// For cyclic chromatic genera, returns the repeating four-step cycle.
    /// For the `EnharmonicGa` generator, returns the 30-moria tetrachord
    /// `[6, 12, 12]` which is tiled across a region span — see
    /// `BYZANTINE_SCALES_REFERENCE.md` §4.2.
    pub fn intervals(&self) -> Vec<i32> {
        match self {
            // Diatonic from Ni: Ni→Pa=12, Pa→Vou=10, Vou→Ga=8, Ga→Di=12,
            // Di→Ke=12, Ke→Zo=10, Zo→Ni'=8.
            Genus::Diatonic => vec![12, 10, 8, 12, 12, 10, 8],
            // Western major from Ni: do→re=12, re→mi=12, mi→fa=6,
            // fa→so=12, so→la=12, la→ti=12, ti→do'=6.
            Genus::Western => vec![12, 12, 6, 12, 12, 12, 6],
            // Hard Chromatic cyclic phase from Pa: Pa→Vou=6, Vou→Ga=20,
            // Ga→Di=4, Di→Ke=12, then repeat from Ke.
            Genus::HardChromatic => vec![6, 20, 4, 12],
            // Soft Chromatic cyclic phase from Ni: Ni→Pa=8, Pa→Vou=14,
            // Vou→Ga=8, Ga→Di=12, then repeat from Di.
            Genus::SoftChromatic => vec![8, 14, 8, 12],
            // Grave Diatonic from Ga: Ga→Di=12, Di→Ke=10, Ke→Zo=12,
            // Zo→Ni'=8, Ni'→Pa'=6, Pa'→Vou'=16, Vou'→Ga'=8.
            Genus::GraveDiatonic => vec![12, 10, 12, 8, 6, 16, 8],
            // Grave Enharmonic from Zo: Zo→Ni=6, Ni→Pa=12, Pa→Vou=12,
            // Vou→Ga=12, Ga→Di=6, Di→Ke=12, Ke→Zo'=12.
            Genus::EnharmonicZo => vec![6, 12, 12, 12, 6, 12, 12],
            // Grave Enharmonic from Ga — tetrachord generator (not closed).
            Genus::EnharmonicGa => vec![6, 12, 12],
            Genus::EqualTemperament { divisions } => vec![72 / divisions; *divisions as usize],
            Genus::Custom { intervals, .. } => intervals.clone(),
        }
    }

    /// True iff this is a closed 7-interval scale summing to exactly 72 moria.
    pub fn is_closed(&self) -> bool {
        let iv = self.intervals();
        iv.len() == 7 && iv.iter().sum::<i32>() == 72
    }

    /// True iff this genus is a four-step chromatic cycle rather than a
    /// seven-step octave scale.
    pub fn is_chromatic_cycle(&self) -> bool {
        matches!(self, Genus::HardChromatic | Genus::SoftChromatic)
    }

    /// True iff this non-closed genus can tile its raw interval sequence
    /// directly across a region.
    pub fn is_tiled_generator(&self) -> bool {
        matches!(
            self,
            Genus::HardChromatic | Genus::SoftChromatic | Genus::EnharmonicGa
        )
    }

    /// True iff this genus is an equal division of the octave.
    pub fn is_equal_temperament(&self) -> bool {
        matches!(self, Genus::EqualTemperament { .. })
    }

    /// Valid equal temperaments divide the 72-moria octave evenly.
    pub fn equal_temperament(divisions: i32) -> Option<Genus> {
        (divisions > 0 && 72 % divisions == 0).then_some(Genus::EqualTemperament { divisions })
    }

    /// Display name for UI.
    pub fn name(&self) -> &str {
        match self {
            Genus::Diatonic => "Diatonic",
            Genus::Western => "Western",
            Genus::HardChromatic => "Hard Chromatic",
            Genus::SoftChromatic => "Soft Chromatic",
            Genus::GraveDiatonic => "Grave Diatonic",
            Genus::EnharmonicZo => "Enharmonic (Zo)",
            Genus::EnharmonicGa => "Enharmonic (Ga)",
            Genus::EqualTemperament { divisions: 12 } => "Chromatic 12-ET",
            Genus::EqualTemperament { divisions: 24 } => "Chromatic 24-ET",
            Genus::EqualTemperament { .. } => "Equal temperament",
            Genus::Custom { name, .. } => name,
        }
    }

    /// All built-in (non-custom) genera.
    pub fn all_builtin() -> [Genus; 7] {
        [
            Genus::Diatonic,
            Genus::Western,
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

    /// The closed genera exclude cyclic chromatic systems and EnharmonicGa.
    #[test]
    fn non_octave_builtins_are_not_closed() {
        let all = Genus::all_builtin();
        let closed_count = all.iter().filter(|g| g.is_closed()).count();
        let open_count = all.iter().filter(|g| !g.is_closed()).count();
        assert_eq!(closed_count, 4);
        assert_eq!(open_count, 3);
        assert!(!Genus::SoftChromatic.is_closed());
        assert!(!Genus::HardChromatic.is_closed());
        assert!(!Genus::EnharmonicGa.is_closed());
        assert!(Genus::SoftChromatic.is_tiled_generator());
        assert!(Genus::HardChromatic.is_tiled_generator());
        assert!(Genus::EnharmonicGa.is_tiled_generator());
    }

    /// Canonical roots match `BYZANTINE_SCALES_REFERENCE.md` §3–§4.
    #[test]
    fn canonical_roots() {
        assert_eq!(Genus::Diatonic.canonical_root(), Degree::Ni);
        assert_eq!(Genus::Western.canonical_root(), Degree::Ni);
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
            (Genus::Diatonic, &[0, 12, 22, 30, 42, 54, 64, 72]),
            (Genus::Western, &[0, 12, 24, 30, 42, 54, 66, 72]),
            // GraveDiatonic cumulative from Ga: 0, 12, 22, 34, 42, 48, 64, 72.
            // Converting to Ni-origin (since Ga is at moria 30 below, i.e.
            // the Ga→Ga octave begins at 30 above Ni) is done in Region tests.
            (Genus::GraveDiatonic, &[0, 12, 22, 34, 42, 48, 64, 72]),
            (Genus::EnharmonicZo, &[0, 6, 18, 30, 42, 48, 60, 72]),
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

    /// Chromatic genera are four-step cycles, not octave scales.
    #[test]
    fn chromatic_generators_match_reference_cycles() {
        assert_eq!(Genus::SoftChromatic.intervals(), vec![8, 14, 8, 12]);
        assert_eq!(Genus::HardChromatic.intervals(), vec![6, 20, 4, 12]);
        assert!(Genus::SoftChromatic.is_chromatic_cycle());
        assert!(Genus::HardChromatic.is_chromatic_cycle());
    }

    /// Enharmonic-Ga generator is the 30-moria tetrachord `[6, 12, 12]`.
    #[test]
    fn enharmonic_ga_generator() {
        assert_eq!(Genus::EnharmonicGa.intervals(), vec![6, 12, 12]);
        assert!(!Genus::EnharmonicGa.is_closed());
    }

    #[test]
    fn equal_temperament_steps() {
        let g12 = Genus::equal_temperament(12).unwrap();
        assert_eq!(g12.intervals(), vec![6; 12]);
        assert_eq!(Genus::equal_temperament(24).unwrap().intervals(), vec![3; 24]);
        assert!(Genus::equal_temperament(7).is_none());
        assert!(!g12.is_closed());
        assert_eq!(g12.name(), "Chromatic 12-ET");
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
