// VoiceWorklet — mic DSP pipeline.
//
// Runs in the AudioWorklet rendering thread. Implements (in JS):
//   HPF (2× cascaded biquad) → optional notch → gate → FFT pitch detection
//   → nearest-cell snap → throttled pitch events to main thread.
//
// Browser-native voice analysis and correction worklet.
//
// Messages FROM main thread:
//   { type: 'tuning_table', table: [{cell_id, period_24_8}] }
//   { type: 'gate_threshold', amp }       — linear 0..1
//   { type: 'notch_enable', enabled, period_samples, amp }
//
// Messages TO main thread (at ~60 Hz):
//   { type: 'pitch', cell_id, neighbor_id, neighbor_vel, gate_open, confidence }
//   { type: 'level', db }                 — gate level for the meter

'use strict';

// ─── Polyfill TextDecoder for AudioWorkletGlobalScope ─────────────────────────
// `TextDecoder` is not available in AudioWorkletGlobalScope (Safari, Chrome).
// wasm-bindgen glue code references it as a global during `eval`. We provide a
// minimal UTF-8 decoder so the glue can instantiate the WASM module and decode
// strings crossing the JS↔WASM boundary.
if (typeof globalThis.TextDecoder === 'undefined') {
  globalThis.TextDecoder = class {
    constructor() {}
    decode(buffer) {
      if (!buffer) return '';
      let str = '';
      for (let i = 0; i < buffer.length; i++) {
        const c = buffer[i];
        if (c < 0x80) {
          str += String.fromCharCode(c);
        } else if (c < 0xe0) {
          str += String.fromCharCode(((c & 0x1f) << 6) | (buffer[i+1] & 0x3f));
          i++;
        } else if (c < 0xf0) {
          str += String.fromCharCode(((c & 0x0f) << 12) | ((buffer[i+1] & 0x3f) << 6) | (buffer[i+2] & 0x3f));
          i += 2;
        } else {
          const codePoint = ((c & 0x07) << 18) | ((buffer[i+1] & 0x3f) << 12) | ((buffer[i+2] & 0x3f) << 6) | (buffer[i+3] & 0x3f);
          const offset = codePoint - 0x10000;
          str += String.fromCharCode(0xd800 + (offset >> 10), 0xdc00 + (offset & 0x3ff));
          i += 3;
        }
      }
      return str;
    }
  };
}

// ─── Detector constants ───────────────────────────────────────────────────────

const RAW_BUFFER_SIZE = 8192;   // audioRaw ring buffer (≥ FFTLEN, power-of-2 for wrap mask)
const FFTLEN          = 4096;   // FFT window — doubled from 2048 for bass-range cepstrum confidence
const HALF            = FFTLEN >>> 1;
const FFT_BLOCK       = 128;    // run detection every 128 samples
const PITCH_RATE_DIV  = Math.round(sampleRate / 60 / FFT_BLOCK); // throttle pitch events
const DEFAULT_GATE_THRESHOLD   = 0.02;
const MONITOR_ATTACK_SECONDS   = 0.015;
const MONITOR_RELEASE_SECONDS  = 0.180;
const LOW_NOTE_RELAX_START_HZ = 261.63; // C4 — start relaxing harmonic ambiguity below here
const LOW_NOTE_RELAX_END_HZ   = 80;     // strong relaxation by baritone/bass fundamentals
const LOW_NOTE_MAX_AMBIGUITY  = 0.65;
const LOW_NOTE_RELAX_BOOST    = 0.35;

// Project-tuned biquad HPF coefficients.
const HPF_K0 = -0.9907866988;
const HPF_K1 =  1.9907440595;

// ─── Filters ─────────────────────────────────────────────────────────────────

class BiquadHpf {
  constructor() {
    this.x = new Float64Array(3);
    this.y = new Float64Array(3);
  }
  process(input) {
    const {x, y} = this;
    x[2] = x[1]; x[1] = x[0]; x[0] = input;
    y[2] = y[1]; y[1] = y[0];
    y[0] = (x[0] + x[2]) - 2*x[1] + HPF_K0*y[2] + HPF_K1*y[1];
    return y[0];
  }
}

