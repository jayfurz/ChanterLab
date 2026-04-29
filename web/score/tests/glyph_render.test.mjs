import test from 'node:test';
import assert from 'node:assert/strict';

import {
  characterForCodepoint,
  glyphPreviewFromText,
  glyphPreviewSourceKind,
} from '../glyph_render.js';
import { hasErrorDiagnostics } from '../diagnostics.js';

test('glyph preview renders quantity, temporal, and rest slots', () => {
  const preview = glyphPreviewFromText('ison oligon apostrofos gorgonAbove leimma2', {
    source: 'glyph',
  });

  assert.equal(hasErrorDiagnostics(preview.diagnostics), false);
  assert.equal(preview.clusters.length, 4);
  assert.deepEqual(preview.clusters.map(cluster => cluster.kind), [
    'neume',
    'neume',
    'neume',
    'rest',
  ]);
  assert.equal(preview.clusters[0].slots.main[0].glyphName, 'ison');
  assert.equal(preview.clusters[2].slots.main[0].glyphName, 'apostrofos');
  assert.equal(preview.clusters[2].slots.above[0].glyphName, 'gorgonAbove');
  assert.equal(preview.clusters[3].slots.main[0].glyphName, 'leimma2');
});

test('glyph preview uses SBMuFL display glyphs even for Unicode Byzantine source', () => {
  const preview = glyphPreviewFromText('\u{1D046}\u{1D047}\u{1D051}\u{1D08F}', {
    source: 'unicode',
  });

  assert.equal(hasErrorDiagnostics(preview.diagnostics), false);
  assert.deepEqual(preview.clusters.map(cluster => cluster.slots.main[0]?.glyphName), [
    'ison',
    'oligon',
    'apostrofos',
  ]);
  assert.equal(preview.clusters[0].slots.main[0].text, '\uE000');
  assert.equal(preview.clusters[1].slots.main[0].text, '\uE001');
  assert.equal(preview.clusters[2].slots.above[0].text, '\uE0F0');
});

test('glyph preview keeps pthora attached above the rendered quantity', () => {
  const preview = glyphPreviewFromText('fthoraSoftChromaticDiAbove ison oligon');

  assert.equal(hasErrorDiagnostics(preview.diagnostics), false);
  assert.equal(preview.clusters[0].kind, 'neume');
  assert.equal(preview.clusters[0].slots.above[0].glyphName, 'fthoraSoftChromaticDiAbove');
  assert.equal(preview.clusters[0].slots.main[0].glyphName, 'ison');
  assert.equal(preview.clusters[0].sourceSpan.start, 0);
  assert.equal(preview.clusters[0].sourceSpan.end, 31);
});

test('glyph preview renders duration signs as Neanes glyphs instead of raw words', () => {
  const preview = glyphPreviewFromText('ison apli oligon klasma apostrofos dipli leimma1 tripli');

  assert.equal(hasErrorDiagnostics(preview.diagnostics), false);
  assert.equal(preview.clusters[0].slots.right[0].glyphName, 'apli');
  assert.equal(preview.clusters[0].slots.right[0].text, '\uE0D2');
  assert.equal(preview.clusters[1].slots.right[0].glyphName, 'klasma');
  assert.equal(preview.clusters[1].slots.right[0].text, '\uE0D0');
  assert.equal(preview.clusters[2].slots.right[0].glyphName, 'dipli');
  assert.equal(preview.clusters[2].slots.right[0].text, '\uE0D3');
  assert.equal(preview.clusters[3].slots.right[0].glyphName, 'tripli');
  assert.equal(preview.clusters[3].slots.right[0].text, '\uE0D4');
});

test('glyph preview reports unknown tokens and renders a placeholder cluster', () => {
  const preview = glyphPreviewFromText('ison notAGlyph oligon');

  assert.equal(hasErrorDiagnostics(preview.diagnostics), true);
  assert.equal(preview.clusters[1].kind, 'unknown');
  assert.equal(preview.clusters[1].slots.main[0].text, '?');
  assert.equal(preview.clusters[1].slots.main[0].raw, 'notAGlyph');
});

test('glyph preview helpers normalize source modes and codepoints', () => {
  assert.equal(glyphPreviewSourceKind('glyph'), 'glyph-name');
  assert.equal(glyphPreviewSourceKind('sbmufl'), 'sbmufl-pua');
  assert.equal(glyphPreviewSourceKind('unicode'), 'unicode-byzantine');
  assert.equal(characterForCodepoint('U+E001'), '\uE001');
});
