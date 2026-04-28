import {
  createChantScore,
  createTempoEvent,
  makeSourceLocation,
  normalizeDegree,
  normalizeScaleName,
  normalizeTempoName,
  scaleDefinition,
} from './chant_score.js';
import { DIAGNOSTIC_SEVERITY, pushDiagnostic, tokenLocation } from './diagnostics.js';

export function parseChantScript(text, options = {}) {
  const diagnostics = [];
  const score = createChantScore();
  const sourceName = options.sourceName;
  const lines = String(text ?? '').split(/\r?\n/);
  let sawTimelineEvent = false;

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const lineNumber = lineIndex + 1;
    const tokens = tokenizeLine(lines[lineIndex], lineNumber, diagnostics, sourceName);
    if (tokens.length === 0) continue;

    const first = lower(tokens[0]);
    const markTimelineEvent = event => {
      if (event) {
        score.events.push(event);
        sawTimelineEvent = true;
      }
    };

    switch (first) {
      case 'title':
        parseSingleStringHeader(score, tokens, diagnostics, 'title', 'title');
        break;
      case 'mode':
        parseSingleStringHeader(score, tokens, diagnostics, 'mode', 'mode');
        break;
      case 'language':
        parseLanguage(score, tokens, diagnostics);
        break;
      case 'lyrics':
        parseLyricMetadata(score, tokens, diagnostics, 'lyrics');
        break;
      case 'translation':
        parseLyricMetadata(score, tokens, diagnostics, 'translations');
        break;
      case 'tempo':
        parseTempo(score, tokens, diagnostics, sawTimelineEvent);
        if (sawTimelineEvent && score.events.at(-1)?.type === 'tempo') sawTimelineEvent = true;
        break;
      case 'timing':
        parseEnumHeader(score, tokens, diagnostics, 'timingMode', 'timing', ['symbolic', 'exact']);
        break;
      case 'orthography':
        parseEnumHeader(score, tokens, diagnostics, 'orthography', 'orthography', ['generated', 'none']);
        break;
      case 'start':
        parseStart(score, tokens, diagnostics);
        break;
      case 'scale':
        parseTopLevelScale(score, tokens, diagnostics, sawTimelineEvent, markTimelineEvent);
        break;
      case 'pthora':
        parseTopLevelScale(score, tokens, diagnostics, sawTimelineEvent, markTimelineEvent, 1);
        break;
      case 'drone':
      case 'ison':
        parseDrone(score, tokens, diagnostics, sawTimelineEvent, markTimelineEvent);
        break;
      case 'martyria':
        if (!sawTimelineEvent && !score.initialMartyria) {
          parseStart(score, tokens, diagnostics, 1);
        } else {
          markTimelineEvent(parseCheckpoint(tokens, diagnostics, 1));
        }
        break;
      case 'checkpoint':
        markTimelineEvent(parseCheckpoint(tokens, diagnostics, 1));
        break;
      case 'phrase':
        markTimelineEvent(parsePhrase(tokens, diagnostics));
        break;
      case 'note':
        markTimelineEvent(parseNoteLine(tokens, diagnostics, 0, score.timingMode, score.orthography));
        break;
      case 'same':
      case 'up':
      case 'down':
      case 'hold':
        markTimelineEvent(parseNoteAlias(tokens, diagnostics, score.timingMode, score.orthography));
        break;
      case 'rest':
        markTimelineEvent(parseRestLine(tokens, diagnostics));
        break;
      case 'silence':
        markTimelineEvent(parseSilenceAlias(tokens, diagnostics));
        break;
      default:
        pushDiagnostic(diagnostics, {
          severity: DIAGNOSTIC_SEVERITY.ERROR,
          code: 'unknown-keyword',
          message: `Unknown chant script keyword "${tokens[0].value}".`,
          ...tokenLocation(tokens[0]),
          source: sourceName,
        });
        break;
    }
  }

  if (!score.initialMartyria) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'missing-start',
      message: 'Chant script is missing a start degree.',
      source: sourceName,
    });
    score.initialMartyria = { type: 'martyria', degree: 'Ni' };
  }

  if (!score.initialScale) {
    score.initialScale = {
      type: 'pthora',
      scale: 'diatonic',
      genus: 'Diatonic',
      phase: undefined,
    };
  }

  return { score, diagnostics };
}

