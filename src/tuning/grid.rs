//! TuningGrid — the authoritative tuning state.
//!
//! See `docs/ARCHITECTURE.md` §3.1. The grid owns:
//!
//! - `ref_ni_hz`: reference frequency for Ni at moria 0.
//! - `low_moria` / `high_moria`: visible cell window (exclusive end).
//! - `regions`: contiguous, ascending spans. Each span has an independent
//!   musical anchor (`anchor_moria`, `anchor_degree`) so pthorae can repaint
//!   a section bidirectionally from the drop point.
//!
//! Cells are *derived*. Nothing outside the grid stores cell state.
//! `cells()` materializes the ladder: one cell every 2 moria inside
//! `[low_moria, high_moria)`, with `degree: Some(..)` set on the positions
//! that sit on the region's rotated scale.
//!
//! Cyclic chromatic systems and open generators like `EnharmonicGa` are tiled
//! from the region anchor.

use std::collections::HashMap;

use crate::tuning::{
    Cell, CellOverride, ChroaRule, Degree, EventId, Genus, ModulatorRule, PthoraRule, Region,
    Shading, SymbolDrop, TuningEvent, TuningEventKind, NUM_DEGREES,
};

/// Default reference frequency: baritone Ni at C3.
pub const DEFAULT_REF_NI_HZ: f64 = 130.81;
/// Default visible range: one octave below reference Ni through two octaves
/// above it. `high_moria` is exclusive, so 146 includes the +144 Ni cell.
pub const DEFAULT_LOW_MORIA: i32 = -72;
pub const DEFAULT_HIGH_MORIA: i32 = 146;

/// Moria span of a full octave.
const OCTAVE_MORIA: i32 = 72;
/// Cell spacing in moria for non-degree slots.
const CELL_STEP: i32 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct DegreeCellInfo {
    degree: Degree,
    chromatic_phase: Option<u8>,
}

/// Convert a moria offset to a frequency given a reference Ni frequency.
///
/// `moria=0` yields `ref_ni_hz`; every 72 moria doubles it.
pub fn moria_to_hz(ref_ni_hz: f64, moria: i32) -> f64 {
    ref_ni_hz * 2.0_f64.powf(moria as f64 / OCTAVE_MORIA as f64)
}

/// The authoritative tuning state. See module docs.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize))]
pub struct TuningGrid {
    pub ref_ni_hz: f64,
    pub low_moria: i32,
    pub high_moria: i32,
    regions: Vec<Region>,
    events: Vec<TuningEvent>,
    next_event_id: EventId,
    /// Per-cell user overrides keyed by the cell's nominal moria.
    overrides: HashMap<i32, CellOverride>,
}

#[cfg(feature = "serde")]
impl<'de> serde::Deserialize<'de> for TuningGrid {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        use serde::de::Error;
        use serde::Deserialize;

        #[derive(Deserialize)]
        struct RawGrid {
            ref_ni_hz: f64,
            low_moria: i32,
            high_moria: i32,
            regions: Vec<RawRegion>,
            #[serde(default)]
            events: Vec<TuningEvent>,
            #[serde(default)]
            next_event_id: Option<EventId>,
            #[serde(default)]
            overrides: HashMap<i32, CellOverride>,
        }

        #[derive(Deserialize)]
        struct RawRegion {
            start_moria: i32,
            end_moria: i32,
            genus: Genus,
            #[serde(default)]
            anchor_moria: Option<i32>,
            #[serde(default)]
            anchor_degree: Option<Degree>,
            #[serde(default)]
            root_degree: Option<Degree>,
            #[serde(default)]
            active_rules: Vec<EventId>,
            #[serde(default)]
            shading: Option<LegacyShading>,
        }

        #[derive(Clone, Copy, Deserialize)]
        enum LegacyShading {
            Zygos,
            Kliton,
            Spathi,
            SpathiKe,
            SpathiGa,
            Enharmonic,
        }

        let raw = RawGrid::deserialize(deserializer)?;
        let mut events = raw.events;
        let mut next_event_id = raw.next_event_id.unwrap_or(1).max(1);
        if let Some(max_id) = events.iter().map(|event| event.id).max() {
            next_event_id = next_event_id.max(max_id + 1);
        }

        let mut regions = Vec::with_capacity(raw.regions.len());
        for raw_region in raw.regions {
            let anchor_moria = raw_region.anchor_moria.unwrap_or(raw_region.start_moria);
            let anchor_degree = raw_region
                .anchor_degree
                .or(raw_region.root_degree)
                .ok_or_else(|| D::Error::missing_field("anchor_degree"))?;
            let mut active_rules = raw_region.active_rules;

            if let Some(legacy) = raw_region.shading {
                let (symbol, legacy_anchor_degree) = match legacy {
                    LegacyShading::Zygos => (Shading::Zygos, Degree::Di),
                    LegacyShading::Kliton => (Shading::Kliton, Degree::Di),
                    LegacyShading::Spathi => (Shading::Spathi, anchor_degree),
                    LegacyShading::SpathiKe => (Shading::Spathi, Degree::Ke),
                    LegacyShading::SpathiGa => (Shading::Spathi, Degree::Ga),
                    LegacyShading::Enharmonic => (Shading::Enharmonic, anchor_degree),
                };
                let legacy_anchor_moria = closed_degree_moria_from_anchor(
                    &raw_region.genus,
                    anchor_moria,
                    anchor_degree,
                    legacy_anchor_degree,
                )
                .unwrap_or(anchor_moria);
                let event_id = next_event_id;
                next_event_id += 1;
                events.push(TuningEvent {
                    id: event_id,
                    drop_moria: legacy_anchor_moria,
                    drop_degree: legacy_anchor_degree,
                    resolved_anchor_moria: legacy_anchor_moria,
                    resolved_anchor_degree: legacy_anchor_degree,
                    kind: TuningEventKind::ChroaPatch(ChroaRule {
                        symbol,
                        prior_anchor_moria: anchor_moria,
                        prior_anchor_degree: anchor_degree,
                        reanchors_region: false,
                    }),
                });
                active_rules.push(event_id);
            }

            regions.push(Region {
                start_moria: raw_region.start_moria,
                end_moria: raw_region.end_moria,
                genus: raw_region.genus,
                anchor_moria,
                anchor_degree,
                active_rules,
            });
        }

        Ok(Self {
            ref_ni_hz: raw.ref_ni_hz,
            low_moria: raw.low_moria,
            high_moria: raw.high_moria,
            regions,
            events,
            next_event_id,
            overrides: raw.overrides,
        })
    }
}

#[cfg(feature = "serde")]
fn closed_degree_moria_from_anchor(
    genus: &Genus,
    anchor_moria: i32,
    anchor_degree: Degree,
    target_degree: Degree,
) -> Option<i32> {
    let region = Region::new(0, 0, genus.clone(), anchor_moria, anchor_degree);
    let steps = region.base_steps_by_degree()?;
    let mut m = anchor_moria;
    let mut degree = anchor_degree;
    let count = (target_degree.index() as i32 - anchor_degree.index() as i32)
        .rem_euclid(NUM_DEGREES as i32);
    for _ in 0..count {
        m += steps[degree.index()];
        degree = degree.shifted_by(1);
    }
    Some(m)
}

#[cfg(feature = "serde")]
impl TuningGrid {
    /// Serialize the grid to a compact JSON string for LocalStorage / postMessage.
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }

    /// Deserialize a grid from a JSON string produced by `to_json`.
    pub fn from_json(json: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(json)
    }
}

impl TuningGrid {
    /// Default grid: Diatonic rooted at Ni, middle-C reference, 3-octave
    /// visible range centered on moria 0.
    pub fn new_default() -> Self {
        Self::with_preset(
            DEFAULT_REF_NI_HZ,
            DEFAULT_LOW_MORIA,
            DEFAULT_HIGH_MORIA,
            Genus::Diatonic,
            Degree::Ni,
        )
    }

    /// Build a single-region grid with the given preset.
    ///
    /// `start_moria` and `end_moria` are snapped outward to multiples of 72.
    /// The region's initial anchor sits at `start_moria`. Panics if the
    /// preset genus is neither a closed octave genus nor a supported tiled
    /// generator.
    pub fn with_preset(
        ref_ni_hz: f64,
        low_moria: i32,
        high_moria: i32,
        genus: Genus,
        anchor_degree: Degree,
    ) -> Self {
        assert!(
            genus.is_closed() || genus.is_tiled_generator(),
            "with_preset requires a closed or tiled genus; got {}",
            genus.name()
        );
        assert!(low_moria < high_moria, "low_moria must be < high_moria");
        let start_moria = floor_to_multiple(low_moria, OCTAVE_MORIA);
        let end_moria = ceil_to_multiple(high_moria, OCTAVE_MORIA);
        let region = Region::new(start_moria, end_moria, genus, start_moria, anchor_degree);
        Self {
            ref_ni_hz,
            low_moria,
            high_moria,
            regions: vec![region],
            events: Vec::new(),
            next_event_id: 1,
            overrides: HashMap::new(),
        }
    }

    pub fn regions(&self) -> &[Region] {
        &self.regions
    }

    pub fn events(&self) -> &[TuningEvent] {
        &self.events
    }

    /// Read-only access to the override map.
    pub fn overrides(&self) -> &HashMap<i32, CellOverride> {
        &self.overrides
    }

