# Byzantine Chant Score And Training Proposal

Audience: clergy/superiors, chanters, music editors, and engineers.

Status: proposal. This document describes a proposed direction for ChanterLab; it is not a claim that these features are already implemented.

## Executive Summary

ChanterLab should eventually support actual Byzantine chant scores rather than only free singing against a scale. The useful next step is not to guess attractions from raw pitch first, but to create a score model that understands Byzantine notation as it is actually used:

- A hymn begins from a martyria, often with a pthora, which establishes the current note and scale context.
- Quantity neumes describe relative melodic movement from the current note, not absolute pitches.
- Temporal symbols modify note durations and sometimes redistribute time from neighboring notes.
- Tempo markings, or agogika, define tempo ranges rather than exact metronome values.
- Rests are first-class rhythmic events and can also be modified by temporal signs.
- Some visual glyph groups contain presentational support glyphs; import must decode semantic neume groups, not just read every visible glyph as a quantity sign.
- Qualitative signs affect execution and expression, but can be ignored in the first implementation.
- Phrase martyrias mostly serve as checkpoints: they confirm where the chanter should already have arrived.
- Ison practice can be derived from mode, cadential notes, and phrase context.

Once ChanterLab can compile a chant score into a timed target-note timeline, it can render a "guitar hero" style training view: target notes approach a fixed crosshair while the singer's live pitch and saved recordings are drawn on the singscope. This gives beginners a concrete target while preserving the relative nature of Byzantine notation.

The same score-aligned data will later let us model melodic attractions through explicit rules, hysteresis, or machine learning trained from real phrase context.

The canonical technical reference for Unicode codepoints, precomposed signs, agogika, rests, and combining behavior should be Unicode Technical Note #20, "Byzantine Musical Notation." The project can also consult practical chant tables, but the importer should be designed around Unicode semantics rather than a single font's private glyph behavior.

Important distinction: Unicode Technical Note #20 describes the notation and encoding semantics. SBMuFL/Neanes is a font-layout standard and display font. ChanterLab currently bundles the SBMuFL `Neanes.otf` font, whose glyphs live in the Unicode Basic Multilingual Plane Private Use Area. SBMuFL metadata can provide a practical mapping from those private glyph codepoints to canonical glyph names, and sometimes to official Unicode Byzantine Musical Symbols through `alternateCodepoint`, but that is still only a starting point. Composite glyphs, support glyphs, and visual convenience forms still need semantic decoding.

## Why This Comes Before Attraction Inference

Many Byzantine intervals are context-sensitive. A note may be attracted differently depending on mode, melodic direction, cadence, formula, tempo, stress, and phrase function. Trying to infer that from unaligned free singing would be fragile.

A score-aware system gives us the missing context:

```text
martyria + mode + pthora + relative neume path + rhythm + phrase position
    -> intended target at time t
    -> singer pitch trace at time t
    -> attraction/correction data
```

This creates a path from simple score-following practice to later attraction modeling.

## Core Musical Assumptions

### Byzantine Notation Is Relative

The score does not primarily say "sing C" or even "sing Di at this frequency." It starts from a known place, then uses neumes to move:

- Martyria establishes or confirms the current scale degree.
- Pthora can alter the scale/genus at a note.
- Quantity neumes move relative to the current note.
- Ison means remain on the same note.
- Ascending and descending neumes move by scale degrees from the current position.

Therefore the compiler must maintain a current melodic state:

```text
current_degree
current_octave/register
current_genus_or_scale_region
current_moria
current_time
```

Each quantity neume consumes that state and produces the next note.

### Martyrias Are Checkpoints

Phrase martyrias should be represented in the score model, but initially they should behave as validation/checkpoint events rather than as new melody generators.

Expected behavior:

- At the beginning of a hymn, martyria can establish the initial note and mode context.
- Within a hymn, martyria should verify the computed note from prior neumes.
- If the computed note disagrees with the martyria, the editor/importer should flag it.
- The UI can show the martyria as a phrase checkpoint for the singer.

### Pthora Events Recompute Scale Context

Pthora should be represented as a score event attached to a note. It should not merely change the label of a note. It changes the active scale context from that point, and the target pitch calculation should follow the same chromatic-cycle logic used by the tuning engine.

For example:

```text
martyria Di + soft chromatic pthora
    -> establishes Di as the starting note and active soft chromatic context
```

From there, quantity neumes produce relative movement inside that active context.

### Temporal Symbols Are Local Rewrite Rules

The rhythm system should not be modeled as a simple duration attached to each note only. Byzantine rhythmic signs can redistribute time among neighboring notes.

Initial rule categories:

- Klasma / Apli: add one beat to the symbol.
- Dipli: add two beats.
- Tripli: add three beats.
- Gorgon: makes the marked note and the note before it divide a beat into two equal parts.
- Digorgon: creates a three-note subdivision, commonly treated as triplet motion.
- Trigorgon: creates a four-note subdivision.
- Higher gorgons can be generalized as local subdivisions over larger windows.
- Argon-like signs combine extension and time stealing from preceding symbols.

The important engineering point is that temporal symbols should compile through a timing pass over neighboring notes:

```text
quantity-neume stream
    -> base durations
    -> temporal rewrite windows
    -> final timed notes
```

This also handles the common "stealing" case:

```text
previous note base duration = 2 beats
next note has gorgon
    -> previous becomes 1.5 beats
    -> next becomes 0.5 beat
```

### Tempo Markings Are Ranges

Tempo markings are not single fixed BPM commands. Unicode Technical Note #20 places them under Agogika, and they are encoded as precomposed symbols. They are built around the time sign chi and temporal modifiers. In Romanian practice the analogous base sign may be `T` for `timp`.

The score model should store both:

- the agogi marking from the score,
- the acceptable BPM range associated with that marking,
- and the selected working BPM used for practice playback/scoring.

That means the app should not treat `Agogi Argi` as exactly one metronome value. It should treat it as a tempo class with a range, then allow the teacher/user/genre preset to choose the working BPM inside that range.

