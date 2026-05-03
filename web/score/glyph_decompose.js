// Composition lookup table for Byzantine neume glyphs.
//
// Each precomposed glyph maps to:
//   atomicParts[] — the visual components (for OCR detection / display)
//   movement — total step value (from the canonical reference table)
//   quality — style tag
//
// The REVERSE index (BY_PARTS) maps {body, modifiers string} → composedName
// so the resolver can identify a composed form from its detected atomic parts.
//
// Key principle: oligon and petasti are equivalent ascending bodies (+1 step).
// Kentima/ypsili are always attached to an ascending body.
// Step values come from LOOKUP, not arithmetic.

// ─── Movement table (from canonical Byzantine notation reference) ──
// Maps composed glyph name → { direction, steps }.
// Source: Table of Byzantine Notation Symbols (byzantinechant.org) +
// SBMuFL Neanes glyph metadata cross-referenced against the PDF table.

const MOVEMENT_TABLE = Object.freeze({
  // Base bodies
  ison: { direction: 'same', steps: 0 },
  oligon: { direction: 'up', steps: 1 },
  apostrofos: { direction: 'down', steps: 1 },
  yporroi: { direction: 'down', steps: 2 },
  elafron: { direction: 'down', steps: 2 },
  chamili: { direction: 'down', steps: 4 },
  petasti: { direction: 'up', steps: 1 },

  // oligon + kentima
  oligonKentimaMiddle: { direction: 'up', steps: 3 },
  oligonKentimaBelow: { direction: 'up', steps: 3 },
  oligonKentimaAbove: { direction: 'up', steps: 3 },

  // oligon + ypsili
  oligonYpsiliRight: { direction: 'up', steps: 4 },
  oligonYpsiliLeft: { direction: 'up', steps: 5 },

  // oligon + kentima + ypsili
  oligonKentimaYpsiliRight: { direction: 'up', steps: 6 },
  oligonKentimaYpsiliMiddle: { direction: 'up', steps: 7 },

  // oligon + multi-ypsili
  oligonDoubleYpsili: { direction: 'up', steps: 5 },
  oligonKentimataDoubleYpsili: { direction: 'up', steps: 5 },
  oligonKentimaDoubleYpsiliRight: { direction: 'up', steps: 6 },
  oligonKentimaDoubleYpsiliLeft: { direction: 'up', steps: 7 },
  oligonTripleYpsili: { direction: 'up', steps: 6 },
  oligonKentimataTripleYpsili: { direction: 'up', steps: 6 },
  oligonKentimaTripleYpsili: { direction: 'up', steps: 7 },

  // oligon + kentimata
  oligonKentimataBelow: { direction: 'up', steps: 1 },
  oligonKentimataAbove: { direction: 'up', steps: 1 },
  oligonIsonKentimata: { direction: 'same', steps: 0 },
  oligonKentimaMiddleKentimata: { direction: 'up', steps: 3 },

  // oligon + kentimata + ypsili
  oligonYpsiliRightKentimata: { direction: 'up', steps: 4 },
  oligonYpsiliLeftKentimata: { direction: 'up', steps: 5 },

  // oligon + descending
  oligonIson: { direction: 'same', steps: 0 },
  oligonApostrofos: { direction: 'down', steps: 1 },
  oligonYporroi: { direction: 'down', steps: 2 },
  oligonElafron: { direction: 'down', steps: 2 },
  oligonElafronApostrofos: { direction: 'down', steps: 3 },
  oligonChamili: { direction: 'down', steps: 4 },
  isonApostrofos: { direction: 'down', steps: 1 },

  // oligon + kentimata + descending
  oligonApostrofosKentimata: { direction: 'down', steps: 1 },
  oligonYporroiKentimata: { direction: 'down', steps: 2 },
  oligonElafronKentimata: { direction: 'down', steps: 2 },
  oligonRunningElafronKentimata: { direction: 'down', steps: 2 },
  oligonElafronApostrofosKentimata: { direction: 'down', steps: 3 },
  oligonChamiliKentimata: { direction: 'down', steps: 4 },

  // petasti + modifiers
  petastiIson: { direction: 'same', steps: 0 },
  petastiOligon: { direction: 'up', steps: 2 },
  petastiKentima: { direction: 'up', steps: 3 },
  petastiYpsiliRight: { direction: 'up', steps: 4 },
  petastiYpsiliLeft: { direction: 'up', steps: 5 },
  petastiKentimaYpsiliRight: { direction: 'up', steps: 6 },
  petastiKentimaYpsiliMiddle: { direction: 'up', steps: 7 },
  petastiDoubleYpsili: { direction: 'up', steps: 5 },
  petastiKentimataDoubleYpsili: { direction: 'up', steps: 5 },
  petastiKentimaDoubleYpsiliRight: { direction: 'up', steps: 6 },
  petastiKentimaDoubleYpsiliLeft: { direction: 'up', steps: 7 },
  petastiTripleYpsili: { direction: 'up', steps: 6 },
  petastiKentimataTripleYpsili: { direction: 'up', steps: 6 },
  petastiKentimaTripleYpsili: { direction: 'up', steps: 7 },

  // petasti + descending
  petastiApostrofos: { direction: 'down', steps: 1 },
  petastiYporroi: { direction: 'down', steps: 2 },
  petastiElafron: { direction: 'down', steps: 2 },
  petastiRunningElafron: { direction: 'down', steps: 2 },
  petastiElafronApostrofos: { direction: 'down', steps: 3 },
  petastiChamili: { direction: 'down', steps: 4 },
  petastiChamiliApostrofos: { direction: 'down', steps: 5 },
  petastiChamiliElafron: { direction: 'down', steps: 6 },
  petastiChamiliElafronApostrofos: { direction: 'down', steps: 7 },
  petastiDoubleChamili: { direction: 'down', steps: 8 },
  petastiDoubleChamiliApostrofos: { direction: 'down', steps: 9 },

  // standalone kentima / kentimata
  kentima: { direction: 'up', steps: 2 },
  kentimata: { direction: 'up', steps: 1 },

  // apostrofos + syndesmos
  apostrofosSyndesmos: { direction: 'down', steps: 1 },
});

