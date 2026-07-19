import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  timedScoreFromParsedMusicXML,
  timedScoreFromCompiledChant,
  scoringInputsFromTimedScore,
  CENTS_PER_MORIA,
  midiFromHz,
} from '../index.js';
import { WESTERN_PARSED_FIXTURE } from './fixtures/western_parsed.mjs';
import { compileChantScriptExample } from '../../web/score/examples.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// scoring.js is the app's UMD scorer; import the CJS default like the
// training-prototype tests do (see training-prototype/tests/scoring.test.mjs).
const ChanterScoring = (
  await import(path.join(__dirname, '..', '..', 'training-prototype', 'scoring.js'))
).default;
const { scoreNotes } = ChanterScoring;

function westernDoc(options = {}) {
  return timedScoreFromParsedMusicXML(WESTERN_PARSED_FIXTURE, {
    scoreId: 'test:western-fixture',
    bpm: 120,
    ...options,
  });
}

function chantDoc(id = 'diatonic-ladder') {
  return timedScoreFromCompiledChant(compileChantScriptExample(id), { scoreId: `chant:${id}` });
}

// Dense on-pitch samples across a target, offset by `deltaMidi` (float
// semitones), matching the sampling style of the scorer's own tests.
function sing(targets, deltaMidi = 0, step = 0.02) {
  const out = [];
  for (const t of targets) {
    for (let s = t.startSec; s < t.endSec; s += step) {
      out.push({ tSec: +s.toFixed(4), midi: t.midi + deltaMidi });
    }
  }
  return out;
}

test('western documents produce the same targets scoring-ui builds today', () => {
  const { targets, opts } = scoringInputsFromTimedScore(westernDoc(), { partId: 'S' });
  const spb = 60 / 120;
  const expected = WESTERN_PARSED_FIXTURE.parts[0].notes.map((n) => ({
    midi: n.midi,
    startSec: n.startBeat * spb,
    endSec: (n.startBeat + n.durBeat) * spb,
    lyric: n.lyric || null,
    measure: n.measure,
  }));
  assert.deepEqual(targets, expected);
  assert.deepEqual(opts, {}); // presets stay the caller's business
  assert.ok(targets.every((t) => Number.isInteger(t.midi)), 'native MIDI passes through untouched');
});

test('byzantine documents become float-MIDI targets with 72-EDO precision', () => {
  const doc = chantDoc();
  const { targets, opts } = scoringInputsFromTimedScore(doc);
  const notes = doc.timeline.events.filter((e) => e.kind === 'note');
  assert.equal(targets.length, notes.length);
  targets.forEach((t, i) => {
    assert.equal(t.midi, midiFromHz(notes[i].target.hz));
  });
  assert.ok(
    targets.some((t) => Math.abs(t.midi - Math.round(t.midi)) > 0.05),
    'at least one target sits off the 12-ET grid',
  );
  assert.ok(Math.abs(opts.centsTol - 4 * CENTS_PER_MORIA) < 1e-12, 'default band is 4 moria');
});

test('the existing scorer scores a chant: on-pitch singing hits every note', () => {
  const { targets, opts } = scoringInputsFromTimedScore(chantDoc());
  const result = scoreNotes(targets, sing(targets), opts);
  assert.equal(result.hit, targets.length);
  assert.equal(result.missed, 0);
});

test('the moria tolerance band behaves like Byzantine practice', () => {
  const { targets, opts } = scoringInputsFromTimedScore(chantDoc());
  // +3 moria = 50 cents: inside the 4-moria (66.7 cent) band.
  const close = scoreNotes(targets, sing(targets, 3 / 6), opts);
  assert.equal(close.hit, targets.length, '+3 moria stays a hit');
  // +6 moria = a full semitone: outside the band, sharp on every note.
  const off = scoreNotes(targets, sing(targets, 6 / 6), opts);
  assert.equal(off.hit, 0, '+6 moria never hits');
  assert.equal(off.sharp, targets.length);
});

test('octave folding carries over: singing an octave up still hits', () => {
  const { targets, opts } = scoringInputsFromTimedScore(chantDoc());
  const result = scoreNotes(targets, sing(targets, 12), opts);
  assert.equal(result.hit, targets.length);
});

test('part selection and input validation', () => {
  const doc = westernDoc();
  const alto = scoringInputsFromTimedScore(doc, { partId: 'A' });
  assert.equal(alto.partId, 'A');
  assert.equal(alto.targets.length, WESTERN_PARSED_FIXTURE.parts[1].notes.length);

  const defaulted = scoringInputsFromTimedScore(doc);
  assert.equal(defaulted.partId, 'S'); // first selectable part

  assert.throws(() => scoringInputsFromTimedScore(doc, { partId: 'X' }), /unknown part/);
  assert.throws(() => scoringInputsFromTimedScore(doc, { toleranceMoria: 0 }), /toleranceMoria/);
  assert.throws(() => scoringInputsFromTimedScore({ nope: true }), /invalid document/);
});
