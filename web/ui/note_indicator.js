// NoteIndicator — bottom-center sung-note feedback with martyria rendering.

const DEGREE_INDEX = { Ni: 0, Pa: 1, Vou: 2, Ga: 3, Di: 4, Ke: 5, Zo: 6 };
const SOLFEGE = {
  Ni: 'do',
  Pa: 're',
  Vou: 'mi',
  Ga: 'fa',
  Di: 'so',
  Ke: 'la',
  Zo: 'ti',
};

const CP = {
  NOTE_LOW: {
    Zo: 0xe130,
    Ni: 0xe131,
    Pa: 0xe132,
    Vou: 0xe133,
    Ga: 0xe134,
    Di: 0xe135,
    Ke: 0xe136,
  },
  NOTE: {
    Zo: 0xe137,
    Ni: 0xe138,
    Pa: 0xe139,
    Vou: 0xe13a,
    Ga: 0xe13b,
    Di: 0xe13c,
    Ke: 0xe13d,
  },
  NOTE_HIGH: {
    Zo: 0xe13e,
    Ni: 0xe13f,
    Pa: 0xe140,
    Vou: 0xe141,
    Ga: 0xe142,
    Di: 0xe143,
    Ke: 0xe144,
  },
  DELTA: 0xe151,
  ALPHA: 0xe152,
  LEGETOS: 0xe153,
  NANA: 0xe154,
  DELTA_DOTTED: 0xe155,
  ALPHA_DOTTED: 0xe156,
  HARD_PA: 0xe157,
  HARD_DI: 0xe158,
  SOFT_DI: 0xe159,
  SOFT_KE: 0xe15a,
  ZYGOS: 0xe15b,
  CHROA_SPATHI: 0xe1cf,
};

const DIATONIC_BELOW = {
  Ni: CP.DELTA,
  Pa: CP.ALPHA,
  Vou: CP.LEGETOS,
  Ga: CP.NANA,
  Di: CP.DELTA_DOTTED,
  Ke: CP.ALPHA_DOTTED,
  Zo: CP.LEGETOS,
};

const HIDDEN_CLASSES = ['grade-perfect', 'grade-close', 'grade-work', 'grade-wide'];

// Neanes note-name glyphs have generous right side bearings. These offsets
// center the visible outline over the zero-width martyria-below glyphs.
const NOTE_VISUAL_DX_EM = {
  0xe130: -0.160, 0xe131: -0.143, 0xe132: -0.147, 0xe133: -0.120,
  0xe134: -0.164, 0xe135: -0.163, 0xe136: -0.208,
  0xe137: -0.160, 0xe138: -0.143, 0xe139: -0.147, 0xe13a: -0.120,
  0xe13b: -0.164, 0xe13c: -0.163, 0xe13d: -0.158,
  0xe13e: -0.167, 0xe13f: -0.186, 0xe140: -0.169, 0xe141: -0.169,
  0xe142: -0.169, 0xe143: -0.169, 0xe144: -0.181,
};

const REGISTER_LAYOUT = {
  NOTE_LOW:  { noteTop: '-8px', belowTop: '31px' },
  NOTE:      { noteTop: '-4px', belowTop: '29px' },
  NOTE_HIGH: { noteTop:  '4px', belowTop: '25px' },
};

function glyph(codepoint) {
  return String.fromCodePoint(codepoint);
}

function posMod(n, d) {
  return ((n % d) + d) % d;
}

function eventKind(event) {
  return event?.kind ?? {};
}

function chroaPatch(event) {
  return eventKind(event).ChroaPatch ?? null;
}

function nearestDegreeCell(cells, degree, moria) {
  return cells
    .filter(cell => cell.degree === degree)
    .reduce((best, cell) => {
      if (!best) return cell;
      return Math.abs(cell.moria - moria) < Math.abs(best.moria - moria) ? cell : best;
    }, null);
}

function makeRegionEventMap(gridState) {
  const byId = new Map();
  for (const event of gridState?.events ?? []) byId.set(event.id, event);
  return byId;
}

function makeLinearIndexMap(cells) {
  const degreeCells = cells
    .filter(cell => cell.degree !== null)
    .slice()
    .sort((a, b) => a.moria - b.moria);
  const map = new Map();
  if (!degreeCells.length) return map;

  let refPos = degreeCells.findIndex(cell => cell.degree === 'Ni' && cell.moria >= 0);
  if (refPos < 0) {
    refPos = degreeCells.reduce((bestIdx, cell, idx) => {
      const best = degreeCells[bestIdx];
      return Math.abs(cell.moria) < Math.abs(best.moria) ? idx : bestIdx;
    }, 0);
  }

  const refDegreeIdx = DEGREE_INDEX[degreeCells[refPos].degree] ?? 0;
  for (let i = 0; i < degreeCells.length; i++) {
    const cell = degreeCells[i];
    map.set(cell.moria, i - refPos + refDegreeIdx);
  }
  return map;
}

