// Tanpura — lookahead-scheduled four-string pluck cycle on the shared
// AudioContext (RAGA-02, docs/plans/80-scales-and-raga/83-tanpura-drone.md).
//
// Cycle: first string (Pa / Ma / Ni relative to Sa), then sa, sa, lower Sa —
// the traditional pluck order, with a slightly longer breath after the
// fourth string. Pitches arrive via setFrequencies() from the app's tuning
// grid, so the drone retunes with presets and Reference Sa changes.
//
// v1 is fully synthesized (plucked envelope + a jawari-like upward overtone
// bloom); bundling recorded samples needs a license decision first — see the
// plan's owner gates. Scheduler pattern copied from ui/metronome.js: a 25 ms
// timer schedules every pluck inside the next 100 ms onto exact
// AudioContext times, so timing survives JS-thread stalls.

const LOOKAHEAD_MS = 25;
const SCHEDULE_S = 0.1;
const PLUCK_DECAY_S = 2.4;
const CYCLE_REST_FACTOR = 1.6; // breath after the fourth string

export class Tanpura {
  constructor(engine) {
    this._engine = engine;
    this._ppm = 66; // plucks per minute
    this._volume = 0.5;
    this._running = false;
    this._timerId = null;
    this._nextTime = 0;
    this._stringIndex = 0;
    this._freqs = { firstHz: null, saHz: null, saLowHz: null };
    this._master = null;
  }

  get isRunning() { return this._running; }
  get ppm() { return this._ppm; }
  get volume() { return this._volume; }

  setPpm(ppm) {
    this._ppm = Math.max(20, Math.min(200, Number(ppm) || 0));
  }

  setVolume(v) {
    this._volume = Math.max(0, Math.min(1, Number(v) || 0));
    const ctx = this._engine.audioContext;
    if (this._master && ctx) {
      // Ramp, don't assign: an instant jump clicks mid-pluck.
      this._master.gain.setTargetAtTime(this._volume, ctx.currentTime, 0.03);
    }
  }

  setFrequencies({ firstHz, saHz, saLowHz }) {
    this._freqs = {
      firstHz: firstHz > 0 ? firstHz : null,
      saHz: saHz > 0 ? saHz : null,
      saLowHz: saLowHz > 0 ? saLowHz : null,
    };
  }

  async start() {
    if (this._running) return;
    if (!this._engine.ready) await this._engine.init();
    const ctx = this._engine.audioContext;
    if (!ctx) return;
    if (!this._master) {
      // There is no global master bus; like the metronome's clicks, the
      // tanpura owns its own gain into the destination.
      this._master = ctx.createGain();
      this._master.gain.value = this._volume;
      this._master.connect(ctx.destination);
    }
    this._running = true;
    this._stringIndex = 0;
    this._nextTime = ctx.currentTime + 0.05;
    this._tick();
  }

  stop() {
    if (!this._running) return;
    this._running = false;
    if (this._timerId !== null) {
      clearTimeout(this._timerId);
      this._timerId = null;
    }
  }

  toggle() {
    return this._running ? (this.stop(), false) : (this.start(), true);
  }

  _hzForString(index) {
    const { firstHz, saHz, saLowHz } = this._freqs;
    // Fall back toward Sa so a grid missing the first-string degree still
    // drones rather than silently dropping plucks.
    const cycle = [firstHz ?? saLowHz ?? saHz, saHz, saHz, saLowHz ?? saHz];
    return cycle[index] ?? null;
  }

  _tick = () => {
    if (!this._running) return;
    const ctx = this._engine.audioContext;
    const horizon = ctx.currentTime + SCHEDULE_S;
    while (this._nextTime < horizon) {
      const hz = this._hzForString(this._stringIndex);
      if (hz) this._schedulePluck(this._nextTime, hz);
      const interval = 60 / this._ppm;
      this._nextTime +=
        this._stringIndex === 3 ? interval * CYCLE_REST_FACTOR : interval;
      this._stringIndex = (this._stringIndex + 1) % 4;
    }
    this._timerId = setTimeout(this._tick, LOOKAHEAD_MS);
  };

  _schedulePluck(when, hz) {
    const ctx = this._engine.audioContext;
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.Q.value = 2.5;
    // Jawari-like bloom: the buzzing bridge makes overtones swell upward
    // after the pluck, then settle as the string decays.
    filter.frequency.setValueAtTime(hz * 2, when);
    filter.frequency.linearRampToValueAtTime(hz * 7, when + 0.35);
    filter.frequency.exponentialRampToValueAtTime(hz * 2.5, when + PLUCK_DECAY_S);

    // Two slightly detuned saws read as one shimmering string.
    for (const cents of [0, 2.5]) {
      const osc = ctx.createOscillator();
      osc.type = 'sawtooth';
      osc.frequency.value = hz * Math.pow(2, cents / 1200);
      osc.connect(filter);
      osc.start(when);
      osc.stop(when + PLUCK_DECAY_S + 0.05);
    }

    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(0.28, when + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + PLUCK_DECAY_S);
    filter.connect(gain).connect(this._master);
  }
}
