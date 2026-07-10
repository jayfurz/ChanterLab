#!/usr/bin/env node
/*
 * Detector A/B measurement harness (issue #80, the spike's deliverable).
 *
 * Feeds the SAME synthetic audio through BOTH pitch detectors and reports an
 * honest comparison:
 *   - JS   : the real scope.js autocorrelation (window.TrainingScope._debug.detectPitch),
 *            driven exactly as the app drives it (2048-sample analyser window,
 *            hopped at ~60 Hz).
 *   - WASM : the pkg-worklet VoiceProcessor (src/worklet.rs), fed 128-sample
 *            blocks and polled at ~60 Hz — exactly as pitch_worklet.js drives it.
 *
 * Deterministic and device-free: no browser, no AudioContext, no fake mic.
 * The wasm module instantiates in Node from the same glue+bytes the worklet
 * loads (verified: the no-modules bundle runs under Node's WebAssembly).
 *
 * Metrics per detector, per timbre:
 *   - pitch accuracy   : median |cents| error after octave folding (this is what
 *                        scoring sees — it folds octaves before grading).
 *   - raw |cents|      : median |cents| BEFORE folding (exposes octave confusion
 *                        in the raw trace the singer watches).
 *   - octave-error rate: fraction of voiced frames off by >= a half-octave
 *                        (i.e. nearest-octave multiple != 0).
 *   - voiced cadence   : voiced frames per second (vs scoring's maxGap=50ms).
 *   - onset latency    : audio-time from a silence->tone onset to first voiced
 *                        detection (gate attack + detector window fill).
 *   - CPU proxy        : wall-ms to process 1 s of audio (Node timing; a proxy,
 *                        NOT a browser number — boundary-crossing shape matches
 *                        the real worklet's one-crossing-per-128-block).
 *
 * Run: node training-prototype/tests/detector-ab.mjs
 *
 * BASE-02: thresholds below turn this into a CI gate (exit 1 on regression),
 * not just a report. Values were set from a real local run (see the commit
 * that added them) with headroom for cross-runner jitter — they're meant to
 * catch a real accuracy/cadence/onset/dropout regression, not to be tight.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROTO = path.resolve(__dirname, '..');           // training-prototype/
const PKG = path.join(PROTO, 'pkg-worklet');

const SR = 48000;
const FFT_BLOCK = 128;
const RATE_DIV = Math.max(1, Math.round(SR / 60 / FFT_BLOCK));   // wasm poll throttle
const JS_HOP = Math.round(SR / 60);                             // JS animation-frame hop
const JS_WIN = 2048;                                           // analyser fftSize

// ── load the REAL JS detector from scope.js ──────────────────────────────────
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
globalThis.performance = globalThis.performance || { now: () => Number(process.hrtime.bigint() / 1000n) / 1000 };
globalThis.requestAnimationFrame = () => 0;
globalThis.ResizeObserver = class { observe() {} };
(0, eval)(readFileSync(path.join(PROTO, 'scope.js'), 'utf8'));
const jsDetect = globalThis.window.TrainingScope._debug.detectPitch;

// ── load the wasm VoiceProcessor (same bytes the worklet loads) ──────────────
const glue = readFileSync(path.join(PKG, 'chanterlab_core.js'), 'utf8');
const wasmBytesBuf = readFileSync(path.join(PKG, 'chanterlab_core_bg.wasm'));
const wasmBytes = wasmBytesBuf.buffer.slice(wasmBytesBuf.byteOffset, wasmBytesBuf.byteOffset + wasmBytesBuf.byteLength);
const bindgen = new Function('TextDecoder', glue + '\nreturn wasm_bindgen;')(TextDecoder);
await bindgen({ module_or_path: wasmBytes });
const newVP = () => new bindgen.VoiceProcessor(SR, 0.02);

// ── signal synthesis ─────────────────────────────────────────────────────────
const midiToHz = (m) => 440 * Math.pow(2, (m - 69) / 12);
const hzToMidi = (hz) => 69 + 12 * Math.log2(hz / 440);

const TIMBRES = {
  // clean sine — the easy case
  pure: [[1, 1]],
  // voice-like: strong harmonic stack (realistic chant timbre)
  voice: [[1, 1], [2, 0.55], [3, 0.4], [4, 0.22], [5, 0.14]],
  // weak fundamental — the classic octave-error trap (organ/bass-ish)
  weakFund: [[1, 0.2], [2, 1], [3, 0.7], [4, 0.35]],
};

function synth(midi, seconds, timbre, amp = 0.35, leadSilence = 0) {
  const f0 = midiToHz(midi);
  const n = Math.round(seconds * SR);
  const lead = Math.round(leadSilence * SR);
  const out = new Float32Array(lead + n);
  let norm = 0; for (const [, a] of timbre) norm += a;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let s = 0;
    for (const [h, a] of timbre) s += a * Math.sin(2 * Math.PI * f0 * h * t);
    out[lead + i] = amp * s / norm;
  }
  return { signal: out, onset: lead };
}

// glide: linear MIDI m0->m1 over `seconds`, instantaneous truth at each sample
function synthGlide(m0, m1, seconds, timbre, amp = 0.35) {
  const n = Math.round(seconds * SR);
  const out = new Float32Array(n);
  let norm = 0; for (const [, a] of timbre) norm += a;
  let phase = 0;
  const truthAt = (i) => m0 + (m1 - m0) * (i / n);
  for (let i = 0; i < n; i++) {
    const f0 = midiToHz(truthAt(i));
    phase += 2 * Math.PI * f0 / SR;
    let s = 0;
    for (const [h, a] of timbre) s += a * Math.sin(h * phase);
    out[i] = amp * s / norm;
  }
  return { signal: out, truthAt };
}

// ── detector runners: return [{ i (sample index of detection), hz }] ─────────
function runJs(signal) {
  const frames = [];
  const win = new Float32Array(JS_WIN);
  for (let start = 0; start + JS_WIN <= signal.length; start += JS_HOP) {
    win.set(signal.subarray(start, start + JS_WIN));
    const hz = jsDetect(win, SR);
    // the detection reflects audio centered in the window; attribute it to the
    // window's trailing edge (freshest sample), matching the live analyser.
    if (hz > 0) frames.push({ i: start + JS_WIN, hz });
    else frames.push({ i: start + JS_WIN, hz: 0 });
  }
  return frames;
}

function runWasm(signal, vp = newVP()) {
  const frames = [];
  const scratch = new Float32Array(FFT_BLOCK);
  let block = 0;
  for (let start = 0; start + FFT_BLOCK <= signal.length; start += FFT_BLOCK) {
    vp.processBlockInto(signal.subarray(start, start + FFT_BLOCK), scratch);
    if (++block >= RATE_DIV) {
      block = 0;
      let hz = 0;
      if (vp.gateOpen()) {
        const p = vp.detectPitch();
        if (p > 0) hz = (SR * 256) / p;
      }
      frames.push({ i: start + FFT_BLOCK, hz });
    }
  }
  return frames;
}

// ── metrics ──────────────────────────────────────────────────────────────────
const median = (a) => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

// steady-tone stats over the region past `warmupSec`
function toneStats(frames, trueMidi, warmupSec) {
  const cut = warmupSec * SR;
  const folded = [], raw = [];
  let voiced = 0, octave = 0, total = 0;
  for (const f of frames) {
    if (f.i < cut) continue;
    total++;
    if (f.hz <= 0) continue;
    voiced++;
    const rawErr = (hzToMidi(f.hz) - trueMidi) * 100;   // cents, signed
    const k = Math.round(rawErr / 1200);
    const foldedErr = rawErr - 1200 * k;
    raw.push(Math.abs(rawErr));
    folded.push(Math.abs(foldedErr));
    if (k !== 0) octave++;
  }
  return {
    voicedPct: total ? voiced / total : 0,
    voicedFrames: voiced,
    accFolded: median(folded),
    accRaw: median(raw),
    octaveRate: voiced ? octave / voiced : 0,
  };
}

// onset latency: first voiced detection after a silence->tone onset, in ms
function onsetLatencyMs(frames, onsetSample) {
  for (const f of frames) if (f.hz > 0 && f.i >= onsetSample) return ((f.i - onsetSample) / SR) * 1000;
  return NaN;
}

function glideStats(frames, truthAt, warmupSec) {
  const cut = warmupSec * SR;
  const folded = [];
  let voiced = 0, total = 0;
  for (const f of frames) {
    if (f.i < cut) continue;
    total++;
    if (f.hz <= 0) continue;
    voiced++;
    const rawErr = (hzToMidi(f.hz) - truthAt(Math.min(f.i, frames[frames.length - 1].i))) * 100;
    const k = Math.round(rawErr / 1200);
    folded.push(Math.abs(rawErr - 1200 * k));
  }
  return { voicedPct: total ? voiced / total : 0, acc: median(folded), voicedFrames: voiced };
}

// cadence: voiced frames per second over the measured window
const cadence = (voicedFrames, sec) => voicedFrames / sec;

// ── run the battery ──────────────────────────────────────────────────────────
const NOTES = [45, 48, 50, 52, 55, 57, 60, 62, 64, 67, 69, 72, 74, 76]; // A2..E5
const TONE_SEC = 0.7, WARMUP = 0.25;
const measuredSec = TONE_SEC - WARMUP;

const agg = {
  js: { pure: [], voice: [], weakFund: [] },
  wasm: { pure: [], voice: [], weakFund: [] },
};
const onset = { js: [], wasm: [] };

for (const timbreName of Object.keys(TIMBRES)) {
  const timbre = TIMBRES[timbreName];
  for (const midi of NOTES) {
    const { signal } = synth(midi, TONE_SEC, timbre);
    agg.js[timbreName].push(toneStats(runJs(signal), midi, WARMUP));
    agg.wasm[timbreName].push(toneStats(runWasm(signal), midi, WARMUP));
  }
}

// onset latency: 0.3s silence then a mid-range voice tone (A3, midi 57)
for (let rep = 0; rep < Object.keys(TIMBRES).length; rep++) { /* keep loop shape parity */ }
{
  const { signal, onset: on } = synth(57, 0.6, TIMBRES.voice, 0.35, 0.3);
  onset.js.push(onsetLatencyMs(runJs(signal), on));
  onset.wasm.push(onsetLatencyMs(runWasm(signal), on));
}

