import {
  glyphCharacter,
  glyphCodepoint,
} from './glyph_cluster_catalog.js';

const CLUSTER_SLOTS = ['above', 'main', 'below'];

export function glyphClusterRenderModel(cluster) {
  const slots = Object.fromEntries(CLUSTER_SLOTS.map(slot => [slot, []]));
  const missing = [];

  for (const component of cluster?.components ?? []) {
    const slot = CLUSTER_SLOTS.includes(component.slot) ? component.slot : 'main';
    const codepoint = glyphCodepoint(component.glyphName);
    const text = glyphCharacter(component.glyphName);
    if (!codepoint || !text) missing.push(component.glyphName);
    slots[slot].push({
      glyphName: component.glyphName,
      role: component.role,
      slot,
      codepoint,
      text: text ?? '?',
    });
  }

  return {
    id: cluster?.id,
    label: cluster?.label,
    category: cluster?.category,
    semantic: cluster?.semantic,
    slots,
    missing,
    modifierOnly: !slots.main.length && (slots.above.length > 0 || slots.below.length > 0),
  };
}

export function createGlyphClusterElement(cluster, documentRef = globalThis.document) {
  if (!documentRef) throw new Error('createGlyphClusterElement requires a DOM document.');
  const model = glyphClusterRenderModel(cluster);
  const shell = documentRef.createElement('div');
  shell.className = 'glyph-cluster-render';
  shell.dataset.clusterId = model.id ?? '';
  if (model.modifierOnly) shell.classList.add('modifier-only');

  for (const slotName of CLUSTER_SLOTS) {
    const slot = documentRef.createElement('span');
    slot.className = `glyph-cluster-render-slot ${slotName}`;
    for (const item of model.slots[slotName]) {
      const glyph = documentRef.createElement('span');
      glyph.className = `glyph-cluster-render-item ${item.role ?? 'unknown'}`;
      glyph.textContent = item.text;
      glyph.title = `${item.glyphName} ${item.codepoint ?? 'missing'}`;
      slot.appendChild(glyph);
    }
    shell.appendChild(slot);
  }

  if (model.missing.length) {
    shell.classList.add('has-missing-glyphs');
    shell.title = `Missing glyphs: ${model.missing.join(', ')}`;
  }

  return shell;
}

export function formatGlyphClusterSemantic(semantic) {
  if (!semantic?.kind) return 'semantic: unknown';
  if (semantic.kind === 'neume') {
    const movement = semantic.movement
      ? `${semantic.movement.direction} ${semantic.movement.steps}`
      : 'movement pending';
    const extras = [
      semantic.beats ? `${semantic.beats} beats` : '',
      semantic.modeSign ?? '',
      semantic.timingWeights ? timingWeightsLabel(semantic.timingWeights) : '',
    ].filter(Boolean);
    return ['neume', movement, ...extras].join(' | ');
  }
  if (semantic.kind === 'rest') return `rest | ${semantic.beats} beats`;
  if (semantic.kind === 'duration') return `duration | ${semantic.beats} beats`;
  if (semantic.kind === 'temporal') return `timing | ${timingWeightsLabel(semantic.timingWeights)}`;
  if (semantic.kind === 'martyria') return `martyria | ${semantic.degree} | ${semantic.scale}`;
  if (semantic.kind === 'pending-interpretation') return `pending | ${semantic.note}`;
  return semantic.kind;
}

function timingWeightsLabel(weights) {
  return Array.isArray(weights) ? `weights ${weights.join(':')}` : 'weights pending';
}
