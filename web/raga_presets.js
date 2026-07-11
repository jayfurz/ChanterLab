// Raga scale presets (RAGA-01,
// docs/plans/80-scales-and-raga/82-raga-presets-sargam.md).
//
// Intervals are moria steps from Sa (= Reference Ni), 12-ET-snapped onto the
// 72-moria grid and summing to exactly 72 — the closed-genus contract that
// JsTuningGrid.applyCustomGenus enforces. Shruti-true just-intonation
// variants are explicitly deferred to RAGA-04 and need a named source
// reference before shipping.

export const RAGA_PRESETS = [
  { label: 'Bilawal', name: 'Bilawal / Shankarabharanam', intervals: [12, 12, 6, 12, 12, 12, 6] },
  { label: 'Yaman', name: 'Yaman / Kalyani', intervals: [12, 12, 12, 6, 12, 12, 6] },
  { label: 'Kafi', name: 'Kafi / Kharaharapriya', intervals: [12, 6, 12, 12, 12, 6, 12] },
  { label: 'Bhairavi', name: 'Bhairavi / Hanumatodi', intervals: [6, 12, 12, 12, 6, 12, 12] },
  { label: 'Bhairav', name: 'Bhairav / Mayamalavagowla', intervals: [6, 18, 6, 12, 6, 18, 6] },
  { label: 'Todi', name: 'Todi / Shubhapantuvarali', intervals: [6, 12, 18, 6, 6, 18, 6] },
].map(raga => ({
  ...raga,
  genus: 'Custom',
  degree: 'Ni', // Sa sits where Ni sits: the reference anchor.
  canonicalRoot: 'Ni',
  labels: 'sargam',
}));
