import test from 'node:test';
import assert from 'node:assert/strict';

import {
  resolveGlyphGroups,
  detectResolverMode,
} from '../glyph_group_resolver.js';
import {
  compileGlyphGroups,
  semanticTokensFromGlyphs,
} from '../glyph_import.js';
import { DIAGNOSTIC_SEVERITY } from '../diagnostics.js';

function withRegion(input, bbox, extras = {}) {
  return { ...input, region: { bbox, ...extras } };
}

test('detectResolverMode returns spatial when every token carries a region', () => {
  const tokens = semanticTokensFromGlyphs([
    withRegion({ glyphName: 'oligon' }, { x: 10, y: 0, w: 20, h: 20 }),
    withRegion({ glyphName: 'gorgonAbove' }, { x: 12, y: 0, w: 10, h: 8 }),
  ]);
  assert.equal(detectResolverMode(tokens), 'spatial');
});

test('detectResolverMode falls back to linear when any token lacks a region', () => {
  const tokens = semanticTokensFromGlyphs([
    { glyphName: 'oligon' },
    withRegion({ glyphName: 'gorgonAbove' }, { x: 12, y: 0, w: 10, h: 8 }),
  ]);
  assert.equal(detectResolverMode(tokens), 'linear');
});

test('spatial resolver groups modifiers with the anchor whose column they sit in', () => {
  const tokens = semanticTokensFromGlyphs([
    withRegion({ glyphName: 'oligon' }, { x: 10, y: 20, w: 20, h: 20 }),
    withRegion({ glyphName: 'gorgonAbove' }, { x: 15, y: 0, w: 10, h: 8 }),
    withRegion({ glyphName: 'apostrofos' }, { x: 50, y: 20, w: 20, h: 20 }),
    withRegion({ glyphName: 'klasma' }, { x: 55, y: 45, w: 10, h: 6 }),
  ]);
  const groups = resolveGlyphGroups(tokens);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].map(token => token.source[0].glyphName), ['oligon', 'gorgonAbove']);
  assert.deepEqual(groups[1].map(token => token.source[0].glyphName), ['apostrofos', 'klasma']);
});

test('spatial resolver attaches a prefix pthora to the next anchor on its right', () => {
  const tokens = semanticTokensFromGlyphs([
    withRegion({ glyphName: 'fthoraSoftChromaticDiAbove' }, { x: 5, y: 0, w: 10, h: 10 }),
    withRegion({ glyphName: 'oligon' }, { x: 30, y: 20, w: 20, h: 20 }),
  ]);
  const groups = resolveGlyphGroups(tokens);
  assert.equal(groups.length, 1);
  const kinds = groups[0].map(token => token.kind).sort();
  assert.deepEqual(kinds, ['pthora', 'quantity']);
});

test('spatial resolver flags a modifier with no anchors at all', () => {
  const tokens = semanticTokensFromGlyphs([
    withRegion({ glyphName: 'gorgonAbove' }, { x: 12, y: 0, w: 10, h: 8 }),
  ]);
  const diagnostics = [];
  resolveGlyphGroups(tokens, { diagnostics });
  assert.equal(diagnostics.some(diagnostic => diagnostic.code === 'glyph-import-unattached-modifier'), true);
});

test('low-confidence source tokens emit a REVIEW diagnostic without blocking compile', () => {
  const diagnostics = [];
  const compiled = compileGlyphGroups([
    [{ glyphName: 'ison', confidence: 0.42 }],
    [{ glyphName: 'oligon', confidence: 0.95 }],
  ], {
    title: 'Low Confidence Fixture',
    startDegree: 'Ni',
    bpm: 120,
    diagnostics,
  });

  const reviews = compiled.diagnostics.filter(diagnostic => diagnostic.severity === DIAGNOSTIC_SEVERITY.REVIEW);
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].code, 'glyph-import-low-confidence');
  assert.equal(reviews[0].source.glyphName, 'ison');
  assert.equal(compiled.notes.length, 2);
});

test('alternates pass through onto the semantic source token', () => {
  const tokens = semanticTokensFromGlyphs([
    {
      glyphName: 'oligon',
      confidence: 0.9,
      alternates: [
        { glyphName: 'petasti', confidence: 0.4 },
        { glyphName: 'oligonKentimaMiddle', confidence: 0.2 },
      ],
    },
  ]);
  assert.equal(tokens[0].source[0].alternates.length, 2);
  assert.equal(tokens[0].source[0].alternates[0].glyphName, 'petasti');
  assert.equal(tokens[0].source[0].confidence, 0.9);
});

test('mixed-region input degrades to linear grouping', () => {
  const tokens = semanticTokensFromGlyphs([
    { glyphName: 'oligon' },
    withRegion({ glyphName: 'gorgonAbove' }, { x: 12, y: 0, w: 10, h: 8 }),
    { glyphName: 'apostrofos' },
  ]);
  const groups = resolveGlyphGroups(tokens);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].map(token => token.source[0].glyphName), ['oligon', 'gorgonAbove']);
  assert.deepEqual(groups[1].map(token => token.source[0].glyphName), ['apostrofos']);
});
