//! Shading — a local tetrachord override applied within a region.
//!
//! See `BYZANTINE_SCALES_REFERENCE.md` §5. All four shadings are tetrachords
//! rooted at Γα; the engine attaches a shading to a region and re-applies it
//! every time cells are rebuilt.
//!
//! Interval tables live here so `Region` can stay free of lookup code. Actual
//! application (overriding the Ga–Di–Ke–Zo span of a region) is implemented
//! in Task 1.7.

/// One of the four canonical Byzantine shadings.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Shading {
    /// Ζυγός: 18·4·16·4 from Γα. Diatonic-adjacent.
    Zygos,
    /// Κλιτόν: 20·4·4·14 from Γα. Chromatic-adjacent.
    Kliton,
    /// Σπάθη (α): 14·12·4 from Γα. Three-interval variant.
    SpathiA,
    /// Σπάθη (β): 14·4·4·20 from Γα. Four-interval variant.
    SpathiB,
}

impl Shading {
    /// Tetrachord steps in moria, starting from Γα.
    pub fn intervals(self) -> &'static [i32] {
        match self {
            Shading::Zygos => &[18, 4, 16, 4],
            Shading::Kliton => &[20, 4, 4, 14],
            Shading::SpathiA => &[14, 12, 4],
            Shading::SpathiB => &[14, 4, 4, 20],
        }
    }

    /// Display name for UI.
    pub fn name(self) -> &'static str {
        match self {
            Shading::Zygos => "Zygos",
            Shading::Kliton => "Kliton",
            Shading::SpathiA => "Spathi A",
            Shading::SpathiB => "Spathi B",
        }
    }

    /// All four built-in shadings.
    pub const ALL: [Shading; 4] = [
        Shading::Zygos,
        Shading::Kliton,
        Shading::SpathiA,
        Shading::SpathiB,
    ];
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Reference §5: Zygos and Kliton are four-interval tetrachords summing
    /// to 42 moria (Γα → Ζω' span).
    #[test]
    fn zygos_and_kliton_span_42_moria() {
        assert_eq!(Shading::Zygos.intervals().iter().sum::<i32>(), 42);
        assert_eq!(Shading::Kliton.intervals().iter().sum::<i32>(), 42);
    }

    /// Reference §5.3: Spathi A is explicitly open — 3 intervals summing to
    /// 30 moria, with the closing step inherited from the containing scale.
    /// Spathi B is closed at 42 moria.
    #[test]
    fn spathi_spans() {
        assert_eq!(Shading::SpathiA.intervals().iter().sum::<i32>(), 30);
        assert_eq!(Shading::SpathiB.intervals().iter().sum::<i32>(), 42);
    }
}
