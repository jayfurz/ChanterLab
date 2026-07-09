/* TrainingScope — singscope strip for the choir-training prototype.
 *
 * A piano-roll style lane synced to playback: the SELECTED voice's target
 * notes are drawn as GOLD bars scrolling toward a fixed "now" line; the
 * singer's live mic pitch is drawn as a cyan trace. When the sung pitch is
 * within ±50 cents of the active target (octave-tolerant), the trace and
 * readout glow gold — the "hitting the note" moment.
 *
 * Pitch detection has two interchangeable front-ends behind one output
 * contract (median-of-3 + EMA smoothing -> MIDI -> pitch-sink/trace/readout,
 * all owned here so both detectors feed scoring identically):
 *   - 'js'   (DEFAULT): plain-JS autocorrelation (cwilso-style ACF with
 *            parabolic interpolation) on an AnalyserNode fed by getUserMedia.
 *   - 'wasm' (opt-in via setDetector('wasm'), gated behind ?detector=wasm in
 *            main.js): routes the mic through an AudioWorkletNode running the
 *            legacy Byzantine app's Rust FFT detector (pkg-worklet's
 *            VoiceProcessor; see pitch_worklet.js). Emits the SAME detected-Hz
 *            into pushVoicedFreq(), so downstream behavior is unchanged.
 * The JS path stays the default until the A/B (issue #80) proves the swap.
 * Swap-in point: `pushVoicedFreq()` — the JS detector calls it from
 * captureMicFrame(); the wasm worklet calls it from onWasmPitch().
 */
