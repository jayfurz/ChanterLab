export const DEGREE_NAMES = Object.freeze(['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo']);

const DEGREE_LOOKUP = new Map(DEGREE_NAMES.map(name => [name.toLowerCase(), name]));
const REFERENCE_DIATONIC_MORIA = Object.freeze({
  Ni: 0,
  Pa: 12,
  Vou: 22,
  Ga: 30,
  Di: 42,
  Ke: 54,
  Zo: 64,
});

export const SCALE_DEFINITIONS = Object.freeze({
  diatonic: Object.freeze({
    name: 'diatonic',
    displayName: 'Diatonic',
    genus: 'Diatonic',
    intervals: Object.freeze([12, 10, 8, 12, 12, 10, 8]),
    cycle: false,
  }),
  western: Object.freeze({
    name: 'western',
    displayName: 'Western',
    genus: 'Western',
    intervals: Object.freeze([12, 12, 6, 12, 12, 12, 6]),
    cycle: false,
  }),
  'soft-chromatic': Object.freeze({
    name: 'soft-chromatic',
    displayName: 'Soft Chromatic',
    genus: 'SoftChromatic',
    intervals: Object.freeze([8, 14, 8, 12]),
    cycle: true,
  }),
  'hard-chromatic': Object.freeze({
    name: 'hard-chromatic',
    displayName: 'Hard Chromatic',
    genus: 'HardChromatic',
    intervals: Object.freeze([6, 20, 4, 12]),
    cycle: true,
  }),
});

const SCALE_ALIASES = new Map([
  ['diatonic', 'diatonic'],
  ['western', 'western'],
  ['soft-chromatic', 'soft-chromatic'],
  ['softchromatic', 'soft-chromatic'],
  ['soft_chromatic', 'soft-chromatic'],
  ['hard-chromatic', 'hard-chromatic'],
  ['hardchromatic', 'hard-chromatic'],
  ['hard_chromatic', 'hard-chromatic'],
]);

export const AGOGI_TEMPO_MAP = Object.freeze({
  'very-slow': Object.freeze({
    key: 'very-slow',
    name: 'very-slow',
    agogiName: 'agogiPoliArgi',
    codepoint: 'U+1D09A',
    sbmufl: Object.freeze(['U+E120', 'U+E128']),
    bpmRange: Object.freeze([56, 80]),
    defaultBpm: 68,
    enabled: true,
  }),
  slower: Object.freeze({
    key: 'slower',
    name: 'slower',
    agogiName: 'agogiArgoteri',
    codepoint: 'U+1D09B',
    sbmufl: Object.freeze(['U+E121', 'U+E129']),
    bpmRange: Object.freeze([80, 100]),
    defaultBpm: 90,
    enabled: true,
  }),
  slow: Object.freeze({
    key: 'slow',
    name: 'slow',
    agogiName: 'agogiArgi',
    codepoint: 'U+1D09C',
    sbmufl: Object.freeze(['U+E122', 'U+E12A']),
    bpmRange: Object.freeze([100, 168]),
    defaultBpm: 120,
    enabled: true,
  }),
  moderate: Object.freeze({
    key: 'moderate',
    name: 'moderate',
    agogiName: 'agogiMetria',
    codepoint: 'U+1D09D',
    sbmufl: Object.freeze(['U+E123', 'U+E12B']),
    bpmRange: Object.freeze([120, 144]),
    defaultBpm: 132,
    enabled: true,
    provisionalRange: true,
  }),
  medium: Object.freeze({
    key: 'medium',
    name: 'medium',
    agogiName: 'agogiMesi',
    codepoint: 'U+1D09E',
    sbmufl: Object.freeze(['U+E124', 'U+E12C']),
    bpmRange: Object.freeze([120, 144]),
    defaultBpm: 132,
    enabled: true,
    provisionalRange: true,
  }),
  swift: Object.freeze({
    key: 'swift',
    name: 'swift',
    agogiName: 'agogiGorgi',
    codepoint: 'U+1D09F',
    sbmufl: Object.freeze(['U+E125', 'U+E12D']),
    bpmRange: Object.freeze([168, 208]),
    defaultBpm: 184,
    enabled: true,
  }),
  swifter: Object.freeze({
    key: 'swifter',
    name: 'swifter',
    agogiName: 'agogiGorgoteri',
    codepoint: 'U+1D0A0',
    sbmufl: Object.freeze(['U+E126', 'U+E12E']),
    bpmRange: Object.freeze([208, 240]),
    defaultBpm: 216,
    enabled: true,
    openEndedUpperRange: true,
  }),
  'very-swift': Object.freeze({
    key: 'very-swift',
    name: 'very-swift',
    agogiName: 'agogiPoliGorgi',
    codepoint: 'U+1D0A1',
    sbmufl: Object.freeze(['U+E127', 'U+E12F']),
    bpmRange: Object.freeze([240, 288]),
    defaultBpm: 252,
    enabled: false,
    provisionalRange: true,
  }),
});