class CascadedHpf {
  constructor() { this.s1 = new BiquadHpf(); this.s2 = new BiquadHpf(); }
  process(x) { return this.s2.process(this.s1.process(x)); }
}

class NotchFilter {
  constructor() {
    this.buffer = new Float32Array(2);
    this.ptr    = 0;
    this.amp    = 0;
  }
  setPeriod(n) {
    this.buffer = new Float32Array(Math.max(2, n));
    this.ptr = 0;
  }
  process(input) {
    const buf = this.buffer;
    const len = buf.length;
    const delayed = buf[this.ptr];
    buf[this.ptr] = (1 - this.amp) * input + this.amp * delayed;
    this.ptr = (this.ptr + 1) % len;
    return input - delayed;
  }
}

// ─── Gate ─────────────────────────────────────────────────────────────────────

class Gate {
  constructor() {
    this.loAmp      = 0;
    this.hiAmp      = 0;
    this.currentAmp = 0;
    this.gateOnAmp  = 0;
    this.gateOffAmp = -1;
    this.open       = false;
    this.count      = 0;
  }
  setThreshold(amp) {
    this.gateOnAmp  = amp;
    this.gateOffAmp = amp * (15 / 16);
  }
  process(s) {
    if (s < this.loAmp) this.loAmp = s;
    if (s > this.hiAmp) this.hiAmp = s;
    if (++this.count >= 128) {
      this.count = 0;
      const pp = this.hiAmp - this.loAmp;
      this.currentAmp = (pp + 3 * this.currentAmp) / 4;
      this.loAmp = this.hiAmp = s;
      if (this.currentAmp > this.gateOnAmp)  this.open = true;
      else if (this.currentAmp < this.gateOffAmp) this.open = false;
    }
    return this.open;
  }
}

// ─── PSOLA pitch corrector ────────────────────────────────────────────────────

class PsolaRepitcher {
  constructor(bufSize = 16384) {
    this._buf = new Float32Array(bufSize);
    this._mask = bufSize - 1; // power-of-2, bitwise wrap
    this._writePtr = 0;
    this._readPtr = 0.0;
    this._actualPeriod = 0.0; // in samples
    this._targetPeriod = 0.0;
    this._rate = 1.0;
    this._xfade = 0.0;
    this._xfadeRate = 0.0;
    this._xoffset = 0.0;
    this._outVolume = 0.0;
    this._LOW_LIMIT = 1350;
    this._HIGH_LIMIT = 2700;
    this._ATTACK_RATE = 6 / 16384;
  }

  push(sample) {
    this._buf[this._writePtr++ & this._mask] = sample;
  }

  setActualPeriod(period_24_8) { this._actualPeriod = period_24_8 / 256.0; }
  setTargetPeriod(period_24_8) { this._targetPeriod = period_24_8 / 256.0; }

  _readInterp(ptr) {
    const floorPtr = Math.floor(ptr);
    const i0 = floorPtr & this._mask;
    const i1 = (i0 + 1) & this._mask;
    const f = ptr - floorPtr;
    return this._buf[i0] + (this._buf[i1] - this._buf[i0]) * f;
  }

  _availableSamples() {
    return (this._writePtr - Math.floor(this._readPtr)) | 0;
  }

