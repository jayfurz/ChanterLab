import {
  referenceMoriaForDegree,
} from './chant_score.js';
import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

const TUNING_MATCH_TOLERANCE_MORIA = 0.001;

export function retuneCompiledScoreWithGrid(compiled, options = {}) {
  const diagnostics = [...(compiled?.diagnostics ?? [])];
  const grid = options.grid ?? options.createGrid?.();
  if (!grid) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.WARNING,
      code: 'score-tuning-grid-missing',
      message: 'No tuning grid was provided; using compiler symbolic moria targets.',
    });
    return { ...compiled, diagnostics };
  }

  if (Number.isFinite(options.refNiHz) && 'refNiHz' in grid) {
    grid.refNiHz = options.refNiHz;
  }

  const initialDrop = compiled?.initialTuning ?? scoreInitialPthoraDrop(compiled?.score);
  if (initialDrop) applyPthoraDrop(grid, initialDrop, diagnostics);

  const timeline = Array.isArray(compiled?.timeline) ? compiled.timeline : [];
  const retunedTimeline = [];
  const retunedNotes = [];
  const retunedPthoraEvents = [];
  const retunedCheckpoints = [];
  const retunedIsonEvents = [];

  for (const event of timeline) {
    if (event?.type === 'pthora') {
      applyPthoraDrop(grid, event, diagnostics);
      const marker = { ...event, applied: true };
      retunedTimeline.push(marker);
      retunedPthoraEvents.push(marker);
      continue;
    }

    if (event?.type === 'martyria') {
      const checkpoint = validateMartyriaWithGrid(event, grid, diagnostics);
      retunedTimeline.push(checkpoint);
      retunedCheckpoints.push(checkpoint);
      continue;
    }

    if (event?.type === 'note') {
      const retuned = retuneNoteWithGrid(event, grid, diagnostics);
      retunedTimeline.push(retuned);
      retunedNotes.push(retuned);
      continue;
    }

    if (event?.type === 'ison') {
      const retuned = retuneIsonWithGrid(event, grid, diagnostics);
      retunedTimeline.push(retuned);
      retunedIsonEvents.push(retuned);
      continue;
    }

    retunedTimeline.push(event);
  }

  return {
    ...compiled,
    timeline: retunedTimeline,
    notes: retunedNotes.length ? retunedNotes : (compiled?.notes ?? []),
    pthoraEvents: retunedPthoraEvents.length ? retunedPthoraEvents : (compiled?.pthoraEvents ?? []),
    checkpoints: retunedCheckpoints.length ? retunedCheckpoints : (compiled?.checkpoints ?? []),
    isonEvents: retunedIsonEvents.length ? retunedIsonEvents : (compiled?.isonEvents ?? []),
    diagnostics,
    tuningSource: 'engine',
  };
}

export function scoreInitialPthoraDrop(score) {
  const startDegree = score?.initialMartyria?.degree ?? 'Ni';
  const initialScale = score?.initialScale;
  if (!initialScale) return undefined;

  return {
    type: 'pthora',
    scale: initialScale.scale,
    genus: initialScale.genus,
    degree: startDegree,
    dropDegree: startDegree,
    dropMoria: referenceMoriaForDegree(startDegree),
    atMs: 0,
    sourceEventIndex: -1,
    ...(Number.isInteger(initialScale.phase) ? { phase: initialScale.phase } : {}),
  };
}

export function applyPthoraDrop(grid, pthora, diagnostics = []) {
  const drop = normalizePthoraDrop(pthora);
  if (!drop) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'score-pthora-invalid',
      message: 'Pthora event is missing genus, degree, or drop moria.',
      ...pthora?.source,
    });
    return false;
  }

  let ok = false;
  if (typeof grid.applySymbolDrop === 'function') {
    ok = grid.applySymbolDrop(JSON.stringify(drop));
  } else if (typeof grid.applyPthora === 'function') {
    ok = grid.applyPthora(drop.dropMoria, drop.genus, drop.degree);
  }

  if (!ok) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'score-pthora-apply-failed',
      message: `Unable to apply ${drop.genus} pthora at ${drop.dropDegree} ${drop.dropMoria}.`,
      ...pthora?.source,
    });
  }

  return ok;
}

