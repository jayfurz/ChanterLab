import {
  DEFAULT_TEMPO_BPM,
  degreeFromLinearIndex,
  degreeIndex,
  normalizeScaleName,
  positiveModulo,
  referenceMoriaForDegree,
  registerFromLinearIndex,
  scaleDefinition,
} from './chant_score.js';
import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';
import { displayForNeume } from './glyph_defaults.js';
import { assignBeatDurations, beatsToMilliseconds } from './timing.js';
import { parseChantScript } from './parser.js';

export function compileChantScript(text, options = {}) {
  const parsed = parseChantScript(text, options);
  return compileChantScore(parsed.score, {
    ...options,
    diagnostics: [...parsed.diagnostics],
  });
}

export function compileChantScore(score, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const startDegree = score.initialMartyria?.degree ?? 'Ni';
  let currentLinear = degreeIndex(startDegree);
  if (currentLinear < 0) {
    currentLinear = 0;
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'invalid-start-degree',
      message: `Invalid start degree "${startDegree}".`,
    });
  }

  let currentMoria = referenceMoriaForDegree(startDegree);
  let activeScale = createScaleContext(score.initialScale, currentLinear);
  const sequenceItems = [];

  for (let eventIndex = 0; eventIndex < score.events.length; eventIndex += 1) {
    const event = score.events[eventIndex];

    if (event.type === 'neume') {
      const resolved = resolveNeume(event, {
        eventIndex,
        currentLinear,
        currentMoria,
        activeScale,
        diagnostics,
        orthography: score.orthography,
      });
      currentLinear = resolved.linearDegree;
      currentMoria = resolved.moria;
      sequenceItems.push({
        kind: 'note',
        event,
        sourceEventIndex: eventIndex,
        resolved,
      });

      if (event.checkpoint) {
        resolved.martyriaCheckpoint = validateCheckpoint(event.checkpoint, currentLinear, diagnostics);
      }
      if (event.pthora) {
        activeScale = createScaleContext(event.pthora, currentLinear);
      }
      continue;
    }

    if (event.type === 'rest') {
      sequenceItems.push({
        kind: 'rest',
        event,
        sourceEventIndex: eventIndex,
        resolved: {
          type: 'rest',
          sourceEventIndex: eventIndex,
        },
      });
      continue;
    }

    if (event.type === 'tempo') {
      sequenceItems.push({
        kind: 'tempo',
        event,
        sourceEventIndex: eventIndex,
      });
      continue;
    }

    if (event.type === 'martyria') {
      sequenceItems.push({
        kind: 'checkpoint',
        event,
        sourceEventIndex: eventIndex,
        checkpoint: validateCheckpoint(event, currentLinear, diagnostics),
      });
      continue;
    }

    if (event.type === 'phrase') {
      sequenceItems.push({
        kind: 'phrase',
        event,
        sourceEventIndex: eventIndex,
        checkpoint: event.checkpoint
          ? validateCheckpoint(event.checkpoint, currentLinear, diagnostics)
          : undefined,
      });
      continue;
    }

    if (event.type === 'pthora') {
      const drop = createPthoraDrop(event, {
        degree: degreeFromLinearIndex(currentLinear),
        linearDegree: currentLinear,
        moria: currentMoria,
      });
      activeScale = createScaleContext(event, currentLinear);
      sequenceItems.push({
        kind: 'pthora',
        event,
        sourceEventIndex: eventIndex,
        scale: activeScale,
        pthora: drop,
      });
      continue;
    }

    if (event.type === 'ison') {
      sequenceItems.push({
        kind: 'ison',
        event,
        sourceEventIndex: eventIndex,
        isonContext: createIsonContext(event.degree, event.register),
      });
      continue;
    }

    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'unsupported-event',
      message: `Unsupported score event type "${event.type}".`,
      ...event.source,
    });
  }

  const timedItems = assignBeatDurations(sequenceItems, score.timingMode ?? 'symbolic', diagnostics);
  return buildMillisecondTimeline(score, timedItems, diagnostics);
}

function resolveNeume(event, context) {
  const { movement } = event;
  const steps = movement?.steps ?? 0;
  let delta = 0;

  if (movement?.direction === 'up') delta = steps;
  else if (movement?.direction === 'down') delta = -steps;
  else if (movement?.direction !== 'same') {
    pushDiagnostic(context.diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'invalid-movement',
      message: `Invalid movement direction "${movement?.direction}".`,
      ...event.source,
    });
  }

  if (Math.abs(delta) > 4) {
    pushDiagnostic(context.diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'unsupported-movement',
      message: 'v0 supports relative movement of 1 through 4 steps.',
      ...event.source,
    });
  }

  const moriaDelta = moriaDeltaForMovement(context.activeScale, context.currentLinear, delta);
  const linearDegree = context.currentLinear + delta;
  const moria = context.currentMoria + moriaDelta;
  const degree = degreeFromLinearIndex(linearDegree);
  const accidentalMoria = event.accidental?.moria ?? 0;
  const pthora = event.pthora
    ? createPthoraDrop(event.pthora, { degree, linearDegree, moria })
    : undefined;

  return {
    type: 'note',
    degree,
    register: registerFromLinearIndex(linearDegree),
    linearDegree,
    moria,
    effectiveMoria: moria + accidentalMoria,
    sourceEventIndex: context.eventIndex,
    movement: { ...movement },
    lyric: event.lyric ?? { kind: 'none' },
    pthora,
    drone: event.drone,
    accidental: event.accidental,
    qualitative: [...(event.qualitative ?? [])],
    display: displayForNeume(event, context.orthography),
    scale: {
      scale: context.activeScale.scale,
      genus: context.activeScale.definition.genus,
      phase: context.activeScale.phase,
    },
  };
}