// glide 50->74 over 3s (voice timbre)
const gl = synthGlide(50, 74, 3.0, TIMBRES.voice);
const glideJs = glideStats(runJs(gl.signal), gl.truthAt, 0.3);
const glideWasm = glideStats(runWasm(gl.signal), gl.truthAt, 0.3);

// CPU proxy: process 8 s of voice tone, measure wall time
function cpuProxy(runner, seconds = 8) {
  const { signal } = synth(60, seconds, TIMBRES.voice);
  const t0 = process.hrtime.bigint();
  runner(signal);
  const t1 = process.hrtime.bigint();
  return Number(t1 - t0) / 1e6 / seconds;   // ms per second of audio
}
const cpuJs = cpuProxy(runJs);
const cpuWasm = cpuProxy((s) => runWasm(s));

// ── aggregate + print ────────────────────────────────────────────────────────
function summarize(arr) {
  return {
    accFolded: median(arr.map((s) => s.accFolded).filter(Number.isFinite)),
    accRaw: median(arr.map((s) => s.accRaw).filter(Number.isFinite)),
    octaveRate: arr.reduce((a, s) => a + s.octaveRate, 0) / arr.length,
    voicedPct: arr.reduce((a, s) => a + s.voicedPct, 0) / arr.length,
    cadence: cadence(median(arr.map((s) => s.voicedFrames)), measuredSec),
  };
}
const sum = {
  js: { pure: summarize(agg.js.pure), voice: summarize(agg.js.voice), weakFund: summarize(agg.js.weakFund) },
  wasm: { pure: summarize(agg.wasm.pure), voice: summarize(agg.wasm.voice), weakFund: summarize(agg.wasm.weakFund) },
};