  getSample() {
    const ap = this._actualPeriod, tp = this._targetPeriod;
    if (ap === 0 || tp === 0) {
      const s = this._readInterp(this._readPtr);
      this._readPtr += 1.0;
      this._outVolume = Math.max(0, this._outVolume - this._ATTACK_RATE * 4);
      return s * this._outVolume;
    }

    const targetRate = ap / tp;
    const step = 0.001;
    if (this._rate < targetRate) this._rate = Math.min(this._rate + step, targetRate);
    else if (this._rate > targetRate) this._rate = Math.max(this._rate - step, targetRate);

    let sample;
    if (this._xfade > 0) {
      const w2 = this._xfade;
      const w1 = 1.0 - w2;
      sample = this._readInterp(this._readPtr + this._xoffset) * w2
             + this._readInterp(this._readPtr) * w1;
      this._readPtr += this._rate;
      this._xfade -= this._xfadeRate;
      if (this._xfade < 0) this._xfade = 0;
    } else {
      sample = this._readInterp(this._readPtr);
      this._readPtr += this._rate;

      const avail = this._availableSamples();
      if (avail < this._LOW_LIMIT) {
        this._xoffset = ap;
        this._readPtr -= ap;
        this._xfadeRate = 1.0 / ap;
        this._xfade = 1.0 - this._xfadeRate;
      } else if (avail > this._HIGH_LIMIT) {
        this._xoffset = -ap;
        this._readPtr += ap;
        this._xfadeRate = 1.0 / ap;
        this._xfade = 1.0 - this._xfadeRate;
      }
    }

    this._outVolume = Math.min(1.0, this._outVolume + this._ATTACK_RATE);
    return sample * this._outVolume;
  }

  reset() {
    this._buf.fill(0);
    this._writePtr = 0;
    this._readPtr = 0;
    this._xfade = 0;
    this._rate = 1.0;
    this._outVolume = 0;
  }
}

// ─── FFT (Cooley-Tukey radix-2, in-place, complex) ───────────────────────────

function fftInPlace(re, im) {
  const n = re.length;
  // Bit-reversal permutation.
  let j = 0;
  for (let i = 1; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      let t = re[i]; re[i] = re[j]; re[j] = t;
      t = im[i]; im[i] = im[j]; im[j] = t;
    }
  }
  // Butterfly.
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len;
    const wr0 = Math.cos(ang), wi0 = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let wr = 1, wi = 0;
      for (let k = 0; k < len >> 1; k++) {
        const ur = re[i+k],          ui = im[i+k];
        const vr = re[i+k+len/2]*wr - im[i+k+len/2]*wi;
        const vi = re[i+k+len/2]*wi + im[i+k+len/2]*wr;
        re[i+k]         = ur + vr;   im[i+k]         = ui + vi;
        re[i+k+len/2]   = ur - vr;   im[i+k+len/2]   = ui - vi;
        const nwr = wr*wr0 - wi*wi0;
        wi = wr*wi0 + wi*wr0; wr = nwr;
      }
    }
  }
}

function ifftInPlace(re, im) {
  const n = re.length;
  for (let i = 0; i < n; i++) im[i] = -im[i];
  fftInPlace(re, im);
  for (let i = 0; i < n; i++) { re[i] /= n; im[i] = -(im[i] / n); }
}

// ─── Integer log mapping ──────────────────────────────────────────────────────

function ilog(x) {
  if (x === 0) return 0;
  const nb = 32 - Math.clz32(x);   // bit length
  return nb <= 6 ? x : ((nb - 6) << 5) | (x >>> (nb - 6));
}

// ─── FFT Pitch Detector ───────────────────────────────────────────────────────

class FftPitchDetector {
  constructor() {
    this.audioRaw  = new Float32Array(RAW_BUFFER_SIZE);
    this.wptr      = 0;

    // Hann window + window-bias correction.
    this.hannWin   = new Float32Array(FFTLEN);
    this.fftCorr   = new Float32Array(HALF);
    this.fftTavg   = new Float32Array(HALF + 2);

    // Working buffers for the FFT.
    this._re = new Float64Array(FFTLEN);
    this._im = new Float64Array(FFTLEN);

    this._initWindowAndCorr();
  }

  push(sample) {
    this.audioRaw[this.wptr & (RAW_BUFFER_SIZE - 1)] = sample;
    this.wptr++;
  }

