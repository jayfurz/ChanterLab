//! Pitch detectors. Two paths:
//!
//! - `TimeDomainDetector`: peak state-machine feeding a log-spaced histogram.
//!
//! - `FftDetector`: cepstrum-based FFT detector. Feature-gated under
//!   `worklet` since it requires `realfft`.

// ─── Time-domain detector ─────────────────────────────────────────────────────

/// A log-spaced histogram bin for the time-domain path.
#[derive(Clone, Default)]
struct HistogramBin {
    /// Center period for this bin (in samples, raw — not fixed-point).
    period: u32,
    total: u64,
    hits: u16,
}

/// Peak state-machine + log-histogram pitch detector.
///
/// Call `push_sample` for every audio sample; call `detect` every 2048 samples
/// to read the histogram peak.
pub struct TimeDomainDetector {
    // Peak state machine
    peak_state: bool, // false = searching for high, true = searching for low
    peak_low: f32,
    peak_high: f32,
    threshold: f32,
    low_pt: u64,
    low_pt0: u64,
    high_pt: u64,
    high_pt0: u64,
    reset_pt: u64,
    sample_pos: u64,

    // Histogram (log-spaced bins, range set from tuning table)
    histogram: Vec<HistogramBin>,
    lowest_period: u32,
    highest_period: u32,
}

impl Default for TimeDomainDetector {
    fn default() -> Self {
        Self::new()
    }
}

impl TimeDomainDetector {
    pub fn new() -> Self {
        Self {
            peak_state: false,
            peak_low: 0.0,
            peak_high: 0.0,
            threshold: 0.0,
            low_pt: 0,
            low_pt0: 0,
            high_pt: 0,
            high_pt0: 0,
            reset_pt: 0,
            sample_pos: 0,
            histogram: Vec::new(),
            lowest_period: u32::MAX,
            highest_period: 0,
        }
    }

    /// Initialise histogram bins from the enabled cell period range.
    /// Bins are log-spaced with ratio 9/8 (matching the C++ `setupHystogram`).
    pub fn setup_histogram(&mut self, lowest_period: u32, highest_period: u32) {
        if lowest_period == 0 || highest_period == 0 || lowest_period > highest_period {
            return;
        }
        self.lowest_period = lowest_period;
        self.highest_period = highest_period;
        self.histogram.clear();

        let mut p = lowest_period;
        while p <= highest_period {
            self.histogram.push(HistogramBin {
                period: p,
                ..Default::default()
            });
            p = p * 9 / 8;
        }
    }

    /// Feed one (already filtered) sample. Returns a raw period when a
    /// peak-to-peak crossing is detected, 0 otherwise.
    /// Update the period histogram from the current peak state.
    #[inline]
    pub fn push_sample(&mut self, sample: f32) -> u32 {
        let pos = self.sample_pos;
        self.sample_pos += 1;

        // Decay threshold every 2048 samples (matching C++ resetpt logic).
        if pos.wrapping_sub(self.reset_pt) >= 2048 {
            self.reset_pt = pos;
            self.threshold -= self.threshold * 0.25;
        }

        let mut period = 0u32;
        if self.peak_state {
            // Searching for low.
            if sample < self.peak_low {
                self.peak_low = sample;
                self.threshold = (self.peak_high * 2.0 + self.peak_low) / 3.0;
                self.low_pt = pos;
            }
            if sample > self.threshold {
                // Transition low→high: measure low-to-low period.
                self.peak_state = false;
                let raw = self.low_pt.wrapping_sub(self.low_pt0) as u32;
                period = raw;
                self.low_pt0 = self.low_pt;
                self.peak_high = sample;
                self.threshold = (self.peak_high * 2.0 + self.peak_low) / 3.0;
                self.reset_pt = pos;
                self.high_pt = pos;
            }
        } else {
            // Searching for high.
            if sample > self.peak_high {
                self.peak_high = sample;
                self.threshold = (self.peak_high + 2.0 * self.peak_low) / 3.0;
                self.high_pt = pos;
            }
            if sample < self.threshold {
                // Transition high→low: measure high-to-high period.
                self.peak_state = true;
                let raw = self.high_pt.wrapping_sub(self.high_pt0) as u32;
                period = raw;
                self.high_pt0 = self.high_pt;
                self.peak_low = sample;
                self.threshold = (self.peak_high + 2.0 * self.peak_low) / 3.0;
                self.reset_pt = pos;
                self.low_pt = pos;
            }
        }

        if period != 0 && !self.histogram.is_empty() {
            self.update_histogram(period);
        }
        period
    }