export function tokenizeLine(line, lineNumber = 1, diagnostics = [], sourceName) {
  const tokens = [];
  let index = 0;

  while (index < line.length) {
    const char = line[index];
    if (char === '#') break;
    if (/\s/.test(char)) {
      index += 1;
      continue;
    }

    const column = index + 1;
    if (char === '"') {
      const { token, nextIndex } = readQuotedString(line, index, lineNumber, diagnostics, sourceName);
      tokens.push(token);
      index = nextIndex;
      continue;
    }

    const start = index;
    while (index < line.length && !/\s/.test(line[index]) && line[index] !== '#') {
      index += 1;
    }
    tokens.push({
      type: 'word',
      value: line.slice(start, index),
      raw: line.slice(start, index),
      line: lineNumber,
      column,
      endColumn: index + 1,
    });
  }

  return tokens;
}

function readQuotedString(line, startIndex, lineNumber, diagnostics, sourceName) {
  let index = startIndex + 1;
  let value = '';
  let closed = false;

  while (index < line.length) {
    const char = line[index];
    if (char === '\\') {
      const next = line[index + 1];
      if (next === '"' || next === '\\') {
        value += next;
        index += 2;
        continue;
      }
      if (next === 'n') {
        value += '\n';
        index += 2;
        continue;
      }
      if (next === 't') {
        value += '\t';
        index += 2;
        continue;
      }
    }
    if (char === '"') {
      closed = true;
      index += 1;
      break;
    }
    value += char;
    index += 1;
  }

  if (!closed) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'unterminated-string',
      message: 'Unterminated quoted string.',
      line: lineNumber,
      column: startIndex + 1,
      source: sourceName,
    });
  }

  return {
    token: {
      type: 'string',
      value,
      raw: line.slice(startIndex, index),
      line: lineNumber,
      column: startIndex + 1,
      endColumn: index + 1,
    },
    nextIndex: index,
  };
}

function parseSingleStringHeader(score, tokens, diagnostics, field, keyword) {
  if (!expectArity(tokens, diagnostics, 2, `${keyword} requires one quoted string.`)) return;
  const token = tokens[1];
  if (!expectString(token, diagnostics, `${keyword} requires a quoted string.`)) return;
  score[field] = token.value;
}

function parseLanguage(score, tokens, diagnostics) {
  if (!expectArity(tokens, diagnostics, 2, 'language requires one language tag.')) return;
  if (tokens[1].type === 'string') {
    diagAt(diagnostics, tokens[1], 'invalid-language', 'language requires an unquoted language tag.');
    return;
  }
  score.language = tokens[1].value;
}

function parseLyricMetadata(score, tokens, diagnostics, field) {
  if (field === 'lyrics' && tokens[1]?.type === 'string') {
    if (!expectArity(tokens, diagnostics, 2, 'lyrics requires either a quoted string or line-id plus quoted string.')) return;
    score.lyrics.push({ id: 'default', text: tokens[1].value, language: score.language });
    return;
  }

  if (!expectArity(tokens, diagnostics, 3, `${tokens[0].value} requires a line id and quoted string.`)) return;
  if (tokens[1].type === 'string') {
    diagAt(diagnostics, tokens[1], 'invalid-line-id', 'line id must be an unquoted identifier.');
    return;
  }
  if (!expectString(tokens[2], diagnostics, `${tokens[0].value} text must be quoted.`)) return;

  score[field].push({
    id: tokens[1].value,
    text: tokens[2].value,
    language: field === 'lyrics' ? score.language : undefined,
  });
}

