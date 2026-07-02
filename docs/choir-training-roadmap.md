# ChanterLab — Choir Training Roadmap (SATB + Byzantine, one practice UI)

Status: **exploratory / prototype**. This document records the owner's vision,
what ChanterLab does today, what a one-night OMR + practice-mode spike proved,
and a phased plan to turn it into a real chant *and* choir training tool.

The runnable spike lives in [`training-prototype/`](../training-prototype/)
(feature branch `choir-training`).

---

## 1. The vision

> Four-part-harmony (SATB) choir pieces — e.g. the freely published scores in
> the [Antiochian Sacred Music Library](https://www.antiochian.org/sacred-music-library)
> — get OCR'd from PDF into machine-readable notation (in addition to the
> existing Byzantine-neume import). A singer picks the **voice** they want to
> practise. During playback that voice's audio track is **silenced** so the
> singer supplies it, while the score shows **their** part's notes highlighted
> in **gold** with a follow cursor as the music advances; the other voices are
> rendered de-emphasized (gray). A practice tool for both chanters and choir
> singers.

Two musical worlds, one training experience:

- **Chanters** read Byzantine neume notation (relative, monophonic + ison).
- **Choir singers** read Western staff notation (absolute pitch, SATB harmony).

The goal is a single practice surface that serves both.

---

## 2. What ChanterLab is today (honest inventory)

ChanterLab is a **browser-based Byzantine chant practice app**: a Rust/WASM
tuning + DSP core with a Canvas/WebAudio UI. It has no server; everything runs
client-side. Deployed target: `byz.alwaysdobetterllc.com` (infra tenant
`byzorgan`, served as an external service on beast `:8765`).

What exists and works:

| Area | Reality |
|---|---|
| **Tuning engine** (`src/tuning/`, Rust→WASM) | Full Byzantine scale model: genera, regions, pthora, shading, accidentals, cents/moria math. Solid, test-driven. |
| **DSP** (`src/dsp/`) | Mic pitch detection (FFT + time-domain), gate, filters, PSOLA correction. Real-time AudioWorklet chain. |
| **Scale ladder + singscope** (`web/ui/`) | Interactive microtonal ladder; scrolling pitch trace aligned to the ladder. Zoom/follow mode. |
| **Chant score engine** (`web/score/`) | A `.chant` **text** grammar → `parser.js` → `compiler.js` → a **timed target-note timeline** (`compiled.timeline`), consumed by `score_practice.js` for a "guitar-hero" follow view. |
| **Byzantine neume OCR** (`web/score/glyph_import.js`, PR #38) | Image → glyph-atlas / template-match / CNN → decoded neume groups → chant score. This is the *existing* OCR path. |
| **Exercises** (`web/ui/exercise_mode.js`) | Pitch-holding drills, scoring against a tolerance, best scores in localStorage. |

What does **not** exist today (i.e. what this feature adds):

- **No Western staff notation** anywhere — no MusicXML import, no OSMD/VexFlow,
  no treble/bass clefs, no key signatures.
- **No multi-voice / harmony model.** The whole app assumes one melodic line
  (+ ison drone). SATB is four simultaneous lines.
- **No per-voice mute / per-voice highlight.** Highlighting today follows the
  single chant line.
- **No PDF → notation pipeline for common-practice music** (only Byzantine
  neume images).

So the SATB choir feature is **net-new surface** bolted onto a strong,
reusable spine (timeline model + scoring + singscope + pitch detection).

---

## 3. What the one-night spike proved

### 3.1 OMR pipeline (PDF → MusicXML)

- Fetched 3 real SATB scores from the Antiochian Sacred Music Library
  (Lozowchuk settings: Trisagion, Cherubic Hymn, Anaphora — see
  `training-prototype/omr/pdfs/` and `SOURCES.md`).
- These are **born-digital, cleanly engraved** PDFs (not scans) — which is the
  *good* news: the real corpus ChanterLab would ingest is high quality, not
  noisy phone photos.
- Ran **`oemer`** (deep-learning OMR, ONNX U-Net) on CPU. Findings and accuracy
  are in §3.3 below; provenance and how-to-reproduce in
  `training-prototype/omr/SOURCES.md`.

### 3.2 Practice-mode prototype (the demo)

`training-prototype/` is a **standalone, self-contained web app** (no build
step; OSMD + Tone.js vendored). It renders a 4-part SATB MusicXML score and:

- **S | A | T | B one-tap voice selector.**
- Selected voice noteheads painted **gold (#d4af37)**; other voices **dim gray**.
- A **gold follow cursor** advances through the score in time with playback.
- **Selected voice muted** in the audio mix (each voice is its own Tone.js
  synth) — with an "also hear my part" override.
- **Tempo** slider and **loop a measure range** (the essential practice feature).
- Two content slots: the **OMR'd antiochian piece** and a **hand-made clean
  control** MusicXML, so the UI is verifiable independent of OMR noise.

This is a **standalone prototype, not yet integrated** into the Rust/WASM app —
see §5 for why and how they converge.

### 3.3 OMR accuracy (honest numbers)

Tested on the **Trisagion** page 2 (the first two 4-stave systems), rendered
at 300 DPI. Tool: `oemer` on CPU (~4m48s/page). Raw output:
`training-prototype/omr/out/01_trisagion_lozowchuk_satb-2.musicxml`; detection
overlay: `..._teaser.png`; rendered in the prototype:
`training-prototype/omr/shots/trisagion_omr.png`.

**Primitive symbol detection — strong on this clean engraving:**

| Element | Result |
|---|---|
| Stafflines / staves | 4 of 4 staves found (S/A/T/B), both systems |
| Key signature | 2 sharps detected — **correct** (matches source) |
| Clefs | Treble (G2) and bass (F4) both detected |
| Noteheads | ~151 pitched + 11 rests detected; accidentals & beam groups boxed |

**Structural assembly — this is where it breaks:**

| Element | Result |
|---|---|
| Parts / voices | Collapsed to **1 part ("Piano"), all notes on 1 staff/1 voice** — no S/A/T/B separation |
| Measures / barlines | **1 measure** for the whole page (barline reconstruction failed; a `RuntimeWarning: overflow in scalar subtract` fired during MusicXML build) |
| Note count fidelity | ~151 pitched vs ~105–115 in the source → **~30–45% over-detection** (doubled/spurious heads) |
| Directly usable for SATB practice? | **No.** Renders end-to-end (the prototype loads it), but as one flattened line. |

**Honest conclusion:** `oemer`'s CNN detects the *primitives* well on these clean,
born-digital scores, but its score-assembly stage is built for **1–2 staff**
music and cannot reconstruct a **4-stave bracketed choral system** into
separate voices and measures. So OMR alone does **not** yield SATB-ready
notation here. A production pipeline needs either (a) a choral-aware assembly
stage (staff-group detection → per-staff voice assignment → barline recovery),
(b) per-staff cropping before OMR (feed each of S/A/T/B as its own single-staff
image, then recombine), and (c) a human correction/verification UI regardless.
Option (b) is the most promising near-term fix and is cheap to try, since these
scores keep each voice on its own staff. Given born-digital PDFs, a
**vector-text extraction path** (read note glyphs/positions straight from the
PDF drawing operators) may ultimately beat raster OMR for this specific,
clean corpus — worth a spike.

A second piece confirms the pattern. The **Cherubic Hymn** page 2 OMR'd to:
key = 4 sharps (detected), **1 part again (no S/A/T/B separation)**, but this
time **6 measures** recovered (vs the Trisagion's 1) with 120 notes. So the
**voice-collapse failure is consistent**, while **barline/measure recovery is
inconsistent** across pieces — reinforcing that a choral-aware assembly stage
(not a per-piece tweak) is the real requirement.

The **control** sample proves the practice UX independently; the **OMR slot**
shows the real, imperfect pipeline output and exactly why the correction step
in Phase 4 exists.

---

## 4. Why standalone (not integrated tonight)

Integrating into the shipped app in one night was **not** the right call:

1. The app has **no staff-notation renderer** at all. Adding OSMD (a ~1 MB dep)
   and a MusicXML data path is a real feature, not a patch.
2. The app's timeline/scoring code assumes **one line + moria pitch**; SATB
   needs an **N-voice, absolute-pitch** generalization of that model. That is
   the actual engineering work and deserves tests.
3. A standalone spike lets the owner **see and feel** the interaction (gold
   part, muted voice, loop) before committing the core refactor.

The prototype is deliberately written so its logic (voice model, mute mix,
gold-highlight, follow cursor, loop) maps 1:1 onto the integration plan in §5.

---

## 5. How the two pipelines become one practice UI

Both the Byzantine and SATB pipelines should converge on a **common timed-score
model**, then feed one practice surface. The Byzantine side already produces
`compiled.timeline`; the SATB side produces the same shape with more voices.

```
  Byzantine neume image ─► glyph_import.js ─┐
  .chant text script ─────► compiler.js ────┤
                                            ├─► TimedScore { voices: [ {label, notes:[{pitch, startBeat, durBeat, lyric}] } ], tempo, key }
  SATB PDF ─► oemer ─► MusicXML ─► xml2score ┘
                                            │
                                            ▼
                        ┌──────────────────────────────────────────┐
                        │  Shared practice core                     │
                        │   • voice selector (mute + highlight)     │
                        │   • follow cursor / timeline clock        │
                        │   • per-note scoring vs. mic pitch        │
                        │   • loop / tempo                          │
                        └───────────────┬───────────────┬──────────┘
                                        │               │
                              Neume renderer      Staff renderer (OSMD)
                              (glyph_render.js)   (new)
                                        │               │
                                  Singscope pitch feedback (existing)
                                        └──────► shared ◄─┘
```

Key point: **the singscope + pitch-detection + scoring already do exactly what
choir practice needs for one line.** SATB is the same machinery over N lines
with a voice picker and a staff renderer. Byzantine chant is just "N = 1 (+ison)".

- **Pitch model:** Byzantine notes carry `moria`; SATB notes carry MIDI /
  frequency. `TimedScore` stores frequency (Hz) as the common currency; the
  Byzantine compiler already converts moria→Hz via the tuning grid, and MIDI→Hz
  is trivial. Scoring against the mic works identically.
- **Renderer is pluggable:** neume glyphs vs. Western staff. The gold-highlight
  / dim-others / follow-cursor logic lives in the shared core and calls the
  active renderer to color notes.

---

## 6. Phased plan

**Phase 0 — spike (done tonight).** Standalone OSMD + Tone.js SATB practice
prototype; OMR of real antiochian scores. This document.

**Phase 1 — MusicXML data path + `TimedScore`.** Define the common timed-score
model in JS; write `xml2score()` (MusicXML → `TimedScore`, N voices, key-sig
handling, chords, ties). Unit-test against the hand-made control. Keep the
Byzantine compiler emitting the same shape.

**Phase 2 — staff renderer + voice practice in-app.** Add OSMD behind a
renderer interface; port the prototype's voice selector, per-voice mute,
gold/dim coloring, gold follow cursor, tempo, and measure-loop into the app as
a new "Choir" mode alongside Sing / Scale / Train. Reuse the existing transport
where possible.

**Phase 3 — mic scoring for choir practice (phase-2 of vision).** Wire the
existing pitch detector + singscope to score the *selected* voice against its
target line in real time: live moria/cents offset readout, per-note pass/fail,
tolerance bands. This reuses open backlog items (see §7) — FB-06, VIS-04/05,
FB-04/05 — now applied to a chosen SATB line. Mic pitch-detection for the
singer is the phase-2 deliverable of the owner's vision.

**Phase 4 — OMR ingestion at scale.** Batch-import the Antiochian catalog
(the library API is documented in `training-prototype/omr/SOURCES.md`): a
review/correction UI for OMR output (OMR is never 100%), a small store of
verified scores, tags by hymn type / tone / composer. Copyright/attribution
gate: only ingest freely published, attributable scores.

**Phase 5 — iPad port implications.** The legacy Byzorgan has an `ipad-port`
(Qt/iOS). The web app is the strategic surface; a WKWebView wrapper would carry
the choir feature to iPad for free *if* audio (Tone.js/AudioWorklet) and OSMD
render acceptably in iOS Safari/WKWebView. Known iOS caveats already tracked in
the app (AudioContext gesture unlock, worklet limits) apply. Do **not** invest
in the Qt port for this feature; target the web app + wrapper.

---

## 7. Backlog items this feature touches

From `jayfurz/ChanterLab` issues (all open, `new-feature`):

- **Directly reused for choir mic-scoring (Phase 3):** #5 FB-06 live moria/cents
  readout, #6 VIS-04/05 tolerance bands + trace color, #13 FB-04 score report,
  #14 FB-05 pass/fail, #4 FB-01b target-pitch playback, #11 FB-02 on-target chime.
- **Reused for playback (Phase 2):** #2 AUD-05a arbitrary-scale playback (SATB
  is 12-ET, trivially covered), #21 AUD-10 timbre selection (per-voice timbre).
- **Persistence:** #7 TCH-02 client-side state (store imported/verified scores),
  #36 TCH-01 offline (cache scores + WASM).
- **Not addressed by this feature** (Byzantine-drill-specific): #3, #8, #9,
  #10, #29–#35 (Grand Tour curriculum, adaptive generator, streaks/badges).

No issue currently tracks **SATB import / choir practice** — this roadmap is the
seed for that epic. (Per instructions, no issues were opened or edited.)

---

## 8. Honest gaps — what a real product needs that a night can't build

- **OMR is not turnkey.** Even on clean engravings, OMR output needs a
  human-in-the-loop correction UI before it is trustworthy for practice.
  Rhythm, ties, lyrics-to-note alignment, and voice assignment are the usual
  failure points. See §3.3 for measured reality.
- **Voice-splitting.** Some SATB scores are 2 staves × 2 voices (S+A on one
  staff, T+B on another) rather than 4 separate staves. The prototype handles
  the 4-stave case (which the antiochian Lozowchuk scores use); 2×2 voice
  splitting needs explicit handling in `xml2score()`.
- **Byzantine ↔ staff is not a clean mapping.** Byzantine pitch is relative and
  microtonal; you cannot losslessly render neumes as Western staff or vice
  versa. The two renderers stay separate; only the timed-score *scheduling* and
  *scoring* are shared.
- **Mic scoring for harmony is hard.** Detecting one singer's pitch while other
  voices play through speakers invites bleed/octave errors. Phase 3 needs
  headphone assumptions, robust octave handling, and confidence gating (the DSP
  already has much of this, but it was tuned for solo chant).
- **Licensing.** "Freely published" is not "public domain." Any catalog
  ingestion must preserve composer/source attribution and honor the
  archdiocese's terms.
- **Playback realism.** Tone.js triangle synths are fine for a pitch reference,
  not for a musical choir sound. A sampled or better-voiced organ/vocal timbre
  is a later upgrade (the app already plans additive/sampled organ voices).