Initial table for Unicode-aware import:

| Codepoint | Name | Proposed Meaning In ChanterLab |
|---|---|---|
| `U+1D09A` | Agogi Poli Argi | very slow tempo, roughly 56-80 BPM |
| `U+1D09B` | Agogi Argoteri | slower tempo, roughly 80-100 BPM |
| `U+1D09C` | Agogi Argi | slow tempo, roughly 100-168 BPM |
| `U+1D09D` | Agogi Metria | moderate tempo; often around the higher slow range |
| `U+1D09E` | Agogi Mesi | medium tempo; likely synonym/near-synonym of metria in some sources |
| `U+1D09F` | Agogi Gorgi | swift tempo, roughly 168-208 BPM |
| `U+1D0A0` | Agogi Gorgoteri | swifter tempo, over roughly 208 BPM |
| `U+1D0A1` | Agogi Poli Gorgi | very swift tempo; needs source/practice validation |

Seed tempo mapping for implementation:

| Key | Unicode | SBMuFL Main | SBMuFL Above | BPM Range | Seed Working BPM | Status |
|---|---|---|---|---|---|---|
| `agogiPoliArgi` | `U+1D09A` | `U+E120` | `U+E128` | 56-80 | 68 | enabled |
| `agogiArgoteri` | `U+1D09B` | `U+E121` | `U+E129` | 80-100 | 90 | enabled |
| `agogiArgi` | `U+1D09C` | `U+E122` | `U+E12A` | 100-168 | 120 | enabled |
| `agogiMetria` | `U+1D09D` | `U+E123` | `U+E12B` | 120-144 seed band | 132 | enabled, validate range |
| `agogiMesi` | `U+1D09E` | `U+E124` | `U+E12C` | 120-144 seed band | 132 | enabled, treat near `agogiMetria` until reviewed |
| `agogiGorgi` | `U+1D09F` | `U+E125` | `U+E12D` | 168-208 | 184 | enabled |
| `agogiGorgoteri` | `U+1D0A0` | `U+E126` | `U+E12E` | 208-240 UI seed band | 216 | enabled, open-ended above 208 |
| `agogiPoliGorgi` | `U+1D0A1` | `U+E127` | `U+E12F` | 240-288 placeholder | 252 | mapped but disabled until chanter review |

The `Above` SBMuFL forms are placement/display variants. They should map to the same semantic `AgogiMarking` as the main forms. Seed bands that are not fixed by the source should remain editable and should be marked as provisional in code comments or metadata.

Suggested browser seed data:

```ts
const AGOGI_SEED_MAP = {
  agogiPoliArgi: {
    unicode: "U+1D09A",
    sbmufl: ["U+E120", "U+E128"],
    bpmRange: [56, 80],
    defaultBpm: 68,
    enabled: true,
  },
  agogiArgoteri: {
    unicode: "U+1D09B",
    sbmufl: ["U+E121", "U+E129"],
    bpmRange: [80, 100],
    defaultBpm: 90,
    enabled: true,
  },
  agogiArgi: {
    unicode: "U+1D09C",
    sbmufl: ["U+E122", "U+E12A"],
    bpmRange: [100, 168],
    defaultBpm: 120,
    enabled: true,
  },
  agogiMetria: {
    unicode: "U+1D09D",
    sbmufl: ["U+E123", "U+E12B"],
    bpmRange: [120, 144],
    defaultBpm: 132,
    enabled: true,
    provisionalRange: true,
  },
  agogiMesi: {
    unicode: "U+1D09E",
    sbmufl: ["U+E124", "U+E12C"],
    bpmRange: [120, 144],
    defaultBpm: 132,
    enabled: true,
    provisionalRange: true,
  },
  agogiGorgi: {
    unicode: "U+1D09F",
    sbmufl: ["U+E125", "U+E12D"],
    bpmRange: [168, 208],
    defaultBpm: 184,
    enabled: true,
  },
  agogiGorgoteri: {
    unicode: "U+1D0A0",
    sbmufl: ["U+E126", "U+E12E"],
    bpmRange: [208, 240],
    defaultBpm: 216,
    enabled: true,
    openEndedUpperRange: true,
  },
  agogiPoliGorgi: {
    unicode: "U+1D0A1",
    sbmufl: ["U+E127", "U+E12F"],
    bpmRange: [240, 288],
    defaultBpm: 252,
    enabled: false,
    provisionalRange: true,
  },
};
```

Open implementation question: because several ranges overlap or are broad, ChanterLab should probably store a `tempoPolicy`:

```ts
type TempoPolicy = {
  source: "score" | "genre-default" | "teacher" | "user";
  bpm: number;
  agogi?: AgogiMarking;
};
```

For practice, the UI can show the agogi label and the selected BPM. Teachers can override the exact BPM without losing the original marking.

### Rests Are Score Events

Rests should not be represented as silent notes. They are rhythmic events with their own notation and duration. Unicode includes leimma/rest signs, including rests of multiple beats and rests modified by temporal signs.

The first implementation should support:

- one-beat rests,
- multi-beat rests,
- half-beat rests,
- rests affected by gorgon-like temporal redistribution,
- phrase-final rest or hold behavior when supported by notation.

This matters for training because the crosshair should show silence as an expected event. The scorer should not penalize the singer for being silent during a rest, and should optionally penalize singing through a rest.

Rest events should compile into the same timeline as notes:

```ts
type CompiledRest = {
  startMs: number;
  durationMs: number;
  sourceEventIndex: number;
};
```

The visual renderer can display rests as gaps or muted bars in the score-practice lane.

### Composite Glyph Groups Need Semantic Decoding

Glyph import must understand that Byzantine notation is often visually stacked or combined for readability.

Examples to handle:

- A visible oligon may act as a presentational "table" or support sign when apostrophos and kentimata are placed above it.
- In that case, the bottom oligon may not contribute quantity; the semantic quantity may come from the signs placed on it.
- Quantity combinations can use a petasti or oligon as a base/support with additional quantity signs to represent the actual movement.
- The usual reading pattern may be bottom-up and left-to-right, but support-glyph cases require exceptions.