function parseTempo(score, tokens, diagnostics, asEvent) {
  if (tokens.length < 3 && lower(tokens[1]) === 'bpm') {
    diagAt(diagnostics, tokens[0], 'invalid-tempo', 'tempo bpm requires a number.');
    return;
  }

  let tempoName;
  let bpm;
  let cursor = 1;

  if (lower(tokens[cursor]) === 'bpm') {
    const parsed = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'tempo bpm');
    if (parsed === undefined) return;
    bpm = parsed;
    cursor += 2;
  } else {
    tempoName = normalizeTempoName(tokens[cursor]?.value);
    if (!tempoName) {
      diagAt(diagnostics, tokens[cursor], 'invalid-tempo-name', `Unsupported tempo name "${tokens[cursor]?.value ?? ''}".`);
      return;
    }
    cursor += 1;

    if (cursor < tokens.length) {
      if (lower(tokens[cursor]) !== 'bpm') {
        diagAt(diagnostics, tokens[cursor], 'invalid-tempo', 'tempo only accepts an optional bpm modifier.');
        return;
      }
      const parsed = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'tempo bpm');
      if (parsed === undefined) return;
      bpm = parsed;
      cursor += 2;
    }
  }

  expectEnd(tokens, diagnostics, cursor);

  const event = createTempoEvent({
    tempoName,
    bpm,
    source: makeSourceLocation(tokens[0]),
  });
  if (!Number.isFinite(event.workingBpm)) {
    diagAt(diagnostics, tokens[0], 'invalid-tempo', 'tempo requires either a name or bpm value.');
    return;
  }

  if (asEvent) {
    score.events.push({ ...event, temporary: true });
    return;
  }

  score.defaultAgogi = event.agogi;
  score.defaultTempoBpm = event.workingBpm;
  score.tempoPolicy = {
    source: tempoName ? 'score' : 'user',
    bpm: event.workingBpm,
    ...(event.agogi ? { agogi: event.agogi } : {}),
  };
}

function parseEnumHeader(score, tokens, diagnostics, field, keyword, allowed) {
  if (!expectArity(tokens, diagnostics, 2, `${keyword} requires one value.`)) return;
  const value = lower(tokens[1]);
  if (!allowed.includes(value)) {
    diagAt(diagnostics, tokens[1], `invalid-${keyword}`, `${keyword} must be one of: ${allowed.join(', ')}.`);
    return;
  }
  score[field] = value;
}

function parseStart(score, tokens, diagnostics, degreeIndex = 1) {
  const degree = parseDegreeToken(tokens[degreeIndex], diagnostics);
  if (!degree) return;
  score.initialMartyria = {
    type: 'martyria',
    degree,
    source: makeSourceLocation(tokens[0]),
  };

  let cursor = degreeIndex + 1;
  if (cursor < tokens.length) {
    if (lower(tokens[cursor]) !== 'scale') {
      diagAt(diagnostics, tokens[cursor], 'invalid-start', 'start accepts only an optional scale modifier.');
      return;
    }
    const parsed = parseScaleSpec(tokens, diagnostics, cursor + 1);
    if (parsed.spec) {
      score.initialScale = parsed.spec;
      cursor = parsed.nextIndex;
    }
  }
  expectEnd(tokens, diagnostics, cursor);
}

function parseTopLevelScale(score, tokens, diagnostics, asEvent, markTimelineEvent, startIndex = 1) {
  const parsed = parseScaleSpec(tokens, diagnostics, startIndex);
  if (!parsed.spec) return;
  expectEnd(tokens, diagnostics, parsed.nextIndex);
  if (asEvent) markTimelineEvent(parsed.spec);
  else score.initialScale = parsed.spec;
}

function parseDrone(score, tokens, diagnostics, asEvent, markTimelineEvent) {
  if (!expectArity(tokens, diagnostics, 2, `${tokens[0].value} requires one degree.`)) return;
  const degree = parseDegreeToken(tokens[1], diagnostics);
  if (!degree) return;
  const event = {
    type: 'ison',
    degree,
    source: makeSourceLocation(tokens[0]),
  };
  if (asEvent) markTimelineEvent(event);
  else score.defaultDrone = degree;
}

function parseCheckpoint(tokens, diagnostics, degreeIndex = 1) {
  if (!expectArity(tokens, diagnostics, degreeIndex + 1, `${tokens[0].value} requires one degree.`)) return undefined;
  const degree = parseDegreeToken(tokens[degreeIndex], diagnostics);
  if (!degree) return undefined;
  return {
    type: 'martyria',
    degree,
    checkpoint: true,
    source: makeSourceLocation(tokens[0]),
  };
}

