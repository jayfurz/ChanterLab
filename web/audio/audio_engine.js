// AudioEngine — main-thread WebAudio context, SynthWorklet, and VoiceWorklet manager.
//
// Usage:
//   const engine = new AudioEngine();
//   // Call init() on the first user gesture (click / keydown).
//   await engine.init();
//   // Call initVoice(onPitchFn) to add mic input; also requires a user gesture.
//   await engine.initVoice(msg => { /* msg.cell_id, neighbor_id, neighbor_vel, gate_open */ });
//   engine.updateTuning(cells, refNiHz);
//   engine.noteOn(moria);
//   engine.noteOff(moria);
//   engine.setIson(moria, volume);  // moria=null or volume=0 to disable

const DEFAULT_VOICE_GATE_THRESHOLD = 0.02;

export class AudioEngine {
  constructor() {
    this._ctx               = null;
    this._node              = null;
    this._ready             = false;
    this._initPromise       = null;
    this._pendingTable      = null;

    this._voiceNode         = null;
    this._micSource         = null;
    this._micStream         = null;
    this._voiceReady        = false;
    this._voiceInitPromise  = null;
    this._onPitch           = null;
    this._pendingVoiceTable = null;
  }

  get ready() { return this._ready; }
  get voiceReady() { return this._voiceReady; }

  // Idempotent — safe to call multiple times; only the first call does work.
  async init() {
    if (this._ready) return;
    if (this._initPromise) return this._initPromise;

    this._initPromise = (async () => {
      this._ctx = new AudioContext();
      if (this._ctx.state === 'suspended') await this._ctx.resume();

      // AudioWorklet path is relative to the module URL.
      await this._ctx.audioWorklet.addModule(new URL('./synth_worklet.js', import.meta.url));
      this._node = new AudioWorkletNode(this._ctx, 'synth-processor', {
        numberOfInputs: 1,
        outputChannelCount: [2],
      });
      this._node.connect(this._ctx.destination);
      this._ready = true;

      if (this._pendingTable) {
        this._post({ type: 'tuning_table', table: this._pendingTable });
        this._pendingTable = null;
      }
    })();

    return this._initPromise;
  }

  // Request mic access and start the VoiceWorklet pipeline.
  // onPitch(msg): called with each pitch event from the worklet.
  // Idempotent — subsequent calls are no-ops.
  async initVoice(onPitch) {
    if (this._voiceReady) return;
    if (this._voiceInitPromise) return this._voiceInitPromise;

    this._onPitch = onPitch;
    this._voiceInitPromise = (async () => {
      if (!this._ready) await this.init();

      // Ask the browser for an unprocessed mic signal. iOS Safari defaults
      // echoCancellation/noiseSuppression/autoGainControl all to ON, which
      // mangle the signal before our pitch detector sees it. We want raw.
      this._micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl:  false,
        },
        video: false,
      });
      await this._ctx.audioWorklet.addModule(new URL('./voice_worklet.js', import.meta.url));

      this._voiceNode = new AudioWorkletNode(this._ctx, 'voice-processor');
      // Forward all messages from the voice worklet (pitch events, dsp_path
      // status, etc.) to the single callback. Caller dispatches on type.
      this._voiceNode.port.onmessage = e => {
        if (e.data && this._onPitch) this._onPitch(e.data);
      };
      this._voiceNode.port.postMessage({
        type: 'gate_threshold',
        amp: DEFAULT_VOICE_GATE_THRESHOLD,
      });

      // Fetch the wasm-bindgen glue + binary on the main thread and transfer
      // the ArrayBuffer to the worklet. Safari's AudioWorkletGlobalScope
      // does not reliably expose `importScripts` and will refuse a .wasm
      // response if a tunnel serves the wrong MIME type; bypass both by
      // doing all network I/O here and handing bytes over by transfer.
      const glueUrl = new URL('../../pkg-worklet/byzorgan_core.js',      import.meta.url);
      const wasmUrl = new URL('../../pkg-worklet/byzorgan_core_bg.wasm', import.meta.url);
      try {
        const [glueText, wasmBuffer] = await Promise.all([
          fetch(glueUrl).then(r => {
            if (!r.ok) throw new Error(`worklet glue HTTP ${r.status}`);
            return r.text();
          }),
          fetch(wasmUrl).then(r => {
            if (!r.ok) throw new Error(`worklet wasm HTTP ${r.status}`);
            return r.arrayBuffer();
          }),
        ]);
        this._voiceNode.port.postMessage(
          { type: 'init_wasm', glueText, wasmBuffer },
          [wasmBuffer],
        );
      } catch (e) {
        console.warn('Failed to load worklet WASM; JS DSP fallback will run:', e);
        this._voiceNode.port.postMessage({ type: 'init_wasm_failed', error: String(e) });
      }

      this._micSource = this._ctx.createMediaStreamSource(this._micStream);
      this._micSource.connect(this._voiceNode);
      // Connect corrected voice audio output into the synth for mixing.
      this._voiceNode.connect(this._node);

      this._voiceReady = true;

      if (this._pendingVoiceTable) {
        this._voiceNode.port.postMessage({ type: 'tuning_table', table: this._pendingVoiceTable });
        this._pendingVoiceTable = null;
      }
    })();

    return this._voiceInitPromise;
  }

  // Build and send the tuning table from grid cells.
  // cells: array from JSON.parse(grid.cellsJson())
  // refNiHz: current reference Ni frequency in Hz
  updateTuning(cells, refNiHz) {
    const sr = this._ctx?.sampleRate ?? 48000;
    const hzTable = cells
      .filter(c => c.enabled)
      .map(c => ({
        cell_id: c.moria,
        hz: refNiHz * Math.pow(2, (c.moria + c.accidental) / 72),
      }));
    if (this._ready) {
      this._post({ type: 'tuning_table', table: hzTable });
    } else {
      this._pendingTable = hzTable;
    }

    // Voice worklet expects period_24_8 values.
    const voiceTable = hzTable.map(e => ({
      cell_id: e.cell_id,
      period_24_8: Math.round(sr / e.hz * 256),
    }));
    if (this._voiceReady) {
      this._voiceNode.port.postMessage({ type: 'tuning_table', table: voiceTable });
    } else {
      this._pendingVoiceTable = voiceTable;
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

  // Set the mix volume for the PSOLA-corrected voice signal in the synth.
  // volume: 0.0–1.0 (default 0.5)
  setCorrectionVolume(volume) {
    if (!this._ready) return;
    this._post({ type: 'correction_volume', volume });
  }

  _post(msg) {
    this._node.port.postMessage(msg);
  }
}