const f1 = (x) => Number.isFinite(x) ? x.toFixed(1) : '—';
const f2 = (x) => Number.isFinite(x) ? x.toFixed(2) : '—';
const pct = (x) => Number.isFinite(x) ? (x * 100).toFixed(1) + '%' : '—';

function row(label, jsv, wasmv, fmt) {
  return `  ${label.padEnd(28)} ${String(fmt(jsv)).padStart(12)}   ${String(fmt(wasmv)).padStart(12)}`;
}

const out = [];
out.push('');
out.push('════════════════════════════════════════════════════════════════════════');
out.push(`  DETECTOR A/B — JS autocorrelation vs Rust/WASM FFT   (SR=${SR} Hz)`);
out.push(`  ${NOTES.length} notes A2..E5 · 3 timbres · glide 50→74 · CPU over 8 s`);
out.push(`  wasm poll cadence target = ${(SR / (RATE_DIV * FFT_BLOCK)).toFixed(1)} Hz (RATE_DIV=${RATE_DIV})`);
out.push('════════════════════════════════════════════════════════════════════════');
out.push(`  ${''.padEnd(28)} ${'JS'.padStart(12)}   ${'WASM'.padStart(12)}`);
out.push('  ─────────────────────────────────────────────────────────────────────');
for (const tb of ['pure', 'voice', 'weakFund']) {
  out.push(`  [${tb}]`);
  out.push(row('  accuracy folded |cents|', sum.js[tb].accFolded, sum.wasm[tb].accFolded, f1));
  out.push(row('  raw |cents| (pre-fold)', sum.js[tb].accRaw, sum.wasm[tb].accRaw, f1));
  out.push(row('  octave-error rate', sum.js[tb].octaveRate, sum.wasm[tb].octaveRate, pct));
  out.push(row('  voiced-frame coverage', sum.js[tb].voicedPct, sum.wasm[tb].voicedPct, pct));
  out.push(row('  voiced cadence (Hz)', sum.js[tb].cadence, sum.wasm[tb].cadence, f1));
}
out.push('  ─────────────────────────────────────────────────────────────────────');
out.push(`  [glide 50→74]`);
out.push(row('  tracking |cents|', glideJs.acc, glideWasm.acc, f1));
out.push(row('  voiced coverage', glideJs.voicedPct, glideWasm.voicedPct, pct));
out.push('  ─────────────────────────────────────────────────────────────────────');
out.push(row('onset latency (ms)', median(onset.js), median(onset.wasm), f1));
out.push(row('CPU proxy (ms / s audio)', cpuJs, cpuWasm, f2));
out.push('════════════════════════════════════════════════════════════════════════');
out.push('  Notes: onset latency = gate attack + window fill (JS 2048 / WASM 4096');
out.push('  samples) measured to first voiced frame; it excludes the worklet→main');
out.push('  message hop (~a few ms, measured live via __training.detector().latencyMs).');
out.push('  CPU proxy is Node wall-time, a relative proxy only — not a device number.');
out.push('  Both detectors feed the SAME median-of-3 + EMA smoothing downstream.');
out.push('');
console.log(out.join('\n'));