function parsePhrase(tokens, diagnostics) {
  if (tokens.length === 1) {
    return {
      type: 'phrase',
      source: makeSourceLocation(tokens[0]),
    };
  }
  if (tokens.length === 3 && lower(tokens[1]) === 'checkpoint') {
    const degree = parseDegreeToken(tokens[2], diagnostics);
    if (!degree) return undefined;
    return {
      type: 'phrase',
      checkpoint: {
        type: 'martyria',
        degree,
        checkpoint: true,
        source: makeSourceLocation(tokens[1]),
      },
      source: makeSourceLocation(tokens[0]),
    };
  }
  diagAt(diagnostics, tokens[1], 'invalid-phrase', 'phrase accepts no modifiers except checkpoint <degree>.');
  return undefined;
}

function parseNoteAlias(tokens, diagnostics, timingMode, orthography) {
  const first = lower(tokens[0]);
  if (first === 'hold') {
    const beats = parsePositiveNumber(tokens[1], diagnostics, 'hold');
    if (beats === undefined) return undefined;
    const note = createNeumeEvent(
      { direction: 'same', steps: 0 },
      tokens[0],
      timingMode,
      orthography
    );
    note.baseBeats = beats;
    parseNoteModifiers(note, tokens, diagnostics, 2);
    return note;
  }
  if (first === 'same') {
    const note = createNeumeEvent(
      { direction: 'same', steps: 0 },
      tokens[0],
      timingMode,
      orthography
    );
    parseNoteModifiers(note, tokens, diagnostics, 1);
    return note;
  }
  return parseDirectedNote(tokens, diagnostics, 0, timingMode, orthography);
}

function parseNoteLine(tokens, diagnostics, startIndex, timingMode, orthography) {
  const movementToken = tokens[startIndex + 1];
  const movement = lower(movementToken);
  if (movement === 'same') {
    const note = createNeumeEvent(
      { direction: 'same', steps: 0 },
      tokens[startIndex],
      timingMode,
      orthography
    );
    parseNoteModifiers(note, tokens, diagnostics, startIndex + 2);
    return note;
  }
  if (movement === 'up' || movement === 'down') {
    return parseDirectedNote(tokens, diagnostics, startIndex + 1, timingMode, orthography, tokens[startIndex]);
  }
  diagAt(diagnostics, movementToken ?? tokens[startIndex], 'invalid-note', 'note must be followed by same, up, or down.');
  return undefined;
}

function parseDirectedNote(tokens, diagnostics, movementIndex, timingMode, orthography, sourceToken = tokens[movementIndex]) {
  const direction = lower(tokens[movementIndex]);
  const steps = parseInteger(tokens[movementIndex + 1], diagnostics, `${direction} steps`);
  if (steps === undefined) return undefined;
  if (steps < 1) {
    diagAt(diagnostics, tokens[movementIndex + 1], 'invalid-steps', 'note steps must be at least 1.');
    return undefined;
  }
  const note = createNeumeEvent(
    { direction, steps },
    sourceToken,
    timingMode,
    orthography
  );
  parseNoteModifiers(note, tokens, diagnostics, movementIndex + 2);
  return note;
}

function createNeumeEvent(movement, sourceToken, timingMode, orthography) {
  return {
    type: 'neume',
    movement,
    quantity: {
      type: 'relative',
      movement,
    },
    temporal: [],
    qualitative: [],
    timingMode,
    display: { orthography },
    lyric: { kind: 'none' },
    source: makeSourceLocation(sourceToken),
  };
}

