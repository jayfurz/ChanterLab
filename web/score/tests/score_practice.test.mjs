import test from 'node:test';
import assert from 'node:assert/strict';

import { compileChantScriptExample } from '../examples.js';
import {
  SCORE_PRACTICE_ENABLED_DEFAULT,
  activeScoreTargetAt,
  createScorePracticeState,
  layoutScorePracticeTargets,
  scorePitchAtTime,
  scorePracticeFeatureEnabled,
} from '../score_practice.js';

test('score practice feature flag is off unless explicitly enabled', () => {
  assert.equal(scorePracticeFeatureEnabled({
    location: { search: '' },
    storage: { getItem: () => null },
  }), false);
  assert.equal(scorePracticeFeatureEnabled({
    location: { search: '?scorePractice=1' },
    storage: { getItem: () => null },
  }), true);
  assert.equal(scorePracticeFeatureEnabled({
    location: { search: '?scorePractice=0' },
    storage: { getItem: () => '1' },
  }), false);
  assert.equal(scorePracticeFeatureEnabled({
    location: { search: '' },
    storage: { getItem: key => key === 'chanterlab_score_practice_enabled' ? 'true' : null },
  }), true);
});

test('score practice state is disabled by default', () => {
  const compiled = compileChantScriptExample('symbolic-timing-steal');
  const state = createScorePracticeState(compiled);

  assert.equal(SCORE_PRACTICE_ENABLED_DEFAULT, false);
  assert.equal(state.enabled, false);
  assert.equal(state.targets.length, 2);
  assert.deepEqual(state.targets.map(target => target.durationBeats), [1.5, 0.5]);
});

test('active target lookup follows compiled note and rest windows', () => {
  const compiled = compileChantScriptExample('soft-chromatic-phrase');
  const state = createScorePracticeState(compiled);
  const rest = state.targets.find(target => target.type === 'rest');

  assert.equal(activeScoreTargetAt(state, 0).degree, 'Di');
  assert.equal(activeScoreTargetAt(state, rest.startMs + 1).type, 'rest');
  assert.equal(activeScoreTargetAt(state, state.totalDurationMs + 1), undefined);
});

test('pitch scoring reports in-tune notes and expected silence', () => {
  const compiled = compileChantScriptExample('symbolic-timing-steal');
  const state = createScorePracticeState(compiled);
  const target = activeScoreTargetAt(state, 10);

  assert.equal(scorePitchAtTime(state, { gate_open: true, raw_moria: target.moria + 2 }, 10).inTune, true);
  assert.equal(scorePitchAtTime(state, { gate_open: true, raw_moria: target.moria + 8 }, 10).inTune, false);

  const restState = createScorePracticeState({
    timeline: [{ type: 'rest', startMs: 0, durationMs: 500, durationBeats: 1, sourceEventIndex: 0 }],
    totalDurationMs: 500,
  });
  assert.equal(scorePitchAtTime(restState, { gate_open: false }, 10).expectedSilence, true);
});

test('layout maps upcoming notes to stable target bars', () => {
  const compiled = compileChantScriptExample('diatonic-ladder');
  const state = createScorePracticeState(compiled, { enabled: true });
  const rowMap = [
    { cell: { moria: 30, effective_moria: 30, enabled: true }, y: 0, h: 20 },
    { cell: { moria: 22, effective_moria: 22, enabled: true }, y: 20, h: 20 },
    { cell: { moria: 12, effective_moria: 12, enabled: true }, y: 40, h: 20 },
    { cell: { moria: 0, effective_moria: 0, enabled: true }, y: 60, h: 20 },
  ];

  const layout = layoutScorePracticeTargets(state, rowMap, {
    width: 500,
    height: 120,
    nowMs: 0,
  });

  assert.ok(layout.length >= 4);
  assert.equal(layout[0].type, 'note');
  assert.equal(layout[0].degree, 'Ni');
  assert.equal(layout[0].active, true);
  assert.equal(layout[0].x, 500 * 0.28);
  assert.ok(layout[0].width > 4);
  assert.ok(layout[0].y > 0);
});

test('layout lead-in places the first note ahead of the crosshair', () => {
  const compiled = compileChantScriptExample('diatonic-ladder');
  const state = createScorePracticeState(compiled, { enabled: true });
  const rowMap = [
    { cell: { moria: 0, effective_moria: 0, enabled: true }, y: 0, h: 20 },
  ];

  const layout = layoutScorePracticeTargets(state, rowMap, {
    width: 500,
    height: 120,
    nowMs: -1000,
  }, {
    pxPerSecond: 100,
  });

  assert.equal(activeScoreTargetAt(state, -1), undefined);
  assert.equal(layout[0].degree, 'Ni');
  assert.equal(layout[0].x, 500 * 0.28 + 100);
});
