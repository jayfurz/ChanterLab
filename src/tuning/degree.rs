//! The seven ascending degrees of the Byzantine scale.

/// Number of degrees in the Byzantine scale.
pub const NUM_DEGREES: usize = 7;

/// One of the seven Byzantine scale degrees (Νη, Πα, Βου, Γα, Δι, Κε, Ζω).
///
/// The `repr(usize)` discriminants are the canonical indices (Ni = 0, ...,
/// Zo = 6) used when accumulating intervals.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
#[repr(usize)]
pub enum Degree {
    Ni = 0,
    Pa = 1,
    Vou = 2,
    Ga = 3,
    Di = 4,
    Ke = 5,
    Zo = 6,
}

impl Degree {
    /// All seven degrees in ascending order.
    pub const ALL: [Degree; NUM_DEGREES] = [
        Degree::Ni,
        Degree::Pa,
        Degree::Vou,
        Degree::Ga,
        Degree::Di,
        Degree::Ke,
        Degree::Zo,
    ];

    /// Roman-letter name.
    pub fn name(self) -> &'static str {
        match self {
            Degree::Ni => "Ni",
            Degree::Pa => "Pa",
            Degree::Vou => "Vou",
            Degree::Ga => "Ga",
            Degree::Di => "Di",
            Degree::Ke => "Ke",
            Degree::Zo => "Zo",
        }
    }

    /// Greek martyria name.
    pub fn greek(self) -> &'static str {
        match self {
            Degree::Ni => "Νη",
            Degree::Pa => "Πα",
            Degree::Vou => "Βου",
            Degree::Ga => "Γα",
            Degree::Di => "Δι",
            Degree::Ke => "Κε",
            Degree::Zo => "Ζω",
        }
    }

    /// Construct from a (possibly out-of-range) index, wrapping modulo 7.
    pub fn from_index(i: usize) -> Degree {
        Self::ALL[i % NUM_DEGREES]
    }

    /// The degree's 0-based index.
    pub fn index(self) -> usize {
        self as usize
    }

    /// Shift forward (or backward, if `n < 0`) by `n` degrees, wrapping.
    ///
    /// `Degree::Zo.shifted_by(1) == Degree::Ni`, wrapping the octave.
    pub fn shifted_by(self, n: i32) -> Degree {
        let d = NUM_DEGREES as i32;
        let shifted = (self.index() as i32 + n).rem_euclid(d);
        Self::from_index(shifted as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_match_reference() {
        assert_eq!(Degree::Ni.name(), "Ni");
        assert_eq!(Degree::Vou.name(), "Vou");
        assert_eq!(Degree::Zo.name(), "Zo");
    }

    #[test]
    fn greek_names_match_reference() {
        // From BYZANTINE_SCALES_REFERENCE.md §1.
        assert_eq!(Degree::Ni.greek(), "Νη");
        assert_eq!(Degree::Ga.greek(), "Γα");
        assert_eq!(Degree::Zo.greek(), "Ζω");
    }

    #[test]
    fn index_roundtrip() {
        for (i, d) in Degree::ALL.iter().enumerate() {
            assert_eq!(d.index(), i);
            assert_eq!(Degree::from_index(i), *d);
        }
    }

    #[test]
    fn from_index_wraps() {
        assert_eq!(Degree::from_index(7), Degree::Ni);
        assert_eq!(Degree::from_index(14), Degree::Ni);
        assert_eq!(Degree::from_index(15), Degree::Pa);
    }

    #[test]
    fn shifted_by_wraps_forward_and_backward() {
        // Forward, positive range.
        for start in 0..NUM_DEGREES {
            for n in 0..14 {
                let d = Degree::from_index(start);
                let expected = Degree::from_index((start + n) % NUM_DEGREES);
                assert_eq!(d.shifted_by(n as i32), expected, "shift {} by {}", d.name(), n);
            }
        }
        // Backward.
        assert_eq!(Degree::Ni.shifted_by(-1), Degree::Zo);
        assert_eq!(Degree::Pa.shifted_by(-2), Degree::Zo);
        assert_eq!(Degree::Ga.shifted_by(-7), Degree::Ga);
        assert_eq!(Degree::Ni.shifted_by(-14), Degree::Ni);
    }
}
