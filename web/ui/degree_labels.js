// Display-only degree-name mapping (RAGA-01,
// docs/plans/80-scales-and-raga/82-raga-presets-sargam.md).
//
// Engine values, dataset attributes, payloads, and saved state stay on the
// Byzantine names; remap happens at the last moment before text hits the
// screen. The two systems reuse letters with clashing meanings — Byzantine
// Ni/Pa/Ga are degrees 1/2/4 while sargam Ni/Pa/Ga are 7/5/3 — so a value
// that leaked through this layer into the engine would land on the wrong
// degree, not error.

const BYZ_TO_SARGAM = {
  Ni: 'Sa',
  Pa: 'Re',
  Vou: 'Ga',
  Ga: 'Ma',
  Di: 'Pa',
  Ke: 'Dha',
  Zo: 'Ni',
};

const DEGREE_TOKEN = /\b(Ni|Pa|Vou|Ga|Di|Ke|Zo)\b/g;

let mode = 'byzantine';

export function setLabelMode(next) {
  mode = next === 'sargam' ? 'sargam' : 'byzantine';
}

export function getLabelMode() {
  return mode;
}

/** Map a single degree name for display. Unknown values pass through. */
export function degreeLabel(degree) {
  return mode === 'sargam' ? (BYZ_TO_SARGAM[degree] ?? degree) : degree;
}

/** Map standalone degree tokens inside composite text (e.g. "Hold Ni"). */
export function degreeLabelText(text) {
  if (mode !== 'sargam' || typeof text !== 'string') return text;
  return text.replace(DEGREE_TOKEN, d => BYZ_TO_SARGAM[d]);
}
