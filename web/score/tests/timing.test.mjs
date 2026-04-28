import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import { compileChantScript } from '../compiler.js';
import { hasErrorDiagnostics } from '../diagnostics.js';
import { TEMPORAL_RULES } from '../timing.js';

function readFixture(name) {
  return readFileSync(
    new URL(`../../../docs/examples/chant_scripts/${name}`, import.meta.url),
    'utf8'
  );
}

function assertDurationsAlmostEqual(actual, expected) {
  assert.equal(actual.length, expected.length);
  for (let index = 0; index < actual.length; index += 1) {
    assert.ok(
      Math.abs(actual[index] - expected[index]) < 1e-12,
      `duration ${index}: expected ${expected[index]}, got ${actual[index]}`
    );
  }
}

test('symbolic timing rewrites beats 2 plus quick into 1.5 and 0.5 beats', () => {
  const compiled = compileChantScript(readFixture('symbolic_timing_steal.chant'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1.5, 0.5]);
  assert.equal(compiled.totalDurationMs, 60000 / 132 * 2);
});

test('rest duration is exact silent time in symbolic mode', () => {
  const compiled = compileChantScript([
    'title "Rest Duration Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'timing symbolic',
    'note same',
    'rest duration 0.5',
    'note up 1',
  ].join('\n'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.equal(compiled.rests[0].durationBeats, 0.5);
  assert.deepEqual(compiled.timeline
    .filter(event => event.type === 'note' || event.type === 'rest')
    .map(event => event.durationBeats), [1, 0.5, 1]);
});

test('rest quick emits a diagnostic instead of crashing', () => {
  const compiled = compileChantScript([
    'title "Rest Quick Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'rest quick',
  ].join('\n'));

  assert.equal(compiled.diagnostics.some(diagnostic => diagnostic.code === 'rest-quick-unsupported'), true);
  assert.equal(compiled.rests.length, 1);
});

test('unsupported divide signs remain diagnostic-only in symbolic timing', () => {
  const compiled = compileChantScript([
    'title "Unsupported Divide Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same',
    'note up 1 divide 5',
  ].join('\n'));

  assert.equal(compiled.diagnostics.some(diagnostic => diagnostic.code === 'temporal-divide-unsupported'), true);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1, 1]);
});

test('phase 3 temporal rules expose gorgon digorgon and trigorgon windows', () => {
  assert.deepEqual(
    Object.values(TEMPORAL_RULES).map(rule => [
      rule.sign,
      rule.windowBefore,
      rule.windowAfter,
      rule.outputFractions.length,
    ]),
    [
      ['gorgon', 1, 0, 2],
      ['digorgon', 1, 1, 3],
      ['trigorgon', 1, 2, 4],
    ]
  );
});

test('digorgon redistributes one parent beat across three notes', () => {
  const compiled = compileChantScript([
    'title "Digorgon Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same',
    'note up 1 digorgon',
    'note down 1',
  ].join('\n'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assertDurationsAlmostEqual(compiled.notes.map(note => note.durationBeats), [1 / 3, 1 / 3, 1 / 3]);
  assert.equal(compiled.totalDurationMs, 500);
});

test('trigorgon redistributes one parent beat across four notes', () => {
  const compiled = compileChantScript([
    'title "Trigorgon Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same',
    'note up 1 trigorgon',
    'note down 1',
    'note same',
  ].join('\n'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assertDurationsAlmostEqual(compiled.notes.map(note => note.durationBeats), [1 / 4, 1 / 4, 1 / 4, 1 / 4]);
  assert.equal(compiled.totalDurationMs, 500);
});

test('temporal rules borrow from extended previous notes while preserving the local window', () => {
  const compiled = compileChantScript([
    'title "Extended Temporal Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same beats 2',
    'note up 1 digorgon',
    'note down 1',
  ].join('\n'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assertDurationsAlmostEqual(compiled.notes.map(note => note.durationBeats), [4 / 3, 1 / 3, 1 / 3]);
  assert.equal(compiled.totalDurationMs, 1000);
});

test('temporal rules diagnose missing following notes', () => {
  const compiled = compileChantScript([
    'title "Broken Digorgon Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same',
    'note up 1 digorgon',
  ].join('\n'));

  assert.equal(compiled.diagnostics.some(diagnostic => diagnostic.code === 'digorgon-window-invalid'), true);
});

test('qualitative style and quality signs are preserved but non-operative', () => {
  const compiled = compileChantScript([
    'title "Qualitative Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same style petasti quality vareia',
    'note up 1',
  ].join('\n'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1, 1]);
  assert.deepEqual(compiled.notes[0].qualitative.map(sign => [sign.type, sign.name]), [
    ['style', 'petasti'],
    ['quality', 'vareia'],
  ]);
});

test('temporal rules fixture compiles gorgon digorgon and trigorgon windows', () => {
  const compiled = compileChantScript(readFixture('temporal_rules.chant'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assertDurationsAlmostEqual(compiled.notes.map(note => note.durationBeats), [
    1 / 2,
    1 / 2,
    1 / 3,
    1 / 3,
    1 / 3,
    1 / 4,
    1 / 4,
    1 / 4,
    1 / 4,
  ]);
  assert.equal(compiled.totalDurationMs, 1500);
});