    /// Set an accidental on the cell at `moria`. `accidental` is the moria
    /// shift; use 0 to remove a prior accidental. Inserts or updates an
    /// override; use `clear_override` to fully remove the override entry.
    ///
    /// Panics if `accidental` is odd (Byzantine accidentals must be even).
    pub fn set_accidental(&mut self, moria: i32, accidental: i32) {
        assert_eq!(
            accidental % 2,
            0,
            "accidental must be an even number of moria"
        );
        // Seed the override's enabled field from the current cell state so
        // the user's prior toggle is not clobbered.
        let current_enabled = self
            .cells()
            .into_iter()
            .find(|c| c.moria == moria)
            .map(|c| c.enabled)
            .unwrap_or(false);
        let entry = self.overrides.entry(moria).or_insert(CellOverride {
            accidental: 0,
            enabled: current_enabled,
        });
        entry.accidental = accidental;
    }

    /// Explicitly set the enabled state for the cell at `moria`.
    ///
    /// Inserts or updates an override. Use `clear_override` to restore the
    /// region default.
    pub fn set_enabled(&mut self, moria: i32, enabled: bool) {
        let entry = self.overrides.entry(moria).or_insert(CellOverride {
            accidental: 0,
            enabled,
        });
        entry.enabled = enabled;
    }

    /// Toggle the enabled state of the cell at `moria`. Returns the new state,
    /// or `None` if no cell exists at that moria in the visible range.
    pub fn toggle_cell(&mut self, moria: i32) -> Option<bool> {
        let cells = self.cells();
        let base_enabled = cells.iter().find(|c| c.moria == moria)?.enabled;
        let new_state = !base_enabled;
        self.set_enabled(moria, new_state);
        Some(new_state)
    }

    /// Remove the override for `moria`, restoring the region-derived default.
    pub fn clear_override(&mut self, moria: i32) {
        self.overrides.remove(&moria);
    }

    /// Frequency at a given moria using `self.ref_ni_hz`.
    pub fn moria_to_hz(&self, moria: i32) -> f64 {
        moria_to_hz(self.ref_ni_hz, moria)
    }

    /// Find the region that contains `moria`, if any.
    pub fn region_at(&self, moria: i32) -> Option<(usize, &Region)> {
        self.regions
            .iter()
            .enumerate()
            .find(|(_, r)| r.contains(moria))
    }

    /// Apply a typed semantic palette drop.
    pub fn apply_symbol_drop(&mut self, drop: SymbolDrop) -> bool {
        match drop {
            SymbolDrop::Pthora {
                drop_moria,
                drop_degree,
                genus,
                target_degree,
                target_phase,
            } => {
                self.apply_pthora_drop(drop_moria, drop_degree, genus, target_degree, target_phase)
            }
            SymbolDrop::Chroa {
                drop_moria,
                drop_degree,
                symbol,
            } => self.apply_chroa_drop(drop_moria, drop_degree, symbol),
            SymbolDrop::Geniki {
                drop_moria,
                drop_degree,
                shift,
            } => self.apply_geniki_drop(drop_moria, drop_degree, shift),
            SymbolDrop::ClearChroa {
                drop_moria,
                drop_degree: _,
            } => self.clear_chroa_at(drop_moria),
        }
    }

    /// Set or clear the local chroa/enharmonic modifier on the region
    /// containing `moria`.
    ///
    /// Compatibility wrapper for the old string-only API. New callers should
    /// use `apply_symbol_drop` so the clicked degree is explicit.
    pub fn apply_shading(&mut self, moria: i32, shading: Option<Shading>) -> bool {
        if shading.is_none() {
            return self.clear_chroa_at(moria);
        }
        let Some(cell) = self
            .cells()
            .into_iter()
            .find(|c| c.moria == moria && c.degree.is_some())
        else {
            return false;
        };
        let degree = cell.degree.unwrap();
        self.apply_chroa_drop(moria, degree, shading.unwrap())
    }

    /// Apply a pthora at `moria`: rebuild the containing region around the
    /// resolved pthora anchor. Unlike the old implementation, this does not
    /// split the region at `moria`; cells on both sides of the anchor are
    /// reinterpreted until the pre-existing region boundary is reached.
    ///
    /// Returns `false` if `moria` is not covered by any region.
    pub fn apply_pthora(&mut self, moria: i32, new_genus: Genus, target_degree: Degree) -> bool {
        let drop_degree = self
            .cells()
            .into_iter()
            .find(|c| c.moria == moria)
            .and_then(|c| c.degree)
            .unwrap_or(target_degree);
        self.apply_pthora_drop(moria, drop_degree, new_genus, target_degree, None)
    }

    fn apply_pthora_drop(
        &mut self,
        moria: i32,
        drop_degree: Degree,
        new_genus: Genus,
        target_degree: Degree,
        target_phase: Option<u8>,
    ) -> bool {
        let Some(idx) = self.regions.iter().position(|r| r.contains(moria)) else {
            return false;
        };

        let (anchor_moria, anchor_degree) = self.resolve_pthora_anchor(
            idx,
            moria,
            drop_degree,
            &new_genus,
            target_degree,
            target_phase,
        );

        self.remove_region_events(idx);
        let event_id = self.push_event(
            moria,
            drop_degree,
            anchor_moria,
            anchor_degree,
            TuningEventKind::PthoraReanchor(PthoraRule {
                genus: new_genus.clone(),
                anchor_degree,
            }),
        );

        let region = &mut self.regions[idx];
        region.genus = new_genus;
        region.anchor_moria = anchor_moria;
        region.anchor_degree = anchor_degree;
        region.active_rules = vec![event_id];
        true
    }

    fn apply_chroa_drop(&mut self, moria: i32, drop_degree: Degree, symbol: Shading) -> bool {
        let Some(idx) = self.regions.iter().position(|r| r.contains(moria)) else {
            return false;
        };

        let (anchor_moria, anchor_degree, reanchor_region) =
            self.resolve_chroa_anchor(idx, moria, drop_degree, symbol);
        let prior_anchor_moria = self.regions[idx].anchor_moria;
        let prior_anchor_degree = self.regions[idx].anchor_degree;

        self.remove_chroa_events(idx);
        let event_id = self.push_event(
            moria,
            drop_degree,
            anchor_moria,
            anchor_degree,
            TuningEventKind::ChroaPatch(ChroaRule {
                symbol,
                prior_anchor_moria,
                prior_anchor_degree,
                reanchors_region: reanchor_region,
            }),
        );

        let region = &mut self.regions[idx];
        if reanchor_region {
            region.anchor_moria = anchor_moria;
            region.anchor_degree = anchor_degree;
        }
        region.active_rules.push(event_id);
        true
    }

    fn apply_geniki_drop(&mut self, moria: i32, drop_degree: Degree, shift: i32) -> bool {
        if self.region_at(moria).is_none() {
            return false;
        }
        self.events.retain(|event| {
            !matches!(
                &event.kind,
                TuningEventKind::GenikiModulator(ModulatorRule { degree, .. })
                    if *degree == drop_degree
            )
        });
        self.push_event(
            moria,
            drop_degree,
            moria,
            drop_degree,
            TuningEventKind::GenikiModulator(ModulatorRule {
                degree: drop_degree,
                shift,
            }),
        );
        true
    }

    fn clear_chroa_at(&mut self, moria: i32) -> bool {
        let Some(idx) = self.regions.iter().position(|r| r.contains(moria)) else {
            return false;
        };
        self.remove_chroa_events(idx);
        true
    }

    fn push_event(
        &mut self,
        drop_moria: i32,
        drop_degree: Degree,
        resolved_anchor_moria: i32,
        resolved_anchor_degree: Degree,
        kind: TuningEventKind,
    ) -> EventId {
        let id = self.next_event_id;
        self.next_event_id += 1;
        self.events.push(TuningEvent {
            id,
            drop_moria,
            drop_degree,
            resolved_anchor_moria,
            resolved_anchor_degree,
            kind,
        });
        id
    }

    fn remove_region_events(&mut self, region_idx: usize) {
        let ids = self.regions[region_idx].active_rules.clone();
        self.regions[region_idx].active_rules.clear();
        self.events.retain(|event| !ids.contains(&event.id));
    }

    fn remove_chroa_events(&mut self, region_idx: usize) {
        let chroa_ids: Vec<EventId> = self.regions[region_idx]
            .active_rules
            .iter()
            .copied()
            .filter(|id| {
                self.events.iter().any(|event| {
                    event.id == *id && matches!(&event.kind, TuningEventKind::ChroaPatch(_))
                })
            })
            .collect();
        let restore_anchor = self.events.iter().rev().find_map(|event| {
            if !chroa_ids.contains(&event.id) {
                return None;
            }
            match &event.kind {
                TuningEventKind::ChroaPatch(rule) if rule.reanchors_region => {
                    Some((rule.prior_anchor_moria, rule.prior_anchor_degree))
                }
                _ => None,
            }
        });
        self.regions[region_idx]
            .active_rules
            .retain(|id| !chroa_ids.contains(id));
        if let Some((anchor_moria, anchor_degree)) = restore_anchor {
            self.regions[region_idx].anchor_moria = anchor_moria;
            self.regions[region_idx].anchor_degree = anchor_degree;
        }
        self.events.retain(|event| !chroa_ids.contains(&event.id));
    }