export function retuneNoteWithGrid(note, grid, diagnostics = []) {
  const match = findDegreeCellForNote(grid, note);
  if (!match) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'score-target-cell-missing',
      message: `No tuning-grid cell was found for ${note.degree}.`,
      ...note.source,
    });
    return note;
  }

  const accidentalMoria = note.accidental?.moria ?? 0;
  const engineMoria = cellEffectiveMoria(match.cell);
  const targetMoria = engineMoria + accidentalMoria;
  const symbolicTarget = Number.isFinite(note.effectiveMoria) ? note.effectiveMoria : note.moria;
  const delta = nearestOctaveMoriaDelta(targetMoria - symbolicTarget);
  if (
    Number.isFinite(symbolicTarget) &&
    Number.isFinite(delta) &&
    Math.abs(delta) > TUNING_MATCH_TOLERANCE_MORIA
  ) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.WARNING,
      code: 'score-target-retuned',
      message: `Engine tuning moved ${note.degree} from ${formatMoria(symbolicTarget)} to ${formatMoria(targetMoria)} moria.`,
      ...note.source,
    });
  }

  return {
    ...note,
    targetMoria,
    engineMoria,
    effectiveMoria: targetMoria,
    tuning: {
      source: 'engine',
      cellMoria: match.cell.moria,
      cellEffectiveMoria: engineMoria,
      expectedMoria: match.expectedMoria,
      distanceMoria: match.distanceMoria,
      accidentalMoria,
    },
  };
}

export function validateMartyriaWithGrid(checkpoint, grid, diagnostics = []) {
  const match = findDegreeCell(grid, checkpoint.degree, checkpoint.moria);
  if (!match) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'martyria-grid-mismatch',
      message: `Martyria ${checkpoint.degree} has no matching tuning-grid degree cell.`,
      ...checkpoint.source,
    });
    return {
      ...checkpoint,
      gridMatches: false,
    };
  }

  return {
    ...checkpoint,
    gridMatches: true,
    targetMoria: cellEffectiveMoria(match.cell),
  };
}

export function retuneIsonWithGrid(ison, grid, diagnostics = []) {
  const expectedMoria = expectedMoriaForIson(ison);
  const match = findDegreeCell(grid, ison.degree, expectedMoria);
  if (!match) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'ison-target-cell-missing',
      message: `No tuning-grid cell was found for ison ${ison.degree}.`,
      ...ison.source,
    });
    return ison;
  }

  const targetMoria = cellEffectiveMoria(match.cell);
  return {
    ...ison,
    targetMoria,
    engineMoria: targetMoria,
    tuning: {
      source: 'engine',
      cellMoria: match.cell.moria,
      cellEffectiveMoria: targetMoria,
      expectedMoria: match.expectedMoria,
      distanceMoria: match.distanceMoria,
    },
  };
}

function normalizePthoraDrop(pthora) {
  const genus = pthora?.genus;
  const degree = pthora?.degree ?? pthora?.dropDegree;
  const dropDegree = pthora?.dropDegree ?? degree;
  const dropMoria = pthora?.dropMoria;
  if (!genus || !degree || !dropDegree || !Number.isFinite(dropMoria)) return undefined;
  return {
    type: 'pthora',
    genus,
    degree,
    dropDegree,
    dropMoria,
    ...(Number.isInteger(pthora.phase) ? { phase: pthora.phase } : {}),
  };
}

function findDegreeCellForNote(grid, note) {
  const expectedMoria = Number.isFinite(note?.moria)
    ? note.moria
    : referenceMoriaForDegree(note?.degree) + (note?.register ?? 0) * 72;
  return findDegreeCell(grid, note?.degree, expectedMoria);
}

function expectedMoriaForIson(ison) {
  if (Number.isFinite(ison?.moria)) return ison.moria;
  return referenceMoriaForDegree(ison?.degree) + (ison?.register ?? 0) * 72;
}

function findDegreeCell(grid, degree, expectedMoria) {
  if (!degree) return undefined;
  const cells = readGridCells(grid);
  let best;
  let bestDist = Infinity;
  for (const cell of cells) {
    if (cell.degree !== degree) continue;
    const dist = Number.isFinite(expectedMoria)
      ? Math.abs(cellEffectiveMoria(cell) - expectedMoria)
      : 0;
    if (dist < bestDist) {
      best = cell;
      bestDist = dist;
    }
  }
  return best ? { cell: best, expectedMoria, distanceMoria: bestDist } : undefined;
}

function readGridCells(grid) {
  try {
    const json = typeof grid.cellsJson === 'function' ? grid.cellsJson() : '[]';
    const cells = JSON.parse(json);
    return Array.isArray(cells) ? cells : [];
  } catch {
    return [];
  }
}

function cellEffectiveMoria(cell) {
  if (Number.isFinite(cell?.effective_moria)) return cell.effective_moria;
  return (cell?.moria ?? 0) + (cell?.accidental ?? 0);
}

function nearestOctaveMoriaDelta(delta) {
  if (!Number.isFinite(delta)) return delta;
  while (delta > 36) delta -= 72;
  while (delta < -36) delta += 72;
  return delta;
}

function formatMoria(moria) {
  return Number.isInteger(moria) ? String(moria) : moria.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
}
