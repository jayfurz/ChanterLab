// Layout planner for the labeled glyph reference atlas.
// Produces a deterministic page description that the renderer paints to canvas.

import { listGlyphImportTokens } from '../../score/glyph_import.js';

const ROLE_ORDER = [
  'quantity',
  'rest',
  'temporal',
  'duration',
  'tempo',
  'pthora',
  'qualitative',
  'martyria-note',
  'martyria-sign',
];

const ROLE_LABELS = Object.freeze({
  quantity: 'Quantity (body) neumes',
  rest: 'Rests · leimma',
  temporal: 'Temporal · gorgon family',
  duration: 'Duration · apli, klasma, dipli, …',
  tempo: 'Tempo · agogi',
  pthora: 'Pthora · mode signs',
  qualitative: 'Qualitative · chroai',
  'martyria-note': 'Martyria notes',
  'martyria-sign': 'Martyria signs',
});

const DEFAULTS = Object.freeze({
  columns: 8,
  cellWidth: 140,
  cellHeight: 112,
  glyphSize: 64,
  labelSize: 10,
  sectionGap: 22,
  headerHeight: 28,
  marginX: 24,
  marginY: 32,
});

export function planAtlas(options = {}) {
  const config = { ...DEFAULTS, ...options };

  const tokens = listGlyphImportTokens()
    .filter(token => token.codepoint)
    .sort((a, b) => a.glyphName.localeCompare(b.glyphName));

  const byRole = new Map(ROLE_ORDER.map(role => [role, []]));
  for (const token of tokens) {
    if (byRole.has(token.role)) byRole.get(token.role).push(token);
  }

  const sections = [];
  let cursorY = config.marginY;

  for (const role of ROLE_ORDER) {
    const items = byRole.get(role) ?? [];
    if (!items.length) continue;

    const sectionTop = cursorY;
    const rows = Math.ceil(items.length / config.columns);
    const sectionHeight = config.headerHeight + rows * config.cellHeight;

    const cells = items.map((token, index) => {
      const col = index % config.columns;
      const row = Math.floor(index / config.columns);
      return {
        glyphName: token.glyphName,
        codepoint: token.codepoint,
        character: characterForCodepoint(token.codepoint),
        x: config.marginX + col * config.cellWidth,
        y: sectionTop + config.headerHeight + row * config.cellHeight,
        cellWidth: config.cellWidth,
        cellHeight: config.cellHeight,
      };
    });

    sections.push({
      role,
      label: ROLE_LABELS[role] ?? role,
      top: sectionTop,
      height: sectionHeight,
      cells,
    });

    cursorY = sectionTop + sectionHeight + config.sectionGap;
  }

  return {
    width: config.marginX * 2 + config.columns * config.cellWidth,
    height: cursorY - config.sectionGap + config.marginY,
    sections,
    config,
    glyphCount: sections.reduce((sum, section) => sum + section.cells.length, 0),
  };
}

export function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}

// Wrap a camelCase glyph name into multiple lines so long names fit narrow cells.
export function wrapGlyphName(name, maxCharsPerLine = 18) {
  if (!name || name.length <= maxCharsPerLine) return [name];
  const segments = name.match(/[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)/g) ?? [name];
  const lines = [];
  let current = '';
  for (const segment of segments) {
    const candidate = current + segment;
    if (candidate.length > maxCharsPerLine && current.length > 0) {
      lines.push(current);
      current = segment;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  return lines;
}
