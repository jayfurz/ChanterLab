import {
  createChantScore,
  createTempoEvent,
  degreeFromLinearIndex,
  degreeIndex,
  normalizeDegree,
  normalizeScaleName,
  positiveModulo,
  scaleDefinition,
} from './chant_score.js';
import { compileChantScore } from './compiler.js';
import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

const UNICODE_BYZANTINE_START = 0x1D000;
const UNICODE_BYZANTINE_END = 0x1D0FF;
const PUA_START = 0xE000;
const PUA_END = 0xF8FF;
const GLYPH_TEXT_GROUP_SEPARATORS = new Set(['|']);

const GLYPH_METADATA = Object.freeze({
  ison: quantity('ison', 'U+E000', 'U+1D046', 'same', 0),
  oligon: quantity('oligon', 'U+E001', 'U+1D047', 'up', 1),
  apostrofos: quantity('apostrofos', 'U+E021', 'U+1D051', 'down', 1),
  yporroi: quantity('yporroi', 'U+E023', 'U+1D053', 'down', 2),
  elafron: quantity('elafron', 'U+E024', 'U+1D055', 'down', 2),
  chamili: quantity('chamili', 'U+E027', 'U+1D056', 'down', 4),

  leimma1: rest('leimma1', 'U+E0E0', 'U+1D08A', 1),
  leimma2: rest('leimma2', 'U+E0E1', 'U+1D08B', 2),
  leimma3: rest('leimma3', 'U+E0E2', 'U+1D08C', 3),
  leimma4: rest('leimma4', 'U+E0E3', 'U+1D08D', 4),

  gorgonAbove: temporal('gorgonAbove', 'U+E0F0', 'U+1D08F', { type: 'quick', sign: 'gorgon' }),
  digorgon: temporal('digorgon', 'U+E0F4', 'U+1D092', { type: 'divide', divide: 3, sign: 'digorgon' }),
  trigorgon: temporal('trigorgon', 'U+E0F8', 'U+1D096', { type: 'divide', divide: 4, sign: 'trigorgon' }),
  argon: temporal('argon', 'U+E0FC', 'U+1D097', { type: 'unsupported', sign: 'argon' }),

  apli: duration('apli', undefined, undefined, 2),
  klasma: duration('klasma', undefined, undefined, 2),
  dipli: duration('dipli', undefined, undefined, 3),
  tripli: duration('tripli', undefined, undefined, 4),

  agogiMetria: tempo('agogiMetria', 'U+E123', 'U+1D09D', 'moderate'),
  agogiGorgi: tempo('agogiGorgi', 'U+E125', 'U+1D09F', 'swift'),

  fthoraHardChromaticPaAbove: pthora('fthoraHardChromaticPaAbove', 'U+E198', undefined, 'hard-chromatic', 'Pa'),
  fthoraHardChromaticDiAbove: pthora('fthoraHardChromaticDiAbove', 'U+E199', undefined, 'hard-chromatic', 'Di'),
  fthoraSoftChromaticDiAbove: pthora('fthoraSoftChromaticDiAbove', 'U+E19A', undefined, 'soft-chromatic', 'Di'),
  fthoraSoftChromaticKeAbove: pthora('fthoraSoftChromaticKeAbove', 'U+E19B', undefined, 'soft-chromatic', 'Ke'),

  chroaZygosAbove: qualitative('chroaZygosAbove', 'U+E19D', undefined, 'zygos'),
  chroaKlitonAbove: qualitative('chroaKlitonAbove', 'U+E19E', undefined, 'kliton'),
  chroaSpathiAbove: qualitative('chroaSpathiAbove', 'U+E19F', undefined, 'spathi'),
});

const GLYPH_BY_NAME = new Map(Object.entries(GLYPH_METADATA));
const GLYPH_BY_CODEPOINT = new Map();
for (const metadata of Object.values(GLYPH_METADATA)) {
  for (const codepoint of [metadata.codepoint, metadata.alternateCodepoint]) {
    if (codepoint && !GLYPH_BY_CODEPOINT.has(codepoint)) {
      GLYPH_BY_CODEPOINT.set(codepoint, metadata);
    }
  }
}

export function semanticTokensFromGlyphs(inputs, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const tokens = Array.isArray(inputs) ? inputs : [inputs];
  return tokens.map((input, index) => semanticTokenFromGlyph(input, {
    diagnostics,
    index,
    source: options.source,
  }));
}