Therefore import should produce a semantic `NeumeGroup`, not a flat character list:

```ts
type NeumeGroup = {
  baseGlyph?: SourceToken;
  supportGlyph?: SourceToken;
  quantitySigns: SourceToken[];
  temporalSigns: SourceToken[];
  qualitativeSigns: SourceToken[];
  pthoraSigns: SourceToken[];
  semanticQuantity: QuantityNeume;
};
```

The importer should preserve the original Unicode tokens for round-tripping/display, but the compiler should use `semanticQuantity`.

### Encoding Layers And Mapping

The importer should keep three layers separate:

1. Source encoding: Unicode Byzantine Musical Symbols, SBMuFL Private Use Area glyphs, OCR labels, or the ChanterLab text script.
2. Glyph identity: canonical names such as `ison`, `oligon`, `gorgonAbove`, or `fthoraSoftChromaticDiAbove`.
3. Musical semantics: relative movement, temporal rule, pthora event, martyria checkpoint, rest, or tempo change.

These layers should not be collapsed into one table. A single glyph can be presentational, and a single semantic note group can require multiple visible glyphs.

Examples:

| Source Token | Glyph Identity | Compiler Meaning |
|---|---|---|
| Unicode `U+1D046` | `ison` | quantity neume with zero movement |
| SBMuFL `U+E000` | `ison`, alternate `U+1D046` | same semantic quantity after metadata lookup |
| SBMuFL `U+E123` | `agogiMetria`, alternate `U+1D09D` | tempo class event, not a fixed BPM |
| SBMuFL `U+E0F4` | `digorgon`, alternate `U+1D092` | temporal subdivision rule over a local note window |
| SBMuFL `U+E19A` | `fthoraSoftChromaticDiAbove` | pthora/modulation event; exact chromatic phase depends on attached note and scale context |
| Composite/support glyph | source-specific glyph name | requires decomposition before quantity can be resolved |

The SBMuFL metadata file `glyphnames.json` is therefore a glyph adapter, not the score model. It is useful for recognizing Neanes-style PUA characters and for finding official Unicode alternates when they exist. It does not replace the semantic grouping pass described above.

Recommended token shape:

```ts
type SourceToken = {
  source: "unicode-byzantine" | "sbmufl-pua" | "chant-script" | "ocr";
  raw: string;
  codepoint?: string;
  glyphName?: string;
  alternateCodepoint?: string;
  span?: { start: number; end: number };
};

type SemanticToken =
  | { kind: "quantity"; value: QuantityNeume; source: SourceToken[] }
  | { kind: "temporal"; value: TemporalSign; source: SourceToken[] }
  | { kind: "qualitative"; value: QualitativeSign; source: SourceToken[] }
  | { kind: "pthora"; value: PthoraEvent; source: SourceToken[] }
  | { kind: "martyria"; value: MartyriaEvent; source: SourceToken[] }
  | { kind: "rest"; value: RestSign; source: SourceToken[] }
  | { kind: "tempo"; value: AgogiMarking; source: SourceToken[] };
```

The `source` arrays are important. They let the editor display or round-trip the original score notation while the practice engine consumes stable semantics.

Initial mapping rules:

- If a Unicode Byzantine codepoint is received, classify it directly using Unicode Technical Note #20 tables.
- If an SBMuFL PUA codepoint is received, look it up in SBMuFL `glyphnames.json`.
- If SBMuFL provides `alternateCodepoint`, attach it to the source token, but do not blindly replace the token before grouping.
- If the glyph is a composite or support form, preserve the glyph name and run a decomposition/grouping rule.
- If the glyph is a fthora/chroa, attach it to the nearest semantic note group according to notation layout.
- If the glyph is soft or hard chromatic, infer the four-phase cyclic meaning from the attached note and current scale context, not from the two SBMuFL glyphs alone.
- If a token cannot be classified unambiguously, keep it in the AST and emit an import diagnostic instead of silently guessing.

Seed SBMuFL mapping examples for the first importer:

| Role | SBMuFL Glyph Name | SBMuFL Codepoint | Unicode Alternate | Import Note |
|---|---|---|---|---|
| Quantity | `ison` | `U+E000` | `U+1D046` | direct zero-movement neume |
| Quantity | `oligon` | `U+E001` | `U+1D047` | direct ascending neume |
| Quantity | `apostrofos` | `U+E021` | `U+1D051` | direct descending neume |
| Quantity | `yporroi` | `U+E023` | `U+1D053` | direct or grouped descent, depending on notation context |
| Quantity | `elafron` | `U+E024` | `U+1D055` | direct descending neume |
| Quantity | `chamili` | `U+E027` | `U+1D056` | direct descending neume |
| Rest | `leimma1` | `U+E0E0` | `U+1D08A` | rest event |
| Rest | `leimma2` | `U+E0E1` | `U+1D08B` | rest event |
| Rest | `leimma3` | `U+E0E2` | `U+1D08C` | rest event |
| Rest | `leimma4` | `U+E0E3` | `U+1D08D` | rest event |
| Temporal | `gorgonAbove` | `U+E0F0` | `U+1D08F` | local subdivision rule |
| Temporal | `digorgon` | `U+E0F4` | `U+1D092` | local subdivision rule |
| Temporal | `trigorgon` | `U+E0F8` | `U+1D096` | local subdivision rule |
| Temporal | `argon` | `U+E0FC` | `U+1D097` | extension/redistribution rule |
| Tempo | `agogiMetria` | `U+E123` | `U+1D09D` | tempo class/range |
| Tempo | `agogiGorgi` | `U+E125` | `U+1D09F` | tempo class/range |
| Pthora | `fthoraHardChromaticPaAbove` | `U+E198` | none in SBMuFL metadata | pthora event; infer phase from placement |
| Pthora | `fthoraHardChromaticDiAbove` | `U+E199` | none in SBMuFL metadata | pthora event; infer phase from placement |
| Pthora | `fthoraSoftChromaticDiAbove` | `U+E19A` | none in SBMuFL metadata | pthora event; infer phase from placement |
| Pthora | `fthoraSoftChromaticKeAbove` | `U+E19B` | none in SBMuFL metadata | pthora event; infer phase from placement |
| Chroa | `chroaZygosAbove` | `U+E19D` | none in SBMuFL metadata | local scale modifier |
| Chroa | `chroaKlitonAbove` | `U+E19E` | none in SBMuFL metadata | local scale modifier |
| Chroa | `chroaSpathiAbove` | `U+E19F` | none in SBMuFL metadata | local scale modifier |

