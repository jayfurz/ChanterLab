import test from 'node:test';
import assert from 'node:assert/strict';

import {
  timedScoreFromParsedMusicXML,
  timedScoreFromCompiledChant,
  scopeLaneFromTimedScore,
  scoringInputsFromTimedScore,
  midiFromHz,
} from '../index.js';
import { WESTERN_PARSED_FIXTURE } from './fixtures/western_parsed.mjs';
import { compileChantScriptExample } from '../../web/score/examples.js';

function westernDoc() {
  return timedScoreFromParsedMusicXML(WESTERN_PARSED_FIXTURE, {
    scoreId: 'test:western-fixture',
    bpm: 120,
  });
}

function chantDoc(id = 'plagal-four-soft-chromatic') {
  return timedScoreFromCompiledChant(compileChantScriptExample(id), { scoreId: `chant:${id}` });
}

test('western lane matches what buildScopeLane hands setLane today', () => {
  const { selected, others, windowSec } = scopeLaneFromTimedScore(westernDoc(), { partId: 'S' });
  const spb = 60 / 120;
  const mk = (p) => p.notes.map((n) => ({
    start: n.startBeat * spb,
    end: (n.startBeat + n.durBeat) * spb,
    midi: n.midi,
    lyric: n.lyric || null,
  }));
  assert.deepEqual(selected, mk(WESTERN_PARSED_FIXTURE.parts[0]));
  assert.deepEqual(others, mk(WESTERN_PARSED_FIXTURE.parts[1]));
  assert.equal(windowSec, 6);
});

test('byzantine lane carries float MIDI, no other voices, rests excluded', () => {
  const doc = chantDoc();
  const { selected, others, windowSec } = scopeLaneFromTimedScore(doc);
  const notes = doc.timeline.events.filter((e) => e.kind === 'note');
  assert.equal(selected.length, notes.length);
  selected.forEach((n, i) => assert.equal(n.midi, midiFromHz(notes[i].target.hz)));
  assert.deepEqual(others, []);
  assert.equal(windowSec, doc.timeline.totalSec);
  assert.ok(selected.every((n) => n.end > n.start));
});

test('the lane a singer sees and the band they are scored on agree', () => {
  for (const doc of [westernDoc(), chantDoc()]) {
    const lane = scopeLaneFromTimedScore(doc);
    const { targets } = scoringInputsFromTimedScore(doc, { partId: lane.partId });
    assert.equal(lane.selected.length, targets.length);
    lane.selected.forEach((n, i) => {
      assert.equal(n.midi, targets[i].midi);
      assert.equal(n.start, targets[i].startSec);
      assert.equal(n.end, targets[i].endSec);
    });
  }
});

test('part selection and validation', () => {
  const alto = scopeLaneFromTimedScore(westernDoc(), { partId: 'A' });
  assert.equal(alto.partId, 'A');
  assert.equal(alto.others.length, WESTERN_PARSED_FIXTURE.parts[0].notes.length);
  assert.throws(() => scopeLaneFromTimedScore(westernDoc(), { partId: 'X' }), /unknown part/);
  assert.throws(() => scopeLaneFromTimedScore({}), /invalid document/);
});