// Quality tags per composed name
const QUALITY_TABLE = Object.freeze({
  oligonKentimaMiddle: 'kentima',
  oligonKentimaBelow: 'kentima',
  oligonKentimaAbove: 'kentima',
  oligonYpsiliRight: 'ypsili',
  oligonYpsiliLeft: 'ypsili',
  oligonKentimaYpsiliRight: 'kentima-ypsili',
  oligonKentimaYpsiliMiddle: 'kentima-ypsili',
  oligonDoubleYpsili: 'double-ypsili',
  oligonKentimataDoubleYpsili: 'kentimata-double-ypsili',
  oligonKentimaDoubleYpsiliRight: 'kentima-double-ypsili',
  oligonKentimaDoubleYpsiliLeft: 'kentima-double-ypsili',
  oligonTripleYpsili: 'triple-ypsili',
  oligonKentimataTripleYpsili: 'kentimata-triple-ypsili',
  oligonKentimaTripleYpsili: 'kentima-triple-ypsili',
  oligonKentimataBelow: 'kentimata',
  oligonKentimataAbove: 'kentimata',
  oligonIsonKentimata: 'kentimata',
  oligonKentimaMiddleKentimata: 'kentima-kentimata',
  oligonYpsiliRightKentimata: 'kentimata-ypsili',
  oligonYpsiliLeftKentimata: 'kentimata-ypsili',
  oligonIson: 'oligon-support',
  oligonApostrofos: 'oligon-support',
  oligonYporroi: 'oligon-support',
  oligonElafron: 'oligon-support',
  oligonElafronApostrofos: 'oligon-support',
  oligonChamili: 'oligon-support',
  isonApostrofos: 'ison-support',
  oligonApostrofosKentimata: 'kentimata',
  oligonYporroiKentimata: 'kentimata',
  oligonElafronKentimata: 'kentimata',
  oligonRunningElafronKentimata: 'kentimata-running-elafron',
  oligonElafronApostrofosKentimata: 'kentimata',
  oligonChamiliKentimata: 'kentimata',
  petastiIson: 'petasti',
  petastiOligon: 'petasti',
  petastiKentima: 'petasti-kentima',
  petastiYpsiliRight: 'petasti-ypsili',
  petastiYpsiliLeft: 'petasti-ypsili',
  petastiKentimaYpsiliRight: 'petasti-kentima-ypsili',
  petastiKentimaYpsiliMiddle: 'petasti-kentima-ypsili',
  petastiDoubleYpsili: 'petasti-double-ypsili',
  petastiKentimataDoubleYpsili: 'petasti-kentimata-double-ypsili',
  petastiKentimaDoubleYpsiliRight: 'petasti-kentima-double-ypsili',
  petastiKentimaDoubleYpsiliLeft: 'petasti-kentima-double-ypsili',
  petastiTripleYpsili: 'petasti-triple-ypsili',
  petastiKentimataTripleYpsili: 'petasti-kentimata-triple-ypsili',
  petastiKentimaTripleYpsili: 'petasti-kentima-triple-ypsili',
  petastiApostrofos: 'petasti',
  petastiYporroi: 'petasti',
  petastiElafron: 'petasti',
  petastiRunningElafron: 'petasti-running-elafron',
  petastiElafronApostrofos: 'petasti',
  petastiChamili: 'petasti',
  petastiChamiliApostrofos: 'petasti',
  petastiChamiliElafron: 'petasti',
  petastiChamiliElafronApostrofos: 'petasti',
  petastiDoubleChamili: 'petasti',
  petastiDoubleChamiliApostrofos: 'petasti',
  kentima: 'kentima',
  kentimata: 'kentimata',
});