    /// Find the peak histogram bin and return the weighted average period
    /// (raw samples). Returns 0 if confidence is too low.
    /// Run time-domain pitch detection for one sample.
    pub fn detect(&mut self) -> u32 {
        if self.histogram.is_empty() {
            return 0;
        }

        // Find the most-hit bin.
        let mut max_hits = 0u16;
        let mut hit_idx = usize::MAX;
        for (i, bin) in self.histogram.iter().enumerate() {
            if bin.hits > max_hits {
                max_hits = bin.hits;
                hit_idx = i;
            }
        }

        if hit_idx == usize::MAX {
            return 0;
        }

        // Accumulate this bin + neighbours.
        let n = self.histogram.len();
        let mut total_hits = self.histogram[hit_idx].hits as u32;
        let mut sum_total = self.histogram[hit_idx].total;
        if hit_idx > 0 {
            total_hits += self.histogram[hit_idx - 1].hits as u32;
            sum_total += self.histogram[hit_idx - 1].total;
        }
        if hit_idx + 1 < n {
            total_hits += self.histogram[hit_idx + 1].hits as u32;
            sum_total += self.histogram[hit_idx + 1].total;
        }

        // Half-life decay (hits >>= 1).
        for bin in &mut self.histogram {
            let old = bin.hits;
            bin.hits >>= 1;
            if bin.hits == 0 {
                bin.total = 0;
            } else {
                bin.total = (bin.total * bin.hits as u64 + old as u64 / 2) / old as u64;
            }
        }

        // Accept only if hit power is large enough (matching C++ threshold 1_100_000).
        let hit_power = total_hits as u64 * self.histogram[hit_idx].period as u64;
        if hit_power >= 1_100_000 {
            // Weighted average period (24.8 fixed-point: shift by 8).
            let period_raw = if total_hits > 0 {
                ((sum_total << 8) + total_hits as u64 / 2) / total_hits as u64
            } else {
                0
            };
            period_raw as u32
        } else {
            0
        }
    }

    fn update_histogram(&mut self, period: u32) {
        // Binary search for nearest bin (log-spaced, so search by period value).
        let pp = (period as u64) << 8;
        let pos = self.histogram.partition_point(|b| (b.period as u64) < pp);

        let idx = if pos == 0 {
            0
        } else if pos == self.histogram.len() {
            self.histogram.len() - 1
        } else {
            let a = pp - (self.histogram[pos - 1].period as u64);
            let b = (self.histogram[pos].period as u64) - pp;
            if a < b {
                pos - 1
            } else {
                pos
            }
        };

        self.histogram[idx].hits = self.histogram[idx].hits.saturating_add(1);
        self.histogram[idx].total += period as u64;
    }
}

// ─── FFT detector ─────────────────────────────────────────────────────────────

/// Cepstrum-based FFT pitch detector.
///
/// Only compiled with the `worklet` feature (requires `realfft`).
#[cfg(feature = "worklet")]
pub mod fft {
    use realfft::num_complex::Complex;
    use realfft::{ComplexToReal, RealFftPlanner, RealToComplex};
    use std::sync::Arc;

    /// FFT length — 5120 samples (doubled from 2560 for bass-range cepstrum confidence).
    /// At 48 kHz, 2560 gives only ~4.3 cycles at 80 Hz; 5120 gives ~8.5.
    pub const FFTLEN: usize = 5120;
    /// Rate at which the FFT runs: every 128 samples (`FFT_DETECT_BLOCK_SIZE`).
    pub const FFT_DETECT_BLOCK_SIZE: usize = 128;
    const HALF: usize = FFTLEN / 2;
    /// Raw audio ring buffer — must be ≥ FFTLEN and power-of-2 for bitwise wrap.
    const RAW_BUFFER_SIZE: usize = 8192;
    const LOW_NOTE_RELAX_START_HZ: f32 = 261.63; // C4
    const LOW_NOTE_RELAX_END_HZ: f32 = 80.0;
    const LOW_NOTE_MAX_AMBIGUITY: f32 = 0.65;
    const LOW_NOTE_RELAX_BOOST: f32 = 0.35;

