import {
  listMinimalGlyphImportTokens,
  semanticTokenGroupsFromGlyphText,
} from './glyph_import.js';

const GLYPH_TOKEN_BY_NAME = new Map(
  listMinimalGlyphImportTokens().map(token => [token.glyphName, token])
);

const PREVIEW_SOURCE_KIND = Object.freeze({
  glyph: 'glyph-name',
  sbmufl: 'sbmufl-pua',
  unicode: 'unicode-byzantine',
});

export function glyphPreviewSourceKind(source) {
  return PREVIEW_SOURCE_KIND[source] ?? source;
}

export function glyphPreviewFromText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const source = glyphPreviewSourceKind(options.source);
  const groups = semanticTokenGroupsFromGlyphText(text, {
    ...(source ? { source } : {}),
    diagnostics,
  });

  return {
    diagnostics,
    groups,
    clusters: groups.map((group, index) => glyphPreviewClusterFromGroup(group, index)),
  };
}

export function glyphPreviewClusterFromGroup(group, index = 0) {
  const tokens = Array.isArray(group) ? group : [];
  const slots = {
    above: [],
    main: [],
    right: [],
    below: [],
  };
  const names = [];
  let kind = 'modifier';

  for (const token of tokens) {
    const item = glyphPreviewItemFromToken(token);
    names.push(item.label);

    if (token.kind === 'quantity') {
      kind = 'neume';
      slots.main.push(item);
      continue;
    }
    if (token.kind === 'rest') {
      kind = 'rest';
      slots.main.push(item);
      continue;
    }
    if (token.kind === 'tempo') {
      if (kind === 'modifier') kind = 'tempo';
      slots.main.push(item);
      continue;
    }
    if (token.kind === 'duration') {
      slots.right.push(item);
      continue;
    }
    if (token.kind === 'pthora') {
      if (kind === 'modifier') kind = 'pthora';
      slots.above.push(item);
      continue;
    }
    if (token.kind === 'temporal' || token.kind === 'qualitative') {
      slots.above.push(item);
      continue;
    }
    if (token.kind === 'unknown') {
      kind = 'unknown';
      slots.main.push(item);
      continue;
    }
    slots.below.push(item);
  }

  return {
    index,
    kind,
    slots,
    label: names.filter(Boolean).join(' + ') || 'empty',
    sourceSpan: sourceSpanForTokens(tokens),
    tokenCount: tokens.length,
  };
}

export function glyphPreviewItemFromToken(token) {
  const glyphName = glyphNameForSemanticToken(token);
  const metadata = glyphName ? GLYPH_TOKEN_BY_NAME.get(glyphName) : undefined;
  const sourceToken = token?.source?.[0];
  const raw = sourceToken?.raw;
  const text = metadata?.codepoint
    ? characterForCodepoint(metadata.codepoint)
    : token?.kind === 'unknown' ? '?' : String(raw ?? glyphName ?? '');

  return {
    kind: token?.kind ?? 'unknown',
    glyphName,
    text,
    label: glyphName ?? raw ?? token?.kind ?? 'unknown',
    raw,
    sourceSpan: sourceSpanForTokens([token]),
  };
}

export function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}

function glyphNameForSemanticToken(token) {
  if (!token) return undefined;
  const sourceGlyphName = token.source?.find(source => source?.glyphName)?.glyphName;
  if (token.kind === 'quantity') return token.value?.glyphName;
  if (token.kind === 'rest') return token.value?.sign;
  if (token.kind === 'temporal') return sourceGlyphName ?? token.value?.sign;
  if (token.kind === 'duration') return sourceGlyphName ?? token.value?.sign;
  if (token.kind === 'pthora') return token.value?.glyphName;
  if (token.kind === 'qualitative') return token.value?.glyphName;
  if (token.kind === 'tempo') return sourceGlyphName;
  return sourceGlyphName;
}

function sourceSpanForTokens(tokens) {
  const spans = (tokens ?? [])
    .flatMap(token => token?.source ?? [])
    .map(source => source?.span)
    .filter(span => Number.isInteger(span?.start) && Number.isInteger(span?.end));
  if (!spans.length) return undefined;
  return {
    start: Math.min(...spans.map(span => span.start)),
    end: Math.max(...spans.map(span => span.end)),
  };
}
