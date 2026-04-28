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

const TEMPORAL_RULES_SCRIPT = `# Engineering fixture: Phase 3 temporal rewrite rules.
# This is synthetic test material, not an authoritative hymn transcription.
title "Temporal Rules Fixture"
tempo moderate bpm 120
start Di
scale diatonic
drone Di
timing symbolic
orthography generated

# Gorgon: one parent beat divided across previous/current notes.
note same lyric "gor"
note up 1 gorgon lyric "gon"

# Digorgon: one parent beat divided across previous/current/following notes.
note same lyric "di"
note up 1 digorgon lyric "gor"
note down 1 lyric "gon"

# Trigorgon: one parent beat divided across previous/current/two following notes.
note same lyric "tri"
note up 1 trigorgon lyric "gor"
note down 1 lyric "gon"
note same lyric "tail"
checkpoint Ke
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
  Object.freeze({
    id: 'temporal-rules',
    title: 'Temporal Rules Fixture',
    path: '../../docs/examples/chant_scripts/temporal_rules.chant',
    script: TEMPORAL_RULES_SCRIPT,
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
