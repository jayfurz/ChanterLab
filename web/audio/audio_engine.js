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
//   engine.setSynthFollow(moria, volume);  // moria=null or volume=0 to disable

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
    this._synthFollowCellId = null;
    this._synthFollowVolume = 0;
    this._voicing           = null;

    // Voice mix chain (lazy — built once initVoice() finishes).
    this._voiceSplitter      = null;
    this._voiceInputGainNode = null;
    this._monitorGainNode    = null;
    this._psolaGainNode      = null;
    this._reverbWetNode      = null;
    this._reverbDryNode      = null;
    this._convolver          = null;
    this._voiceLimiter       = null;
    // Makeup gain for the mic. iOS Safari delivers very low levels through
    // getUserMedia (the audio session is forced to playAndRecord category),
    // so a per-user trim is exposed and a limiter sits downstream to catch
    // peaks if the user cranks it.
    this._voiceInputGain  = 6;
    this._monitorVolume   = 0.5;
    this._psolaVolume     = 0;
    this._reverbWet       = 0.2;
  }

  get ready() { return this._ready; }
  get voiceReady() { return this._voiceReady; }
  get micStream() { return this._micStream; }
  get audioContext() { return this._ctx; }

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
      if (this._voicing) {
        this._post({ type: 'synth_voicing', name: this._voicing });
      }
      if (this._synthFollowCellId != null && this._synthFollowVolume > 0) {
        this._post({
          type: 'noteOn',
          cell_id: this._synthFollowCellId,
          velocity: this._synthFollowVolume,
        });
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

      this._voiceNode = new AudioWorkletNode(this._ctx, 'voice-processor', {
        // ch0 = dry monitor, ch1 = PSOLA-corrected. The downstream graph
        // splits these to drive separate gain + send chains.
        outputChannelCount: [2],
      });
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
      const glueUrl = new URL('../../pkg-worklet/chanterlab_core.js',      import.meta.url);
      const wasmUrl = new URL('../../pkg-worklet/chanterlab_core_bg.wasm', import.meta.url);
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

      // Voice signal chain: ch0 (dry monitor) and ch1 (PSOLA) each get their
      // own gain + EQ chain, then meet on a shared bus that splits into a
      // dry path and a reverb send. The synth worklet no longer mixes voice
      // — these chains go straight to ctx.destination.
      this._buildVoiceChain();

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

  // Pick a synth timbre (e.g. "Sine", "Organ", "Reed", "Flute", "String").
  // Applied to keyboard voices, ison drone, and synth-follow alike.
  setVoicing(name) {
    this._voicing = name;
    if (!this._ready) return;
    this._post({ type: 'synth_voicing', name });
  }

  // Synth voice driven by the snapped mic pitch. Uses the same note messages
  // as the keyboard path so it works with the current SynthWorklet.
  setSynthFollow(cellId, volume) {
    const nextCellId = cellId ?? null;
    const nextVolume = volume ?? 0;
    const prevCellId = this._synthFollowCellId;
    const prevVolume = this._synthFollowVolume;

    this._synthFollowCellId = nextVolume > 0 ? nextCellId : null;
    this._synthFollowVolume = nextVolume;
    if (!this._ready) return;

    if (prevCellId != null && (prevCellId !== nextCellId || nextVolume <= 0)) {
      this._post({ type: 'noteOff', cell_id: prevCellId });
    }
    if (nextCellId == null || nextVolume <= 0) return;

    if (prevCellId !== nextCellId || prevVolume !== nextVolume) {
      this._post({ type: 'noteOn', cell_id: nextCellId, velocity: nextVolume });
    }
  }

  // Mic makeup gain (linear, 1×–12× sensible range). iOS users typically
  // need 6× or more to match desktop levels.
  setVoiceInputGain(gain) {
    this._voiceInputGain = Math.max(0, Math.min(16, gain ?? 1));
    if (this._voiceInputGainNode) this._voiceInputGainNode.gain.value = this._voiceInputGain;
  }

  // Voice-monitor mix volume (the dry, EQ'd version of the singer).
  setMonitorVolume(volume) {
    this._monitorVolume = Math.max(0, Math.min(1, volume ?? 0));
    if (this._monitorGainNode) this._monitorGainNode.gain.value = this._monitorVolume;
  }

  // PSOLA pitch-corrected playback volume. Pass 0 to mute.
  setPsolaPlayback(volume) {
    this._psolaVolume = Math.max(0, Math.min(1, volume ?? 0));
    if (this._psolaGainNode) this._psolaGainNode.gain.value = this._psolaVolume;
  }

  // Reverb wet send (0..1). Both monitor and PSOLA share the same reverb.
  setMonitorReverb(wet) {
    this._reverbWet = Math.max(0, Math.min(1, wet ?? 0));
    if (this._reverbWetNode) this._reverbWetNode.gain.value = this._reverbWet;
    // Slight dry attenuation as wet rises so the apparent loudness stays flat.
    if (this._reverbDryNode) this._reverbDryNode.gain.value = 1 - 0.4 * this._reverbWet;
  }

  // Backwards-compatible alias.
  setCorrectionVolume(volume) { this.setMonitorVolume(volume); }

  // ── Internal: voice signal graph ────────────────────────────────────────

  _buildVoiceChain() {
    const ctx = this._ctx;

    // Mic makeup gain. The pre-rewrite path applied a fixed 4× boost inside
    // the synth worklet; this exposes the same idea as a user-trimmable
    // node so iOS users (where getUserMedia levels are dramatically lower
    // than desktop) can match the synth/ison loudness.
    const inputGain = ctx.createGain();
    inputGain.gain.value = this._voiceInputGain;
    this._voiceNode.connect(inputGain);
    this._voiceInputGainNode = inputGain;

    const splitter = ctx.createChannelSplitter(2);
    inputGain.connect(splitter);
    this._voiceSplitter = splitter;

    // Per-channel EQ chain. BiquadFilter nodes can't be shared between
    // sources, so each channel gets its own copy of the curve. Cheap.
    const monitorChain = this._buildVocalEqChain();
    const psolaChain   = this._buildVocalEqChain();
    splitter.connect(monitorChain.input, 0);
    splitter.connect(psolaChain.input,   1);

    const monitorGain = ctx.createGain();
    monitorGain.gain.value = this._monitorVolume;
    monitorChain.output.connect(monitorGain);
    this._monitorGainNode = monitorGain;

    const psolaGain = ctx.createGain();
    psolaGain.gain.value = this._psolaVolume;
    psolaChain.output.connect(psolaGain);
    this._psolaGainNode = psolaGain;

    // Shared post-EQ bus that fans out to dry + reverb send.
    const bus = ctx.createGain();
    bus.gain.value = 1;
    monitorGain.connect(bus);
    psolaGain.connect(bus);

    // Soft limiter on the voice bus. Cranking the input gain hard would
    // clip the destination on belted peaks; this catches them with a
    // musical compression curve (no audible pumping on sustained chant).
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -6;
    limiter.knee.value      = 12;
    limiter.ratio.value     = 6;
    limiter.attack.value    = 0.01;
    limiter.release.value   = 0.25;
    bus.connect(limiter);
    this._voiceLimiter = limiter;

    const dryGain = ctx.createGain();
    dryGain.gain.value = 1 - 0.4 * this._reverbWet;
    limiter.connect(dryGain);
    dryGain.connect(ctx.destination);
    this._reverbDryNode = dryGain;

    const convolver = ctx.createConvolver();
    convolver.normalize = true;
    convolver.buffer = this._makeReverbImpulse(1.6);
    const wetGain = ctx.createGain();
    wetGain.gain.value = this._reverbWet;
    limiter.connect(convolver);
    convolver.connect(wetGain);
    wetGain.connect(ctx.destination);
    this._convolver     = convolver;
    this._reverbWetNode = wetGain;
  }

  // 4-band fixed vocal EQ: low-shelf cut → 300 Hz peak cut (de-mud) →
  // 3 kHz presence lift → high-shelf air. Returns the head/tail of the
  // chain so callers can plug it into a larger graph.
  _buildVocalEqChain() {
    const ctx = this._ctx;
    const lowShelf = ctx.createBiquadFilter();
    lowShelf.type = 'lowshelf';
    lowShelf.frequency.value = 120;
    lowShelf.gain.value = -2;

    const mudCut = ctx.createBiquadFilter();
    mudCut.type = 'peaking';
    mudCut.frequency.value = 300;
    mudCut.Q.value = 1.0;
    mudCut.gain.value = -3;

    const presence = ctx.createBiquadFilter();
    presence.type = 'peaking';
    presence.frequency.value = 3000;
    presence.Q.value = 0.7;
    presence.gain.value = 2;

    const air = ctx.createBiquadFilter();
    air.type = 'highshelf';
    air.frequency.value = 8000;
    air.gain.value = 1.5;

    lowShelf.connect(mudCut).connect(presence).connect(air);
    return { input: lowShelf, output: air };
  }

  // Synthetic exponential-decay noise IR — sounds like a small chapel.
  // Stereo, decorrelated noise streams give the wet signal a sense of width.
  _makeReverbImpulse(seconds) {
    const ctx = this._ctx;
    const len = Math.floor(ctx.sampleRate * seconds);
    const ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const data = ir.getChannelData(ch);
      for (let i = 0; i < len; i++) {
        const t = i / len;
        // Exponential decay with mild early-reflection bump.
        const env = Math.pow(1 - t, 3) * (1 + 0.3 * Math.exp(-t * 12));
        data[i] = (Math.random() * 2 - 1) * env;
      }
    }
    return ir;
  }

  _post(msg) {
    this._node.port.postMessage(msg);
  }
}