`none in SBMuFL metadata` means the SBMuFL mapping file does not declare a direct `alternateCodepoint` for that glyph. It does not mean the musical concept is absent from Unicode TN20; it means the importer needs an explicit semantic rule instead of a mechanical one-codepoint replacement.

## Proposed Internal Model

Use a semantic internal model. Do not treat font glyphs as the source of truth.

```ts
type ChantScore = {
  title?: string;
  mode?: string;
  language?: string;
  lyrics?: LyricLine[];
  translations?: LyricLine[];
  defaultAgogi?: AgogiMarking;
  defaultTempoBpm: number;
  initialMartyria: MartyriaEvent;
  events: ScoreEvent[];
};

type LyricLine = {
  id: string;
  text: string;
  language?: string;
};

type ScoreEvent =
  | MartyriaEvent
  | PthoraEvent
  | NeumeEvent
  | RestEvent
  | TempoEvent
  | PhraseBreakEvent
  | IsonEvent;

type MartyriaEvent = {
  type: "martyria";
  degree: "Ni" | "Pa" | "Vou" | "Ga" | "Di" | "Ke" | "Zo";
  genus?: "Diatonic" | "SoftChromatic" | "HardChromatic" | string;
  pthora?: PthoraEvent;
};

type PthoraEvent = {
  type: "pthora";
  genus: "Diatonic" | "SoftChromatic" | "HardChromatic" | string;
  phase?: 0 | 1 | 2 | 3;
};

type RelativeMovement = {
  steps: number;
  direction: "same" | "up" | "down";
};

type NotationDisplay = {
  sourceTokens?: SourceToken[];
  preferredGlyphName?: string;
  generatedGlyphName?: string;
  orthography?: "none" | "generated" | "literal";
};

type LyricAttachment = {
  kind: "start" | "continue" | "none";
  text?: string;
  lineId?: string;
  language?: string;
};

type NeumeEvent = {
  type: "neume";
  group?: NeumeGroup;
  movement: RelativeMovement;
  quantity?: QuantityNeume;
  temporal: TemporalSign[];
  timingMode?: "symbolic" | "exact";
  exactBeats?: number;
  qualitative: QualitativeSign[];
  display?: NotationDisplay;
  lyric?: LyricAttachment;
};

type RestEvent = {
  type: "rest";
  rest: RestSign;
  temporal: TemporalSign[];
};

type TempoEvent = {
  type: "tempo";
  agogi?: AgogiMarking;
  bpmRange?: [number, number];
  workingBpm?: number;
  temporary?: boolean;
};

type AgogiMarking = {
  codepoint: string;
  name: string;
  bpmRange?: [number, number];
};
```

The compiler should produce a timeline:

```ts
type CompiledTimelineEvent = CompiledNote | CompiledRest | CompiledTempoChange;

type CompiledNote = {
  startMs: number;
  durationMs: number;
  degree: string;
  moria: number;
  effectiveMoria: number;
  sourceEventIndex: number;
  lyric?: LyricAttachment;
  pthora?: PthoraEvent;
  martyriaCheckpoint?: MartyriaEvent;
};

type CompiledRest = {
  type: "rest";
  startMs: number;
  durationMs: number;
  sourceEventIndex: number;
};

type CompiledTempoChange = {
  type: "tempo";
  atMs: number;
  agogi?: AgogiMarking;
  workingBpm: number;
  sourceEventIndex: number;
};
```

That compiled timeline is what the training UI and scoring engine consume.

## Human-Readable Chant Script

Before parsing real glyph notation, we should create a controlled text format that maps directly to the internal model. This lets chanters and engineers test musical behavior without fighting font encoding issues.

The script should be English-first. It should not require an English-speaking user or engineer to know names like `agogi`, `ison`, `oligon`, `apostrofos`, `apli`, or `martyria` just to write a test phrase. Those names should remain supported as aliases and glyph identities, but the primary script should describe what the engine needs to know:

- starting note,
- scale/modulation,
- relative movement,
- duration,
- tempo,
- drone/ison suggestion,
- checkpoints,
- optional notation/glyph hints.

This implies two separate choices:

- Timing mode: symbolic notation timing or exact compiled timing.
- Orthography mode: generated notation, literal imported notation, or no notation display.

English-first example:

```text
title "Example Soft Chromatic Phrase"
tempo moderate bpm 132
start Di
scale soft-chromatic phase 0
drone Di

note same
note up 1
note down 1 quick
rest duration 0.5
note same beats 2
note up 1 beats 3
checkpoint Ke
```

This means:

- Start at Di.
- Apply soft chromatic context.
- Use Di as the drone/ison suggestion.
- Select a working BPM inside the score's agogi range.
- Compile each relative movement from the current note.
- Compile rests into silence events. `rest duration 0.5` means an explicit half-beat rest and does not borrow time from neighboring notes.
- Apply temporal symbols during the timing pass.
- Use the final martyria as a checkpoint.

In the default `symbolic` timing mode, `beats` and `quick` are notation-like instructions, not final stopwatch durations. The compiler applies temporal rewrite rules after parsing.

Example:

```text
note same beats 2
note up 1 quick
```

This should compile like the Byzantine notation case where a following gorgon takes half a beat from the previous extended note:

```text
previous note: 1.5 beats
quick note:    0.5 beat
window total:  2.0 beats
```

The quick note does not add a separate extra beat on top of the previous note's two-beat span. If an engineer wants to bypass notation timing and test already-compiled durations, the script should allow exact timing:

