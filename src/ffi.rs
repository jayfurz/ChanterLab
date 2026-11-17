//! C ABI for native hosts (`feature = "ffi"`): pitch tracker, tuning grid
//! and synth.
//!
//! The iOS audio engine drives the same HPF → gate → FFT-detector pipeline the
//! training app's AudioWorklet uses (`training-prototype/pitch_worklet.js`),
//! so pitch detection is identical on both platforms. Every function is
//! allocation-free after `clp_tracker_new` and safe to call from the audio
//! thread; a tracker must not be used from two threads at once.

use crate::dsp::{detector::fft::FftDetector, filters::CascadedHpf, gate::Gate};

/// One mono pitch-tracking channel.
pub struct PitchTracker {
    hpf: CascadedHpf,
    gate: Gate,
    det: FftDetector,
    sample_rate: f32,
}

impl PitchTracker {
    pub fn new(sample_rate: f32, gate_on_amp: f32) -> Self {
        let mut gate = Gate::new();
        gate.set_threshold(gate_on_amp);
        Self {
            hpf: CascadedHpf::new(),
            gate,
            det: FftDetector::new(sample_rate),
            sample_rate,
        }
    }

    pub fn push(&mut self, samples: &[f32]) {
        for &x in samples {
            let y = self.hpf.process(x);
            self.gate.process(y);
            self.det.push(y);
        }
    }

    /// Detected fundamental in Hz, or 0 when the gate is closed or no
    /// confident pitch is found.
    pub fn detect_hz(&mut self) -> f32 {
        if !self.gate.gate_open() {
            return 0.0;
        }
        let min_period = (self.sample_rate / 1200.0 * 256.0).max(1.0) as u32;
        match self.det.detect(min_period) {
            0 => 0.0,
            period_24_8 => self.sample_rate * 256.0 / period_24_8 as f32,
        }
    }
}

#[no_mangle]
pub extern "C" fn clp_tracker_new(sample_rate: f32, gate_on_amp: f32) -> *mut PitchTracker {
    Box::into_raw(Box::new(PitchTracker::new(sample_rate, gate_on_amp)))
}

/// # Safety
/// `t` must come from `clp_tracker_new` and not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_free(t: *mut PitchTracker) {
    if !t.is_null() {
        drop(Box::from_raw(t));
    }
}

/// # Safety
/// `t` must be a live tracker; `samples` must point to `len` floats.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_push(t: *mut PitchTracker, samples: *const f32, len: usize) {
    if t.is_null() || samples.is_null() {
        return;
    }
    (*t).push(core::slice::from_raw_parts(samples, len));
}

/// # Safety
/// `t` must be a live tracker.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_detect_hz(t: *mut PitchTracker) -> f32 {
    if t.is_null() {
        return 0.0;
    }
    (*t).detect_hz()
}

/// # Safety
/// `t` must be a live tracker.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_gate_open(t: *const PitchTracker) -> bool {
    !t.is_null() && (*t).gate.gate_open()
}

/// # Safety
/// `t` must be a live tracker.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_level(t: *const PitchTracker) -> f32 {
    if t.is_null() {
        return 0.0;
    }
    (*t).gate.current_level()
}

/// # Safety
/// `t` must be a live tracker.
#[no_mangle]
pub unsafe extern "C" fn clp_tracker_set_gate(t: *mut PitchTracker, gate_on_amp: f32) {
    if !t.is_null() {
        (*t).gate.set_threshold(gate_on_amp);
    }
}

// ── Tuning grid ───────────────────────────────────────────────────────────
//
// Mirrors the wasm `JsTuningGrid` surface (`src/lib.rs`): names cross as C
// strings, structured values as JSON. Grid calls are main-thread only.

use crate::names::{parse_custom_genus, parse_degree, parse_genus, parse_symbol_drop};
use crate::synth::{Cmd, Synth};
use crate::tuning::TuningGrid;
use std::ffi::{c_char, CStr, CString};

/// # Safety
/// `s` must be null or a NUL-terminated string.
unsafe fn str_arg<'a>(s: *const c_char) -> Option<&'a str> {
    if s.is_null() {
        return None;
    }
    CStr::from_ptr(s).to_str().ok()
}

fn string_out(s: String) -> *mut c_char {
    CString::new(s).map_or(core::ptr::null_mut(), CString::into_raw)
}

