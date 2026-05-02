//! Worklet-bundle WASM exports (`feature = "worklet"`).
//!
//! This module exposes `VoiceProcessor` to the AudioWorklet's WASM instance.
//! See `docs/ARCHITECTURE.md §8.2` for how the worklet WASM is loaded.
//!
//! The JavaScript voice worklet (`web/audio/voice_worklet.js`) retains its
//! pure-JS DSP path as a fallback; when `web/pkg-worklet/` is present it
//! loads this module's `VoiceProcessor` via `importScripts` and delegates
//! the pipeline to Rust.

#[cfg(feature = "worklet")]
mod worklet_exports {
    const MONITOR_ATTACK_SECONDS: f32 = 0.015;
    const MONITOR_RELEASE_SECONDS: f32 = 0.180;

    use crate::dsp::{
        detector::{fft::FftDetector, TimeDomainDetector},
        filters::{CascadedHpf, LowPassFilter1, NotchFilter},
        gate::Gate,
        psola::PsolaRepitcher,
    };
    use crate::tuning::{nearest_enabled_cell, NearestCellResult};
    use wasm_bindgen::prelude::*;

    /// All-in-one voice DSP processor exposed to the AudioWorklet.
    ///
    /// Maintains all filter and detector state for one audio channel.
    /// The worklet calls `process_sample` for every input sample, then
    /// calls `detect_pitch` every 128 samples when the gate is open.
    #[wasm_bindgen]
    pub struct VoiceProcessor {
        hpf: CascadedHpf,
        notch: NotchFilter,
        notch_enabled: bool,
        gate: Gate,
        lpf: LowPassFilter1,
        td_det: TimeDomainDetector,
        fft_det: FftDetector,
        psola: PsolaRepitcher,
        // Tuning table: sorted (period_24_8, cell_id).
        tuning_table: Vec<(u32, i32)>,
        last_cell_id: Option<i32>,
        sample_rate: f32,
        sample_count: u32,
        monitor_gain: f32,
        monitor_attack_inc: f32,
        monitor_release_inc: f32,
    }

    #[wasm_bindgen]
    impl VoiceProcessor {
        /// Create a new voice processor.
        /// `gate_on_amp` is the linear amplitude threshold to open the gate.
        #[wasm_bindgen(constructor)]
        pub fn new(sample_rate: f32, gate_on_amp: f32) -> VoiceProcessor {
            let mut gate = Gate::new();
            gate.set_threshold(gate_on_amp);
            VoiceProcessor {
                hpf: CascadedHpf::new(),
                notch: NotchFilter::new(),
                notch_enabled: false,
                gate,
                lpf: LowPassFilter1::for_peak_detector(),
                td_det: TimeDomainDetector::new(),
                fft_det: FftDetector::new(sample_rate),
                psola: PsolaRepitcher::new(),
                tuning_table: Vec::new(),
                last_cell_id: None,
                sample_rate,
                sample_count: 0,
                monitor_gain: 0.0,
                monitor_attack_inc: 1.0 / (MONITOR_ATTACK_SECONDS * sample_rate).max(1.0),
                monitor_release_inc: 1.0 / (MONITOR_RELEASE_SECONDS * sample_rate).max(1.0),
            }
        }

        fn step_monitor_gain(&mut self, gate_open: bool) -> f32 {
            if gate_open {
                self.monitor_gain = (self.monitor_gain + self.monitor_attack_inc).min(1.0);
            } else {
                self.monitor_gain = (self.monitor_gain - self.monitor_release_inc).max(0.0);
            }
            self.monitor_gain
        }

        /// Apply the full preprocessing chain to one sample and push it into
        /// the FFT ring buffer. Returns the HPF-filtered sample.
        ///
        /// Prefer `processBlock` from AudioWorklet code — the per-sample wasm
        /// boundary crossing cost dominates on mobile Safari.
        #[wasm_bindgen(js_name = processSample)]
        pub fn process_sample(&mut self, input: f32) -> f32 {
            let filtered = self.hpf.process(input);
            let out = if self.notch_enabled {
                self.notch.process(filtered)
            } else {
                filtered
            };
            let gate_open = self.gate.process(out);
            // Time-domain path (LPF → peak machine → histogram).
            let lp = self.lpf.process(out);
            self.td_det.push_sample(lp);
            // FFT ring buffer.
            self.fft_det.push(out);
            self.sample_count = self.sample_count.wrapping_add(1);
            out * self.step_monitor_gain(gate_open)
        }