  /** Run detection. Returns 24.8 fixed-point period or 0. */
  detect(lowestPeriod24_8) {
    this._calcSpectrum();
    return this._pitchDetection(lowestPeriod24_8);
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  _initWindowAndCorr() {
    const n = FFTLEN;
    for (let i = 0; i < n; i++) {
      this.hannWin[i] = 0.5 * (1 - Math.cos(2 * Math.PI * i / n));
    }
    // Window autocorrelation: FFT(window) → magnitudes → IFFT.
    const re = this._re, im = this._im;
    for (let i = 0; i < n; i++) { re[i] = this.hannWin[i]; im[i] = 0; }
    fftInPlace(re, im);
    // Magnitudes of first HALF bins into IFFT real input.
    const re2 = new Float64Array(n), im2 = new Float64Array(n);
    for (let i = 0; i < HALF; i++) {
      const mag = Math.sqrt(re[i]*re[i] + im[i]*im[i]);
      re2[i] = mag;
      if (i > 0) re2[n - i] = mag;  // conjugate symmetry
    }
    ifftInPlace(re2, im2);
    const t = Math.abs(re2[0]) + 0.1;
    for (let i = 0; i < HALF; i++) {
      this.fftCorr[i] = Math.max(1e-9, Math.abs(re2[i]) / t);
    }
  }

  _calcSpectrum() {
    const n = FFTLEN, raw = this.audioRaw, win = this.hannWin;
    const re = this._re, im = this._im;
    const j = (this.wptr - n) & (RAW_BUFFER_SIZE - 1);
    for (let i = 0; i < n; i++) {
      re[i] = win[i] * raw[(j + i) & (RAW_BUFFER_SIZE - 1)];
      im[i] = 0;
    }
    fftInPlace(re, im);
  }

  _pitchDetection(lowestPeriod24_8) {
    const re = this._re, im = this._im;
    const n  = FFTLEN;

    // Sqrt-magnitude spectrum → IFFT (cepstrum approximation).
    const re2 = new Float64Array(n), im2 = new Float64Array(n);
    for (let i = 0; i < HALF; i++) {
      const mag = Math.sqrt(re[i]*re[i] + im[i]*im[i]);
      re2[i] = mag;
      if (i > 0) re2[n - i] = mag;
    }
    ifftInPlace(re2, im2);
    // tdata = real part of IFFT, clipped to ≥ 0 after bias removal.
    const tdata = re2;   // alias

    // How many lags to inspect (lowest pitch = sample_rate/60).
    const limit = Math.min(
      Math.ceil(sampleRate / 60) + 1,
      Math.floor(n * 2 / 5),
      tdata.length
    );

    // Window-bias removal.
    const t = Math.abs(tdata[0]) + 0.1;
    for (let i = 0; i < limit; i++) {
      tdata[i] = Math.max(0, tdata[i] / (t * this.fftCorr[i]));
    }

    // Alias suppression: k ∈ {2,3,5,7}, iterate i downward.
    const _interp = (data, index, denom) => {
      const idx = 2*index - denom + 1;
      const d2  = denom * 2;
      if (idx < 0) return data[0];
      const ix = Math.floor(idx / d2);
      const iy = idx % d2;
      if (ix + 1 >= data.length) return data[data.length - 1] || 0;
      return data[ix] + (data[ix+1] - data[ix]) * iy / d2;
    };
    for (const hno of [2, 3, 5, 7]) {
      for (let i = limit - 1; i >= 0; i--) {
        tdata[i] = Math.max(0, tdata[i] - _interp(tdata, i, hno));
      }
    }

    // Log-bin EMA decay.
    const tavg = this.fftTavg;
    const avgMax = ilog(limit) + 2;
    for (let i = 0; i < Math.min(avgMax, tavg.length); i++) tavg[i] *= 0.75;

    // Find peaks; track global and second peak; update EMA.
    let i = 1;
    while (i < limit && tdata[i] > 0) i++;

    let peakIndex = 0, globalPeak = 0, secondPeak = 0;
    const minLag = (lowestPeriod24_8 >>> 8);

    while (i < limit) {
      while (i < limit && tdata[i] <= 0) i++;
      if (i >= limit) break;

      let jm = i, apeak = tdata[i];
      while (i < limit && tdata[i] > 0) {
        if (tdata[i] > apeak) { apeak = tdata[i]; jm = i; }
        i++;
      }

      if (jm >= minLag && apeak > 0.1) {
        const aindex = Math.min(ilog(jm) + 1, tavg.length - 1);
        const cpeak  = apeak * tavg[aindex];
        if (cpeak > globalPeak)       { secondPeak = globalPeak; globalPeak = cpeak; peakIndex = jm; }
        else if (cpeak > secondPeak)  { secondPeak = cpeak; }

        tavg[aindex] += apeak;
        for (let k = 1; k <= 6; k++) {
          const m = apeak / Math.pow(1.1, k*k);
          if (aindex >= k)                      tavg[aindex - k] += m;
          if (aindex + k < tavg.length)         tavg[aindex + k] += m;
        }
      }
    }

    // Two-tier confidence gate. Below C4, let a stronger competing harmonic
    // coexist before we reject the candidate — bass/baritone voices often
    // carry a much stronger overtone than the fundamental.
    if (!peakIndex || globalPeak <= 0.03) return 0;
    const baseAmbiguityLimit = Math.min(globalPeak * 0.6 + 0.14, 0.5);
    const bassStart = sampleRate / LOW_NOTE_RELAX_START_HZ;
    const bassEnd   = sampleRate / LOW_NOTE_RELAX_END_HZ;
    const bassBlend = bassEnd > bassStart
      ? Math.max(0, Math.min(1, (peakIndex - bassStart) / (bassEnd - bassStart)))
      : 0;
    const ambiguityLimit = Math.min(
      LOW_NOTE_MAX_AMBIGUITY,
      baseAmbiguityLimit + Math.sqrt(bassBlend) * LOW_NOTE_RELAX_BOOST,
    );
    if (secondPeak / globalPeak >= ambiguityLimit) return 0;

    // Parabolic LSQ sub-sample interpolation.
    const thr  = tdata[peakIndex] * 0.5;
    const pklI = Math.floor(peakIndex * 3 / 4);
    const pkrI = Math.ceil(peakIndex  * 5 / 4);

    let pkl = peakIndex;
    while (pkl > pklI && tdata[pkl] >= thr) pkl--;
    pkl++;
    let pkr = peakIndex + 1;
    while (pkr <= Math.min(pkrI, limit - 1) && tdata[pkr] >= thr) pkr++;
    pkr--;

    const pkw = pkr - pkl + 1;
    if (pkw < 3) return 0;

    const w2 = pkw * pkw;
    const s20 = (w2 - 1) / 3;
    const s42 = (3*w2 - 7) / 5;
    let b0 = 0, b1 = 0, b2 = 0;
    let x = -(pkw - 1);
    for (let idx = pkl; idx <= pkr; idx++) {
      const y = tdata[idx];
      b0 += y; b1 += x*y; b2 += x*x*y;
      x += 2;
    }
    const z1 = b1 * (s42 - s20);
    const z2 = b2 - s20 * b0;
    if (z2 >= -1e-10) return 0;

    const period = 0.5 * (pkl + pkr + 1) - z1 / (2 * z2);
    if (period < sampleRate / 1200 || period > sampleRate / 60) return 0;
    return (period * 256 + 0.5) | 0;
  }
}

// ─── Nearest-cell snap ────────────────────────────────────────────────────────

function nearestEnabledCell(sortedTable, period24_8, lastCellId) {
  const n = sortedTable.length;
  if (n === 0) return null;

  // Binary search: first index where period > period24_8.
  let lo = 0, hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (sortedTable[mid].period <= period24_8) lo = mid + 1; else hi = mid;
  }
  const pos = lo;

