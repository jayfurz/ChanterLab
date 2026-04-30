import {
  glyphPreviewFromText,
  glyphPreviewSourceKind,
} from './glyph_render.js';

export function renderGlyphPreview(previewEl, options = {}) {
  if (!previewEl) return undefined;
  const documentRef = options.documentRef ?? previewEl.ownerDocument ?? globalThis.document;
  const sourceText = options.text ?? '';
  const preview = options.preview ?? glyphPreviewFromText(sourceText, {
    source: glyphPreviewSourceKind(options.source ?? 'glyph'),
  });

  previewEl.innerHTML = '';
  const strip = createGlyphPreviewStrip(preview, {
    documentRef,
    sourceText,
    clusterTag: options.clusterTag ?? 'button',
  });
  const summary = createGlyphPreviewSummary(preview, documentRef);
  previewEl.append(strip, summary);
  previewEl.classList.toggle('has-errors', glyphPreviewErrorCount(preview) > 0);
  return preview;
}

export function createGlyphPreviewStrip(preview, options = {}) {
  const documentRef = options.documentRef ?? globalThis.document;
  const sourceText = options.sourceText ?? '';
  const strip = documentRef.createElement('div');
  strip.className = 'score-practice-glyph-preview-strip';

  if (!preview?.clusters?.length) {
    const empty = documentRef.createElement('span');
    empty.className = 'score-practice-glyph-preview-empty';
    empty.textContent = 'No glyphs';
    strip.appendChild(empty);
    return strip;
  }

  for (const cluster of preview.clusters) {
    strip.appendChild(createGlyphPreviewClusterElement(cluster, {
      documentRef,
      sourceText,
      clusterTag: options.clusterTag ?? 'button',
    }));
  }

  return strip;
}

export function createGlyphPreviewClusterElement(cluster, options = {}) {
  const documentRef = options.documentRef ?? globalThis.document;
  const clusterTag = options.clusterTag ?? 'button';
  const aboveItems = [...(cluster?.slots?.above ?? []), ...(cluster?.slots?.right ?? [])];
  const clusterEl = documentRef.createElement(clusterTag);
  if (clusterTag.toLowerCase() === 'button') clusterEl.type = 'button';
  clusterEl.className = [
    'score-practice-glyph-cluster',
    cluster?.kind,
    aboveItems.length ? 'has-above' : '',
    cluster?.slots?.below?.length ? 'has-below' : '',
  ].filter(Boolean).join(' ');
  clusterEl.title = cluster?.label ?? '';

  const span = codePointSpanToStringSpan(options.sourceText ?? '', cluster?.sourceSpan);
  if (span) {
    clusterEl.dataset.sourceStart = String(span.start);
    clusterEl.dataset.sourceEnd = String(span.end);
  }

  appendGlyphPreviewSlot(clusterEl, 'above', aboveItems, documentRef);
  appendGlyphPreviewSlot(clusterEl, 'main', cluster?.slots?.main ?? [], documentRef);
  appendGlyphPreviewSlot(clusterEl, 'below', cluster?.slots?.below ?? [], documentRef);

  const label = documentRef.createElement('span');
  label.className = 'score-practice-glyph-cluster-label';
  label.textContent = compactGlyphPreviewLabel(cluster?.label);
  clusterEl.appendChild(label);
  return clusterEl;
}

export function createGlyphPreviewSummary(preview, documentRef = globalThis.document) {
  const summary = documentRef.createElement('div');
  summary.className = 'score-practice-glyph-preview-summary';
  const errors = glyphPreviewErrorCount(preview);
  const warnings = glyphPreviewWarningCount(preview);
  summary.textContent = [
    `${preview?.clusters?.length ?? 0} group${preview?.clusters?.length === 1 ? '' : 's'}`,
    errors ? `${errors} error${errors === 1 ? '' : 's'}` : '',
    warnings ? `${warnings} warning${warnings === 1 ? '' : 's'}` : '',
  ].filter(Boolean).join(' · ');
  return summary;
}

export function compactGlyphPreviewLabel(label) {
  return String(label ?? '')
    .replaceAll('fthora', '')
    .replaceAll('Chromatic', 'Chr')
    .replaceAll('Above', '')
    .replaceAll('gorgon', 'gor')
    .slice(0, 28);
}

export function codePointSpanToStringSpan(text, span) {
  if (!Number.isInteger(span?.start) || !Number.isInteger(span?.end)) return undefined;
  const chars = Array.from(text ?? '');
  const start = chars.slice(0, span.start).join('').length;
  const end = chars.slice(0, span.end).join('').length;
  return { start, end };
}

function appendGlyphPreviewSlot(clusterEl, slotName, items, documentRef) {
  const row = documentRef.createElement('span');
  row.className = `score-practice-glyph-slot ${slotName}`;
  for (const item of items ?? []) {
    row.appendChild(glyphPreviewItemElement(item, documentRef));
  }
  clusterEl.appendChild(row);
}

function glyphPreviewItemElement(item, documentRef) {
  const el = documentRef.createElement('span');
  el.className = `score-practice-glyph-preview-item ${item?.kind ?? 'unknown'}`;
  el.textContent = item?.text || '?';
  el.title = item?.label ?? item?.glyphName ?? item?.raw ?? '';
  return el;
}

function glyphPreviewErrorCount(preview) {
  return (preview?.diagnostics ?? [])
    .filter(diagnostic => diagnostic?.severity === 'error').length;
}

function glyphPreviewWarningCount(preview) {
  return (preview?.diagnostics ?? [])
    .filter(diagnostic => diagnostic?.severity === 'warning').length;
}
