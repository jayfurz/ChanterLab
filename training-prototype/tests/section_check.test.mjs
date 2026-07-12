#!/usr/bin/env node
/*
 * SectionCheckAnalysis unit tests (issue #90 — post-hoc ensemble Section check).
 *
 * Node's built-in test runner, no framework/build step, matching
 * tests/scoring.test.mjs. Drives the exact same js/section_analysis.js the
 * browser loads (dual-mode node/browser module — see that file's header).
 *
 * The audio fixtures are synthesized here after the #84 spike's own voice
 * model (docs/design/MULTIPITCH-SPIKE.md §2.1): additive harmonics with 1/h
 * rolloff, vibrato ~18 cents at 5.5 Hz, clamped random-walk jitter, plus a
 * deterministic broadband noise bed — so ground truth is exact and every run
 * is bit-identical (seeded LCG, no Math.random). Rooms/reverb are the owner's
 * field-validation job (§7), not unit-testable.
 *
 * Run directly:  node training-prototype/tests/section_check.test.mjs
 * or:            node --test training-prototype/tests/section_check.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// UMD module (module.exports from a factory) — import the CJS default and
// destructure, same pattern scoring.test.mjs uses for scoring.js.
const SectionCheckAnalysis = (await import(path.join(__dirname, '..', 'js', 'section_analysis.js'))).default;
const { analyzeTake, createAnalyzer, aggregateSections, mapTransportToClip, midiToFreq } =
  SectionCheckAnalysis;

const SR = 48000;

/* ---------- synthetic-audio fixtures ------------------------------------ */

// Spike-style voice: 6 partials at 1/h, vibrato + random-walk jitter (both
// deterministic), 10 ms edge ramps. detuneCents shifts the SUNG pitch; the
// note timeline keeps the notated midi.
function renderVoice(buf, sr, midi, t0, t1, o = {}) {
  const det = o.detuneCents || 0;
  const H = o.harmonics || 6;
  const amp = o.amp || 0.2;
  const vibHz = o.vibHz || 5.5;
  const vibCents = o.vibCents != null ? o.vibCents : 18;
  const jitterStep = o.jitterStep != null ? o.jitterStep : 0.08;
  const f0 = midiToFreq(midi) * Math.pow(2, det / 1200);
  const i0 = Math.max(0, Math.round(t0 * sr));
  const i1 = Math.min(buf.length, Math.round(t1 * sr));
  const ramp = Math.round(0.01 * sr);
  const phase = new Float64Array(H + 1);
  let s = (o.seed || 42) >>> 0;
  let jitter = 0;
  for (let i = i0; i < i1; i++) {
    const t = (i - i0) / sr;
    s = (1103515245 * s + 12345) >>> 0;
    jitter = Math.max(-7, Math.min(7, jitter + ((s / 4294967296) - 0.5) * jitterStep));
    const cents = vibCents * Math.sin(2 * Math.PI * vibHz * t) + jitter;
    const f = f0 * Math.pow(2, cents / 1200);
    const dphi = 2 * Math.PI * f / sr;
    let x = 0;
    for (let h = 1; h <= H; h++) { phase[h] += h * dphi; x += (amp / h) * Math.sin(phase[h]); }
    buf[i] += x * Math.min(1, (i - i0) / ramp, (i1 - i) / ramp);
  }
}

// Deterministic broadband noise bed (every real capture has one; a perfectly
// sterile floor makes "dB over local floor" degenerate — spike §3.6).
function addNoise(buf, amp = 2e-3, seed = 987654321) {
  let s = seed >>> 0;
  for (let i = 0; i < buf.length; i++) {
    s = (1103515245 * s + 12345) >>> 0;
    buf[i] += amp * ((s / 4294967296) * 2 - 1);
  }
}

function note(midi, startSec = T0, endSec = T1, measure = 1) {
  return { midi, startSec, endSec, measure };
}
function part(key, name, notes) {
  return { key, name, notes };
}

// One chant-length note per part is plenty (1.5 s ⇒ ~64 analysis frames after
// the 90/60 ms edge gates), so per-note medians are meaningful.
const T0 = 0.10, T1 = 1.60;

/* ---------- measurement precision (stationary tone) --------------------- */