export function semanticTokenFromGlyph(input, options = {}) {
  if (input?.kind && input?.value && Array.isArray(input?.source)) {
    return input;
  }

  const diagnostics = options.diagnostics ?? [];
  const sourceToken = normalizeGlyphSourceToken(input, {
    index: options.index,
    source: options.source,
  });
  const metadata = glyphMetadataForSource(sourceToken);
  if (!metadata) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-unknown',
      message: `Unknown glyph token "${sourceToken.raw}".`,
      source: sourceToken,
    });
    return {
      kind: 'unknown',
      value: {},
      source: [sourceToken],
    };
  }

  const enrichedSource = {
    ...sourceToken,
    glyphName: sourceToken.glyphName ?? metadata.glyphName,
    codepoint: sourceToken.codepoint ?? metadata.codepoint,
    alternateCodepoint: sourceToken.alternateCodepoint ?? metadata.alternateCodepoint,
  };

  if (metadata.role === 'quantity') {
    return semanticToken('quantity', {
      glyphName: metadata.glyphName,
      movement: { ...metadata.movement },
    }, enrichedSource);
  }
  if (metadata.role === 'rest') {
    return semanticToken('rest', {
      sign: metadata.glyphName,
      beats: metadata.beats,
    }, enrichedSource);
  }
  if (metadata.role === 'temporal') {
    return semanticToken('temporal', { ...metadata.temporal }, enrichedSource);
  }
  if (metadata.role === 'duration') {
    return semanticToken('duration', {
      sign: metadata.glyphName,
      beats: metadata.beats,
    }, enrichedSource);
  }
  if (metadata.role === 'tempo') {
    return semanticToken('tempo', {
      tempoName: metadata.tempoName,
    }, enrichedSource);
  }
  if (metadata.role === 'pthora') {
    return semanticToken('pthora', {
      glyphName: metadata.glyphName,
      scale: metadata.scale,
      glyphDegree: metadata.glyphDegree,
      generatorRoot: chromaticGeneratorRoot(metadata.scale),
    }, enrichedSource);
  }
  if (metadata.role === 'qualitative') {
    return semanticToken('qualitative', {
      glyphName: metadata.glyphName,
      name: metadata.quality,
    }, enrichedSource);
  }

  pushDiagnostic(diagnostics, {
    severity: DIAGNOSTIC_SEVERITY.ERROR,
    code: 'glyph-import-role-unsupported',
    message: `Unsupported glyph role "${metadata.role}" for "${metadata.glyphName}".`,
    source: enrichedSource,
  });
  return {
    kind: 'unknown',
    value: {},
    source: [enrichedSource],
  };
}

export function normalizeGlyphSourceToken(input, options = {}) {
  if (input?.source && input?.raw && (input?.glyphName || input?.codepoint)) {
    return input;
  }

  const raw = rawGlyphText(input);
  const explicitCodepoint = normalizeCodepoint(input?.codepoint);
  const rawCodepoint = normalizeCodepoint(raw);
  const sourceCodepoint = explicitCodepoint ?? rawCodepoint ?? codepointFromCharacter(raw);
  const explicitGlyphName = typeof input?.glyphName === 'string'
    ? input.glyphName
    : undefined;
  const metadataByCodepoint = sourceCodepoint ? GLYPH_BY_CODEPOINT.get(sourceCodepoint) : undefined;
  const glyphName = explicitGlyphName ?? metadataByCodepoint?.glyphName ?? glyphNameFromRaw(raw);
  const metadataByName = glyphName ? GLYPH_BY_NAME.get(glyphName) : undefined;
  const codepoint = sourceCodepoint ?? metadataByName?.codepoint;
  const source = input?.source ?? options.source ?? inferSourceKind(sourceCodepoint);

  return {
    source,
    raw,
    ...(codepoint ? { codepoint } : {}),
    ...(glyphName ? { glyphName } : {}),
    ...(metadataByName?.alternateCodepoint || metadataByCodepoint?.alternateCodepoint
      ? { alternateCodepoint: metadataByName?.alternateCodepoint ?? metadataByCodepoint?.alternateCodepoint }
      : {}),
    ...(input?.span
      ? { span: input.span }
      : Number.isInteger(options.index) ? { span: { start: options.index, end: options.index + 1 } } : {}),
  };
}

