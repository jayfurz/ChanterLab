#!/usr/bin/env node
/*
 * ChanterScoring unit tests (issue #55 — Scoring v1).
 *
 * Node's built-in test runner, no framework/build step, matching the rest of
 * this app. Drives the exact same scoring.js the browser loads (dual-mode
 * node/browser module — see that file's header).
 *
 * Run directly:  node training-prototype/tests/scoring.test.mjs
 * or:             node --test training-prototype/tests
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// scoring.js is a UMD module (module.exports = {...} built by a factory
// function) — Node's CJS/ESM interop can't statically detect its named
// exports, so import the CJS default and destructure from that instead of
// relying on `import { x } from ...` against a .js/commonjs file.
const ChanterScoring = (await import(path.join(__dirname, '..', 'scoring.js'))).default;
const { scoreNotes, summaryLine, worstSpots, PRESETS, centsToTarget } = ChanterScoring;

// Dense, evenly-spaced samples (well under maxGap=0.05s) so coverage math
// reflects sustained voicing rather than dropout handling — see scoring.js's
// header comment on the dropout/coverage decision.
function dense(startSec, endSec, midi, step = 0.02) {
  const out = [];
  for (let t = startSec; t < endSec; t += step) out.push({ tSec: +t.toFixed(3), midi });
  return out;
}

test('scoreNotes: dead-on note scores hit with full coverage', () => {
  const targets = [{ midi: 60, startSec: 0, endSec: 1, measure: 1 }];
  const samples = dense(0.15, 1.0, 60); // past the 0.1s attack grace
  const r = scoreNotes(targets, samples);
  assert.equal(r.notes, 1);
  assert.equal(r.hit, 1);
  assert.equal(r.hitPct, 100);
  assert.equal(r.details[0].result, 'hit');
  assert.equal(r.details[0].measure, 1);
});

test('scoreNotes: octave-tolerant — an octave-down sung pitch still hits', () => {
  const targets = [{ midi: 72, startSec: 0, endSec: 1 }]; // C5
  const samples = dense(0.15, 1.0, 60); // C4, one octave low
  const r = scoreNotes(targets, samples);
  assert.equal(r.details[0].result, 'hit');
  assert.equal(centsToTarget(60, 72), 0);
});

test('scoreNotes: no samples in the note -> missed', () => {
  const targets = [{ midi: 60, startSec: 0, endSec: 1, measure: 5 }];
  const r = scoreNotes(targets, []);
  assert.equal(r.missed, 1);
  assert.equal(r.details[0].result, 'missed');
  assert.equal(r.details[0].measure, 5); // measure passes through even when missed
});

test('scoreNotes: measure rides through to details[] unmodified; absent -> null', () => {
  const targets = [
    { midi: 60, startSec: 0, endSec: 1, measure: 3 },
    { midi: 62, startSec: 1, endSec: 2 }, // no measure supplied
  ];
  const r = scoreNotes(targets, dense(0.15, 1.9, 60));
  assert.equal(r.details[0].measure, 3);
  assert.equal(r.details[1].measure, null);
});

test('PRESETS.relaxed matches the historical no-opts call exactly', () => {
  const targets = [{ midi: 60, startSec: 0, endSec: 1 }];
  const samples = dense(0.15, 1.0, 61); // ~+167 cents sharp: hit under 50c-relaxed? no, out of tol
  const withNoOpts = scoreNotes(targets, samples);
  const withRelaxedPreset = scoreNotes(targets, samples, PRESETS.relaxed);
  assert.deepEqual(withRelaxedPreset, withNoOpts);
});

test('PRESETS.strict is tighter than PRESETS.relaxed on a borderline (40 cents flat) note', () => {
  const targets = [{ midi: 62, startSec: 0, endSec: 1, measure: 7 }];
  const samples = dense(0.15, 1.0, 61.6); // 40 cents flat of midi 62
  const relaxed = scoreNotes(targets, samples, PRESETS.relaxed); // 50c tol -> hit
  const strict = scoreNotes(targets, samples, PRESETS.strict);   // 35c tol -> flat
  assert.equal(relaxed.details[0].result, 'hit');
  assert.equal(strict.details[0].result, 'flat');
});

test('worstSpots: groups non-hit notes by measure, sorted worst-first, ties by ascending measure', () => {
  const targets = [
    { midi: 60, startSec: 0, endSec: 1, measure: 1 },
    { midi: 60, startSec: 1, endSec: 2, measure: 1 },
    { midi: 60, startSec: 2, endSec: 3, measure: 2 },
    { midi: 60, startSec: 3, endSec: 4, measure: 3 },
    { midi: 60, startSec: 4, endSec: 5, measure: 3 },
  ];
  // Note 0 (m1) hit; note 1 (m1) missed; note 2 (m2) missed; notes 3+4 (m3) missed.
  const samples = dense(0.15, 1.0, 60);
  const r = scoreNotes(targets, samples);
  const spots = worstSpots(r, 3);
  assert.deepEqual(spots.map((s) => s.measure), [3, 1, 2]); // m3 has 2 bad, m1 and m2 have 1 each (m1 before m2)
  assert.equal(spots[0].bad, 2);
  assert.equal(spots[0].missed, 2);
});

test('worstSpots: respects the limit and returns [] for a clean (all-hit) result', () => {
  const targets = [{ midi: 60, startSec: 0, endSec: 1, measure: 1 }];
  const r = scoreNotes(targets, dense(0.15, 1.0, 60));
  assert.deepEqual(worstSpots(r), []);
  assert.equal(worstSpots(null).length, 0);
  assert.equal(worstSpots({ details: [] }).length, 0);
});

test('summaryLine: formats totals, and handles the no-targets case', () => {
  const targets = [{ midi: 60, startSec: 0, endSec: 1 }];
  const r = scoreNotes(targets, dense(0.15, 1.0, 60));
  assert.equal(summaryLine(r), 'Scored 1 notes: 1 hit · 0 flat · 0 sharp · 0 missed (100%)');
  assert.equal(summaryLine({ notes: 0 }), 'No target notes in this loop to score.');
  assert.equal(summaryLine(null), 'No target notes in this loop to score.');
});