function parseNoteModifiers(note, tokens, diagnostics, startIndex) {
  let cursor = startIndex;
  while (cursor < tokens.length) {
    const word = lower(tokens[cursor]);
    switch (word) {
      case 'beats': {
        const value = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'beats');
        if (value === undefined) return;
        note.baseBeats = value;
        cursor += 2;
        break;
      }
      case 'apli':
      case 'klasma':
        note.baseBeats = 2;
        cursor += 1;
        break;
      case 'dipli':
        note.baseBeats = 3;
        cursor += 1;
        break;
      case 'tripli':
        note.baseBeats = 4;
        cursor += 1;
        break;
      case 'quick':
      case 'gorgon':
        note.temporal.push({ type: 'quick', sign: 'gorgon', source: makeSourceLocation(tokens[cursor]) });
        cursor += 1;
        break;
      case 'divide': {
        const value = parseInteger(tokens[cursor + 1], diagnostics, 'divide');
        if (value === undefined) return;
        note.temporal.push({ type: 'divide', divide: value, source: makeSourceLocation(tokens[cursor]) });
        cursor += 2;
        break;
      }
      case 'digorgon':
        note.temporal.push({ type: 'divide', divide: 3, sign: 'digorgon', source: makeSourceLocation(tokens[cursor]) });
        cursor += 1;
        break;
      case 'trigorgon':
        note.temporal.push({ type: 'divide', divide: 4, sign: 'trigorgon', source: makeSourceLocation(tokens[cursor]) });
        cursor += 1;
        break;
      case 'duration': {
        const value = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'duration');
        if (value === undefined) return;
        note.durationBeats = value;
        cursor += 2;
        break;
      }
      case 'accidental': {
        const value = parseAccidentalMoria(tokens[cursor + 1], diagnostics, 'accidental');
        if (value === undefined) return;
        note.accidental = { moria: value, source: makeSourceLocation(tokens[cursor]) };
        cursor += 2;
        break;
      }
      case 'sharp':
      case 'diesis': {
        const value = parseAccidentalMagnitude(tokens[cursor + 1], diagnostics, word);
        if (value === undefined) return;
        note.accidental = { moria: value, source: makeSourceLocation(tokens[cursor]) };
        cursor += 2;
        break;
      }
      case 'flat':
      case 'hyphesis': {
        const value = parseAccidentalMagnitude(tokens[cursor + 1], diagnostics, word);
        if (value === undefined) return;
        note.accidental = { moria: -value, source: makeSourceLocation(tokens[cursor]) };
        cursor += 2;
        break;
      }
      case 'scale':
      case 'pthora': {
        const parsed = parseScaleSpec(tokens, diagnostics, cursor + 1);
        if (!parsed.spec) return;
        note.pthora = parsed.spec;
        cursor = parsed.nextIndex;
        break;
      }
      case 'drone':
      case 'ison': {
        const degree = parseDegreeToken(tokens[cursor + 1], diagnostics);
        if (!degree) return;
        note.drone = { type: 'ison', degree, source: makeSourceLocation(tokens[cursor]) };
        cursor += 2;
        break;
      }
      case 'checkpoint':
      case 'martyria': {
        const degree = parseDegreeToken(tokens[cursor + 1], diagnostics);
        if (!degree) return;
        note.checkpoint = {
          type: 'martyria',
          degree,
          checkpoint: true,
          source: makeSourceLocation(tokens[cursor]),
        };
        cursor += 2;
        break;
      }
      case 'style': {
        const value = parseNameToken(tokens[cursor + 1], diagnostics, 'style');
        if (!value) return;
        note.qualitative.push({ type: 'style', name: value, source: makeSourceLocation(tokens[cursor]) });
        cursor += 2;
        break;
      }
      case 'quality': {
        const value = parseNameToken(tokens[cursor + 1], diagnostics, 'quality');
        if (!value) return;
        note.qualitative.push({ type: 'quality', name: value, source: makeSourceLocation(tokens[cursor]) });
        cursor += 2;
        break;
      }
      case 'glyph': {
        const value = parseNameToken(tokens[cursor + 1], diagnostics, 'glyph');
        if (!value) return;
        note.display = {
          ...(note.display ?? {}),
          preferredGlyphName: value,
        };
        cursor += 2;
        break;
      }
      case 'lyric': {
        const parsed = parseLyricAttachment(tokens, diagnostics, cursor + 1);
        if (!parsed.attachment) return;
        note.lyric = parsed.attachment;
        cursor = parsed.nextIndex;
        break;
      }
      case 'text': {
        const token = tokens[cursor + 1];
        if (!expectString(token, diagnostics, 'text requires a quoted string.')) return;
        note.lyric = { kind: 'start', text: token.value };
        cursor += 2;
        break;
      }
      case '_':
        note.lyric = { kind: 'continue' };
        cursor += 1;
        break;
      default:
        diagAt(diagnostics, tokens[cursor], 'unknown-note-modifier', `Unknown note modifier "${tokens[cursor].value}".`);
        return;
    }
  }
}