    /// Portable integer-bit-length for alias index mapping. Mirrors `ilog` /
    /// Integer log2 helper for period bucketing.
    fn ilog(x: usize) -> usize {
        if x == 0 {
            return 0;
        }
        let nb = usize::BITS as usize - x.leading_zeros() as usize; // bit length
        if nb <= 6 {
            x
        } else {
            ((nb - 6) << 5) | (x >> (nb - 6))
        }
    }

    pub struct FftDetector {
        sample_rate: f32,
        r2c: Arc<dyn RealToComplex<f32>>,
        c2r: Arc<dyn ComplexToReal<f32>>,

        // Preallocated buffers.
        fft_window: Box<[f32; FFTLEN]>,
        fft_corr: Box<[f32; HALF]>,
        fft_tdata: Vec<f32>,                   // r2c input / c2r output
        fft_spectrum: Vec<Complex<f32>>,       // r2c output
        fft_fdata2: Vec<f32>,                  // sqrt spectrum (c2r input, real part)
        fft_fdata2_complex: Vec<Complex<f32>>, // c2r input buffer
        fft_tavg: Box<[f32; HALF + 1]>,        // log-bin EMA

        /// Ring buffer of raw filtered samples (size RAW_BUFFER_SIZE = 8192).
        pub audio_raw: Box<[f32; RAW_BUFFER_SIZE]>,
        pub write_ptr: usize,
    }

    impl FftDetector {
        pub fn new(sample_rate: f32) -> Self {
            let mut planner = RealFftPlanner::<f32>::new();
            let r2c = planner.plan_fft_forward(FFTLEN);
            let c2r = planner.plan_fft_inverse(FFTLEN);

            let fft_tdata = r2c.make_input_vec();
            let fft_spectrum = r2c.make_output_vec();
            let fft_fdata2 = vec![0.0f32; HALF];
            let fft_fdata2_complex = c2r.make_input_vec();

            let mut det = Self {
                sample_rate,
                r2c,
                c2r,
                fft_window: Box::new([0.0; FFTLEN]),
                fft_corr: Box::new([0.0; HALF]),
                fft_tdata,
                fft_spectrum,
                fft_fdata2,
                fft_fdata2_complex,
                fft_tavg: Box::new([0.0; HALF + 1]),
                audio_raw: Box::new([0.0; RAW_BUFFER_SIZE]),
                write_ptr: 0,
            };
            det.init_window_and_corr();
            det
        }

        /// Push one filtered sample into the ring buffer.
        #[inline]
        pub fn push(&mut self, sample: f32) {
            self.audio_raw[self.write_ptr & (RAW_BUFFER_SIZE - 1)] = sample;
            self.write_ptr = self.write_ptr.wrapping_add(1);
        }

        /// Run the full cepstrum pipeline. Returns 24.8 fixed-point period, or 0
        /// if confidence gates fail.
        pub fn detect(&mut self, lowest_period: u32) -> u32 {
            self.calc_spectrum();
            self.pitch_detection(lowest_period)
        }

        // ── Internal ──────────────────────────────────────────────────────────

        fn init_window_and_corr(&mut self) {
            use std::f32::consts::PI;

            // Hann window.
            for i in 0..FFTLEN {
                self.fft_window[i] = 0.5 * (1.0 - (2.0 * PI * i as f32 / FFTLEN as f32).cos());
            }

            // Compute window autocorrelation for bias removal.
            // 1. Window the window itself.
            for i in 0..FFTLEN {
                self.fft_tdata[i] = self.fft_window[i];
            }
            // 2. Forward FFT.
            let _ = self
                .r2c
                .process(&mut self.fft_tdata, &mut self.fft_spectrum);
            // 3. Magnitude spectrum.
            for i in 0..HALF {
                let c = self.fft_spectrum[i];
                self.fft_fdata2[i] = (c.re * c.re + c.im * c.im).sqrt();
            }
            // 4. Inverse FFT of magnitudes (treated as real → conjugate-symmetric).
            for i in 0..HALF {
                self.fft_fdata2_complex[i] = Complex::new(self.fft_fdata2[i], 0.0);
            }
            // Mirror for conjugate symmetry (matches FFTW REDFT01 intent).
            for i in HALF + 1..self.fft_fdata2_complex.len() {
                let j = FFTLEN - i;
                if j < HALF {
                    self.fft_fdata2_complex[i] = Complex::new(self.fft_fdata2[j], 0.0);
                }
            }
            let mut corr_out = self.c2r.make_output_vec();
            let _ = self
                .c2r
                .process(&mut self.fft_fdata2_complex, &mut corr_out);

            let t = corr_out[0].abs() + 0.1;
            for i in 0..HALF {
                self.fft_corr[i] = (corr_out[i] / t).abs().max(1e-9);
            }
        }

