//! Shading — a local chroa/enharmonic patch applied by semantic drop events.
//!
//! The interval calculations are context-sensitive and live in `TuningGrid`
//! because the effective anchor can differ from the clicked note.

/// One of the palette chroa/enharmonic symbols.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum Shading {
    /// Ζυγός.
    Zygos,
    /// Κλιτόν.
    Kliton,
    /// Σπάθη. Legacy `"SpathiKe"` and `"SpathiGa"` JSON values are migrated by
    /// `TuningGrid::from_json` into this semantic symbol with an anchor.
    Spathi,
    /// Enharmonic/Ajem modifier.
    Enharmonic,
}

impl Shading {
    /// Display name for UI.
    pub fn name(self) -> &'static str {
        match self {
            Shading::Zygos => "Zygos",
            Shading::Kliton => "Kliton",
            Shading::Spathi => "Spathi",
            Shading::Enharmonic => "Enharmonic",
        }
    }

    /// All built-in chroa/enharmonic modifiers.
    pub const ALL: [Shading; 4] = [
        Shading::Zygos,
        Shading::Kliton,
        Shading::Spathi,
        Shading::Enharmonic,
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
