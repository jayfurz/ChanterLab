import { compileChantScript } from './compiler.js';
import { parseChantScript } from './parser.js';

const DIATONIC_LADDER_SCRIPT = `# Engineering fixture: simple diatonic movement.
title "Diatonic Ladder Fixture"
tempo moderate bpm 132
start Ni
scale diatonic
drone Ni
timing symbolic
orthography generated

note same lyric "Ni"
note up 1 lyric "Pa"
note up 1 lyric "Vou"
note up 1 lyric "Ga"
note down 1 lyric "Vou"
note down 1 lyric "Pa"
note down 1 lyric "Ni"
checkpoint Ni
`;

const LYRICS_MELISMA_SCRIPT = `# Engineering fixture: lyric alignment with a melisma.
title "Lyrics Melisma Fixture"
language en
lyrics "Amen"
tempo moderate bpm 132
start Di
scale diatonic
drone Di
timing symbolic
orthography generated

note same lyric "A-"
note up 1 lyric continue
note down 1 quick lyric "men"
checkpoint Di
`;

const SOFT_CHROMATIC_PHRASE_SCRIPT = `# Engineering fixture: soft chromatic context with a checkpoint.
title "Soft Chromatic Phrase Fixture"
tempo moderate bpm 132
start Di
scale soft-chromatic phase 0
drone Di
timing symbolic
orthography generated

note same lyric "Di"
note up 1 lyric "Ke"
note down 1 quick lyric "Di"
rest duration 0.5
note same beats 2 lyric "Di"
note up 1 beats 3 lyric "Ke"
checkpoint Ke
`;

const SYMBOLIC_TIMING_STEAL_SCRIPT = `# Engineering fixture: basic symbolic gorgon-style timing rewrite.
title "Symbolic Timing Steal Fixture"
tempo moderate bpm 132
start Di
scale diatonic
drone Di
timing symbolic
orthography generated

note same beats 2 lyric "A"
note up 1 quick lyric "men"
checkpoint Ke

# Expected symbolic timing:
# note same beats 2 + note up 1 quick -> 1.5 beats + 0.5 beat.
`;

export const CHANT_SCRIPT_EXAMPLES = Object.freeze([
  Object.freeze({
    id: 'diatonic-ladder',
    title: 'Diatonic Ladder Fixture',
    path: '../../docs/examples/chant_scripts/diatonic_ladder.chant',
    script: DIATONIC_LADDER_SCRIPT,
  }),
  Object.freeze({
    id: 'lyrics-melisma',
    title: 'Lyrics Melisma Fixture',
    path: '../../docs/examples/chant_scripts/lyrics_melisma.chant',
    script: LYRICS_MELISMA_SCRIPT,
  }),
  Object.freeze({
    id: 'soft-chromatic-phrase',
    title: 'Soft Chromatic Phrase Fixture',
    path: '../../docs/examples/chant_scripts/soft_chromatic_phrase.chant',
    script: SOFT_CHROMATIC_PHRASE_SCRIPT,
  }),
  Object.freeze({
    id: 'symbolic-timing-steal',
    title: 'Symbolic Timing Steal Fixture',
    path: '../../docs/examples/chant_scripts/symbolic_timing_steal.chant',
    script: SYMBOLIC_TIMING_STEAL_SCRIPT,
  }),
]);

export function findChantScriptExample(id) {
  return CHANT_SCRIPT_EXAMPLES.find(example => example.id === id);
}

export function listChantScriptExamples() {
  return CHANT_SCRIPT_EXAMPLES.map(({ id, title, path }) => ({ id, title, path }));
}

export function chantScriptExampleText(id) {
  return findChantScriptExample(id)?.script;
}

export function parseChantScriptExample(id, options = {}) {
  const example = findChantScriptExample(id);
  if (!example) throw new Error(`Unknown chant script example "${id}".`);
  return parseChantScript(example.script, {
    sourceName: example.path,
    ...options,
  });
}

export function compileChantScriptExample(id, options = {}) {
  const example = findChantScriptExample(id);
  if (!example) throw new Error(`Unknown chant script example "${id}".`);
  return compileChantScript(example.script, {
    sourceName: example.path,
    ...options,
  });
}