// ─── Composition entries ───────────────────────────────────────────

const COMPOSITIONS = {
  // ── oligon + kentima (all positions = same step value) ──
  oligonKentimaMiddle: {
    body: 'oligon',
    parts: ['oligon', 'kentima'],
    slot: 'above-body',
  },
  oligonKentimaBelow: {
    body: 'oligon',
    parts: ['oligon', 'kentima'],
    slot: 'below-body',
  },
  oligonKentimaAbove: {
    body: 'oligon',
    parts: ['oligon', 'kentima'],
    slot: 'above-body',
  },

  // ── oligon + ypsili ──
  oligonYpsiliRight: {
    body: 'oligon',
    parts: ['oligon', 'ypsili'],
    slot: 'right-body',
  },
  oligonYpsiliLeft: {
    body: 'oligon',
    parts: ['oligon', 'ypsili'],
    slot: 'left-body',
  },

  // ── oligon + kentima + ypsili ──
  oligonKentimaYpsiliRight: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'ypsili'],
    slot: 'right-body',
  },
  oligonKentimaYpsiliMiddle: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'ypsili'],
    slot: 'left-body',
  },

  // ── oligon + multi-ypsili ──
  oligonDoubleYpsili: {
    body: 'oligon',
    parts: ['oligon', 'ypsili', 'ypsili'],
  },
  oligonKentimataDoubleYpsili: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'ypsili', 'ypsili'],
  },
  oligonKentimaDoubleYpsiliRight: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'ypsili', 'ypsili'],
  },
  oligonKentimaDoubleYpsiliLeft: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'ypsili', 'ypsili'],
  },
  oligonTripleYpsili: {
    body: 'oligon',
    parts: ['oligon', 'ypsili', 'ypsili', 'ypsili'],
  },
  oligonKentimataTripleYpsili: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'ypsili', 'ypsili', 'ypsili'],
  },
  oligonKentimaTripleYpsili: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'ypsili', 'ypsili', 'ypsili'],
  },

  // ── oligon + kentimata (kentimata adds no steps compared to plain oligon) ──
  oligonKentimataBelow: {
    body: 'oligon',
    parts: ['oligon', 'kentimata'],
  },
  oligonKentimataAbove: {
    body: 'oligon',
    parts: ['oligon', 'kentimata'],
  },
  oligonIsonKentimata: {
    body: 'oligon',
    parts: ['oligon', 'ison', 'kentimata'],
  },
  oligonKentimaMiddleKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentima', 'kentimata'],
  },

  // ── oligon + kentimata + ypsili ──
  oligonYpsiliRightKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'ypsili'],
  },
  oligonYpsiliLeftKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'ypsili'],
  },

  // ── oligon + descending support ──
  oligonIson: {
    body: 'oligon',
    parts: ['oligon', 'ison'],
  },
  oligonApostrofos: {
    body: 'oligon',
    parts: ['oligon', 'apostrofos'],
  },
  oligonYporroi: {
    body: 'oligon',
    parts: ['oligon', 'yporroi'],
  },
  oligonElafron: {
    body: 'oligon',
    parts: ['oligon', 'elafron'],
  },
  oligonElafronApostrofos: {
    body: 'oligon',
    parts: ['oligon', 'elafron', 'apostrofos'],
  },
  oligonChamili: {
    body: 'oligon',
    parts: ['oligon', 'chamili'],
  },
  isonApostrofos: {
    body: 'ison',
    parts: ['ison', 'apostrofos'],
  },

  // ── oligon + kentimata + descending ──
  oligonApostrofosKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'apostrofos'],
  },
  oligonYporroiKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'yporroi'],
  },
  oligonElafronKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'elafron'],
  },
  oligonRunningElafronKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'elafron'],  // runningElafron ≈ elafron for step count
  },
  oligonElafronApostrofosKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'elafron', 'apostrofos'],
  },
  oligonChamiliKentimata: {
    body: 'oligon',
    parts: ['oligon', 'kentimata', 'chamili'],
  },

  // ── petasti + modifiers (same step values as oligon equivalents) ──
  petastiIson: {
    body: 'petasti',
    parts: ['petasti', 'ison'],
  },
  petastiOligon: {
    body: 'petasti',
    parts: ['petasti', 'oligon'],
  },
  petastiKentima: {
    body: 'petasti',
    parts: ['petasti', 'kentima'],
  },
  petastiYpsiliRight: {
    body: 'petasti',
    parts: ['petasti', 'ypsili'],
  },
  petastiYpsiliLeft: {
    body: 'petasti',
    parts: ['petasti', 'ypsili'],
  },
  petastiKentimaYpsiliRight: {
    body: 'petasti',
    parts: ['petasti', 'kentima', 'ypsili'],
  },
  petastiKentimaYpsiliMiddle: {
    body: 'petasti',
    parts: ['petasti', 'kentima', 'ypsili'],
  },
  petastiDoubleYpsili: {
    body: 'petasti',
    parts: ['petasti', 'ypsili', 'ypsili'],
  },
  petastiKentimataDoubleYpsili: {
    body: 'petasti',
    parts: ['petasti', 'kentimata', 'ypsili', 'ypsili'],
  },
  petastiKentimaDoubleYpsiliRight: {
    body: 'petasti',
    parts: ['petasti', 'kentima', 'ypsili', 'ypsili'],
  },
  petastiKentimaDoubleYpsiliLeft: {
    body: 'petasti',
    parts: ['petasti', 'kentima', 'ypsili', 'ypsili'],
  },
  petastiTripleYpsili: {
    body: 'petasti',
    parts: ['petasti', 'ypsili', 'ypsili', 'ypsili'],
  },
  petastiKentimataTripleYpsili: {
    body: 'petasti',
    parts: ['petasti', 'kentimata', 'ypsili', 'ypsili', 'ypsili'],
  },
  petastiKentimaTripleYpsili: {
    body: 'petasti',
    parts: ['petasti', 'kentima', 'ypsili', 'ypsili', 'ypsili'],
  },

  // ── petasti + descending ──
  petastiApostrofos: {
    body: 'petasti',
    parts: ['petasti', 'apostrofos'],
  },
  petastiYporroi: {
    body: 'petasti',
    parts: ['petasti', 'yporroi'],
  },
  petastiElafron: {
    body: 'petasti',
    parts: ['petasti', 'elafron'],
  },
  petastiRunningElafron: {
    body: 'petasti',
    parts: ['petasti', 'elafron'],
  },
  petastiElafronApostrofos: {
    body: 'petasti',
    parts: ['petasti', 'elafron', 'apostrofos'],
  },
  petastiChamili: {
    body: 'petasti',
    parts: ['petasti', 'chamili'],
  },
  petastiChamiliApostrofos: {
    body: 'petasti',
    parts: ['petasti', 'chamili', 'apostrofos'],
  },
  petastiChamiliElafron: {
    body: 'petasti',
    parts: ['petasti', 'chamili', 'elafron'],
  },
  petastiChamiliElafronApostrofos: {
    body: 'petasti',
    parts: ['petasti', 'chamili', 'elafron', 'apostrofos'],
  },
  petastiDoubleChamili: {
    body: 'petasti',
    parts: ['petasti', 'chamili', 'chamili'],
  },
  petastiDoubleChamiliApostrofos: {
    body: 'petasti',
    parts: ['petasti', 'chamili', 'chamili', 'apostrofos'],
  },

  // ── apostrofos + syndesmos ──
  apostrofosSyndesmos: {
    body: 'apostrofos',
    parts: ['apostrofos', 'syndesmos'],
  },
};

