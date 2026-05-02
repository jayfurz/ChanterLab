// Metronome — lookahead-scheduled click on the shared AudioContext.
//
// Usage:
//   const m = new Metronome(audioEngine);
//   m.setBpm(80); m.setBeats(4); m.setVolume(0.5);
//   await m.start();           // calls engine.init() if needed
//   m.stop();
//   m.onBeat = (idx) => { ... } // 0-based beat-in-measure, fires per click
//
// Scheduler pattern: a 25 ms timer wakes up and schedules every click that
// falls within the next 100 ms window onto exact AudioContext times. This
// keeps timing tight even when the JS thread stalls.

const LOOKAHEAD_MS  = 25;
const SCHEDULE_S    = 0.1;
const CLICK_DUR_S   = 0.04;

export class Metronome {
  constructor(engine) {
    this._engine    = engine;
    this._bpm       = 80;
    this._beats     = 4;
    this._volume    = 0.5;
    this._running   = false;
    this._timerId   = null;
    this._nextTime  = 0;
    this._beatIndex = 0;
    this.onBeat     = null;
  }

  get isRunning() { return this._running; }
  get bpm()       { return this._bpm; }
  get beats()     { return this._beats; }
  get volume()    { return this._volume; }

  setBpm(bpm) {
    const n = Math.max(20, Math.min(300, Number(bpm) || 0));
    this._bpm = n;
  }

  setBeats(beats) {
    const n = Math.max(1, Math.min(12, Number(beats) || 1));
    this._beats = n;
    if (this._beatIndex >= n) this._beatIndex = 0;
  }

  setVolume(v) {
    this._volume = Math.max(0, Math.min(1, Number(v) || 0));
  }

  async start() {
    if (this._running) return;
    if (!this._engine.ready) await this._engine.init();
    const ctx = this._engine.audioContext;
    if (!ctx) return;
    this._running   = true;
    this._beatIndex = 0;
    this._nextTime  = ctx.currentTime + 0.05;
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

  _tick = () => {
    if (!this._running) return;
    const ctx = this._engine.audioContext;
    const horizon = ctx.currentTime + SCHEDULE_S;
    while (this._nextTime < horizon) {
      const beatIdx = this._beatIndex;
      this._scheduleClick(this._nextTime, beatIdx === 0);
      if (this.onBeat) {
        const fireAt = this._nextTime;
        const delay = Math.max(0, (fireAt - ctx.currentTime) * 1000);
        const idx = beatIdx;
        setTimeout(() => { if (this._running) this.onBeat?.(idx); }, delay);
      }
      this._nextTime += 60 / this._bpm;
      this._beatIndex = (this._beatIndex + 1) % this._beats;
    }
    this._timerId = setTimeout(this._tick, LOOKAHEAD_MS);
  };

  _scheduleClick(when, isDownbeat) {
    const ctx = this._engine.audioContext;
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = isDownbeat ? 1500 : 1000;
    osc.type = 'square';
    const peak = this._volume * (isDownbeat ? 0.35 : 0.22);
    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(peak, when + 0.001);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + CLICK_DUR_S);
    osc.connect(gain).connect(ctx.destination);
    osc.start(when);
    osc.stop(when + CLICK_DUR_S + 0.01);
  }
}
