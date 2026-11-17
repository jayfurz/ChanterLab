//! C ABI for native hosts (`feature = "ffi"`).
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
}