export function sourceTokensFromGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  if (typeof text !== 'string') {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-text-invalid',
      message: 'Glyph text import requires a string input.',
    });
    return [];
  }

  return tokenizeGlyphText(text)
    .filter(token => token.type === 'glyph')
    .map((token, index) => normalizeGlyphSourceToken({
      raw: token.raw,
      ...(options.source ? { source: options.source } : {}),
      span: token.span,
    }, { index }));
}

export function semanticTokenGroupsFromGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const items = tokenizeGlyphText(text);
  const semanticItems = [];
  let glyphIndex = 0;

  for (const item of items) {
    if (item.type === 'separator') {
      semanticItems.push({ kind: 'separator', source: item });
      continue;
    }
    if (item.type !== 'glyph') continue;
    semanticItems.push(semanticTokenFromGlyph({
      raw: item.raw,
      ...(options.source ? { source: options.source } : {}),
      span: item.span,
    }, {
      diagnostics,
      index: glyphIndex,
    }));
    glyphIndex += 1;
  }

  return groupSemanticGlyphTokens(semanticItems, diagnostics);
}

export function chantScoreFromGlyphGroups(groups, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const semanticGroups = normalizeGlyphGroups(groups, diagnostics);
  const score = createChantScore();
  score.title = options.title ?? 'Imported Glyph Score';
  score.timingMode = options.timingMode ?? 'symbolic';
  score.orthography = options.orthography ?? 'generated';
  score.initialMartyria = {
    type: 'martyria',
    degree: normalizeDegree(options.startDegree) ?? 'Ni',
    source: importSource({ kind: 'initial-martyria' }),
  };
  score.initialScale = scaleSpec(options.scale ?? 'diatonic', {
    phase: options.phase,
    source: importSource({ kind: 'initial-scale' }),
  });

  const initialTempo = createTempoEvent({
    tempoName: options.tempoName ?? 'moderate',
    bpm: Number.isFinite(options.bpm) ? options.bpm : undefined,
    source: importSource({ kind: 'initial-tempo' }),
  });
  score.defaultTempoBpm = Number.isFinite(initialTempo.workingBpm)
    ? initialTempo.workingBpm
    : score.defaultTempoBpm;
  score.defaultAgogi = initialTempo.agogi;
  score.tempoPolicy = {
    source: 'glyph-import',
    bpm: score.defaultTempoBpm,
    ...(initialTempo.tempoName ? { tempoName: initialTempo.tempoName } : {}),
  };

  const defaultDrone = normalizeDegree(options.defaultDrone);
  if (defaultDrone) {
    score.defaultDrone = defaultDrone;
    score.defaultDroneRegister = Number.isInteger(options.defaultDroneRegister)
      ? options.defaultDroneRegister
      : 0;
  }

  let currentLinear = degreeIndex(score.initialMartyria.degree);
  for (const group of semanticGroups) {
    const event = scoreEventFromSemanticGroup(group, {
      diagnostics,
      currentLinear,
    });
    if (!event) continue;
    if (event.type === 'neume') {
      currentLinear += movementDelta(event.movement);
    }
    score.events.push(event);
  }

  return { score, semanticGroups, diagnostics };
}

export function compileGlyphGroups(groups, options = {}) {
  const imported = chantScoreFromGlyphGroups(groups, options);
  const compiled = compileChantScore(imported.score, {
    ...options,
    diagnostics: [...imported.diagnostics],
  });
  return {
    ...compiled,
    imported,
  };
}

export function compileGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const semanticGroups = semanticTokenGroupsFromGlyphText(text, {
    ...options,
    diagnostics,
  });
  return compileGlyphGroups(semanticGroups, {
    ...options,
    diagnostics,
  });
}

export function compileSbmuflGlyphText(text, options = {}) {
  return compileGlyphText(text, {
    ...options,
    source: options.source ?? 'sbmufl-pua',
  });
}

export function compileUnicodeByzantineText(text, options = {}) {
  return compileGlyphText(text, {
    ...options,
    source: options.source ?? 'unicode-byzantine',
  });
}

export function listMinimalGlyphImportTokens() {
  return Object.values(GLYPH_METADATA).map(publicGlyphImportToken);
}

