import test from 'node:test';
import assert from 'node:assert/strict';

import {
  timedScoreFromCompiledChant,
  validateTimedScore,
  hzFromMoria,
  DEFAULT_REF_NI_HZ,
} from '../index.js';
import {
  compileChantScriptExample,
  listChantScriptExamples,
} from '../../web/score/examples.js';
import { createScorePracticeState } from '../../web/score/score_practice.js';

const exampleIds = listChantScriptExamples().map((e) => e.id ?? e);

test('every example chant script adapts to a valid document', () => {
  assert.ok(exampleIds.length > 0, 'chant script examples exist');
  for (const id of exampleIds) {
    const compiled = compileChantScriptExample(id);
    const doc = timedScoreFromCompiledChant(compiled, { scoreId: `chant:${id}` });
    const result = validateTimedScore(doc);
    assert.deepEqual(result.errors, [], `example "${id}" validates`);
    assert.equal(doc.capabilities.microtonal, true);
  }
});

test('adapter timeline matches the shipping score-practice projection', () => {
  for (const id of exampleIds) {
    const compiled = compileChantScriptExample(id);
    const doc = timedScoreFromCompiledChant(compiled, { scoreId: `chant:${id}` });
    const practice = createScorePracticeState(compiled);

    const practiceNotes = practice.targets.filter((t) => t.type === 'note');
    const docNotes = doc.timeline.events.filter((e) => e.kind === 'note');
    assert.equal(docNotes.length, practiceNotes.length, `${id}: note count`);
    docNotes.forEach((e, i) => {
      const want = practiceNotes[i];
      assert.equal(e.startSec, want.startMs / 1000, `${id}[${i}]: startSec`);
      assert.equal(e.endSec, want.endMs / 1000, `${id}[${i}]: endSec`);
      assert.equal(e.target.pitch.moria, want.moria, `${id}[${i}]: moria (score_practice precedence)`);
      assert.equal(e.target.hz, hzFromMoria(want.moria, DEFAULT_REF_NI_HZ), `${id}[${i}]: hz from moria`);
    });

    assert.equal(doc.timeline.ison.length, practice.isonEvents.length, `${id}: ison lane`);
    doc.timeline.ison.forEach((entry, i) => {
      assert.equal(entry.atSec, practice.isonEvents[i].atMs / 1000, `${id}: ison[${i}] atSec`);
    });
    assert.equal(doc.timeline.tuningChanges.length, practice.pthoraEvents.length, `${id}: tuning changes`);
    assert.equal(doc.timeline.totalSec, practice.totalDurationMs / 1000, `${id}: total duration`);
  }
});

test('rests are first-class events on the chant side', () => {
  const compiled = compileChantScriptExample('soft-chromatic-phrase');
  const doc = timedScoreFromCompiledChant(compiled, { scoreId: 'chant:soft-chromatic-phrase' });
  const rests = doc.timeline.events.filter((e) => e.kind === 'rest');
  assert.ok(rests.length > 0, 'the soft chromatic example contains a rest');
  assert.equal(doc.capabilities.explicitRests, true);
  for (const r of rests) assert.equal(r.target, null);

  const noRests = timedScoreFromCompiledChant(compiled, {
    scoreId: 'chant:soft-chromatic-phrase',
    includeRests: false,
  });
  assert.equal(noRests.timeline.events.filter((e) => e.kind === 'rest').length, 0);
  assert.equal(noRests.capabilities.explicitRests, false);
});

test('microtonal intervals survive that 12-ET cannot represent', () => {
  const compiled = compileChantScriptExample('soft-chromatic-phrase');
  const doc = timedScoreFromCompiledChant(compiled, { scoreId: 'chant:soft-chromatic-phrase' });
  const moria = doc.timeline.events.filter((e) => e.kind === 'note').map((e) => e.target.pitch.moria);
  const deltas = moria.slice(1).map((m, i) => m - moria[i]).filter((d) => d !== 0);
  // A semitone is 6 moria; the soft chromatic genus moves in 8/14-moria steps.
  assert.ok(
    deltas.some((d) => Math.abs(d) % 6 !== 0),
    `at least one interval is off the 12-ET grid (deltas: ${deltas.join(', ')})`,
  );
});

test('retuned scores win via the targetMoria precedence', () => {
  const synthetic = {
    score: { title: 'Synthetic' },
    notes: [{
      type: 'note',
      degree: 'Di',
      register: 0,
      linearDegree: 4,
      moria: 42,
      effectiveMoria: 44,
      targetMoria: 40,
      startMs: 0,
      durationMs: 1000,
      durationBeats: 1,
      sourceEventIndex: 0,
      lyric: { kind: 'start', text: 'Di' },
    }],
    rests: [],
    tempoChanges: [],
    checkpoints: [],
    phraseBreaks: [],
    isonEvents: [],
    pthoraEvents: [],
    diagnostics: [],
    totalDurationMs: 1000,
  };
  const doc = timedScoreFromCompiledChant(synthetic, { scoreId: 'chant:synthetic' });
  assert.equal(doc.timeline.events[0].target.pitch.moria, 40);
  assert.equal(doc.timeline.events[0].target.hz, hzFromMoria(40));
});

test('determinism, custom refNiHz, and input validation', () => {
  const compiled = compileChantScriptExample(exampleIds[0]);
  const a = timedScoreFromCompiledChant(compiled, { scoreId: 'chant:a' });
  const b = timedScoreFromCompiledChant(compiled, { scoreId: 'chant:a' });
  assert.deepEqual(a, b);

  const higher = timedScoreFromCompiledChant(compiled, { scoreId: 'chant:a', refNiHz: 2 * DEFAULT_REF_NI_HZ });
  const firstNote = (d) => d.timeline.events.find((e) => e.kind === 'note');
  assert.ok(Math.abs(firstNote(higher).target.hz / firstNote(a).target.hz - 2) < 1e-12);
  assert.equal(firstNote(higher).target.pitch.moria, firstNote(a).target.pitch.moria);

  assert.throws(() => timedScoreFromCompiledChant(compiled, {}), /scoreId/);
  assert.throws(() => timedScoreFromCompiledChant(compiled, { scoreId: 'x', refNiHz: 0 }), /refNiHz/);
});
