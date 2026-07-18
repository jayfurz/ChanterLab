// Layout planner for the labeled glyph reference atlas.
// Uses the complete font glyph table, not just the semantic importer subset.

import { NEANES_GLYPH_MAP } from './font_glyph_map.js';

const ROLE_ORDER = [
  'quantity',
  'ornamental',
  'temporal',
  'duration',
  'tempo',
  'rest',
  'pthora',
  'chroa',
  'martyria-note',
  'martyria-sign',
  'accidental',
  'mode',
  'barline',
  'indicator',
  'other',
];

const ROLE_LABELS = Object.freeze({
  quantity: 'Quantity · body neumes',
  ornamental: 'Ornamental · vareia, heteron, omalon, psifiston, …',
  temporal: 'Temporal · gorgon, digorgon, trigorgon, argon',
  duration: 'Duration · apli, klasma, dipli, koronis, …',
  tempo: 'Tempo · agogi markings',
  rest: 'Rests · leimma',
  pthora: 'Pthora · mode-change signs',
  chroa: 'Chroa · qualitative mode marks',
  'martyria-note': 'Martyria notes',
  'martyria-sign': 'Martyria modal signatures',
  accidental: 'Accidentals · diesis, yfesis (sharps/flats)',
  mode: 'Mode signatures · echos indicators',
  barline: 'Barlines · separators',
  indicator: 'Indicators · note & ison pointers',
  other: 'Unicode alternates & other',
});

const ROLE_RULES = [
  { role: 'rest', pattern: /^leimma/ },
  { role: 'temporal', pattern: /^(gorgon|digorgon|trigorgon|argon|diargon|triargon)/ },
  { role: 'duration', pattern: /^(apli|dipli|tripli|tetrapli|klasma|koronis)/ },
  { role: 'tempo', pattern: /^agogi/ },
  { role: 'pthora', pattern: /^fthora/ },
  { role: 'chroa', pattern: /^chroa/ },
  { role: 'martyria-note', pattern: /^martyriaNote/ },
  { role: 'martyria-sign', pattern: /^martyria(?!Note)/ },
  { role: 'accidental', pattern: /^(diesis|yfesis)/ },
  { role: 'barline', pattern: /^(barline|measureNumber)/ },
  { role: 'indicator', pattern: /^(noteIndicator|isonIndicator)/ },
  { role: 'mode', pattern: /^mode/ },
  { role: 'ornamental', pattern: /^(vareia|psifiston|antikenoma|omalon|heteron|endofonon|yfen|stavros|breath|gorthmikon|pelastikon|syndesmos)/ },
  { role: 'quantity', pattern: /./ }, // catch-all last
];

const EXCLUDE_PATTERNS = [
  /^\.notdef$/,
  /^space$/,
  /^uni200D$/,
  /^u1D[0-9A-F]+$/,           // bare Unicode codepoint names (duplicates of named glyphs)
  /^uniE[0-9A-F]+$/,           // bare PUA codepoint names
  /\.alt0[12]$/,               // alternate glyph designs, not distinct symbols
  /\.salt0[12]$/,              // stylistic alternates
];

const DEFAULTS = Object.freeze({
  columns: 10,
  cellWidth: 160,
  cellHeight: 135,
  glyphSize: 42,
  labelSize: 11,
  sectionGap: 24,
  headerHeight: 28,
  marginX: 24,
  marginY: 40,
});

export function planAtlas(options = {}) {
  const config = { ...DEFAULTS, ...options };

  const glyphs = NEANES_GLYPH_MAP
    .filter(g => !EXCLUDE_PATTERNS.some(pat => pat.test(g.name)))
    .map(g => {
      const role = ROLE_RULES.find(r => r.pattern.test(g.name))?.role ?? 'other';
      return {
        glyphName: g.name,
        codepoint: g.codepoint,
        character: characterForCodepoint(g.codepoint),
        role,
      };
    })
    .sort((a, b) => a.glyphName.localeCompare(b.glyphName));

  const byRole = new Map(ROLE_ORDER.map(role => [role, []]));
  for (const glyph of glyphs) {
    byRole.get(glyph.role).push(glyph);
  }

  const sections = [];
  let cursorY = config.marginY;

  for (const role of ROLE_ORDER) {
    const items = byRole.get(role) ?? [];
    if (!items.length) continue;

    const sectionTop = cursorY;
    const rows = Math.ceil(items.length / config.columns);
    const sectionHeight = config.headerHeight + rows * config.cellHeight;

    const cells = items.map((item, index) => {
      const col = index % config.columns;
      const row = Math.floor(index / config.columns);
      return {
        glyphName: item.glyphName,
        codepoint: item.codepoint,
        character: item.character,
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
