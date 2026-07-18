import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONTRACT_NAME,
  CONTRACT_VERSION,
  CAPABILITY_KEYS,
  DEFAULT_REF_NI_HZ,
  hzFromMidi,
  hzFromMoria,
  validateTimedScore,
} from '../index.js';

function allCapabilities(overrides = {}) {
  const caps = {};
  for (const key of CAPABILITY_KEYS) caps[key] = false;
  return { ...caps, ...overrides };
}

function makeMinimalDoc() {
  return {
    contract: CONTRACT_NAME,
    contractVersion: CONTRACT_VERSION,
    score: { id: 'test:minimal', title: 'Minimal', notation: 'musicxml-satb', sourceRef: null },
    capabilities: allCapabilities(),
    parts: [{ id: 'p', name: 'Part', role: 'melody', selectable: true }],
    timeline: {
      units: 'seconds',
      totalSec: 1,
      events: [
        {
          id: 'e0',
          partId: 'p',
          kind: 'note',
          startSec: 0,
          endSec: 1,
          target: { hz: 440, pitch: { type: 'midi', midi: 69, a4Hz: 440 } },
          lyric: null,
          anchors: {},
        },
      ],
      tempo: [{ atSec: 0, bpm: 120 }],
      sections: [],
      ison: [],
      tuningChanges: [],
      checkpoints: [],
      phrases: [],
    },
    diagnostics: [],
  };
}

test('pitch helpers match the engines\' single conversion formulas', () => {
  assert.equal(hzFromMidi(69), 440); // transport.js midiToFreq, A4=440
  assert.equal(hzFromMidi(57), 220);
  assert.equal(hzFromMoria(0), DEFAULT_REF_NI_HZ); // grid.rs moria_to_hz, Reference Ni
  assert.equal(hzFromMoria(72, 100), 200); // 72 moria = one octave
  assert.ok(Math.abs(hzFromMoria(12, 100) - 100 * Math.pow(2, 12 / 72)) < 1e-12);
});

test('a minimal well-formed document validates', () => {
  const result = validateTimedScore(makeMinimalDoc());
  assert.deepEqual(result.errors, []);
  assert.equal(result.ok, true);
});

test('contract identity and major version are enforced', () => {
  const wrongName = makeMinimalDoc();
  wrongName.contract = 'something-else';
  assert.equal(validateTimedScore(wrongName).ok, false);

  const wrongMajor = makeMinimalDoc();
  wrongMajor.contractVersion = '2.0.0';
  assert.equal(validateTimedScore(wrongMajor).ok, false);

  const laterMinor = makeMinimalDoc();
  laterMinor.contractVersion = '1.9.3';
  assert.equal(validateTimedScore(laterMinor).ok, true);
});

test('event integrity: duplicate ids, bad times, unknown parts, order', () => {
  const dupIds = makeMinimalDoc();
  dupIds.timeline.events.push({ ...dupIds.timeline.events[0] });
  assert.match(validateTimedScore(dupIds).errors.join('\n'), /duplicate event id/);

  const badEnd = makeMinimalDoc();
  badEnd.timeline.events[0].endSec = -0.5;
  assert.match(validateTimedScore(badEnd).errors.join('\n'), /endSec/);

  const badPart = makeMinimalDoc();
  badPart.timeline.events[0].partId = 'nope';
  assert.match(validateTimedScore(badPart).errors.join('\n'), /unknown part/);

  const outOfOrder = makeMinimalDoc();
  outOfOrder.timeline.events.push({
    ...outOfOrder.timeline.events[0],
    id: 'e1',
    startSec: -0,
    endSec: 0.5,
  });
  outOfOrder.timeline.events[0].startSec = 0.75;
  outOfOrder.timeline.events[0].endSec = 1;
  assert.match(validateTimedScore(outOfOrder).errors.join('\n'), /non-decreasing/);
});

test('pitch union is checked', () => {
  const badType = makeMinimalDoc();
  badType.timeline.events[0].target.pitch = { type: 'solfege', syllable: 'la' };
  assert.match(validateTimedScore(badType).errors.join('\n'), /unknown pitch type/);

  const badMoria = makeMinimalDoc();
  badMoria.capabilities = allCapabilities({ microtonal: true });
  badMoria.timeline.events[0].target.pitch = { type: 'moria', moria: Number.NaN, refNiHz: DEFAULT_REF_NI_HZ };
  assert.match(validateTimedScore(badMoria).errors.join('\n'), /finite `moria`/);

  const restWithTarget = makeMinimalDoc();
  restWithTarget.timeline.events[0].kind = 'rest';
  assert.match(validateTimedScore(restWithTarget).errors.join('\n'), /rests must have a null target/);
});

test('capability flags must be explicit and coherent with the data', () => {
  const missingKey = makeMinimalDoc();
  delete missingKey.capabilities.ison;
  assert.match(validateTimedScore(missingKey).errors.join('\n'), /capabilities\.ison: missing/);

  const unknownKey = makeMinimalDoc();
  unknownKey.capabilities.telepathy = true;
  assert.match(validateTimedScore(unknownKey).errors.join('\n'), /unknown capability key/);

  const hiddenMoria = makeMinimalDoc();
  hiddenMoria.timeline.events[0].target.pitch = { type: 'moria', moria: 42, refNiHz: DEFAULT_REF_NI_HZ };
  assert.match(validateTimedScore(hiddenMoria).errors.join('\n'), /microtonal.*moria-typed/);

  const hiddenIson = makeMinimalDoc();
  hiddenIson.timeline.ison = [{ atSec: 0, hz: 100 }];
  assert.match(validateTimedScore(hiddenIson).errors.join('\n'), /ison.*populated/);
});
