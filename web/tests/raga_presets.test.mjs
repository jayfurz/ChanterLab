// RAGA-01 preset regression (docs/plans/80-scales-and-raga/82-raga-presets-sargam.md):
// the shipped raga intervals must match the plan's approved table exactly and
// satisfy the closed-genus contract that JsTuningGrid.applyCustomGenus
// enforces. Hindustani naming per owner decision 2026-07-11.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { RAGA_PRESETS } from '../raga_presets.js';

const APPROVED = {
  Bilawal: [12, 12, 6, 12, 12, 12, 6],
  Yaman: [12, 12, 12, 6, 12, 12, 6],
  Kafi: [12, 6, 12, 12, 12, 6, 12],
  Bhairavi: [6, 12, 12, 12, 6, 12, 12],
  Bhairav: [6, 18, 6, 12, 6, 18, 6],
  Todi: [6, 12, 18, 6, 6, 18, 6],
};

test('every approved raga ships, with its approved intervals, exactly once', () => {
  assert.deepEqual(
    Object.fromEntries(RAGA_PRESETS.map(p => [p.label, p.intervals])),
    APPROVED,
  );
  assert.equal(RAGA_PRESETS.length, Object.keys(APPROVED).length);
});

test('presets satisfy the closed-genus contract (7 positive steps, sum 72)', () => {
  for (const preset of RAGA_PRESETS) {
    assert.equal(preset.intervals.length, 7, preset.label);
    assert.ok(preset.intervals.every(step => Number.isInteger(step) && step > 0), preset.label);
    assert.equal(preset.intervals.reduce((a, b) => a + b, 0), 72, preset.label);
  }
});

test('presets carry the fields selectPreset needs for the Custom path', () => {
  for (const preset of RAGA_PRESETS) {
    assert.equal(preset.genus, 'Custom', preset.label);
    assert.equal(preset.degree, 'Ni', preset.label);
    assert.equal(preset.canonicalRoot, 'Ni', preset.label);
    assert.equal(preset.name, `Raga ${preset.label}`, preset.label);
  }
});