// machine-readable line for any wrapper that wants to diff runs
console.log('AB_JSON ' + JSON.stringify({ sum, glide: { js: glideJs, wasm: glideWasm }, onset: { js: median(onset.js), wasm: median(onset.wasm) }, cpu: { js: cpuJs, wasm: cpuWasm }, cadenceTargetHz: SR / (RATE_DIV * FFT_BLOCK) }));

// ── CI gate: stable accuracy/cadence/onset/dropout thresholds ────────────────
// CPU is deliberately NOT gated here (Audio Gate: "CPU is informational unless
// measured on a controlled runner") — reported above, never asserted.
const THRESHOLDS = {
  // per-timbre steady-tone checks, per detector
  accFoldedCentsMax: { js: 5, wasm: 15 },
  octaveRateMax: { js: 0.05, wasm: 0.05 },
  voicedPctMin: { js: 0.90, wasm: 0.80 },
  cadenceHzMin: { js: 45, wasm: 45 },
  // glide (50->74 MIDI tracking)
  glideCentsMax: { js: 40, wasm: 90 },
  glideVoicedPctMin: { js: 0.85, wasm: 0.80 },
  // onset latency
  onsetMsMax: { js: 40, wasm: 90 },
};

const gateFailures = [];
function checkMax(label, val, max) {
  if (!(val <= max)) gateFailures.push(`${label}: ${Number.isFinite(val) ? val.toFixed(2) : val} exceeds max ${max}`);
}
function checkMin(label, val, min) {
  if (!(val >= min)) gateFailures.push(`${label}: ${Number.isFinite(val) ? val.toFixed(2) : val} below min ${min}`);
}

for (const detector of ['js', 'wasm']) {
  for (const timbre of ['pure', 'voice', 'weakFund']) {
    const s = sum[detector][timbre];
    checkMax(`${detector}/${timbre} accFolded`, s.accFolded, THRESHOLDS.accFoldedCentsMax[detector]);
    checkMax(`${detector}/${timbre} octaveRate`, s.octaveRate, THRESHOLDS.octaveRateMax[detector]);
    checkMin(`${detector}/${timbre} voicedPct`, s.voicedPct, THRESHOLDS.voicedPctMin[detector]);
    checkMin(`${detector}/${timbre} cadence`, s.cadence, THRESHOLDS.cadenceHzMin[detector]);
  }
  const g = detector === 'js' ? glideJs : glideWasm;
  checkMax(`${detector} glide |cents|`, g.acc, THRESHOLDS.glideCentsMax[detector]);
  checkMin(`${detector} glide voicedPct`, g.voicedPct, THRESHOLDS.glideVoicedPctMin[detector]);
  const onsetMs = detector === 'js' ? median(onset.js) : median(onset.wasm);
  checkMax(`${detector} onset latency`, onsetMs, THRESHOLDS.onsetMsMax[detector]);
}

if (gateFailures.length) {
  console.error(`\n[detector-ab] GATE FAIL (${gateFailures.length}):`);
  gateFailures.forEach((f, i) => console.error(`  ${i + 1}. ${f}`));
  process.exitCode = 1;
} else {
  console.log('[detector-ab] GATE PASS — all accuracy/cadence/onset/dropout thresholds held.');
}
