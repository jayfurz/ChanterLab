import test from 'node:test';
import assert from 'node:assert/strict';

import { compileGlyphText, listGlyphImportTokens } from '../glyph_import.js';
import { listGlyphClusterCatalog } from '../glyph_cluster_catalog.js';
import {
  applyGlyphScoreCluster,
  createGlyphScoreEditorState,
  glyphScoreClusterInfo,
  removeGlyphScoreGroup,
  serializeGlyphScoreEditorState,
} from '../glyph_score_editor.js';

const CATALOG = listGlyphClusterCatalog();

function cluster(id) {
  const found = CATALOG.find(item => item.id === id);
  assert.ok(found, id);
  return found;
}

test('glyph score editor marks atlas semantic clusters as importable', () => {
  const oligon = glyphScoreClusterInfo(cluster('quantity-oligon'));
  const gorgon = glyphScoreClusterInfo(cluster('timing-gorgonAbove'));
  const compound = glyphScoreClusterInfo(cluster('oligon-compounds-oligonKentimaMiddle'));

  assert.equal(oligon.importable, true);
  assert.equal(oligon.insertion, 'group');
  assert.equal(gorgon.importable, true);
  assert.equal(gorgon.insertion, 'modifier');
  assert.equal(compound.importable, true);
  assert.deepEqual(compound.tokenNames, ['oligonKentimaMiddle']);
});

test('glyph score editor can import every atlas cluster', () => {
  const importTokenNames = new Set(listGlyphImportTokens().map(token => token.glyphName));
  const missingGlyphs = [...new Set(CATALOG.flatMap(item => item.components.map(component => component.glyphName)))]
    .filter(glyphName => !importTokenNames.has(glyphName));
  const blockedClusters = CATALOG
    .map(item => [item.id, glyphScoreClusterInfo(item)])
    .filter(([, info]) => !info.importable)
    .map(([id, info]) => `${id}: ${info.reason}`);

  assert.deepEqual(missingGlyphs, []);
  assert.deepEqual(blockedClusters, []);
});

test('glyph score editor appends quantity groups and attaches modifiers to the selected group', () => {
  let state = createGlyphScoreEditorState();
  state = applyGlyphScoreCluster(state, cluster('quantity-ison'));
  state = applyGlyphScoreCluster(state, cluster('quantity-oligon'));
  state = applyGlyphScoreCluster(state, cluster('timing-gorgonAbove'));
  state = applyGlyphScoreCluster(state, cluster('duration-klasma'));

  assert.equal(serializeGlyphScoreEditorState(state), 'ison | oligon gorgonAbove klasma');
  assert.equal(state.selectedIndex, 1);
});

test('glyph score editor replaces mutually exclusive modifiers within a group', () => {
  let state = createGlyphScoreEditorState();
  state = applyGlyphScoreCluster(state, cluster('quantity-oligon'));
  state = applyGlyphScoreCluster(state, cluster('timing-gorgonAbove'));
  state = applyGlyphScoreCluster(state, cluster('timing-digorgon'));
  state = applyGlyphScoreCluster(state, cluster('mode-fthoraSoftChromaticDiAbove'));
  state = applyGlyphScoreCluster(state, cluster('mode-chroaZygosAbove'));

  assert.equal(serializeGlyphScoreEditorState(state), 'oligon digorgon chroaZygosAbove');
});

test('glyph score editor attaches mode signs to the nearest compatible quantity', () => {
  let state = createGlyphScoreEditorState();
  state = applyGlyphScoreCluster(state, cluster('quantity-oligon'));
  state = applyGlyphScoreCluster(state, cluster('rest-leimma2'));
  state = applyGlyphScoreCluster(state, cluster('mode-fthoraSoftChromaticDiAbove'));

  assert.equal(serializeGlyphScoreEditorState(state), 'oligon fthoraSoftChromaticDiAbove | leimma2');
  assert.equal(state.selectedIndex, 0);
});

test('glyph score editor serializes SBMuFL source text for importable groups', () => {
  let state = createGlyphScoreEditorState();
  state = applyGlyphScoreCluster(state, cluster('quantity-ison'));
  state = applyGlyphScoreCluster(state, cluster('example-oligon-gorgon'));
  state = applyGlyphScoreCluster(state, cluster('rest-leimma2'));

  const text = serializeGlyphScoreEditorState(state, { source: 'sbmufl' });
  assert.equal(text, '\uE000 | \uE0F0 \uE001 | \uE0E1');

  const compiled = compileGlyphText(text, {
    source: 'sbmufl-pua',
    startDegree: 'Ni',
  });
  assert.deepEqual(
    compiled.diagnostics.filter(diagnostic => diagnostic.severity === 'error'),
    []
  );
  assert.equal(compiled.notes.length, 2);
});

test('glyph score editor imports martyria checkpoints as score groups', () => {
  const state = createGlyphScoreEditorState();
  const next = applyGlyphScoreCluster(state, cluster('martyria-di-diatonic'));

  assert.equal(next.changed, true);
  assert.equal(serializeGlyphScoreEditorState(next), 'martyriaNoteDi martyriaDeltaBelow');

  const compiled = compileGlyphText(serializeGlyphScoreEditorState(next), {
    startDegree: 'Di',
    bpm: 120,
  });
  assert.deepEqual(
    compiled.diagnostics.filter(diagnostic => diagnostic.severity === 'error'),
    []
  );
  assert.equal(compiled.checkpoints.length, 1);
  assert.equal(compiled.checkpoints[0].degree, 'Di');
});

test('glyph score editor removes selected groups and keeps selection valid', () => {
  let state = createGlyphScoreEditorState();
  state = applyGlyphScoreCluster(state, cluster('quantity-ison'));
  state = applyGlyphScoreCluster(state, cluster('quantity-oligon'));

  state = removeGlyphScoreGroup(state, 1);
  assert.equal(serializeGlyphScoreEditorState(state), 'ison');
  assert.equal(state.selectedIndex, 0);
});
