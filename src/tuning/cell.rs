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
//! - `chromatic_phase`: for cyclic chromatic genera, the 0-based phase in the
//!   repeating four-step interval cycle.

use crate::tuning::Degree;

/// Per-cell user state stored in `TuningGrid::overrides`.
///
/// Absence from the map means "no override; use region default." Storing
/// both fields avoids Option overhead and lets the serializer round-trip
/// cleanly — callers that only want to change one field first read the
/// current value from `TuningGrid::cells()`.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CellOverride {
    /// Even-moria shift applied to the cell's nominal position. 0 = no shift.
    pub accidental: i32,
    /// Whether the cell is active. Overrides the region-derived default
    /// (degree cells default true; non-degree cells default false).
    pub enabled: bool,
}

/// A single ladder cell. See module docs for semantics.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Cell {
    pub moria: i32,
    pub degree: Option<Degree>,
    #[cfg_attr(feature = "serde", serde(skip_serializing_if = "Option::is_none"))]
    pub chromatic_phase: Option<u8>,
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
            chromatic_phase: None,
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
            chromatic_phase: None,
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
            chromatic_phase: None,
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
            chromatic_phase: None,
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
            chromatic_phase: None,
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
            chromatic_phase: None,
            accidental: 0,
            enabled: false,
            region_idx: 0,
        };
        assert!(!c.is_degree());
    }
}
