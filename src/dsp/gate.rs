//! Asymmetric hysteretic noise gate for the voice analysis path.
//!
//! Every `BLOCK` samples (default 128, matching C++) the peak-to-peak
//! amplitude of that block is EMA-smoothed into `current_amp`.
//! Gate opens when `current_amp > gate_on_amp`; closes when it drops below
//! the strictly lower `gate_off_amp = gate_on_amp * (15/16)`.

const BLOCK: usize = 128;

/// Hysteretic noise gate.
pub struct Gate {
    lo_amp: f32,
    hi_amp: f32,
    current_amp: f32,
    gate_on_amp: f32,
    gate_off_amp: f32,
    gate_open: bool,
    count: usize,
}

impl Default for Gate {
    fn default() -> Self {
        Self::new()
    }
}

impl Gate {
    /// Default: gate always open (on-amp = 0, off-amp = -1).
    /// Call `set_threshold` before using in production.
    pub fn new() -> Self {
        Self {
            lo_amp: 0.0,
            hi_amp: 0.0,
            current_amp: 0.0,
            gate_on_amp: 0.0,
            gate_off_amp: -1.0,
            gate_open: false,
            count: 0,
        }
    }

    /// Set gate-open threshold in linear amplitude (0.0..1.0 for normalised
    /// -1..+1 audio).  `gate_off_amp` is set to `on * (15/16)`.
    pub fn set_threshold(&mut self, gate_on_amp: f32) {
        self.gate_on_amp = gate_on_amp;
        self.gate_off_amp = gate_on_amp * (15.0 / 16.0);
    }

    pub fn gate_open(&self) -> bool {
        self.gate_open
    }

    pub fn current_level(&self) -> f32 {
        self.current_amp
    }

    /// Process one sample. Call after filtering. Returns current gate state.
    #[inline]
    pub fn process(&mut self, sample: f32) -> bool {
        if sample < self.lo_amp {
            self.lo_amp = sample;
        }
        if sample > self.hi_amp {
            self.hi_amp = sample;
        }

        self.count += 1;
        if self.count >= BLOCK {
            self.count = 0;
            // EMA of peak-to-peak amplitude over the block (¼ new, ¾ old).
            let block_pp = self.hi_amp - self.lo_amp;
            self.current_amp = (block_pp + 3.0 * self.current_amp) / 4.0;
            self.lo_amp = sample;
            self.hi_amp = sample;

            if self.current_amp > self.gate_on_amp {
                self.gate_open = true;
            } else if self.current_amp < self.gate_off_amp {
                self.gate_open = false;
            }
        }

        self.gate_open
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f32::consts::PI;

    /// Sine wave at 440 Hz, sample rate 44100 — pp ≈ 1.0 within every block.
    fn sine_samples(n: usize) -> Vec<f32> {
        (0..n)
            .map(|i| 0.5 * (2.0 * PI * 440.0 * i as f32 / 44100.0).sin())
            .collect()
    }

    #[test]
    fn gate_opens_on_loud_signal() {
        let mut g = Gate::new();
        g.set_threshold(0.1);
        // Silence then sine.
        for _ in 0..1024 {
            g.process(0.0);
        }
        let mut last_state = false;
        for s in sine_samples(2048) {
            last_state = g.process(s);
        }
        assert!(
            last_state,
            "gate should be open after sustained sine signal"
        );
    }

    #[test]
    fn gate_starts_closed() {
        let mut g = Gate::new();
        g.set_threshold(0.1);
        for _ in 0..512 {
            g.process(0.0);
        }
        assert!(!g.gate_open(), "gate should stay closed during silence");
    }

    #[test]
    fn gate_closes_after_silence_with_hysteresis() {
        let mut g = Gate::new();
        g.set_threshold(0.1);
        // Open the gate with a sine signal.
        for s in sine_samples(2048) {
            g.process(s);
        }
        assert!(g.gate_open(), "gate should open during loud sine");
        // Now feed prolonged silence.
        for _ in 0..8192 {
            g.process(0.0);
        }
        assert!(!g.gate_open(), "gate should close after prolonged silence");
    }
}
