// RAGA-01 preset regression (docs/plans/80-scales-and-raga/82-raga-presets-sargam.md):
// the shipped raga intervals must match the plan's approved table exactly and
// satisfy the closed-genus contract that JsTuningGrid.applyCustomGenus enforces.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { RAGA_PRESETS } from '../raga_presets.js';

const APPROVED = {
  'Bilawal / Shankarabharanam': [12, 12, 6, 12, 12, 12, 6],
  'Yaman / Kalyani': [12, 12, 12, 6, 12, 12, 6],
  'Kafi / Kharaharapriya': [12, 6, 12, 12, 12, 6, 12],
  'Bhairavi / Hanumatodi': [6, 12, 12, 12, 6, 12, 12],
  'Bhairav / Mayamalavagowla': [6, 18, 6, 12, 6, 18, 6],
  'Todi / Shubhapantuvarali': [6, 12, 18, 6, 6, 18, 6],
};

test('every approved raga ships, with its approved intervals, exactly once', () => {
  assert.deepEqual(
    Object.fromEntries(RAGA_PRESETS.map(p => [p.name, p.intervals])),
    APPROVED,
  );
  assert.equal(RAGA_PRESETS.length, Object.keys(APPROVED).length);
});

test('presets satisfy the closed-genus contract (7 positive steps, sum 72)', () => {
  for (const preset of RAGA_PRESETS) {
    assert.equal(preset.intervals.length, 7, preset.name);
    assert.ok(preset.intervals.every(step => Number.isInteger(step) && step > 0), preset.name);
    assert.equal(preset.intervals.reduce((a, b) => a + b, 0), 72, preset.name);
  }
});

test('presets carry the fields selectPreset needs for the Custom path', () => {
  for (const preset of RAGA_PRESETS) {
    assert.equal(preset.genus, 'Custom', preset.name);
    assert.equal(preset.degree, 'Ni', preset.name);
    assert.equal(preset.canonicalRoot, 'Ni', preset.name);
    assert.equal(preset.labels, 'sargam', preset.name);
    assert.ok(preset.label.length > 0 && preset.label.length <= 10, preset.name);
  }
});