test('stationary in-tune tone: sub-cent measurement, result ok', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { vibCents: 0, jitterStep: 0 });
  const r = analyzeTake(buf, SR, [part('S', 'Soprano', [note(60)])]);
  const n = r.parts[0].notes[0];
  assert.equal(n.result, 'ok');
  assert.ok(Math.abs(n.cents) < 1, `cents ${n.cents} not sub-cent`);
  assert.ok(n.framesMeasured >= 30, `expected ≥30 frames, got ${n.framesMeasured}`);
});

/* ---------- single realistic voice: presence + intonation ---------------- */

test('in-tune voice (vibrato + jitter): result ok, cents within ±6', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { seed: 7 });
  addNoise(buf);
  const r = analyzeTake(buf, SR, [part('S', 'Soprano', [note(60)])]);
  const n = r.parts[0].notes[0];
  assert.equal(n.result, 'ok');
  assert.ok(Math.abs(n.cents) < 6, `cents ${n.cents} not within ±6`);
});

test('30 cents flat: result flat, measured cents in (−40, −20)', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { detuneCents: -30, seed: 7 });
  addNoise(buf);
  const r = analyzeTake(buf, SR, [part('S', 'Soprano', [note(60)])]);
  const n = r.parts[0].notes[0];
  assert.equal(n.result, 'flat');
  assert.ok(n.cents > -40 && n.cents < -20, `cents ${n.cents} not ≈ −30`);
});

test('30 cents sharp: result sharp, measured cents in (+20, +40)', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { detuneCents: 30, seed: 7 });
  addNoise(buf);
  const r = analyzeTake(buf, SR, [part('S', 'Soprano', [note(60)])]);
  const n = r.parts[0].notes[0];
  assert.equal(n.result, 'sharp');
  assert.ok(n.cents > 20 && n.cents < 40, `cents ${n.cents} not ≈ +30`);
});

test('a note too short for the edge gates abstains (never guesses)', () => {
  const buf = new Float32Array(1 * SR);
  renderVoice(buf, SR, 60, 0.10, 0.22);
  addNoise(buf);
  const r = analyzeTake(buf, SR, [part('S', 'Soprano', [note(60, 0.10, 0.22)])]);
  assert.equal(r.parts[0].notes[0].result, 'abstain');
});

/* ---------- two parts: attribution + false-accusation guards ------------- */

// C4 vs F#4 (a tritone): expected harmonics rarely coincide, so both parts
// keep free bands — the "which part is detuned" headline case.
test('two parts, one detuned: the flat part is named, the in-tune part is NOT accused', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { seed: 11 });                        // Soprano in tune
  renderVoice(buf, SR, 66, T0, T1, { detuneCents: -40, seed: 22 });      // Alto 40c flat
  addNoise(buf);
  const r = analyzeTake(buf, SR, [
    part('S', 'Soprano', [note(60)]),
    part('A', 'Alto', [note(66)]),
  ]);
  const s = r.parts[0].notes[0], a = r.parts[1].notes[0];
  assert.equal(s.result, 'ok', `soprano falsely accused: ${s.result} ${s.cents}¢`);
  assert.equal(a.result, 'flat');
  assert.ok(a.cents < -15 && a.cents > -50, `alto cents ${a.cents} not clearly flat`);

  const agg = aggregateSections(r, null);
  assert.equal(agg.overall[0].verdict, 'in-tune');
  assert.equal(agg.overall[1].verdict, 'flat');
});

test('a silent part is NEVER given an intonation verdict (accusation guard)', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { seed: 7 });   // Soprano sings...
  addNoise(buf);
  const r = analyzeTake(buf, SR, [                 // ...Alto expected but silent
    part('S', 'Soprano', [note(60)]),
    part('A', 'Alto', [note(66)]),
  ]);
  assert.equal(r.parts[0].notes[0].result, 'ok');
  const a = r.parts[1].notes[0];
  assert.ok(a.result === 'abstain' || a.result === 'missing',
    `silent alto must degrade to no-verdict, got ${a.result} ${a.cents}¢`);
  const agg = aggregateSections(r, null);
  const av = agg.overall[1].verdict;
  assert.ok(av === 'not-attributable' || av === 'not-heard', `got ${av}`);
});