function buildMillisecondTimeline(score, timedItems, diagnostics) {
  const timeline = [];
  const notes = [];
  const rests = [];
  const tempoChanges = [];
  const checkpoints = [];
  const phraseBreaks = [];
  const isonEvents = [];
  const pthoraEvents = [];

  let currentMs = 0;
  let currentBpm = Number.isFinite(score.defaultTempoBpm) ? score.defaultTempoBpm : DEFAULT_TEMPO_BPM;
  const initialTempo = {
    type: 'tempo',
    atMs: 0,
    workingBpm: currentBpm,
    sourceEventIndex: -1,
    ...(score.defaultAgogi ? { agogi: score.defaultAgogi } : {}),
  };
  timeline.push(initialTempo);
  tempoChanges.push(initialTempo);
  if (score.defaultDrone) {
    const initialIson = createIsonEvent({
      degree: score.defaultDrone,
      atMs: 0,
      sourceEventIndex: -1,
      kind: 'default',
      context: createIsonContext(score.defaultDrone, score.defaultDroneRegister),
    });
    timeline.push(initialIson);
    isonEvents.push(initialIson);
  }

  for (const item of timedItems) {
    if (item.kind === 'tempo') {
      currentBpm = Number.isFinite(item.event.workingBpm) ? item.event.workingBpm : currentBpm;
      const tempoChange = {
        type: 'tempo',
        atMs: currentMs,
        workingBpm: currentBpm,
        sourceEventIndex: item.sourceEventIndex,
        ...(item.event.agogi ? { agogi: item.event.agogi } : {}),
      };
      timeline.push(tempoChange);
      tempoChanges.push(tempoChange);
      continue;
    }

    if (item.kind === 'checkpoint') {
      checkpoints.push({
        ...item.checkpoint,
        atMs: currentMs,
        sourceEventIndex: item.sourceEventIndex,
      });
      continue;
    }

    if (item.kind === 'phrase') {
      phraseBreaks.push({
        type: 'phrase',
        atMs: currentMs,
        sourceEventIndex: item.sourceEventIndex,
        ...(item.checkpoint ? { checkpoint: item.checkpoint } : {}),
      });
      continue;
    }

    if (item.kind === 'ison') {
      const isonEvent = createIsonEvent({
        degree: item.event.degree,
        atMs: currentMs,
        sourceEventIndex: item.sourceEventIndex,
        kind: 'explicit',
        context: item.isonContext,
      });
      timeline.push(isonEvent);
      isonEvents.push(isonEvent);
      continue;
    }

    if (item.kind === 'pthora') {
      const pthoraEvent = {
        ...item.pthora,
        type: 'pthora',
        atMs: currentMs,
        sourceEventIndex: item.sourceEventIndex,
      };
      timeline.push(pthoraEvent);
      pthoraEvents.push(pthoraEvent);
      continue;
    }

    if (item.kind !== 'note' && item.kind !== 'rest') continue;

    const durationMs = beatsToMilliseconds(item.durationBeats, currentBpm);

    if (!Number.isFinite(durationMs) || durationMs < 0) {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'invalid-duration',
        message: 'Compiled event duration is invalid.',
        ...item.event.source,
      });
      continue;
    }

    if (item.kind === 'note') {
      if (item.resolved.martyriaCheckpoint) {
        const checkpoint = {
          ...item.resolved.martyriaCheckpoint,
          atMs: currentMs,
          sourceEventIndex: item.sourceEventIndex,
        };
        timeline.push(checkpoint);
        checkpoints.push(checkpoint);
      }
      if (item.resolved.pthora) {
        const pthoraEvent = {
          ...item.resolved.pthora,
          atMs: currentMs,
          sourceEventIndex: item.sourceEventIndex,
        };
        timeline.push(pthoraEvent);
        pthoraEvents.push(pthoraEvent);
      }
      if (item.resolved.drone) {
        const isonEvent = createIsonEvent({
          degree: item.resolved.drone.degree,
          atMs: currentMs,
          sourceEventIndex: item.sourceEventIndex,
          kind: 'note',
          context: createIsonContext(item.resolved.drone.degree, item.resolved.drone.register),
        });
        timeline.push(isonEvent);
        isonEvents.push(isonEvent);
        item.resolved.drone = {
          ...item.resolved.drone,
          atMs: currentMs,
          sourceEventIndex: item.sourceEventIndex,
        };
      }
      const compiled = {
        ...item.resolved,
        startMs: currentMs,
        durationMs,
        durationBeats: item.durationBeats,
        sourceEventIndex: item.sourceEventIndex,
      };
      timeline.push(compiled);
      notes.push(compiled);
      if (compiled.pthora) {
        compiled.pthora = {
          ...compiled.pthora,
          atMs: currentMs,
          sourceEventIndex: item.sourceEventIndex,
        };
      }
    } else {
      const compiled = {
        type: 'rest',
        startMs: currentMs,
        durationMs,
        durationBeats: item.durationBeats,
        sourceEventIndex: item.sourceEventIndex,
      };
      timeline.push(compiled);
      rests.push(compiled);
    }

    currentMs += durationMs;
  }

  return {
    score,
    timeline,
    notes,
    rests,
    tempoChanges,
    checkpoints,
    phraseBreaks,
    isonEvents,
    pthoraEvents,
    initialTuning: createInitialTuning(score),
    diagnostics,
    totalDurationMs: currentMs,
  };
}

