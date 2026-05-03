// Decomposition table: maps precomposed glyph names to their atomic components.
// Each atomic has a glyphName, kind, slot, and optional stepContribution.
//
// The base body sets movement direction; stepContributions from ornamentals add to it.
// When the same glyph appears standalone (e.g. kentima alone), the compiler treats
// it as a self-anchored neume with its own full movement.

export const GLYPH_DECOMPOSITION = Object.freeze({
  // ── oligon + kentima ──
  oligonKentimaMiddle: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
  ],
  oligonKentimaBelow: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'below-body', stepContribution: 2 },
  ],
  oligonKentimaAbove: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
  ],

  // ── oligon + ypsili ──
  oligonYpsiliRight: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  oligonYpsiliLeft: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],

  // ── oligon + kentima + ypsili ──
  oligonKentimaYpsiliRight: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  oligonKentimaYpsiliMiddle: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],

  // ── oligon + multi-ypsili ──
  oligonDoubleYpsili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],
  oligonKentimataDoubleYpsili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],
  oligonKentimaDoubleYpsiliRight: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  oligonKentimaDoubleYpsiliLeft: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],
  oligonTripleYpsili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body-2', stepContribution: 1 },
  ],
  oligonKentimataTripleYpsili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body-2', stepContribution: 1 },
  ],
  oligonKentimaTripleYpsili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],

  // ── oligon + kentimata (no extra steps) ──
  oligonKentimataBelow: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
  ],
  oligonKentimataAbove: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'above-body', stepContribution: 0 },
  ],
  oligonIsonKentimata: [
    { glyphName: 'oligonIson', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
  ],
  oligonKentimaMiddleKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
  ],

  // ── oligon + kentimata + ypsili ──
  oligonYpsiliRightKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  oligonYpsiliLeftKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],

  // ── oligon support (descending) ──
  oligonIson: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'ison', kind: 'ornamental-step', slot: 'support', stepContribution: -1 },
  ],
  oligonApostrofos: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body', stepContribution: -2 },
  ],
  oligonYporroi: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'yporroi', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
  ],
  oligonElafron: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
  ],
  oligonElafronApostrofos: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -1 },
  ],
  oligonChamili: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
  ],
  isonApostrofos: [
    { glyphName: 'ison', kind: 'quantity', slot: 'main' },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body', stepContribution: -1 },
  ],

  // ── oligon + kentimata + descending support ──
  oligonApostrofosKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -2 },
  ],
  oligonYporroiKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'yporroi', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
  ],
  oligonElafronKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
  ],
  oligonRunningElafronKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'runningElafron', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
  ],
  oligonElafronApostrofosKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-3', stepContribution: -1 },
  ],
  oligonChamiliKentimata: [
    { glyphName: 'oligon', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -5 },
  ],

  // ── petasti + modifier variants ──
  petastiIson: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'ison', kind: 'ornamental-step', slot: 'support', stepContribution: -1 },
  ],
  petastiOligon: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'oligon', kind: 'ornamental-step', slot: 'support', stepContribution: 1 },
  ],
  petastiKentima: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
  ],
  petastiYpsiliRight: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  petastiYpsiliLeft: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],
  petastiKentimaYpsiliRight: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  petastiKentimaYpsiliMiddle: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],
  petastiDoubleYpsili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],
  petastiKentimataDoubleYpsili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],
  petastiKentimaDoubleYpsiliRight: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
  ],
  petastiKentimaDoubleYpsiliLeft: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 4 },
  ],
  petastiTripleYpsili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body-2', stepContribution: 1 },
  ],
  petastiKentimataTripleYpsili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentimata', kind: 'ornamental-step', slot: 'below-body', stepContribution: 0 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body-2', stepContribution: 1 },
  ],
  petastiKentimaTripleYpsili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'kentima', kind: 'ornamental-step', slot: 'above-body', stepContribution: 2 },
    { glyphName: 'ypsiliRight', kind: 'ornamental-step', slot: 'right-body', stepContribution: 3 },
    { glyphName: 'ypsiliLeft', kind: 'ornamental-step', slot: 'left-body', stepContribution: 1 },
  ],

  // ── petasti + descending ──
  petastiApostrofos: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body', stepContribution: -2 },
  ],
  petastiYporroi: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'yporroi', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
  ],
  petastiElafron: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
  ],
  petastiRunningElafron: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'runningElafron', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
  ],
  petastiElafronApostrofos: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body', stepContribution: -3 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -1 },
  ],
  petastiChamili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
  ],
  petastiChamiliApostrofos: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -1 },
  ],
  petastiChamiliElafron: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
  ],
  petastiChamiliElafronApostrofos: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
    { glyphName: 'elafron', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -3 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-3', stepContribution: -1 },
  ],
  petastiDoubleChamili: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -4 },
  ],
  petastiDoubleChamiliApostrofos: [
    { glyphName: 'petasti', kind: 'quantity', slot: 'main' },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body', stepContribution: -5 },
    { glyphName: 'chamili', kind: 'ornamental-step', slot: 'below-body-2', stepContribution: -4 },
    { glyphName: 'apostrofos', kind: 'ornamental-step', slot: 'below-body-3', stepContribution: -1 },
  ],

  // ── standalone kentima / kentimata (self-anchored when no body present) ──
  // Handled by the compiler: if an ornamental-step has no quantity in group, it becomes the anchor.
  // No decomposition needed for these — they're already atomic.

  // ── apostrofos + syndesmos ──
  apostrofosSyndesmos: [
    { glyphName: 'apostrofos', kind: 'quantity', slot: 'main' },
    { glyphName: 'syndesmos', kind: 'ornamental', slot: 'below-body' },
  ],
});