const TEMPO_ALIASES = new Map([
  ['very-slow', 'very-slow'],
  ['poli-argi', 'very-slow'],
  ['slower', 'slower'],
  ['argoteri', 'slower'],
  ['slow', 'slow'],
  ['argi', 'slow'],
  ['moderate', 'moderate'],
  ['metria', 'moderate'],
  ['medium', 'medium'],
  ['mesi', 'medium'],
  ['swift', 'swift'],
  ['gorgi', 'swift'],
  ['swifter', 'swifter'],
  ['gorgoteri', 'swifter'],
  ['very-swift', 'very-swift'],
  ['poli-gorgi', 'very-swift'],
]);

export const DEFAULT_TEMPO_BPM = AGOGI_TEMPO_MAP.moderate.defaultBpm;

export function createChantScore() {
  return {
    type: 'chant-score',
    formatVersion: 0,
    title: undefined,
    mode: undefined,
    language: undefined,
    lyrics: [],
    translations: [],
    timingMode: 'symbolic',
    orthography: 'generated',
    defaultAgogi: undefined,
    defaultTempoBpm: DEFAULT_TEMPO_BPM,
    tempoPolicy: { source: 'default', bpm: DEFAULT_TEMPO_BPM },
    initialMartyria: undefined,
    initialScale: undefined,
    defaultDrone: undefined,
    defaultDroneRegister: undefined,
    events: [],
  };
}

export function normalizeDegree(value) {
  if (typeof value !== 'string') return undefined;
  return DEGREE_LOOKUP.get(value.toLowerCase());
}

export function degreeIndex(degree) {
  const normalized = normalizeDegree(degree);
  return normalized ? DEGREE_NAMES.indexOf(normalized) : -1;
}

export function degreeFromLinearIndex(linearIndex) {
  return DEGREE_NAMES[positiveModulo(linearIndex, DEGREE_NAMES.length)];
}

export function referenceMoriaForDegree(degree) {
  const normalized = normalizeDegree(degree);
  return normalized ? REFERENCE_DIATONIC_MORIA[normalized] : 0;
}

export function registerFromLinearIndex(linearIndex) {
  return Math.floor(linearIndex / DEGREE_NAMES.length);
}

export function normalizeScaleName(value) {
  if (typeof value !== 'string') return undefined;
  const key = value.toLowerCase();
  return SCALE_ALIASES.get(key);
}

export function scaleDefinition(value) {
  const key = normalizeScaleName(value);
  return key ? SCALE_DEFINITIONS[key] : undefined;
}

export function normalizeTempoName(value) {
  if (typeof value !== 'string') return undefined;
  return TEMPO_ALIASES.get(value.toLowerCase());
}

export function tempoDefinition(value) {
  const key = normalizeTempoName(value);
  return key ? AGOGI_TEMPO_MAP[key] : undefined;
}

export function createTempoEvent({ tempoName, bpm, source } = {}) {
  const definition = tempoDefinition(tempoName);
  const workingBpm = Number.isFinite(bpm) ? bpm : definition?.defaultBpm;
  return {
    type: 'tempo',
    ...(definition
      ? {
          tempoName: definition.key,
          agogi: {
            codepoint: definition.codepoint,
            name: definition.agogiName,
            bpmRange: [...definition.bpmRange],
            enabled: definition.enabled,
            ...(definition.provisionalRange ? { provisionalRange: true } : {}),
            ...(definition.openEndedUpperRange ? { openEndedUpperRange: true } : {}),
          },
          bpmRange: [...definition.bpmRange],
        }
      : {}),
    workingBpm,
    temporary: false,
    ...(source ? { source } : {}),
  };
}

export function positiveModulo(value, modulus) {
  return ((value % modulus) + modulus) % modulus;
}

export function makeSourceLocation(token) {
  if (!token) return undefined;
  return {
    line: token.line,
    column: token.column,
    endColumn: token.endColumn,
  };
}