function createIsonEvent({ degree, atMs, sourceEventIndex, kind, context }) {
  return {
    type: 'ison',
    atMs,
    degree,
    sourceEventIndex,
    ...(kind ? { kind } : {}),
    ...(Number.isFinite(context?.linearDegree) ? { linearDegree: context.linearDegree } : {}),
    ...(Number.isFinite(context?.register) ? { register: context.register } : {}),
    ...(Number.isFinite(context?.moria) ? { moria: context.moria } : {}),
  };
}

function createIsonContext(degree, register = 0) {
  const baseLinear = degreeIndex(degree);
  if (baseLinear < 0) return {};
  const resolvedRegister = Number.isInteger(register) ? register : 0;

  return {
    linearDegree: baseLinear + resolvedRegister * 7,
    register: resolvedRegister,
    moria: referenceMoriaForDegree(degree) + resolvedRegister * 72,
  };
}

function validateCheckpoint(checkpoint, currentLinear, diagnostics) {
  const actualDegree = degreeFromLinearIndex(currentLinear);
  const matches = checkpoint.degree === actualDegree;
  if (!matches) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'checkpoint-mismatch',
      message: `Checkpoint expected ${checkpoint.degree}, but the resolved melody is at ${actualDegree}.`,
      ...checkpoint.source,
    });
  }
  return {
    ...checkpoint,
    actualDegree,
    linearDegree: currentLinear,
    register: registerFromLinearIndex(currentLinear),
    matches,
  };
}

function createPthoraDrop(spec, context) {
  if (!spec) return undefined;
  const degree = context.degree;
  return {
    type: 'pthora',
    scale: spec.scale,
    genus: spec.genus,
    degree,
    dropDegree: degree,
    dropMoria: context.moria,
    linearDegree: context.linearDegree,
    ...(Number.isInteger(spec.phase) ? { phase: spec.phase } : {}),
    ...(spec.source ? { source: spec.source } : {}),
  };
}

function createInitialTuning(score) {
  const startDegree = score.initialMartyria?.degree ?? 'Ni';
  const initialScale = score.initialScale;
  if (!initialScale) return undefined;
  return {
    type: 'pthora',
    scale: initialScale.scale,
    genus: initialScale.genus,
    degree: startDegree,
    dropDegree: startDegree,
    dropMoria: referenceMoriaForDegree(startDegree),
    linearDegree: degreeIndex(startDegree),
    atMs: 0,
    sourceEventIndex: -1,
    ...(Number.isInteger(initialScale.phase) ? { phase: initialScale.phase } : {}),
    ...(initialScale.source ? { source: initialScale.source } : {}),
  };
}

function createScaleContext(spec, anchorLinear) {
  const scale = normalizeScaleName(spec?.scale) ?? 'diatonic';
  const definition = scaleDefinition(scale);
  return {
    scale,
    definition,
    anchorLinear,
    phase: Number.isInteger(spec?.phase) ? spec.phase : 0,
  };
}

function moriaDeltaForMovement(scaleContext, startLinear, delta) {
  if (delta === 0) return 0;
  let moria = 0;

  if (delta > 0) {
    for (let step = 0; step < delta; step += 1) {
      moria += intervalUp(scaleContext, startLinear + step);
    }
    return moria;
  }

  for (let step = 0; step < Math.abs(delta); step += 1) {
    moria -= intervalUp(scaleContext, startLinear - step - 1);
  }
  return moria;
}

function intervalUp(scaleContext, fromLinear) {
  const { definition } = scaleContext;
  if (!definition.cycle) {
    return definition.intervals[positiveModulo(fromLinear, 7)];
  }
  const phaseIndex = positiveModulo(
    fromLinear - scaleContext.anchorLinear + scaleContext.phase,
    definition.intervals.length
  );
  return definition.intervals[phaseIndex];
}
