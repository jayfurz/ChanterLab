import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

export const TEMPORAL_RULES = Object.freeze({
  gorgon: Object.freeze({
    sign: 'gorgon',
    divide: 2,
    windowBefore: 1,
    windowAfter: 0,
    outputFractions: Object.freeze([1 / 2, 1 / 2]),
    canBorrowFromExtendedPrevious: true,
  }),
  digorgon: Object.freeze({
    sign: 'digorgon',
    divide: 3,
    windowBefore: 1,
    windowAfter: 1,
    outputFractions: Object.freeze([1 / 3, 1 / 3, 1 / 3]),
    canBorrowFromExtendedPrevious: true,
  }),
  trigorgon: Object.freeze({
    sign: 'trigorgon',
    divide: 4,
    windowBefore: 1,
    windowAfter: 2,
    outputFractions: Object.freeze([1 / 4, 1 / 4, 1 / 4, 1 / 4]),
    canBorrowFromExtendedPrevious: true,
  }),
});

const TEMPORAL_RULES_BY_DIVIDE = new Map([
  [2, TEMPORAL_RULES.gorgon],
  [3, TEMPORAL_RULES.digorgon],
  [4, TEMPORAL_RULES.trigorgon],
]);

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
    const temporalRule = item.kind === 'note'
      ? temporalRuleForEvent(event, diagnostics, { reportUnsupported: timingMode === 'symbolic' })
      : undefined;
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
      } else if (temporalRule) {
        durationBeats = 0;
      } else if (hasQuick) {
        durationBeats = 0;
      } else if (baseBeats !== undefined) {
        durationBeats = baseBeats;
      }
    }

    return {
      ...item,
      durationBeats,
      timingLocked,
      ...(temporalRule ? { temporalRule } : {}),
    };
  });

  if (timingMode === 'symbolic') {
    applyTemporalRewriteRules(timed, diagnostics);
  }

  return timed;
}

function applyTemporalRewriteRules(timed, diagnostics) {
  const assignedWindows = new Map();

  for (let index = 0; index < timed.length; index += 1) {
    const item = timed[index];
    if (item.kind !== 'note' || !item.temporalRule) continue;
    applyTemporalRule(timed, index, item.temporalRule, assignedWindows, diagnostics);
  }
}

function applyTemporalRule(timed, index, rule, assignedWindows, diagnostics) {
  const item = timed[index];
  const window = collectTemporalWindow(timed, index, rule);
  const fallbackBeats = rule.outputFractions[rule.windowBefore] ?? (1 / rule.divide);

  if (!window.ok) {
    item.durationBeats = item.durationBeats || fallbackBeats;
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: windowDiagnosticCode(rule, 'invalid'),
      message: window.message,
      ...item.event.source,
    });
    return;
  }

  const overlapped = window.indices.find(windowIndex => assignedWindows.has(windowIndex));
  if (overlapped !== undefined) {
    item.durationBeats = item.durationBeats || fallbackBeats;
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'temporal-window-overlap',
      message: `${rule.sign} overlaps a ${assignedWindows.get(overlapped)} temporal window; overlapping temporal rewrites are not supported yet.`,
      ...item.event.source,
    });
    return;
  }

  const locked = window.indices
    .map(windowIndex => timed[windowIndex])
    .find(windowItem => windowItem.timingLocked);
  if (locked) {
    item.durationBeats = item.durationBeats || fallbackBeats;
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: windowDiagnosticCode(rule, 'locked'),
      message: `${rule.sign} cannot rewrite a window that contains an exact-duration note.`,
      ...item.event.source,
    });
    return;
  }

  const previous = timed[window.indices[0]];
  const borrowBeats = rule.outputFractions
    .slice(rule.windowBefore)
    .reduce((sum, beats) => sum + beats, 0);
  if (previous.durationBeats < borrowBeats) {
    item.durationBeats = item.durationBeats || fallbackBeats;
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: windowDiagnosticCode(rule, 'too-short'),
      message: `${rule.sign} cannot borrow ${formatBeats(borrowBeats)} beat(s) because the previous note is only ${formatBeats(previous.durationBeats)} beat(s).`,
      ...item.event.source,
    });
    return;
  }

  for (let offset = 1; offset < window.indices.length; offset += 1) {
    const windowItem = timed[window.indices[offset]];
    if (hasExplicitDuration(windowItem.event)) {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.WARNING,
        code: 'temporal-window-duration-overridden',
        message: `${rule.sign} controls the duration of this note; its explicit duration modifier is ignored inside the temporal window.`,
        ...windowItem.event.source,
      });
    }
  }

  previous.durationBeats -= borrowBeats;
  for (let offset = 1; offset < window.indices.length; offset += 1) {
    timed[window.indices[offset]].durationBeats = rule.outputFractions[offset];
  }

  for (const windowIndex of window.indices) {
    assignedWindows.set(windowIndex, rule.sign);
  }
}

