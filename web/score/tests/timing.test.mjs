import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import { compileChantScript } from '../compiler.js';
import { hasErrorDiagnostics } from '../diagnostics.js';

function readFixture(name) {
  return readFileSync(
    new URL(`../../../docs/examples/chant_scripts/${name}`, import.meta.url),
    'utf8'
  );
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

test('divide signs parse but remain diagnostic-only in v0 timing', () => {
  const compiled = compileChantScript([
    'title "Divide Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same',
    'note up 1 digorgon',
  ].join('\n'));

  assert.equal(compiled.diagnostics.some(diagnostic => diagnostic.code === 'temporal-divide-unimplemented'), true);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1, 1]);
});
