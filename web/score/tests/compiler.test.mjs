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

test('compiler resolves diatonic ladder relative movement and checkpoints', () => {
  const compiled = compileChantScript(readFixture('diatonic_ladder.chant'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.degree), [
    'Ni', 'Pa', 'Vou', 'Ga', 'Vou', 'Pa', 'Ni',
  ]);
  assert.deepEqual(compiled.notes.map(note => note.moria), [
    0, 12, 22, 30, 22, 12, 0,
  ]);
  assert.equal(compiled.checkpoints.length, 1);
  assert.equal(compiled.checkpoints[0].degree, 'Ni');
  assert.equal(compiled.checkpoints[0].matches, true);
});

test('compiler preserves lyrics and generated default glyph hints', () => {
  const compiled = compileChantScript(readFixture('lyrics_melisma.chant'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.lyric), [
    { kind: 'start', text: 'A-' },
    { kind: 'continue' },
    { kind: 'start', text: 'men' },
  ]);
  assert.deepEqual(compiled.notes.map(note => note.display.generatedGlyphNames), [
    ['ison'],
    ['oligon'],
    ['apostrofos', 'gorgon'],
  ]);
});

test('compiler carries soft chromatic scale context and rests', () => {
  const compiled = compileChantScript(readFixture('soft_chromatic_phrase.chant'));

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.degree), ['Di', 'Ke', 'Di', 'Di', 'Ke']);
  assert.deepEqual(compiled.notes.map(note => note.moria), [42, 50, 42, 42, 50]);
  assert.deepEqual(compiled.notes.map(note => note.scale.scale), [
    'soft-chromatic',
    'soft-chromatic',
    'soft-chromatic',
    'soft-chromatic',
    'soft-chromatic',
  ]);
  assert.equal(compiled.rests.length, 1);
  assert.equal(compiled.rests[0].durationBeats, 0.5);
  assert.equal(compiled.checkpoints[0].degree, 'Ke');
  assert.equal(compiled.checkpoints[0].matches, true);
});

test('compiler attaches pthora and ison changes without changing movement semantics', () => {
  const script = [
    'title "Pthora Fixture"',
    'tempo moderate bpm 132',
    'start Di',
    'scale diatonic',
    'note same scale soft-chromatic phase 0 drone Di',
    'note up 1',
    'checkpoint Ke',
  ].join('\n');

  const compiled = compileChantScript(script);

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.equal(compiled.notes[0].degree, 'Di');
  assert.equal(compiled.notes[0].pthora.scale, 'soft-chromatic');
  assert.equal(compiled.notes[0].pthora.dropDegree, 'Di');
  assert.equal(compiled.notes[0].pthora.dropMoria, 42);
  assert.equal(compiled.notes[1].degree, 'Ke');
  assert.equal(compiled.notes[1].scale.scale, 'soft-chromatic');
  assert.equal(compiled.pthoraEvents.length, 1);
  assert.equal(compiled.pthoraEvents[0].degree, 'Di');
  assert.equal(compiled.pthoraEvents[0].dropMoria, 42);
  assert.equal(compiled.isonEvents.length, 1);
  assert.equal(compiled.timeline.some(event => event.type === 'ison' && event.degree === 'Di'), true);
});

test('compiler emits default and explicit ison timeline events', () => {
  const script = [
    'title "Ison Fixture"',
    'tempo moderate bpm 120',
    'start Ni',
    'scale diatonic',
    'drone Ni',
    'note same',
    'ison Pa',
    'note up 1',
    'note up 1 drone Vou',
  ].join('\n');

  const compiled = compileChantScript(script);

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.isonEvents.map(event => [event.degree, event.atMs, event.kind]), [
    ['Ni', 0, 'default'],
    ['Pa', 500, 'explicit'],
    ['Vou', 1000, 'note'],
  ]);
  assert.deepEqual(
    compiled.timeline.filter(event => event.type === 'ison').map(event => event.degree),
    ['Ni', 'Pa', 'Vou']
  );
});

test('compiler promotes note-local martyria checkpoints into compiled checkpoint events', () => {
  const script = [
    'title "Note Checkpoint Fixture"',
    'tempo moderate bpm 132',
    'start Di',
    'scale diatonic',
    'note same checkpoint Di',
    'note up 1',
  ].join('\n');

  const compiled = compileChantScript(script);

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.equal(compiled.checkpoints.length, 1);
  assert.equal(compiled.checkpoints[0].degree, 'Di');
  assert.equal(compiled.checkpoints[0].actualDegree, 'Di');
  assert.equal(compiled.checkpoints[0].atMs, 0);
  assert.equal(compiled.timeline[1].type, 'martyria');
});

test('compiler applies accidentals only to the compiled note target', () => {
  const script = [
    'title "Accidental Compile Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'note same accidental +4',
    'note up 1',
    'note up 1 flat 6',
    'note up 1',
  ].join('\n');

  const compiled = compileChantScript(script);

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.degree), ['Ni', 'Pa', 'Vou', 'Ga']);
  assert.deepEqual(compiled.notes.map(note => note.moria), [0, 12, 22, 30]);
  assert.deepEqual(compiled.notes.map(note => note.effectiveMoria), [4, 12, 16, 30]);
  assert.deepEqual(compiled.notes.map(note => note.accidental?.moria ?? 0), [4, 0, -6, 0]);
});

test('exact timing uses duration values and rejects symbolic temporal modifiers', () => {
  const script = [
    'title "Exact Fixture"',
    'tempo bpm 120',
    'start Ni',
    'scale diatonic',
    'timing exact',
    'note same duration 1.5',
    'note up 1 duration 0.5',
    'note up 1 quick duration 0.25',
  ].join('\n');

  const compiled = compileChantScript(script);

  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1.5, 0.5, 0.25]);
  assert.equal(compiled.diagnostics.some(diagnostic => diagnostic.code === 'exact-symbolic-temporal'), true);
});