function parseLyricAttachment(tokens, diagnostics, startIndex) {
  const first = tokens[startIndex];
  if (!first) {
    diagAt(diagnostics, tokens[startIndex - 1], 'invalid-lyric', 'lyric requires a quoted string, continue, none, or line-id form.');
    return {};
  }

  if (first.type === 'string') {
    return {
      attachment: { kind: 'start', text: first.value },
      nextIndex: startIndex + 1,
    };
  }

  const firstWord = lower(first);
  if (firstWord === 'continue') {
    return {
      attachment: { kind: 'continue' },
      nextIndex: startIndex + 1,
    };
  }
  if (firstWord === 'none') {
    return {
      attachment: { kind: 'none' },
      nextIndex: startIndex + 1,
    };
  }

  const second = tokens[startIndex + 1];
  if (!second) {
    diagAt(diagnostics, first, 'invalid-lyric', 'lyric line-id form requires a quoted string or continue.');
    return {};
  }
  if (second.type === 'string') {
    return {
      attachment: { kind: 'start', lineId: first.value, text: second.value },
      nextIndex: startIndex + 2,
    };
  }
  if (lower(second) === 'continue') {
    return {
      attachment: { kind: 'continue', lineId: first.value },
      nextIndex: startIndex + 2,
    };
  }
  diagAt(diagnostics, second, 'invalid-lyric', 'lyric line-id form requires a quoted string or continue.');
  return {};
}

function parseRestLine(tokens, diagnostics) {
  const rest = {
    type: 'rest',
    rest: { type: 'rest', sign: 'leimma1' },
    temporal: [],
    source: makeSourceLocation(tokens[0]),
  };

  let cursor = 1;
  while (cursor < tokens.length) {
    const word = lower(tokens[cursor]);
    if (word === 'beats') {
      const value = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'rest beats');
      if (value === undefined) return undefined;
      rest.baseBeats = value;
      cursor += 2;
    } else if (word === 'duration') {
      const value = parsePositiveNumber(tokens[cursor + 1], diagnostics, 'rest duration');
      if (value === undefined) return undefined;
      rest.durationBeats = value;
      cursor += 2;
    } else if (word === 'quick' || word === 'gorgon') {
      rest.temporal.push({ type: 'quick', sign: 'gorgon', source: makeSourceLocation(tokens[cursor]) });
      cursor += 1;
    } else {
      diagAt(diagnostics, tokens[cursor], 'unknown-rest-modifier', `Unknown rest modifier "${tokens[cursor].value}".`);
      return undefined;
    }
  }

  return rest;
}

function parseSilenceAlias(tokens, diagnostics) {
  if (!expectArity(tokens, diagnostics, 2, 'silence requires one duration number.')) return undefined;
  const duration = parsePositiveNumber(tokens[1], diagnostics, 'silence');
  if (duration === undefined) return undefined;
  return {
    type: 'rest',
    rest: { type: 'rest', sign: 'leimma1' },
    temporal: [],
    durationBeats: duration,
    source: makeSourceLocation(tokens[0]),
  };
}

