// AudioEngine — main-thread WebAudio context and SynthWorklet manager.
//
// Usage:
//   const engine = new AudioEngine();
//   // Call init() on the first user gesture (click / keydown).
//   await engine.init();
//   engine.updateTuning(cells, refNiHz);
//   engine.noteOn(moria);
//   engine.noteOff(moria);
//   engine.setIson(moria, volume);  // moria=null or volume=0 to disable

export class AudioEngine {
  constructor() {
    this._ctx          = null;
    this._node         = null;
    this._ready        = false;
    this._initPromise  = null;
    this._pendingTable = null;
  }

  get ready() { return this._ready; }

  // Idempotent — safe to call multiple times; only the first call does work.
  async init() {
    if (this._ready) return;
    if (this._initPromise) return this._initPromise;

    this._initPromise = (async () => {
      this._ctx = new AudioContext();
      if (this._ctx.state === 'suspended') await this._ctx.resume();

      // AudioWorklet path is relative to the module URL.
      await this._ctx.audioWorklet.addModule(new URL('./synth_worklet.js', import.meta.url));
      this._node = new AudioWorkletNode(this._ctx, 'synth-processor');
      this._node.connect(this._ctx.destination);
      this._ready = true;

      if (this._pendingTable) {
        this._post({ type: 'tuning_table', table: this._pendingTable });
        this._pendingTable = null;
      }
    })();

    return this._initPromise;
  }

  // Build and send the tuning table from grid cells.
  // cells: array from JSON.parse(grid.cellsJson())
  // refNiHz: current reference Ni frequency in Hz
  updateTuning(cells, refNiHz) {
    const table = cells
      .filter(c => c.enabled)
      .map(c => ({
        cell_id: c.moria,
        hz: refNiHz * Math.pow(2, (c.moria + c.accidental) / 72),
      }));
    if (this._ready) {
      this._post({ type: 'tuning_table', table });
    } else {
      this._pendingTable = table;
    }
  }

  noteOn(moria, velocity = 0.8) {
    if (!this._ready) return;
    this._post({ type: 'noteOn', cell_id: moria, velocity });
  }

  noteOff(moria) {
    if (!this._ready) return;
    this._post({ type: 'noteOff', cell_id: moria });
  }

  // Pass cell_id=null or volume=0 to disable the ison drone.
  setIson(cellId, volume) {
    if (!this._ready) return;
    this._post({ type: 'ison', cell_id: cellId ?? null, volume: volume ?? 0 });
  }

  _post(msg) {
    this._node.port.postMessage(msg);
  }
}
