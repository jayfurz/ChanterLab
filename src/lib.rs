//! Byzorgan core — Byzantine tuning engine and DSP primitives.
//!
//! See `docs/ARCHITECTURE.md` for the overall design and
//! `docs/BYZANTINE_SCALES_REFERENCE.md` for the music-theory reference.
//!
//! This file is the main-thread WASM bundle entry point (feature `main`).
//! It exports `JsTuningGrid`, a thin wasm_bindgen wrapper around
//! `TuningGrid` that communicates via JSON strings. No JS-facing type
//! exports are gated here; all core logic lives in `tuning/`.

pub mod tuning;

#[cfg(feature = "main")]
mod main_exports {
    use wasm_bindgen::prelude::*;

    use crate::tuning::{Degree, Genus, Shading, TuningGrid};

    /// WASM-exported handle to a `TuningGrid`.
    ///
    /// All complex return values are JSON strings; the JS caller
    /// `JSON.parse`s them. This avoids the overhead of registering
    /// per-field getters and keeps the boundary thin.
    #[wasm_bindgen]
    pub struct JsTuningGrid {
        inner: TuningGrid,
    }

    #[wasm_bindgen]
    impl JsTuningGrid {
        /// Default grid: Diatonic, Ni root, 261.63 Hz, ±108 moria visible.
        #[wasm_bindgen(constructor)]
        pub fn new() -> JsTuningGrid {
            JsTuningGrid {
                inner: TuningGrid::new_default(),
            }
        }

        /// Serialize the grid state to JSON (for LocalStorage / postMessage).
        #[wasm_bindgen(js_name = toJson)]
        pub fn to_json(&self) -> Result<String, JsValue> {
            self.inner.to_json().map_err(|e| JsValue::from_str(&e.to_string()))
        }

        /// Deserialize a grid previously produced by `toJson`.
        #[wasm_bindgen(js_name = fromJson)]
        pub fn from_json(json: &str) -> Result<JsTuningGrid, JsValue> {
            TuningGrid::from_json(json)
                .map(|inner| JsTuningGrid { inner })
                .map_err(|e| JsValue::from_str(&e.to_string()))
        }

        /// Return all cells in the visible window as a JSON array.
        ///
        /// Each element has the shape:
        /// `{ moria, degree, accidental, effective_moria, enabled, region_idx }`
        #[wasm_bindgen(js_name = cellsJson)]
        pub fn cells_json(&self) -> Result<String, JsValue> {
            let cells = self.inner.cells();
            serde_json::to_string(&cells).map_err(|e| JsValue::from_str(&e.to_string()))
        }

        /// Frequency in Hz at `moria` using the grid's reference Ni.
        #[wasm_bindgen(js_name = moriaToHz)]
        pub fn moria_to_hz(&self, moria: i32) -> f64 {
            self.inner.moria_to_hz(moria)
        }

        /// Reference Ni frequency in Hz.
        #[wasm_bindgen(getter, js_name = refNiHz)]
        pub fn ref_ni_hz(&self) -> f64 {
            self.inner.ref_ni_hz
        }

        /// Set the reference Ni frequency.
        #[wasm_bindgen(setter, js_name = refNiHz)]
        pub fn set_ref_ni_hz(&mut self, hz: f64) {
            self.inner.ref_ni_hz = hz;
        }

        /// Apply a pthora: split the containing region at `moria` and assign
        /// the new `(genus, target_degree)` to the right half.
        ///
        /// `genus` and `target_degree` are the string names used in the
        /// Rust enums (e.g. `"Diatonic"`, `"HardChromatic"`, `"Ni"`, `"Pa"`).
        /// Returns `false` on unknown names or out-of-range moria.
        #[wasm_bindgen(js_name = applyPthora)]
        pub fn apply_pthora(&mut self, moria: i32, genus: &str, target_degree: &str) -> bool {
            let (Some(g), Some(d)) = (parse_genus(genus), parse_degree(target_degree)) else {
                return false;
            };
            self.inner.apply_pthora(moria, g, d)
        }

        /// Remove the pthora whose region starts at `moria`.
        #[wasm_bindgen(js_name = removePthora)]
        pub fn remove_pthora(&mut self, moria: i32) -> bool {
            self.inner.remove_pthora(moria)
        }

        /// Apply or clear a shading on the region containing `moria`.
        ///
        /// `shading` is one of `"Zygos"`, `"Kliton"`, `"SpathiA"`,
        /// `"SpathiB"`, or `null`/`""` to clear. Returns `false` if
        /// `moria` is out of range.
        #[wasm_bindgen(js_name = applyShading)]
        pub fn apply_shading(&mut self, moria: i32, shading: &str) -> bool {
            let s = if shading.is_empty() { None } else { parse_shading(shading) };
            self.inner.apply_shading(moria, s)
        }

        /// Set an even-moria accidental on the cell at `moria`.
        /// Panics in debug if `accidental` is odd.
        #[wasm_bindgen(js_name = setAccidental)]
        pub fn set_accidental(&mut self, moria: i32, accidental: i32) {
            self.inner.set_accidental(moria, accidental);
        }

        /// Explicitly set the enabled state for the cell at `moria`.
        #[wasm_bindgen(js_name = setEnabled)]
        pub fn set_enabled(&mut self, moria: i32, enabled: bool) {
            self.inner.set_enabled(moria, enabled);
        }

        /// Toggle the enabled state of the cell at `moria`.
        /// Returns the new state, or `-1` if no cell exists there.
        #[wasm_bindgen(js_name = toggleCell)]
        pub fn toggle_cell(&mut self, moria: i32) -> i32 {
            match self.inner.toggle_cell(moria) {
                Some(true) => 1,
                Some(false) => 0,
                None => -1,
            }
        }

        /// Remove the override for `moria`, restoring the region default.
        #[wasm_bindgen(js_name = clearOverride)]
        pub fn clear_override(&mut self, moria: i32) {
            self.inner.clear_override(moria);
        }
    }

    // ── String → enum helpers ─────────────────────────────────────────────

    fn parse_degree(s: &str) -> Option<Degree> {
        match s {
            "Ni" => Some(Degree::Ni),
            "Pa" => Some(Degree::Pa),
            "Vou" => Some(Degree::Vou),
            "Ga" => Some(Degree::Ga),
            "Di" => Some(Degree::Di),
            "Ke" => Some(Degree::Ke),
            "Zo" => Some(Degree::Zo),
            _ => None,
        }
    }

    fn parse_genus(s: &str) -> Option<Genus> {
        match s {
            "Diatonic" => Some(Genus::Diatonic),
            "HardChromatic" => Some(Genus::HardChromatic),
            "SoftChromatic" => Some(Genus::SoftChromatic),
            "GraveDiatonic" => Some(Genus::GraveDiatonic),
            "EnharmonicZo" => Some(Genus::EnharmonicZo),
            "EnharmonicGa" => Some(Genus::EnharmonicGa),
            _ => None,
        }
    }

    fn parse_shading(s: &str) -> Option<Shading> {
        match s {
            "Zygos" => Some(Shading::Zygos),
            "Kliton" => Some(Shading::Kliton),
            "SpathiA" => Some(Shading::SpathiA),
            "SpathiB" => Some(Shading::SpathiB),
            _ => None,
        }
    }
}