        /// Block variant of `process_sample`. Processes `input` in one wasm
        /// call and returns the filtered block. Use this from the AudioWorklet
        /// — a render quantum of 128 samples fits in a single boundary crossing.
        #[wasm_bindgen(js_name = processBlock)]
        pub fn process_block(&mut self, input: &[f32]) -> Vec<f32> {
            let mut out = Vec::with_capacity(input.len());
            for &x in input {
                out.push(self.process_sample(x));
            }
            out
        }

        /// In-place variant of `process_block`. Avoids allocating a fresh
        /// JS-facing typed array on every render quantum.
        #[wasm_bindgen(js_name = processBlockInto)]
        pub fn process_block_into(&mut self, input: &[f32], output: &mut [f32]) {
            let n = input.len().min(output.len());
            for i in 0..n {
                output[i] = self.process_sample(input[i]);
            }
            for x in &mut output[n..] {
                *x = 0.0;
            }
        }

        /// True when the gate is currently open.
        #[wasm_bindgen(js_name = gateOpen)]
        pub fn gate_open(&self) -> bool {
            self.gate.gate_open()
        }

        /// Smoothed peak-to-peak level used by the hysteretic gate.
        #[wasm_bindgen(js_name = currentLevel)]
        pub fn current_level(&self) -> f32 {
            self.gate.current_level()
        }

        /// Run pitch detection. Returns a 24.8 fixed-point period in samples,
        /// or 0 if no confident pitch is found.
        ///
        /// Should be called every 128 samples when the gate is open.
        /// Uses the FFT detector; the time-domain detector runs continuously
        /// inside `process_sample` as a warm-up path.
        #[wasm_bindgen(js_name = detectPitch)]
        pub fn detect_pitch(&mut self) -> u32 {
            let min_period = (self.sample_rate / 1200.0 * 256.0).max(1.0) as u32;
            self.fft_det.detect(min_period)
        }

        /// Snap a 24.8 fixed-point period to the nearest enabled cell in the
        /// tuning table. Returns the cell's moria id, or -1 if no cells are set.
        #[wasm_bindgen(js_name = nearestCell)]
        pub fn nearest_cell(&mut self, period_24_8: u32) -> i32 {
            let result = nearest_enabled_cell(&self.tuning_table, period_24_8, self.last_cell_id);
            match result {
                Some(r) => {
                    self.last_cell_id = Some(r.primary_id);
                    r.primary_id
                }
                None => -1,
            }
        }

        /// Full snap result: primary id, neighbor id (-1 if none), neighbor velocity.
        /// Returns flat [primary_id, neighbor_id, neighbor_vel * 1000] as i32 triple.
        #[wasm_bindgen(js_name = nearestCellFull)]
        pub fn nearest_cell_full(&mut self, period_24_8: u32) -> Vec<i32> {
            let result = nearest_enabled_cell(&self.tuning_table, period_24_8, self.last_cell_id);
            match result {
                Some(NearestCellResult {
                    primary_id,
                    neighbor_id,
                    neighbor_vel,
                }) => {
                    self.last_cell_id = Some(primary_id);
                    vec![
                        primary_id,
                        neighbor_id.unwrap_or(-1),
                        (neighbor_vel * 1000.0) as i32,
                    ]
                }
                None => vec![-1, -1, 0],
            }
        }

        /// Update the tuning table from flat arrays.
        /// `cell_ids` and `periods` must be the same length; `periods` are
        /// 24.8 fixed-point. Sorts internally — caller order doesn't matter.
        #[wasm_bindgen(js_name = setTuning)]
        pub fn set_tuning(&mut self, cell_ids: &[i32], periods: &[u32]) {
            self.tuning_table = periods
                .iter()
                .zip(cell_ids.iter())
                .map(|(&p, &id)| (p, id))
                .collect();
            self.tuning_table.sort_by_key(|(p, _)| *p);

            // Refresh the time-domain histogram range.
            if let (Some(&(lo, _)), Some(&(hi, _))) =
                (self.tuning_table.first(), self.tuning_table.last())
            {
                self.td_det.setup_histogram(lo, hi);
            }
        }

