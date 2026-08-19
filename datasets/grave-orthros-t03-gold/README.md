# grave-orthros-t03 — gold dataset #2

Chanter-verified alignment ground truth for hymn `t03_` of *Mode Grave
Anastasimatarion 2 Orthros* (Vasilikos recording, Ioannou printed
Anastasimatarion, born-digital vector score). Frozen 2026-08-18, **revision 2**
(chanter-corrected segmentation: 76 units, was 75 — see "Revision 2" below).

This is the first **densely pinned** gold piece: the chanter placed a timing
anchor on *every one* of the 76 score units, not a sample. It is also the first
gold with explicit **neume-level notation corrections** in the chanter's own
words.

## What is in here

| file | what it is |
|---|---|
| `pins.json` | 76 `[unit_index, onset_seconds]` chanter timing anchors — one per unit, units 0–75 complete |
| `chanter_notes.json` | the 25 flagged glyphs: the chanter's note verbatim, plus the machine decode it was reacting to and the pre-split export index |
| `score_units.json` | the frozen score-side unit stream the pin indices refer to |
| `baseline.json` | machine-vs-gold metrics at freeze time, plus the audio checksum |

The chanter's untouched browser export stays at `../exports/grave-orthros-t03/`
in its original 75-unit indexing. This directory is the curated, re-indexed
copy; nothing here is overwritten by an export.

`score_units.json` is the load-bearing file. Pin index *i* means unit *i* **of
this exact stream**. The stream is produced by `load_units_h()` in
`tools/corpus/hymn_align.py` from pages 520 lines 6–11 of the glyph corpus, and
it is stable only as long as unit segmentation does not change. If segmentation
is revised, the pins must be re-indexed against this file, not silently reused —
revision 2 is the worked example.

`prep_hymn_annotator.py` ships this directory to the annotator as a **seed**, so
re-segmenting a piece costs a re-index rather than the chanter's work: when
`data_rev` changes and no local edits match, the annotator restores these pins
and notes instead of presenting a blank piece.

The audio is `melos_t03_/audio.wav` in the corpus workdir, sha256 prefix
recorded in `baseline.json`. It was re-cut from tape at RMS pause boundaries
158.5–211.9 s; pins are meaningless against any other cut.

## Revision 2 — the segmentation correction

Chanter, 2026-08-18, on what was unit 6:

> it should be split into an oligon and ison (two neumes) … there is an omalon
> underneath the ison and the oligon, and the oligon is preceded by a vareia.
> both the vareia and [omalon] are interpreted qualitative neumes that have no
> quantity associated with them … there is no apli

The raw vectors bear this out exactly. On page 520 line 6:

| cluster | x range | colour | identity |
|---|---|---|---|
| 12 | 231.1–241.0 | black | vareia — qualitative, already silent |
| 6 | 239.8–273.7 | black | **oligon, +1** |
| 36 | 253.8–289.2 | black | **omalon** — ties the two, qualitative |
| 5 | 275.5–308.9 | black | **ison, 0** |

The oligon ends at 273.7 and the ison starts at 275.5, so **they never touch**.
They were fused into one unit only because the omalon overlaps both and unit
grouping was transitive. The machine then picked the ison as the base (largest
area), demoted the oligon to a mark, and read the whole thing as one note of
interval 0. Cluster 36 was additionally listed in `APLI`, adding a beat that
does not exist.

Two fixes in `tools/corpus/hymn_align.py`:

1. `_note_subgroups()` — base candidates that do not *directly* x-overlap are
   separate notes. Candidates that do overlap stay fused, which preserves the
   genuine vertical compounds (ison printed over petasti, petasti+oligon). The
   rule is generic, so every span mark benefits: the **eteron** (31, red,
   bridges **324/325** — chanter-confirmed 2026-08-18), the **omalon** (36,
   225/261), a wider eteron variant (74, 10/10, unconfirmed), tie/syndesmos
   (85) and di/trigorgon (25, 30). The chanter flagged this class
   independently: *"another glyph that is sometimes two wide is the eteron"*.
   All three are now recorded in `scores/atlas_chanter.json`.
2. `APLI` no longer contains 36. The real apli/dipli is cluster 10, still
   unwired because it needs the duration model first (dipli = 2 beats,
   tripli = 3, vareia + apli adjacent = a rest).

Corpus-wide this splits 609 of 108,348 groups (0.56%), adding 79 units across
169 hymns; 58 hymns changed unit count. All `unitdeg_*.json` were regenerated
and every hymn re-aligned.

Re-indexing: old unit *g* maps to *g* for g ≤ 6 and *g*+1 for g ≥ 7. The new
unit 7 (the ison) was pinned at 5.043 s, the midpoint of the old units 6 and 7
(4.527 and 5.560) as the chanter directed. `chanter_notes.json` keeps
`gi_export_75unit` on every note so the mapping stays auditable.