    fn resolve_pthora_anchor(
        &self,
        region_idx: usize,
        moria: i32,
        drop_degree: Degree,
        new_genus: &Genus,
        target_degree: Degree,
        target_phase: Option<u8>,
    ) -> (i32, Degree) {
        if new_genus.is_chromatic_cycle() {
            let phase = target_phase.unwrap_or(0).min(3);
            if phase == 0 {
                return (moria, target_degree);
            }

            let anchor_degree = drop_degree.shifted_by(-(phase as i32));
            if let Some(anchor_moria) =
                self.related_degree_moria(region_idx, moria, drop_degree, -(phase as i32))
            {
                return (anchor_moria, anchor_degree);
            }

            return (
                moria - Self::generator_offset_to_phase(new_genus, phase),
                anchor_degree,
            );
        }

        // A diatonic Ga pthora dropped onto Zo/Vou uses the same "move the
        // clicked note until the lower interval is 6" behavior as Ajem.
        if matches!(new_genus, Genus::Diatonic)
            && target_degree == Degree::Ga
            && matches!(drop_degree, Degree::Zo | Degree::Vou)
        {
            if let Some(lower) = self.related_degree_moria(region_idx, moria, drop_degree, -1) {
                return (lower + 6, target_degree);
            }
        }

        (moria, target_degree)
    }

    fn generator_offset_to_phase(genus: &Genus, phase: u8) -> i32 {
        let intervals = genus.intervals();
        intervals.iter().take(phase as usize).sum()
    }

    fn resolve_chroa_anchor(
        &self,
        region_idx: usize,
        moria: i32,
        drop_degree: Degree,
        symbol: Shading,
    ) -> (i32, Degree, bool) {
        match symbol {
            Shading::Zygos if drop_degree == Degree::Vou => {
                let anchor = self
                    .related_degree_moria(region_idx, moria, drop_degree, 2)
                    .unwrap_or(moria);
                (anchor, Degree::Di, false)
            }
            Shading::Zygos => (moria, drop_degree, false),
            Shading::Kliton => {
                if drop_degree == Degree::Pa && self.is_spathi_flattened_pa(region_idx, moria) {
                    (moria, Degree::Ni, true)
                } else {
                    (moria, drop_degree, false)
                }
            }
            Shading::Spathi => (moria, drop_degree, false),
            Shading::Enharmonic => {
                let anchor_degree = match drop_degree {
                    Degree::Ga => Degree::Vou,
                    Degree::Ni => Degree::Zo,
                    other => other,
                };
                let anchor_seed = if anchor_degree == drop_degree {
                    moria
                } else {
                    self.moria_for_degree_near(region_idx, moria, anchor_degree)
                        .unwrap_or(moria)
                };
                let anchor_moria = self
                    .related_degree_moria(region_idx, anchor_seed, anchor_degree, -1)
                    .map(|lower| lower + 6)
                    .unwrap_or(anchor_seed);
                (anchor_moria, anchor_degree, false)
            }
        }
    }

    fn is_spathi_flattened_pa(&self, region_idx: usize, moria: i32) -> bool {
        self.regions[region_idx].active_rules.iter().any(|id| {
            self.events.iter().any(|event| {
                event.id == *id
                    && matches!(
                        &event.kind,
                        TuningEventKind::ChroaPatch(ChroaRule {
                            symbol: Shading::Spathi,
                            ..
                        })
                    )
                    && event.resolved_anchor_degree == Degree::Ni
                    && event.resolved_anchor_moria + 4 == moria
            })
        })
    }

    fn related_degree_moria(
        &self,
        region_idx: usize,
        origin_moria: i32,
        origin_degree: Degree,
        rel: i32,
    ) -> Option<i32> {
        let target = origin_degree.shifted_by(rel);
        let cells = self.cells();
        let region = &self.regions[region_idx];
        let candidates = cells
            .into_iter()
            .filter(|cell| {
                cell.region_idx == region_idx
                    && cell.degree == Some(target)
                    && region.contains(cell.moria)
            })
            .map(|cell| cell.moria);
        if rel >= 0 {
            candidates
                .filter(|m| *m >= origin_moria)
                .min_by_key(|m| *m - origin_moria)
        } else {
            candidates
                .filter(|m| *m <= origin_moria)
                .max_by_key(|m| origin_moria - *m)
        }
    }

    fn moria_for_degree_near(
        &self,
        region_idx: usize,
        origin_moria: i32,
        target: Degree,
    ) -> Option<i32> {
        self.cells()
            .into_iter()
            .filter(|cell| cell.region_idx == region_idx && cell.degree == Some(target))
            .map(|cell| cell.moria)
            .min_by_key(|m| (m - origin_moria).abs())
    }

    /// Remove the pthora at `moria` (i.e. remove the region *starting* at
    /// `moria`). Merges the removed region into its left neighbor.
    ///
    /// Returns `false` if no region starts at `moria`, or if the region to
    /// remove is the first region (nothing to merge into).
    ///
    /// The merge absorbs the removed region's span into the left neighbor's
    /// end_moria without changing the neighbor's genus or anchor.
    pub fn remove_pthora(&mut self, moria: i32) -> bool {
        let Some(idx) = self.regions.iter().position(|r| r.start_moria == moria) else {
            return false;
        };
        if idx == 0 {
            return false;
        }
        let removed = self.regions.remove(idx);
        self.regions[idx - 1].end_moria = removed.end_moria;
        true
    }

    /// Materialize the ladder cells in `[low_moria, high_moria)`.
    ///
    /// Every even moria yields a cell. For closed genera, positions matching
    /// the region's rotated scale get `degree: Some(..)` and `enabled: true`;
    /// non-degree slots start disabled. For `EnharmonicGa` regions the
    /// generator is tiled across the span (see `build_generator_map`).
    pub fn cells(&self) -> Vec<Cell> {
        let mut cells = Vec::new();
        for (idx, region) in self.regions.iter().enumerate() {
            let degree_map: HashMap<i32, DegreeCellInfo> = if region.genus.is_closed() {
                self.build_degree_map(region)
            } else {
                self.build_generator_map(region)
            };
            let start = region.start_moria.max(self.low_moria);
            let end = region.end_moria.min(self.high_moria);
            let mut m = align_up(start, CELL_STEP);
            while m < end {
                let degree_info = degree_map.get(&m).copied();
                let degree = degree_info.map(|info| info.degree);
                let geniki_shift = degree.map(|d| self.geniki_shift_for(d)).unwrap_or_default();
                let (accidental, enabled) = self
                    .overrides
                    .get(&m)
                    .map(|ov| (ov.accidental + geniki_shift, ov.enabled))
                    .unwrap_or((geniki_shift, degree.is_some()));
                cells.push(Cell {
                    moria: m,
                    degree,
                    chromatic_phase: degree_info.and_then(|info| info.chromatic_phase),
                    accidental,
                    enabled,
                    region_idx: idx,
                });
                m += CELL_STEP;
            }
        }
        cells.sort_by_key(|c| c.moria);
        cells
    }

    /// Tile the closed genus's degree positions across the region span,
    /// returning a map from absolute moria → degree-cell metadata.
    fn build_degree_map(&self, region: &Region) -> HashMap<i32, DegreeCellInfo> {
        let mut map = HashMap::new();
        let Some(steps) = self.effective_steps_by_degree(region) else {
            return map;
        };

        // Walk upward from the anchor, including repeated octaves.
        let mut m = region.anchor_moria;
        let mut degree = region.anchor_degree;
        while m < region.end_moria {
            if m >= region.start_moria {
                map.insert(
                    m,
                    DegreeCellInfo {
                        degree,
                        chromatic_phase: None,
                    },
                );
            }
            let step = steps[degree.index()];
            if step <= 0 {
                break;
            }
            m += step;
            degree = degree.shifted_by(1);
        }

        // Walk downward from the anchor so cells below the drop are also
        // reinterpreted by the active genus/patches.
        let mut m = region.anchor_moria;
        let mut degree = region.anchor_degree;
        loop {
            let prev = degree.shifted_by(-1);
            let step = steps[prev.index()];
            if step <= 0 {
                break;
            }
            m -= step;
            degree = prev;
            if m < region.start_moria {
                break;
            }
            if m < region.end_moria {
                map.insert(
                    m,
                    DegreeCellInfo {
                        degree,
                        chromatic_phase: None,
                    },
                );
            }
        }
        map
    }

    /// Tile a generator interval sequence across the region span.
    ///
    /// For soft/hard chromatic regions, the generator is the four-step
    /// chromatic phase cycle. The phase is stored alongside the degree name so
    /// the UI can distinguish, for example, a phase-1 Pa from a phase-3 Pa.
    ///
    /// Non-generator even-moria positions fall in the map as `None` (not
    /// inserted) so the caller marks them disabled.
    fn build_generator_map(&self, region: &Region) -> HashMap<i32, DegreeCellInfo> {
        let generator = region.genus.intervals();
        let mut map = HashMap::new();
        let mut m = region.anchor_moria;
        let mut degree = region.anchor_degree;
        let mut phase_idx: i32 = 0;
        let phase_len = if region.genus.is_chromatic_cycle() {
            Some(generator.len() as i32)
        } else {
            None
        };
        while m < region.end_moria {
            if m >= region.start_moria {
                map.insert(
                    m,
                    DegreeCellInfo {
                        degree,
                        chromatic_phase: phase_len.map(|len| phase_idx.rem_euclid(len) as u8),
                    },
                );
            }
            // Advance to the next generator step, cycling through the
            // generator slice.
            let gen_step = generator[phase_idx.rem_euclid(generator.len() as i32) as usize];
            m += gen_step;
            degree = degree.shifted_by(1);
            phase_idx += 1;
        }

        let mut m = region.anchor_moria;
        let mut degree = region.anchor_degree;
        let mut phase_idx: i32 = 0;
        loop {
            phase_idx -= 1;
            let prev = degree.shifted_by(-1);
            let gen_step = generator[phase_idx.rem_euclid(generator.len() as i32) as usize];
            m -= gen_step;
            degree = prev;
            if m < region.start_moria {
                break;
            }
            if m < region.end_moria {
                map.insert(
                    m,
                    DegreeCellInfo {
                        degree,
                        chromatic_phase: phase_len.map(|len| phase_idx.rem_euclid(len) as u8),
                    },
                );
            }
        }
        map
    }