/// Free a string returned by this library.
///
/// # Safety
/// `s` must come from a `clp_*` function returning `char *`, and not be reused.
#[no_mangle]
pub unsafe extern "C" fn clp_string_free(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

#[no_mangle]
pub extern "C" fn clp_grid_new() -> *mut TuningGrid {
    Box::into_raw(Box::new(TuningGrid::new_default()))
}

/// Restore a grid saved by `clp_grid_to_json`. Null on malformed input.
///
/// # Safety
/// `json` must be null or a NUL-terminated string.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_from_json(json: *const c_char) -> *mut TuningGrid {
    match str_arg(json).and_then(|j| TuningGrid::from_json(j).ok()) {
        Some(grid) => Box::into_raw(Box::new(grid)),
        None => core::ptr::null_mut(),
    }
}

/// # Safety
/// `g` must come from a grid constructor and not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_free(g: *mut TuningGrid) {
    if !g.is_null() {
        drop(Box::from_raw(g));
    }
}

/// # Safety
/// `g` must be a live grid. Free the result with `clp_string_free`.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_to_json(g: *const TuningGrid) -> *mut c_char {
    match g.as_ref().and_then(|g| g.to_json().ok()) {
        Some(json) => string_out(json),
        None => core::ptr::null_mut(),
    }
}

/// All cells in the visible window as a JSON array (same shape as the web
/// app's `cellsJson`).
///
/// # Safety
/// `g` must be a live grid. Free the result with `clp_string_free`.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_cells_json(g: *const TuningGrid) -> *mut c_char {
    match g
        .as_ref()
        .and_then(|g| serde_json::to_string(&g.cells()).ok())
    {
        Some(json) => string_out(json),
        None => core::ptr::null_mut(),
    }
}

/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_moria_to_hz(g: *const TuningGrid, moria: i32) -> f64 {
    g.as_ref().map_or(0.0, |g| g.moria_to_hz(moria))
}

/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_ref_ni_hz(g: *const TuningGrid) -> f64 {
    g.as_ref().map_or(0.0, |g| g.ref_ni_hz)
}

/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_set_ref_ni_hz(g: *mut TuningGrid, hz: f64) {
    if let Some(g) = g.as_mut() {
        if hz.is_finite() && hz > 0.0 {
            g.ref_ni_hz = hz;
        }
    }
}

/// Reanchor the region containing `moria` to `genus` with `degree` at `moria`.
/// Genus and degree use the Rust enum names (`"HardChromatic"`, `"Pa"`).
///
/// # Safety
/// `g` must be a live grid; strings must be NUL-terminated.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_apply_pthora(
    g: *mut TuningGrid,
    moria: i32,
    genus: *const c_char,
    degree: *const c_char,
) -> bool {
    let (Some(g), Some(genus), Some(degree)) = (
        g.as_mut(),
        str_arg(genus).and_then(parse_genus),
        str_arg(degree).and_then(parse_degree),
    ) else {
        return false;
    };
    g.apply_pthora(moria, genus, degree)
}

/// Apply a custom closed scale (7 positive moria steps summing to 72, as a
/// JSON array) with `degree` at `moria`.
///
/// # Safety
/// `g` must be a live grid; strings must be NUL-terminated.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_apply_custom_genus(
    g: *mut TuningGrid,
    moria: i32,
    degree: *const c_char,
    name: *const c_char,
    intervals_json: *const c_char,
    canonical_root: *const c_char,
) -> bool {
    let (Some(g), Some(degree), Some(name), Some(intervals), Some(root)) = (
        g.as_mut(),
        str_arg(degree).and_then(parse_degree),
        str_arg(name),
        str_arg(intervals_json),
        str_arg(canonical_root),
    ) else {
        return false;
    };
    match parse_custom_genus(name, intervals, root) {
        Some(genus) => g.apply_pthora(moria, genus, degree),
        None => false,
    }
}

/// Apply a palette drop: `{ type: "pthora" | "shading", dropMoria, dropDegree, ... }`.
///
/// # Safety
/// `g` must be a live grid; `json` must be NUL-terminated.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_apply_symbol_drop(
    g: *mut TuningGrid,
    json: *const c_char,
) -> bool {
    let (Some(g), Some(drop)) = (g.as_mut(), str_arg(json).and_then(parse_symbol_drop)) else {
        return false;
    };
    g.apply_symbol_drop(drop)
}

/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_remove_pthora(g: *mut TuningGrid, moria: i32) -> bool {
    g.as_mut().is_some_and(|g| g.remove_pthora(moria))
}

/// Set an accidental (moria shift) on the cell at `moria`. Odd values are ignored.
///
/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_set_accidental(g: *mut TuningGrid, moria: i32, accidental: i32) {
    if let Some(g) = g.as_mut() {
        if accidental % 2 == 0 {
            g.set_accidental(moria, accidental);
        }
    }
}