```text
timing exact
note same duration 1.5
note up 1 duration 0.5
```

In `exact` timing mode, symbolic temporal signs such as `quick`, `gorgon`, `apli`, `dipli`, and `tripli` should either be rejected or treated only as display hints. The parser should emit a diagnostic if a line mixes exact `duration` with symbolic temporal signs without an explicit override.

Rests should follow the same distinction:

```text
rest duration 0.5
```

means a half-beat silent event. It does not steal from a neighboring note.

```text
rest quick
```

would be a symbolic temporal rest, and only that form should participate in gorgon-like local redistribution. The first implementation can reject `rest quick` until the exact rest-temporal rules are reviewed.

### Symbolic Mode Grammar V0

The first parser should support a small strict grammar. It should reject unknown words instead of guessing.

General rules:

- Blank lines are ignored.
- `#` starts a comment.
- Keywords are case-insensitive.
- Degree names are case-insensitive: `Ni`, `Pa`, `Vou`, `Ga`, `Di`, `Ke`, `Zo`.
- Numbers may be integers or decimals.
- Quoted strings are required for titles and multi-word lyrics.
- Default timing mode is `symbolic`.
- Default orthography mode is `generated`.

Header lines:

```text
title "Text"
mode "Text"
language <tag>
lyrics "Text"
lyrics <line-id> "Text"
translation <line-id> "Text"
tempo <tempo-name> [bpm <number>]
tempo bpm <number>
timing symbolic
timing exact
orthography generated
orthography none
start <degree>
start <degree> scale <scale-name> [phase <number>]
scale <scale-name> [phase <number>]
drone <degree>
```

Supported tempo names should be:

```text
very-slow | slower | slow | moderate | medium | swift | swifter | very-swift
```

with Greek-derived aliases:

```text
poli-argi | argoteri | argi | metria | mesi | gorgi | gorgoteri | poli-gorgi
```

Supported scale names should be:

```text
diatonic | soft-chromatic | hard-chromatic | western
```

Note lines:

```text
note same [note-modifier...]
note up <steps> [note-modifier...]
note down <steps> [note-modifier...]
```

Initial supported `steps` should be `1` through `4`. The grammar can allow larger values later, but the first compiler should reject unsupported movement with a clear diagnostic.

Note modifiers:

```text
beats <number>
quick
divide <number>
duration <number>
scale <scale-name> [phase <number>]
drone <degree>
checkpoint <degree>
style <name>
quality <name>
glyph <sbmufl-glyph-name>
lyric "Text"
lyric <line-id> "Text"
lyric continue
lyric <line-id> continue
lyric none
```

Modifier meanings:

| Modifier | Symbolic Mode Meaning |
|---|---|
| no timing modifier | one notated beat |
| `beats N` | notated base duration before temporal rewrite |
| `quick` | gorgon-like temporal sign on this note; initial support should implement the basic previous/current half-beat case |
| `divide N` | generalized temporal division marker; `divide 3` and higher should be parsed but may be diagnostic-only until reviewed |
| `duration N` | exact compiled duration; allowed only in `timing exact` unless explicitly overridden later |
| `scale ...` | pthora/scale change attached to the produced note |
| `drone ...` | ison change attached at this point |
| `checkpoint ...` | martyria/checkpoint attached to this point |
| `style ...` / `quality ...` | preserved qualitative hint |
| `glyph ...` | preferred display glyph; does not change pitch by itself |
| `lyric "Text"` | starts a new lyric syllable/text attachment on this note, using the default lyric line |
| `lyric <line-id> "Text"` | starts a new lyric unit on a named lyric line |
| `lyric continue` | continues the previous syllable on the default lyric line across this note, for melisma |
| `lyric <line-id> continue` | continues the previous syllable on a named lyric line |
| `lyric none` | explicitly marks no lyric on this note |

Lyric line headers:

```text
language en
lyrics "Lord have mercy"
lyrics greek "Kyrie eleison"
translation english "Lord have mercy"
```

The line-level `lyrics` text is metadata for display/search/review. It does not automatically align syllables to notes. Note-level `lyric` modifiers are the alignment source of truth.

Lyric alignment rules:

- `lyric "Text"` starts a new lyric unit on that note.
- `lyric <line-id> "Text"` is available for later multi-line chant text, translations, or transliterations.
- The text should be the exact syllable or visible text the author wants displayed, including hyphens or punctuation.
- `lyric continue` means the current note is sung on the previous lyric unit. The renderer can draw an extender line or omit repeated text.
- `lyric none` means the note has no lyric, useful for rests, intonations, or ornamental notes.
- If a note omits `lyric`, the first implementation should treat it as `lyric none` and may warn if surrounding notes have lyrics.
- Rests should not carry lyrics in v0.

Example with a melisma:

```text
lyrics "Amen"

note same lyric "A-"
note up 1 lyric continue
note down 1 quick lyric "men"
```

Rest lines:

```text
rest
rest beats <number>
rest duration <number>
rest quick
```

Rest meanings:

- `rest` is a one-beat silent event.
- `rest beats N` is a symbolic notated silent event with base duration `N`.
- `rest duration N` is an explicit silent duration and does not borrow from neighbors.
- `rest quick` should be rejected in the first implementation until rest-temporal behavior is reviewed.

Checkpoint and phrase lines:

```text
checkpoint <degree>
phrase
phrase checkpoint <degree>
```

`checkpoint` should validate the current computed note. `phrase` creates a visual phrase boundary. `phrase checkpoint <degree>` does both.

Recommended aliases:

| Alias | Canonical Parse |
|---|---|
| `same` | `note same` when used alone on a note line |
| `up N` | `note up N` when used alone on a note line |
| `down N` | `note down N` when used alone on a note line |
| `hold N` | `note same beats N` |
| `silence N` | `rest duration N` |
| `text "Text"` | `lyric "Text"` |
| `_` | `lyric continue` when used as a note modifier |
| `ison <degree>` | `drone <degree>` |
| `martyria <degree>` | `checkpoint <degree>` unless used at the top before notes, where it is `start <degree>` |
| `pthora <scale-name> phase=N` | `scale <scale-name> phase <N>` |
| `gorgon` | `quick` |
| `digorgon` | `divide 3` |
| `trigorgon` | `divide 4` |
| `apli` / `klasma` | `beats 2` |
| `dipli` | `beats 3` |
| `tripli` | `beats 4` |