window.TrainingScope = (() => {
  'use strict';

  const GOLD = '#d4af37';
  const GOLD_BRIGHT = '#ffd95e';
  const CYAN = '#4dd7ff';
  const DIMBAR = 'rgba(154,160,166,0.22)';
  const BG = '#14161c';
  const GRID = 'rgba(255,255,255,0.05)';
  const GRID_OCT = 'rgba(255,255,255,0.14)';

  const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

  let canvas = null, g = null, readoutEl = null, hintEl = null;
  let dpr = Math.max(1, window.devicePixelRatio || 1);
  let cssW = 0, cssH = 0;

  // content
  let lane = [];        // selected voice: [{start,end,midi}] seconds from window start
  let others = [];      // other voices, faint
  let totalSec = 0;
  let range = { lo: 48, hi: 72 };   // midi range shown on Y

  // time
  let timeSource = () => ({ playing: false, t: null });

  // mic — `processing=false` is HEADPHONES MODE (default): raw stream, no
  // echoCancellation. Chrome/Android ties echoCancellation to system-level
  // audio ducking, which was muting every backing voice the moment the singer
  // sang; with headphones there is no echo to cancel, so we keep it OFF.
  // `processing=true` is speaker mode (echoCancellation back on; the OS may
  // duck playback while the mic hears voice — documented in the UI).
  // In the JS default the mic stream feeds ONLY the AnalyserNode; in 'wasm'
  // mode it ALSO feeds the detector worklet (on a native context — see the wasm
  // block below), whose output goes through a gain=0 keep-alive to the
  // destination. Either way the mic is NEVER audible and never touches a Tone.js
  // gain — the singer only ever hears the backing voices.
  const mic = { on: false, stream: null, src: null, analyser: null, buf: null, ctx: null, processing: false };

  function micConstraints() {
    return {
      audio: mic.processing
        ? { echoCancellation: true, noiseSuppression: true, autoGainControl: false }
        : { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    };
  }

  // live pitch state
  const hist3 = [];               // median-of-3 raw freq (octave-error rejection)
  let pitchSink = null;           // optional subscriber: fn({tSec, midi, playing})
                                  // called once per VOICED frame (scoring tap, #49)
  let trace = [];                 // [{wall, dispMidi, cents, hit, hasTarget}]
  const TRACE_KEEP_SEC = 12;
  let lastDetect = { name: '—', cents: null, hit: false, fresh: 0, quiet: false };

  // L_in — input/detection latency (seconds): sound is SUNG this long before the
  // detector reports it (mic buffer + 2048-sample autocorrelation window + the
  // median-of-3 + one-euro group delay). Back-dating the trace AND the scoring
  // stamp by it aligns a note sung on the audible beat with that note. main.js
  // owns the persisted/calibrated value (setInputLatency); this is a mid default.
  let inputLatencySec = 0.08;

  // Detector front-end (issue #80). 'js' is the default and leaves every code
  // path below byte-for-byte unchanged; 'wasm' is opt-in and only touches the
  // guarded branches in micStart/micStop/setMicProcessing + the worklet glue at
  // the bottom of this file. Nothing wasm-related runs — no fetch, no worklet,
  // no console — while the mode is 'js'.
  let detectorMode = 'js';
  const WASM_GATE_THRESHOLD = 0.02;   // linear amp; matches the legacy worklet default
  const wasm = {
    node: null, gain: null, srcNode: null, nativeCtx: null, ownCtx: null,
    ready: false, moduleCtx: null,
    glueText: null, wasmBuffer: null, loading: null, lastError: null,
    frames: 0, voiced: 0, firstWall: null, lastWall: null, cadenceHz: null, latencyMs: null, rateDiv: null,
  };

  const PX_PER_SEC = 68;
  const NOW_FRAC = 0.33;

  /* ---------- pitch detection (JS autocorrelation) -------------------- */

  // Adaptive noise gate. Headphones mode delivers a RAW stream (no browser
  // processing), which on many devices is far quieter than the processed
  // speaker-mode stream — a fixed 0.012 RMS gate forced singers to belt.
  // The floor tracks background level on UNVOICED frames only (fast down,
  // slow up), so singing never raises it; the gate sits above the floor but
  // never below GATE_MIN (mic self-noise) nor above GATE_MAX (old fixed gate).
  const GATE_MIN = 0.004, GATE_MAX = 0.012;
  let noiseFloor = 0.002;
  const currentGate = () => Math.min(GATE_MAX, Math.max(GATE_MIN, noiseFloor * 3));

  function detectPitch(buf, sr, rmsIn) {
    let SIZE = buf.length;
    let rms = rmsIn;
    if (rms === undefined) {
      let acc = 0;
      for (let i = 0; i < SIZE; i++) acc += buf[i] * buf[i];
      rms = Math.sqrt(acc / SIZE);
    }
    if (rms < currentGate()) return -1;            // noise gate (adaptive)

    // trim leading/trailing low-signal edges (transient guard)
    const thres = 0.2 * Math.max(...[0, 1, 2, 3].map(k => Math.abs(buf[(SIZE >> 2) * k]))) || 0.02;
    let r1 = 0, r2 = SIZE - 1;
    for (let i = 0; i < SIZE / 2; i++) if (Math.abs(buf[i]) < thres) { r1 = i; break; }
    for (let i = 1; i < SIZE / 2; i++) if (Math.abs(buf[SIZE - i]) < thres) { r2 = SIZE - i; break; }
    buf = buf.subarray(r1, r2);
    SIZE = buf.length;
    if (SIZE < 256) return -1;

    const maxLag = Math.min(SIZE - 1, Math.floor(sr / 60));   // >= 60 Hz
    const minLag = Math.max(2, Math.floor(sr / 1100));        // <= 1100 Hz
    const c = new Float32Array(maxLag + 1);
    for (let lag = minLag; lag <= maxLag; lag++) {
      let sum = 0;
      for (let j = 0; j + lag < SIZE; j++) sum += buf[j] * buf[j + lag];
      c[lag] = sum;
    }
    // skip the initial decreasing region, then take global max
    let d = minLag;
    while (d + 1 <= maxLag && c[d] > c[d + 1]) d++;
    let maxval = -1, maxpos = -1;
    for (let i = d; i <= maxLag; i++) if (c[i] > maxval) { maxval = c[i]; maxpos = i; }
    if (maxpos <= 0) return -1;
    // confidence: peak vs zero-lag energy
    let e0 = 0;
    for (let j = 0; j < SIZE; j++) e0 += buf[j] * buf[j];
    if (e0 <= 0 || maxval / e0 < 0.25) return -1;

    let T0 = maxpos;
    const x1 = c[T0 - 1] ?? c[T0], x2 = c[T0], x3 = c[T0 + 1] ?? c[T0];
    const a = (x1 + x3 - 2 * x2) / 2, b = (x3 - x1) / 2;
    if (a) T0 = T0 - b / (2 * a);
    const f = sr / T0;
    return (f >= 60 && f <= 1100) ? f : -1;
  }

  const midiFromFreq = (f) => 69 + 12 * Math.log2(f / 440);
  const noteName = (m) => NOTE_NAMES[((Math.round(m) % 12) + 12) % 12] + (Math.floor(Math.round(m) / 12) - 1);

  function captureMicFrame() {
    if (!mic.on) return;
    // In 'wasm' mode the pitch stream is driven by worklet messages
    // (onWasmPitch -> pushVoicedFreq), not the analyser, so the animation-frame
    // capture is a no-op. draw() still renders the trace pushVoicedFreq builds.
    if (detectorMode === 'wasm') return;
    if (!mic.analyser) return;
    mic.analyser.getFloatTimeDomainData(mic.buf);
    let acc = 0;
    for (let i = 0; i < mic.buf.length; i++) acc += mic.buf[i] * mic.buf[i];
    const rms = Math.sqrt(acc / mic.buf.length);
    const f = detectPitch(mic.buf, mic.ctx.sampleRate, rms);
    const wall = performance.now() / 1000;
    if (f <= 0) {
      // unvoiced frame: adapt the noise floor (fast down, slow up — singing
      // frames never reach here, so the voice can't raise its own gate)
      noiseFloor = rms < noiseFloor ? rms : Math.min(0.02, noiseFloor * 0.98 + rms * 0.02);
      // signal present but under the gate? tell the singer they're close
      lastDetect.quiet = rms >= currentGate() * 0.5 && rms < currentGate();
      lastDetect.fresh = Math.max(0, lastDetect.fresh - 1);
      return;
    }
    pushVoicedFreq(f, wall);
  }

  /* ---------- adaptive pitch smoothing (one-euro) --------------------- *
   * Replaces the old fixed EMA (α=0.55), whose settle time meant fast notes
   * (e.g. eighths at 70bpm) never converged before the note was over. The
   * one-euro filter lowers its cutoff on sustained pitch (heavy smoothing, low
   * jitter) and raises it when the pitch is moving fast (a note change → little
   * lag), so short notes register. The residual near-constant group delay on
   * sustained notes is absorbed by the inputLatencySec back-date / calibration. */
  // Tuned offline (tmp/oneeuro_tune): min-cutoff 2 + beta 1.0 settles a fifth
  // leap in ~33ms (vs ~83ms for the old EMA α=0.55) while holding sustained-note
  // jitter ≈0.03 semitone — i.e. fast notes register without a shaky trace.
  const OE_MIN_CUTOFF = 2.0;   // Hz — cutoff floor on steady pitch (smoothing)
  const OE_BETA = 1.0;         // how much pitch velocity raises the cutoff
  const OE_DCUTOFF = 1.0;      // Hz — cutoff for the derivative estimate
  const oe = { xPrev: null, dxPrev: 0, tPrev: null };
  const oeAlpha = (cutoff, dt) => { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); };
  function oneEuroMidi(x, wall) {
    if (oe.xPrev === null || oe.tPrev === null) { oe.xPrev = x; oe.dxPrev = 0; oe.tPrev = wall; return x; }
    let dt = wall - oe.tPrev;
    if (!(dt > 0) || dt > 0.25) dt = 1 / 60;   // first frame / long gap → nominal
    oe.tPrev = wall;
    const dx = (x - oe.xPrev) / dt;
    const aD = oeAlpha(OE_DCUTOFF, dt);
    oe.dxPrev = aD * dx + (1 - aD) * oe.dxPrev;
    const cutoff = OE_MIN_CUTOFF + OE_BETA * Math.abs(oe.dxPrev);
    const aX = oeAlpha(cutoff, dt);
    oe.xPrev = aX * x + (1 - aX) * oe.xPrev;
    return oe.xPrev;
  }
  function resetSmoothing() { oe.xPrev = null; oe.tPrev = null; oe.dxPrev = 0; hist3.length = 0; }

  // Shared voiced-frame ingestion: median-of-3 + one-euro smoothing, MIDI
  // conversion, the {tSec, midi} pitch-sink emit, the scope trace, and the
  // readout. BOTH detectors funnel a raw detected Hz through here, so the
  // smoothed-MIDI stream that reaches scoring is identical regardless of which
  // front-end produced `f`.
  function pushVoicedFreq(f, wall) {
    hist3.push(f);
    if (hist3.length > 3) hist3.shift();
    const sorted = [...hist3].sort((a, b) => a - b);
    const fMed = sorted[Math.floor(sorted.length / 2)];

    // Adaptive one-euro smoothing (see block above): snaps on note changes,
    // smooths on sustain — so short notes register where the fixed EMA lagged.
    const m = oneEuroMidi(midiFromFreq(fMed), wall);

    const { playing, t } = timeSource();
    // Input-latency back-date: this sample reflects sound sung inputLatencySec
    // ago, so associate it with the note that was audible THEN — for the scoring
    // stamp AND the readout/glow lookup below. (The trace is drawn back-dated by
    // the same amount in draw(), so the cyan line rides under the gold bar the
    // singer actually heard.)
    const tEff = (t == null) ? null : t - inputLatencySec;
    // Scoring tap (#49): emit the smoothed sung MIDI in input-compensated
    // transport seconds so a subscriber can grade it against the lane. Octave
    // folding is the scorer's job, so we hand it the un-folded pitch.
    if (pitchSink) pitchSink({ tSec: tEff, midi: m, playing });
    let dispMidi, cents = null, hit = false, hasTarget = false;
    const target = (playing && tEff !== null) ? activeTargetAt(tEff) : null;
    if (target) {
      hasTarget = true;
      // octave-tolerant: fold the sung pitch to the octave nearest the target
      const k = Math.round((m - target.midi) / 12);
      dispMidi = m - 12 * k;
      cents = (dispMidi - target.midi) * 100;
      hit = Math.abs(cents) <= 50;
    } else {
      dispMidi = foldIntoRange(m);
    }
    trace.push({ wall, dispMidi, cents, hit, hasTarget });
    const cutoff = wall - TRACE_KEEP_SEC;
    while (trace.length && trace[0].wall < cutoff) trace.shift();

    lastDetect = {
      name: noteName(m),
      cents: cents === null ? null : Math.round(cents),
      hit, fresh: 6, quiet: false,
    };
  }

  function activeTargetAt(t) {
    for (let i = 0; i < lane.length; i++) {
      if (t >= lane[i].start - 0.03 && t < lane[i].end + 0.03) return lane[i];
    }
    return null;
  }

  function foldIntoRange(m) {
    while (m < range.lo) m += 12;
    while (m > range.hi) m -= 12;
    return m;
  }

  /* ---------- drawing -------------------------------------------------- */

  const yOf = (midi) => {
    const pad = 8;
    const span = range.hi - range.lo;
    return pad + (1 - (midi - range.lo) / span) * (cssH - 2 * pad);
  };

  function draw() {
    requestAnimationFrame(draw);
    if (!g || cssW === 0) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = BG;
    g.fillRect(0, 0, cssW, cssH);

    const rowH = (cssH - 16) / (range.hi - range.lo);
    // gridlines
    for (let m = Math.ceil(range.lo); m <= range.hi; m++) {
      const isC = (m % 12) === 0;
      if (!isC && rowH < 5) continue;
      g.strokeStyle = isC ? GRID_OCT : GRID;
      g.beginPath();
      const y = yOf(m);
      g.moveTo(0, y); g.lineTo(cssW, y); g.stroke();
      if (isC && rowH >= 3) {
        g.fillStyle = 'rgba(255,255,255,0.35)';
        g.font = '10px system-ui';
        g.fillText(noteName(m), 4, y - 2);
      }
    }

    const { playing, t } = timeSource();
    // use transport time whenever it exists (playing OR paused) so the lane
    // freezes in place on pause instead of snapping back to the start
    const tNow = (t !== null && t !== undefined) ? t : 0;
    const nowX = cssW * NOW_FRAC;
    const xOfNote = (sec) => nowX + (sec - tNow) * PX_PER_SEC;

    // other voices — faint context bars
    g.fillStyle = DIMBAR;
    others.forEach((n) => {
      const x0 = xOfNote(n.start), x1 = xOfNote(n.end);
      if (x1 < -20 || x0 > cssW + 20) return;
      g.fillRect(x0, yOf(n.midi) - Math.min(3, rowH * 0.25), Math.max(2, x1 - x0 - 2), Math.min(6, rowH * 0.5));
    });

    // selected voice — gold target lane, lyric syllables riding just below
    lane.forEach((n) => {
      const x0 = xOfNote(n.start), x1 = xOfNote(n.end);
      if (x1 < -20 || x0 > cssW + 20) return;
      const active = playing && tNow >= n.start - 0.03 && tNow < n.end + 0.03;
      const h = Math.max(6, Math.min(14, rowH * 0.8));
      const w = Math.max(4, x1 - x0 - 2);
      const yMid = yOf(n.midi);
      g.fillStyle = active ? GOLD_BRIGHT : GOLD;
      if (active) { g.shadowColor = GOLD; g.shadowBlur = 12; }
      roundRect(g, x0, yMid - h / 2, w, h, 3);
      g.fill();
      g.shadowBlur = 0;
      if (n.lyric && w >= 14) {
        // clip to the bar's horizontal span so long syllables on short
        // notes don't smear over their neighbours
        g.save();
        g.beginPath();
        g.rect(x0 - 2, yMid + h / 2, w + 4, 14);
        g.clip();
        g.font = '11px system-ui';
        g.textBaseline = 'top';
        g.fillStyle = active ? GOLD_BRIGHT : 'rgba(212,175,55,0.85)';
        g.fillText(n.lyric, x0 + 1, yMid + h / 2 + 2);
        g.restore();
      }
    });

    // loop-end marker
    if (totalSec > 0) {
      const xe = xOfNote(totalSec);
      if (xe > 0 && xe < cssW) {
        g.strokeStyle = 'rgba(255,255,255,0.2)';
        g.setLineDash([4, 4]);
        g.beginPath(); g.moveTo(xe, 0); g.lineTo(xe, cssH); g.stroke();
        g.setLineDash([]);
      }
    }

    // now line
    g.strokeStyle = 'rgba(255,255,255,0.5)';
    g.beginPath(); g.moveTo(nowX, 0); g.lineTo(nowX, cssH); g.stroke();

    // live pitch trace (wall-clock, back-dated by the input latency so a sample
    // sits under the note that was audible when it was SUNG — not when detected).
    if (trace.length) {
      const wallNow = performance.now() / 1000;
      const inLat = inputLatencySec;
      let prev = null;
      for (const p of trace) {
        const x = nowX - (wallNow - p.wall + inLat) * PX_PER_SEC;
        if (x < -10) { prev = null; continue; }
        const y = yOf(p.dispMidi);
        if (prev && (p.wall - prev.wall) < 0.18) {
          g.strokeStyle = p.hit ? GOLD_BRIGHT : (p.hasTarget ? CYAN : 'rgba(77,215,255,0.5)');
          g.lineWidth = p.hit ? 3 : 2;
          if (p.hit) { g.shadowColor = GOLD; g.shadowBlur = 10; }
          g.beginPath(); g.moveTo(prev.x, prev.y); g.lineTo(x, y); g.stroke();
          g.shadowBlur = 0;
        }
        prev = { x, y, wall: p.wall };
      }
      g.lineWidth = 1;
      // current-point dot — sits at the back-dated leading edge of the trace,
      // matching the line above (else the dot would float ahead of it).
      const last = trace[trace.length - 1];
      if (wallNow - last.wall < 0.25) {
        const y = yOf(last.dispMidi);
        const dotX = nowX - inLat * PX_PER_SEC;
        g.fillStyle = last.hit ? GOLD_BRIGHT : CYAN;
        if (last.hit) { g.shadowColor = GOLD; g.shadowBlur = 14; }
        g.beginPath(); g.arc(dotX, y, last.hit ? 6 : 4.5, 0, Math.PI * 2); g.fill();
        g.shadowBlur = 0;
      }
    }

    captureMicFrame();
    updateReadout();
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function updateReadout() {
    if (!readoutEl) return;
    if (!mic.on) { readoutEl.textContent = ''; readoutEl.className = 'scope-readout'; return; }
    if (lastDetect.fresh <= 0) {
      readoutEl.textContent = lastDetect.quiet
        ? '🎤 almost — sing a touch louder'
        : '🎤 listening…';
      readoutEl.className = 'scope-readout idle';
      return;
    }
    let txt = lastDetect.name;
    if (lastDetect.cents !== null) {
      const c = lastDetect.cents;
      txt += `  ${c > 0 ? '+' : ''}${c}¢`;
      if (lastDetect.hit) txt += '  ✓';
    }
    readoutEl.textContent = txt;
    readoutEl.className = 'scope-readout' + (lastDetect.hit ? ' hit' : '');
  }

  /* ---------- sizing ---------------------------------------------------- */

  function resize() {
    if (!canvas) return;
    const r = canvas.getBoundingClientRect();
    cssW = r.width; cssH = r.height;
    dpr = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }

  /* ---------- wasm detector (issue #80) --------------------------------- *
   * A minimal AudioWorklet front-end that reuses the legacy Byzantine app's
   * Rust FFT detector (pkg-worklet's VoiceProcessor). We follow the proven
   * legacy load pattern (web/audio/audio_engine.js): fetch the wasm-bindgen
   * no-modules glue + .wasm bytes on the MAIN thread and transfer them into
   * the worklet, so Safari's fetch/importScripts-less worklet scope never
   * touches the network. Everything here is dormant unless detectorMode is
   * 'wasm'. */

  // Fetch the glue text + wasm bytes once and cache them on `wasm`. URLs are
  // resolved against the document base so they work under either serve root
  // (/training-prototype/ from the repo, or /training/ via the web symlink).
  function loadWasmPayload() {
    if (wasm.glueText && wasm.wasmBuffer) return Promise.resolve();
    if (wasm.loading) return wasm.loading;
    const base = (typeof document !== 'undefined' && document.baseURI) || location.href;
    const glueUrl = new URL('pkg-worklet/chanterlab_core.js', base);
    const wasmUrl = new URL('pkg-worklet/chanterlab_core_bg.wasm', base);
    wasm.loading = Promise.all([
      fetch(glueUrl).then((r) => { if (!r.ok) throw new Error('worklet glue HTTP ' + r.status); return r.text(); }),
      fetch(wasmUrl).then((r) => { if (!r.ok) throw new Error('worklet wasm HTTP ' + r.status); return r.arrayBuffer(); }),
    ]).then(([glueText, wasmBuffer]) => {
      wasm.glueText = glueText;
      wasm.wasmBuffer = wasmBuffer;
    }).finally(() => { wasm.loading = null; });
    return wasm.loading;
  }

  // Resolve a NATIVE BaseAudioContext for the worklet. Tone.js (14.x) wraps its
  // context with standardized-audio-context, and the native AudioWorkletNode
  // constructor rejects that wrapper ("parameter 1 is not of type
  // 'BaseAudioContext'"). The legacy Byzantine app sidesteps this by owning a
  // native AudioContext outright (web/audio/audio_engine.js); here we prefer to
  // UNWRAP Tone's native context (shared clock, no extra iOS context cost) and
  // fall back to a dedicated native context only if unwrap fails.
  function resolveNativeCtx() {
    const NativeBase = (typeof window !== 'undefined') && (window.BaseAudioContext || window.AudioContext);
    const ctx = mic.ctx;
    if (NativeBase && ctx instanceof NativeBase) return ctx;
    if (ctx) {
      for (const k of ['_nativeAudioContext', '_nativeContext']) {
        const n = ctx[k];
        if (n && NativeBase && n instanceof NativeBase) return n;
      }
    }
    const AC = (typeof window !== 'undefined') && (window.AudioContext || window.webkitAudioContext);
    if (!AC) throw new Error('no native AudioContext constructor');
    if (!wasm.ownCtx) wasm.ownCtx = new AC();      // dedicated fallback, reused across toggles
    return wasm.ownCtx;
  }

  async function startWasmDetector() {
    if (!mic.stream) throw new Error('no mic stream');
    await loadWasmPayload();
    const ctx = resolveNativeCtx();
    wasm.nativeCtx = ctx;
    if (ctx.state === 'suspended' && ctx.resume) { try { await ctx.resume(); } catch (e) { /* best effort */ } }
    // addModule is per-context; (re)register on a fresh context (e.g. after
    // recreateAudioContext on iOS, or the dedicated fallback). Idempotent within
    // one context.
    if (wasm.moduleCtx !== ctx) {
      const base = (typeof document !== 'undefined' && document.baseURI) || location.href;
      await ctx.audioWorklet.addModule(new URL('pitch_worklet.js', base));
      wasm.moduleCtx = ctx;
    }
    const node = new AudioWorkletNode(ctx, 'training-pitch-detector', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    });
    node.port.onmessage = ({ data }) => onWasmMessage(data);
    // Transfer a COPY of the wasm bytes so the cached original survives for a
    // later re-init (mirrors the legacy wasmBuffer.slice(0) transfer).
    const wasmCopy = wasm.wasmBuffer.slice(0);
    node.port.postMessage(
      { type: 'init_wasm', glueText: wasm.glueText, wasmBuffer: wasmCopy, gateThreshold: WASM_GATE_THRESHOLD },
      [wasmCopy],
    );
    // Tap the RAW MediaStream on the native context (independent of the Tone
    // analyser leg — scope's mic.src stays on the wrapper context for the JS
    // path / recording fan-out). Keep-alive: an AudioWorkletNode is only pulled
    // while it reaches the destination, so route it through a MUTED gain — the
    // mic is never monitored (same invariant as the JS path: never audible).
    const srcNode = ctx.createMediaStreamSource(mic.stream);
    const keep = ctx.createGain();
    keep.gain.value = 0;
    srcNode.connect(node);
    node.connect(keep);
    keep.connect(ctx.destination);
    wasm.node = node;
    wasm.gain = keep;
    wasm.srcNode = srcNode;
    wasm.ready = false;
    wasm.frames = 0; wasm.voiced = 0; wasm.firstWall = null; wasm.lastWall = null;
    wasm.cadenceHz = null; wasm.latencyMs = null;
  }

  function stopWasmDetector() {
    if (wasm.srcNode) { try { wasm.srcNode.disconnect(); } catch (e) { /* noop */ } }
    if (wasm.node) {
      try { wasm.node.port.onmessage = null; } catch (e) { /* noop */ }
      try { wasm.node.disconnect(); } catch (e) { /* noop */ }
    }
    if (wasm.gain) { try { wasm.gain.disconnect(); } catch (e) { /* noop */ } }
    wasm.node = null; wasm.gain = null; wasm.srcNode = null; wasm.ready = false;
    wasm.frames = 0; wasm.voiced = 0; wasm.firstWall = null; wasm.lastWall = null;
    wasm.cadenceHz = null; wasm.latencyMs = null;
  }

  function onWasmMessage(data) {
    if (!data) return;
    if (data.type === 'ready') { wasm.ready = true; wasm.rateDiv = data.rateDiv; return; }
    if (data.type === 'init_failed') { wasm.ready = false; wasm.lastError = data.error; return; }
    if (data.type === 'pitch') onWasmPitch(data);
  }

  // Per-pitch-event handler: the wasm analogue of captureMicFrame's branch.
  // Voiced events feed pushVoicedFreq (the shared smoothing/sink/trace path);
  // gate-closed events decay the readout. Also tracks live cadence + a
  // message-hop latency proxy for the diagnostics overlay / A/B hook.
  function onWasmPitch(msg) {
    if (!mic.on || detectorMode !== 'wasm') return;
    const wall = performance.now() / 1000;
    wasm.frames++;
    // Cadence = frames per second since the first event (stable average — the
    // worklet posts deterministically every RATE_DIV blocks; a per-interval EMA
    // over jittery main-thread receipt times would overstate it).
    if (wasm.firstWall == null) wasm.firstWall = wall;
    else if (wall > wasm.firstWall) wasm.cadenceHz = (wasm.frames - 1) / (wall - wasm.firstWall);
    wasm.lastWall = wall;
    if (wasm.nativeCtx && typeof msg.ct === 'number') {
      const lat = (wasm.nativeCtx.currentTime - msg.ct) * 1000;   // audio-time -> callback, ms
      if (isFinite(lat) && lat >= 0) wasm.latencyMs = wasm.latencyMs == null ? lat : (wasm.latencyMs * 0.9 + lat * 0.1);
    }
    if (msg.gateOpen && msg.hz > 0) {
      wasm.voiced++;
      pushVoicedFreq(msg.hz, wall);
    } else {
      lastDetect.quiet = false;
      lastDetect.fresh = Math.max(0, lastDetect.fresh - 1);
    }
  }

  /* ---------- public API ------------------------------------------------ */

  // Select the pitch-detection front-end: 'js' (default) or 'wasm'. Takes
  // effect on the next micStart; if the mic is already live, restarts it so the
  // new front-end is wired. Returns the mode actually in effect.
  function setDetector(mode) {
    const next = mode === 'wasm' ? 'wasm' : 'js';
    if (next === detectorMode) return detectorMode;
    detectorMode = next;
    if (mic.on) {
      // Re-tap the SAME context/analyser onto the newly-selected front-end.
      if (next === 'wasm') {
        startWasmDetector().catch((e) => { wasm.lastError = String(e && e.message ? e.message : e); detectorMode = 'js'; });
      } else {
        stopWasmDetector();
      }
    }
    return detectorMode;
  }
  function getDetector() { return detectorMode; }

  // Live introspection for the diagnostics overlay + the __training.detector()
  // A/B hook (issue #80).
  function detectorInfo() {
    return {
      mode: detectorMode,
      active: detectorMode === 'wasm' ? (!!wasm.node && wasm.ready) : mic.on,
      wasmReady: wasm.ready,
      framesSeen: wasm.frames,
      voicedFrames: wasm.voiced,
      cadenceHz: wasm.cadenceHz != null ? Math.round(wasm.cadenceHz * 10) / 10 : null,
      latencyMs: wasm.latencyMs != null ? Math.round(wasm.latencyMs * 10) / 10 : null,
      blockSize: 128,
      rateDiv: wasm.rateDiv,
      lastError: wasm.lastError,
      sampleRate: mic.ctx ? mic.ctx.sampleRate : null,
    };
  }

  function attach(canvasEl, readout, hint) {
    canvas = canvasEl;
    g = canvas.getContext('2d');
    readoutEl = readout;
    hintEl = hint || null;
    new ResizeObserver(resize).observe(canvas);
    resize();
    requestAnimationFrame(draw);
  }

  function setLane(selectedNotes, otherNotes, windowSec) {
    lane = selectedNotes || [];
    others = otherNotes || [];
    totalSec = windowSec || 0;
    if (lane.length) {
      let lo = Infinity, hi = -Infinity;
      lane.forEach((n) => { lo = Math.min(lo, n.midi); hi = Math.max(hi, n.midi); });
      lo -= 4; hi += 4;
      while (hi - lo < 14) { lo -= 1; hi += 1; }   // min span for readability
      range = { lo, hi };
    }
  }

  function setTimeSource(fn) { timeSource = fn; }

  // Subscribe to the live voiced-pitch stream (scoring tap, #49). The callback
  // fires once per voiced frame with {tSec, midi, playing}; pass null to detach.
  function setPitchSink(fn) { pitchSink = typeof fn === 'function' ? fn : null; }

  // L_in (input/detection latency) back-date, seconds. main.js owns the
  // persisted/calibrated value; clamped to a sane [0, 0.5) range here.
  function setInputLatency(sec) {
    const n = Number(sec);
    inputLatencySec = (isFinite(n) && n >= 0 && n < 0.5) ? n : 0;
    return inputLatencySec;
  }
  function getInputLatency() { return inputLatencySec; }

  async function micStart(audioCtx) {
    if (mic.on) return true;
    mic.ctx = audioCtx;
    mic.stream = await navigator.mediaDevices.getUserMedia(micConstraints());
    mic.src = audioCtx.createMediaStreamSource(mic.stream);
    mic.analyser = audioCtx.createAnalyser();
    mic.analyser.fftSize = 2048;
    mic.src.connect(mic.analyser);
    mic.buf = new Float32Array(mic.analyser.fftSize);
    noiseFloor = 0.002;                 // fresh stream, fresh floor
    mic.on = true;
    // Detector swap (issue #80): only in 'wasm' mode — the JS default never
    // reaches here, so its micStart path is unchanged. Loading the worklet
    // AFTER getUserMedia (and, upstream, after Tone.start()/unlockAudio in
    // main.js's mic flow) is deliberate for iOS: the AudioWorklet is added to
    // the already-unlocked context that the mic session settled on.
    if (detectorMode === 'wasm') {
      try {
        await startWasmDetector();
      } catch (e) {
        // Never break practice: fall back to the JS analyser path for this
        // session and record why. The analyser is already wired above.
        wasm.lastError = String(e && e.message ? e.message : e);
        detectorMode = 'js';
      }
    }
    return true;
  }

  function micStop() {
    stopWasmDetector();                 // no-op unless a wasm node is live
    if (mic.src) { try { mic.src.disconnect(); } catch (e) { /* already gone */ } }
    if (mic.stream) mic.stream.getTracks().forEach((tr) => tr.stop());
    mic.on = false; mic.stream = null; mic.src = null; mic.analyser = null;
    trace = []; resetSmoothing();
    lastDetect = { name: '—', cents: null, hit: false, fresh: 0, quiet: false };
  }

  // Switch headphones/speaker mic processing. If the mic is live, re-acquire
  // the stream with the new constraints and swap it under the running
  // analyser; on failure the old stream keeps running and we report false.
  async function setMicProcessing(processing) {
    processing = !!processing;
    if (mic.processing === processing) return true;
    mic.processing = processing;
    if (!mic.on) return true;                     // applied on next micStart
    const oldStream = mic.stream, oldSrc = mic.src;
    try {
      const stream = await navigator.mediaDevices.getUserMedia(micConstraints());
      if (oldSrc) { try { oldSrc.disconnect(); } catch (e) { /* noop */ } }
      if (oldStream) oldStream.getTracks().forEach((tr) => tr.stop());
      mic.stream = stream;
      mic.src = mic.ctx.createMediaStreamSource(stream);
      mic.src.connect(mic.analyser);
      // Re-tap the re-acquired stream into the wasm worklet too (#80). The
      // worklet owns its own native source node, so rebuild it on the new
      // stream. Guarded: dormant in the JS default.
      if (detectorMode === 'wasm' && wasm.node) {
        stopWasmDetector();
        await startWasmDetector();
      }
      noiseFloor = 0.002;               // new stream = new level profile
      return true;
    } catch (e) {
      mic.processing = !processing;               // revert — old stream still live
      if (!(oldStream && oldStream.active)) { mic.on = false; throw e; }
      return false;
    }
  }

  // Introspection for the UI/debugging: what the browser actually granted.
  function getMicSettings() {
    const tr = mic.stream && mic.stream.getAudioTracks()[0];
    return tr ? tr.getSettings() : null;
  }

  return {
    attach, setLane, setTimeSource, setPitchSink, micStart, micStop,
    setMicProcessing, getMicSettings,
    // Input-latency (L_in) back-date for the trace + scoring stamp.
    setInputLatency, getInputLatency,
    // Detector front-end selection + introspection (issue #80).
    setDetector, getDetector, detectorInfo,
    isMicOn: () => mic.on,
    getMicProcessing: () => mic.processing,
    // The live MediaStreamAudioSourceNode (in the SAME AudioContext Tone was
    // handed via micStart's rawContext). Exposed so the recording graph
    // (js/recording.js, issue #67) can FAN OUT the mic into its own gain →
    // record destination WITHOUT touching the analyser feed (scoring/pitch tap
    // is unaffected). Null while the mic is off; changes when the stream is
    // re-acquired (setMicProcessing) — recording re-taps on mic-state changes.
    getMicSourceNode: () => mic.src,
    // for the headless checks + detector swap-in experiments
    _debug: {
      detectPitch,
      gate: currentGate,
      floor: () => noiseFloor,
      setFloor: (v) => { noiseFloor = v; },
      lane: () => lane,
    },
  };
})();
