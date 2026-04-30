import test from 'node:test';
import assert from 'node:assert/strict';

import { compileChantScriptExample } from '../examples.js';
import {
  SCORE_PRACTICE_ENABLED_DEFAULT,
  ScorePracticePrototype,
  activeScoreIsonAt,
  activeScoreTargetAt,
  activeScoreTuningAt,
  createScorePracticeState,
  layoutScorePracticeMarkers,
  layoutScorePracticeTargets,
  scorePitchAtTime,
  scorePracticeExplicitlyDisabled,
  scorePracticeIsonControlState,
  scorePracticeIsonMoria,
  scorePracticeLeadInScoreMs,
} from '../score_practice.js';

test('score practice is default-on with an explicit URL opt-out', () => {
  assert.equal(scorePracticeExplicitlyDisabled({
    location: { search: '' },
  }), false);
  assert.equal(scorePracticeExplicitlyDisabled({
    location: { search: '?scorePractice=1' },
  }), false);
  assert.equal(scorePracticeExplicitlyDisabled({
    location: { search: '?scorePractice=0' },
  }), true);
  assert.equal(scorePracticeExplicitlyDisabled({
    location: { search: '?score-practice=off' },
  }), true);
});

test('score practice state is enabled by default', () => {
  const compiled = compileChantScriptExample('symbolic-timing-steal');
  const state = createScorePracticeState(compiled);

  assert.equal(SCORE_PRACTICE_ENABLED_DEFAULT, true);
  assert.equal(state.enabled, true);
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

test('score practice targets prefer engine retuned moria when present', () => {
  const state = createScorePracticeState({
    timeline: [{
      type: 'note',
      degree: 'Ke',
      moria: 54,
      effectiveMoria: 54,
      targetMoria: 50,
      engineMoria: 50,
      startMs: 0,
      durationMs: 500,
      durationBeats: 1,
      sourceEventIndex: 0,
    }],
    totalDurationMs: 500,
  });

  assert.equal(state.targets[0].moria, 50);
  assert.equal(state.targets[0].symbolicMoria, 54);
  assert.equal(scorePitchAtTime(state, { gate_open: true, raw_moria: 50 }, 10).inTune, true);
});

test('layout exposes pthora, ison, and martyria markers for score practice rendering', () => {
  const state = createScorePracticeState({
    timeline: [],
    pthoraEvents: [{ type: 'pthora', atMs: 500, scale: 'soft-chromatic', degree: 'Di' }],
    isonEvents: [{ type: 'ison', atMs: 750, degree: 'Di', targetMoria: 42 }],
    checkpoints: [{ type: 'martyria', atMs: 1000, degree: 'Ke' }],
    totalDurationMs: 1500,
  });

  const markers = layoutScorePracticeMarkers(state, {
    width: 500,
    height: 120,
    nowMs: 0,
  }, {
    pxPerSecond: 100,
  });

  assert.deepEqual(markers.map(marker => marker.markerType), ['pthora', 'ison', 'martyria']);
  assert.deepEqual(markers.map(marker => marker.x), [
    500 * 0.28 + 50,
    500 * 0.28 + 75,
    500 * 0.28 + 100,
  ]);
});

test('score practice includes explicit initial non-diatonic pthora marker', () => {
  const compiled = compileChantScriptExample('soft-chromatic-phrase');
  const state = createScorePracticeState(compiled);

  assert.equal(state.pthoraEvents[0].scale, 'soft-chromatic');
  assert.equal(state.pthoraEvents[0].degree, 'Di');
  assert.equal(state.pthoraEvents[0].dropMoria, 42);
});

test('active score ison persists until the next score ison event', () => {
  const state = createScorePracticeState({
    timeline: [],
    isonEvents: [
      { type: 'ison', atMs: 1000, degree: 'Pa', targetMoria: 12 },
      { type: 'ison', atMs: 0, degree: 'Ni', targetMoria: 0 },
      { type: 'ison', atMs: 2000, degree: 'Vou', targetMoria: 22 },
    ],
    totalDurationMs: 3000,
  });

  assert.equal(activeScoreIsonAt(state, -500).degree, 'Ni');
  assert.equal(activeScoreIsonAt(state, 1500).degree, 'Pa');
  assert.equal(activeScoreIsonAt(state, 2500).degree, 'Vou');
});

test('score practice resolves explicit ison octaves before central retune fallbacks', () => {
  const lower = scorePracticeIsonControlState({
    type: 'ison',
    degree: 'Di',
    register: -1,
    moria: -30,
    targetMoria: 42,
    engineMoria: 42,
    tuning: { cellMoria: 42 },
  });
  assert.deepEqual({
    degree: lower.degree,
    octave: lower.octave,
    cellId: lower.cellId,
    displayMoria: lower.displayMoria,
  }, {
    degree: 'Di',
    octave: -1,
    cellId: -30,
    displayMoria: -30,
  });
  assert.equal(scorePracticeIsonMoria(lower.source), -30);

  const retunedLower = scorePracticeIsonControlState({
    type: 'ison',
    degree: 'Di',
    register: -1,
    moria: -30,
    targetMoria: -32,
    engineMoria: -32,
    tuning: { cellMoria: -32 },
  });
  assert.equal(retunedLower.cellId, -32);
  assert.equal(retunedLower.displayMoria, -32);

  const retunedCentral = scorePracticeIsonControlState({
    type: 'ison',
    degree: 'Ke',
    register: 0,
    moria: 54,
    targetMoria: 50,
    engineMoria: 50,
    tuning: { cellMoria: 50 },
  });
  assert.equal(retunedCentral.octave, 0);
  assert.equal(retunedCentral.cellId, 50);
  assert.equal(retunedCentral.displayMoria, 50);

  assert.equal(scorePracticeIsonMoria({
    type: 'ison',
    degree: 'Di',
    register: 0,
    moria: 42,
    targetMoria: 42,
  }), 42);
});

test('plagal-four score practice callback reaches the late lower-octave Di ison', () => {
  const changes = [];
  const practice = new ScorePracticePrototype(null, {
    enabled: true,
    onIsonChange: ison => changes.push(scorePracticeIsonControlState(ison)),
  });
  practice.setCompiledScore(compileChantScriptExample('plagal-four-soft-chromatic'));
  practice.seek(11000);

  const lowerDi = changes.at(-1);
  assert.equal(lowerDi.degree, 'Di');
  assert.equal(lowerDi.octave, -1);
  assert.equal(lowerDi.cellId, -30);
  assert.equal(lowerDi.displayMoria, -30);
});

test('score practice notifies ison changes on load and seek', () => {
  const changes = [];
  const practice = new ScorePracticePrototype(null, {
    enabled: true,
    onIsonChange: ison => changes.push(ison?.degree ?? null),
  });
  practice.setCompiledScore({
    timeline: [],
    isonEvents: [
      { type: 'ison', atMs: 0, degree: 'Ni', targetMoria: 0 },
      { type: 'ison', atMs: 1000, degree: 'Pa', targetMoria: 12 },
    ],
    totalDurationMs: 2000,
  });
  practice.seek(1200);

  assert.deepEqual(changes, ['Ni', 'Pa']);
});

test('disabling score practice clears active score ison even when playback is stopped', () => {
  const changes = [];
  const practice = new ScorePracticePrototype(null, {
    enabled: true,
    onIsonChange: ison => changes.push(ison?.degree ?? null),
  });
  practice.setCompiledScore({
    timeline: [],
    isonEvents: [
      { type: 'ison', atMs: 0, degree: 'Ni', targetMoria: 0 },
    ],
    totalDurationMs: 2000,
  });

  practice.setEnabled(false);

  assert.deepEqual(changes, ['Ni', null]);
});

test('active tuning state includes elapsed pthora events and active accidentals', () => {
  const state = createScorePracticeState({
    timeline: [{
      type: 'note',
      degree: 'Zo',
      moria: -8,
      effectiveMoria: -6,
      targetMoria: -6,
      engineMoria: -8,
      accidental: { moria: 2 },
      tuning: { cellMoria: -8 },
      startMs: 1000,
      durationMs: 500,
      durationBeats: 1,
      sourceEventIndex: 2,
    }],
    pthoraEvents: [
      { type: 'pthora', atMs: 500, genus: 'SoftChromatic', degree: 'Di', dropMoria: 42, sourceEventIndex: 1 },
      { type: 'pthora', atMs: 1600, genus: 'Diatonic', degree: 'Di', dropMoria: 42, sourceEventIndex: 3 },
    ],
    totalDurationMs: 2000,
  });

  assert.deepEqual(activeScoreTuningAt(state, 1200), {
    pthoraEvents: [
      { type: 'pthora', atMs: 500, genus: 'SoftChromatic', degree: 'Di', dropMoria: 42, sourceEventIndex: 1 },
    ],
    accidental: {
      degree: 'Zo',
      cellMoria: -8,
      accidentalMoria: 2,
      sourceEventIndex: 2,
    },
  });
  assert.equal(activeScoreTuningAt(state, 1700).accidental, undefined);
  assert.equal(activeScoreTuningAt(state, 1700).pthoraEvents.length, 2);
});

test('running score practice uses updated playback rate on the next frame', () => {
  const originalRaf = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  const originalPerformance = globalThis.performance;
  const callbacks = [];
  let now = 0;
  globalThis.requestAnimationFrame = callback => {
    callbacks.push(callback);
    return callbacks.length;
  };
  globalThis.cancelAnimationFrame = () => {};
  Object.defineProperty(globalThis, 'performance', {
    configurable: true,
    value: { now: () => now },
  });

  try {
    const practice = new ScorePracticePrototype(null, {
      enabled: true,
      leadInMs: 0,
      playbackRate: 1,
    });
    practice.setCompiledScore({
      timeline: [],
      totalDurationMs: 10000,
    });
    practice.start(0);
    callbacks.shift()(100);
    assert.equal(practice.nowMs, 100);

    now = 100;
    practice.setTiming({ playbackRate: 2 });
    callbacks.shift()(200);
    assert.equal(practice.nowMs, 300);
    practice.stop();
  } finally {
    if (originalRaf) globalThis.requestAnimationFrame = originalRaf;
    else delete globalThis.requestAnimationFrame;
    if (originalCancel) globalThis.cancelAnimationFrame = originalCancel;
    else delete globalThis.cancelAnimationFrame;
    Object.defineProperty(globalThis, 'performance', {
      configurable: true,
      value: originalPerformance,
    });
  }
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

test('layout keeps visual scroll fixed while playback rate changes target length', () => {
  const state = createScorePracticeState({
    timeline: [{
      type: 'note',
      degree: 'Ni',
      moria: 0,
      effectiveMoria: 0,
      startMs: 0,
      durationMs: 1000,
      durationBeats: 1,
      sourceEventIndex: 0,
    }],
    totalDurationMs: 1000,
  }, { enabled: true });
  const rowMap = [
    { cell: { moria: 0, effective_moria: 0, enabled: true }, y: 0, h: 20 },
  ];

  const fastOptions = {
    leadInMs: 3000,
    pxPerSecond: 100,
    playbackRate: 2,
  };
  const slowOptions = {
    leadInMs: 3000,
    pxPerSecond: 100,
    playbackRate: 0.5,
  };
  const fastLeadIn = scorePracticeLeadInScoreMs({ width: 1000 }, fastOptions);
  const slowLeadIn = scorePracticeLeadInScoreMs({ width: 1000 }, slowOptions);

  const fast = layoutScorePracticeTargets(state, rowMap, {
    width: 1000,
    height: 120,
    nowMs: -fastLeadIn,
  }, fastOptions);
  const slow = layoutScorePracticeTargets(state, rowMap, {
    width: 1000,
    height: 120,
    nowMs: -slowLeadIn,
  }, slowOptions);

  assert.equal(fast[0].x, 1000 * 0.28 + 300);
  assert.equal(fast[0].width, 50);
  assert.equal(slow[0].x, 1000 * 0.28 + 300);
  assert.equal(slow[0].width, 200);
});

test('fixed lead-in places the first note ahead of the crosshair', () => {
  const compiled = compileChantScriptExample('diatonic-ladder');
  const state = createScorePracticeState(compiled, { enabled: true });
  const rowMap = [
    { cell: { moria: 0, effective_moria: 0, enabled: true }, y: 0, h: 20 },
  ];
  const options = {
    leadInMs: 3000,
    playbackRate: 0.5,
    pxPerSecond: 100,
    crosshairX: 0.28,
  };
  const leadInScoreMs = scorePracticeLeadInScoreMs({ width: 500 }, options);

  const layout = layoutScorePracticeTargets(state, rowMap, {
    width: 500,
    height: 120,
    nowMs: -leadInScoreMs,
  }, options);

  assert.equal(leadInScoreMs, 1500);
  assert.equal(layout[0].degree, 'Ni');
  assert.equal(layout[0].x, 500 * 0.28 + 300);
});