Example symbolic phrase:

```text
title "Symbolic Timing Example"
tempo moderate bpm 132
start Di
timing symbolic

note same beats 2 lyric "A"
note up 1 quick lyric "men"
checkpoint Ke
```

The timing compiler should preserve the two-beat local window:

```text
note same beats 2 + note up 1 quick -> 1.5 beats + 0.5 beat
```

The pitch compiler should ignore whether the rendered glyph is `oligon`, `petasti`, or another one-step ascent. That is orthography. Greek-derived names can still be accepted through the alias table above for users who want one-to-one glyph identity.

This script is not meant to replace Byzantine notation. It is a bootstrap and test format for the engine. Its canonical output is the semantic AST, not a text spelling.

Qualitative signs are not lost by using English names. They should be modeled as optional decorators on a note group:

```text
note up 1 style petasti
note up 1 quality bright
note down 1 quick glyph apostrofos
```

The first implementation can preserve `style`/`quality`/`glyph` fields without acting on them. Later, a chant-aware renderer or importer can use the same fields to display exact notation and apply qualitative execution rules.

### Symbolic V0 Review Checklist

These are the decisions to rubber-stamp before implementation:

- `symbolic` is the default timing mode.
- `beats N` means notated base duration before temporal rewrite.
- `duration N` means exact compiled duration and is only valid in `timing exact`.
- `quick` means the basic gorgon-like previous/current rewrite, initially compiling `beats 2` + `quick` as `1.5 + 0.5`.
- `divide 3` and `divide 4` are parsed as digorgon/trigorgon-style markers, but can remain diagnostic-only until their exact windows are reviewed.
- `rest duration N` never steals from neighbors.
- `rest quick` is rejected until rest-temporal behavior is reviewed.
- `lyric "Text"` starts a new lyric unit; `lyric continue` carries the prior lyric unit through a melisma.
- Full `lyrics "Text"` lines are metadata and do not auto-align the score.
- `note up 1` is semantic movement only; generated display can start as `oligon`.
- `glyph petasti` or `style petasti` can preserve or request petasti without changing the pitch movement.
- Orthography rules, such as preferring `petasti` over `oligon` in specific contexts, belong in a renderer/importer pass, not in the pitch compiler.
- Real hymn files should include source, reviewer, and copyright/public-domain notes before being treated as practice material.

### Orthography Is Separate From Movement

Multiple Byzantine glyphs can express the same relative movement. For example, both `oligon` and `petasti` can represent an upward step, but `petasti` also carries qualitative and orthographic information. Therefore the engine must not assume `note up 1` always means the visible glyph `oligon`.

The internal model should keep these apart:

```text
movement: up 1
quality/style: optional
orthography: generated or literal
display glyph: optional
```

For hand-written English scripts, ChanterLab can start with a simple default renderer:

```text
note up 1 -> oligon
note down 1 -> apostrofos
note same -> ison
```

Then add an orthography pass later:

```text
semantic movement + neighboring context + quality/style hints
    -> preferred Byzantine glyph group
```

This is where rules such as "use `petasti` rather than `oligon` in a particular orthographic context" belong. They should not live in the pitch compiler. The pitch compiler only needs the semantic movement; the notation renderer chooses the appropriate glyph.

Imported notation works differently. If the source score explicitly contains `petasti`, the importer should preserve that literal glyph and decode it to:

```text
movement: up 1
quality/style: petasti
display glyph: petasti
orthography: literal
```

That gives both use cases:

- English authoring stays readable.
- Imported or expert-authored notation can remain exact.
- Later orthography rules can generate better glyphs without changing the pitch/timing compiler.

### Script And Glyph Display

Score Practice should be able to show actual notation glyphs above or inside the moving target bars.

There are two display modes:

1. Imported notation: preserve the original Unicode/SBMuFL source tokens and render those glyph groups directly.
2. English script: generate simple default glyphs from semantic movement and timing, while allowing optional `glyph` hints when exact notation matters.
3. Generated orthography: use a rule table to choose the preferred Byzantine glyph group from movement, context, and quality/style hints.

Examples:

| English Input | Default Display Glyph | Note |
|---|---|---|
| `note same` | `ison` | generated default |
| `note up 1` | `oligon` | generated default |
| `note down 1` | `apostrofos` | generated default |
| `note down 1 quick` | `apostrofos` + `gorgon` | generated default group |
| `note up 1 glyph petasti` | `petasti` | explicit display hint |

This gives students real glyph exposure in the guitar-hero style view without making the engine script unreadable. When a score is imported from real notation, the app should prefer the original glyphs; when a phrase is hand-written for tests or training, generated glyphs are acceptable and should be labeled internally as generated.

## Unicode / Glyph Import Later

The project already bundles the OFL SBMuFL Neanes font for display. The long-term goal can include reading notation text encoded with Unicode Byzantine Musical Symbols, or text produced by Neanes-like programs.

However, glyph import should come after the internal score model is stable.

Reasons:

- Unicode codepoints are the canonical interchange layer, but they still need semantic grouping.
- Font glyphs are presentation details and may differ between fonts or source programs.
- SBMuFL/Neanes uses Private Use Area codepoints for glyphs; the SBMuFL `glyphnames.json` metadata maps those to names and, where available, an official Unicode `alternateCodepoint`.
- Not every SBMuFL glyph has a one-to-one Unicode counterpart because the font includes composite and presentation glyphs for readable score layout.
- Unicode contains precomposed signs for some tempo markings, rests, and combinations.
- A single visual neume group may contain quantity, qualitative, temporal, pthora, and support signs.
- We need to preserve semantic grouping, not merely read characters from left to right.