function scoreEventFromSemanticGroup(group, context) {
  const diagnostics = context.diagnostics;
  const quantityTokens = group.filter(token => token.kind === 'quantity');
  const restTokens = group.filter(token => token.kind === 'rest');
  const tempoTokens = group.filter(token => token.kind === 'tempo');
  const pthoraTokens = group.filter(token => token.kind === 'pthora');
  const temporalTokens = group.filter(token => token.kind === 'temporal');
  const durationTokens = group.filter(token => token.kind === 'duration');
  const qualitativeTokens = group.filter(token => token.kind === 'qualitative');
  const unknown = group.find(token => token.kind === 'unknown');
  if (unknown) return undefined;

  if (quantityTokens.length > 1 || restTokens.length > 1) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-ambiguous',
      message: 'A glyph group may contain only one quantity or rest sign in this importer phase.',
      source: groupSource(group),
    });
    return undefined;
  }
  if (quantityTokens.length && restTokens.length) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-ambiguous',
      message: 'A glyph group cannot contain both a quantity sign and a rest sign.',
      source: groupSource(group),
    });
    return undefined;
  }

  if (tempoTokens.length && !quantityTokens.length && !restTokens.length) {
    return createTempoEvent({
      tempoName: tempoTokens.at(-1).value.tempoName,
      source: groupSource(group),
    });
  }

  if (restTokens.length) {
    return {
      type: 'rest',
      rest: { type: 'rest', sign: restTokens[0].value.sign },
      temporal: temporalEvents(temporalTokens, diagnostics),
      baseBeats: durationTokens.at(-1)?.value.beats ?? restTokens[0].value.beats,
      source: groupSource(group),
    };
  }

  if (!quantityTokens.length) {
    if (pthoraTokens.length) {
      const currentDegree = degreeFromLinearIndex(context.currentLinear);
      return pthoraEventFromToken(pthoraTokens.at(-1), currentDegree);
    }
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-missing-quantity',
      message: 'A glyph group needs a quantity, rest, tempo, or pthora sign.',
      source: groupSource(group),
    });
    return undefined;
  }

  const quantity = quantityTokens[0];
  const nextLinear = context.currentLinear + movementDelta(quantity.value.movement);
  const attachedDegree = degreeFromLinearIndex(nextLinear);
  const pthoraToken = pthoraTokens.at(-1);
  const temporal = temporalEvents(temporalTokens, diagnostics);
  const unsupportedTemporal = temporal.find(sign => sign.type === 'unsupported');
  if (unsupportedTemporal) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.WARNING,
      code: 'glyph-import-temporal-unsupported',
      message: `${unsupportedTemporal.sign} is preserved as a qualitative sign; timing rewrite is not implemented yet.`,
      source: groupSource(group),
    });
  }

  return {
    type: 'neume',
    movement: { ...quantity.value.movement },
    temporal: temporal.filter(sign => sign.type !== 'unsupported'),
    qualitative: [
      ...qualitativeTokens.map(token => ({
        type: 'quality',
        name: token.value.name,
        source: tokenSource(token),
      })),
      ...temporal
        .filter(sign => sign.type === 'unsupported')
        .map(sign => ({
          type: 'quality',
          name: sign.sign,
          source: groupSource(group),
        })),
    ],
    ...(durationTokens.length ? { baseBeats: durationTokens.at(-1).value.beats } : {}),
    ...(pthoraToken ? { pthora: pthoraSpecFromToken(pthoraToken, attachedDegree) } : {}),
    display: {
      preferredGlyphName: quantity.value.glyphName,
    },
    source: groupSource(group),
  };
}

function temporalEvents(tokens, diagnostics) {
  return tokens.map(token => {
    const temporal = { ...token.value };
    if (temporal.type === 'unsupported') return temporal;
    if (temporal.type !== 'quick' && temporal.type !== 'divide') {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'glyph-import-temporal-invalid',
        message: `Unsupported temporal token "${temporal.sign}".`,
        source: tokenSource(token),
      });
    }
    return {
      ...temporal,
      source: tokenSource(token),
    };
  });
}

function pthoraEventFromToken(token, attachedDegree) {
  const spec = pthoraSpecFromToken(token, attachedDegree);
  return {
    ...spec,
    degree: attachedDegree,
  };
}

function pthoraSpecFromToken(token, attachedDegree) {
  const scale = normalizeScaleName(token.value.scale) ?? 'diatonic';
  const definition = scaleDefinition(scale);
  const phase = inferPthoraPhase(token.value, attachedDegree);
  return {
    type: 'pthora',
    scale,
    genus: definition.genus,
    ...(Number.isInteger(phase) ? { phase } : {}),
    source: tokenSource(token),
  };
}