function registerForLinearIndex(linearIndex) {
  if (!Number.isFinite(linearIndex)) return 'NOTE';
  // The central martyria octave is Zo-below-Ni through Ke.
  if (linearIndex < -1) return 'NOTE_LOW';
  if (linearIndex >= 6) return 'NOTE_HIGH';
  return 'NOTE';
}

function noteCodepointFor(cell, linearIndex) {
  const family = CP[registerForLinearIndex(linearIndex)];
  const codepoint = family?.[cell.degree] ?? CP.NOTE[cell.degree];
  return codepoint ?? null;
}

function solfegeFor(cell, linearIndex) {
  const base = SOLFEGE[cell.degree] ?? cell.degree ?? '';
  if (linearIndex >= 7 && cell.degree === 'Ni') return `${base}'`;
  if (linearIndex < 0 && cell.degree === 'Ni') return `${base},`;
  return base;
}

function baseDiatonicBelow(cell) {
  return DIATONIC_BELOW[cell.degree] ?? CP.DELTA;
}

function oppositeChromatic(codepoint, genus) {
  if (genus === 'SoftChromatic') return codepoint === CP.SOFT_DI ? CP.SOFT_KE : CP.SOFT_DI;
  return codepoint === CP.HARD_PA ? CP.HARD_DI : CP.HARD_PA;
}

function anchorVariantForChromatic(genus, anchorLinearIndex) {
  if (genus === 'SoftChromatic') {
    // Soft chromatic repeats by fifth from Ni: Ni, Di, upper Pa, ...
    return posMod(anchorLinearIndex, 4) === 0 ? CP.SOFT_DI : CP.SOFT_KE;
  }
  // Hard chromatic repeats by fifth from Pa: Pa, Ke, upper Vou, ...
  return posMod(anchorLinearIndex - 1, 4) === 0 ? CP.HARD_PA : CP.HARD_DI;
}

function baseChromaticBelow(cell, context, genus) {
  const anchorLinear = context.linearIndexForMoria(context.region?.anchor_moria)
    ?? context.linearIndexForCell(nearestDegreeCell(context.cells, context.region?.anchor_degree, context.region?.anchor_moria))
    ?? 0;
  const cellLinear = context.linearIndexForCell(cell);
  const anchorVariant = anchorVariantForChromatic(genus, anchorLinear);
  if (!Number.isFinite(cellLinear)) return anchorVariant;
  return posMod(cellLinear - anchorLinear, 4) === 0
    ? anchorVariant
    : oppositeChromatic(anchorVariant, genus);
}

function baseBelowFor(cell, context) {
  const genus = context.region?.genus;
  if (genus === 'SoftChromatic' || genus === 'HardChromatic') {
    return baseChromaticBelow(cell, context, genus);
  }
  return baseDiatonicBelow(cell);
}

function chroaAnchorLinear(event, context) {
  const exact = context.linearIndexForMoria(event.resolved_anchor_moria);
  if (Number.isFinite(exact)) return exact;
  const anchorCell = nearestDegreeCell(
    context.cells,
    event.resolved_anchor_degree,
    event.resolved_anchor_moria,
  );
  return context.linearIndexForCell(anchorCell);
}

function applyChroaBelow(cell, below, context) {
  const cellLinear = context.linearIndexForCell(cell);
  if (!Number.isFinite(cellLinear)) return below;

  for (const event of context.chroaEvents) {
    const patch = chroaPatch(event);
    const symbol = patch?.symbol;
    if (!symbol) continue;

    const anchorLinear = chroaAnchorLinear(event, context);
    const rel = Number.isFinite(anchorLinear) ? cellLinear - anchorLinear : null;

    if (symbol === 'Spathi') {
      if (rel === 0) return CP.CHROA_SPATHI;
      if (rel === 1) return CP.HARD_DI;
      if (rel === -1) return CP.HARD_PA;
    } else if (symbol === 'Kliton') {
      if (rel === 0) return CP.NANA;
      if (rel === -1) return CP.LEGETOS;
      if (rel === -2) return CP.ALPHA;
      if (rel === -3) return CP.DELTA;
    } else if (symbol === 'Zygos') {
      if (cell.degree === 'Di' || cell.degree === 'Vou') return CP.ZYGOS;
      if (cell.degree === 'Pa' || cell.degree === 'Ga') return CP.HARD_PA;
    }
  }

  return below;
}

function correctionGrade(absMoria) {
  if (absMoria <= 0.5) return { className: 'grade-perfect', label: 'Locked' };
  if (absMoria <= 1.5) return { className: 'grade-close', label: 'Close' };
  if (absMoria <= 3.5) return { className: 'grade-work', label: 'Adjust' };
  return { className: 'grade-wide', label: 'Reach' };
}

