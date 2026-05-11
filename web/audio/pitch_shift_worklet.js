// PitchShiftProcessor - lightweight dual-delay pitch shifter for reference audio.
//
// This keeps playbackRate available for tempo changes while applying a separate
// pitch ratio in the WebAudio graph. It is intentionally modest: good enough
// for chant reference practice without pulling in a large time-stretch library.

const BUFFER_LEN = 32768;
const GRAIN_SIZE = 2048;
const TWO_PI = Math.PI * 2;

class PitchShiftProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffers = [];
    this._writeIndex = 0;
    this._phase = 0;
    this._ratio = 1;

    this.port.onmessage = ({ data }) => {
      if (data?.type === 'pitch_shift') {
        const moria = Number.isFinite(data.moria) ? data.moria : 0;
        this._ratio = Math.pow(2, moria / 72);
      }
    };
  }

  process(inputs, outputs) {
    const input = inputs[0] || [];
    const output = outputs[0] || [];
    const channelCount = Math.max(output.length, input.length, 1);
    this._ensureBuffers(channelCount);

    const n = output[0]?.length || input[0]?.length || 128;
    const ratio = this._ratio;
    const shifted = Math.abs(ratio - 1) > 0.0001;
    const phaseInc = shifted ? Math.max(0.00002, Math.abs(ratio - 1) / GRAIN_SIZE) : 0;

    for (let i = 0; i < n; i++) {
      const phaseA = this._phase;
      const phaseB = (phaseA + 0.5) % 1;
      const delayA = ratio >= 1 ? (1 - phaseA) * GRAIN_SIZE : phaseA * GRAIN_SIZE;
      const delayB = ratio >= 1 ? (1 - phaseB) * GRAIN_SIZE : phaseB * GRAIN_SIZE;
      const gainA = this._hann(phaseA);
      const gainB = this._hann(phaseB);

      for (let ch = 0; ch < output.length; ch++) {
        const inCh = input[ch] || input[0];
        const sample = inCh ? inCh[i] || 0 : 0;
        const buffer = this._buffers[ch];

        output[ch][i] = shifted
          ? this._readDelay(buffer, delayA) * gainA + this._readDelay(buffer, delayB) * gainB
          : sample;
        buffer[this._writeIndex] = sample;
      }

      this._writeIndex = (this._writeIndex + 1) % BUFFER_LEN;
      if (shifted) this._phase = (this._phase + phaseInc) % 1;
      else this._phase = 0;
    }

    return true;
  }

  _ensureBuffers(channelCount) {
    while (this._buffers.length < channelCount) {
      this._buffers.push(new Float32Array(BUFFER_LEN));
    }
  }

  _readDelay(buffer, delay) {
    let idx = this._writeIndex - delay;
    while (idx < 0) idx += BUFFER_LEN;
    const i0 = Math.floor(idx) % BUFFER_LEN;
    const i1 = (i0 + 1) % BUFFER_LEN;
    const frac = idx - Math.floor(idx);
    return buffer[i0] * (1 - frac) + buffer[i1] * frac;
  }

  _hann(phase) {
    return 0.5 - 0.5 * Math.cos(TWO_PI * phase);
  }
}

registerProcessor('pitch-shift-processor', PitchShiftProcessor);
