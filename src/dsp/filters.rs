//! Audio filters ported from `vocproc.cpp` and `vocproc.h`.
//!
//! - `CascadedHpf`: two 2nd-order biquad high-pass stages (~50 Hz corner).
//!   Coefficients from `vocproc.cpp:665-666`.
//! - `NotchFilter`: comb-delay notch. Port of `vocproc.h:23-46`.
//! - `LowPassFilter1`: 1st-order LPF used before the time-domain peak detector.

/// One 2nd-order biquad high-pass section.
///
/// Difference equation (from `highPassFilter2` in `vocproc.cpp`):
///   y[n] = (x[n] + x[n-2]) - 2·x[n-1] + k1·y[n-1] + k0·y[n-2]
pub struct BiquadHpf {
    x: [f32; 3],
    y: [f32; 3],
    k0: f32,
    k1: f32,
}

impl BiquadHpf {
    pub fn new(k0: f32, k1: f32) -> Self {
        Self {
            x: [0.0; 3],
            y: [0.0; 3],
            k0,
            k1,
        }
    }

    #[inline]
    pub fn process(&mut self, input: f32) -> f32 {
        self.x[2] = self.x[1];
        self.x[1] = self.x[0];
        self.x[0] = input;
        self.y[2] = self.y[1];
        self.y[1] = self.y[0];
        self.y[0] =
            (self.x[0] + self.x[2]) - 2.0 * self.x[1] + self.k0 * self.y[2] + self.k1 * self.y[1];
        self.y[0]
    }
}

// Coefficients from vocproc.cpp:665-666.
const HPF_K0: f32 = -0.9907866988;
const HPF_K1: f32 = 1.9907440595;

/// Two cascaded 2nd-order biquad HPF stages (~32 Hz corner frequency).
/// Port of the `xa/xb/xc` filter chain in `VocProc::writeData`.
pub struct CascadedHpf {
    stage1: BiquadHpf,
    stage2: BiquadHpf,
}

impl Default for CascadedHpf {
    fn default() -> Self {
        Self::new()
    }
}

impl CascadedHpf {
    pub fn new() -> Self {
        Self {
            stage1: BiquadHpf::new(HPF_K0, HPF_K1),
            stage2: BiquadHpf::new(HPF_K0, HPF_K1),
        }
    }

    #[inline]
    pub fn process(&mut self, input: f32) -> f32 {
        self.stage2.process(self.stage1.process(input))
    }
}

/// Comb-delay notch filter. Port of `NotchFilter` in `vocproc.h:23-46`.
///
/// Creates a notch at frequency `sample_rate / period_samples` and its
/// harmonics. `amp` (0.0 = bypass, 1.0 = full depth) controls feedback.
///
/// The C++ operates on scaled int32; here we use normalised f32.
pub struct NotchFilter {
    buffer: Vec<f32>,
    amp: f32,
    ptr: usize,
}

impl Default for NotchFilter {
    fn default() -> Self {
        Self::new()
    }
}

impl NotchFilter {
    pub fn new() -> Self {
        Self {
            buffer: vec![0.0, 0.0],
            amp: 0.0,
            ptr: 0,
        }
    }

    pub fn set_period(&mut self, period_samples: usize) {
        let p = period_samples.max(2);
        if p != self.buffer.len() {
            self.buffer = vec![0.0; p];
            self.ptr = 0;
        }
    }

    pub fn set_amp(&mut self, amp: f32) {
        self.amp = amp.clamp(0.0, 1.0);
    }

    #[inline]
    pub fn process(&mut self, input: f32) -> f32 {
        let len = self.buffer.len();
        let delayed = self.buffer[self.ptr];
        let to_delay = (1.0 - self.amp) * input + self.amp * delayed;
        self.buffer[self.ptr] = to_delay;
        self.ptr = (self.ptr + 1) % len;
        input - delayed
    }
}

/// 1st-order IIR low-pass filter used before the time-domain peak detector.
/// Port of `lowPassFilter1` in `vocproc.cpp` with k0 = 0.9929014614.
pub struct LowPassFilter1 {
    x: [f32; 2],
    y: [f32; 2],
    k0: f32,
}

impl LowPassFilter1 {
    pub fn new(k0: f32) -> Self {
        Self {
            x: [0.0; 2],
            y: [0.0; 2],
            k0,
        }
    }

    /// Pre-configured for the time-domain path in `vocproc.cpp`.
    pub fn for_peak_detector() -> Self {
        Self::new(0.9929014614)
    }

    #[inline]
    pub fn process(&mut self, input: f32) -> f32 {
        self.x[1] = self.x[0];
        self.x[0] = input;
        self.y[1] = self.y[0];
        self.y[0] = (self.x[1] + self.x[0]) + self.k0 * self.y[1];
        self.y[0]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// DC signal should be fully blocked by the HPF.
    #[test]
    fn hpf_attenuates_dc() {
        let mut hpf = CascadedHpf::new();
        let mut out = 0.0f32;
        for _ in 0..20_000 {
            out = hpf.process(1.0);
        }
        assert!(out.abs() < 0.001, "HPF DC leakage = {out}");
    }

    /// 500 Hz is well above the ~32 Hz corner; gain must be close to unity.
    #[test]
    fn hpf_passes_500hz() {
        let mut hpf = CascadedHpf::new();
        let sr = 44100.0f32;
        let freq = 500.0f32;
        let mut peak = 0.0f32;
        for n in 0..30_000usize {
            let x = (2.0 * std::f32::consts::PI * freq * n as f32 / sr).sin();
            let y = hpf.process(x);
            if n > 10_000 {
                peak = peak.max(y.abs());
            }
        }
        assert!(
            peak > 0.80,
            "HPF should pass 500 Hz with gain > 0.8, got {peak}"
        );
    }

    /// LPF DC gain: input of 1.0 should converge to 1/(1 - k0) * 2 = very large,
    /// so what we actually test is that output grows (LPF passes DC).
    #[test]
    fn lpf_output_grows_for_dc() {
        let mut lpf = LowPassFilter1::for_peak_detector();
        // Feed DC: output should grow (LPF doesn't block DC).
        let out = lpf.process(0.01);
        let out2 = lpf.process(0.01);
        assert!(out2 > out, "LPF output should grow toward steady state");
    }

    #[test]
    fn notch_filter_compiles_and_runs() {
        let mut notch = NotchFilter::new();
        notch.set_period(100);
        notch.set_amp(0.5);
        let _ = notch.process(0.5);
    }
}
