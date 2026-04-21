//! Byzantine tuning model: degrees, genera, regions, cells, pthora, shading.
//!
//! See `docs/ARCHITECTURE.md` §3 for the design and
//! `docs/BYZANTINE_SCALES_REFERENCE.md` for the authoritative music-theory
//! reference.

pub mod degree;
pub mod genus;

pub use degree::{Degree, NUM_DEGREES};
pub use genus::Genus;
