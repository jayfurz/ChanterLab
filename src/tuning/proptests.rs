//! Property tests for `TuningGrid` structural invariants.
//!
//! ARCHITECTURE.md §9 calls for property tests asserting the grid's invariants
//! hold after arbitrary edit sequences: regions stay contiguous, cells stay
//! sorted/unique and inside their region, and the worklet tuning table stays
//! sorted and enabled-only. These fuzz long random sequences of pthora, chroa,
//! geniki, accidental, toggle, clear, and pthora-removal operations and assert
//! the invariants survive every combination.

use proptest::prelude::*;

use crate::tuning::grid::{DEFAULT_HIGH_MORIA, DEFAULT_LOW_MORIA, DEFAULT_REF_NI_HZ};
use crate::tuning::{Degree, Genus, Shading, SymbolDrop, TuningGrid};

/// One user-facing edit applied through the grid's public API.
#[derive(Debug, Clone)]
enum Op {
    Pthora {
        moria: i32,
        genus: Genus,
        degree: Degree,
    },
    Chroa {
        moria: i32,
        shading: Shading,
    },
    ClearChroa {
        moria: i32,
    },
    Geniki {
        moria: i32,
        degree: Degree,
        shift: i32,
    },
    Accidental {
        moria: i32,
        k: i32,
    },
    Toggle {
        moria: i32,
    },
    ClearOverride {
        moria: i32,
    },
    RemovePthora {
        moria: i32,
    },
}

fn genus_strategy() -> impl Strategy<Value = Genus> {
    prop_oneof![
        Just(Genus::Diatonic),
        Just(Genus::Western),
        Just(Genus::HardChromatic),
        Just(Genus::SoftChromatic),
        Just(Genus::GraveDiatonic),
        Just(Genus::EnharmonicZo),
        Just(Genus::EnharmonicGa),
    ]
}

fn degree_strategy() -> impl Strategy<Value = Degree> {
    (0usize..7).prop_map(Degree::from_index)
}

fn shading_strategy() -> impl Strategy<Value = Shading> {
    prop_oneof![
        Just(Shading::Zygos),
        Just(Shading::Kliton),
        Just(Shading::Spathi),
        Just(Shading::Enharmonic),
    ]
}

/// Moria range covering the default visible window plus a little slack so some
/// operations land outside any region (and are harmlessly rejected).
fn moria_strategy() -> impl Strategy<Value = i32> {
    DEFAULT_LOW_MORIA - 8..DEFAULT_HIGH_MORIA + 8
}

fn op_strategy() -> impl Strategy<Value = Op> {
    prop_oneof![
        (moria_strategy(), genus_strategy(), degree_strategy()).prop_map(
            |(moria, genus, degree)| Op::Pthora {
                moria,
                genus,
                degree
            }
        ),
        (moria_strategy(), shading_strategy())
            .prop_map(|(moria, shading)| Op::Chroa { moria, shading }),
        moria_strategy().prop_map(|moria| Op::ClearChroa { moria }),
        // Geniki is the ±6 general accidental (see lib.rs Diesis/Yfesis Geniki).
        (
            moria_strategy(),
            degree_strategy(),
            prop_oneof![Just(-6), Just(6)]
        )
            .prop_map(|(moria, degree, shift)| Op::Geniki {
                moria,
                degree,
                shift
            }),
        // Accidentals must be even; k scales to a ±even shift.
        (moria_strategy(), -6i32..=6).prop_map(|(moria, k)| Op::Accidental { moria, k }),
        moria_strategy().prop_map(|moria| Op::Toggle { moria }),
        moria_strategy().prop_map(|moria| Op::ClearOverride { moria }),
        moria_strategy().prop_map(|moria| Op::RemovePthora { moria }),
    ]
}

/// Initial single-region grid: any built-in genus, any anchor, default window.
fn grid_strategy() -> impl Strategy<Value = TuningGrid> {
    (genus_strategy(), degree_strategy()).prop_map(|(genus, anchor)| {
        TuningGrid::with_preset(
            DEFAULT_REF_NI_HZ,
            DEFAULT_LOW_MORIA,
            DEFAULT_HIGH_MORIA,
            genus,
            anchor,
        )
    })
}

