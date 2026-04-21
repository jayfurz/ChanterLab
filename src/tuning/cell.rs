//! Cell — a single position on the Byzantine scale ladder.
//!
//! Cells are the grid's atomic unit. They're *derived* from regions and
//! overrides (see `docs/ARCHITECTURE.md` §3.1) — nothing in the engine stores
//! cell state independently of its source.
//!
//! A cell carries:
//! - `moria`: its scale-derived grid position (before any accidental).
//! - `degree`: `Some` iff the cell sits on one of the seven degrees of its
//!   containing region's rotated scale; `None` for in-between accidental
//!   slots.
//! - `accidental`: even-moria shift, any magnitude (`±2k`). UI exposes
//!   ±2/4/6/8 as defaults; data model is unbounded.
//! - `enabled`: whether the cell plays.
//! - `region_idx`: index into `TuningGrid.regions` for quick lookup.

use crate::tuning::Degree;

/// A single ladder cell. See module docs for semantics.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Cell {
    pub moria: i32,
    pub degree: Option<Degree>,
    pub accidental: i32,
    pub enabled: bool,
    pub region_idx: usize,
}

impl Cell {
    /// The actual pitch position in moria after applying the accidental.
    pub fn effective_moria(&self) -> i32 {
        self.moria + self.accidental
    }

    /// True iff this cell sits on a degree of its region's rotated scale.
    pub fn is_degree(&self) -> bool {
        self.degree.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn effective_moria_applies_accidental() {
        let c = Cell {
            moria: 12,
            degree: Some(Degree::Pa),
            accidental: 4,
            enabled: true,
            region_idx: 0,
        };
        assert_eq!(c.effective_moria(), 16);
    }

    #[test]
    fn effective_moria_zero_accidental() {
        let c = Cell {
            moria: 30,
            degree: Some(Degree::Ga),
            accidental: 0,
            enabled: true,
            region_idx: 0,
        };
        assert_eq!(c.effective_moria(), 30);
    }

    #[test]
    fn negative_accidental() {
        let c = Cell {
            moria: 22,
            degree: Some(Degree::Vou),
            accidental: -6,
            enabled: true,
            region_idx: 0,
        };
        assert_eq!(c.effective_moria(), 16);
    }

    /// Data model is unbounded: ±10 moria should be representable without
    /// saturation.
    #[test]
    fn large_accidental_accepted() {
        let c = Cell {
            moria: 22,
            degree: Some(Degree::Vou),
            accidental: 10,
            enabled: true,
            region_idx: 0,
        };
        assert_eq!(c.effective_moria(), 32);
    }

    #[test]
    fn is_degree_true_for_degree_cells() {
        let c = Cell {
            moria: 0,
            degree: Some(Degree::Ni),
            accidental: 0,
            enabled: true,
            region_idx: 0,
        };
        assert!(c.is_degree());
    }

    #[test]
    fn is_degree_false_for_in_between_cells() {
        let c = Cell {
            moria: 4,
            degree: None,
            accidental: 0,
            enabled: false,
            region_idx: 0,
        };
        assert!(!c.is_degree());
    }
}
