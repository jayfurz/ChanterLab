import test from 'node:test';
import assert from 'node:assert/strict';

import {
  compileGlyphGroups,
  compileSbmuflGlyphText,
  compileUnicodeByzantineText,
  inferPthoraPhase,
  semanticTokensFromGlyphs,
  semanticTokenGroupsFromGlyphText,
  sourceTokensFromGlyphText,
} from '../glyph_import.js';
import { hasErrorDiagnostics } from '../diagnostics.js';

test('glyph import classifies minimal Unicode and SBMuFL source tokens', () => {
  const diagnostics = [];
  const tokens = semanticTokensFromGlyphs([
    'ison',
    { codepoint: 'U+E001' },
    '\u{1D051}',
    'digorgon',
  ], { diagnostics });

  assert.equal(hasErrorDiagnostics(diagnostics), false);
  assert.deepEqual(tokens.map(token => token.kind), ['quantity', 'quantity', 'quantity', 'temporal']);
  assert.deepEqual(tokens.map(token => token.value.movement?.direction ?? token.value.sign), [
    'same',
    'up',
    'down',
    'digorgon',
  ]);
  assert.equal(tokens[0].source[0].alternateCodepoint, 'U+1D046');
  assert.equal(tokens[0].source[0].source, 'glyph-name');
  assert.equal(tokens[1].source[0].source, 'sbmufl-pua');
  assert.equal(tokens[2].source[0].source, 'unicode-byzantine');
  assert.equal(tokens[2].source[0].glyphName, 'apostrofos');
});

test('glyph groups compile through the chant score compiler', () => {
  const compiled = compileGlyphGroups([
    ['ison'],
    ['oligon'],
    ['oligon'],
    ['apostrofos', 'gorgonAbove'],
    ['leimma2'],
  ], {
    title: 'Glyph Import Compile Fixture',
    startDegree: 'Ni',
    bpm: 120,
  });

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.degree), ['Ni', 'Pa', 'Vou', 'Pa']);
  assert.deepEqual(compiled.notes.map(note => note.display.preferredGlyphName), [
    'ison',
    'oligon',
    'oligon',
    'apostrofos',
  ]);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1, 1, 0.5, 0.5]);
  assert.equal(compiled.rests.length, 1);
  assert.equal(compiled.rests[0].durationBeats, 2);
  assert.equal(compiled.imported.semanticGroups[0][0].source[0].source, 'glyph-name');
});

test('glyph import infers chromatic pthora phase from attached note placement', () => {
  assert.equal(inferPthoraPhase({ scale: 'soft-chromatic' }, 'Di'), 0);
  assert.equal(inferPthoraPhase({ scale: 'soft-chromatic' }, 'Ke'), 1);
  assert.equal(inferPthoraPhase({ scale: 'hard-chromatic' }, 'Pa'), 0);
  assert.equal(inferPthoraPhase({ scale: 'hard-chromatic' }, 'Di'), 3);

  const compiled = compileGlyphGroups([
    ['ison', 'fthoraSoftChromaticDiAbove'],
    ['oligon'],
  ], {
    title: 'Glyph Pthora Fixture',
    startDegree: 'Di',
    bpm: 120,
  });

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.equal(compiled.pthoraEvents.length, 1);
  assert.equal(compiled.pthoraEvents[0].scale, 'soft-chromatic');
  assert.equal(compiled.pthoraEvents[0].degree, 'Di');
  assert.equal(compiled.pthoraEvents[0].phase, 0);
  assert.deepEqual(compiled.notes.map(note => note.moria), [42, 50]);
});

test('glyph import reports unknown and ambiguous groups without guessing', () => {
  const unknown = compileGlyphGroups([
    ['notAGlyph'],
  ]);
  assert.equal(hasErrorDiagnostics(unknown.diagnostics), true);
  assert.equal(unknown.diagnostics.some(diagnostic => diagnostic.code === 'glyph-import-unknown'), true);

  const ambiguous = compileGlyphGroups([
    ['ison', 'oligon'],
  ]);
  assert.equal(hasErrorDiagnostics(ambiguous.diagnostics), true);
  assert.equal(ambiguous.diagnostics.some(diagnostic => diagnostic.code === 'glyph-import-group-ambiguous'), true);
});