/// Toggle a cell. Returns 1 (now enabled), 0 (now disabled) or -1 (no such cell).
///
/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_toggle_cell(g: *mut TuningGrid, moria: i32) -> i32 {
    match g.as_mut().and_then(|g| g.toggle_cell(moria)) {
        Some(true) => 1,
        Some(false) => 0,
        None => -1,
    }
}

/// # Safety
/// `g` must be a live grid.
#[no_mangle]
pub unsafe extern "C" fn clp_grid_clear_override(g: *mut TuningGrid, moria: i32) {
    if let Some(g) = g.as_mut() {
        g.clear_override(moria);
    }
}

// ── Synth ─────────────────────────────────────────────────────────────────
//
// `clp_synth_render` is the audio thread's; every other call belongs to one
// control thread. Control calls are queued lock-free and take effect at the
// start of the next render.

#[no_mangle]
pub extern "C" fn clp_synth_new(sample_rate: f32) -> *mut Synth {
    Box::into_raw(Box::new(Synth::new(sample_rate)))
}

/// # Safety
/// `s` must come from `clp_synth_new`; no thread may use it afterwards.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_free(s: *mut Synth) {
    if !s.is_null() {
        drop(Box::from_raw(s));
    }
}

/// Render `len` mono samples, overwriting `out`.
///
/// # Safety
/// `s` must be a live synth; `out` must point to `len` floats.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_render(s: *const Synth, out: *mut f32, len: usize) {
    if out.is_null() {
        return;
    }
    let out = core::slice::from_raw_parts_mut(out, len);
    match s.as_ref() {
        Some(s) => s.render(out),
        None => out.fill(0.0),
    }
}

unsafe fn synth_send(s: *const Synth, cmd: Cmd) {
    if let Some(s) = s.as_ref() {
        s.send(cmd);
    }
}

/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_note_on(s: *const Synth, id: i32, hz: f32, velocity: f32) {
    synth_send(s, Cmd::NoteOn { id, hz, velocity });
}

/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_note_off(s: *const Synth, id: i32) {
    synth_send(s, Cmd::NoteOff { id });
}

/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_retune(s: *const Synth, id: i32, hz: f32) {
    synth_send(s, Cmd::Retune { id, hz });
}

/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_all_notes_off(s: *const Synth) {
    synth_send(s, Cmd::AllNotesOff);
}

/// Sustained drone; `volume <= 0` stops it.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_ison(s: *const Synth, hz: f32, volume: f32) {
    synth_send(s, Cmd::Ison { hz, volume });
}

/// 0 Sine, 1 Organ, 2 Reed, 3 Flute, 4 String.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_set_voicing(s: *const Synth, index: u8) {
    synth_send(s, Cmd::Voicing(index));
}

/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_set_master(s: *const Synth, level: f32) {
    synth_send(s, Cmd::Master(level));
}

/// One metronome tick.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_click(s: *const Synth, hz: f32, volume: f32) {
    synth_send(s, Cmd::Click { hz, volume });
}

/// The synth clock in samples (as of the last render). Any thread.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_frames(s: *const Synth) -> u64 {
    s.as_ref().map_or(0, Synth::frames)
}

/// Schedule a note on the synth clock: start at sample `start`, release
/// `frames` later. `voicing` as in `clp_synth_set_voicing`, plus 5 Triangle.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_note_at(
    s: *const Synth,
    hz: f32,
    velocity: f32,
    start: u64,
    frames: u32,
    voicing: u8,
) {
    synth_send(
        s,
        Cmd::NoteAt {
            hz,
            velocity,
            start,
            frames,
            voicing,
        },
    );
}

/// Drop scheduled notes and release the ones sounding.
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_clear_scheduled(s: *const Synth) {
    synth_send(s, Cmd::ClearScheduled);
}

// ── Scores and scoring ────────────────────────────────────────────────────

/// Parse MusicXML into the practice note model (JSON; see `score::Score`),
/// with lyrics for `verse` (1-based). On failure returns `{"error": "..."}`.
///
/// # Safety
/// `xml` must be NUL-terminated. Free the result with `clp_string_free`.
#[no_mangle]
pub unsafe extern "C" fn clp_score_parse(xml: *const c_char, verse: u32) -> *mut c_char {
    let result = match str_arg(xml) {
        Some(xml) => crate::score::parse(xml, verse).map_err(|e| e.0),
        None => Err("score text is not valid UTF-8".to_string()),
    };
    string_out(match result {
        Ok(score) => serde_json::to_string(&score).unwrap_or_default(),
        Err(e) => serde_json::json!({ "error": e }).to_string(),
    })
}