// ─── Derived lookup tables ─────────────────────────────────────────

// composedName → { body, parts[], slot?, movement, quality }
export const COMPOSITION_LOOKUP = Object.freeze(
  Object.fromEntries(
    Object.entries(COMPOSITIONS).map(([name, entry]) => [
      name,
      Object.freeze({
        body: entry.body,
        parts: Object.freeze([...entry.parts]),
        slot: entry.slot ?? null,
        movement: MOVEMENT_TABLE[name] ? { ...MOVEMENT_TABLE[name] } : null,
        quality: QUALITY_TABLE[name] ?? null,
      }),
    ])
  )
);

// Reverse: partsSignature → composedName
// A partsSignature is a sorted, unique set of glyph names joined by '+'.
// For ambiguous cases (oligon+kentima maps to 3 variants), returns the first match.
export const COMPOSITION_BY_PARTS = Object.freeze(
  (() => {
    const map = new Map();
    for (const [name, entry] of Object.entries(COMPOSITION_LOOKUP)) {
      const sig = [...new Set(entry.parts)].sort().join('+');
      if (!map.has(sig)) map.set(sig, name);
    }
    return map;
  })()
);

// ─── Public API ────────────────────────────────────────────────────

// Given a composed glyph name, return its atomic parts. e.g. "oligonKentimaYpsiliRight" → ['oligon', 'kentima', 'ypsili']
export function atomicPartsForComposed(name) {
  const entry = COMPOSITION_LOOKUP[name];
  return entry ? [...entry.parts] : null;
}