export function inferPthoraPhase(pthoraValue, attachedDegree) {
  const root = chromaticGeneratorRoot(pthoraValue?.scale);
  const rootIndex = degreeIndex(root);
  const attachedIndex = degreeIndex(attachedDegree);
  if (rootIndex < 0 || attachedIndex < 0) return undefined;
  return positiveModulo(attachedIndex - rootIndex, 4);
}

function normalizeGlyphGroups(groups, diagnostics) {
  return (Array.isArray(groups) ? groups : [])
    .map(group => {
      const inputs = Array.isArray(group) ? group : [group];
      return semanticTokensFromGlyphs(inputs, { diagnostics });
    });
}

function groupSemanticGlyphTokens(tokens, diagnostics) {
  const groups = [];
  let current = [];
  let pending = [];

  const flushCurrent = () => {
    if (current.length) groups.push(current);
    current = [];
  };

  for (const token of tokens) {
    if (token.kind === 'separator') {
      flushCurrent();
      if (pending.length) {
        groups.push(pending);
        pending = [];
      }
      continue;
    }

    if (isGroupAnchor(token)) {
      flushCurrent();
      current = [...pending, token];
      pending = [];
      continue;
    }

    if (isGroupModifier(token)) {
      if (current.length && current.some(isGroupAnchor)) current.push(token);
      else pending.push(token);
      continue;
    }

    flushCurrent();
    groups.push([...pending, token]);
    pending = [];
  }

  flushCurrent();
  if (pending.length) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-unattached-modifier',
      message: 'Glyph modifiers without a quantity or rest sign cannot be imported unambiguously.',
      source: groupSource(pending),
    });
    groups.push(pending);
  }

  return groups;
}

function isGroupAnchor(token) {
  return token?.kind === 'quantity' || token?.kind === 'rest' || token?.kind === 'tempo';
}

function isGroupModifier(token) {
  return token?.kind === 'temporal'
    || token?.kind === 'duration'
    || token?.kind === 'pthora'
    || token?.kind === 'qualitative';
}

function tokenizeGlyphText(text) {
  const chars = Array.from(text ?? '');
  const tokens = [];
  let cursor = 0;

  const pushWord = start => {
    let end = start;
    while (end < chars.length && isWordGlyphChar(chars[end])) end += 1;
    tokens.push({
      type: 'glyph',
      raw: chars.slice(start, end).join(''),
      span: { start, end },
    });
    return end;
  };

  while (cursor < chars.length) {
    const char = chars[cursor];
    if (char === '\n' || char === '\r' || GLYPH_TEXT_GROUP_SEPARATORS.has(char)) {
      tokens.push({ type: 'separator', raw: char, span: { start: cursor, end: cursor + 1 } });
      cursor += 1;
      continue;
    }
    if (/\s|,/.test(char)) {
      cursor += 1;
      continue;
    }
    if (isGlyphTextWordStart(char)) {
      cursor = pushWord(cursor);
      continue;
    }
    tokens.push({
      type: 'glyph',
      raw: char,
      span: { start: cursor, end: cursor + 1 },
    });
    cursor += 1;
  }

  return tokens;
}

function isGlyphTextWordStart(char) {
  return /[A-Za-z_]/.test(char);
}

function isWordGlyphChar(char) {
  return /[A-Za-z0-9_+\-]/.test(char);
}

function glyphMetadataForSource(sourceToken) {
  if (sourceToken.glyphName && GLYPH_BY_NAME.has(sourceToken.glyphName)) {
    return GLYPH_BY_NAME.get(sourceToken.glyphName);
  }
  if (sourceToken.codepoint && GLYPH_BY_CODEPOINT.has(sourceToken.codepoint)) {
    return GLYPH_BY_CODEPOINT.get(sourceToken.codepoint);
  }
  return undefined;
}

function scaleSpec(scaleName, { phase, source } = {}) {
  const scale = normalizeScaleName(scaleName) ?? 'diatonic';
  const definition = scaleDefinition(scale);
  return {
    type: 'pthora',
    scale,
    genus: definition.genus,
    ...(Number.isInteger(phase) ? { phase } : {}),
    ...(source ? { source } : {}),
  };
}

function movementDelta(movement) {
  if (movement?.direction === 'up') return movement.steps ?? 1;
  if (movement?.direction === 'down') return -(movement.steps ?? 1);
  return 0;
}

