import test from 'node:test';
import assert from 'node:assert/strict';

import { compileChantScript } from '../compiler.js';
import { hasErrorDiagnostics } from '../diagnostics.js';
import {
  retuneCompiledScoreWithGrid,
  scoreInitialPthoraDrop,
} from '../tuning_context.js';

class FakeTuningGrid {
  constructor() {
    this.refNiHz = 130.81;
    this.drops = [];
    this.cells = diatonicCells();
  }

  cellsJson() {
    return JSON.stringify(this.cells);
  }

  applySymbolDrop(json) {
    const drop = JSON.parse(json);
    this.drops.push(drop);
    if (drop.genus === 'SoftChromatic' && drop.dropDegree === 'Di' && drop.dropMoria === 42) {
      this.cells = softChromaticDiCells();
      return true;
    }
    if (drop.genus === 'Diatonic') {
      this.cells = diatonicCells();
      return true;
    }
    return false;
  }
}

test('initial martyria scale becomes a tuning-engine pthora drop', () => {
  const compiled = compileChantScript([
    'title "Initial Tuning Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale soft-chromatic phase 0',
    'note same',
    'note up 1',
  ].join('\n'));
  const grid = new FakeTuningGrid();
  const tuned = retuneCompiledScoreWithGrid(compiled, { grid, refNiHz: 144 });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.equal(grid.refNiHz, 144);
  assert.deepEqual(grid.drops[0], {
    type: 'pthora',
    genus: 'SoftChromatic',
    degree: 'Di',
    dropDegree: 'Di',
    dropMoria: 42,
    phase: 0,
  });
  assert.deepEqual(tuned.notes.map(note => note.targetMoria), [42, 50]);
  assert.equal(tuned.tuningSource, 'engine');
});

test('note-attached pthora retunes the attached note and following targets', () => {
  const compiled = compileChantScript([
    'title "Attached Pthora Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale diatonic',
    'note same pthora soft-chromatic phase 0',
    'note up 1',
  ].join('\n'));
  const grid = new FakeTuningGrid();
  const tuned = retuneCompiledScoreWithGrid(compiled, { grid });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.equal(grid.drops.length, 2);
  assert.equal(grid.drops[1].dropMoria, 42);
  assert.equal(tuned.timeline[1].type, 'pthora');
  assert.deepEqual(tuned.notes.map(note => note.targetMoria), [42, 50]);
});

test('score-local accidentals move only the retuned target note', () => {
  const compiled = compileChantScript([
    'title "Retuned Accidental Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale soft-chromatic phase 0',
    'note same',
    'note up 1 flat 6',
    'note down 1',
  ].join('\n'));
  const tuned = retuneCompiledScoreWithGrid(compiled, { grid: new FakeTuningGrid() });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.deepEqual(tuned.notes.map(note => note.targetMoria), [42, 44, 42]);
});

test('ison events are retuned through the active tuning grid', () => {
  const compiled = compileChantScript([
    'title "Retuned Ison Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale soft-chromatic phase 0',
    'drone Di',
    'note same',
    'ison Ke',
    'note up 1',
  ].join('\n'));
  const tuned = retuneCompiledScoreWithGrid(compiled, { grid: new FakeTuningGrid() });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.deepEqual(tuned.isonEvents.map(event => [event.degree, event.targetMoria, event.tuning.cellMoria]), [
    ['Di', 42, 42],
    ['Ke', 50, 50],
  ]);
  assert.equal(tuned.timeline.filter(event => event.type === 'ison')[1].targetMoria, 50);
});

test('ison retuning defaults to the central degree register when context is missing', () => {
  const tuned = retuneCompiledScoreWithGrid({
    diagnostics: [],
    timeline: [{ type: 'ison', atMs: 0, degree: 'Di', sourceEventIndex: 0 }],
    isonEvents: [{ type: 'ison', atMs: 0, degree: 'Di', sourceEventIndex: 0 }],
    totalDurationMs: 0,
  }, { grid: new FakeTuningGrid() });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.equal(tuned.isonEvents[0].targetMoria, 42);
  assert.equal(tuned.isonEvents[0].tuning.cellMoria, 42);
});

test('note-attached ison changes retune after note-attached pthora is applied', () => {
  const compiled = compileChantScript([
    'title "Attached Ison Retune Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale diatonic',
    'note same pthora soft-chromatic phase 0 drone Ke',
    'note up 1',
  ].join('\n'));
  const tuned = retuneCompiledScoreWithGrid(compiled, { grid: new FakeTuningGrid() });

  assert.equal(hasErrorDiagnostics(tuned.diagnostics), false);
  assert.equal(tuned.isonEvents[0].degree, 'Ke');
  assert.equal(tuned.isonEvents[0].targetMoria, 50);
});

test('initial tuning helper anchors scale at martyria degree instead of first note', () => {
  const compiled = compileChantScript([
    'title "Initial Anchor Fixture"',
    'tempo bpm 120',
    'start Di',
    'scale soft-chromatic phase 0',
    'note down 1',
  ].join('\n'));

  assert.deepEqual(scoreInitialPthoraDrop(compiled.score), {
    type: 'pthora',
    scale: 'soft-chromatic',
    genus: 'SoftChromatic',
    degree: 'Di',
    dropDegree: 'Di',
    dropMoria: 42,
    atMs: 0,
    sourceEventIndex: -1,
    phase: 0,
  });
});

function diatonicCells() {
  return [
    cell('Di', -30),
    cell('Ni', 0),
    cell('Pa', 12),
    cell('Vou', 22),
    cell('Ga', 30),
    cell('Di', 42),
    cell('Ke', 54),
    cell('Zo', 64),
  ];
}

function softChromaticDiCells() {
  return [
    cell('Di', -30),
    cell('Ni', 0),
    cell('Pa', 12),
    cell('Vou', 22),
    cell('Ga', 34),
    cell('Di', 42),
    cell('Ke', 50),
    cell('Zo', 64),
  ];
}

function cell(degree, moria) {
  return {
    degree,
    moria,
    effective_moria: moria,
    accidental: 0,
    enabled: true,
  };
}
