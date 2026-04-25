//! Byzantine tuning model: degrees, genera, regions, cells, pthora, shading.
//!
//! See `docs/ARCHITECTURE.md` §3 for the design and
//! `docs/BYZANTINE_SCALES_REFERENCE.md` for the authoritative music-theory
//! reference.

pub mod cell;
pub mod degree;
pub mod event;
pub mod genus;
pub mod grid;
pub mod pthora;
pub mod region;
pub mod shading;

pub use cell::{Cell, CellOverride};
pub use degree::{Degree, NUM_DEGREES};
pub use event::{
    ChroaRule, EventId, ModulatorRule, PthoraRule, SymbolDrop, TuningEvent, TuningEventKind,
};
pub use genus::Genus;
pub use grid::{moria_to_hz, nearest_enabled_cell, NearestCellResult, TuningGrid};
pub use pthora::Pthora;
pub use region::Region;
pub use shading::Shading;
