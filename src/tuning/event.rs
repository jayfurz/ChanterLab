//! Semantic tuning events.
//!
//! Palette drops are stored as events so provenance remains visible even when
//! two different symbols happen to produce the same pitch movement.

use crate::tuning::{Degree, Genus, Shading};

/// Stable identifier for a semantic tuning event.
pub type EventId = u64;

/// A pthora reanchor rule.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct PthoraRule {
    pub genus: Genus,
    pub anchor_degree: Degree,
}

/// A grid-wide general sharp/flat rule.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ModulatorRule {
    pub degree: Degree,
    pub shift: i32,
}

/// A local chroa/enharmonic interval patch.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ChroaRule {
    pub symbol: Shading,
    pub prior_anchor_moria: i32,
    pub prior_anchor_degree: Degree,
    pub reanchors_region: bool,
}

/// Semantic event category.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum TuningEventKind {
    PthoraReanchor(PthoraRule),
    ChroaPatch(ChroaRule),
    GenikiModulator(ModulatorRule),
    ManualAccidental,
    IsonChange,
}

/// A user- or transcription-originated tuning event.
#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TuningEvent {
    pub id: EventId,
    pub drop_moria: i32,
    pub drop_degree: Degree,
    pub resolved_anchor_moria: i32,
    pub resolved_anchor_degree: Degree,
    pub kind: TuningEventKind,
}

/// Typed palette drop consumed by the core engine.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SymbolDrop {
    Pthora {
        drop_moria: i32,
        drop_degree: Degree,
        genus: Genus,
        target_degree: Degree,
        target_phase: Option<u8>,
    },
    Chroa {
        drop_moria: i32,
        drop_degree: Degree,
        symbol: Shading,
    },
    Geniki {
        drop_moria: i32,
        drop_degree: Degree,
        shift: i32,
    },
    ClearChroa {
        drop_moria: i32,
        drop_degree: Degree,
    },
}