test('SBMuFL glyph-name text adapter groups modifiers with nearest quantity', () => {
  const compiled = compileSbmuflGlyphText([
    'ison',
    'oligon',
    'oligon',
    'apostrofos gorgonAbove',
    'leimma2',
  ].join(' '), {
    title: 'SBMuFL Name Text Fixture',
    startDegree: 'Ni',
    bpm: 120,
  });

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.deepEqual(compiled.notes.map(note => note.degree), ['Ni', 'Pa', 'Vou', 'Pa']);
  assert.deepEqual(compiled.notes.map(note => note.durationBeats), [1, 1, 0.5, 0.5]);
  assert.equal(compiled.rests[0].durationBeats, 2);
  assert.equal(compiled.imported.semanticGroups[0][0].source[0].source, 'sbmufl-pua');
});

test('SBMuFL PUA and Unicode Byzantine text adapters compile equivalent melody', () => {
  const sbmufl = compileSbmuflGlyphText('\uE000\uE001\uE001\uE021\uE0F0\uE0E1', {
    title: 'SBMuFL PUA Fixture',
    startDegree: 'Ni',
    bpm: 120,
  });
  const unicode = compileUnicodeByzantineText('\u{1D046}\u{1D047}\u{1D047}\u{1D051}\u{1D08F}\u{1D08B}', {
    title: 'Unicode Byzantine Fixture',
    startDegree: 'Ni',
    bpm: 120,
  });

  assert.equal(hasErrorDiagnostics(sbmufl.diagnostics), false);
  assert.equal(hasErrorDiagnostics(unicode.diagnostics), false);
  assert.deepEqual(unicode.notes.map(note => note.degree), sbmufl.notes.map(note => note.degree));
  assert.deepEqual(unicode.notes.map(note => note.durationBeats), sbmufl.notes.map(note => note.durationBeats));
  assert.equal(sbmufl.imported.semanticGroups[0][0].source[0].source, 'sbmufl-pua');
  assert.equal(unicode.imported.semanticGroups[0][0].source[0].source, 'unicode-byzantine');
});

test('glyph text adapter attaches prefix pthora to following quantity', () => {
  const groups = semanticTokenGroupsFromGlyphText('fthoraSoftChromaticDiAbove ison oligon');
  assert.deepEqual(groups.map(group => group.map(token => token.kind)), [
    ['pthora', 'quantity'],
    ['quantity'],
  ]);

  const compiled = compileSbmuflGlyphText('fthoraSoftChromaticDiAbove ison oligon', {
    title: 'Prefix Pthora Fixture',
    startDegree: 'Di',
    bpm: 120,
  });

  assert.equal(hasErrorDiagnostics(compiled.diagnostics), false);
  assert.equal(compiled.pthoraEvents[0].scale, 'soft-chromatic');
  assert.equal(compiled.pthoraEvents[0].degree, 'Di');
  assert.equal(compiled.pthoraEvents[0].phase, 0);
  assert.deepEqual(compiled.notes.map(note => note.moria), [42, 50]);
});

test('glyph text source token adapter preserves spans and explicit source mode', () => {
  const tokens = sourceTokensFromGlyphText('ison U+E001 \u{1D051}', { source: 'ocr' });

  assert.deepEqual(tokens.map(token => token.raw), ['ison', 'U+E001', '\u{1D051}']);
  assert.deepEqual(tokens.map(token => token.source), ['ocr', 'ocr', 'ocr']);
  assert.deepEqual(tokens.map(token => token.span), [
    { start: 0, end: 4 },
    { start: 5, end: 11 },
    { start: 12, end: 13 },
  ]);
});