  let primaryIdx;
  if (pos === 0) {
    primaryIdx = 0;
  } else if (pos === n) {
    primaryIdx = n - 1;
  } else {
    let dBelow = period24_8 - sortedTable[pos-1].period;
    let dAbove = sortedTable[pos].period - period24_8;
    if (lastCellId != null) {
      if (sortedTable[pos-1].cell_id === lastCellId) dBelow >>>= 1;
      if (sortedTable[pos].cell_id   === lastCellId) dAbove >>>= 1;
    }
    // Strict < : ties go to above, matching C++ `if (a1 < a2) key = i1 else key = i2`.
    primaryIdx = dBelow < dAbove ? pos - 1 : pos;
  }

  const primary = sortedTable[primaryIdx];

  // Neighbor: adjacent cell in the sorted table, velocity proportional to distance.
  let neighbor = null;
  if (n > 1) {
    const below = primaryIdx > 0   ? sortedTable[primaryIdx - 1] : null;
    const above = primaryIdx < n-1 ? sortedTable[primaryIdx + 1] : null;
    if (below && above) {
      const a2 = Math.max(0, period24_8 - below.period);
      const a3 = Math.max(0, above.period - period24_8);
      const total = a2 + a3;
      if (a2 <= a3) {
        neighbor = { cell_id: below.cell_id, vel: total > 0 ? a3 / total : 0.5 };
      } else {
        neighbor = { cell_id: above.cell_id, vel: total > 0 ? a2 / total : 0.5 };
      }
    } else if (below) {
      neighbor = { cell_id: below.cell_id, vel: 0.5 };
    } else {
      neighbor = { cell_id: above.cell_id, vel: 0.5 };
    }
  }

