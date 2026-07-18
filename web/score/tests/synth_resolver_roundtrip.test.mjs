import test from 'node:test';
import assert from 'node:assert/strict';

import { planSyntheticPage } from '../../ocr/synth/layout.js';
import {
  semanticTokenGroupsFromGlyphText,
  semanticTokensFromGlyphs,
} from '../glyph_import.js';
import { resolveGlyphGroups, detectResolverMode } from '../glyph_group_resolver.js';

function namesByGroup(groups) {
  return groups.map(group =>
    group.map(token => token.source[0].glyphName).filter(Boolean).sort()
  );
}

function rebuildSourceTokens(layout) {
  return layout.glyphs.map(glyph => ({
    glyphName: glyph.glyphName,
    region: { bbox: { ...glyph.bbox }, line: glyph.line, role: 'neume' },
    confidence: 0.99,
  }));
}

test('synthetic layout round-trips through the spatial resolver to identical groups', () => {
  const cases = [
    'ison oligon apostrofos',
    'oligon gorgonAbove apli',
    'fthoraSoftChromaticDiAbove ison oligon',
    'ison oligon oligon apostrofos gorgonAbove leimma2',
  ];

  for (const text of cases) {
    const original = semanticTokenGroupsFromGlyphText(text);
    const layout = planSyntheticPage(original, { fontSize: 40, pageWidth: 1024 });

    const tokens = semanticTokensFromGlyphs(rebuildSourceTokens(layout));
    assert.equal(detectResolverMode(tokens), 'spatial', `case "${text}" should run spatial`);

    const regrouped = resolveGlyphGroups(tokens);
    assert.deepEqual(
      namesByGroup(regrouped),
      namesByGroup(original),
      `case "${text}" should round-trip`
    );
  }
});

test('multi-line synthetic layout still groups correctly per anchor column', () => {
  const text = Array.from({ length: 8 }, () => 'oligon gorgonAbove').join(' ');
  const original = semanticTokenGroupsFromGlyphText(text);
  const layout = planSyntheticPage(original, { fontSize: 40, pageWidth: 320, marginX: 16 });

  const tokens = semanticTokensFromGlyphs(rebuildSourceTokens(layout));
  const regrouped = resolveGlyphGroups(tokens);

  assert.equal(regrouped.length, original.length);
  for (let i = 0; i < regrouped.length; i += 1) {
    assert.deepEqual(
      regrouped[i].map(token => token.source[0].glyphName).sort(),
      original[i].map(token => token.source[0].glyphName).sort(),
      `group ${i} mismatch`
    );
  }
});
