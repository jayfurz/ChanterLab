// PsolaRepitcher — waveform-domain pitch correction.
// Ports RepitchPSOLA from byzorgan-source repitcher.cpp (lines 762–855).
//
// The C++ implementation uses 16.16 fixed-point arithmetic for `rate` and
// `rptr1`.  Here we use `f32`/`f64` floating-point throughout — no
// fixed-point needed in the browser target.
//
// Constants (from repitcher.cpp lines 1-60):
//   lowLimit  = 1350  — trigger back-jump when buffer is nearly empty
//   highLimit = 2700  — trigger forward-jump when buffer is too full
//   ATTACK_RATE = 6   — numerator for output volume ramp (6/16384 per sample)

const RING_SIZE: usize = 16384;
const RING_MASK: usize = RING_SIZE - 1;

const LOW_LIMIT: i32 = 1350;
const HIGH_LIMIT: i32 = 2700;

/// Ramp rate for `out_volume` per sample (6/16384 ≈ 3.66 × 10⁻⁴).
const ATTACK_RATE: f32 = 6.0 / 16384.0;

/// Release multiplier — fade out 4× faster than attack.
const RELEASE_RATE: f32 = ATTACK_RATE * 4.0;

/// Portamento glide step per sample (matches a "rateRate" that converges
/// quickly but avoids clicks on target-period changes).
const PORTA_STEP: f32 = 0.001;

/// PSOLA pitch repitcher.
///
/// Call [`push_sample`] once per input sample (the HPF-filtered mic signal),
/// and [`get_sample`] once per output sample (same clock) to obtain the
/// pitch-corrected waveform.
pub struct PsolaRepitcher {
    /// Ring buffer of filtered input samples.
    audio_in: Box<[f32; RING_SIZE]>,
    /// Write position into `audio_in` (wraps mod `RING_SIZE`).
    write_ptr: usize,
    /// Fractional read position (may be non-integer for interpolation).
    read_ptr: f64,
    /// Detected fundamental period in samples (= period_24_8 / 256.0).
    /// 0.0 means "not detected" → passthrough.
    actual_period: f32,
    /// Target period in samples for the snapped cell.
    /// 0.0 means "no target" → passthrough / fade-out.
    target_period: f32,
    /// Current read-rate (samples consumed per output sample).
    /// Glides toward `actual_period / target_period` for portamento.
    rate: f32,
    /// Crossfade progress: starts at ≈1.0 and decays to 0 over one period.
    xfade: f32,
    /// Decay per sample: `1.0 / actual_period`.
    xfade_rate: f32,
    /// Signed sample offset for the crossfade peek (±actual_period in samples).
    xoffset: f64,
    /// Output gain envelope (0.0 → 1.0).  Fades in on voiced audio, fades
    /// out when unvoiced.
    out_volume: f32,
}

impl PsolaRepitcher {
    pub fn new() -> Self {
        PsolaRepitcher {
            audio_in: Box::new([0.0f32; RING_SIZE]),
            write_ptr: 0,
            read_ptr: 0.0,
            actual_period: 0.0,
            target_period: 0.0,
            rate: 1.0,
            xfade: 0.0,
            xfade_rate: 0.0,
            xoffset: 0.0,
            out_volume: 0.0,
        }
    }

    /// Write one filtered input sample into the ring buffer.
    pub fn push_sample(&mut self, s: f32) {
        self.audio_in[self.write_ptr & RING_MASK] = s;
        self.write_ptr = self.write_ptr.wrapping_add(1);
    }

    /// Update the detected actual period from a 24.8 fixed-point value.
    /// Call whenever the pitch detector emits a new result.
    pub fn set_actual_period(&mut self, period_24_8: u32) {
        self.actual_period = period_24_8 as f32 / 256.0;
    }

    /// Update the target (snapped cell) period from a 24.8 fixed-point value.
    /// Pass 0 to signal "no target" (triggers fade-out).
    pub fn set_target_period(&mut self, period_24_8: u32) {
        self.target_period = period_24_8 as f32 / 256.0;
    }

    /// Produce one pitch-corrected output sample.
    ///
    /// Ports `RepitchPSOLA::convertSamples` for a single sample.
    pub fn get_sample(&mut self) -> f32 {
        let ap = self.actual_period;
        let tp = self.target_period;

        // ── Passthrough / fade-out when no period is detected ────────────
        if ap == 0.0 || tp == 0.0 {
            let s = self.read_interp(self.read_ptr);
            self.read_ptr += 1.0;
            self.out_volume = (self.out_volume - RELEASE_RATE).max(0.0);
            return s * self.out_volume;
        }

        // ── Compute target rate and glide current rate toward it ─────────
        let target_rate = ap / tp;
        if self.rate < target_rate {
            self.rate = (self.rate + PORTA_STEP).min(target_rate);
        } else if self.rate > target_rate {
            self.rate = (self.rate - PORTA_STEP).max(target_rate);
        }

        // ── Crossfade or normal read ──────────────────────────────────────
        let sample = if self.xfade > 0.0 {
            // Blend: new position (xoffset applied) and old position.
            // In the C++ (16.16 fixed-point):
            //   xfade2 = (xfade + 32768) >> 16   → weight for NEW position
            //   xfade1 = 4096 - xfade2            → weight for OLD position
            // Translated to float: xfade is already normalised 0..1.
            let w_new = self.xfade;
            let w_old = 1.0 - w_new;
            let s = self.read_interp(self.read_ptr + self.xoffset) * w_new
                + self.read_interp(self.read_ptr) * w_old;
            self.read_ptr += self.rate as f64;
            self.xfade -= self.xfade_rate;
            if self.xfade < 0.0 {
                self.xfade = 0.0;
            }
            s
        } else {
            let s = self.read_interp(self.read_ptr);
            self.read_ptr += self.rate as f64;

            let avail = self.available_samples();
            if avail < LOW_LIMIT {
                // Buffer near-empty: jump read ptr back one period.
                // xoffset = +ap so that peek(read_ptr + xoffset) reads the
                // OLD position (before the seek back).
                self.xoffset = ap as f64;
                self.read_ptr -= ap as f64;
                self.xfade_rate = 1.0 / ap;
                self.xfade = 1.0 - self.xfade_rate;
            } else if avail > HIGH_LIMIT {
                // Buffer overfull: jump read ptr forward one period.
                self.xoffset = -(ap as f64);
                self.read_ptr += ap as f64;
                self.xfade_rate = 1.0 / ap;
                self.xfade = 1.0 - self.xfade_rate;
            }
            s
        };

        // ── Output volume: attack toward 1.0 ─────────────────────────────
        self.out_volume = (self.out_volume + ATTACK_RATE).min(1.0);

        sample * self.out_volume
    }