function nearestOctaveMoriaDelta(delta) {
  if (!Number.isFinite(delta)) return delta;
  while (delta > 36) delta -= 72;
  while (delta < -36) delta += 72;
  return delta;
}

export class NoteIndicator {
  constructor(container) {
    this.el = container;
    this._cells = [];
    this._gridState = null;
    this._eventsById = new Map();
    this._linearIndexByMoria = new Map();

    this._martyriaEl = container.querySelector('.note-indicator-martyria');
    this._noteGlyphEl = container.querySelector('.note-indicator-note-glyph');
    this._belowGlyphEl = container.querySelector('.note-indicator-below-glyph');
    this._westernEl = container.querySelector('.note-indicator-western');
    this._nameEl = container.querySelector('.note-indicator-name');
    this._scoreEl = container.querySelector('.note-indicator-score');
    this._offsetEl = container.querySelector('.note-indicator-offset');
    this._cursorEl = container.querySelector('.note-indicator-cursor');
  }

  refresh(cells, gridState) {
    this._cells = cells ?? [];
    this._gridState = gridState ?? null;
    this._eventsById = makeRegionEventMap(gridState);
    this._linearIndexByMoria = makeLinearIndexMap(this._cells);
  }

  clear() {
    this.el.classList.add('hidden');
  }

  showPitch(msg) {
    if (!msg?.gate_open || !Number.isFinite(msg.cell_id)) {
      this.clear();
      return;
    }

    const cell = this._cells.find(candidate => candidate.moria === msg.cell_id);
    if (!cell || cell.degree === null) {
      this.clear();
      return;
    }

    const context = this._contextForCell(cell);
    const target = cell.moria + (cell.accidental ?? 0);
    const rawMoria = Number.isFinite(msg.raw_moria) ? msg.raw_moria : target;
    const errorMoria = nearestOctaveMoriaDelta(rawMoria - target);
    this._paint(cell, context, errorMoria);
  }

  _contextForCell(cell) {
    const region = this._gridState?.regions?.[cell.region_idx] ?? null;
    const activeIds = region?.active_rules ?? [];
    const chroaEvents = activeIds
      .map(id => this._eventsById.get(id))
      .filter(event => chroaPatch(event));

    return {
      cells: this._cells,
      region,
      chroaEvents,
      linearIndexForMoria: moria => this._linearIndexByMoria.get(moria),
      linearIndexForCell: c => c ? this._linearIndexByMoria.get(c.moria) : null,
    };
  }

  _paint(cell, context, errorMoria) {
    const linearIndex = context.linearIndexForCell(cell);
    const genus = context.region?.genus;
    const absMoria = Math.abs(errorMoria);
    const grade = correctionGrade(absMoria);
    const direction = errorMoria > 0.2 ? 'Lower' : errorMoria < -0.2 ? 'Lift' : 'Hold';
    const offsetLabel = `${errorMoria >= 0 ? '+' : ''}${errorMoria.toFixed(1)} m`;
    const cursor = Math.max(-1, Math.min(1, errorMoria / 6));

    this.el.classList.remove('hidden', ...HIDDEN_CLASSES);
    this.el.classList.add(grade.className);
    this._nameEl.textContent = cell.degree;
    this._scoreEl.textContent = grade.label;
    this._offsetEl.textContent = `${direction} ${offsetLabel}`;
    this._cursorEl.style.left = `${50 + cursor * 48}%`;

    if (genus === 'Western') {
      this._martyriaEl.classList.add('western-mode');
      this._westernEl.textContent = solfegeFor(cell, linearIndex);
      this._noteGlyphEl.textContent = '';
      this._belowGlyphEl.textContent = '';
      return;
    }

    const register = registerForLinearIndex(linearIndex);
    const noteCodepoint = noteCodepointFor(cell, linearIndex);
    const below = applyChroaBelow(cell, baseBelowFor(cell, context), context);
    const layout = REGISTER_LAYOUT[register] ?? REGISTER_LAYOUT.NOTE;

    this._martyriaEl.classList.remove('western-mode');
    this._martyriaEl.dataset.register = register;
    this._westernEl.textContent = '';
    this._noteGlyphEl.textContent = noteCodepoint ? glyph(noteCodepoint) : '';
    this._belowGlyphEl.textContent = glyph(below);
    this._noteGlyphEl.style.setProperty('--glyph-dx', `${NOTE_VISUAL_DX_EM[noteCodepoint] ?? 0}em`);
    this._noteGlyphEl.style.setProperty('--glyph-top', layout.noteTop);
    this._belowGlyphEl.style.setProperty('--glyph-dx', '0em');
    this._belowGlyphEl.style.setProperty('--glyph-top', layout.belowTop);
  }
}
