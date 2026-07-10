# OMR full-score verification — 2026-07-02

Systematic audit of the three extracted scores (`training-prototype/content/*_vector.musicxml`)
against the original Antiochian Sacred Music Library PDFs, prompted by the owner's
report of "errors in the rendering of the notes" and "notes squished together" on
the live training page.

**Scope:** every measure × every voice of all 3 pieces — Trisagion (22 mm),
Cherubic Hymn (29 mm, mid-piece closed→open score switch), Anaphora (51 mm).
408 measure-voices, 1,850 printed noteheads.

**Method** (`training-prototype/omr/verify/`):

| Tool | What it proves |
|---|---|
| `coverage.py` | machine check: every notehead/rest glyph in the PDF appears in the final MusicXML or is explicitly accounted for (exit 1 otherwise) |
| `annotate.py` | draws every extracted event back onto the PDF at its own coordinates (voice-colored dot + pitch/duration label) — drops, voice-routing, durations, accidentals, ties are verified against the engraving itself; `-m N` gives a 6× single-measure zoom |
| `render_compare.py` | verovio render of the extracted MusicXML per system, stacked under the matching PDF crop (uses the extractor's own staff/measure geometry) |
| `shot.mjs` (existing) | live-page OSMD screenshots for before/after |

Bake-off ground truth (`score_extraction.py` vs `ground_truth/trisagion_p2_gt.json`)
still passes at 100 % recall / precision / duration accuracy after all fixes.

---

## 1. Discrepancy catalog

### Counts by class

| Class | Found | Fixed |
|---|---|---|
| (a) extraction bugs | 4 distinct bugs, 3 pieces affected | **all fixed** |
| (b) documented limitations (verified, kept) | 5 kinds | reported in confidence report |
| (c) renderer/layout artifacts | 3 kinds | 2 fixed in emitter, 1 needs a 1-line app.js option |
| (d) fine | everything else — all 102 measures' pitches, durations, voice routing, accidentals, key signatures, clefs verified correct | — |

### (a) Extraction bugs — all fixed in `vector_extract.py`

**a1. False ties (20 note events).** A melisma slur whose first and last notes have
the same pitch (very common in chant: D–C♯–D turn figures, "Lord.___" phrases) was
classified as a tie because `_apply_ties` only compared endpoint pitches. The result
tied non-adjacent notes across intervening pitches.

| Piece | False ties (measure/voice) | Real ties (verified, preserved) |
|---|---|---|
| Trisagion | m1 A, m9 A | m17 B (G3–G3 beamed pair) |
| Cherubic | m25 S, m25 A, m25 B (both chord heads), m28 A | none |
| Anaphora | m2 S, m2 A, m3 S, m3 T, m12 S, m12 A, m15 A, m17 S, m17 A, m19 S, m36 S, m40 S, m45 B, m48 S | m13→14 T, m25 T, m32→33 A, m34 T, m50→51 T (incl. across barlines) |

*Fix:* a tie now additionally requires the two events to be **consecutive** in the
voice (no other note of that voice strictly between them on the same staff).
Tie counts went 3/4/20 → 1/0/5, matching the engraving exactly.

**a2. Printed naturals played sharp in the app.** Printed naturals (e.g. C♮5 against
the 2-sharp key in Trisagion mm.3/7/11/17/21 and the C♮3 bass cadences) were emitted
with no `<alter>` element. That is *legal* MusicXML (absent alter = natural), but the
app's parser falls back to the key signature when `<alter>` is missing, so every
printed natural **played a semitone sharp** on the live site — almost certainly part
of the owner's "errors in the notes" report. The emitter now writes an explicit
`<alter>` (including `<alter>0</alter>`) whenever the key signature would otherwise
alter the step. 27 notes affected in Trisagion; 0 in the other two pieces (no
out-of-key naturals printed).

**a3. Lyrics silently dropped in tight systems + junk lyrics.** The lyric band below
a staff ended `2.0 staff-spaces` above the next staff; in Anaphora's tight systems
the lyric baseline sits ~2.0 sp above the alto staff, so soprano lyrics for
mm.13–19 and 26–29 ("It is meet and right", "Ho-san-na in the high-est") missed the
band by 0.1 pt and were dropped. Meanwhile the *last* staff's band swallowed
non-lyric text: bass picked up `=` (from a "♩ = 98" tempo line) and `are` (from the
"*parenthetical notes are optional" footnote) as lyrics. Fixed: band widened to
0.5 sp above the next staff, and text lines matching tempo/footnote patterns
(`=`, digits, `N.B.`, leading `*`, `rit.`) are excluded. Soprano lyric coverage in
Anaphora went 37 → 47 measures (now identical to tenor's); bass junk gone.

**a4. Tempo marks: only the first captured, always placed at measure 1.** The
Cherubic Hymn opens "Gently" (no metronome mark) and switches to "Lively ♩ = 110"
at m21 — the extractor stamped 110 onto m1. The Anaphora has **eight** metronome
marks (♩ = 56, 90, 98, 94, 56, 60, 74, 70); only the first was kept. Now every
`♩ = NN` mark is captured with its page/x/y and emitted as a
`<metronome>` direction + `<sound tempo>` at the measure it sits above
(top part only). Verified placements: Cherubic m21=110; Anaphora m1=56, m8=90,
m10=98, m13=94, m16=56, m30=60, m32=74, m36=70.
(The prototype's playback uses its own BPM slider, so this is display/metadata
correctness today, and enables future "tempo follows the score" playback.)

### (b) Documented limitations — verified against the PDFs, still open

1. **Bass divisi drops — exactly 3 spots / 6 notes, as documented.** Cherubic
   m27 `[A2 E2 G2]`, m28 `[B2]`, m29 `[E2 F2]`: a second bass stream the
   engraver wrote under the main line; the divisi-subset search keeps the primary
   stream and reports the drop. Confirmed by `coverage.py`: these are the *only*
   unextracted noteheads besides (2) below. Correction-UI material.
2. **Parenthesized optional notes — 9 skipped, Anaphora mm.44–51.** The score's own
   footnote says "*parenthetical notes are optional*". Skipped + reported.
3. **Unison a2 duplications** (9 in Cherubic) — every one checked against the
   print; all musically correct (both voices genuinely sing the note).
4. **Repeat barline not encoded.** Cherubic m19–20 "x5" Amen repeat is treated as a
   plain barline (noted in the report). The app has no repeat support either.
5. **Text directions not extracted:** "Sl. Slower", "a tempo", "rit.", "N.B.",
   dynamics (p, pp, hairpins), breath marks. Cosmetic for the training use-case.

### (c) Renderer/layout artifacts

1. **No beams emitted** → OSMD/verovio drew every 8th/16th with a flag, unlike the
   beamed engraving; dense melismas became unreadable. **Fixed:** beam groups are
   reconstructed from the beam-quad geometry (union-find over stems), and
   `<beam>` elements are emitted incl. two-level beams and 16th stub hooks
   (`backward/forward hook`) for dotted-8th+16th figures.
2. **Squished measures** — see §2. **Fixed** (emitter-side), plus one recommended
   app.js option below.
3. **Slurs are not emitted** (only ties). The PDF shows phrase/melisma slurs that
   our render omits. Deliberate scope choice; does not affect notes or playback.

---

## 2. The "squished notes" problem

**Root cause.** These pieces are unmetered chant: the extractor emits whole phrases
as single measures with hidden time signatures (up to 10 quarters, e.g. Anaphora
m14; Cherubic's opening phrases are 8 beats). OSMD cannot break a line inside a
measure, so it packed 2–3 giant measures per line at minimum note spacing —
glyphs collide, lyrics overlap. Flagged (unbeamed) 8ths made it look worse.

**Fixes (all in the extractor's MusicXML, no app changes):**

1. **Invisible-barline splits.** Measures longer than 6.5 beats are split at beat
   positions where *all four voices* have an event onset (target segment ≈4.5
   beats), joined by `<barline location="right"><bar-style>none</bar-style></barline>`.
   Sub-measures keep the printed measure `number` (continuations get
   `implicit="yes"`), so the app's measure-loop UI still addresses printed measures.
   Layout measure counts: Trisagion 22→23, Cherubic 29→38, Anaphora 51→54.
   Accidental memory is carried across sub-measures of one printed measure, and
   explicit `<alter>`s (fix a2) keep pitches unambiguous for every consumer.
2. **Beams** (see c1) — dense passages now occupy realistic width.
3. **Engraving geometry hints:** every measure now carries its real engraved
   `width` (in tenths, from the PDF's own measure spans) and each PDF system start
   is marked `<print new-system="yes"/>`. OSMD ignores these *by default* — see
   the recommendation below — but any renderer that honors them can reproduce the
   original line breaks exactly.

**Result:** before/after of the same passage:
`training-prototype/omr/verify/proof/5_anaphora_before_after_live.png`
(top = before: crushed flags/lyrics; bottom = after: beamed, spaced, readable).

---

## 3. Proof images (side-by-side, PDF truth vs extraction)

All under `training-prototype/omr/verify/proof/`:

1. `1_cherubic_m4_closed_score_voice_split.png` — 6× overlay: closed-score S/A and
   T/B separation incl. side-by-side halves+quarters, dotted values, 16th run.
2. `2_cherubic_m24-25_after_tie_fix.png` — "by the angelic hosts": false ties gone,
   octave divisi chords, dotted rhythms, beams matching the print.
3. `3_anaphora_m27-29_16th_runs.png` — the big Hosanna melisma: dotted-8th+16th
   groups, two-level beams, final whole-note chord.
4. `4_cherubic_m26-28_divisi_drop_overlay.png` — annotated overlay where printed
   noteheads *without* a colored dot are exactly the documented bass-divisi drops.
5. `5_anaphora_before_after_live.png` — live-page before/after of the squish fix.

Full per-system audit imagery: `verify/out/*_ann*.png` (annotated overlays) and
`verify/out/*_sys*.png` (render comparisons), regenerable via
`verify/annotate.py` / `verify/render_compare.py`.

---

## 4. Recommendation for the UI agent (app.js — NOT applied here)

1. **One-liner, high value:** add `newSystemFromXML: true` to the OSMD constructor
   options in `loadScore()` (app.js ~L181). The MusicXML now carries
   `<print new-system="yes"/>` at every original engraving line break, so with this
   option the on-screen line breaks will mirror the printed score.
2. Optional cosmetic: OSMD's displayed measure numbers are its own ordinal count,
   which since the layout splits no longer matches printed numbers (the loop UI
   *does* use printed numbers from the XML). Either `drawMeasureNumbers: false`
   or (if the bundled OSMD supports it) `EngravingRules.UseXMLMeasureNumbers = true`.
3. FYI, app parser nit (moot for our files since fix a2, but affects any external
   MusicXML): `parseMusicXML` applies the key signature when `<alter>` is absent;
   per MusicXML semantics an absent `<alter>` means natural.
