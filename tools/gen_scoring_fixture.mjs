// Regenerates tests/fixtures/scoring_cases.json: random lap-scoring cases with
// the answers training-prototype/scoring.js gives. src/scoring.rs must agree.
//   node tools/gen_scoring_fixture.mjs
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
const S = createRequire(import.meta.url)('../training-prototype/scoring.js');

let seed = 20261116;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);
const r3 = (x) => Math.round(x * 1000) / 1000;

const cases = [];
for (let c = 0; c < 48; c++) {
  const targets = [];
  const samples = [];
  let t = 0;
  for (let i = 0, n = 3 + Math.floor(rnd() * 8); i < n; i++) {
    const dur = [0.08, 0.15, 0.3, 0.5, 1.0, 1.6][Math.floor(rnd() * 6)];
    const midi = 48 + Math.floor(rnd() * 24);
    targets.push({ midi, startSec: r3(t), endSec: r3(t + dur), measure: 1 + Math.floor(i / 3) });
    // What the singer does on this note: in tune, off by a bit, off by a lot,
    // an octave away, drifting, patchy, or silent.
    const style = Math.floor(rnd() * 8);
    if (style !== 7) {
      const offset = [0, 0.3, -0.3, 0.45, -0.55, 0.8, 12.1][style];
      const from = t + rnd() * 0.12, to = t + dur * (0.5 + rnd() * 0.6);
      for (let s = from; s < to; s += 1 / 60) {
        if (style === 5 && rnd() < 0.5) continue; // dropouts
        const drift = style === 3 ? (s - from) * 0.6 : 0;
        samples.push({ tSec: r3(s), midi: r3(midi + offset + drift + (rnd() - 0.5) * 0.1) });
      }
    }
    t += dur + (rnd() < 0.3 ? 0.2 : 0);
  }
  const strict = c % 2 === 1;
  const result = S.scoreNotes(targets, samples, strict ? S.PRESETS.strict : S.PRESETS.relaxed);
  cases.push({
    strict, targets, samples,
    expected: {
      hitPct: result.hitPct,
      details: result.details.map((d) => ({ result: d.result, coverage: d.coverage, meanCents: d.meanCents })),
      worst: S.worstSpots(result),
    },
  });
}
writeFileSync(new URL('../tests/fixtures/scoring_cases.json', import.meta.url), JSON.stringify(cases));
console.log(`${cases.length} cases`);