Recommended import pipeline:

```text
Unicode text / editor export / OCR output
    -> Unicode or SBMuFL-PUA tokens
    -> SBMuFL metadata lookup where needed
    -> semantic neume groups
    -> ChantScore AST
    -> CompiledNote timeline
```

The UI should continue to render with the OFL font, but storage should use semantic tokens plus original source-token spans for round-trip display.

OCR may be useful for scanned or image-only scores, but OCR output should still target this Unicode-token layer before compilation.

### Importer Modules

The future importer should be split into small adapters rather than one large parser:

| Module | Responsibility |
|---|---|
| `unicode_byzantine_adapter` | Classifies Unicode Byzantine Musical Symbols into `SourceToken`s using TN20-derived tables. |
| `sbmufl_adapter` | Converts SBMuFL/Neanes PUA characters into glyph names and optional Unicode alternates using SBMuFL metadata. |
| `glyph_group_resolver` | Groups visible symbols into semantic neume groups, handling support glyphs and stacked signs. |
| `chant_score_builder` | Converts semantic groups into `ChantScore` events. |
| `import_diagnostics` | Reports ambiguous support glyphs, invalid temporal windows, martyria mismatches, and unknown symbols. |

This keeps Neanes compatibility useful without making Neanes or SBMuFL the canonical file format.

## Timing Engine Design

### Pass 1: Melody Resolution

Input: starting note/martyria, pthora or scale-change events, English script notes or imported neume groups, rests, and tempo events.

Output: ordered note/rest events with scale degree/register where applicable, but not final durations.

Responsibilities:

- Apply initial martyria.
- Apply pthora at the attached note.
- Resolve semantic relative movement from English script notes or imported neume groups.
- Track octave/register wrapping.
- Validate internal martyrias.
- Preserve rests as silent timeline events.
- Preserve tempo changes as timeline control events.
- Ignore qualitative signs at first, but preserve them in the AST.

### Pass 2: Tempo Selection

Resolve English tempo names or agogi marks to a working BPM.

Responsibilities:

- Read the initial tempo/agogi from the signature if present.
- Infer a genre/default tempo if no explicit agogi is present.
- Represent temporary mid-piece agogi changes as tempo events.
- Store the original tempo class and BPM range.
- Choose a working BPM inside the range for practice.

This pass must not collapse the notation into a single exact BPM permanently. The exact practice BPM should be editable.

### Pass 3: Base Rhythm

Assign each neume and rest a default duration of one beat unless modified.

Timing modes:

- `symbolic`: parse notation-like duration and temporal signs, then apply rewrite rules.
- `exact`: use already-compiled durations and skip temporal rewriting for those events.

Duration extensions:

- Klasma/Apli -> +1 beat.
- Dipli -> +2 beats.
- Tripli -> +3 beats.
- Future extensions should be data-driven.

Rests should pass through the same duration pipeline as notes, while remaining silent.

In symbolic mode, duration extensions describe the notated time available before temporal division. A following `quick`/gorgon can borrow from that available time. In exact mode, `duration 1.5` means the final duration is already 1.5 beats.

### Pass 4: Temporal Rewrite Windows

Apply gorgon and related signs as local duration rewrites for symbolic events.

Proposed general model:

```ts
type TemporalRule = {
  sign: string;
  windowBefore: number;
  windowAfter: number;
  outputFractions: Fraction[];
  canBorrowFromExtendedPrevious: boolean;
};
```

Examples:

- Gorgon: affects current and previous note, producing half-beat motion.
- Digorgon: affects a three-note window--the current and previous note, as well as the one following it.
- Trigorgon: affects a four-note window--the current and previous note, as well as two following it.
- Argon: combines extension with subtraction from prior notes.

This rule table must be reviewed by experienced chanters before being treated as authoritative.

The rewrite pass should preserve the total duration of its local window unless a rule explicitly says otherwise. This prevents `beats 2` followed by `quick` from accidentally becoming `2.5` beats. It should compile as `1.5 + 0.5` in the basic gorgon case.

### Pass 5: Millisecond Timeline

Convert beats to milliseconds using the active working BPM at each point in the score.

Output:

- `CompiledNote` events for sung targets.
- `CompiledRest` events for expected silence.
- `CompiledTempoChange` events for display and playback state.

## Training UI Proposal

Add a new "Score Practice" mode.

Visual behavior:

- Vertical axis remains the scale ladder.
- Horizontal axis becomes time.
- A fixed vertical crosshair marks "now."
- Target notes scroll toward the crosshair.
- Long notes appear as long horizontal bars.
- Short notes appear as short bars.
- Actual or generated Byzantine glyphs appear with the target bars when available.
- Pthora events appear as vertical markers or badges.
- Martyria checkpoints appear at phrase boundaries.
- Live detected pitch remains overlaid on the singscope.
- Saved recordings can replay with the score and pitch trace.

This supports both learning and evaluation:

- The singer sees what is coming.
- The singer sees whether their pitch aligns with the target at the crosshair.
- The app can score timing and pitch separately.

## Recording And Dataset Strategy

The current recording/playback work can become the foundation for a chant dataset.

For every practice take, save:

- Audio recording.
- Pitch trace.
- Compiled score timeline.
- Active scale/mode/pthora state.
- User-selected voice range/reference Ni.
- Timing alignment between score and recording.

This enables:

- Review by teachers.
- Repetition of difficult phrases.
- Rule-based attraction tuning.
- Future model training.

For attraction modeling, the key data record is:

```text
score phrase context + intended base target + actual singer pitch + expert correction/label
```

## Ison Integration

The ison should not be hardcoded only by exercise. A score-aware system should support:

- explicit ison markings if present,
- default ison recommendations by mode,
- changes at cadential notes,
- phrase-level ison suggestions from an ison chart.

Initial implementation:

- Let score script specify `drone Degree`, with `ison Degree` accepted as an alias. It will be a decorator for the note it is to change on.
- Add optional phrase-level ison events.
- Later add a mode/cadence rule table.