function collectTemporalWindow(timed, index, rule) {
  const indices = [];
  const previousIndex = previousTimedNoteOrRestIndex(timed, index);
  if (previousIndex === undefined || timed[previousIndex].kind !== 'note') {
    return {
      ok: false,
      message: `${rule.sign} requires a previous symbolic note to borrow from.`,
    };
  }
  indices.push(previousIndex, index);

  let cursor = index;
  for (let count = 0; count < rule.windowAfter; count += 1) {
    const nextIndex = nextTimedNoteOrRestIndex(timed, cursor);
    if (nextIndex === undefined || timed[nextIndex].kind !== 'note') {
      return {
        ok: false,
        message: `${rule.sign} requires ${rule.windowAfter} following note(s) in its temporal window.`,
      };
    }

    if (timed[nextIndex].temporalRule) {
      return {
        ok: false,
        message: `${rule.sign} cannot include a following note that starts another temporal rewrite.`,
      };
    }

    indices.push(nextIndex);
    cursor = nextIndex;
  }

  return { ok: true, indices };
}

function previousTimedNoteOrRestIndex(timed, beforeIndex) {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const item = timed[index];
    if (item.kind === 'note' || item.kind === 'rest') return index;
  }
  return undefined;
}

function nextTimedNoteOrRestIndex(timed, afterIndex) {
  for (let index = afterIndex + 1; index < timed.length; index += 1) {
    const item = timed[index];
    if (item.kind === 'note' || item.kind === 'rest') return index;
  }
  return undefined;
}

function temporalRuleForEvent(event, diagnostics, options = {}) {
  const matches = [];
  for (const sign of event.temporal ?? []) {
    const rule = temporalRuleForSign(sign, diagnostics, options);
    if (rule) matches.push({ rule, source: sign.source });
  }

  if (matches.length > 1) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'temporal-sign-conflict',
      message: 'Only one temporal rewrite sign is supported on a note.',
      ...(matches[1].source ?? event.source),
    });
  }

  return matches[0]?.rule;
}

function temporalRuleForSign(sign, diagnostics, options = {}) {
  if (sign.type === 'quick') return TEMPORAL_RULES.gorgon;
  if (sign.type !== 'divide') return undefined;

  const rule = TEMPORAL_RULES_BY_DIVIDE.get(sign.divide);
  if (rule) return rule;

  if (options.reportUnsupported) {
    pushDiagnostic(diagnostics, {
      severity: sign.divide < 2 ? DIAGNOSTIC_SEVERITY.ERROR : DIAGNOSTIC_SEVERITY.WARNING,
      code: 'temporal-divide-unsupported',
      message: `divide ${sign.divide} is parsed but no temporal rewrite rule is available for it.`,
      ...sign.source,
    });
  }
  return undefined;
}

function hasTemporal(event, type) {
  return (event.temporal ?? []).some(sign => sign.type === type);
}

function hasExplicitDuration(event) {
  return Number.isFinite(event?.baseBeats) || Number.isFinite(event?.durationBeats);
}

function numberOrUndefined(value) {
  return Number.isFinite(value) ? value : undefined;
}

function windowDiagnosticCode(rule, kind) {
  if (rule.sign === 'gorgon' && kind === 'invalid') return 'quick-window-invalid';
  if (rule.sign === 'gorgon' && kind === 'too-short') return 'quick-window-too-short';
  return `${rule.sign}-window-${kind}`;
}

function formatBeats(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
}