// Given a set of atomic glyph names (e.g. from OCR), return the best composed name match.
// Returns null if no match found.
export function composedNameFromParts(glyphNames) {
  const sig = [...new Set(glyphNames)].sort().join('+');
  return COMPOSITION_BY_PARTS.get(sig) ?? null;
}

// Look up the movement for a composed glyph name. Returns null if unknown.
export function movementForComposedName(name) {
  const entry = COMPOSITION_LOOKUP[name];
  if (entry?.movement) return { ...entry.movement };
  return null;
}

// Look up the quality tag for a composed glyph name. Returns null if none.
export function qualityForComposedName(name) {
  return COMPOSITION_LOOKUP[name]?.quality ?? null;
}

// Given atomic glyph names from OCR, look up the total movement.
// Returns null if the combination is unknown.
export function movementFromAtomicParts(glyphNames) {
  const composed = composedNameFromParts(glyphNames);
  if (!composed) return null;
  return movementForComposedName(composed);
}

// Decompose a precomposed quantity token into atomic parts (for OCR round-trip display).
// Returns an array of token descriptors. The CALLER creates the actual semantic tokens.
export function decomposeToAtomicParts(composedName) {
  const entry = COMPOSITION_LOOKUP[composedName];
  if (!entry) return null;
  return entry.parts.map((glyphName, index) => ({
    glyphName,
    kind: index === 0 ? 'quantity' : 'ornamental',
    slot: index === 0 ? 'main' : (entry.slot ?? 'above-body'),
  }));
}