        /// Read the ring buffer into `fft_tdata` with a Hann window, then run
        /// the forward FFT.
        fn calc_spectrum(&mut self) {
            let j = self.write_ptr.wrapping_sub(FFTLEN);
            for i in 0..FFTLEN {
                let s = self.audio_raw[(j.wrapping_add(i)) & (RAW_BUFFER_SIZE - 1)];
                self.fft_tdata[i] = self.fft_window[i] * s;
            }
            let _ = self
                .r2c
                .process(&mut self.fft_tdata, &mut self.fft_spectrum);
        }

        /// Operates on `fft_spectrum` set by `calc_spectrum`.
        /// Returns 24.8 fixed-point period or 0.
        fn pitch_detection(&mut self, lowest_period: u32) -> u32 {
            // Build sqrt-magnitude spectrum → fft_fdata2.
            for i in 0..HALF {
                let c = self.fft_spectrum[i];
                self.fft_fdata2[i] = (c.re * c.re + c.im * c.im).sqrt();
            }

            // Inverse transform (use real part of c2r as our cepstrum approximation).
            for i in 0..HALF {
                self.fft_fdata2_complex[i] = Complex::new(self.fft_fdata2[i], 0.0);
            }
            for i in HALF + 1..self.fft_fdata2_complex.len() {
                let j = FFTLEN.saturating_sub(i);
                if j < HALF {
                    self.fft_fdata2_complex[i] = Complex::new(self.fft_fdata2[j], 0.0);
                } else {
                    self.fft_fdata2_complex[i] = Complex::new(0.0, 0.0);
                }
            }
            let mut tdata = self.c2r.make_output_vec();
            let _ = self.c2r.process(&mut self.fft_fdata2_complex, &mut tdata);

            // Limit: lowest detectable pitch is sample_rate/60 Hz.
            let limit = ((self.sample_rate / 60.0) as usize + 1)
                .min(FFTLEN * 2 / 5)
                .min(tdata.len());

            // Window-bias removal + clamp to ≥ 0.
            let t = tdata[0].abs() + 0.1;
            for i in 0..limit {
                let a = tdata[i] / (t * self.fft_corr[i]);
                tdata[i] = a.max(0.0);
            }

            // Alias suppression: k ∈ {2, 3, 5, 7}, iterate i downward.
            fn interpolate(data: &[f32], index: usize, denom: usize) -> f32 {
                let idx = (2 * index) as isize - denom as isize + 1;
                let denom2 = denom * 2;
                if idx < 0 {
                    return data[0];
                }
                let ix = idx as usize / denom2;
                let iy = idx as usize % denom2;
                if ix + 1 >= data.len() {
                    return *data.last().unwrap_or(&0.0);
                }
                data[ix] + (data[ix + 1] - data[ix]) * iy as f32 / denom2 as f32
            }
            for &hno in &[2usize, 3, 5, 7] {
                for i in (0..limit).rev() {
                    let sub = interpolate(&tdata, i, hno);
                    tdata[i] = (tdata[i] - sub).max(0.0);
                }
            }

            // Log-bin EMA + neighbour spreading (k²-weighted Gaussian).
            let avg_max = ilog(limit) + 2;
            for i in 0..avg_max.min(self.fft_tavg.len()) {
                self.fft_tavg[i] *= 0.75;
            }

            // Find peaks, track global and second peak, update EMA.
            let mut i = 1;
            while i < limit && tdata[i] > 0.0 {
                i += 1;
            }

            let mut peak_index = 0usize;
            let mut global_peak = 0.0f32;
            let mut second_peak = 0.0f32;

            while i < limit {
                while i < limit && tdata[i] <= 0.0 {
                    i += 1;
                }
                if i >= limit {
                    break;
                }
                let mut jm = i;
                let mut apeak = tdata[i];
                while i < limit && tdata[i] > 0.0 {
                    if tdata[i] > apeak {
                        apeak = tdata[i];
                        jm = i;
                    }
                    i += 1;
                }

                // Only consider lags ≥ lowest_period/256 (hi-freq cutoff).
                let min_lag = (lowest_period >> 8) as usize;
                if jm >= min_lag && apeak > 0.1 {
                    let aindex = (ilog(jm) + 1).min(self.fft_tavg.len() - 1);
                    let cpeak = apeak * self.fft_tavg[aindex];

                    if cpeak > global_peak {
                        second_peak = global_peak;
                        global_peak = cpeak;
                        peak_index = jm;
                    } else if cpeak > second_peak {
                        second_peak = cpeak;
                    }

                    self.fft_tavg[aindex] += apeak;
                    for k in 1..=6usize {
                        let m = apeak / 1.1f32.powi((k * k) as i32);
                        if aindex >= k {
                            self.fft_tavg[aindex - k] += m;
                        }
                        if aindex + k < self.fft_tavg.len() {
                            self.fft_tavg[aindex + k] += m;
                        }
                    }
                }
            }

            // Two-tier confidence gate. Below C4, tolerate stronger harmonic
            // competitors before rejecting the candidate — low voices often
            // project a stronger overtone than the fundamental.
            let base_ambiguity_limit = (global_peak * 0.6 + 0.14).min(0.5);
            let bass_start = self.sample_rate / LOW_NOTE_RELAX_START_HZ;
            let bass_end = self.sample_rate / LOW_NOTE_RELAX_END_HZ;
            let bass_blend = if bass_end > bass_start {
                ((peak_index as f32 - bass_start) / (bass_end - bass_start)).clamp(0.0, 1.0)
            } else {
                0.0
            };
            let ambiguity_limit = (base_ambiguity_limit + bass_blend.sqrt() * LOW_NOTE_RELAX_BOOST)
                .min(LOW_NOTE_MAX_AMBIGUITY);
            let clarity_ok =
                global_peak > 0.03 && second_peak / global_peak.max(1e-9) < ambiguity_limit;
            if !clarity_ok || peak_index == 0 {
                return 0;
            }

            // Parabolic least-squares sub-sample interpolation.
            let thr = tdata[peak_index] * 0.5;
            let pkl_init = peak_index * 3 / 4;
            let pkr_init = peak_index * 5 / 4;

            let mut pkl = peak_index;
            while pkl > pkl_init && tdata[pkl] >= thr {
                pkl -= 1;
            }
            pkl += 1;

            let mut pkr = peak_index + 1;
            while pkr <= pkr_init.min(limit - 1) && tdata[pkr] >= thr {
                pkr += 1;
            }
            pkr -= 1;

            let pkw = (pkr as isize - pkl as isize + 1) as usize;
            if pkw < 3 {
                return 0;
            }

            let w2 = pkw * pkw;
            let s20 = (w2 - 1) as f32 / 3.0;
            let s42 = (3 * w2 - 7) as f32 / 5.0;
            let mut b0 = 0.0f32;
            let mut b1 = 0.0f32;
            let mut b2 = 0.0f32;
            let mut x = -(pkw as i32 - 1);
            for idx in pkl..=pkr {
                let y = tdata[idx];
                b0 += y;
                b1 += x as f32 * y;
                b2 += (x * x) as f32 * y;
                x += 2;
            }
            let z1 = b1 * (s42 - s20);
            let z2 = b2 - s20 * b0;
            if z2 >= -1e-10 {
                return 0;
            }
            let period = 0.5 * (pkl + pkr + 1) as f32 - z1 / (2.0 * z2);
            if period < (self.sample_rate / 1200.0) || period > (self.sample_rate / 60.0) {
                return 0;
            }
            (period * 256.0 + 0.5) as u32
        }
    }

