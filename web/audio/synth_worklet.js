// SynthWorklet — additive organ voice synthesizer.
//
// Runs in the AudioWorklet rendering thread. Accepts main-thread messages:
//   { type: 'tuning_table', table: [{cell_id, hz}] }
//   { type: 'noteOn',  cell_id, velocity }
//   { type: 'noteOff', cell_id }
//   { type: 'ison',    cell_id, volume }  (cell_id=null or volume=0 to disable)
//   { type: 'synth_follow', cell_id, volume }  (cell_id=null or volume=0 to disable)

const K = 8;       // harmonics per voice
const ALPHA = 1.2; // amplitude of kth harmonic = 1 / k^ALPHA
const MAX_VOICES = 16;
const ATTACK_S  = 0.005;
const RELEASE_S = 0.08;

// Harmonic amplitude tables, normalised to unit peak sum.
function _makeAmps(weights) {
  const s = weights.reduce((a, b) => a + b, 0);
  return new Float64Array(weights.map(w => w / s));
}

const VOICE_AMPS = _makeAmps(
  Array.from({ length: K }, (_, i) => 1 / Math.pow(i + 1, ALPHA))
);

const VOICE_MIX_GAIN = 4.0;

// Ison: richer lower harmonics, attenuated upper.
const ISON_AMPS = _makeAmps([1.0, 0.75, 0.55, 0.38, 0.26, 0.17, 0.11, 0.07]);

class Voice {
  constructor(cellId, hz, velocity, amps) {
    this.cellId  = cellId;
    this.hz      = hz;
    this.velocity = velocity;
    this.amps    = amps;
    this.phases  = new Float64Array(K);
    this.env     = 0;
    this.state   = 'attack'; // 'attack' | 'sustain' | 'release' | 'dead'
    this._attackInc  = 1 / (ATTACK_S  * sampleRate);
    this._releaseInc = 1 / (RELEASE_S * sampleRate);
  }

  release() {
    if (this.state !== 'dead') this.state = 'release';
  }

  setVelocity(velocity) {
    this.velocity = velocity;
  }

  get isDead() { return this.state === 'dead'; }

  renderInto(buf, len) {
    const hz  = this.hz;
    const vel = this.velocity;
    for (let i = 0; i < len; i++) {
      switch (this.state) {
        case 'attack':
          this.env += this._attackInc;
          if (this.env >= 1) { this.env = 1; this.state = 'sustain'; }
          break;
        case 'release':
          this.env -= this._releaseInc;
          if (this.env <= 0) { this.env = 0; this.state = 'dead'; return; }
          break;
        // 'sustain': env stays at 1
      }
      let s = 0;
      for (let k = 0; k < K; k++) {
        s += this.amps[k] * Math.sin(2 * Math.PI * this.phases[k]);
        this.phases[k] += hz * (k + 1) / sampleRate;
        if (this.phases[k] >= 1) this.phases[k] -= Math.trunc(this.phases[k]);
      }
      buf[i] += s * vel * this.env;
    }
  }
}

class SynthProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._voices           = []; // regular voices
    this._isonVoice        = null;
    this._followVoice      = null;
    this._followReleases   = [];
    this._tuning           = new Map(); // cell_id(moria) → hz
    this._correctionVolume = 0.5;

    this.port.onmessage = ({ data }) => this._dispatch(data);
  }

  _releaseFollowVoice() {
    if (!this._followVoice) return;
    this._followVoice.release();
    this._followReleases.push(this._followVoice);
    this._followVoice = null;
  }

  _dispatch(msg) {
    switch (msg.type) {
      case 'tuning_table': {
        this._tuning.clear();
        for (const { cell_id, hz } of msg.table) this._tuning.set(cell_id, hz);
        break;
      }
      case 'noteOn': {
        const hz = this._tuning.get(msg.cell_id);
        if (hz === undefined) return;
        // Release any live voice for the same cell so pitch stays clean.
        for (const v of this._voices) {
          if (v.cellId === msg.cell_id && v.state !== 'release') v.release();
        }
        // Voice stealing: prefer releasing voices, then oldest active.
        if (this._voices.length >= MAX_VOICES) {
          const ri = this._voices.findIndex(v => v.state === 'release');
          this._voices.splice(ri >= 0 ? ri : 0, 1);
        }
        this._voices.push(new Voice(msg.cell_id, hz, msg.velocity ?? 0.8, VOICE_AMPS));
        break;
      }
      case 'noteOff': {
        for (const v of this._voices) {
          if (v.cellId === msg.cell_id && v.state !== 'release') v.release();
        }
        break;
      }
      case 'correction_volume': {
        this._correctionVolume = msg.volume;
        break;
      }
      case 'ison': {
        if (msg.cell_id == null || msg.volume <= 0) {
          if (this._isonVoice) { this._isonVoice.release(); this._isonVoice = null; }
          return;
        }
        const hz = this._tuning.get(msg.cell_id);
        if (hz === undefined) return;
        if (this._isonVoice) this._isonVoice.release();
        this._isonVoice = new Voice(msg.cell_id, hz, msg.volume, ISON_AMPS);
        break;
      }
      case 'synth_follow': {
        if (msg.cell_id == null || msg.volume <= 0) {
          this._releaseFollowVoice();
          return;
        }
        const hz = this._tuning.get(msg.cell_id);
        if (hz === undefined) return;
        if (this._followVoice?.cellId === msg.cell_id && this._followVoice.state !== 'release') {
          this._followVoice.setVelocity(msg.volume);
        } else {
          this._releaseFollowVoice();
          this._followVoice = new Voice(msg.cell_id, hz, msg.volume, VOICE_AMPS);
        }
        break;
      }
    }
  }

  process(inputs, outputs) {
    const out = outputs[0];
    const chL = out?.[0];
    const chR = out?.[1];
    if (!chL) return true;

    chL.fill(0);

    for (const v of this._voices) {
      if (!v.isDead) v.renderInto(chL, chL.length);
    }
    this._voices = this._voices.filter(v => !v.isDead);

    if (this._isonVoice) {
      if (!this._isonVoice.isDead) {
        this._isonVoice.renderInto(chL, chL.length);
      } else {
        this._isonVoice = null;
      }
    }

    if (this._followVoice) {
      if (!this._followVoice.isDead) {
        this._followVoice.renderInto(chL, chL.length);
      } else {
        this._followVoice = null;
      }
    }
    for (const v of this._followReleases) {
      if (!v.isDead) v.renderInto(chL, chL.length);
    }
    this._followReleases = this._followReleases.filter(v => !v.isDead);

    // Mix in PSOLA-corrected voice audio from the VoiceWorklet.
    const voiceIn = inputs[0]?.[0];
    if (voiceIn) {
      const vol = this._correctionVolume * VOICE_MIX_GAIN;
      for (let i = 0; i < chL.length; i++) chL[i] += voiceIn[i] * vol;
    }

    // Duplicate mono to right channel for stereo output.
    if (chR) chR.set(chL);

    return true;
  }
}

registerProcessor('synth-processor', SynthProcessor);