  return { primary: primary.cell_id, period: primary.period, neighbor };
}

// ─── VoiceProcessor (AudioWorkletProcessor) ───────────────────────────────────

class VoiceProcessor extends AudioWorkletProcessor {
  constructor() {
    super();

    this._hpf        = new CascadedHpf();
    this._notch      = new NotchFilter();
    this._notchOn    = false;
    this._gate       = new Gate();
    this._gate.setThreshold(DEFAULT_GATE_THRESHOLD);
    this._det        = new FftPitchDetector();
    this._psola      = new PsolaRepitcher();
    this._monitorGain = 0;
    this._monitorAttackInc = 1 / Math.max(1, MONITOR_ATTACK_SECONDS * sampleRate);
    this._monitorReleaseInc = 1 / Math.max(1, MONITOR_RELEASE_SECONDS * sampleRate);

    // Tuning: [{cell_id, period}] sorted by period ascending.
    this._tuning     = [];
    this._lastCellId = null;

    this._lastActualPeriod = 0;
    this._lastTargetPeriod = 0;

    this._blockCount = 0;   // counts FFT_BLOCK-sample blocks
    this._pitchDiv   = 0;   // sub-divides to ~60 Hz pitch events

    // WASM VoiceProcessor — null until init_wasm message is received and resolved.
    this._wasmReady  = false;
    this._wasmProc   = null;

    this.port.onmessage = ({ data }) => this._dispatch(data);
  }

  _dispatch(msg) {
    switch (msg.type) {
      case 'tuning_table': {
        // Table arrives as [{cell_id, period_24_8}]; sort by period.
        this._tuning = [...msg.table].sort((a, b) => a.period_24_8 - b.period_24_8)
          .map(e => ({ cell_id: e.cell_id, period: e.period_24_8 }));
        if (this._wasmReady) this._syncWasmTuning();
        break;
      }
      case 'gate_threshold':
        this._gate.setThreshold(msg.amp);
        if (this._wasmReady && this._wasmProc) this._wasmProc.setGateThreshold(msg.amp);
        break;
      case 'notch_enable':
        this._notchOn = msg.enabled;
        if (msg.period_samples) this._notch.setPeriod(msg.period_samples);
        if (msg.amp != null)    this._notch.amp = msg.amp;
        if (this._wasmReady && this._wasmProc) {
          this._wasmProc.setNotchEnabled(msg.enabled);
          if (msg.period_samples || msg.amp != null) {
            this._wasmProc.setNotchParams(
              msg.period_samples || this._notch.buffer.length,
              msg.amp != null ? msg.amp : this._notch.amp,
            );
          }
        }
        break;
      case 'init_wasm':
        this._initWasm(msg.glueText, msg.wasmBuffer);
        break;
      case 'init_wasm_failed':
        this.port.postMessage({ type: 'dsp_path', path: 'js', error: msg.error });
        break;
    }
  }