## Implementation Readiness

The plan is ready to implement in phases. It is not finished in the sense of being a complete Byzantine notation engine, but it is complete enough to start without guessing the architecture.

Ready now:

- Phase 1 semantic score core.
- English-first text-script parser.
- Relative melody resolution from starting note and English movement commands.
- Rest events.
- Agogi/tempo seed map.
- Simple duration extensions.
- Initial score-practice prototype on top of the singscope with generated glyph display.
- Symbolic timing mode plus exact-duration mode.

Ready to scaffold but not finalize:

- Unicode and SBMuFL adapters.
- Import diagnostics.
- Glyph-group resolver.
- Pthora import and chromatic phase inference.
- Generated orthography rules.

Needs chanter review while implementing:

- Exact temporal rewrite windows for digorgon, trigorgon, higher gorgons, and argon combinations.
- Composite/support glyph decomposition rules.
- Orthography rules for choosing `oligon`, `petasti`, and compound glyphs from the same semantic movement.
- Martyria validation strictness.
- Ison chart behavior by mode and cadence.
- Attraction grammar.

Recommended first implementation target:

1. Build the semantic AST and text script first.
2. Compile a small phrase into target-note/rest/tempo timeline events.
3. Render that timeline in a new score-practice mode with generated notation glyphs.
4. Add Unicode/SBMuFL import only after the compiler has tests and at least one reviewed phrase.

## Implementation Roadmap

### Phase 1: Semantic Score Core

- Create `web/score/chant_score.js`.
- Define `ChantScore`, `ScoreEvent`, and `CompiledNote`.
- Implement a small hand-written parser for the English-first text script.
- Implement melody resolution from starting note + relative movement.
- Implement simple duration extensions.
- Implement symbolic timing and exact-duration timing as separate modes.
- Generate default display glyphs for simple movement/timing events.
- Add unit tests for relative movement and basic rhythm.

### Phase 2: Score Practice Prototype

- Add one sample phrase in the app.
- Compile it to timed target notes.
- Render target bars on the singscope.
- Add a fixed crosshair.
- Compare live pitch against the active score note.

### Phase 3: Temporal Rules

- Add gorgon/digorgon/trigorgon rule tables.
- Add tests for local duration redistribution.
- Add chanter-reviewed examples.
- Keep qualitative signs parsed but non-operative.

### Phase 4: Pthora And Martyria Validation

- Attach pthora events to score notes.
- Reuse the tuning engine to compute target moria.
- Show martyria checkpoints.
- Flag mismatches between computed note and martyria.

### Phase 5: Ison Rules

- Add explicit score ison events.
- Add mode/cadence ison suggestions.
- Allow playback of the suggested ison during practice.

### Phase 6: Glyph Import

- Vendor or generate the minimal SBMuFL metadata needed by the browser.
- Add a Unicode Byzantine adapter based on Unicode Technical Note #20.
- Add an SBMuFL/Neanes PUA adapter based on `glyphnames.json`.
- Parse glyph groups into semantic neume events.
- Add explicit decomposition rules for support/table glyph cases.
- Infer soft/hard chromatic pthora phase from note placement and active scale context.
- Provide import diagnostics when grouping is ambiguous.
- Keep the text script as the canonical fallback.

### Phase 7: Attraction Grammar

- Add rule-based attractions as temporary target offsets.
- Make attraction rules depend on score context, not only pitch direction.
- Add phrase-level examples reviewed by chanters.

### Phase 8: Data-Assisted Models

- Use score-aligned recordings to study attraction behavior.
- Start with hysteresis/rule tuning.
- Consider transformer or sequence models only after enough reviewed phrase data exists.

## Engineering Risks And Open Questions

- Exact rhythmic rules vary by notation tradition and need chanter review. Will default to the most straightforward interpretation.
- Glyph import may depend heavily on source program and font encoding. Neanes/SBMuFL text should go through the metadata adapter; scanned or image-only scores may need OCR that outputs the same canonical token layer.
- Some pthora/martyria combinations may need editorial interpretation. Examples are soft and hard chromatic pthora don't distinguish between 0 and 2, and 1 and 3 cyclic representations, but can sometimes be inferred.
- Phrase endings and cadences may require mode-specific logic.
- Mobile UI must remain usable in portrait and landscape.
- Long recordings and WAV export may need memory limits on iOS Safari. We can add compression to mp3.
- Downloaded/generated score data should avoid copyright issues for protected hymn editions.

## Review Questions For Chanters

- Which quantity neumes should be supported first?
- Which temporal signs are essential for a first usable hymn?
- What are the simplest phrases that demonstrate gorgon, digorgon, and argon behavior?
- Which martyrias should be treated as hard validation checkpoints versus visual reminders?
- Which pthora placements are common enough to prioritize?
- Which ison rules should be implemented before a full ison chart?

## Review Questions For Engineers

- Should the score compiler live entirely in JavaScript first, or should it be moved into Rust once stable?
- What is the best test format for chant examples?
- How should score-aligned recordings be stored without exceeding browser memory?
- Should score files be plain text, JSON, or both?
- How much of the renderer can reuse the current singscope canvas?
- What is the right compatibility target for iOS Safari audio and recording APIs?

## References To Review

- Table of Byzantine Notation Symbols: http://www.byzantinechant.org/notation/Table%20of%20Byzantine%20Notation%20Symbols.pdf
- Ison Chart: http://www.byzantinechant.org/notation/Ison_Chart.pdf
- Unicode Technical Note #20, Byzantine Musical Notation: https://www.unicode.org/notes/tn20/
- SBMuFL font layout and metadata: https://github.com/neanes/sbmufl
- SBMuFL documentation: https://neanes.github.io/sbmufl/
- ChanterLab scale and tuning reference: `docs/BYZANTINE_SCALES_REFERENCE.md`
- ChanterLab architecture reference: `docs/ARCHITECTURE.md`

The public notation table is useful for symbol names and introductory rhythmic descriptions, but this project should still validate exact timing behavior with experienced chanters before encoding it as software logic.