// Glyph names that are "atomic" building blocks referenced by decompositions.
// These need to exist in GLYPH_METADATA with proper standalone behavior.
export const ATOMIC_ORNAMENTAL_STEP_NAMES = Object.freeze(new Set([
  'kentima',
  'kentimata',
  'ypsiliRight',
  'ypsiliLeft',
]));

// Expand a precomposed semantic token into its atomic parts.
// Returns an array — at minimum the original token, or the atomic parts if decomposable.
// After expansion, callers should re-run the resolver to group atomics correctly.
export function decomposeSemanticToken(token) {
  if (!token || token.kind !== 'quantity') return [token];
  const glyphName = token.value?.glyphName ?? token.source?.[0]?.glyphName;
  if (!glyphName) return [token];
  const recipe = GLYPH_DECOMPOSITION[glyphName];
  if (!recipe) return [token];

  // Compute the base body's own movement: total minus step contributions.
  const signedTotal = signedMovementSteps(token.value.movement);
  const stepSum = recipe
    .filter(part => part.kind === 'ornamental-step')
    .reduce((sum, part) => sum + (part.stepContribution ?? 0), 0);
  const baseSigned = signedTotal - stepSum;
  const baseMovement = movementFromSigned(baseSigned);

  const parts = [];
  for (const part of recipe) {
    const sourceToken = { ...(token.source[0] ?? {}), glyphName: part.glyphName };
    if (part.kind === 'quantity') {
      parts.push({
        kind: 'quantity',
        value: {
          glyphName: part.glyphName,
          movement: baseMovement,
          ...(token.value.quality ? { quality: token.value.quality } : {}),
        },
        source: [{ ...sourceToken, _slot: part.slot }],
      });
    } else if (part.kind === 'ornamental-step') {
      parts.push({
        kind: 'ornamental-step',
        value: {
          glyphName: part.glyphName,
          stepContribution: part.stepContribution ?? 0,
          slot: part.slot,
        },
        source: [{ ...sourceToken, _slot: part.slot }],
      });
    } else if (part.kind === 'ornamental') {
      parts.push({
        kind: 'ornamental',
        value: {
          glyphName: part.glyphName,
          name: part.glyphName,
        },
        source: [{ ...sourceToken, _slot: part.slot }],
      });
    }
  }
  return parts;
}

export function decomposeSemanticTokens(tokens) {
  return tokens.flatMap(token => decomposeSemanticToken(token));
}

function signedMovementSteps(movement) {
  if (!movement) return 0;
  const steps = movement.steps ?? 0;
  if (movement.direction === 'up') return steps;
  if (movement.direction === 'down') return -steps;
  return 0;
}

function movementFromSigned(value) {
  if (value > 0) return { direction: 'up', steps: value };
  if (value < 0) return { direction: 'down', steps: Math.abs(value) };
  return { direction: 'same', steps: 0 };
}
