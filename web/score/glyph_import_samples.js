export const GLYPH_IMPORT_SAMPLE_FIXTURES = Object.freeze([
  Object.freeze({
    id: 'basic-ladder',
    title: 'Basic Ladder',
    source: 'glyph',
    startDegree: 'Ni',
    bpm: 90,
    text: 'ison oligon oligon apostrofos gorgonAbove leimma2',
  }),
  Object.freeze({
    id: 'soft-chromatic-di',
    title: 'Soft Chromatic Di',
    source: 'glyph',
    startDegree: 'Di',
    bpm: 84,
    text: [
      'fthoraSoftChromaticDiAbove ison',
      'oligon',
      'apostrofos gorgonAbove',
      'oligon',
      'oligon',
      'apostrofos gorgonAbove',
      'apostrofos',
    ].join(' '),
  }),
  Object.freeze({
    id: 'hard-chromatic-pa',
    title: 'Hard Chromatic Pa',
    source: 'glyph',
    startDegree: 'Pa',
    bpm: 84,
    text: [
      'fthoraHardChromaticPaAbove ison',
      'oligon',
      'apostrofos gorgonAbove',
      'oligon',
      'yporroi',
      'leimma1',
    ].join(' '),
  }),
  Object.freeze({
    id: 'sbmufl-basic',
    title: 'SBMuFL Basic',
    source: 'sbmufl',
    startDegree: 'Ni',
    bpm: 90,
    text: '\uE000\uE001\uE001\uE021\uE0F0\uE0E1',
  }),
  Object.freeze({
    id: 'unicode-basic',
    title: 'Unicode Basic',
    source: 'unicode',
    startDegree: 'Ni',
    bpm: 90,
    text: '\u{1D046}\u{1D047}\u{1D047}\u{1D051}\u{1D08F}\u{1D08B}',
  }),
]);

export function listGlyphImportSampleFixtures() {
  return GLYPH_IMPORT_SAMPLE_FIXTURES.map(copyGlyphImportSampleFixture);
}

export function findGlyphImportSampleFixture(id) {
  const sample = GLYPH_IMPORT_SAMPLE_FIXTURES.find(fixture => fixture.id === id);
  return sample ? copyGlyphImportSampleFixture(sample) : undefined;
}

function copyGlyphImportSampleFixture(sample) {
  return { ...sample };
}
