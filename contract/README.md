# The Timed-Score Contract (ONEAPP-01)

Tracking: issue #127, under epic #45. Plan:
[`docs/plans/60-one-app/61-common-timed-score-contract.md`](../docs/plans/60-one-app/61-common-timed-score-contract.md).

A **timed-score document** is the smallest plain-data representation the
practice shell — transport, target lane, recording, scoring — needs, with
adapters from the two notation systems. It is a practice timeline, not a
notation model: rendering stays with OSMD (Western) and the chant glyph
renderer (Byzantine), reachable through `score.sourceRef` and per-event
`anchors`/`notationData` that consumers treat as opaque.

Nothing in the current apps consumes this package yet. Per the plan, adapters
land without changing current consumers; UI migration (steps 5–6) needs owner
approval and stable practice/scoring contracts first.

## Characterization: the two source models

### Western (`training-prototype/`)

`parseMusicXML` (`js/model.js`) produces the single source of truth:
`{ parts: [{ voiceKey, voiceName, index, notes }], measureCount, maxVerse }`,
each note `{ midi, startBeat, durBeat, measure, lyric, lyricVerses }`.

- Times are **quarter-note beats**; seconds are derived on demand from one
  global BPM (`spb = 60 / bpm`) — there is no tempo map; MusicXML tempo marks
  are ignored.
- Pitch is an **integer MIDI number**; the only Hz conversion is
  `440 * 2^((midi-69)/12)` (`js/transport.js` `midiToFreq`).
- Ties are pre-merged into one note; **rests are omitted** (gaps are implicit).
- The loop window is a measure range mapped to beats by min/max note extents
  (`model.measureBeatRange`), and three consumers replicate the same
  window/derivation math: `voices.js buildScopeLane`,
  `scoring-ui.js buildScoreTargets`, `transport.js scheduleAll`.
- Practice transpose (±12 semitones) is added wherever MIDI leaves the model;
  the engraving is untouched.
- Notes have **no stable IDs** (positional only) — a gap this contract fills.

Fixture: [`tests/fixtures/western_parsed.mjs`](tests/fixtures/western_parsed.mjs)
(hand-authored to the parser's exact output shape, semantics documented inline).

### Byzantine (`web/score/`)

`compileChantScore` (`web/score/compiler.js`) flattens the relative-movement
chant DSL into an absolute timeline:
`{ notes, rests, tempoChanges, checkpoints, phraseBreaks, isonEvents,
pthoraEvents, initialTuning, diagnostics, totalDurationMs }`.

- Pitch is **absolute moria** (72 per octave) relative to Reference Ni;
  Hz is `refNiHz * 2^(moria/72)` (`src/tuning/grid.rs` `moria_to_hz`,
  default Reference Ni = 130.81 Hz). The genus interval distinctions
  (8/10/12/14/20 moria) are **not representable in 12-ET MIDI**.
- Times are absolute milliseconds with BPM baked in at compile time
  (real tempo-change support).
- Rests are first-class; ison, pthora (mid-piece tuning mutation), martyria
  checkpoints, and phrase breaks are separate lanes.
- The shipping practice projection is `createScorePracticeState`
  (`web/score/score_practice.js`); its pitch precedence is
  `targetMoria ?? effectiveMoria ?? moria` (retuned-by-grid wins).

Fixtures: the six real example scripts (`web/score/examples.js`), compiled by
the real engine in the tests.

## Document shape (v1.0.0)

```js
{
  contract: 'chanterlab.timed-score',
  contractVersion: '1.0.0',
  adapter: { name, version, options },        // reproducibility record
  score: { id, title, notation, sourceRef },  // sourceRef: opaque render pointer
  capabilities: { microtonal, ison, tuningChanges, tempoChanges, explicitRests,
                  sections, phrases, checkpoints, multiPart, lyrics }, // all explicit
  parts: [{ id, name, role: 'satb'|'melody'|'ison', selectable }],
  timeline: {
    units: 'seconds',
    totalSec,
    events: [{
      id,                        // deterministic; stable across loop windows
      partId, kind: 'note'|'rest',
      startSec, endSec,
      target: {                  // null for rests
        hz,                      // deterministic absolute frequency
        pitch: { type:'midi',  midi, a4Hz }                                  // Western
             | { type:'moria', moria, refNiHz, degree, register, accidentalMoria } // Byzantine
      },
      lyric,                     // display syllable or null
      anchors,                   // source coordinates (measure/startBeat | sourceEventIndex/beats)
      notationData?,             // opaque notation payload (glyphs, scale context, …)
    }],
    tempo:         [{ atSec, bpm }],
    sections:      [{ id, title, anchors: { fromMeasure, toMeasure } }], // measure-anchored
    ison:          [{ atSec, hz, pitch, degree, kind }],
    tuningChanges: [{ atSec, kind: 'initial'|'pthora', detail }],
    checkpoints:   [{ atSec, degree, actualDegree, matches }],
    phrases:       [{ atSec }],
  },
  diagnostics: [],
}
```

Design decisions:

- **Pitch is a tagged union, never rounded.** Every note carries `hz` (the
  universal coordinate every consumer can play or score against) plus its
  native coordinate. Byzantine moria are preserved exactly — the hard
  constraint from the one-app orchestrator ("no MIDI flattening") is
  structural, not conventional.
- **Capability negotiation is explicit and two-way.** All flags must be
  present; the validator rejects documents whose lanes contradict their flags.
  A consumer lacking a capability degrades predictably (hides the control)
  instead of guessing.
- **Event IDs are deterministic and window-stable.** Western: index into the
  part's full note array (`mx:S:3` is the same note in any loop window).
  Byzantine: index into the compiled notes/rests lanes (`ch:note:0`), with
  `sourceEventIndex` anchoring back to the script.
- **Timeline vs notation separation.** Seconds/Hz/lyrics/lanes are the
  timeline; everything renderer-specific lives behind `sourceRef`, `anchors`,
  and `notationData` and is never interpreted by practice consumers.

## Modules

- [`timed_score.js`](timed_score.js) — contract constants, pitch helpers
  (`hzFromMidi`, `hzFromMoria`), `validateTimedScore`.
- [`from_musicxml.js`](from_musicxml.js) — parsed-model adapter
  (`timedScoreFromParsedMusicXML(parsed, { scoreId, bpm, transposeSemitones,
  fromMeasure, toMeasure, sections, sourceRef })`).
- [`from_chant.js`](from_chant.js) — compiled-chant adapter
  (`timedScoreFromCompiledChant(compiled, { scoreId, refNiHz, includeRests,
  sourceRef })`).

Both adapters are pure and deterministic: same input + same options →
byte-identical document.

## Verification

`contract/tests/` runs in the `root-js` CI job (`npm test`):

- the Western adapter is compared against an independent replication of the
  current apps' window/beat→seconds/Hz math (the shared formula of
  `buildScopeLane` / `buildScoreTargets` / `scheduleAll`);
- the Byzantine adapter is compared event-by-event against the shipping
  `createScorePracticeState` projection for all six real example scripts,
  including ison/tuning/tempo lanes and the rest in `soft-chromatic-phrase`;
- a soft-chromatic example proves intervals off the 12-ET grid survive.

## Versioning, migration, rollback

`contractVersion` is semver. Consumers accept any minor/patch within their
major (`validateTimedScore` enforces major match). Additive fields bump minor;
breaking shape changes bump major and require a migration note here. Rollback
is trivial while nothing consumes the contract: the package is additive and
side-effect-free, and reverting the commit restores the previous state
exactly.