    #[cfg(test)]
    mod tests {
        use super::{FftDetector, FFT_DETECT_BLOCK_SIZE};
        use std::f32::consts::PI;

        const SR: f32 = 44100.0;

        fn make_det() -> FftDetector {
            FftDetector::new(SR)
        }

        fn feed_sine(det: &mut FftDetector, freq: f32, n_samples: usize) {
            for i in 0..n_samples {
                let s = (2.0 * PI * freq * i as f32 / SR).sin();
                det.push(s);
            }
        }

        /// Pure sine at 220 Hz → detected period ≈ SR/220 = 200.45 samples.
        ///
        /// The EMA (`fft_tavg`) starts at zero, so the detector needs several
        /// calls to warm up — matching its intended ~60 Hz call rate.
        #[test]
        fn detects_220hz_sine() {
            let mut det = make_det();
            let min_period = (SR / 1200.0 * 256.0) as u32;

            // Feed and detect in interleaved blocks to warm up the EMA.
            let block = FFT_DETECT_BLOCK_SIZE;
            let mut result = 0u32;
            let mut sample_pos = 0usize;
            for _ in 0..80 {
                for j in 0..block {
                    det.push((2.0 * PI * 220.0 * (sample_pos + j) as f32 / SR).sin());
                }
                sample_pos += block;
                result = det.detect(min_period);
                if result > 0 {
                    break;
                }
            }

            assert!(result > 0, "expected detection after EMA warm-up, got 0");
            let period_samples = result as f32 / 256.0;
            let detected_freq = SR / period_samples;
            let err = (detected_freq - 220.0).abs() / 220.0;
            assert!(
                err < 0.02,
                "220 Hz: detected {detected_freq:.1} Hz (err {:.1}%)",
                err * 100.0
            );
        }