/// Score a lap. `targets_json`: `[{midi, startSec, endSec, measure?}]`;
/// `samples_json`: `[{tSec, midi}]` (voiced frames only). Returns the report
/// as JSON (see `scoring::Report`), or null on malformed input.
///
/// # Safety
/// Both strings must be NUL-terminated. Free the result with `clp_string_free`.
#[no_mangle]
pub unsafe extern "C" fn clp_score_lap(
    targets_json: *const c_char,
    samples_json: *const c_char,
    strict: bool,
) -> *mut c_char {
    use crate::scoring::{score_notes, Config, Sample, Target};
    let parsed = str_arg(targets_json)
        .and_then(|t| serde_json::from_str::<Vec<Target>>(t).ok())
        .zip(str_arg(samples_json).and_then(|s| serde_json::from_str::<Vec<Sample>>(s).ok()));
    let Some((targets, samples)) = parsed else {
        return core::ptr::null_mut();
    };
    let cfg = if strict {
        Config::STRICT
    } else {
        Config::RELAXED
    };
    match serde_json::to_string(&score_notes(&targets, &samples, &cfg)) {
        Ok(json) => string_out(json),
        Err(_) => core::ptr::null_mut(),
    }
}

/// Sample-accurate metronome; `bpm <= 0` stops it. The first beat of every
/// `beats_per_bar` is accented (0 = no accent).
///
/// # Safety
/// `s` must be a live synth.
#[no_mangle]
pub unsafe extern "C" fn clp_synth_metronome(
    s: *const Synth,
    bpm: f32,
    volume: f32,
    beats_per_bar: u8,
) {
    synth_send(
        s,
        Cmd::Metronome {
            bpm,
            volume,
            beats_per_bar,
        },
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sine(hz: f32, sr: f32, n: usize, amp: f32) -> Vec<f32> {
        (0..n)
            .map(|i| amp * (2.0 * core::f32::consts::PI * hz * i as f32 / sr).sin())
            .collect()
    }

    #[test]
    fn tracks_a_sung_range_sine() {
        for sr in [44_100.0, 48_000.0] {
            for hz in [130.81, 220.0, 440.0] {
                let mut t = PitchTracker::new(sr, 0.02);
                let mut got = 0.0;
                for block in sine(hz, sr, sr as usize, 0.3).chunks(512) {
                    t.push(block);
                    got = t.detect_hz();
                }
                assert!((got - hz).abs() / hz < 0.01, "{hz} Hz @ {sr}: got {got}");
            }
        }
    }

    #[test]
    fn silence_reports_no_pitch() {
        let mut t = PitchTracker::new(48_000.0, 0.02);
        t.push(&vec![0.0; 48_000]);
        assert_eq!(t.detect_hz(), 0.0);
    }

    #[test]
    fn c_abi_round_trip() {
        unsafe {
            let t = clp_tracker_new(48_000.0, 0.02);
            let s = sine(220.0, 48_000.0, 48_000, 0.3);
            // The detector settles over successive calls, as on the audio thread.
            let mut hz = 0.0;
            for block in s.chunks(512) {
                clp_tracker_push(t, block.as_ptr(), block.len());
                hz = clp_tracker_detect_hz(t);
            }
            assert!(clp_tracker_gate_open(t));
            assert!((hz - 220.0).abs() < 2.5, "got {hz}");
            clp_tracker_free(t);
        }
    }

    fn cstr(s: &str) -> CString {
        CString::new(s).unwrap()
    }

    unsafe fn take(s: *mut c_char) -> String {
        assert!(!s.is_null());
        let out = CStr::from_ptr(s).to_str().unwrap().to_string();
        clp_string_free(s);
        out
    }

    unsafe fn first_octave(g: *const TuningGrid) -> Vec<i64> {
        let cells: Vec<serde_json::Value> =
            serde_json::from_str(&take(clp_grid_cells_json(g))).unwrap();
        cells
            .iter()
            .filter(|c| c["enabled"] == true)
            .filter_map(|c| c["moria"].as_i64())
            .filter(|m| (0..72).contains(m))
            .collect()
    }

    #[test]
    fn grid_presets_and_round_trip() {
        unsafe {
            let g = clp_grid_new();
            assert_eq!(first_octave(g), vec![0, 12, 22, 30, 42, 54, 64]);
            assert!((clp_grid_moria_to_hz(g, 72) - 2.0 * clp_grid_ref_ni_hz(g)).abs() < 1e-9);

            assert!(clp_grid_apply_pthora(
                g,
                0,
                cstr("Chromatic12").as_ptr(),
                cstr("Ni").as_ptr()
            ));
            assert_eq!(first_octave(g).len(), 12);

            assert!(clp_grid_apply_custom_genus(
                g,
                0,
                cstr("Ni").as_ptr(),
                cstr("Raga Yaman").as_ptr(),
                cstr("[12,12,12,6,12,12,6]").as_ptr(),
                cstr("Ni").as_ptr(),
            ));
            assert_eq!(first_octave(g), vec![0, 12, 24, 36, 42, 54, 66]);

            clp_grid_set_ref_ni_hz(g, 146.83);
            let saved = take(clp_grid_to_json(g));
            let restored = clp_grid_from_json(cstr(&saved).as_ptr());
            assert!(!restored.is_null());
            assert_eq!(first_octave(restored), first_octave(g));
            assert_eq!(clp_grid_ref_ni_hz(restored), 146.83);
            clp_grid_free(restored);
            clp_grid_free(g);
        }
    }

    #[test]
    fn grid_rejects_bad_input_without_crashing() {
        unsafe {
            let g = clp_grid_new();
            let before = first_octave(g);
            assert!(!clp_grid_apply_pthora(
                g,
                0,
                cstr("Nope").as_ptr(),
                cstr("Ni").as_ptr()
            ));
            assert!(!clp_grid_apply_pthora(
                g,
                0,
                core::ptr::null(),
                cstr("Ni").as_ptr()
            ));
            assert!(!clp_grid_apply_symbol_drop(g, cstr("not json").as_ptr()));
            assert!(clp_grid_from_json(cstr("{").as_ptr()).is_null());
            clp_grid_set_accidental(g, 0, 3); // odd: ignored
            clp_grid_set_ref_ni_hz(g, f64::NAN);
            assert_eq!(first_octave(g), before);
            assert_eq!(clp_grid_toggle_cell(g, 0), 0);
            assert_eq!(clp_grid_toggle_cell(g, 0), 1);
            clp_grid_free(g);
        }
    }

    #[test]
    fn score_and_lap_c_abi() {
        unsafe {
            let xml = cstr(
                "<score-partwise><part-list><score-part id=\"P1\"><part-name>Soprano</part-name></score-part></part-list>\
                 <part id=\"P1\"><measure number=\"1\"><attributes><divisions>1</divisions></attributes>\
                 <note><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration></note></measure></part></score-partwise>",
            );
            let score: serde_json::Value =
                serde_json::from_str(&take(clp_score_parse(xml.as_ptr(), 1))).unwrap();
            assert_eq!(score["parts"][0]["notes"][0]["midi"], 69);
            assert_eq!(score["parts"][0]["notes"][0]["durBeat"], 2.0);

            let bad: serde_json::Value =
                serde_json::from_str(&take(clp_score_parse(cstr("<a>").as_ptr(), 1))).unwrap();
            assert!(bad["error"].is_string());

            let targets = cstr(r#"[{"midi":69,"startSec":0,"endSec":1,"measure":1}]"#);
            let samples: Vec<String> = (0..60)
                .map(|i| format!(r#"{{"tSec":{},"midi":69.1}}"#, i as f64 / 60.0))
                .collect();
            let samples = cstr(&format!("[{}]", samples.join(",")));
            let report: serde_json::Value = serde_json::from_str(&take(clp_score_lap(
                targets.as_ptr(),
                samples.as_ptr(),
                false,
            )))
            .unwrap();
            assert_eq!(report["hitPct"], 100);
            assert_eq!(report["details"][0]["result"], "hit");
            assert!(clp_score_lap(cstr("nope").as_ptr(), samples.as_ptr(), false).is_null());
        }
    }

    #[test]
    fn synth_c_abi_renders_a_note() {
        unsafe {
            let s = clp_synth_new(48_000.0);
            let mut buf = vec![1.0f32; 4800];
            clp_synth_render(s, buf.as_mut_ptr(), buf.len());
            assert!(buf.iter().all(|x| *x == 0.0));
            clp_synth_note_on(s, 0, 220.0, 0.8);
            clp_synth_render(s, buf.as_mut_ptr(), buf.len());
            assert!(buf.iter().any(|x| x.abs() > 0.1));
            clp_synth_free(s);
        }
    }
}