function groupSource(group) {
  return importSource({
    tokens: group.flatMap(token => token.source ?? []),
  });
}

function tokenSource(token) {
  return importSource({
    tokens: token?.source ?? [],
  });
}

function importSource(detail) {
  return {
    source: {
      kind: 'glyph-import',
      ...detail,
    },
  };
}

function semanticToken(kind, value, sourceToken) {
  return {
    kind,
    value,
    source: [sourceToken],
  };
}

function quantity(glyphName, codepoint, alternateCodepoint, direction, steps) {
  return {
    role: 'quantity',
    glyphName,
    codepoint,
    alternateCodepoint,
    movement: { direction, steps },
  };
}

function rest(glyphName, codepoint, alternateCodepoint, beats) {
  return { role: 'rest', glyphName, codepoint, alternateCodepoint, beats };
}

function temporal(glyphName, codepoint, alternateCodepoint, value) {
  return { role: 'temporal', glyphName, codepoint, alternateCodepoint, temporal: value };
}

function duration(glyphName, codepoint, alternateCodepoint, beats) {
  return { role: 'duration', glyphName, codepoint, alternateCodepoint, beats };
}

function tempo(glyphName, codepoint, alternateCodepoint, tempoName) {
  return { role: 'tempo', glyphName, codepoint, alternateCodepoint, tempoName };
}

function pthora(glyphName, codepoint, alternateCodepoint, scale, glyphDegree) {
  return { role: 'pthora', glyphName, codepoint, alternateCodepoint, scale, glyphDegree };
}

function qualitative(glyphName, codepoint, alternateCodepoint, quality) {
  return { role: 'qualitative', glyphName, codepoint, alternateCodepoint, quality };
}

function chromaticGeneratorRoot(scale) {
  const normalized = normalizeScaleName(scale);
  if (normalized === 'hard-chromatic') return 'Pa';
  return 'Ni';
}

function rawGlyphText(input) {
  if (typeof input === 'string') return input;
  if (typeof input?.raw === 'string') return input.raw;
  if (typeof input?.glyphName === 'string') return input.glyphName;
  if (typeof input?.codepoint === 'string') return input.codepoint;
  return String(input ?? '');
}

function glyphNameFromRaw(raw) {
  return GLYPH_BY_NAME.has(raw) ? raw : undefined;
}

function normalizeCodepoint(value) {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim().toUpperCase();
  if (!/^U\+[0-9A-F]{4,6}$/.test(trimmed)) return undefined;
  return trimmed;
}

function codepointFromCharacter(raw) {
  if (typeof raw !== 'string') return undefined;
  const chars = Array.from(raw);
  if (chars.length !== 1) return undefined;
  const value = chars[0].codePointAt(0);
  if (!Number.isInteger(value)) return undefined;
  return `U+${value.toString(16).toUpperCase().padStart(4, '0')}`;
}

function inferSourceKind(codepoint) {
  const value = numericCodepoint(codepoint);
  if (value >= UNICODE_BYZANTINE_START && value <= UNICODE_BYZANTINE_END) return 'unicode-byzantine';
  if (value >= PUA_START && value <= PUA_END) return 'sbmufl-pua';
  return 'glyph-name';
}

function numericCodepoint(codepoint) {
  const normalized = normalizeCodepoint(codepoint);
  return normalized ? Number.parseInt(normalized.slice(2), 16) : NaN;
}

function publicGlyphImportToken(metadata) {
  return {
    glyphName: metadata.glyphName,
    role: metadata.role,
    ...(metadata.codepoint ? { codepoint: metadata.codepoint } : {}),
    ...(metadata.alternateCodepoint ? { alternateCodepoint: metadata.alternateCodepoint } : {}),
    ...(metadata.movement ? { movement: { ...metadata.movement } } : {}),
    ...(Number.isFinite(metadata.beats) ? { beats: metadata.beats } : {}),
    ...(metadata.temporal ? { temporal: { ...metadata.temporal } } : {}),
    ...(metadata.tempoName ? { tempoName: metadata.tempoName } : {}),
    ...(metadata.scale ? { scale: metadata.scale } : {}),
    ...(metadata.glyphDegree ? { glyphDegree: metadata.glyphDegree } : {}),
    ...(metadata.quality ? { quality: metadata.quality } : {}),
  };
}

export const MINIMAL_GLYPH_IMPORT_METADATA = GLYPH_METADATA;