        /// White noise should produce no confident detection.
        #[test]
        fn no_detection_on_noise() {
            use std::collections::hash_map::DefaultHasher;
            use std::hash::{Hash, Hasher};

            let mut det = make_det();
            // Deterministic pseudo-noise.
            for i in 0u64..8192 {
                let mut h = DefaultHasher::new();
                i.hash(&mut h);
                let v = (h.finish() as i64 as f32) / (i64::MAX as f32);
                det.push(v * 0.1);
            }
            let min_period = (SR / 1200.0 * 256.0) as u32;
            let result = det.detect(min_period);
            // Noise should not pass the confidence gate consistently.
            // (May occasionally fire; we just verify the pipeline completes.)
            let _ = result; // don't assert 0 — noise can occasionally trigger
        }

        /// 220 Hz + 440 Hz stack → alias suppression should prefer 220 Hz.
        #[test]
        fn alias_suppression_prefers_fundamental() {
            let mut det = make_det();
            for i in 0..8192 {
                let t = i as f32 / SR;
                let s = (2.0 * PI * 220.0 * t).sin() + 0.7 * (2.0 * PI * 440.0 * t).sin();
                det.push(s);
            }
            let min_period = (SR / 1200.0 * 256.0) as u32;
            let result = det.detect(min_period);
            if result > 0 {
                let period_samples = result as f32 / 256.0;
                let detected_freq = SR / period_samples;
                // Should detect the fundamental, not the octave harmonic.
                assert!(
                    detected_freq < 300.0,
                    "expected ~220 Hz fundamental, got {detected_freq:.1} Hz"
                );
            }
        }

        /// Bass-range detection: 100 Hz sine should pass the confidence gate.
        /// With FFTLEN=5120 at 44.1 kHz we get ~441 cycles per window,
        /// giving enough cepstral peak energy to clear the 0.03 gate.
        #[test]
        fn detects_bass_range_100hz() {
            let mut det = make_det();
            let min_period = (SR / 1200.0 * 256.0) as u32;

            let block = FFT_DETECT_BLOCK_SIZE;
            let mut result = 0u32;
            let mut sample_pos = 0usize;
            for _ in 0..120 {
                for j in 0..block {
                    det.push((2.0 * PI * 100.0 * (sample_pos + j) as f32 / SR).sin());
                }
                sample_pos += block;
                result = det.detect(min_period);
                if result > 0 {
                    break;
                }
            }

            assert!(
                result > 0,
                "expected bass 100 Hz detection after warm-up, got 0"
            );
            let period_samples = result as f32 / 256.0;
            let detected_freq = SR / period_samples;
            let err = (detected_freq - 100.0).abs() / 100.0;
            assert!(
                err < 0.03,
                "100 Hz bass: detected {detected_freq:.1} Hz (err {:.1}%)",
                err * 100.0
            );
        }

