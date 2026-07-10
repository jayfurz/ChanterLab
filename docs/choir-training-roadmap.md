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
- **Singscope with live mic pitch** (added 2026-07-02 on owner feedback):
  mobile-first piano-roll lane — selected voice's targets in gold, live pitch
  as a cyan trace, octave-tolerant **±50¢** matches glow gold, note-name/cents
  readout. JS autocorrelation detector (see prototype README §pitch detection
  for the works-tonight rationale, latency, and the WASM swap-in point). The
  same session made the whole prototype responsive (360/390 px verified) with
  cursor auto-scroll and thumb-sized controls.

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
clean corpus — worth a spike. **(Spike done the next night — it wins
decisively; see §3.4.)**

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

## 3.4 OMR bake-off (2026-07-02) — vector extraction wins

Following §3.3's hunch, three pipelines were built/run on the same corpus and
scored against a **hand-encoded ground truth**: the first 8 measures × 4
voices of the Trisagion (page 2, both systems — system 2 is a *varied*
repeat, so it's real test data), encoded from 7–9× zoomed renders note by
note (`training-prototype/omr/ground_truth/trisagion_p2_gt.json`, committed).
Judge: `omr/score_extraction.py` — LCS alignment per voice; metrics are
note recall/precision per voice, duration accuracy on matched notes,
voice-assignment, and measure integrity.

**Why vector extraction is even possible:** the Antiochian PDFs are Dorico
exports. Every notehead/clef/rest/accidental is a **Bravura (SMuFL) font
glyph at exact coordinates** (noteheads use Bravura's "oversized" alternates
U+F4BC/BD/BE); staff lines, stems, beams and barlines are vector paths. No
pixels are ever rendered — `omr/vector_extract.py` reads the primitives with
PyMuPDF and reassembles notation deterministically.

### Scoreboard — Trisagion p2 ground truth (8 measures, 161 notes)

| Metric | oemer (raster OMR) | Audiveris 5.10.2 (raster OMR) | **vector extraction** |
|---|---|---|---|
| Parts produced | 1 ("Piano") | 4 (SOPRANO/ALTO/TENOR/BASS) | **4 (Soprano/Alto/Tenor/Bass)** |
| Voice-aware note recall | 28.6% | 100% | **100%** |
| Voice-aware note precision | 28.4% | 100% | **100%** |
| Voice-blind pitch recall / precision | 77.0% / 76.5% | 100% / 100% | **100% / 100%** |
| Duration accuracy (matched notes) | 84.8% | 100% | **100%** |
| Measures recovered (of 8) | 1 | 8 | **8** |
| Per-voice measure-length match | 0% | 100% | **100%** |
| Lyrics | none | partial (S+T lines) | **full syllables + hyphenation** |
| Runtime (whole piece, CPU) | ~4 m 48 s **per page** | ~20–45 s per piece | **~0.15–0.2 s per piece** |
| Footprint | Python + ONNX U-Net | JDK 21 + Audiveris + Tesseract | **PyMuPDF only** |

### The tie-breaker: the Cherubic Hymn's 2-staff reduction pages

The Trisagion/Anaphora are 4-staff (easy mode: one voice per staff). The
Cherubic Hymn's first two pages are a **2-staff choral reduction** (S+A share
the treble staff, T+B the bass) — the classic voice-separation nightmare:

- **Audiveris** keeps the reduction as 2 parts with 2 internal MusicXML
  voices each and generic/partial names (`Voice`, `Voice`, `ALTO`, `BASS`),
  and stitches the mid-piece 2-staff↔4-staff layout switch into an
  inconsistent 4-part hybrid. Not loadable as S|A|T|B without writing the
  entire voice-splitting layer anyway.
