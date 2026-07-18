import test from 'node:test';
import assert from 'node:assert/strict';

import { timedScoreFromParsedMusicXML, validateTimedScore, hzFromMidi } from '../index.js';
import { WESTERN_PARSED_FIXTURE } from './fixtures/western_parsed.mjs';

const EPS = 1e-6;

// Replicates the app's shared window + beat->seconds math exactly as the
// current consumers compute it (voices.js buildScopeLane, scoring-ui.js
// buildScoreTargets, transport.js scheduleAll), as the independent expected
// value for comparing the adapter's timeline against current playback.
function expectedTimeline(parsed, { bpm, transposeSemitones = 0, fromMeasure = 1, toMeasure }) {
  const to = toMeasure ?? parsed.measureCount;
  let winStart = Infinity;
  let winEnd = 0;
  parsed.parts.forEach((p) => p.notes.forEach((n) => {
    if (n.measure >= fromMeasure && n.measure <= to) {
      winStart = Math.min(winStart, n.startBeat);
      winEnd = Math.max(winEnd, n.startBeat + n.durBeat);
    }
  }));
  if (!Number.isFinite(winStart)) { winStart = 0; winEnd = 0; }
  const spb = 60 / bpm;
  const perPart = parsed.parts.map((p) => p.notes
    .filter((n) => n.startBeat >= winStart - EPS && n.startBeat < winEnd - EPS)
    .map((n) => ({
      start: (n.startBeat - winStart) * spb,
      end: (n.startBeat - winStart + n.durBeat) * spb,
      midi: n.midi + transposeSemitones,
      freq: 440 * Math.pow(2, (n.midi + transposeSemitones - 69) / 12), // transport.js midiToFreq
    })));
  return { perPart, windowSec: (winEnd - winStart) * spb };
}

function docFor(options = {}) {
  return timedScoreFromParsedMusicXML(WESTERN_PARSED_FIXTURE, {
    scoreId: 'test:western-fixture',
    bpm: 120,
    ...options,
  });
}

test('full-window adapter output validates and matches current playback math', () => {
  const doc = docFor();
  const result = validateTimedScore(doc);
  assert.deepEqual(result.errors, []);

  const expected = expectedTimeline(WESTERN_PARSED_FIXTURE, { bpm: 120 });
  assert.equal(doc.timeline.totalSec, expected.windowSec);

  WESTERN_PARSED_FIXTURE.parts.forEach((part, pi) => {
    const events = doc.timeline.events.filter((e) => e.partId === part.voiceKey);
    assert.equal(events.length, expected.perPart[pi].length);
    events.forEach((e, i) => {
      const want = expected.perPart[pi][i];
      assert.equal(e.startSec, want.start);
      assert.equal(e.endSec, want.end);
      assert.equal(e.target.pitch.midi, want.midi);
      assert.equal(e.target.hz, want.freq);
    });
  });
});

test('model semantics survive: merged tie is one event, rest gap has no event', () => {
  const doc = docFor();
  // The soprano's tie-merged C5 (startBeat 4, durBeat 3) is a single 1.5 s event.
  const tied = doc.timeline.events.find((e) => e.id === 'mx:S:3');
  assert.equal(tied.startSec, 2);
  assert.equal(tied.endSec, 3.5);
  // The alto's measure-3 gap (beats 8..9) produces nothing between 4 s and 4.5 s.
  const altoAtGap = doc.timeline.events.filter(
    (e) => e.partId === 'A' && e.startSec >= 4 - EPS && e.startSec < 4.5 - EPS,
  );
  assert.deepEqual(altoAtGap, []);
  assert.equal(doc.capabilities.explicitRests, false);
});

test('transpose shifts hz and midi but preserves the notated pitch', () => {
  const doc = docFor({ transposeSemitones: 2 });
  const first = doc.timeline.events.find((e) => e.id === 'mx:S:0');
  assert.equal(first.target.pitch.midi, 69);
  assert.equal(first.anchors.notatedMidi, 67);
  assert.equal(first.target.hz, hzFromMidi(69));
  const untransposed = docFor().timeline.events.find((e) => e.id === 'mx:S:0');
  assert.ok(Math.abs(first.target.hz / untransposed.target.hz - Math.pow(2, 2 / 12)) < 1e-12);
});

test('event ids are stable across loop windows', () => {
  const full = docFor();
  const loop = docFor({ fromMeasure: 2, toMeasure: 3 });
  const fullIds = new Set(full.timeline.events.map((e) => e.id));
  for (const e of loop.timeline.events) {
    assert.ok(fullIds.has(e.id), `loop event ${e.id} keeps its full-window id`);
  }
  // Same note, same id, window-relative time: the tied C5 starts the loop window.
  const tied = loop.timeline.events.find((e) => e.id === 'mx:S:3');
  assert.equal(tied.startSec, 0);
  assert.equal(validateTimedScore(loop).ok, true);
});

test('sections stay measure-anchored and gate the capability', () => {
  const bare = docFor();
  assert.equal(bare.capabilities.sections, false);
  assert.deepEqual(bare.timeline.sections, []);

  const doc = docFor({ sections: [{ title: 'Verse', measure: 1 }, { title: 'Refrain', measure: 2 }] });
  assert.equal(doc.capabilities.sections, true);
  assert.deepEqual(doc.timeline.sections.map((s) => s.anchors), [
    { fromMeasure: 1, toMeasure: 1 },
    { fromMeasure: 2, toMeasure: 3 },
  ]);
});

test('determinism and input validation', () => {
  assert.deepEqual(docFor(), docFor());
  assert.throws(() => timedScoreFromParsedMusicXML(WESTERN_PARSED_FIXTURE, { scoreId: 'x' }), /bpm/);
  assert.throws(() => timedScoreFromParsedMusicXML(WESTERN_PARSED_FIXTURE, { bpm: 120 }), /scoreId/);
  const caps = docFor().capabilities;
  assert.equal(caps.multiPart, true);
  assert.equal(caps.lyrics, true);
  assert.equal(caps.microtonal, false);
});
