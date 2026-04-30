import test from 'node:test';
import assert from 'node:assert/strict';

import {
  glyphCharacter,
  glyphCodepoint,
  listGlyphClusterCatalog,
} from '../glyph_cluster_catalog.js';
import {
  formatGlyphClusterSemantic,
  glyphClusterRenderModel,
} from '../glyph_cluster_render.js';

test('glyph cluster catalog has stable unique ids', () => {
  const clusters = listGlyphClusterCatalog();
  const ids = clusters.map(cluster => cluster.id);

  assert.ok(clusters.length >= 90);
  assert.equal(new Set(ids).size, ids.length);
});

test('glyph cluster catalog components all resolve to Neanes codepoints', () => {
  const clusters = listGlyphClusterCatalog();
  const missing = clusters.flatMap(cluster => (
    cluster.components
      .filter(component => !glyphCodepoint(component.glyphName) || !glyphCharacter(component.glyphName))
      .map(component => `${cluster.id}:${component.glyphName}`)
  ));

  assert.deepEqual(missing, []);
});

test('glyph cluster render models expose all declared slots without missing glyphs', () => {
  for (const cluster of listGlyphClusterCatalog()) {
    const model = glyphClusterRenderModel(cluster);

    assert.ok(Array.isArray(model.slots.above), cluster.id);
    assert.ok(Array.isArray(model.slots.main), cluster.id);
    assert.ok(Array.isArray(model.slots.below), cluster.id);
    assert.deepEqual(model.missing, [], cluster.id);
    assert.equal(model.hasAbove, model.slots.above.length > 0, cluster.id);
    assert.equal(model.hasMain, model.slots.main.length > 0, cluster.id);
    assert.equal(model.hasBelow, model.slots.below.length > 0, cluster.id);
    assert.ok(formatGlyphClusterSemantic(cluster.semantic).length > 0, cluster.id);
  }
});

test('standalone modifier atlas cells are marked for centered rendering', () => {
  const modifierOnly = new Set(['Duration Signs', 'Timing Signs', 'Pthora And Chroa']);

  for (const cluster of listGlyphClusterCatalog().filter(cluster => modifierOnly.has(cluster.category))) {
    const model = glyphClusterRenderModel(cluster);
    assert.equal(model.modifierOnly, true, cluster.id);
  }
});

test('dotted gorgon timing weights are normalized-ready positive ratios', () => {
  const timingClusters = listGlyphClusterCatalog()
    .filter(cluster => cluster.semantic?.kind === 'temporal');

  assert.ok(timingClusters.some(cluster => cluster.id === 'timing-gorgonDottedLeft'));
  assert.ok(timingClusters.some(cluster => cluster.id === 'timing-digorgonDottedLeftAbove'));
  assert.ok(timingClusters.some(cluster => cluster.id === 'timing-trigorgonDottedRight'));

  for (const cluster of timingClusters) {
    const weights = cluster.semantic.timingWeights;
    assert.ok(Array.isArray(weights), cluster.id);
    assert.ok(weights.length >= 2, cluster.id);
    assert.ok(weights.every(weight => Number.isFinite(weight) && weight > 0), cluster.id);
    assert.ok(weights.reduce((sum, weight) => sum + weight, 0) > weights.length - 1, cluster.id);
  }
});
