/* pitch_worklet.js — training-app AudioWorklet pitch detector (issue #80).
 *
 * The first "One App" slice (epic #45): route mic audio through the legacy
 * Byzantine app's battle-tested Rust/WASM detector instead of scope.js's JS
 * autocorrelation, behind a runtime flag (?detector=wasm). This is a MINIMAL
 * processor — it borrows only the `VoiceProcessor` from the shared
 * pkg-worklet bundle (src/worklet.rs), and only the raw pitch it exposes;
 * none of the legacy tuning/cell-snap/PSOLA machinery is wired here. The
 * output contract back to scope.js is a plain detected-Hz stream, so scope.js
 * keeps ownership of smoothing (median-of-3 + EMA), MIDI conversion, the
 * scope trace, and the {tSec, midi} pitch-sink — identical to the JS path.
 *
 * LOADING (mirrors web/audio/audio_engine.js + voice_worklet.js): the main
 * thread fetches the wasm-bindgen `no-modules` glue text + the .wasm bytes and
 * transfers them in via an `init_wasm` message. Safari's AudioWorkletGlobalScope
 * does not reliably expose importScripts/fetch, so ALL network I/O stays on the
 * main thread; the worklet just eval()s the glue and instantiates from bytes.
 *
 * MESSAGES
 *   in : { type:'init_wasm', glueText, wasmBuffer, gateThreshold }
 *        { type:'set_gate', amp }
 *   out: { type:'ready', sampleRate, rateDiv }
 *        { type:'init_failed', error }
 *        { type:'pitch', hz, gateOpen, level, seq, ct }   // ct = worklet audio time
 */

// ── Polyfill TextDecoder for AudioWorkletGlobalScope ─────────────────────────
// TextDecoder is absent in AudioWorkletGlobalScope (Chrome + Safari); the
// wasm-bindgen glue constructs one lazily to decode strings crossing the
// JS<->WASM boundary. Minimal UTF-8 decoder, lifted verbatim from the legacy
// web/audio/voice_worklet.js so behavior matches the shipped Byzantine app.
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
          str += String.fromCharCode(((c & 0x1f) << 6) | (buffer[i + 1] & 0x3f));
          i++;
        } else if (c < 0xf0) {
          str += String.fromCharCode(((c & 0x0f) << 12) | ((buffer[i + 1] & 0x3f) << 6) | (buffer[i + 2] & 0x3f));
          i += 2;
        } else {
          const codePoint = ((c & 0x07) << 18) | ((buffer[i + 1] & 0x3f) << 12) | ((buffer[i + 2] & 0x3f) << 6) | (buffer[i + 3] & 0x3f);
          const offset = codePoint - 0x10000;
          str += String.fromCharCode(0xd800 + (offset >> 10), 0xdc00 + (offset & 0x3ff));
          i += 3;
        }
      }
      return str;
    }
  };
}

// Detection cadence: the FFT detector runs off a 128-sample block; throttle the
// emitted pitch events to ~60 Hz, matching the legacy worklet's PITCH_RATE_DIV
// and the JS path's animation-frame cadence (so scope.js's downstream timing
// and scoring's maxGap assumptions see a comparable frame rate).
const FFT_BLOCK = 128;
const RATE_DIV = Math.max(1, Math.round(sampleRate / 60 / FFT_BLOCK));
const DEFAULT_GATE_THRESHOLD = 0.02;

class TrainingPitchDetector extends AudioWorkletProcessor {
  constructor() {
    super();
    this._proc = null;        // Rust VoiceProcessor once wasm is ready
    this._ready = false;
    this._blockCount = 0;
    this._seq = 0;
    this._scratch = null;     // reused filter-output buffer (no per-quantum alloc)
    this.port.onmessage = ({ data }) => this._onMessage(data);
  }

  _onMessage(msg) {
    if (!msg) return;
    if (msg.type === 'init_wasm') {
      this._initWasm(msg.glueText, msg.wasmBuffer, msg.gateThreshold);
    } else if (msg.type === 'set_gate' && this._proc) {
      this._proc.setGateThreshold(msg.amp);
    }
  }

  _initWasm(glueText, wasmBuffer, gateThreshold) {
    try {
      // Evaluate the no-modules glue in a function scope so its top-level
      // `let wasm_bindgen = (...)` binding can be captured and returned. The
      // glue references `TextDecoder` (provided) and, in browsers, guards its
      // own `document`/`fetch` auto-init behind a code path we never take —
      // we hand it the bytes directly via the modern `{ module_or_path }` form.
      const bindgen = new Function('TextDecoder', glueText + '\nreturn wasm_bindgen;')(globalThis.TextDecoder);
      bindgen({ module_or_path: wasmBuffer })
        .then(() => {
          this._proc = new bindgen.VoiceProcessor(sampleRate, gateThreshold || DEFAULT_GATE_THRESHOLD);
          this._ready = true;
          this.port.postMessage({ type: 'ready', sampleRate, rateDiv: RATE_DIV });
        })
        .catch((err) => {
          this.port.postMessage({ type: 'init_failed', error: String(err) });
        });
    } catch (err) {
      this.port.postMessage({ type: 'init_failed', error: String(err) });
    }
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!this._ready || !this._proc || !input) return true;

    // One boundary crossing per render quantum. We discard the filtered output
    // (the training app never monitors the mic) but processBlockInto still runs
    // the full HPF -> gate -> FFT-ring pipeline that detectPitch reads from.
    if (!this._scratch || this._scratch.length !== input.length) {
      this._scratch = new Float32Array(input.length);
    }
    this._proc.processBlockInto(input, this._scratch);

    if (++this._blockCount >= RATE_DIV) {
      this._blockCount = 0;
      const gateOpen = this._proc.gateOpen();
      const level = this._proc.currentLevel ? this._proc.currentLevel() : 0;
      let hz = 0;
      if (gateOpen) {
        const period24_8 = this._proc.detectPitch();   // 24.8 fixed-point period, 0 = no pitch
        if (period24_8 > 0) hz = (sampleRate * 256) / period24_8;
      }
      this.port.postMessage({
        type: 'pitch',
        hz,
        gateOpen,
        level,
        seq: ++this._seq,
        ct: currentTime,   // worklet audio-clock time at emission (latency probe)
      });
    }
    return true;
  }
}

registerProcessor('training-pitch-detector', TrainingPitchDetector);
