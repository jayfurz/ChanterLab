import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import { hasErrorDiagnostics } from '../diagnostics.js';
import { parseChantScript } from '../parser.js';

const FIXTURES = Object.freeze({
  diatonic: 'diatonic_ladder.chant',
  lyrics: 'lyrics_melisma.chant',
  soft: 'soft_chromatic_phrase.chant',
  steal: 'symbolic_timing_steal.chant',
});

function readFixture(name) {
  return readFileSync(
    new URL(`../../../docs/examples/chant_scripts/${name}`, import.meta.url),
    'utf8'
  );
}

function parseFixture(name) {
  return parseChantScript(readFixture(name), { sourceName: name });
}

test('parser accepts all seed chant fixtures without errors', () => {
  for (const name of Object.values(FIXTURES)) {
    const result = parseFixture(name);
    assert.equal(hasErrorDiagnostics(result.diagnostics), false, name);
  }
});

test('diatonic ladder headers and events parse into a semantic score', () => {
  const { score, diagnostics } = parseFixture(FIXTURES.diatonic);

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.equal(score.title, 'Diatonic Ladder Fixture');
  assert.equal(score.initialMartyria.degree, 'Ni');
  assert.equal(score.initialScale.scale, 'diatonic');
  assert.equal(score.defaultDrone, 'Ni');
  assert.equal(score.timingMode, 'symbolic');
  assert.equal(score.orthography, 'generated');
  assert.equal(score.events.length, 8);
  assert.equal(score.events.at(-1).type, 'martyria');
  assert.equal(score.events.at(-1).degree, 'Ni');
});

test('lyric metadata and melisma attachments stay separate', () => {
  const { score, diagnostics } = parseFixture(FIXTURES.lyrics);
  const lyricSequence = score.events
    .filter(event => event.type === 'neume')
    .map(event => event.lyric);

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.deepEqual(score.lyrics, [{ id: 'default', text: 'Amen', language: 'en' }]);
  assert.deepEqual(lyricSequence, [
    { kind: 'start', text: 'A-' },
    { kind: 'continue' },
    { kind: 'start', text: 'men' },
  ]);
});

test('soft chromatic fixture parses scale phase, rest duration, and checkpoint', () => {
  const { score, diagnostics } = parseFixture(FIXTURES.soft);
  const rest = score.events.find(event => event.type === 'rest');

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.equal(score.initialMartyria.degree, 'Di');
  assert.equal(score.initialScale.scale, 'soft-chromatic');
  assert.equal(score.initialScale.phase, 0);
  assert.equal(rest.durationBeats, 0.5);
  assert.equal(score.events.at(-1).degree, 'Ke');
});

test('parser handles aliases and case-insensitive names', () => {
  const script = [
    'TITLE "Alias Fixture"',
    'tempo metria bpm 132',
    'martyria di',
    'ison di',
    'timing symbolic',
    'same text "A"',
    'up 1 gorgon _',
    'hold 2 lyric "men"',
    'silence .5',
    'phrase checkpoint Ke',
  ].join('\n');

  const { score, diagnostics } = parseChantScript(script);

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.equal(score.initialMartyria.degree, 'Di');
  assert.equal(score.defaultDrone, 'Di');
  assert.equal(score.events.length, 5);
  assert.equal(score.events[1].temporal[0].type, 'quick');
  assert.deepEqual(score.events[1].lyric, { kind: 'continue' });
  assert.equal(score.events[2].baseBeats, 2);
  assert.equal(score.events[3].durationBeats, 0.5);
  assert.equal(score.events[4].checkpoint.degree, 'Ke');
});

test('note-local accidentals parse as even moria offsets', () => {
  const script = [
    'title "Accidental Fixture"',
    'tempo moderate',
    'start Ni',
    'scale diatonic',
    'note same accidental +4',
    'note up 1 flat 6',
    'note up 1 sharp 2',
  ].join('\n');

  const { score, diagnostics } = parseChantScript(script);

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.deepEqual(score.events.map(event => event.accidental?.moria), [4, -6, 2]);
});

test('unknown keywords produce line and column diagnostics', () => {
  const { diagnostics } = parseChantScript([
    'start Ni',
    'scale diatonic',
    'unknown-word',
  ].join('\n'));

  assert.equal(diagnostics.some(diagnostic => (
    diagnostic.code === 'unknown-keyword'
    && diagnostic.line === 3
    && diagnostic.column === 1
  )), true);
});

test('invalid accidental magnitudes produce diagnostics', () => {
  const { diagnostics } = parseChantScript([
    'start Ni',
    'scale diatonic',
    'note same accidental +3',
  ].join('\n'));

  assert.equal(diagnostics.some(diagnostic => diagnostic.code === 'invalid-accidental'), true);
});
