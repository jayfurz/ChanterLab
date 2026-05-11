import { listGlyphImportTokens } from '../../score/glyph_import.js';

const GLYPH_TOKEN_BY_NAME = new Map(
  listGlyphImportTokens().map(token => [token.glyphName, token])
);

const SLOT_BY_KIND = Object.freeze({
  quantity: 'main',
  rest: 'main',
  tempo: 'main',
  'martyria-note': 'main',
  pthora: 'above',
  temporal: 'above',
  qualitative: 'above',
  duration: 'below',
  'martyria-sign': 'below',
});

const DEFAULT_OPTIONS = Object.freeze({
  fontSize: 48,
  pageWidth: 1024,
  marginX: 32,
  marginY: 32,
  lineHeight: 132,
  anchorAdvance: 1.15,
  groupGap: 0.25,
  modifierStackGap: 0.15,
  aboveOffset: 0.05,
  belowOffset: 0.05,
});

export function planSyntheticPage(groups, options = {}) {
  const config = { ...DEFAULT_OPTIONS, ...options };
  const list = Array.isArray(groups) ? groups : [];
  const cellWidth = config.fontSize * config.anchorAdvance;
  const groupGap = config.fontSize * config.groupGap;
  const usableWidth = config.pageWidth - config.marginX * 2;

  const glyphs = [];
  const groupSummaries = [];

  let cursorX = config.marginX;
  let cursorY = config.marginY;
  let lineIndex = 0;

  for (let groupIndex = 0; groupIndex < list.length; groupIndex += 1) {
    const tokens = Array.isArray(list[groupIndex]) ? list[groupIndex] : [];
    if (!tokens.length) continue;

    const advance = cellWidth;
    if (cursorX + advance > config.marginX + usableWidth) {
      cursorX = config.marginX;
      cursorY += config.lineHeight;
      lineIndex += 1;
    }

    const anchorIndex = tokens.findIndex(token => SLOT_BY_KIND[token?.kind] === 'main');
    const baselineY = cursorY + config.fontSize;
    const anchorCenterX = cursorX + cellWidth / 2;

    const slotCounters = { above: 0, below: 0 };
    const groupGlyphIndices = [];
    const groupId = `g${String(groupIndex).padStart(4, '0')}`;

    tokens.forEach((token, indexInGroup) => {
      const glyph = layoutGlyphInGroup({
        token,
        indexInGroup,
        anchorIndex,
        anchorCenterX,
        baselineY,
        cellWidth,
        config,
        slotCounters,
      });
      if (!glyph) return;
      glyph.groupId = groupId;
      glyph.line = lineIndex;
      groupGlyphIndices.push(glyphs.length);
      glyphs.push(glyph);
    });

    groupSummaries.push({
      id: groupId,
      line: lineIndex,
      anchorIndex: anchorIndex >= 0 ? anchorIndex : null,
      glyphIndices: groupGlyphIndices,
      bbox: bboxOfGlyphs(groupGlyphIndices.map(i => glyphs[i])),
    });

    cursorX += advance + groupGap;
  }

  const pageHeight = cursorY + config.lineHeight + config.marginY;

  return {
    width: config.pageWidth,
    height: pageHeight,
    fontSize: config.fontSize,
    fontFamily: 'Neanes',
    glyphs,
    groups: groupSummaries,
  };
}

function layoutGlyphInGroup({
  token,
  indexInGroup,
  anchorIndex,
  anchorCenterX,
  baselineY,
  cellWidth,
  config,
  slotCounters,
}) {
  const glyphName = token?.source?.[0]?.glyphName ?? token?.value?.glyphName;
  if (!glyphName) return undefined;
  const metadata = GLYPH_TOKEN_BY_NAME.get(glyphName);
  if (!metadata) return undefined;

  const slot = indexInGroup === anchorIndex
    ? 'main'
    : SLOT_BY_KIND[token.kind] ?? 'above';

  const cellHeight = config.fontSize;
  const halfCell = cellHeight / 2;
  const x = anchorCenterX - cellWidth / 2;

  if (slot === 'main') {
    return {
      glyphName,
      codepoint: metadata.codepoint,
      character: characterForCodepoint(metadata.codepoint),
      role: metadata.role,
      slot,
      bbox: { x, y: baselineY - cellHeight, w: cellWidth, h: cellHeight },
    };
  }

  if (slot === 'above') {
    const stackOffset = slotCounters.above * cellHeight * (1 - config.modifierStackGap);
    const y = baselineY - cellHeight - cellHeight * (1 + config.aboveOffset) - stackOffset;
    slotCounters.above += 1;
    return {
      glyphName,
      codepoint: metadata.codepoint,
      character: characterForCodepoint(metadata.codepoint),
      role: metadata.role,
      slot,
      bbox: { x: anchorCenterX - halfCell, y, w: cellHeight, h: cellHeight },
    };
  }

  // slot === 'below'
  const stackOffset = slotCounters.below * cellHeight * (1 - config.modifierStackGap);
  const y = baselineY + cellHeight * config.belowOffset + stackOffset;
  slotCounters.below += 1;
  return {
    glyphName,
    codepoint: metadata.codepoint,
    character: characterForCodepoint(metadata.codepoint),
    role: metadata.role,
    slot,
    bbox: { x: anchorCenterX - halfCell, y, w: cellHeight, h: cellHeight },
  };
}

function bboxOfGlyphs(glyphs) {
  if (!glyphs.length) return undefined;
  const left = Math.min(...glyphs.map(glyph => glyph.bbox.x));
  const top = Math.min(...glyphs.map(glyph => glyph.bbox.y));
  const right = Math.max(...glyphs.map(glyph => glyph.bbox.x + glyph.bbox.w));
  const bottom = Math.max(...glyphs.map(glyph => glyph.bbox.y + glyph.bbox.h));
  return { x: left, y: top, w: right - left, h: bottom - top };
}

export function groundTruthFromLayout(layout) {
  return {
    width: layout.width,
    height: layout.height,
    fontFamily: layout.fontFamily,
    fontSize: layout.fontSize,
    glyphs: layout.glyphs.map(glyph => ({
      glyphName: glyph.glyphName,
      codepoint: glyph.codepoint,
      bbox: { ...glyph.bbox },
      groupId: glyph.groupId,
      line: glyph.line,
      slot: glyph.slot,
    })),
    groups: layout.groups.map(group => ({
      id: group.id,
      line: group.line,
      anchorIndex: group.anchorIndex,
      glyphIndices: [...group.glyphIndices],
      bbox: group.bbox ? { ...group.bbox } : null,
    })),
  };
}

export function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}