  // Evaluate the wasm-bindgen no-modules glue text in a function scope so
  // its top-level `let wasm_bindgen = (...)` binding can be captured and
  // returned. Then initialise the Rust VoiceProcessor from the transferred
  // ArrayBuffer. Safari's AudioWorkletGlobalScope does not expose
  // `importScripts` or `fetch`, so all network I/O happens on the main
  // thread and bytes are transferred here. Falls back to JS DSP on failure.
  _initWasm(glueText, wasmBuffer) {
    const reportPath = (path, error) =>
      this.port.postMessage({ type: 'dsp_path', path, error: error ? String(error) : undefined });

    let bindgen;
    try {
      bindgen = new Function('TextDecoder', glueText + '\nreturn wasm_bindgen;')(globalThis.TextDecoder);
    } catch (e) {
      console.warn('[voice-worklet] glue eval failed, continuing with JS DSP:', e);
      reportPath('js', e);
      return;
    }

    bindgen(wasmBuffer).then(() => {
      const sr = sampleRate;
      this._wasmProc = new bindgen.VoiceProcessor(sr, this._gate.gateOnAmp || DEFAULT_GATE_THRESHOLD);
      this._wasmProc.setNotchEnabled(this._notchOn);
      this._wasmProc.setNotchParams(this._notch.buffer.length, this._notch.amp);
      this._syncWasmTuning();
      this._wasmReady = true;
      console.log('[voice-worklet] WASM VoiceProcessor ready');
      reportPath('wasm');
    }).catch(err => {
      console.warn('[voice-worklet] WASM instantiate failed, continuing with JS DSP:', err);
      reportPath('js', err);
    });
  }

  // Push the current tuning table into the WASM VoiceProcessor.
  _syncWasmTuning() {
    if (!this._wasmProc || !this._tuning.length) return;
    const ids     = new Int32Array(this._tuning.map(e => e.cell_id));
    const periods = new Uint32Array(this._tuning.map(e => e.period));
    this._wasmProc.setTuning(ids, periods);
  }

  _stepMonitorGain(gateOpen) {
    if (gateOpen) {
      this._monitorGain = Math.min(1, this._monitorGain + this._monitorAttackInc);
    } else {
      this._monitorGain = Math.max(0, this._monitorGain - this._monitorReleaseInc);
    }
    return this._monitorGain;
  }

  process(inputs, outputs) {
    const input  = inputs[0]?.[0];
    const output = outputs[0]?.[0];
    if (!input) return true;

    if (this._wasmReady && this._wasmProc) {
      return this._processWasm(input, output);
    }
    return this._processJs(input, output);
  }

  // Original JS DSP path — HPF → notch → gate → FFT pitch detect.
  // Monitor output is the HPF'd dry signal, continuous. PSOLA output is
  // intentionally NOT routed here: its volume envelope fades on every
  // detection miss, producing the "breaking up" stutter that makes the
  // monitor unusable. PSOLA correction will be reintroduced on a separate
  // output channel once the detector feeds it a valid target period.
  _processJs(input, output) {
    const n = input.length;  // 128 per render quantum

    for (let i = 0; i < n; i++) {
      let s = this._hpf.process(input[i]);
      if (this._notchOn) s = this._notch.process(s);
      const gateOpen = this._gate.process(s);
      this._det.push(s);

      if (output) output[i] = s * this._stepMonitorGain(gateOpen);
    }

    // Run pitch detection every FFT_BLOCK samples (= every render quantum).
    if (++this._blockCount >= PITCH_RATE_DIV) {
      this._blockCount = 0;
      this._runPitchAndEmit();
    }

    return true;
  }