- **vector extraction** emits 4 clean named parts across the layout switch.
  Stem direction gives the definite assignments; the genuinely ambiguous
  notations (written unisons/a2, single-stem chords, lone whole notes,
  stacked whole pairs, shared vs voice-specific rests) are resolved by a
  per-measure **constrained search**: both voices of a staff must sum to the
  same beat count, both staves of a system must agree on the measure length,
  and engraving-convention priors break the remaining ties. Full-piece
  measure integrity: **Trisagion 22/22, Cherubic 29/29, Anaphora 51/51
  measures (100%)**, with every assumption logged in the confidence report.

Honest caveats where Audiveris did *well*: on 4-staff pages it matched the
ground truth perfectly (it is the reference OMR for a reason), and on the
Anaphora's bass divisi it kept the secondary line as MusicXML voice 2 where
vector extraction currently **drops secondary divisi streams** (3 spots in
the Cherubic, all reported with exact pitches — correction-UI material).
Audiveris also logged 40 warnings on this corpus (unmetered music trips its
time-signature checks) and its OCR lyric capture was partial.

### Verdict

**`omr/pipeline.py` = vector extraction** (usage in `omr/README.md`):
PDF → 4-voice MusicXML + JSON confidence report; refuses scanned PDFs
(exit 3) instead of guessing; exits 2 below a measure-integrity threshold.
All three full pieces load in the practice prototype with working S|A|T|B
selection, gold highlighting, per-voice mute, and follow cursor
(screenshots: `omr/shots/trisagion_vector_S.png`,
`omr/shots/trisagion_vector_T_play.png`, `omr/shots/cherubic_vector_A.png`).

Scope honesty: this wins **for born-digital engravings** — which is what the
Antiochian library serves (≈3,800 items, largely Dorico/Sibelius-era
publications). For scanned/photographed scores, Audiveris is the fallback
path already validated above (JDK 21 user-level install, batch CLI), with
the caveat that 2-staff reductions then still need a voice-splitting
post-pass like the one built here.

### Phase-2 correction UI — what the residuals actually need

From the confidence reports, the correction UI only has to handle a short,
well-defined list (all locations are already machine-reported):

1. **Dropped divisi streams** (secondary line under a held note): offer
   "restore as chord / restore as second voice / leave out".
2. **Unison-assumption review**: measures where a2 duplication or ambiguous
   whole/rest routing was applied — show the choice, allow flipping.
3. **Repeat structure**: repeat barlines + "x5" texts are detected and
   reported but not expanded; UI should let the user set verse counts.
4. **Lyric attachment nits**: syllable→note mismatches are counted in the
   report; a click-to-reassign affordance suffices.
No pitch/duration editor is needed for this corpus — no pitch or duration
errors were found against ground truth.

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

**Phase 3 — mic scoring for choir practice (phase-2 of vision).**
*First slice shipped in the prototype (owner request, 2026-07-02):* `scope.js`
adds a mobile-first **singscope** — gold target lane for the selected voice,
live mic pitch via JS autocorrelation (see prototype README for the detector
choice + latency numbers), octave-tolerant ±50¢ gold-glow hit feedback, and a
note-name/cents readout.
*Still open for 3b:* per-note pass/fail + exercise scoring (reuse the
`exercise_mode.js` patterns: tolerance bands, per-step stats, best scores),
score report at loop end, swapping in the WASM worklet detector for lower
latency/robustness, and tuning the hit band per skill level. This reuses open
backlog items (see §7) — FB-06, VIS-04/05, FB-04/05 — now applied to a chosen
SATB line.

**Phase 4 — ingestion at scale.** Batch-import the Antiochian catalog with
`training-prototype/omr/pipeline.py` (the library API is documented in
`training-prototype/omr/SOURCES.md`): the vector pipeline's confidence
report gates each piece (integrity threshold), a review/correction UI covers
the short residual list in §3.4, a small store of verified scores, tags by
hymn type / tone / composer. Raster OMR (Audiveris) is only the fallback for
scanned uploads. Copyright/attribution gate: only ingest freely published,
attributable scores.

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