    /// Reset all state to initial values (e.g. on stream restart).
    pub fn reset(&mut self) {
        self.audio_in.fill(0.0);
        self.write_ptr = 0;
        self.read_ptr = 0.0;
        self.actual_period = 0.0;
        self.target_period = 0.0;
        self.rate = 1.0;
        self.xfade = 0.0;
        self.xfade_rate = 0.0;
        self.xoffset = 0.0;
        self.out_volume = 0.0;
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    /// How many input samples are buffered ahead of the read pointer.
    ///
    /// Positive: read is behind write (normal).
    /// Near 0: buffer nearly empty → back-jump.
    /// Large:  buffer overfull → forward-jump.
    fn available_samples(&self) -> i32 {
        (self.write_ptr as i32).wrapping_sub(self.read_ptr as i32)
    }

    /// Linear interpolation from the ring buffer at a fractional position.
    fn read_interp(&self, ptr: f64) -> f32 {
        let i0 = (ptr as usize) & RING_MASK;
        let i1 = i0.wrapping_add(1) & RING_MASK;
        let frac = (ptr - ptr.floor()) as f32;
        let s0 = self.audio_in[i0];
        let s1 = self.audio_in[i1];
        s0 + (s1 - s0) * frac
    }
}

impl Default for PsolaRepitcher {
    fn default() -> Self {
        Self::new()
    }
}

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Passthrough mode: both periods 0 → get_sample returns near-zero
    /// after silence is pushed.
    #[test]
    fn test_psola_passthrough() {
        let mut r = PsolaRepitcher::new();
        // actual_period and target_period remain 0 (default).
        for _ in 0..100 {
            r.push_sample(0.0);
        }
        // The output volume starts at 0 and decays in passthrough mode,
        // so the result should always be 0.0.
        let out = r.get_sample();
        assert!(out.abs() < 1e-6, "expected ~0.0, got {out}");
    }

    /// Pitch-up test: feed a 440 Hz sine at 48 000 Hz, set target one
    /// octave up (880 Hz).  Verify no panics and samples stay in [-1, 1].
    #[test]
    fn test_psola_pitch_up() {
        const SR: f32 = 48_000.0;
        const ACTUAL_HZ: f32 = 440.0;
        const TARGET_HZ: f32 = 880.0;
        let actual_period_24_8 = ((SR / ACTUAL_HZ) * 256.0 + 0.5) as u32;
        let target_period_24_8 = ((SR / TARGET_HZ) * 256.0 + 0.5) as u32;

        let mut r = PsolaRepitcher::new();
        r.set_actual_period(actual_period_24_8);
        r.set_target_period(target_period_24_8);

        // Pre-fill enough samples to satisfy the buffer requirements.
        for i in 0..500 {
            let s = (2.0 * std::f32::consts::PI * ACTUAL_HZ * i as f32 / SR).sin();
            r.push_sample(s);
        }

        for _ in 0..200 {
            let out = r.get_sample();
            assert!(out >= -1.0 && out <= 1.0, "sample out of range: {out}");
        }
    }

    /// Period change mid-stream should not panic.
    #[test]
    fn test_psola_period_change() {
        const SR: f32 = 48_000.0;
        let period_a = ((SR / 440.0) * 256.0 + 0.5) as u32;
        let period_b = ((SR / 550.0) * 256.0 + 0.5) as u32;

        let mut r = PsolaRepitcher::new();
        r.set_actual_period(period_a);
        r.set_target_period(period_a); // unison to start

        for i in 0..300 {
            let s = (2.0 * std::f32::consts::PI * 440.0 * i as f32 / SR).sin();
            r.push_sample(s);
        }
        for _ in 0..100 {
            let out = r.get_sample();
            assert!(out >= -1.0 && out <= 1.0, "sample out of range: {out}");
        }

        // Change target mid-stream.
        r.set_target_period(period_b);

        for i in 300..500 {
            let s = (2.0 * std::f32::consts::PI * 440.0 * i as f32 / SR).sin();
            r.push_sample(s);
        }
        for _ in 0..100 {
            let out = r.get_sample();
            assert!(out >= -1.0 && out <= 1.0, "sample out of range: {out}");
        }
    }
}