function parseScaleSpec(tokens, diagnostics, startIndex) {
  const scaleToken = tokens[startIndex];
  if (!scaleToken) {
    diagAt(diagnostics, tokens[startIndex - 1], 'invalid-scale', 'scale requires a scale name.');
    return {};
  }
  const scale = normalizeScaleName(scaleToken.value);
  if (!scale) {
    diagAt(diagnostics, scaleToken, 'invalid-scale-name', `Unsupported scale name "${scaleToken.value}".`);
    return {};
  }

  let cursor = startIndex + 1;
  let phase;
  if (cursor < tokens.length) {
    const word = lower(tokens[cursor]);
    if (word === 'phase') {
      phase = parseInteger(tokens[cursor + 1], diagnostics, 'phase');
      if (phase === undefined) return {};
      cursor += 2;
    } else if (word?.startsWith('phase=')) {
      const phaseText = tokens[cursor].value.slice(tokens[cursor].value.indexOf('=') + 1);
      phase = parseInlineInteger(phaseText, tokens[cursor], diagnostics, 'phase');
      if (phase === undefined) return {};
      cursor += 1;
    }
  }

  const definition = scaleDefinition(scale);
  return {
    spec: {
      type: 'pthora',
      scale,
      genus: definition.genus,
      ...(Number.isInteger(phase) ? { phase } : {}),
      source: makeSourceLocation(scaleToken),
    },
    nextIndex: cursor,
  };
}

function parseDegreeToken(token, diagnostics) {
  const degree = normalizeDegree(token?.value);
  if (!degree) {
    diagAt(diagnostics, token, 'invalid-degree', `Expected degree Ni, Pa, Vou, Ga, Di, Ke, or Zo.`);
    return undefined;
  }
  return degree;
}

function parseNameToken(token, diagnostics, label) {
  if (!token || token.type === 'string') {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires an unquoted name.`);
    return undefined;
  }
  return token.value;
}

function parsePositiveNumber(token, diagnostics, label) {
  if (!token || token.type === 'string') {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires a positive number.`);
    return undefined;
  }
  const number = Number(token.value);
  if (!Number.isFinite(number) || number <= 0 || !/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(token.value)) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires a positive number.`);
    return undefined;
  }
  return number;
}

function parseAccidentalMoria(token, diagnostics, label) {
  if (!token || token.type === 'string') {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires a signed even-moria integer.`);
    return undefined;
  }
  if (!/^[+-]?\d+$/.test(token.value)) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires a signed even-moria integer.`);
    return undefined;
  }
  const value = Number(token.value);
  if (value === 0 || value % 2 !== 0) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} must be a non-zero even number of moria.`);
    return undefined;
  }
  return value;
}

function parseAccidentalMagnitude(token, diagnostics, label) {
  if (!token || token.type === 'string') {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires an even-moria magnitude.`);
    return undefined;
  }
  if (!/^\d+$/.test(token.value)) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires an even-moria magnitude.`);
    return undefined;
  }
  const value = Number(token.value);
  if (value === 0 || value % 2 !== 0) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} must be a non-zero even number of moria.`);
    return undefined;
  }
  return value;
}

function parseInteger(token, diagnostics, label) {
  if (!token || token.type === 'string') {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires an integer.`);
    return undefined;
  }
  return parseInlineInteger(token.value, token, diagnostics, label);
}

function parseInlineInteger(value, token, diagnostics, label) {
  if (!/^\d+$/.test(value)) {
    diagAt(diagnostics, token, `invalid-${label}`, `${label} requires an integer.`);
    return undefined;
  }
  return Number(value);
}

function expectArity(tokens, diagnostics, arity, message) {
  if (tokens.length === arity) return true;
  diagAt(diagnostics, tokens[Math.min(tokens.length - 1, arity)] ?? tokens[0], 'invalid-arity', message);
  return false;
}

function expectString(token, diagnostics, message) {
  if (token?.type === 'string') return true;
  diagAt(diagnostics, token, 'expected-string', message);
  return false;
}

function expectEnd(tokens, diagnostics, cursor) {
  if (cursor >= tokens.length) return true;
  diagAt(diagnostics, tokens[cursor], 'unexpected-token', `Unexpected token "${tokens[cursor].value}".`);
  return false;
}

function diagAt(diagnostics, token, code, message) {
  pushDiagnostic(diagnostics, {
    severity: DIAGNOSTIC_SEVERITY.ERROR,
    code,
    message,
    ...tokenLocation(token),
  });
}

function lower(token) {
  return token?.value?.toLowerCase();
}
