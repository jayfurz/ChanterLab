// SynthWorklet — additive organ voice synthesizer.
//
// Runs in the AudioWorklet rendering thread. Accepts main-thread messages:
//   { type: 'tuning_table', table: [{cell_id, hz}] }
//   { type: 'noteOn',  cell_id, velocity }
//   { type: 'noteOff', cell_id }
//   { type: 'ison',    cell_id, volume }  (cell_id=null or volume=0 to disable)
//   { type: 'synth_follow', cell_id, volume }  (cell_id=null or volume=0 to disable)
//   { type: 'synth_voicing', name }  (one of "Sine", "Organ", "Reed", "Flute", "String")

const K = 8;       // harmonics per voice
const ALPHA = 1.2; // amplitude of kth harmonic = 1 / k^ALPHA
const MAX_VOICES = 16;
const ATTACK_S  = 0.005;
const RELEASE_S = 0.08;
const VEL_RAMP_S = 0.02; // velocity smoothing for live gain changes

// Harmonic amplitude tables, normalised to unit peak sum.
function _makeAmps(weights) {
  const s = weights.reduce((a, b) => a + b, 0);
  return new Float64Array(weights.map(w => w / s));
}

const VOICE_MIX_GAIN = 4.0;

// Voicings: each defines a harmonic-amplitude table for keyboard/follow voices
// and one for the ison drone. The ison curves emphasise lower partials so the
// drone sits underneath the chant without competing with the upper harmonics
// of the lead voice.
const VOICINGS = {
  Sine: {
    voice: _makeAmps([1, 0, 0, 0, 0, 0, 0, 0]),
    ison:  _makeAmps([1, 0, 0, 0, 0, 0, 0, 0]),
  },
  Organ: {
    voice: _makeAmps(Array.from({ length: K }, (_, i) => 1 / Math.pow(i + 1, ALPHA))),
    ison:  _makeAmps([1.0, 0.75, 0.55, 0.38, 0.26, 0.17, 0.11, 0.07]),
  },
  // Reedy / nasal: odd harmonics emphasised, like a clarinet/zurna.
  Reed: {
    voice: _makeAmps([1.0, 0.30, 0.85, 0.25, 0.65, 0.20, 0.45, 0.15]),
    ison:  _makeAmps([1.0, 0.40, 0.75, 0.30, 0.55, 0.20, 0.35, 0.12]),
  },
  // Flute: mostly fundamental, a touch of 2nd, almost nothing above.
  Flute: {
    voice: _makeAmps([1.0, 0.25, 0.08, 0.04, 0.02, 0.01, 0.005, 0.002]),
    ison:  _makeAmps([1.0, 0.30, 0.10, 0.04, 0.02, 0.01, 0.005, 0.002]),
  },
  // Bowed string: rich, slow harmonic decay.
  String: {
    voice: _makeAmps([1.0, 0.85, 0.70, 0.55, 0.45, 0.35, 0.25, 0.18]),
    ison:  _makeAmps([1.0, 0.90, 0.75, 0.60, 0.48, 0.36, 0.26, 0.18]),
  },
};
const DEFAULT_VOICING = 'Organ';

class Voice {
  constructor(cellId, hz, velocity, amps) {
    this.cellId   = cellId;
    this.hz       = hz;
    this.velocity = velocity;
    this.targetVelocity = velocity;
    this.amps     = amps;
    this.phases   = new Float64Array(K);
    this.env      = 0;
    this.state    = 'attack'; // 'attack' | 'sustain' | 'release' | 'dead'
    this._attackInc  = 1 / (ATTACK_S  * sampleRate);
    this._releaseInc = 1 / (RELEASE_S * sampleRate);
    this._velStep    = 1 / (VEL_RAMP_S * sampleRate);
  }

  release() {
    if (this.state !== 'dead') this.state = 'release';
  }

  // Smoothly ramp gain toward `velocity` instead of jumping. Cheap per-sample
  // lerp avoids the click that an instantaneous velocity change would cause
  // when the user drags a volume slider.
  setVelocity(velocity) {
    this.targetVelocity = velocity;
  }

  get isDead() { return this.state === 'dead'; }

  renderInto(buf, len) {
    const hz   = this.hz;
    const step = this._velStep;
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
      // Velocity smoothing — lerp toward target over VEL_RAMP_S.
      const dv = this.targetVelocity - this.velocity;
      if (dv > step)       this.velocity += step;
      else if (dv < -step) this.velocity -= step;
      else                 this.velocity  = this.targetVelocity;

      let s = 0;
      for (let k = 0; k < K; k++) {
        s += this.amps[k] * Math.sin(2 * Math.PI * this.phases[k]);
        this.phases[k] += hz * (k + 1) / sampleRate;
        if (this.phases[k] >= 1) this.phases[k] -= Math.trunc(this.phases[k]);
      }
      buf[i] += s * this.velocity * this.env;
    }
  }
}

class SynthProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._voices           = []; // regular voices
    this._isonVoice        = null;
    this._isonReleases     = [];
    this._followVoice      = null;
    this._followReleases   = [];
    this._tuning           = new Map(); // cell_id(moria) → hz
    this._correctionVolume = 0.5;
    this._voicing          = VOICINGS[DEFAULT_VOICING];

    this.port.onmessage = ({ data }) => this._dispatch(data);
  }

  _releaseFollowVoice() {
    if (!this._followVoice) return;
    this._followVoice.release();
    this._followReleases.push(this._followVoice);
    this._followVoice = null;
  }

  _releaseIsonVoice() {
    if (!this._isonVoice) return;
    this._isonVoice.release();
    this._isonReleases.push(this._isonVoice);
    this._isonVoice = null;
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
        this._voices.push(new Voice(msg.cell_id, hz, msg.velocity ?? 0.8, this._voicing.voice));
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
          this._releaseIsonVoice();
          return;
        }
        const hz = this._tuning.get(msg.cell_id);
        if (hz === undefined) return;
        // Live volume change on the same drone: just retarget velocity so the
        // voice keeps its envelope and no new attack ramp is triggered.
        if (this._isonVoice?.cellId === msg.cell_id && this._isonVoice.state !== 'release') {
          this._isonVoice.setVelocity(msg.volume);
        } else {
          this._releaseIsonVoice();
          this._isonVoice = new Voice(msg.cell_id, hz, msg.volume, this._voicing.ison);
        }
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
          this._followVoice = new Voice(msg.cell_id, hz, msg.volume, this._voicing.voice);
        }
        break;
      }
      case 'synth_voicing': {
        const next = VOICINGS[msg.name];
        if (!next) return;
        this._voicing = next;
        // Re-spawn the ison drone immediately with the new timbre so the
        // change is audible without toggling the drone off and on. Park the
        // outgoing voice in the release pool so its tail still renders.
        if (this._isonVoice && this._isonVoice.state !== 'release') {
          const { cellId, hz, targetVelocity } = this._isonVoice;
          this._releaseIsonVoice();
          this._isonVoice = new Voice(cellId, hz, targetVelocity, this._voicing.ison);
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
    for (const v of this._isonReleases) {
      if (!v.isDead) v.renderInto(chL, chL.length);
    }
    this._isonReleases = this._isonReleases.filter(v => !v.isDead);

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
