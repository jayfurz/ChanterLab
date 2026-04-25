//! Pthora — a modulation that reanchors the active genus at a specific scale
//! position.
//!
//! Dropping a pthora on a moria position M causes `TuningGrid::apply_pthora`
//! to rebuild the containing region bidirectionally from M; adjacent
//! pre-existing regions are preserved.
//!
//! The engine accepts any `(genus, degree)` combination on any moria — the
//! canonical pthora families are a UI concern, not an engine constraint.

use crate::tuning::{Degree, Genus};

/// A pthora instruction: what genus starts at the drop point and which
/// degree sits at that position.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Pthora {
    pub genus: Genus,
    /// Which degree name the pthora assigns to the drop position.
    pub target_degree: Degree,
}

impl Pthora {
    pub fn new(genus: Genus, target_degree: Degree) -> Self {
        Self {
            genus,
            target_degree,
        }
    }
}

/// Well-known pthora families exposed in the palette. The engine accepts
/// any `Pthora`; these are the canonical presets.
pub mod presets {
    use super::Pthora;
    use crate::tuning::{Degree, Genus};

    pub fn diatonic_from_ni() -> Pthora {
        Pthora::new(Genus::Diatonic, Degree::Ni)
    }
    pub fn diatonic_from_pa() -> Pthora {
        Pthora::new(Genus::Diatonic, Degree::Pa)
    }
    pub fn diatonic_from_ga() -> Pthora {
        Pthora::new(Genus::Diatonic, Degree::Ga)
    }
    pub fn hard_chromatic_from_pa() -> Pthora {
        Pthora::new(Genus::HardChromatic, Degree::Pa)
    }
    pub fn soft_chromatic_from_ni() -> Pthora {
        Pthora::new(Genus::SoftChromatic, Degree::Ni)
    }
    pub fn enharmonic_zo() -> Pthora {
        Pthora::new(Genus::EnharmonicZo, Degree::Zo)
    }
    pub fn enharmonic_ga() -> Pthora {
        Pthora::new(Genus::EnharmonicGa, Degree::Ga)
    }
}
