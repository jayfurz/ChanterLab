/* TrainingScope — singscope strip for the choir-training prototype.
 *
 * A piano-roll style lane synced to playback: the SELECTED voice's target
 * notes are drawn as GOLD bars scrolling toward a fixed "now" line; the
 * singer's live mic pitch is drawn as a cyan trace. When the sung pitch is
 * within ±50 cents of the active target (octave-tolerant), the trace and
 * readout glow gold — the "hitting the note" moment.
 *
 * Pitch detection: plain-JS autocorrelation (cwilso-style ACF with parabolic
 * interpolation + median-of-3 + EMA smoothing) on an AnalyserNode fed by
 * getUserMedia. The Rust/WASM detector in the main app lives in the
 * pkg-worklet bundle and is not loadable standalone without the AudioWorklet
 * plumbing, so the JS fallback is the deliberate works-tonight choice —
 * documented in the README. Swap-in point: `detectPitch()`.
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
  // The mic stream feeds ONLY the AnalyserNode — it is never routed to the
  // destination and never touches any Tone.js gain.
  const mic = { on: false, stream: null, src: null, analyser: null, buf: null, ctx: null, processing: false };

  function micConstraints() {
    return {
      audio: mic.processing
        ? { echoCancellation: true, noiseSuppression: true, autoGainControl: false }
        : { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    };
  }

  // live pitch state
  const hist3 = [];               // median-of-3 raw freq
  let emaMidi = null;
  let trace = [];                 // [{wall, dispMidi, cents, hit, hasTarget}]
  const TRACE_KEEP_SEC = 12;
  let lastDetect = { name: '—', cents: null, hit: false, fresh: 0, quiet: false };

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
    if (!mic.on || !mic.analyser) return;
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

    hist3.push(f);
    if (hist3.length > 3) hist3.shift();
    const sorted = [...hist3].sort((a, b) => a - b);
    const fMed = sorted[Math.floor(sorted.length / 2)];

    let m = midiFromFreq(fMed);
    emaMidi = emaMidi === null ? m : (emaMidi * 0.45 + m * 0.55);
    m = emaMidi;

    const { playing, t } = timeSource();
    let dispMidi, cents = null, hit = false, hasTarget = false;
    const target = (playing && t !== null) ? activeTargetAt(t) : null;
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

    // live pitch trace (wall-clock anchored at the now line)
    if (trace.length) {
      const wallNow = performance.now() / 1000;
      let prev = null;
      for (const p of trace) {
        const x = nowX - (wallNow - p.wall) * PX_PER_SEC;
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
      // current-point dot
      const last = trace[trace.length - 1];
      if (wallNow - last.wall < 0.25) {
        const y = yOf(last.dispMidi);
        g.fillStyle = last.hit ? GOLD_BRIGHT : CYAN;
        if (last.hit) { g.shadowColor = GOLD; g.shadowBlur = 14; }
        g.beginPath(); g.arc(nowX, y, last.hit ? 6 : 4.5, 0, Math.PI * 2); g.fill();
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

  /* ---------- public API ------------------------------------------------ */

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
    return true;
  }

  function micStop() {
    if (mic.src) { try { mic.src.disconnect(); } catch (e) { /* already gone */ } }
    if (mic.stream) mic.stream.getTracks().forEach((tr) => tr.stop());
    mic.on = false; mic.stream = null; mic.src = null; mic.analyser = null;
    trace = []; emaMidi = null; hist3.length = 0;
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
    attach, setLane, setTimeSource, micStart, micStop,
    setMicProcessing, getMicSettings,
    isMicOn: () => mic.on,
    getMicProcessing: () => mic.processing,
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