    fn effective_steps_by_degree(&self, region: &Region) -> Option<[i32; NUM_DEGREES]> {
        let mut steps = region.base_steps_by_degree()?;
        for event_id in &region.active_rules {
            let Some(event) = self.events.iter().find(|event| event.id == *event_id) else {
                continue;
            };
            let TuningEventKind::ChroaPatch(rule) = &event.kind else {
                continue;
            };
            Self::apply_chroa_patch(&mut steps, rule.symbol, event.resolved_anchor_degree);
        }
        Some(steps)
    }

    fn apply_chroa_patch(steps: &mut [i32; NUM_DEGREES], symbol: Shading, anchor: Degree) {
        match symbol {
            Shading::Zygos => {
                steps[anchor.shifted_by(-4).index()] = 18;
                steps[anchor.shifted_by(-3).index()] = 4;
                steps[anchor.shifted_by(-2).index()] = 16;
                steps[anchor.shifted_by(-1).index()] = 4;
            }
            Shading::Kliton => {
                steps[anchor.shifted_by(-3).index()] = 14;
                steps[anchor.shifted_by(-2).index()] = 12;
                steps[anchor.shifted_by(-1).index()] = 4;
            }
            Shading::Spathi => {
                let below = anchor.shifted_by(-1);
                let above = anchor;
                let outer_below = anchor.shifted_by(-2);
                let outer_above = anchor.shifted_by(1);
                let old_below = steps[below.index()];
                let old_above = steps[above.index()];
                steps[below.index()] = 4;
                steps[above.index()] = 4;
                steps[outer_below.index()] += old_below - 4;
                steps[outer_above.index()] += old_above - 4;
            }
            Shading::Enharmonic => {
                let below = anchor.shifted_by(-1);
                let old_below = steps[below.index()];
                steps[below.index()] = 6;
                steps[anchor.index()] += old_below - 6;
            }
        }
    }

    fn geniki_shift_for(&self, degree: Degree) -> i32 {
        self.events
            .iter()
            .filter_map(|event| match &event.kind {
                TuningEventKind::GenikiModulator(ModulatorRule { degree: d, shift })
                    if *d == degree =>
                {
                    Some(*shift)
                }
                _ => None,
            })
            .sum()
    }
}

impl Default for TuningGrid {
    fn default() -> Self {
        Self::new_default()
    }
}

impl TuningGrid {
    /// Build the period table sent to both worklets on every grid change.
    ///
    /// Returns a vec of `(period_24_8, cell_id)` pairs sorted ascending by
    /// period (= descending by frequency), containing only enabled cells.
    /// `period_24_8` is a 24.8 fixed-point sample count:
    ///   `floor((sample_rate / cell_hz) * 256)`
    /// matching the `setKeyTuning` / `tuning_table` spec in `ARCHITECTURE.md §3.7`.
    pub fn tuning_table(&self, sample_rate: f32) -> Vec<(u32, i32)> {
        let cells = self.cells();
        let mut table: Vec<(u32, i32)> = cells
            .iter()
            .filter(|c| c.enabled)
            .map(|c| {
                let hz = moria_to_hz(self.ref_ni_hz, c.effective_moria());
                let period = ((sample_rate as f64 / hz) * 256.0).round() as u32;
                (period, c.moria)
            })
            .collect();
        table.sort_by_key(|(p, _)| *p);
        table
    }
}

/// Result of a nearest-cell lookup.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct NearestCellResult {
    /// Moria index of the primary (best-matching) enabled cell.
    pub primary_id: i32,
    /// Moria index of the adjacent neighbor cell (for half-lit UI feedback),
    /// or `None` if there is only one enabled cell.
    pub neighbor_id: Option<i32>,
    /// Proportional velocity 0.0..1.0 for the neighbor; see `processPeriod` in
    /// the voice detector's nearest-neighbor UI feedback.
    pub neighbor_vel: f32,
}

/// Find the nearest enabled cell to `period_24_8`, applying `last_cell_id`
/// hysteresis (halves the distance to the previously held cell).
///
/// `sorted_table` must be the output of `TuningGrid::tuning_table` (sorted
/// ascending by period). Returns `None` only if the table is empty.
///
/// Period-sorted nearest-cell index for voice detection.
pub fn nearest_enabled_cell(
    sorted_table: &[(u32, i32)],
    period_24_8: u32,
    last_cell_id: Option<i32>,
) -> Option<NearestCellResult> {
    let n = sorted_table.len();
    if n == 0 {
        return None;
    }

    // Binary search: first entry with period > period_24_8.
    let pos = sorted_table.partition_point(|(p, _)| *p <= period_24_8);

    let primary_idx = if pos == 0 {
        0
    } else if pos == n {
        n - 1
    } else {
        let below = &sorted_table[pos - 1];
        let above = &sorted_table[pos];
        let mut dist_below = period_24_8 - below.0;
        let mut dist_above = above.0 - period_24_8;
        // Hysteresis: halve distance to the currently held cell.
        if let Some(last) = last_cell_id {
            if below.1 == last {
                dist_below >>= 1;
            }
            if above.1 == last {
                dist_above >>= 1;
            }
        }
        // Ties go to the above entry, matching C++ `if (a1 < a2) key = i1; else key = i2`.
        if dist_below < dist_above {
            pos - 1
        } else {
            pos
        }
    };

    let primary_id = sorted_table[primary_idx].1;
    let primary_period = sorted_table[primary_idx].0;

    // Find neighbor: the other adjacent cell in the sorted table.
    // Neighbor-cell velocity calculation for half-lit adjacent UI feedback.
    let (neighbor_id, neighbor_vel) = if n > 1 {
        let below_nb = if primary_idx > 0 {
            Some(sorted_table[primary_idx - 1])
        } else {
            None
        };
        let above_nb = if primary_idx + 1 < n {
            Some(sorted_table[primary_idx + 1])
        } else {
            None
        };

        match (below_nb, above_nb) {
            (Some(below), Some(above)) => {
                // a2 = distance from actual period to below-primary neighbor.
                // a3 = distance from above-primary neighbor to actual period.
                let a2 = period_24_8.saturating_sub(below.0);
                let a3 = above.0.saturating_sub(period_24_8);
                let total = a2 + a3;
                if total > 0 {
                    // The closer neighbor gets higher velocity (matches C++ formula).
                    if a2 <= a3 {
                        let vel = (a3 as f32 / total as f32).min(1.0);
                        (Some(below.1), vel)
                    } else {
                        let vel = (a2 as f32 / total as f32).min(1.0);
                        (Some(above.1), vel)
                    }
                } else {
                    (Some(below.1), 0.5)
                }
            }
            (Some(b), None) => {
                let dist = primary_period.saturating_sub(b.0);
                let total = period_24_8.abs_diff(b.0) + dist;
                let vel = if total > 0 {
                    period_24_8.abs_diff(b.0) as f32 / total as f32
                } else {
                    0.5
                };
                (Some(b.1), vel.min(1.0))
            }
            (None, Some(a)) => {
                let dist = a.0.saturating_sub(primary_period);
                let total = period_24_8.abs_diff(a.0) + dist;
                let vel = if total > 0 {
                    period_24_8.abs_diff(a.0) as f32 / total as f32
                } else {
                    0.5
                };
                (Some(a.1), vel.min(1.0))
            }
            (None, None) => (None, 0.0),
        }
    } else {
        (None, 0.0)
    };

    Some(NearestCellResult {
        primary_id,
        neighbor_id,
        neighbor_vel,
    })
}

/// Largest multiple of `m` ≤ `n`. `m` must be positive.
fn floor_to_multiple(n: i32, m: i32) -> i32 {
    n.div_euclid(m) * m
}

/// Smallest multiple of `m` ≥ `n`. `m` must be positive.
fn ceil_to_multiple(n: i32, m: i32) -> i32 {
    let q = n.div_euclid(m);
    let r = n.rem_euclid(m);
    if r == 0 {
        q * m
    } else {
        (q + 1) * m
    }
}