// The decisive-missing mechanism: a silent LOW part under a sounding HIGH part
// keeps several genuinely-free low bands. The absolute presence gate is a
// floor-statistics call (the spike tuned 5 dB on realistic room mixes; on this
// synthetic noise-only floor the peak-over-median statistic itself sits ≈5 dB),
// so the mechanism is asserted with the gate at 8 dB — far below any sounding
// part here (≥35 dB), far above true absence proof being possible.
test('a silent bass under a soprano is detected missing; the section reads not-heard', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 72, T0, T1, { seed: 5 });   // C5 soprano sings
  addNoise(buf);
  const r = analyzeTake(buf, SR, [
    part('S', 'Soprano', [note(72)]),
    part('B', 'Bass', [note(48)]),                 // C3 bass expected, silent
  ], { presenceMissingDb: 8 });
  const b = r.parts[1].notes[0];
  assert.equal(b.result, 'missing');
  // The soprano two octaves above an expected bass is fully masked by the
  // score's own collision rule (every S harmonic = a plausible B harmonic).
  assert.equal(r.parts[0].notes[0].result, 'abstain');
  const agg = aggregateSections(r, null);
  assert.equal(agg.overall[1].verdict, 'not-heard');
  assert.equal(agg.overall[0].verdict, 'not-attributable');
});

test('when the bass DOES sing under the soprano it reads ok (no false missing)', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 72, T0, T1, { seed: 5 });
  renderVoice(buf, SR, 48, T0, T1, { seed: 6 });
  addNoise(buf);
  const r = analyzeTake(buf, SR, [
    part('S', 'Soprano', [note(72)]),
    part('B', 'Bass', [note(48)]),
  ], { presenceMissingDb: 8 });
  const b = r.parts[1].notes[0];
  assert.equal(b.result, 'ok');
  assert.ok(Math.abs(b.cents) < 6, `bass cents ${b.cents}`);
});

test('unison collision: both parts abstain (masking is physics — spike §2.3)', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { seed: 1 });
  renderVoice(buf, SR, 60, T0, T1, { detuneCents: 25, seed: 2 });
  addNoise(buf);
  const r = analyzeTake(buf, SR, [
    part('S', 'Soprano', [note(60)]),
    part('A', 'Alto', [note(60)]),
  ]);
  assert.equal(r.parts[0].notes[0].result, 'abstain');
  assert.equal(r.parts[1].notes[0].result, 'abstain');
  const agg = aggregateSections(r, null);
  assert.equal(agg.overall[0].verdict, 'not-attributable');
  assert.equal(agg.overall[1].verdict, 'not-attributable');
});

test('octave collision: the upper part is masked, the lower keeps its odd harmonics', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 48, T0, T1, { seed: 3 });   // C3 (lower)
  renderVoice(buf, SR, 60, T0, T1, { seed: 4 });   // C4 (upper, octave above)
  addNoise(buf);
  const r = analyzeTake(buf, SR, [
    part('T', 'Tenor', [note(60)]),   // upper: every harmonic collides
    part('B', 'Bass', [note(48)]),    // lower: odd harmonics stay free
  ]);
  assert.equal(r.parts[0].notes[0].result, 'abstain');
  assert.equal(r.parts[1].notes[0].result, 'ok');
});

/* ---------- chunked analyzer ≡ synchronous analyzer ---------------------- */

test('createAnalyzer stepped in small chunks matches analyzeTake exactly', () => {
  const buf = new Float32Array(2 * SR);
  renderVoice(buf, SR, 60, T0, T1, { detuneCents: -30, seed: 7 });
  addNoise(buf);
  const parts = [part('S', 'Soprano', [note(60)])];
  const sync = analyzeTake(buf, SR, parts);
  const a = createAnalyzer(buf, SR, parts);
  let guard = 0;
  while (!a.step(7)) { if (++guard > 1e5) throw new Error('no progress'); }
  assert.deepEqual(a.finish(), sync);
});

/* ---------- section aggregation ------------------------------------------ */

function fakeNote(result, cents, measure) {
  return { midi: 60, measure, startSec: 0, endSec: 1, result, cents,
           presenceDb: 20, framesMeasured: 10, framesMasked: 0 };
}

