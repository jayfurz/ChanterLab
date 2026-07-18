import test from 'node:test';
import assert from 'node:assert/strict';

import {
  planSyntheticPage,
  groundTruthFromLayout,
} from '../../ocr/synth/layout.js';
import { semanticTokenGroupsFromGlyphText } from '../glyph_import.js';
import { resolveGlyphGroups } from '../glyph_group_resolver.js';

function bboxCenter(bbox) {
  return { x: bbox.x + bbox.w / 2, y: bbox.y + bbox.h / 2 };
}

test('synth layout assigns one main glyph per group on a stable baseline', () => {
  const groups = semanticTokenGroupsFromGlyphText('ison oligon apostrofos');
  const layout = planSyntheticPage(groups, { fontSize: 40, pageWidth: 800 });

  assert.equal(layout.glyphs.length, 3);
  assert.equal(layout.groups.length, 3);
  for (const glyph of layout.glyphs) assert.equal(glyph.slot, 'main');

  const baselines = layout.glyphs.map(glyph => glyph.bbox.y + glyph.bbox.h);
  assert.equal(new Set(baselines).size, 1, 'all main glyphs share a baseline on one line');
});

test('synth layout stacks above-modifiers above the anchor and below-modifiers below', () => {
  const groups = semanticTokenGroupsFromGlyphText('oligon gorgonAbove apli');
  // After resolver: one group [oligon, gorgonAbove, apli]
  const layout = planSyntheticPage(groups, { fontSize: 40, pageWidth: 800 });

  assert.equal(layout.groups.length, 1);
  const [main, above, below] = layout.glyphs;
  assert.equal(main.slot, 'main');
  assert.equal(above.slot, 'above');
  assert.equal(below.slot, 'below');

  assert.ok(above.bbox.y + above.bbox.h <= main.bbox.y, 'above modifier sits over the anchor');
  assert.ok(below.bbox.y >= main.bbox.y + main.bbox.h, 'below modifier sits under the anchor');

  const mainCenter = bboxCenter(main.bbox);
  const aboveCenter = bboxCenter(above.bbox);
  const belowCenter = bboxCenter(below.bbox);
  assert.equal(aboveCenter.x, mainCenter.x);
  assert.equal(belowCenter.x, mainCenter.x);
});

test('synth layout wraps to a new line when groups overflow the usable width', () => {
  const text = Array.from({ length: 12 }, () => 'oligon').join(' ');
  const groups = semanticTokenGroupsFromGlyphText(text);
  const layout = planSyntheticPage(groups, { fontSize: 40, pageWidth: 320, marginX: 16 });

  const lines = new Set(layout.glyphs.map(glyph => glyph.line));
  assert.ok(lines.size >= 2, `expected wrap, got ${lines.size} line(s)`);
});

test('groundTruthFromLayout exports a JSON-safe manifest with bboxes and group indices', () => {
  const groups = semanticTokenGroupsFromGlyphText('oligon gorgonAbove');
  const layout = planSyntheticPage(groups, { fontSize: 32, pageWidth: 400 });
  const manifest = groundTruthFromLayout(layout);

  const json = JSON.parse(JSON.stringify(manifest));
  assert.equal(json.glyphs.length, 2);
  assert.equal(json.groups.length, 1);
  assert.deepEqual(json.groups[0].glyphIndices, [0, 1]);
  assert.equal(json.glyphs[0].groupId, json.groups[0].id);
  assert.equal(json.glyphs[1].groupId, json.groups[0].id);
});