        /// Set gate open threshold (linear amplitude, 0.0..1.0).
        #[wasm_bindgen(js_name = setGateThreshold)]
        pub fn set_gate_threshold(&mut self, amp: f32) {
            self.gate.set_threshold(amp);
        }

        /// Enable or disable the notch filter.
        #[wasm_bindgen(js_name = setNotchEnabled)]
        pub fn set_notch_enabled(&mut self, enabled: bool) {
            self.notch_enabled = enabled;
        }

        /// Set the notch filter period in samples and feedback amplitude.
        #[wasm_bindgen(js_name = setNotchParams)]
        pub fn set_notch_params(&mut self, period_samples: u32, amp: f32) {
            self.notch.set_period(period_samples as usize);
            self.notch.set_amp(amp);
        }

        /// Reset the `last_cell_id` hysteresis (call when the user lifts a key).
        #[wasm_bindgen(js_name = resetHysteresis)]
        pub fn reset_hysteresis(&mut self) {
            self.last_cell_id = None;
        }

        // ── PSOLA pitch correction ──────────────────────────────────────────
        //
        // The repitcher is fed sample-by-sample inside `processBlockIntoStereo`
        // and produces one output sample per input sample. Period setters are
        // called from JS at pitch-event rate (~60 Hz).

        /// Update the PSOLA detected (actual) period in 24.8 fixed-point.
        #[wasm_bindgen(js_name = setActualPeriod)]
        pub fn set_actual_period(&mut self, period_24_8: u32) {
            self.psola.set_actual_period(period_24_8);
        }

        /// Update the PSOLA target (snapped cell) period in 24.8 fixed-point.
        /// Pass 0 to signal "no target" — PSOLA fades out.
        #[wasm_bindgen(js_name = setTargetPeriod)]
        pub fn set_target_period(&mut self, period_24_8: u32) {
            self.psola.set_target_period(period_24_8);
        }

        /// Reset PSOLA buffer + envelope state. Call when the gate closes for
        /// long enough that the in-flight buffer is no longer relevant.
        #[wasm_bindgen(js_name = resetPsola)]
        pub fn reset_psola(&mut self) {
            self.psola.reset();
        }

        /// Process one render quantum producing both the dry monitor channel
        /// and the PSOLA-corrected channel in a single boundary crossing.
        ///
        /// `dry_out` receives the same signal as `processBlockInto` (HPF →
        /// optional notch → monitor envelope). `psola_out` receives the
        /// pitch-corrected version of the same input (or fade-out silence
        /// when no target period is set).
        #[wasm_bindgen(js_name = processBlockIntoStereo)]
        pub fn process_block_into_stereo(
            &mut self,
            input: &[f32],
            dry_out: &mut [f32],
            psola_out: &mut [f32],
        ) {
            let n = input.len().min(dry_out.len()).min(psola_out.len());
            for i in 0..n {
                let filtered = self.hpf.process(input[i]);
                let post_notch = if self.notch_enabled {
                    self.notch.process(filtered)
                } else {
                    filtered
                };
                let gate_open = self.gate.process(post_notch);
                let lp = self.lpf.process(post_notch);
                self.td_det.push_sample(lp);
                self.fft_det.push(post_notch);
                self.psola.push_sample(post_notch);
                self.sample_count = self.sample_count.wrapping_add(1);

                let monitor_gain = self.step_monitor_gain(gate_open);
                dry_out[i] = post_notch * monitor_gain;
                // PSOLA already self-envelopes via its own out_volume; gate it
                // by the monitor envelope so it tracks the singer's onsets.
                psola_out[i] = self.psola.get_sample() * monitor_gain;
            }
            for x in &mut dry_out[n..] {
                *x = 0.0;
            }
            for x in &mut psola_out[n..] {
                *x = 0.0;
            }
        }
    }
}
