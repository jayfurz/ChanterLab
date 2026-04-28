import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

export function beatsToMilliseconds(beats, bpm) {
  return beats * (60000 / bpm);
}

export function assignBeatDurations(sequenceItems, timingMode, diagnostics = []) {
  const timed = sequenceItems.map(item => {
    if (item.kind !== 'note' && item.kind !== 'rest') return { ...item };

    const event = item.event;
    const exactDuration = numberOrUndefined(event.durationBeats);
    const baseBeats = numberOrUndefined(event.baseBeats);
    const hasQuick = hasTemporal(event, 'quick');
    const hasDivide = (event.temporal ?? []).some(sign => sign.type === 'divide');
    let durationBeats = 1;
    let timingLocked = false;

    if (item.kind === 'rest') {
      if (hasQuick) {
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.ERROR,
          code: 'rest-quick-unsupported',
          message: 'rest quick is recognized but unsupported in v0 until rest-temporal behavior is reviewed.',
          ...event.source,
        });
      }
      if (exactDuration !== undefined) {
        durationBeats = exactDuration;
        timingLocked = true;
      } else if (baseBeats !== undefined) {
        durationBeats = baseBeats;
      }
    } else if (timingMode === 'exact') {
      if (exactDuration !== undefined) {
        durationBeats = exactDuration;
      } else if (baseBeats !== undefined) {
        durationBeats = baseBeats;
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.ERROR,
          code: 'exact-symbolic-beats',
          message: 'beats is symbolic timing; use duration in timing exact mode.',
          ...event.source,
        });
      } else {
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.WARNING,
          code: 'exact-duration-missing',
          message: 'timing exact note has no duration; using one beat as a fallback.',
          ...event.source,
        });
      }

      if (hasQuick || hasDivide) {
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.ERROR,
          code: 'exact-symbolic-temporal',
          message: 'symbolic temporal modifiers are not supported in timing exact mode.',
          ...event.source,
        });
      }
    } else {
      if (exactDuration !== undefined) {
        durationBeats = exactDuration;
        timingLocked = true;
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.ERROR,
          code: 'symbolic-exact-duration',
          message: 'note duration is exact timing; use beats in timing symbolic mode.',
          ...event.source,
        });
      } else if (hasQuick) {
        durationBeats = 0;
      } else if (baseBeats !== undefined) {
        durationBeats = baseBeats;
      }
    }

    for (const sign of event.temporal ?? []) {
      if (sign.type === 'divide' && sign.divide >= 3) {
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.WARNING,
          code: 'temporal-divide-unimplemented',
          message: `divide ${sign.divide} is parsed but its temporal rewrite window is not implemented in v0.`,
          ...event.source,
        });
      }
    }

    return {
      ...item,
      durationBeats,
      timingLocked,
    };
  });

  if (timingMode === 'symbolic') {
    applyQuickRewrite(timed, diagnostics);
  }

  return timed;
}

function applyQuickRewrite(timed, diagnostics) {
  for (let index = 0; index < timed.length; index += 1) {
    const item = timed[index];
    if (item.kind !== 'note' || !hasTemporal(item.event, 'quick')) continue;

    const previous = previousTimedNoteOrRest(timed, index);
    if (!previous || previous.kind !== 'note' || previous.timingLocked) {
      item.durationBeats = item.durationBeats || 0.5;
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'quick-window-invalid',
        message: 'quick requires a previous symbolic note to borrow a half beat from.',
        ...item.event.source,
      });
      continue;
    }

    if (previous.durationBeats < 0.5) {
      item.durationBeats = item.durationBeats || 0.5;
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'quick-window-too-short',
        message: 'quick cannot borrow a half beat because the previous note is shorter than a half beat.',
        ...item.event.source,
      });
      continue;
    }

    previous.durationBeats -= 0.5;
    item.durationBeats += 0.5;
  }
}

function previousTimedNoteOrRest(timed, beforeIndex) {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const item = timed[index];
    if (item.kind === 'note' || item.kind === 'rest') return item;
  }
  return undefined;
}

function hasTemporal(event, type) {
  return (event.temporal ?? []).some(sign => sign.type === type);
}

function numberOrUndefined(value) {
  return Number.isFinite(value) ? value : undefined;
}