fn apply(grid: &mut TuningGrid, op: &Op) {
    match op {
        Op::Pthora {
            moria,
            genus,
            degree,
        } => {
            let _ = grid.apply_pthora(*moria, genus.clone(), *degree);
        }
        Op::Chroa { moria, shading } => {
            let _ = grid.apply_shading(*moria, Some(*shading));
        }
        Op::ClearChroa { moria } => {
            let _ = grid.apply_shading(*moria, None);
        }
        Op::Geniki {
            moria,
            degree,
            shift,
        } => {
            let _ = grid.apply_symbol_drop(SymbolDrop::Geniki {
                drop_moria: *moria,
                drop_degree: *degree,
                shift: *shift,
            });
        }
        Op::Accidental { moria, k } => grid.set_accidental(*moria, k * 2),
        Op::Toggle { moria } => {
            let _ = grid.toggle_cell(*moria);
        }
        Op::ClearOverride { moria } => grid.clear_override(*moria),
        Op::RemovePthora { moria } => {
            let _ = grid.remove_pthora(*moria);
        }
    }
}

/// Assert every structural invariant on the grid in its current state.
fn assert_invariants(grid: &TuningGrid) {
    let regions = grid.regions();
    assert!(!regions.is_empty(), "grid must always have ≥1 region");

    // Regions are ascending, non-empty, and contiguous (no gaps/overlaps).
    for r in regions {
        assert!(
            r.start_moria < r.end_moria,
            "region must have positive span: {r:?}"
        );
    }
    for pair in regions.windows(2) {
        assert_eq!(
            pair[0].end_moria, pair[1].start_moria,
            "regions must be contiguous: {:?} then {:?}",
            pair[0], pair[1]
        );
    }

    // The region cover must include the whole visible window.
    assert!(regions.first().unwrap().start_moria <= grid.low_moria);
    assert!(regions.last().unwrap().end_moria >= grid.high_moria);

    let cells = grid.cells();

    // Cells are strictly ascending and unique by moria.
    for pair in cells.windows(2) {
        assert!(
            pair[0].moria < pair[1].moria,
            "cells must be sorted and unique: {} then {}",
            pair[0].moria,
            pair[1].moria
        );
    }

    for cell in &cells {
        // Inside the visible window.
        assert!(
            cell.moria >= grid.low_moria && cell.moria < grid.high_moria,
            "cell {} outside [{}, {})",
            cell.moria,
            grid.low_moria,
            grid.high_moria
        );
        // Even-moria grid positions.
        assert_eq!(cell.moria.rem_euclid(2), 0, "cell {} not even", cell.moria);
        // Accidentals stay even (region default 0, ±even accidentals, ±6 geniki).
        assert_eq!(
            cell.accidental.rem_euclid(2),
            0,
            "accidental {} at moria {} not even",
            cell.accidental,
            cell.moria
        );
        assert_eq!(cell.effective_moria(), cell.moria + cell.accidental);
        // region_idx points at a region that actually contains the cell.
        let region = regions
            .get(cell.region_idx)
            .expect("cell region_idx in range");
        assert!(
            region.contains(cell.moria),
            "cell {} not contained by its region {:?}",
            cell.moria,
            region
        );
    }

    // The worklet tuning table is sorted ascending by period and enabled-only.
    let table = grid.tuning_table(48_000.0);
    let enabled = cells.iter().filter(|c| c.enabled).count();
    assert_eq!(
        table.len(),
        enabled,
        "tuning table must hold every enabled cell"
    );
    for pair in table.windows(2) {
        assert!(
            pair[0].0 <= pair[1].0,
            "tuning table must be period-sorted: {} then {}",
            pair[0].0,
            pair[1].0
        );
    }
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(192))]

    /// A freshly-built single-region grid satisfies every invariant.
    #[test]
    fn fresh_grid_holds_invariants(grid in grid_strategy()) {
        assert_invariants(&grid);
    }

    /// Invariants survive an arbitrary sequence of edits.
    #[test]
    fn edits_preserve_invariants(
        mut grid in grid_strategy(),
        ops in prop::collection::vec(op_strategy(), 0..16),
    ) {
        for op in &ops {
            apply(&mut grid, op);
            // Check after *every* step so a shrinking failure points at the
            // exact operation that broke an invariant.
            assert_invariants(&grid);
        }
    }
}
