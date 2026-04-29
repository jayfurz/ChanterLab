# ChanterLab Chant Script Engine Implementation Brief

Audience: implementation agent or engineer.

Status: ready-to-implement brief. This file summarizes the score/script plan in an actionable form. The source design document remains `docs/BYZANTINE_CHANT_SCORE_PROPOSAL.md`.

## Hard Constraints

- Do not stop, restart, kill, or bind over any existing server on port `8765`.
- Do not run destructive process commands such as `killall`, broad `pkill`, or anything that targets port `8765`.
- Do not make real hymn editions or copyrighted chant books part of the repository unless source/reviewer/copyright status is explicitly documented.
- Keep the existing Sing, Scale, Train, Settings flows working while implementing the score engine.
- Prefer adding isolated `web/score/` modules and tests before touching UI.
- Do not rewrite the tuning engine unless a narrow, reviewed integration point requires it.

## Recommended Worktree Workflow

Use a separate worktree so the existing server can continue serving the current repo state.

```sh
git worktree add ../chanterlab-score-engine -b feature/chant-script-engine
cd ../chanterlab-score-engine
```

Important: if the plan files are not committed yet, a new worktree will not contain them. Either commit the docs first, or provide this brief plus `docs/BYZANTINE_CHANT_SCORE_PROPOSAL.md` and `docs/examples/chant_scripts/` to the agent as context.

If local serving is needed later, use a non-`8765` port, for example:

```sh
python3 -m http.server 8776 --directory web
```

Only start a local server after parser/compiler tests pass. Do not use `8765`.

## Source Documents

Read these first:

- `docs/BYZANTINE_CHANT_SCORE_PROPOSAL.md`
- `docs/examples/chant_scripts/README.md`
- `docs/examples/chant_scripts/*.chant`
- `docs/BYZANTINE_SCALES_REFERENCE.md`
- `docs/ARCHITECTURE.md`

External references named in the design:

- Unicode Technical Note #20, Byzantine Musical Notation
- SBMuFL / Neanes metadata, especially `glyphnames.json`

Do not fetch external data during the first parser/compiler phase unless needed. The seed script grammar can be implemented from the local docs.

## Goal

Implement an English-first symbolic chant script engine that can compile a small chant phrase into timed target-note/rest/tempo events for future score-practice playback and display.

The engine must keep these layers separate:

1. Semantic movement and timing.
2. Byzantine orthography/glyph display.
3. Imported source tokens.
4. Training/playback timeline.

The immediate goal is not a full notation importer. The immediate goal is a stable semantic parser/compiler that future importers and UI tools can target.

## Non-Goals For The First Pass

- Do not implement full Unicode/SBMuFL glyph import yet.
- Do not implement OCR.
- Do not implement full orthographic generation rules yet.
- Do not implement attraction grammar yet.
- Do not replace the current training modules yet.
- Do not add copyrighted or unreviewed real hymn transcriptions.

## Suggested File Layout

Prefer a new isolated module tree:

```text
web/score/
  chant_score.js
  parser.js
  compiler.js
  timing.js
  glyph_defaults.js
  diagnostics.js
  examples.js
```

Optional tests:

```text
web/score/tests/
  parser.test.mjs
  compiler.test.mjs
  timing.test.mjs
```

If Node ESM friction appears, either keep tests as `.mjs` or add a narrow `web/score/package.json` with `{ "type": "module" }`. Do not add broad project tooling unless necessary.

## Data Model

Implement the model described in `docs/BYZANTINE_CHANT_SCORE_PROPOSAL.md`, including:

- `ChantScore`
- `LyricLine`
- `LyricAttachment`
- `ScoreEvent`
- `NeumeEvent`
- `RestEvent`
- `TempoEvent`
- `MartyriaEvent`
- `PthoraEvent`
- `PhraseBreakEvent`
- `IsonEvent`
- `CompiledNote`
- `CompiledRest`
- `CompiledTempoChange`
- diagnostics for unsupported or ambiguous syntax

Use plain JavaScript objects in v0. TypeScript-style shapes in the docs are specifications, not a requirement to add a TS build.

## Symbolic Grammar V0

Implement the strict symbolic grammar from the proposal.

Required headers:

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
drone <degree> [octave <integer>]
```

Required note forms:

```text
note same [modifier...]
note up <steps> [modifier...]
note down <steps> [modifier...]
```

Required note modifiers:

```text
beats <number>
quick
divide <number>
duration <number>
scale <scale-name> [phase <number>]
drone <degree> [octave <integer>]
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

Required rest forms:

```text
rest
rest beats <number>
rest duration <number>
rest quick
```

For v0, reject `rest quick` with a diagnostic until rest-temporal behavior is reviewed.

Required checkpoint and phrase forms:

```text
checkpoint <degree>
phrase
phrase checkpoint <degree>
```

Required degrees:

```text
Ni Pa Vou Ga Di Ke Zo
```

Required scales:

```text
diatonic
soft-chromatic
hard-chromatic
western
```

Required English tempo names:

```text
very-slow
slower
slow
moderate
medium
swift
swifter
very-swift
```

Required aliases:

```text
same -> note same
up N -> note up N
down N -> note down N
hold N -> note same beats N
silence N -> rest duration N
text "Text" -> lyric "Text"
_ -> lyric continue when used as a note modifier
ison <degree> [octave <integer>] -> drone <degree> [octave <integer>]
martyria <degree> -> checkpoint <degree>, or start <degree> before notes
pthora <scale-name> phase=N -> scale <scale-name> phase <N>
gorgon -> quick
digorgon -> divide 3
trigorgon -> divide 4
apli / klasma -> beats 2
dipli -> beats 3
tripli -> beats 4
```

Parser behavior:

- Reject unknown keywords.
- Keep line/column diagnostics.
- Treat keywords and degree names case-insensitively.
- Require quoted strings for titles and multi-word lyrics.
- Default `timing` is `symbolic`.
- Default `orthography` is `generated`.

## Timing Semantics

Implement two timing modes.

`symbolic`:

- `beats N` means notated base duration before temporal rewrite.
- No timing modifier means one notated beat.
- `quick` means the basic gorgon-like previous/current rewrite.
- For v0, implement this core case:

```text
note same beats 2
note up 1 quick
```

Expected compiled beats:

```text
1.5
0.5
```

- Preserve the total local window duration.
- `divide 3` and `divide 4` may parse but can emit "not implemented" diagnostics until reviewed.

`exact`:

- `duration N` means already-compiled duration in beats.
- Reject or diagnose symbolic temporal modifiers in exact mode.

Rests:

- `rest` is one silent beat.
- `rest beats N` is a symbolic silent event.
- `rest duration N` is an exact silent duration and never steals from neighbors.
- Reject `rest quick` in v0.

## Lyrics Semantics

Line-level lyrics are metadata:

```text
language en
lyrics "Amen"
lyrics greek "Kyrie eleison"
translation english "Lord have mercy"
```

They do not auto-align to notes.

Note-level lyrics are alignment:

```text
note same lyric "A-"
note up 1 lyric continue
note down 1 quick lyric "men"
```

Rules:

- `lyric "Text"` starts a new lyric unit.
- `lyric continue` continues the previous lyric unit across a melisma.
- `lyric none` explicitly marks no lyric.
- Omitted lyric means `none` in v0, optionally with a warning if surrounding notes have lyrics.
- Rests should not carry lyrics in v0.

## Orthography And Glyphs

Do not tie pitch movement to a single glyph.

Example:

```text
note up 1
```

means semantic upward movement by one degree. It may display as `oligon` by default, but later may display as `petasti` or another glyph based on orthography rules.

V0 default display glyphs:

```text
note same -> ison
note up 1 -> oligon
note down 1 -> apostrofos
note down 1 quick -> apostrofos + gorgon
```

Explicit hints:

```text
note up 1 glyph petasti
note up 1 style petasti
```

These preserve/request display or qualitative metadata. They do not change pitch movement by themselves.

## Compiler Responsibilities

The compiler should:

1. Parse `.chant` text into `ChantScore`.
2. Resolve starting note and scale context.
3. Resolve relative movement into scale degrees/register positions.
4. Preserve pthora/scale-change events.
5. Preserve drone/ison events.
6. Preserve checkpoint events.
7. Compile symbolic or exact durations.
8. Produce `CompiledNote`, `CompiledRest`, and `CompiledTempoChange` events.
9. Attach lyric alignment to compiled notes.
10. Attach generated/default display glyph hints.
11. Emit diagnostics without crashing on unsupported but recognized constructs.

For v0, target degree/register sequencing is enough. Full moria/frequency integration can be added after parser/compiler tests pass. When pitch integration is added, reuse the existing tuning engine rather than inventing a parallel tuning model.

## Seed Fixtures

The parser/compiler must handle:

- `docs/examples/chant_scripts/diatonic_ladder.chant`
- `docs/examples/chant_scripts/soft_chromatic_phrase.chant`
- `docs/examples/chant_scripts/symbolic_timing_steal.chant`
- `docs/examples/chant_scripts/lyrics_melisma.chant`

Add expected-output tests for at least:

- number of parsed events,
- start degree,
- scale name/phase,
- lyric attachment sequence,
- checkpoint degree,
- `beats 2` + `quick` compiling to `1.5` and `0.5`.

## UI Integration Plan

Do not start with UI.

After parser/compiler tests pass:

1. Add a small internal sample loader for the seed scripts.
2. Add a disabled-by-default Score Practice prototype.
3. Render target bars on the singscope or a separate canvas.
4. Show generated glyph labels near target bars when available.
5. Show lyric text under or near target bars.
6. Compare live pitch to active compiled note only after timeline playback is stable.

Keep this behind a feature flag or hidden development control until Justin confirms it is ready.

## Verification

Minimum checks before handoff:

```sh
cargo test
cargo test --features serde
make build-main
make build-worklet
```

Also run syntax checks on touched JS modules. If a Node test harness is added, document the exact command and run it.

Do not use port `8765` for manual testing. If browser testing is needed, use a separate worktree and a different port.

## Handoff Checklist

Before asking for review:

- Parser accepts all seed `.chant` files.
- Unsupported but recognized constructs produce diagnostics, not crashes.
- Existing app still builds.
- Existing Rust tests pass.
- Score engine modules are isolated under `web/score/`.
- No server on port `8765` was stopped, restarted, or reused.
- Any UI entry point is disabled by default or clearly marked experimental.
- New real hymn content, if any, has source/reviewer/copyright comments.