  // WASM DSP path — delegates filtering, gate, pitch detection, and PSOLA to Rust.
  _processWasm(input, output) {
    const proc = this._wasmProc;

    // One boundary crossing per render quantum instead of 128 — critical
    // for mobile Safari, which otherwise runs out of quantum budget.
    if (output) proc.processBlockInto(input, output);
    else proc.processBlock(input);

    // Emit pitch events at ~60 Hz (same throttle as JS path).
    if (++this._blockCount >= PITCH_RATE_DIV) {
      this._blockCount = 0;

      const gateOpen    = proc.gateOpen();
      const levelAmp    = proc.currentLevel ? proc.currentLevel() : 0;
      let period24_8    = 0;
      let cellId        = -1;
      let neighborId    = -1;
      let neighborVel   = 0;

      if (gateOpen && this._tuning.length > 0) {
        period24_8 = proc.detectPitch();
        if (period24_8 > 0) {
          const snap = nearestEnabledCell(this._tuning, period24_8, this._lastCellId);
          if (snap) {
            cellId = snap.primary;
            this._lastCellId = cellId;
            if (snap.neighbor) {
              neighborId = snap.neighbor.cell_id;
              neighborVel = snap.neighbor.vel;
            }
          }
        }
      }

      if (!gateOpen || period24_8 === 0) {
        this._lastCellId = null;
        proc.resetHysteresis();
      }

      this.port.postMessage({
        type:         'pitch',
        cell_id:      cellId,
        neighbor_id:  neighborId,
        neighbor_vel: neighborVel,
        gate_open:    gateOpen,
        confidence:   period24_8 > 0 ? 1 : 0,
        period_24_8:  period24_8,
        detected_hz:  period24_8 > 0 ? (sampleRate * 256) / period24_8 : 0,
        level_amp:    levelAmp,
      });
    }

    return true;
  }

  _runPitchAndEmit() {
    const gateOpen = this._gate.open;
    let cellId    = -1;
    let neighborId = -1;
    let neighborVel = 0;
    let confidence  = 0;
    let detectedPeriod24_8 = 0;

    if (gateOpen && this._tuning.length > 0) {
      const minPeriod24_8 = Math.max(1, Math.floor(sampleRate / 1200 * 256));
      const period24_8    = this._det.detect(minPeriod24_8);
      detectedPeriod24_8 = period24_8;

      if (period24_8 > 0) {
        const snap = nearestEnabledCell(this._tuning, period24_8, this._lastCellId);
        if (snap) {
          cellId    = snap.primary;
          this._lastCellId = cellId;
          if (snap.neighbor) {
            neighborId  = snap.neighbor.cell_id;
            neighborVel = snap.neighbor.vel;
          }
          confidence = 1;

          if (period24_8 !== this._lastActualPeriod) {
            this._psola.setActualPeriod(period24_8);
            this._lastActualPeriod = period24_8;
          }
          const targetPeriod = snap.period;
          if (targetPeriod !== this._lastTargetPeriod) {
            this._psola.setTargetPeriod(targetPeriod);
            this._lastTargetPeriod = targetPeriod;
          }
        } else {
          this._psola.setActualPeriod(0);
          this._lastActualPeriod = 0;
        }
      } else {
        this._psola.setActualPeriod(0);
        this._lastActualPeriod = 0;
      }
    } else if (!gateOpen) {
      this._lastCellId = null;
      if (this._lastActualPeriod !== 0 || this._lastTargetPeriod !== 0) {
        this._psola.setActualPeriod(0);
        this._psola.setTargetPeriod(0);
        this._lastActualPeriod = 0;
        this._lastTargetPeriod = 0;
      }
    }

    this.port.postMessage({
      type:        'pitch',
      cell_id:     cellId,
      neighbor_id: neighborId,
      neighbor_vel: neighborVel,
      gate_open:   gateOpen,
      confidence,
      period_24_8: detectedPeriod24_8,
      detected_hz: detectedPeriod24_8 > 0 ? (sampleRate * 256) / detectedPeriod24_8 : 0,
      level_amp:   this._gate.currentAmp,
    });
  }
}

registerProcessor('voice-processor', VoiceProcessor);