test('aggregateSections groups by printed-measure ranges with per-section verdicts', () => {
  const analysis = {
    parts: [{
      key: 'S', name: 'Soprano',
      notes: [
        fakeNote('flat', -25, 1), fakeNote('flat', -28, 1), fakeNote('flat', -26, 2),
        fakeNote('ok', 2, 3), fakeNote('ok', -1, 3), fakeNote('ok', 4, 4),
      ],
    }],
  };
  const sections = [
    { title: 'Intro', fromMeasure: 1, toMeasure: 2 },
    { title: 'Verse', fromMeasure: 3, toMeasure: 4 },
  ];
  const agg = aggregateSections(analysis, sections);
  assert.equal(agg.sections.length, 2);
  assert.equal(agg.sections[0].parts[0].verdict, 'flat');
  assert.equal(agg.sections[0].parts[0].cents, -26);
  assert.equal(agg.sections[1].parts[0].verdict, 'in-tune');
  assert.equal(agg.overall[0].total, 6);
  assert.equal(agg.overall[0].scored, 6);
});

test('aggregateSections: not-heard, not-attributable, no-notes and low-confidence flags', () => {
  const analysis = {
    parts: [
      { key: 'S', name: 'Soprano', notes: [fakeNote('missing', null, 1), fakeNote('missing', null, 1), fakeNote('ok', 0, 1)] },
      { key: 'A', name: 'Alto', notes: [fakeNote('abstain', null, 1), fakeNote('abstain', null, 1)] },
      { key: 'T', name: 'Tenor', notes: [] },
      { key: 'B', name: 'Bass', notes: [fakeNote('ok', 1, 1), fakeNote('ok', 2, 1)] },
    ],
  };
  const agg = aggregateSections(analysis, null);   // no sections ⇒ one whole-take block
  assert.equal(agg.sections.length, 1);
  assert.equal(agg.sections[0].title, 'Whole take');
  assert.equal(agg.overall[0].verdict, 'not-heard');        // 2 of 3 scored notes missing
  assert.equal(agg.overall[1].verdict, 'not-attributable'); // everything masked
  assert.equal(agg.overall[2].verdict, 'no-notes');
  assert.equal(agg.overall[3].verdict, 'in-tune');
  assert.equal(agg.overall[3].lowConfidence, true);         // only 2 scored notes
});

/* ---------- transport→clip alignment -------------------------------------- */

test('mapTransportToClip: anchor math and linearity', () => {
  const map = mapTransportToClip({ clipSec: 5.0, transportSec: 2.0, latencySec: 0.3 });
  // at the anchor instant, transport time maps to clip time + the audible lag
  assert.ok(Math.abs(map(2.0) - 5.3) < 1e-9);
  // the window start (transport 0) sits latency-late in the clip too
  assert.ok(Math.abs(map(0) - 3.3) < 1e-9);
  // strictly linear: intervals are preserved exactly
  assert.ok(Math.abs((map(10) - map(4)) - 6) < 1e-9);
});

test('mapTransportToClip: degenerate anchors degrade to a finite identity-ish map', () => {
  const map = mapTransportToClip(null);
  assert.equal(map(1.5), 1.5);
  const map2 = mapTransportToClip({ clipSec: NaN, transportSec: undefined, latencySec: 'x' });
  assert.ok(isFinite(map2(2)));
});

/* ---------- timing-contract characterization (documents, not enforces) ---- */

// The live path subtracts L_out + L_in from sample stamps (the calibration SUM
// invariant — js/calibrate.js); the post-hoc path ADDS only L_out to note
// windows. This test pins the intended relationship: a singer exactly on the
// audible beat lands exactly on the mapped note window, with NO L_in term.
test('post-hoc alignment uses L_out only: an on-the-audible-beat onset lands on the note', () => {
  const L_OUT = 0.25;              // schedule→audible on the recording device
  const noteStartTransport = 4.0;  // schedule-domain note start
  // recording started 1.7 s before transport 0; anchor taken at transport 2.
  const map = mapTransportToClip({ clipSec: 3.7, transportSec: 2.0, latencySec: L_OUT });
  // The beat is AUDIBLE (and sung, and captured) at clip time:
  const audibleAtClip = (noteStartTransport + 1.7) + L_OUT;
  assert.ok(Math.abs(map(noteStartTransport) - audibleAtClip) < 1e-9);
});