/// Smallest multiple of `step` ≥ `n`. `step` must be positive.
fn align_up(n: i32, step: i32) -> i32 {
    ceil_to_multiple(n, step)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tuning::Shading;

    #[test]
    fn moria_to_hz_at_zero_is_reference() {
        assert!((moria_to_hz(261.63, 0) - 261.63).abs() < 1e-9);
    }

    #[test]
    fn moria_to_hz_doubles_per_octave() {
        assert!((moria_to_hz(261.63, 72) - 523.26).abs() < 1e-6);
        assert!((moria_to_hz(261.63, -72) - 130.815).abs() < 1e-6);
        assert!((moria_to_hz(261.63, 144) - 1046.52).abs() < 1e-5);
    }

    #[test]
    fn moria_to_hz_matches_equal_temperament_on_72_per_octave() {
        // 72 moria per octave ⇒ 2^(m/72). Compare against exponential.
        let f0 = 440.0;
        for m in [-108, -36, 0, 36, 72, 108] {
            let expected = f0 * 2.0_f64.powf(m as f64 / 72.0);
            let got = moria_to_hz(f0, m);
            assert!((got - expected).abs() < 1e-9, "moria={}", m);
        }
    }

    #[test]
    fn floor_and_ceil_to_multiple() {
        assert_eq!(floor_to_multiple(-108, 72), -144);
        assert_eq!(floor_to_multiple(0, 72), 0);
        assert_eq!(floor_to_multiple(71, 72), 0);
        assert_eq!(floor_to_multiple(72, 72), 72);
        assert_eq!(floor_to_multiple(73, 72), 72);

        assert_eq!(ceil_to_multiple(108, 72), 144);
        assert_eq!(ceil_to_multiple(0, 72), 0);
        assert_eq!(ceil_to_multiple(1, 72), 72);
        assert_eq!(ceil_to_multiple(72, 72), 72);
        assert_eq!(ceil_to_multiple(-108, 72), -72);
    }

    #[test]
    fn default_grid_single_region_snapped_to_octave_boundaries() {
        let g = TuningGrid::new_default();
        assert_eq!(g.regions().len(), 1);
        let r = &g.regions()[0];
        assert_eq!(r.start_moria, -72);
        assert_eq!(r.end_moria, 216);
        assert_eq!(r.genus, Genus::Diatonic);
        assert_eq!(r.anchor_moria, -72);
        assert_eq!(r.anchor_degree, Degree::Ni);
        assert!(r.active_rules.is_empty());
    }

    /// Default grid has cells at every even moria in [-72, 146).
    #[test]
    fn default_grid_cell_count() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        let expected = (146 - (-72)) / 2;
        assert_eq!(cells.len(), expected as usize);
        assert_eq!(cells.first().unwrap().moria, -72);
        assert_eq!(cells.last().unwrap().moria, 144);
    }

    /// Ni appears at every multiple of 72 inside the visible range.
    #[test]
    fn default_grid_ni_positions() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        let ni_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.degree == Some(Degree::Ni))
            .map(|c| c.moria)
            .collect();
        assert_eq!(ni_moria, vec![-72, 0, 72, 144]);
    }

    /// All seven degrees appear in each octave of the visible range,
    /// with the canonical Ni-indexed cumulatives.
    #[test]
    fn default_grid_degrees_match_reference() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        // Expected degree positions in the [0, 72) octave.
        let expected: &[(i32, Degree)] = &[
            (0, Degree::Ni),
            (12, Degree::Pa),
            (22, Degree::Vou),
            (30, Degree::Ga),
            (42, Degree::Di),
            (54, Degree::Ke),
            (64, Degree::Zo),
        ];
        for (m, d) in expected {
            let cell = cells.iter().find(|c| c.moria == *m).expect("cell at moria");
            assert_eq!(cell.degree, Some(*d), "moria {}", m);
            assert!(cell.enabled, "degree cell at moria {} must be enabled", m);
        }
    }

    /// Non-degree cells start disabled.
    #[test]
    fn non_degree_cells_start_disabled() {
        let g = TuningGrid::new_default();
        for cell in g.cells() {
            if cell.degree.is_none() {
                assert!(
                    !cell.enabled,
                    "non-degree cell at {} should be disabled",
                    cell.moria
                );
            }
        }
    }

    /// Cells are sorted and unique.
    #[test]
    fn cells_are_sorted_and_unique() {
        let g = TuningGrid::new_default();
        let cells = g.cells();
        for pair in cells.windows(2) {
            assert!(pair[0].moria < pair[1].moria);
        }
    }

    /// All cells point to region 0 in a single-region grid.
    #[test]
    fn cells_reference_correct_region() {
        let g = TuningGrid::new_default();
        for cell in g.cells() {
            assert_eq!(cell.region_idx, 0);
        }
    }

    /// A HardChromatic preset rooted at Pa produces Pa at moria 0 because
    /// the region start snaps to a multiple of 72 and the genus is
    /// identity-rotated when rooted at its canonical root.
    #[test]
    fn hard_chromatic_preset_places_pa_at_octave_multiples() {
        let g = TuningGrid::with_preset(261.63, -72, 72, Genus::HardChromatic, Degree::Pa);
        let cells = g.cells();
        let pa_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.degree == Some(Degree::Pa))
            .map(|c| c.moria)
            .collect();
        // start_moria snaps to -72 (multiple of 72). Pa sits at -72, 0.
        assert_eq!(pa_moria, vec![-72, 0]);
    }

    #[test]
    fn region_at_finds_containing_region() {
        let g = TuningGrid::new_default();
        let (idx, r) = g.region_at(0).expect("region at 0");
        assert_eq!(idx, 0);
        assert_eq!(r.start_moria, -72);
        assert!(g.region_at(216).is_none());
    }

    // ── EnharmonicGa tiling tests ──────────────────────────────────────────

    fn enharmonic_ga_grid(low: i32, high: i32) -> TuningGrid {
        // Build directly since with_preset refuses open genera.
        let start = floor_to_multiple(low, OCTAVE_MORIA);
        let end = ceil_to_multiple(high, OCTAVE_MORIA);
        TuningGrid {
            ref_ni_hz: DEFAULT_REF_NI_HZ,
            low_moria: low,
            high_moria: high,
            regions: vec![Region::new(
                start,
                end,
                Genus::EnharmonicGa,
                start,
                Degree::Ga,
            )],
            events: Vec::new(),
            next_event_id: 1,
            overrides: HashMap::new(),
        }
    }

    /// Generator steps from Ga land at 0, 6, 18, 30 (=30 moria / tetrachord).
    #[test]
    fn enharmonic_ga_first_tetrachord_positions() {
        let g = enharmonic_ga_grid(0, 72);
        let cells = g.cells();
        let enabled_moria: Vec<i32> = cells
            .iter()
            .filter(|c| c.enabled)
            .map(|c| c.moria)
            .collect();
        // From start_moria=0 (snapped from low_moria=0), generator:
        // 0 (Ga), +6=6, +12=18, +12=30, +6=36, +12=48, +12=60, +6=66 (exits at 72)
        assert_eq!(enabled_moria, vec![0, 6, 18, 30, 36, 48, 60, 66]);
    }

    /// Enabled cells form the 6·12·12 tiling pattern.
    #[test]
    fn enharmonic_ga_tiling_pattern() {
        let g = enharmonic_ga_grid(0, 72);
        let enabled: Vec<i32> = g
            .cells()
            .iter()
            .filter(|c| c.enabled)
            .map(|c| c.moria)
            .collect();
        let diffs: Vec<i32> = enabled.windows(2).map(|w| w[1] - w[0]).collect();
        // Generator [6,12,12] cycling: 6,12,12, 6,12,12, 6,12 (before 72 ends it)
        assert_eq!(diffs, vec![6, 12, 12, 6, 12, 12, 6]);
    }

    /// Non-generator cells (between generator positions) are disabled.
    #[test]
    fn enharmonic_ga_non_generator_cells_disabled() {
        let g = enharmonic_ga_grid(0, 72);
        let cells = g.cells();
        // All cells exist at 2-moria granularity; only generator positions enabled.
        assert_eq!(cells.len(), 36); // (72-0)/2
        for cell in &cells {
            if [0, 6, 18, 30, 36, 48, 60, 66].contains(&cell.moria) {
                assert!(
                    cell.enabled,
                    "generator pos {} should be enabled",
                    cell.moria
                );
                assert!(
                    cell.degree.is_some(),
                    "generator pos {} should have degree",
                    cell.moria
                );
            } else {
                assert!(!cell.enabled, "gap pos {} should be disabled", cell.moria);
                assert!(
                    cell.degree.is_none(),
                    "gap pos {} should have no degree",
                    cell.moria
                );
            }
        }
    }

    /// Root Ga sits at start_moria; the degree sequence cycles from Ga.
    #[test]
    fn enharmonic_ga_degree_sequence_from_ga() {
        let g = enharmonic_ga_grid(0, 72);
        let degree_cells: Vec<(i32, Degree)> = g
            .cells()
            .into_iter()
            .filter(|c| c.degree.is_some())
            .map(|c| (c.moria, c.degree.unwrap()))
            .collect();
        // Sequential cycling from Ga: Ga, Di, Ke, Zo, Ni, Pa, Vou, Ga (wraps).
        let expected = vec![
            (0, Degree::Ga),
            (6, Degree::Di),
            (18, Degree::Ke),
            (30, Degree::Zo),
            (36, Degree::Ni),
            (48, Degree::Pa),
            (60, Degree::Vou),
            (66, Degree::Ga),
        ];
        assert_eq!(degree_cells, expected);
    }

    // ── Pthora application tests ───────────────────────────────────────────

    /// Applying a pthora mid-region reanchors the containing region without
    /// turning the drop point into a boundary.
    #[test]
    fn apply_pthora_reanchors_existing_region() {
        let mut g = TuningGrid::new_default();
        assert_eq!(g.regions().len(), 1);
        // Drop HardChromatic from Pa at moria=30 (where Ga sits in Diatonic).
        let ok = g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
        assert!(ok);
        assert_eq!(g.regions().len(), 1);
        let r = &g.regions()[0];
        assert_eq!(r.genus, Genus::HardChromatic);
        assert_eq!(r.anchor_moria, 30);
        assert_eq!(r.anchor_degree, Degree::Pa);
        assert_eq!(r.start_moria, -72);
        assert_eq!(r.end_moria, 216);
        assert_eq!(g.events().len(), 1);
    }

    /// Applying at a region's own start_moria still replaces that region's
    /// genus/anchor in-place.
    #[test]
    fn apply_pthora_at_start_moria_replaces() {
        let mut g = TuningGrid::new_default();
        let original_start = g.regions()[0].start_moria;
        g.apply_pthora(original_start, Genus::SoftChromatic, Degree::Ni);
        assert_eq!(g.regions().len(), 1);
        assert_eq!(g.regions()[0].genus, Genus::SoftChromatic);
        assert_eq!(g.regions()[0].start_moria, original_start);
    }

    /// Applying a second pthora in the same region reanchors that region again.
    #[test]
    fn apply_pthora_twice_keeps_one_region() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(0, Genus::HardChromatic, Degree::Pa);
        g.apply_pthora(42, Genus::SoftChromatic, Degree::Ni);
        assert_eq!(g.regions().len(), 1);
        let r = &g.regions()[0];
        assert_eq!(r.anchor_moria, 42);
        assert_eq!(r.anchor_degree, Degree::Ni);
        assert_eq!(r.genus, Genus::SoftChromatic);
    }

    /// `apply_pthora` returns false when moria is outside any region.
    #[test]
    fn apply_pthora_outside_region_returns_false() {
        let mut g = TuningGrid::new_default();
        let out_of_range = g.regions()[0].end_moria + 10;
        assert!(!g.apply_pthora(out_of_range, Genus::Diatonic, Degree::Ni));
        assert_eq!(g.regions().len(), 1);
    }

    /// remove_pthora on the first region (nothing to merge into) returns false.
    #[test]
    fn remove_pthora_on_first_region_returns_false() {
        let mut g = TuningGrid::new_default();
        let first_start = g.regions()[0].start_moria;
        assert!(!g.remove_pthora(first_start));
        assert_eq!(g.regions().len(), 1);
    }

    /// remove_pthora returns false if no region starts at moria.
    #[test]
    fn remove_pthora_no_region_at_moria_returns_false() {
        let mut g = TuningGrid::new_default();
        assert!(!g.remove_pthora(99));
    }

    /// Cells below and above the pthora anchor follow the new genus.
    #[test]
    fn pthora_bidirectional() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(42, Genus::HardChromatic, Degree::Pa);
        let cells = g.cells();

        let below = cells.iter().find(|c| c.moria == 30).unwrap();
        assert_eq!(below.degree, Some(Degree::Ni));
        assert_eq!(below.region_idx, 0);
        assert_eq!(below.chromatic_phase, Some(3));

        let anchor = cells.iter().find(|c| c.moria == 42).unwrap();
        assert_eq!(anchor.degree, Some(Degree::Pa));
        assert_eq!(anchor.chromatic_phase, Some(0));

        let above = cells.iter().find(|c| c.moria == 48).unwrap();
        assert_eq!(above.degree, Some(Degree::Vou));
        assert_eq!(above.chromatic_phase, Some(1));
    }

    #[test]
    fn cells_walk_upward_and_downward_from_anchor() {
        let g = TuningGrid {
            ref_ni_hz: DEFAULT_REF_NI_HZ,
            low_moria: -36,
            high_moria: 36,
            regions: vec![Region::new(-36, 72, Genus::Diatonic, 0, Degree::Ni)],
            events: Vec::new(),
            next_event_id: 1,
            overrides: HashMap::new(),
        };
        let cells = g.cells();
        assert_eq!(
            cells.iter().find(|c| c.moria == -30).unwrap().degree,
            Some(Degree::Di)
        );
        assert_eq!(
            cells.iter().find(|c| c.moria == -8).unwrap().degree,
            Some(Degree::Zo)
        );
        assert_eq!(
            cells.iter().find(|c| c.moria == 12).unwrap().degree,
            Some(Degree::Pa)
        );
    }

    /// Pthora repainting only touches the containing pre-existing region.
    #[test]
    fn pthora_preserves_adjacent_regions() {
        let mut g = TuningGrid {
            ref_ni_hz: DEFAULT_REF_NI_HZ,
            low_moria: -72,
            high_moria: 72,
            regions: vec![
                Region::new(-144, 0, Genus::Diatonic, -144, Degree::Ni),
                Region::new(0, 144, Genus::Diatonic, 0, Degree::Ni),
            ],
            events: Vec::new(),
            next_event_id: 1,
            overrides: HashMap::new(),
        };
        g.apply_pthora(42, Genus::HardChromatic, Degree::Pa);
        assert_eq!(g.regions().len(), 2);
        assert_eq!(g.regions()[0].genus, Genus::Diatonic);
        assert_eq!(g.regions()[0].anchor_moria, -144);
        assert_eq!(g.regions()[1].genus, Genus::HardChromatic);
        assert_eq!(g.regions()[1].anchor_moria, 42);
    }

    // ── Shading tests ──────────────────────────────────────────────────────

    /// Zygos on Di: the four intervals *below* Di change to [18,4,16,4].
    /// Di stays at 42; intervals above Di (→Ke, →Zo) are unchanged.
    #[test]
    fn zygos_shading_shifts_degrees_correctly() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(42, Some(Shading::Zygos));
        let cells = g.cells();
        let degree_cells: Vec<(i32, Degree)> = cells
            .iter()
            .filter(|c| c.degree.is_some())
            .map(|c| (c.moria, c.degree.unwrap()))
            .collect();
        // iv = [18,4,16,4,12,10,8]: Pa=18, Vou=22, Ga=38, Di=42, Ke=54, Zo=64.
        let expected = vec![
            (0, Degree::Ni),
            (18, Degree::Pa),
            (22, Degree::Vou),
            (38, Degree::Ga),
            (42, Degree::Di),
            (54, Degree::Ke),
            (64, Degree::Zo),
        ];
        assert_eq!(degree_cells, expected);
    }

    /// Zygos dropped on Vou resolves to the corresponding Di anchor.
    #[test]
    fn zygos_on_vou_resolves_to_di() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_symbol_drop(SymbolDrop::Chroa {
            drop_moria: 22,
            drop_degree: Degree::Vou,
            symbol: Shading::Zygos,
        });
        let event = g.events().last().unwrap();
        assert_eq!(event.resolved_anchor_degree, Degree::Di);
        assert_eq!(event.resolved_anchor_moria, 42);
        let ga = g.cells().into_iter().find(|c| c.moria == 38).unwrap();
        assert_eq!(ga.degree, Some(Degree::Ga));
    }

    /// Spathi on Ke: Di→Ke=4 and Ke→Zo=4.
    #[test]
    fn spathi_ke_recalculates_adjacent_intervals() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(54, Some(Shading::Spathi));
        let degree_cells: Vec<(i32, Degree)> = g
            .cells()
            .into_iter()
            .filter_map(|c| c.degree.map(|d| (c.moria, d)))
            .collect();
        assert_eq!(
            degree_cells,
            vec![
                (0, Degree::Ni),
                (12, Degree::Pa),
                (22, Degree::Vou),
                (30, Degree::Ga),
                (50, Degree::Di),
                (54, Degree::Ke),
                (58, Degree::Zo),
            ]
        );
    }

    /// Spathi on Ni flattens Pa above Ni so Ni→Pa=4.
    #[test]
    fn spathi_on_ni_flattens_pa() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Spathi));
        let cells = g.cells();
        let ni = cells.iter().find(|c| c.degree == Some(Degree::Ni)).unwrap();
        let pa = cells.iter().find(|c| c.degree == Some(Degree::Pa)).unwrap();
        assert_eq!(pa.moria - ni.moria, 4);
    }

    #[test]
    fn kliton_on_effective_new_ni() {
        let mut g = TuningGrid::with_preset(261.63, -72, 80, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Spathi));
        g.apply_shading(4, Some(Shading::Kliton));

        let r = &g.regions()[0];
        assert_eq!(r.anchor_moria, 4);
        assert_eq!(r.anchor_degree, Degree::Ni);

        let cells = g.cells();
        assert_eq!(
            cells.iter().find(|c| c.moria == 0).unwrap().degree,
            Some(Degree::Zo)
        );
        assert_eq!(
            cells.iter().find(|c| c.moria == 4).unwrap().degree,
            Some(Degree::Ni)
        );
        assert_eq!(
            cells.iter().find(|c| c.moria == 16).unwrap().degree,
            Some(Degree::Pa)
        );
    }

    #[test]
    fn clearing_reanchoring_chroa_restores_prior_anchor() {
        let mut g = TuningGrid::with_preset(261.63, -72, 80, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Spathi));
        g.apply_shading(4, Some(Shading::Kliton));
        assert_eq!(g.regions()[0].anchor_moria, 4);

        g.apply_shading(4, None);
        assert_eq!(g.regions()[0].anchor_moria, -72);
        assert_eq!(g.regions()[0].anchor_degree, Degree::Ni);
    }

    #[test]
    fn kliton_on_ni_intervals() {
        let mut g = TuningGrid::with_preset(261.63, 0, 144, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Kliton));
        let cells = g.cells();
        let di = cells.iter().find(|c| c.degree == Some(Degree::Di)).unwrap();
        let ke = cells.iter().find(|c| c.degree == Some(Degree::Ke)).unwrap();
        let zo = cells.iter().find(|c| c.degree == Some(Degree::Zo)).unwrap();
        let ni_hi = cells
            .iter()
            .filter(|c| c.degree == Some(Degree::Ni))
            .max_by_key(|c| c.moria)
            .unwrap();
        assert_eq!(ke.moria - di.moria, 14);
        assert_eq!(zo.moria - ke.moria, 12);
        assert_eq!(ni_hi.moria - zo.moria, 4);
    }

    #[test]
    fn kliton_on_di_and_ga_intervals() {
        let mut on_di = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        on_di.apply_shading(42, Some(Shading::Kliton));
        let cells = on_di.cells();
        let pa = cells.iter().find(|c| c.degree == Some(Degree::Pa)).unwrap();
        let vou = cells
            .iter()
            .find(|c| c.degree == Some(Degree::Vou))
            .unwrap();
        let ga = cells.iter().find(|c| c.degree == Some(Degree::Ga)).unwrap();
        let di = cells.iter().find(|c| c.degree == Some(Degree::Di)).unwrap();
        assert_eq!(vou.moria - pa.moria, 14);
        assert_eq!(ga.moria - vou.moria, 12);
        assert_eq!(di.moria - ga.moria, 4);

        let mut on_ga = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        on_ga.apply_shading(30, Some(Shading::Kliton));
        let cells = on_ga.cells();
        let ni = cells.iter().find(|c| c.degree == Some(Degree::Ni)).unwrap();
        let pa = cells.iter().find(|c| c.degree == Some(Degree::Pa)).unwrap();
        let vou = cells
            .iter()
            .find(|c| c.degree == Some(Degree::Vou))
            .unwrap();
        let ga = cells.iter().find(|c| c.degree == Some(Degree::Ga)).unwrap();
        assert_eq!(pa.moria - ni.moria, 14);
        assert_eq!(vou.moria - pa.moria, 12);
        assert_eq!(ga.moria - vou.moria, 4);
    }

    #[test]
    fn ajem_on_zo_moves_dropped_note() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(64, Some(Shading::Enharmonic));
        let cells = g.cells();
        let ke = cells.iter().find(|c| c.degree == Some(Degree::Ke)).unwrap();
        let zo = cells.iter().find(|c| c.degree == Some(Degree::Zo)).unwrap();
        assert_eq!(zo.moria - ke.moria, 6);
    }

    #[test]
    fn ajem_on_vou_moves_dropped_note() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(22, Some(Shading::Enharmonic));
        let cells = g.cells();
        let pa = cells.iter().find(|c| c.degree == Some(Degree::Pa)).unwrap();
        let vou = cells
            .iter()
            .find(|c| c.degree == Some(Degree::Vou))
            .unwrap();
        assert_eq!(vou.moria - pa.moria, 6);
    }

    #[test]
    fn soft_chromatic_phase_one_on_ke_moves_drop() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_symbol_drop(SymbolDrop::Pthora {
            drop_moria: 54,
            drop_degree: Degree::Ke,
            genus: Genus::SoftChromatic,
            target_degree: Degree::Ke,
            target_phase: Some(1),
        });
        let r = &g.regions()[0];
        assert_eq!(r.anchor_moria, 42);
        assert_eq!(r.anchor_degree, Degree::Di);

        let cells = g.cells();
        let di = cells.iter().find(|c| c.moria == 42).unwrap();
        assert_eq!(di.degree, Some(Degree::Di));
        assert_eq!(di.chromatic_phase, Some(0));
        let ke = cells.iter().find(|c| c.moria == 50).unwrap();
        assert_eq!(ke.degree, Some(Degree::Ke));
        assert_eq!(ke.chromatic_phase, Some(1));
        assert_eq!(cells.iter().find(|c| c.moria == 54).unwrap().degree, None);
    }

    #[test]
    fn soft_chromatic_phase_cycle_repeats_by_four_degrees() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(0, Genus::SoftChromatic, Degree::Ni);
        let cells = g.cells();
        let cases = [
            (0, Degree::Ni, 0),
            (8, Degree::Pa, 1),
            (22, Degree::Vou, 2),
            (30, Degree::Ga, 3),
            (42, Degree::Di, 0),
            (50, Degree::Ke, 1),
            (64, Degree::Zo, 2),
            (72, Degree::Ni, 3),
            (84, Degree::Pa, 0),
        ];
        for (moria, degree, phase) in cases {
            let cell = cells.iter().find(|c| c.moria == moria).unwrap();
            assert_eq!(cell.degree, Some(degree), "moria {moria}");
            assert_eq!(cell.chromatic_phase, Some(phase), "moria {moria}");
        }
    }

    #[test]
    fn hard_chromatic_phase_cycle_places_lower_and_upper_ni_differently() {
        let mut g = TuningGrid::new_default();
        g.apply_pthora(0, Genus::HardChromatic, Degree::Pa);
        let cells = g.cells();
        let cases = [
            (-12, Degree::Ni, 3),
            (0, Degree::Pa, 0),
            (6, Degree::Vou, 1),
            (26, Degree::Ga, 2),
            (30, Degree::Di, 3),
            (42, Degree::Ke, 0),
            (48, Degree::Zo, 1),
            (68, Degree::Ni, 2),
            (72, Degree::Pa, 3),
            (84, Degree::Vou, 0),
        ];
        for (moria, degree, phase) in cases {
            let cell = cells.iter().find(|c| c.moria == moria).unwrap();
            assert_eq!(cell.degree, Some(degree), "moria {moria}");
            assert_eq!(cell.chromatic_phase, Some(phase), "moria {moria}");
        }
    }

    #[test]
    fn diatonic_ga_pthora_on_vou_moves_drop() {
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_symbol_drop(SymbolDrop::Pthora {
            drop_moria: 22,
            drop_degree: Degree::Vou,
            genus: Genus::Diatonic,
            target_degree: Degree::Ga,
            target_phase: None,
        });
        let r = &g.regions()[0];
        assert_eq!(r.anchor_moria, 18);
        assert_eq!(r.anchor_degree, Degree::Ga);

        let cells = g.cells();
        assert_eq!(
            cells.iter().find(|c| c.moria == 18).unwrap().degree,
            Some(Degree::Ga)
        );
        assert_eq!(cells.iter().find(|c| c.moria == 22).unwrap().degree, None);
    }

    #[test]
    fn diesis_geniki_raises_every_occurrence_without_overwriting_manual() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(64, 2);
        g.apply_symbol_drop(SymbolDrop::Geniki {
            drop_moria: 64,
            drop_degree: Degree::Zo,
            shift: 6,
        });
        let zo_cells: Vec<Cell> = g
            .cells()
            .into_iter()
            .filter(|c| c.degree == Some(Degree::Zo))
            .collect();
        assert_eq!(zo_cells.len(), 3);
        for cell in zo_cells {
            if cell.moria == 64 {
                assert_eq!(cell.accidental, 8);
            } else {
                assert_eq!(cell.accidental, 6);
            }
        }
    }

    #[test]
    fn yfesis_geniki_lowers_every_occurrence() {
        let mut g = TuningGrid::new_default();
        g.apply_symbol_drop(SymbolDrop::Geniki {
            drop_moria: 64,
            drop_degree: Degree::Zo,
            shift: -6,
        });
        for cell in g
            .cells()
            .into_iter()
            .filter(|c| c.degree == Some(Degree::Zo))
        {
            assert_eq!(cell.accidental, -6);
        }
    }

    /// apply_shading returns false when moria is outside all regions.
    #[test]
    fn apply_shading_outside_region_returns_false() {
        let mut g = TuningGrid::new_default();
        assert!(!g.apply_shading(9999, Some(Shading::Zygos)));
    }

    /// Clearing shading (None) restores the unshaded cells.
    #[test]
    fn clearing_shading_restores_cells() {
        let unshaded = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni).cells();
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(0, Some(Shading::Kliton));
        g.apply_shading(0, None);
        assert_eq!(g.cells(), unshaded);
    }

    #[test]
    fn clearing_shading_does_not_require_degree_cell() {
        let unshaded = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni).cells();
        let mut g = TuningGrid::with_preset(261.63, 0, 72, Genus::Diatonic, Degree::Ni);
        g.apply_shading(22, Some(Shading::Enharmonic));
        assert!(g
            .cells()
            .into_iter()
            .find(|c| c.moria == 22)
            .unwrap()
            .degree
            .is_none());
        assert!(g.apply_shading(22, None));
        assert_eq!(g.cells(), unshaded);
    }

    // ── Accidental / override tests ────────────────────────────────────────

    /// set_accidental changes effective_moria without moving the cell's
    /// nominal moria.
    #[test]
    fn set_accidental_shifts_effective_moria() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(12, 4); // Pa +4 = sharp by 4 moria
        let cells = g.cells();
        let pa = cells.iter().find(|c| c.moria == 12).unwrap();
        assert_eq!(pa.moria, 12);
        assert_eq!(pa.accidental, 4);
        assert_eq!(pa.effective_moria(), 16);
    }

    #[test]
    fn set_accidental_negative() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(22, -6); // Vou flat by 6 moria
        let vou = g.cells().into_iter().find(|c| c.moria == 22).unwrap();
        assert_eq!(vou.accidental, -6);
        assert_eq!(vou.effective_moria(), 16);
    }

    /// Odd accidental panics (Byzantine intervals are always even).
    #[test]
    #[should_panic(expected = "accidental must be an even number of moria")]
    fn set_accidental_odd_panics() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(12, 3);
    }

    /// Large accidentals (beyond ±8) are accepted — the data model is
    /// unbounded as per docs/ARCHITECTURE.md §3.4.
    #[test]
    fn set_accidental_large_value_accepted() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(12, 20);
        let pa = g.cells().into_iter().find(|c| c.moria == 12).unwrap();
        assert_eq!(pa.effective_moria(), 32);
    }

    /// Setting accidental on a non-degree cell (between degrees) is allowed.
    #[test]
    fn set_accidental_on_non_degree_cell() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(4, 2); // moria=4 is a gap between Ni(0) and Pa(12)
        let cell = g.cells().into_iter().find(|c| c.moria == 4).unwrap();
        assert_eq!(cell.accidental, 2);
    }

    /// set_enabled toggles a cell independently of its region default.
    #[test]
    fn set_enabled_overrides_region_default() {
        let mut g = TuningGrid::new_default();
        // Disable a degree cell (Ga at moria 30, enabled by default).
        g.set_enabled(30, false);
        let ga = g.cells().into_iter().find(|c| c.moria == 30).unwrap();
        assert!(!ga.enabled);
        // Enable a non-degree cell (moria=2, disabled by default).
        g.set_enabled(2, true);
        let gap = g.cells().into_iter().find(|c| c.moria == 2).unwrap();
        assert!(gap.enabled);
    }

    /// toggle_cell flips the current state.
    #[test]
    fn toggle_cell_flips_state() {
        let mut g = TuningGrid::new_default();
        // Degree cell starts enabled.
        let new_state = g.toggle_cell(12).unwrap();
        assert!(!new_state);
        let pa = g.cells().into_iter().find(|c| c.moria == 12).unwrap();
        assert!(!pa.enabled);
        // Toggle back.
        g.toggle_cell(12);
        let pa2 = g.cells().into_iter().find(|c| c.moria == 12).unwrap();
        assert!(pa2.enabled);
    }

    /// set_accidental preserves the cell's existing enabled state.
    #[test]
    fn set_accidental_preserves_enabled_state() {
        let mut g = TuningGrid::new_default();
        g.set_enabled(12, false); // disable Pa
        g.set_accidental(12, 4); // then add accidental
        let pa = g.cells().into_iter().find(|c| c.moria == 12).unwrap();
        assert!(!pa.enabled, "enabled state should be preserved");
        assert_eq!(pa.accidental, 4);
    }

    /// clear_override restores the region-derived default.
    #[test]
    fn clear_override_restores_default() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(12, 6);
        g.set_enabled(12, false);
        g.clear_override(12);
        let pa = g.cells().into_iter().find(|c| c.moria == 12).unwrap();
        assert_eq!(pa.accidental, 0);
        assert!(pa.enabled); // degree cell default = enabled
    }

    /// Overrides survive a pthora operation (they're stored by moria key,
    /// independent of the region split).
    #[test]
    fn overrides_survive_pthora() {
        let mut g = TuningGrid::new_default();
        g.set_accidental(42, 4); // Di +4
        g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
        let di = g.cells().into_iter().find(|c| c.moria == 42).unwrap();
        assert_eq!(di.accidental, 4, "accidental should survive pthora");
    }

    // ── Serialization roundtrip tests (require --features serde) ──────────

    #[cfg(feature = "serde")]
    mod serde_tests {
        use super::*;

        #[test]
        fn default_grid_roundtrips_via_json() {
            let original = TuningGrid::new_default();
            let json = original.to_json().expect("serialize");
            let restored = TuningGrid::from_json(&json).expect("deserialize");
            assert_eq!(original, restored);
        }

        #[test]
        fn json_includes_ref_ni_hz_field() {
            let g = TuningGrid::new_default();
            let json = g.to_json().unwrap();
            assert!(json.contains("ref_ni_hz"), "JSON: {json}");
        }

        #[test]
        fn grid_with_pthora_and_overrides_roundtrips() {
            let mut g = TuningGrid::new_default();
            g.apply_pthora(30, Genus::HardChromatic, Degree::Pa);
            g.set_accidental(12, 4);
            g.set_enabled(2, true);
            g.apply_shading(30, Some(Shading::Zygos));

            let json = g.to_json().unwrap();
            let restored = TuningGrid::from_json(&json).unwrap();
            assert_eq!(g, restored);
            // Verify the override round-tripped.
            let pa = restored
                .cells()
                .into_iter()
                .find(|c| c.moria == 12)
                .unwrap();
            assert_eq!(pa.accidental, 4);
        }

        #[test]
        fn cells_after_roundtrip_match_original() {
            let mut g = TuningGrid::new_default();
            g.set_accidental(0, -2);
            g.apply_pthora(42, Genus::SoftChromatic, Degree::Ni);
            let original_cells = g.cells();

            let json = g.to_json().unwrap();
            let restored = TuningGrid::from_json(&json).unwrap();
            assert_eq!(restored.cells(), original_cells);
        }

        #[test]
        fn spathi_legacy_json_roundtrip() {
            let legacy = r#"{
                "ref_ni_hz": 261.63,
                "low_moria": 0,
                "high_moria": 72,
                "regions": [{
                    "start_moria": 0,
                    "end_moria": 72,
                    "genus": "Diatonic",
                    "root_degree": "Ni",
                    "shading": "SpathiKe"
                }],
                "overrides": {}
            }"#;

            let restored = TuningGrid::from_json(legacy).unwrap();
            let event = restored.events().last().unwrap();
            assert_eq!(event.resolved_anchor_degree, Degree::Ke);
            assert!(matches!(
                &event.kind,
                TuningEventKind::ChroaPatch(ChroaRule {
                    symbol: Shading::Spathi,
                    ..
                })
            ));

            let cells = restored.cells();
            assert_eq!(
                cells.iter().find(|c| c.moria == 50).unwrap().degree,
                Some(Degree::Di)
            );
            assert_eq!(
                cells.iter().find(|c| c.moria == 54).unwrap().degree,
                Some(Degree::Ke)
            );

            let json = restored.to_json().unwrap();
            let reparsed = TuningGrid::from_json(&json).unwrap();
            assert_eq!(reparsed, restored);
        }

        #[test]
        fn from_json_rejects_malformed_input() {
            assert!(TuningGrid::from_json("not json").is_err());
            assert!(TuningGrid::from_json("{\"ref_ni_hz\": 261}").is_err());
        }
    }

    // ── nearest_enabled_cell tests ─────────────────────────────────────────

    /// Build a hand-crafted table with three cells at periods 100, 120, 150.
    ///
    /// Plan test: "input period 110 snaps to 100 if last = 100 (hysteresis),
    /// else to 120."
    fn period_table() -> Vec<(u32, i32)> {
        vec![(100 * 256, 0), (120 * 256, 1), (150 * 256, 2)]
    }

    #[test]
    fn nearest_cell_no_hysteresis_picks_closer() {
        let table = period_table();
        // Period 110: equidistant between 100 and 120 → tie goes to 120 (above).
        let r = nearest_enabled_cell(&table, 110 * 256, None).unwrap();
        assert_eq!(r.primary_id, 1, "equidistant snap should pick 120 (above)");
    }

    #[test]
    fn nearest_cell_hysteresis_favors_last_key() {
        let table = period_table();
        // Period 110 + last = 0 (period 100): halved dist = 5 < 10 → picks 100.
        let r = nearest_enabled_cell(&table, 110 * 256, Some(0)).unwrap();
        assert_eq!(r.primary_id, 0, "hysteresis should snap to last cell (100)");
    }

    #[test]
    fn nearest_cell_clearly_closer_without_hysteresis() {
        let table = period_table();
        // Period 105: dist to 100 = 5, dist to 120 = 15 → picks 100.
        let r = nearest_enabled_cell(&table, 105 * 256, None).unwrap();
        assert_eq!(r.primary_id, 0);
    }

    #[test]
    fn nearest_cell_returns_none_on_empty_table() {
        assert!(nearest_enabled_cell(&[], 100 * 256, None).is_none());
    }

    #[test]
    fn nearest_cell_single_entry_always_matches() {
        let table = vec![(200 * 256, 42)];
        let r = nearest_enabled_cell(&table, 100 * 256, None).unwrap();
        assert_eq!(r.primary_id, 42);
        assert!(r.neighbor_id.is_none());
    }

    #[test]
    fn tuning_table_sorted_and_enabled_only() {
        let g = TuningGrid::new_default();
        let table = g.tuning_table(44100.0);
        // Periods should be sorted ascending (= pitches descending).
        for w in table.windows(2) {
            assert!(w[0].0 <= w[1].0, "tuning_table must be sorted by period");
        }
        // Default grid: -72 through +144 includes 22 enabled degree cells.
        assert_eq!(table.len(), 22, "default grid should have 22 enabled cells");
    }
}
