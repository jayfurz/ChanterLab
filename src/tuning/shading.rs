//! Shading — a local tetrachord override applied within a region.
//!
//! Each shading is applied relative to a fixed drop note; the drop note's
//! absolute position never changes. Only intervals around it are modified.
//! The actual interval calculations are context-sensitive and live in
//! `Region::effective_intervals`.

/// One of the four canonical Byzantine shadings.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum Shading {
    /// Ζυγός: dropped on Δι. The four ascending intervals ending at Di become
    /// 18·4·16·4 (Ni→Pa=18, Pa→Vou=4, Vou→Ga=16, Ga→Di=4). Di is unchanged.
    Zygos,
    /// Κλιτόν: dropped on Δι. Two notes below Di shift; Pa is preserved.
    /// Ga→Di=4, Vou→Ga=12, Pa→Vou=14 (perfect fourth Pa→Di preserved at 30).
    Kliton,
    /// Σπάθη on Κε: dropped on Ke. Di→Ke and Ke→Zo become 4; Ga→Di and
    /// Zo→Ni' are recalculated to keep Ga and Ni' at their original positions.
    SpathiKe,
    /// Σπάθη on Γα: dropped on Ga. Vou→Ga and Ga→Di become 4; Pa→Vou and
    /// Di→Ke are recalculated to keep Pa and Ke at their original positions.
    SpathiGa,
}

impl Shading {
    /// Display name for UI.
    pub fn name(self) -> &'static str {
        match self {
            Shading::Zygos => "Zygos",
            Shading::Kliton => "Kliton",
            Shading::SpathiKe => "Spathi (Ke)",
            Shading::SpathiGa => "Spathi (Ga)",
        }
    }

    /// All four built-in shadings.
    pub const ALL: [Shading; 4] = [
        Shading::Zygos,
        Shading::Kliton,
        Shading::SpathiKe,
        Shading::SpathiGa,
    ];
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_are_non_empty() {
        for s in Shading::ALL {
            assert!(!s.name().is_empty());
        }
    }
}
