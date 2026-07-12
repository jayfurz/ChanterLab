// Raga scale presets (RAGA-01,
// docs/plans/80-scales-and-raga/82-raga-presets-sargam.md).
//
// Hindustani naming per owner decision 2026-07-11 (Carnatic melakarta
// equivalents noted per row for reference only). Intervals are moria steps
// from Sa (= Reference Ni), 12-ET-snapped onto the 72-moria grid and summing
// to exactly 72 — the closed-genus contract that
// JsTuningGrid.applyCustomGenus enforces. Shruti-true just-intonation
// variants are explicitly deferred to RAGA-04 and need a named source
// reference before shipping.

export const RAGA_PRESETS = [
  { label: 'Bilawal', intervals: [12, 12, 6, 12, 12, 12, 6] },  // Shankarabharanam
  { label: 'Yaman', intervals: [12, 12, 12, 6, 12, 12, 6] },    // Kalyani
  { label: 'Kafi', intervals: [12, 6, 12, 12, 12, 6, 12] },     // Kharaharapriya
  { label: 'Bhairavi', intervals: [6, 12, 12, 12, 6, 12, 12] }, // Hanumatodi
  { label: 'Bhairav', intervals: [6, 18, 6, 12, 6, 18, 6] },    // Mayamalavagowla
  { label: 'Todi', intervals: [6, 12, 18, 6, 6, 18, 6] },       // Shubhapantuvarali
].map(raga => ({
  ...raga,
  name: `Raga ${raga.label}`,
  genus: 'Custom',
  degree: 'Ni', // Sa sits where Ni sits: the reference anchor.
  canonicalRoot: 'Ni',
}));