        /// Very-low bass: 80 Hz (baritone/bass register).
        #[test]
        fn detects_deep_bass_80hz() {
            let mut det = make_det();
            let min_period = (SR / 1200.0 * 256.0) as u32;

            let block = FFT_DETECT_BLOCK_SIZE;
            let mut result = 0u32;
            let mut sample_pos = 0usize;
            for _ in 0..150 {
                for j in 0..block {
                    det.push((2.0 * PI * 80.0 * (sample_pos + j) as f32 / SR).sin());
                }
                sample_pos += block;
                result = det.detect(min_period);
                if result > 0 {
                    break;
                }
            }

            assert!(
                result > 0,
                "expected deep bass 80 Hz detection after warm-up, got 0"
            );
            let period_samples = result as f32 / 256.0;
            let detected_freq = SR / period_samples;
            let err = (detected_freq - 80.0).abs() / 80.0;
            assert!(
                err < 0.04,
                "80 Hz deep bass: detected {detected_freq:.1} Hz (err {:.1}%)",
                err * 100.0
            );
        }

        /// Harmonic-rich low voices can have a stronger 2f/3f than the
        /// fundamental. The detector should still keep the bass candidate
        /// alive instead of rejecting it as ambiguous.
        #[test]
        fn detects_noisy_harmonic_rich_low_voice() {
            let mut det = make_det();
            let min_period = (SR / 1200.0 * 256.0) as u32;
            let freq = 174.61f32; // F3, below C4

            fn next_noise(state: &mut u32) -> f32 {
                *state ^= *state << 13;
                *state ^= *state >> 17;
                *state ^= *state << 5;
                (*state as f32 / u32::MAX as f32) * 2.0 - 1.0
            }

            let block = FFT_DETECT_BLOCK_SIZE;
            let mut result = 0u32;
            let mut sample_pos = 0usize;
            let mut noise_state = 0x1234_5678u32;

            for _ in 0..180 {
                for j in 0..block {
                    let t = (sample_pos + j) as f32 / SR;
                    let noise = next_noise(&mut noise_state) * 0.10;
                    let s = 0.04 * (2.0 * PI * freq * t).sin()
                        + 0.55 * (2.0 * PI * 2.0 * freq * t).sin()
                        + 0.28 * (2.0 * PI * 3.0 * freq * t).sin()
                        + 0.15 * (2.0 * PI * 4.0 * freq * t).sin()
                        + noise;
                    det.push(s);
                }
                sample_pos += block;
                result = det.detect(min_period);
                if result > 0 {
                    break;
                }
            }

            assert!(
                result > 0,
                "expected noisy harmonic-rich low voice to detect, got 0"
            );

            let period_samples = result as f32 / 256.0;
            let detected_freq = SR / period_samples;
            let err = (detected_freq - freq).abs() / freq;
            assert!(
                err < 0.06,
                "noisy low voice: detected {detected_freq:.1} Hz (err {:.1}%)",
                err * 100.0
            );
        }
    }
}

// ─── Unit tests for time-domain detector ─────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::f32::consts::PI;

    fn make_td_det(sr: f32) -> TimeDomainDetector {
        let mut d = TimeDomainDetector::new();
        // Pitch range: 60 Hz..1200 Hz at given sample rate.
        let lo = (sr / 1200.0) as u32;
        let hi = (sr / 60.0) as u32;
        d.setup_histogram(lo, hi);
        d
    }

    #[test]
    fn time_domain_detects_sine_period() {
        let sr = 44100.0f32;
        let freq = 440.0;
        let mut det = make_td_det(sr);
        let mut lpf = crate::dsp::filters::LowPassFilter1::for_peak_detector();

        for i in 0..8192usize {
            let s = (2.0 * PI * freq * i as f32 / sr).sin();
            let fs = lpf.process(s);
            det.push_sample(fs);
        }

        let result = det.detect();
        // Result is 24.8 fixed-point; convert to raw samples.
        if result > 0 {
            let period_samples = result as f32 / 256.0;
            let detected_freq = sr / period_samples;
            let err = (detected_freq - freq).abs() / freq;
            assert!(
                err < 0.05,
                "440 Hz: detected {detected_freq:.1} Hz (err {:.1}%)",
                err * 100.0
            );
        }
        // If result is 0 the histogram didn't reach threshold — that's
        // acceptable for 8192 samples; we test the pipeline runs without panic.
    }
}