## The state of the machine

| measure | r1 (75 units) | r2 (76 units) |
|---|---|---|
| units matched | 44 / 75 (58.7 %) | 54 / 76 (**71.1 %**) |
| aligner movement agreement | 0.98 | 0.96 |
| pins within 0.35 s | 6 / 44 | **16 / 54** |
| median &#124;Δt&#124; vs gold | 4.10 s | **0.563 s** |
| p90 &#124;Δt&#124; | 6.65 s | 4.68 s |
| strict-on-pins | 0.784 | 0.787 |

The segmentation fix alone cut median onset error by a factor of seven. Note
what movement agreement did while that happened: it went **down**, 0.98 → 0.96.
It is measured against the aligner's own decoded degree sequence, so it rewards
a self-consistent path whether or not that path sits at the right moment in
time. **Never tune on movement agreement alone — check the gold pins.**

A large excursion survives. The alignment is exact for units 0–2, drifts to
−5.8 s by unit 12, and only recovers around unit 25. Nothing in the cost model
anchors the path to absolute time, so a single slip is permanent. That is the
core remaining defect and the reason the pins exist.

Meanwhile strict-on-pins is 0.787: sampled at the chanter's own onsets, the
*pitch* reading agrees with the notation about 79 % of the time. So notation
decoding is mediocre-but-working and **timing is the broken half**.

## The 25 chanter notes

Nine are live in the pipeline as interval overrides in `iv_ovr_t03_.json`
(post-split indices 0, 1, 2, 3, 6, 10, 12, 13, 14). Nine more carry text that
**has never reached the pipeline** — there is no automated path from a
free-text note to anything the aligner reads. `chanter_notes.json` marks these
`pending_transcription: true`.

Six flags carry an empty note (post-split units 22, 24, 31, 36, 39, 42). They
are recorded as `note_empty: true` and must be treated as unresolved — do not
infer content for them.

The 25th note is the new ison at unit 7, recording why the split happened.

The notes are not all the same kind of correction, which is why a single
override file cannot absorb them:

- **interval** — "Oligon makes it +1", "up three". Sink exists:
  `iv_ovr_<hymn>.json`.
- **duration** — "klasma … should add an extra beat", "hold an extra beat",
  dipli. **No sink exists.**
- **segmentation** — "it should be split into an oligon and ison (two neumes)".
  No sink existed; revision 2 fixed the extractor instead, which is the right
  answer, but nothing yet *detects* that a chanter note implies a re-split.
- **genus / fthora** — the red ajem "turns the scale into harmonic meaning the
  zo gets flattened to be only 6 moria from ke and 12 from ni".
  **No sink exists**; genus is one value per `hymns.json` row.
- **orthographic-only** — psifiston, omalon, vareia, antikenoma. These confirm
  the machine was *right* and are as valuable as the corrections, because they
  are the negative examples. No sink exists.

## How this differs from gold #1

`datasets/eothinon-11-workdir` + `datasets/exports/eothinon-11-plagal4` is the
English Eleventh Matinal Doxastikon (Karam, EZ fonts), 270 glyphs / 327 slots
over 4:24. Its ground truth is `note_times.json` (259 onsets),
`slot_claims.json`, the chanter's pitch-ghost taxonomy and melisma spellings —
but only 3 edited slots and **zero pins**.

So the two are complementary and must not be pooled naively:

|  | eothinon-11 | grave-orthros-t03 |
|---|---|---|
| script / font | English, Karam EZ | Greek, Ioannou vector |
| length | 4:24 | 0:53 |
| units | 270 glyphs / 327 slots | 76 units |
| timing gold | onsets + slot claims, 0 pins | **76 pins, every unit** |
| notation gold | melisma spellings, analytical interpretations | **25 neume-level corrections** |
| pitch gold | chanter pitch-ghost taxonomy | none |

eothinon-11 licenses claims about melisma spelling, analytical notation and
pitch-detector artifacts. t03 licenses claims about per-unit onset accuracy and
compound-neume decoding. Neither licenses a claim about the other's territory,
and with two pieces total, any metric reported without saying which piece it
came from is meaningless.

## Regenerating

`ingest_pins.py --exports-dir <dir> --piece grave-orthros-t03` writes the scored
row into `/mnt/data/chant-corpus/verification_ledger.json` and stages
`chanter_pins.json` / `chanter_flags.json` into the melos dir. Point it at a
directory holding this gold (re-indexed), not at the raw 75-unit export.

Note that `hymn_align.py` still does not read the staged pins — 76 verified
anchors remain invisible to the aligner. See
`docs/plans/CHANT-MODEL-ACCURACY.md`.
