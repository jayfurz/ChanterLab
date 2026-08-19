# Chant model accuracy: decoding, correction sinks, and honest alignment

Working plan, 2026-08-18. Scope: `tools/corpus/` (hymn_align, prep_hymn_annotator,
ingest_pins, align_eval, reseed_round), `tools/mcr/`, and the chanter annotator
(`tools/chant-reel/annotator/`). Every number below was read off the code or the
data in this checkout / `/mnt/data/chant-corpus` on 2026-08-18; ablation figures
that came from experiments rather than from a file on disk are labelled as such
and are re-derived by EVAL-01 before anything is built on them.

---

## 0. Status addendum, 2026-08-18 19:20 — part of DECODE-01 has landed

This plan was drafted against a 75-unit t03. While it was being written the
chanter corrected the segmentation of unit 6, and the two decoder defects that
correction exposed were fixed the same evening. The verification pass caught up
with those changes, so **sections 1–3 already quote revision 2**; this section
records what landed and why it matters to the sequencing, rather than
correcting the body.

Landed (all were proposed below and are now done):

1. **`APLI` no longer contains cluster 36** — row 3 of the section-3 table. It
   is the omalon, not an apli, so it added a phantom beat to 261 units
   corpus-wide. Cluster 10 remains unwired pending DUR-01.
2. **Structural split** — row 6 of the section-3 table, and the group-splitting
   half of DECODE-01. `_note_subgroups()` in `hymn_align.py` splits base
   candidates that never *directly* x-overlap, so a wide orthographic span can
   no longer bridge two notes into one unit. Candidates that do overlap stay
   fused, preserving ison-over-petasti and petasti+oligon. Span marks rescued,
   by bridge frequency: the **eteron** (31, red, 324/325 — chanter-confirmed
   2026-08-18, *"another glyph that is sometimes two wide is the eteron"*), the
   **omalon** (36, 225/261), a wide eteron variant (74, 10/10, unconfirmed),
   85 tie/syndesmos, 25/30 di/trigorgon. All now in `atlas_chanter.json`,
   which takes the atlas to 52 classified clusters — DECODE-01 reads it. Corpus impact 609/108,348 groups (0.56%), +79 units over 169
   hymns, 58 hymns changed unit count. t03 is 76 units; re-index is old *g* →
   *g* for g ≤ 6, *g*+1 for g ≥ 7.
3. **`.bak` scoreboard inflation** — an EVAL-01 item. The two
   `melos_*.bak-20260818` dirs are renamed `_bak_*`; grave-orthros now reports
   its real 25 hymns, and the corpus 173.
4. **Gold seeding** — `prep_hymn_annotator.load_gold_seed()` ships
   `datasets/<piece>-gold/` into `annotator_data.seed`, and the annotator
   restores it when `data_rev` changes and no local edits match. Re-segmenting
   a piece now costs a re-index rather than the chanter's pins.

5. **DUR-01 has largely landed too** (2026-08-18 20:30), on two further chanter
   rulings: *"treat apli dipli and tripli … as duration markings as they should
   be. apli is one beat, dipli is two beats, tripli is 3"*, and *"rests should
   be units, they take up time … even if the chanter skips them … it is still
   what the music notation is saying one should do"*.
   - `beats_seq(units)` replaces six copies of the beat formula across
     `hymn_align`, `dtw_conf`, `hymn_to_workdir` and `prep_hymn_annotator`. It
     is a **sequence** pass because the gorgon family reaches into neighbours.
   - Gorgon family implemented from `Table-of-Byzantine-Notation-Symbols.pdf`:
     order *k* takes *k/(k+1)* of a beat off a window of *k+1* symbols starting
     one BEFORE the sign. All eight illustrated cases reproduce exactly,
     including the klasma variants 1½ ½ / 1⅓ ⅓ ⅓ / 1¼ ¼ ¼ ¼. Digorgon and
     trigorgon previously did **nothing at all** — clusters 25 and 30 were not
     in `RED_TIME`. Argon wired (adds a beat, removes ½ from the two before).
   - **Klasma detection was colour-blind in the wrong direction**: it looked at
     red glyphs only, so **2100 units carrying a black cluster-8 klasma added
     zero beats**, against 25 caught by the red path. Now colour-blind. This is
     what makes t03 gi12/gi13 come out at the chanter's 1½ / ½.
   - Dots counted: 980 units with one, 1092 with two, 7 with three.
   - **Rests are units** (12 across 11 hymns). They cannot claim a sung event,
     so `dtw()` filters them and folds their beats into the following note, so
     the duration prior still sees the true elapsed span.
   - Still open, deliberately not changed: `RED_TIME` counts red 22, 23 and 9
     as klasma-family, but the atlas calls 23 the Ga martyria LETTER and 22 an
     ison variant — 25 units, awaiting a chanter ruling rather than a silent
     subtraction.

Measured effect, and the reason EVAL-01 must come first:

| | r1 (fused) | r2 (split) | r3 (timing) |
|---|---|---|---|
| t03 median &#124;Δt&#124; vs pins | 4.10 s | 0.563 s | **0.514 s** |
| t03 pins within 0.35 s | 6 / 44 | 16 / 54 | **20 / 54** |
| t03 pins within 0.15 s | — | — | **20 / 54** |
| t03 coverage | 58.7 % | 71.1 % | 71.1 % |
| t03 movement agreement | 0.98 | 0.96 | 0.96 |
| t03 strict-on-pins, unassisted | — | 0.760 | 0.760 |
| corpus strict | 0.930 | 0.930 | 0.931 |
| corpus cents55 | 0.651 | 0.640 | 0.644 |
| corpus coverage | 66.8 % | 66.7 % | 66.8 % |

At r3 the matched pins are strictly **bimodal**: within-0.15 s and within-0.35 s
are the same 20 pins. Nothing lands in between. The residual error is not
diffuse imprecision, it is a path that has slipped a note and cannot re-sync —
which is the case for ALIGN-02's hard anchors, not for tuning the cost weights.

A sevenfold improvement in real onset accuracy moved the corpus scoreboard not
at all and moved the headline per-hymn metric *downward*. This is the plan's
central thesis demonstrated on a live change rather than argued: until EVAL-01
lands, the project has no instrument that can see its own progress except the
gold pins. Everything after section 1 stands as written.

The still-open half of DECODE-01 is the one that matters most — base election
is still `max(area)` rather than role-driven from `atlas_chanter.json`.

---

## 1. Where the pipeline stands today

**Corpus scoreboard** (`/mnt/data/chant-corpus/scoreboard_round2_20260818.txt`,
produced by `align_eval.py`):

```
mode       hymns  pairs    strict   cents55 coverage
grave-orthros    26   1122     0.923     0.686    58.2%
...
OVERALL      174  10570     0.930     0.651    66.8%
```

**This board is stale and is quoted only as the "before" text**: it predates the
second `.bak-` copy (see below) and it predates the 19:00 re-alignment of
`melos_t03_` against the corrected 76-unit stream, so that hymn's contribution
no longer matches. Gate A re-runs the board from a pinned revision and this
quotation is replaced by that run.

`strict` is `summary.json:movement_agreement`, computed at
`hymn_align.py:618-626` (the pair loop; the test `deg_obs[k] - deg_obs[k2] ==
exp` is at `:626`) and written into `summary.json` at `:664` — the aligner's own
quantization compared against the aligner's own expectation, where `exp` comes
from `unit_deg` (`unitdeg_<hymn>.json`), a file `cmd_legend` itself wrote by
cumulating `iv_of`. It is a DTW residual, not an accuracy. `cents55` is the
honest metric (`|obs_cents - exp_cents| <= 55`) and it averages 0.651 overall,
0.683 across the 25 real grave-orthros hymns, against a `movement_agreement`
mean of 0.922 on the same 25.

The row count in that board is inflated: `align_eval.py:17` globs
`melos_*/summary.json` with no `.bak` filter, and two backup copies
(`melos_t01_.bak-20260818`, `melos_t03_.bak-20260818`) were being counted as
real hymns — which is why its grave-orthros row says 26 against 25 real hymns.
**Fixed 2026-08-18 19:05** by renaming both to `_bak_*`, outside the glob; the
glob now returns 25 under `workdirs/grave-orthros` and 173 across `workdirs/`.
The filter itself is still owed by EVAL-01, since a rename is a convention and
not an enforcement. The current board is
`/mnt/data/chant-corpus/scoreboard_postsplit_20260818.txt`:

```
mode       hymns  pairs    strict   cents55 coverage
grave-orthros    25   1084     0.933     0.692    59.6%
...
OVERALL      173  10564     0.930     0.640    66.7%
```

**Gold hymn t03** (`workdirs/grave-orthros/melos_t03_/summary.json`, re-aligned
2026-08-18 19:00 against the corrected 76-unit stream — see "revision 2" in
`datasets/grave-orthros-t03-gold/README.md`):

```
n_units 76  n_events 85  n_matched 54  coverage_units_pct 71.1
movement_agreement 0.96  movement_agreement_cents 0.91
ni_cents_rel55 1445.5  ni_hz 126.8
```

(The pre-split r1 run of the same hymn read `n_units 75  n_matched 44
coverage 58.7  movement_agreement 0.98`; it is preserved in
`datasets/grave-orthros-t03-gold/baseline.json` under `vs_gold_r1_75unit` and is
the state both this document's first draft and the ledger's 18:18 row were
written against.)

**Verification ledger** (`/mnt/data/chant-corpus/verification_ledger.json`,
re-ingested 2026-08-18 19:00 against the re-indexed 76-pin gold, superseding the
18:18 row; `melos_t03_/chanter_pins.json` holds 76 pins):

```
n_pins 76   n_flags 25   n_machine_checked 54
median_dt 0.563 s   p90_dt 4.68 s   n_confirm 16   n_contradict 38
strict_pins 0.787 over 75 pin pairs
16 legend_disagreements
machine_agreement 0.96   machine_coverage_pct 71.1
```

So the one hymn with external ground truth scores 0.96 on the headline metric
while only 16 of its 54 machine-matched units land inside the 0.35 s tolerance
(`TOL`, `ingest_pins.py:38`) — 16 of all 76 pins, i.e. 0.21. `median_dt` is not a
median: `ingest_pins.py:161-162` takes `dts[len(dts)//2]`, the upper median, so
the true median over the same 54 values is **0.551 s**, not 0.563 s.
`machine_agreement` in the ledger row is `p.get('movement_agreement')` copied
straight from the scoreboard (`ingest_pins.py:167`) — an audio-vs-audio quantity
sitting in a row a reader takes as decode accuracy.

**Decoder state**, measured by running `hymn_align.load_units_h` over all 25
grave-orthros hymns (**1,883 units**) at the pinned decoder revision
`tools/corpus/hymn_align.py` sha256 `284e595988627d9e…`, 680 lines. That
revision already contains two fixes that landed *before* Gate A — `APLI` is now
empty (cluster 36 is the omalon, not an apli) and `_note_subgroups`
(`hymn_align.py:55`) splits base candidates that only a wide span mark had
fused. Their effect is therefore inside the baseline below and must **not** be
attributed to DECODE-01 or DUR-01 later:

| fact | value |
|---|---|
| units whose elected base is cluster 7 (psifiston, atlas `interval: null`, "qualitative") | 133 |
| units whose elected base is 19 / 33 / 57 / 28 (antikenoma, tempo signs, ypsili) | 5 / 6 / 2 / 1 |
| units with the `klasma` flag set | 5 |
| units carrying an `8ab`/`8be` **mark token** in the key (atlas cluster 8 = "klasma ... BLACK duration mark (+1 beat)") | 199 |
| units with the `apli` flag set (`APLI = set()`, `hymn_align.py:42` — cluster 36 was removed from it pre-Gate-A) | 0 |
| units carrying `10ab`/`10be` mark tokens (atlas cluster 10 = "apli/dipli dots") | 37 |
| units carrying both an 8-token and a 10-token | 0 (so the duration-mark union is exactly 199 + 37 = **236**) |
| units with `gorgon` | 113 |
| distinct unit keys | 52 |
| keys with a legend value in `legend_global.json` | 36 (42 keys have support) |
| units whose exact key misses the legend (`iv_of`, `hymn_align.py:213-219`) | 77 |
| of those, units whose bare base is also absent, i.e. **silent 0** | 23 |
| of those, units that return the bare base and **silently discard** their marks | 54 |

**The free checksum nobody spends.** `load_units` already records martyria
degrees (`hymn_align.py:139-143`). On t03 the two martyria anchors are the units
whose base key is `4|8ab` at the two cadences: the first carries `mart_deg == 1`
(Pa), the second `mart_deg == 3` (Ga) — at the current segmentation they are
units 24 and 50 — so the book requires net **+2** across the units between them.
The current legend decodes **-3**. Applying only three chanter rulings
(`7|6ab` -> +1, `7|16ab+6ab` -> +3, `3|16ab+8be` -> +3) gives exactly **+2**, and
whole-hymn cumulative drift moves from **-13** to **0**. `mart_deg` is
currently used only as a soft DTW cost (`W_MART = 1.6`, `hymn_align.py:211`,
`:255`). Everywhere in this plan a martyria segment is named by its **anchor
ordinal** ("between martyria #1 and martyria #2") or by unit `uid`, never by a
`gi`, because `gi` moves whenever segmentation does.

**Dead sinks.** `ingest_pins.py:15-17` states the staged pins are copied "so the
aligner can consume them as hard anchors"; `grep -n chanter_pins hymn_align.py`
returns nothing. `chanter_flags.json` likewise has no reader anywhere in
`tools/`. The only live correction sink is `iv_ovr_<hymn>.json`, and
`hymn_align.py:505-515` rewrites each overridden unit's key to a private
`#ovr{j}`, deliberately preventing the ruling from generalizing to identical
figures. Both `ingest_pins.py:177` and `serve.py:39,125` default `--exports-dir`
to `tools/chant-reel/annotator/exports`, which is not where anything is written;
the live server process is running with
`--exports-dir .../datasets/exports` passed explicitly.

---

## 2. The two gold datasets and the evaluation protocol

### Gold #1 — eothinon-11 (`datasets/eothinon-11-workdir/`)

270 glyphs in `mcr_interpretation.json` expanding to 327 slots (`slots.json`
`t`/`gi`/`sub`, all length 327), `slot_claims.json` length 327 with 255 non-null
claims into the **cleaned** event stream, 18 line groups, plus `barlines.json`,
`expected_degrees.json`, `ison_timeline.json`, `ladder_track.json`.
`note_align6.py` (the v2 movement-space aligner) lives here.

Licenses: per-slot claim supervision for the arc/MCR model lane, and a
byte-identity regression target for any refactor of that aligner.
Current numbers (`models/report_aligner.json`): `cv_glyph_acc` 0.7608,
`cv_slot_acc` 0.7137, folds `[0.842, 0.822, 0.780, 0.465, 0.841, 0.818]`
(fold sd 0.135 → SE ≈ 0.055 over 6 folds), gate 0.7 = coverage 0.655 / accuracy
0.904 where the coverage denominator is gold claims (255), not score slots
(327). `models/report_gbm.json`: interval-rule baseline 0.4902 beats GBM flat
glyph 0.4667 and (`report_cnn.json`) CNN glyph 0.4588. **Each head must be
quoted against its own majority baseline, and today `report_gbm.json` records a
majority baseline only for the glyph task** (0.3451). Computed from
`events.jsonl` over the same 255 structural events, the majority class is 0.447
for `y_beats` (`'0.5'`, 114/255) and 0.663 for `y_comp` (`'single'`, 169/255).
So: the beats head clears its majority baseline (0.569 vs 0.447); the
compound-position head does **not** clear its own (0.690 vs 0.663, inside one SE
— SE ≈ 0.029 at n = 255) and is retained only as a feature, not as a headline
result. GOLD-01 writes both baselines into `report_gbm.json`.

### Gold #2 — grave-orthros-t03 (`datasets/grave-orthros-t03-gold/`)

The chanter's raw browser export stays at `datasets/exports/grave-orthros-t03/`
in its original 75-unit indexing (75 pins in `pins.json`, one per unit,
`[gi, time]`, same timebase as `melos_t03_/voice_notes.json`; 24 flags in
`mcr_flags.json`; plus `slots_corrected.json`, `pitch_ghosts.json`,
`analytical_notes.json` and a `history/` of session snapshots). The **curated
gold is `datasets/grave-orthros-t03-gold/`, revision 2**: the same session
re-indexed onto the corrected 76-unit stream (`pins.json` 76 pins covering every
unit, `chanter_notes.json` 25 notes of which 6 are empty and 9 are already
transcribed into `iv_ovr_t03_.json`, `score_units.json` as the frozen unit
stream the indices refer to, `baseline.json` with the freeze-time metrics and
the audio checksum). All pin figures in this plan are against revision 2; where
an r1 figure is quoted it is labelled as such.

Licenses: **onset timing** truth for the whole hymn, **strict-on-adjacent-pins**
interval truth, and 19 typed notation statements (25 flags less 6 empty). It does not yet license
model training: `find workdirs/grave-orthros -maxdepth 2 -name arc -type d`
returns nothing (arc dirs exist only under other workdirs, e.g.
`workdirs/mode1/melos_t04_/arc`), and no code converts `[gi, time]` pins into
`slot_claims.json` indices over `mcrlib.clean_stream`.

### Protocol (two pieces only)

1. **Piece is the only honest fold.** Gold #2 is never in a training set, and
   for gold evaluation **every chanter-derived overlay whose provenance is this
   piece is disabled**: `unitdeg_chanter_t03_.json`, `iv_ovr_t03_.json`,
   `chanter_legend.json` entries provenanced to t03, `beats_ovr_t03_.json` and
   `fthora_t03_.json`. Disabling only the `unitdeg` overlay is not enough,
   because the interval sink is what the strict metric reads (see 2).
2. **Primary metrics, both external:** onset error against the gold `pins.json`
   and strict-on-**adjacent**-pin pairs (non-adjacent pairs launder legend error
   through the interval sum).
   - **Onset denominator is fixed: all 76 pins.** An unmatched pin is a miss and
     counts against `frac ≤ 0.15 s` / `frac ≤ 0.30 s`. The median is necessarily
     over the matched subset and is always printed as "median over matched,
     n = …" next to the matched-pin coverage, so the median can never be bought
     by dropping hard units out of the match set.
   - Today's baseline against the shipped `melos_t03_/aligned.json`: **54 of 76
     pins matched (0.711); median |dt| over matched 0.551 s; 16 pins within
     0.30 s = 0.211 over all 76** (0.296 over the matched subset — the two
     denominators differ by 40 % and must never be mixed). r1, pre-split:
     44 matched, upper-median 4.1 s, 6 within 0.35 s = 0.08 over 75 pins.
   - **Strict-on-pins is reported twice, assisted and unassisted**, exactly as
     §2.3 does for anchored vs held-out pins, and the **unassisted number is the
     primary one**. As shipped it is *not* external: `ingest_pins.py:118-124`
     builds the expected delta as `iv_u = lambda j: ovr[j] if j in ovr else …`
     where `ovr` is `iv_ovr_t03_.json`, the chanter's own hand-transcribed
     interval rulings, so the metric scores his answers as if they were model
     predictions — and CORR-02 compiles every confirmed correction into exactly
     that file plus `chanter_legend.json`, which would make the number rise
     mechanically with each correction ingested and no model improvement at all.
     **Measured 2026-08-18:** assisted 0.787, unassisted (legend only) 0.760 —
     the chanter's nine rulings are worth 2 of 75 pairs today. Small now, but it
     is the slope that matters: CORR-02 grows `ovr` with every correction, so
     the assisted number drifts upward on its own. Recorded in
     `datasets/grave-orthros-t03-gold/baseline.json` as
     `strict_on_pins_assisted` / `strict_on_pins_unassisted`; the unassisted
     figure is the one to track.
3. **Pin holdout.** Once ALIGN-02 consumes pins as hard anchors, every third pin
   (indices 2, 5, 8, … 74; 25 of 76) is withheld from the aligner and reported
   separately. Anchored and held-out numbers are always printed together.
4. **Secondary, direction only:** eothinon line-GroupKFold reported as mean ±
   fold sd with the fold vector, plus a contiguous-block holdout variant that
   masks the held-out region out of `decode_em`'s anchor set
   (`train_aligner.py:482` currently decodes the whole piece with train-line
   anchors before scoring test lines).
5. **Corpus-wide, label-free:** total martyria checksum residual (CHECK-01).
   This is the day-to-day metric because it needs no annotation and covers all
   173 alignable hymns.
6. **Budget.** Gold #2 is measured **once per accepted change**, not per
   candidate, and the touch count is appended to a changelog in this document's
   sibling `CHANT-MODEL-ACCURACY-LOG.md`. That count is the
   multiple-comparisons budget.
7. **Coverage is reported against three denominators** (gold claims, score
   slots S, cleaned events K) and headlined as `coverage_slots`; alignment
   coverage is reported alongside its ceiling `min(1, E/U)` — 10 of the 25
   grave-orthros hymns have fewer detected events than units and are
   detector-bound, not aligner-bound.
8. **Assisted hymns** (any hymn with `unitdeg_chanter_*`, `iv_ovr_*` or pins)
   are printed in a separate scoreboard block and excluded from OVERALL.

---

## 3. What the chanter's notes proved

25 flags at gold revision 2; 19 carry text, 6 are empty. The 19 are not 19
unrelated corrections — they are six repeating machine defects, of which exactly
one (a per-instance interval integer) has any sink today. Machine values below
are from `load_units_h('t03_')` + `iv_of` under the current legend, at the
pinned revision recorded in §1.

**Indexing.** Every `gi` below is a **revision-2 (76-unit) index**, re-derived
after the note-split landed; the chanter's original export indices were one
lower for every unit from old-gi 6 on (`old ≥ 6 → new = old + 1`, and new gi 7
is the ison that the split created). `datasets/grave-orthros-t03-gold/chanter_notes.json`
carries both (`gi`, `gi_export_75unit`). Two of the six defects below —
**#3 (APLI) and #6 (the split)** — were fixed in the tree before Gate A; they are
kept in the table because the *class* of defect is what DECODE-01/DUR-01
generalize, but their t03 instances are already green and must not be counted as
a DECODE-01/DUR-01 win.

| # | Defect | Chanter's own words (gi) | Machine now | Units affected |
|---|---|---|---|---|
| 1 | **Base elected by bbox area, so the qualitative mark becomes the note.** `hymn_align.py:159` takes `max(area)` over black glyphs not in `MARK_ONLY = {36,13,27,10,16}`; cluster 7 (psifiston) is not in that set and outweighs the oligon it decorates. | gi10 "oligon with psifiston underneath. Psifiston is just orthographic and qualitative. Oligon should be +1"; gi71 same; gi48 "Oligon with vareia underneath ... Oligon makes it +1"; gi63 "Oligon with kentima on top like this is +3" | gi10/22/42/48/71 key `7\|6ab` → **+0**; gi39/63 key `7\|16ab+6ab` → **+0** | 7 in t03, **133 in the corpus** |
| 2 | **Duration marks read off colour, not role.** `klasma = any(red cluster != 11)` (`hymn_align.py:170-171`), but in this book klasma prints BLACK as cluster 8 (atlas: "klasma ... BLACK duration mark (+1 beat) ... appears in keys as 8ab/8be"). | gi12 "extra beat due to the klasma"; gi19 "2 beats"; gi45 "Should add an extra beat"; gi50 "Two beats"; gi61 "Hold an extra beat"; gi66 "Should be plus one beat" | every one of gi12/14/19/45/50/61/66 reports `klasma False`, `beats 1.0` | 7 in t03, **199 in the corpus** (mark-token match on `8ab`/`8be`) vs 5 flagged |
| 3 | **APLI set inverted — FIXED pre-Gate-A.** `APLI` was `{36}`; cluster 36 has no atlas entry at all, and the chanter calls it omalon. It is now `set()`, so the phantom beat is gone. The other half stands: the 37 corpus units with cluster-10 dots still add nothing. | gi6 "a ομαλον below it ... is qualitatively/orthographic only"; gi75 "oligon with a dipli. (Dipli only usually at the end of phrases)" | gi6 `apli False`, 1.0 beats (was 2.0); gi75 `6\|10be+10be` still **1.0 beats** at the hymn's final cadence | 0 phantom (was 6) + 37 still uncounted |
| 4 | **Key string mixes pitch and time axes, so EM estimates the duration variant separately — and got it wrong.** `3\|16ab+8be` is a pitch mark plus a time mark: it is *present* in `legend_global.json` with the value **1**, learned from its own 8 votes, while `3\|16ab` = 3 and `CHANTER_LOCK['3\|16ab'] = 3`. This is a wrong exact-key value, not a missing key — no fallback warning can ever surface it. | gi14 "petasti compound with a kentima meaning go up three" | **+1** (should be +3) | general: 77 corpus units miss their exact key — 23 to a silent 0, 54 returning the bare base with their marks discarded |
| 5 | **No mid-hymn genus.** Genus is one scalar per `hymns.json` row (all 25 grave-orthros rows `diatonic`). A red glyph sharing a group with a base note matches neither the gorgon test nor `RED_TIME`, so it is dropped with no record. | gi14 "The red ajem on top turns the scale into harmonic meaning the zo gets flattened to be only 6 moria from ke and 12 from ni" | Zo stays at 64 moria for the remaining 62 of 76 units | whole tail of every hymn with a **genus-only** fthora; see FTH-01 for the pivoting kind |
| 6 | **No structural split — FIXED pre-Gate-A for the x-disjoint case.** `_note_subgroups` (`hymn_align.py:55`) now separates base candidates that never directly x-overlap, so t03 gi6/gi7 are two units. What remains unrepresentable is a *sub-note* split inside one unit: `iv_ovr` holds one integer per unit and `prep_hymn_annotator.py:310` hardcodes `sub_notes: 1`. | gi6 "This is two different notes with a ομαλον below it which ties the two together ... The first note is the oligon (up one) then the ison (stay the same)" | two units, `6\|36be` (+1) and `5\|` (0) — correct; but `sub_notes` is still 1 everywhere | t03 has 76 sung notes, and the stream now has 76 units |

Category tally over the 19 described notes: **interval 7** (gi6, 7, 10, 14, 48,
63, 71) — sink exists but per-instance only; **duration 9** (gi12, 13, 14, 19,
45, 50, 61, 66, 75) — no sink; **genus 1** (gi14) — no sink; **split 1** (gi6) —
decoder fixed, sub-note representation still missing; **orthographic
confirmation 5** (gi0, 1, 2, 3 and the interval half of gi19 "interval is
correct") — machine already agrees (`6|`=+1, `3|`=+1, `4|`=-1, `5|`=0),
discarded as no-ops; **lyric 1** (gi0 "The word is Κα (drop cap Κ and vowel
α)"); **UI 1** (gi50 "Just use the solfege syllables"). gi14 alone is interval +
duration + genus and the sink held only the interval.

The book independently confirms that the chanter is right and the machine is
wrong, without involving his testimony:

- **The book.** The martyria checksum above: -3 decoded where the printed
  cadences require +2, and exactly +2 under his three rulings.

The audio is **consistent with** those corrections but is not an independent
confirmation, and must not be quoted as one: the ledger's pin-derived `sung`
column is computed from the same alignment under test, and 6 of its 16 rows are
musically implausible (`gi 16 sung −5`, `17 +4`, `18 −4`, `19 +4`, `55 −5`,
`56 +4` — fifths and fourths where the book prints steps), i.e. a ~38 % gross
error rate on the column. The rows that do agree
(`{gi 22, key 7|6ab, legend 0, sung 1}`, same at gi42/48/71, and
`{gi 39, key 7|16ab+6ab, legend 0, sung 3}`, same at gi63) are corroboration of
the right sign, nothing more. For real independence, recompute `sung` on a
theory ladder anchored by martyria only, from a run with **all** chanter
overrides disabled (§2.1), and report the agreement rate over **all 75 pin
pairs**, not six selected rows.

The six empty flags (gi22, 24, 31, 36, 39, 42) mean "marked, not yet described"
— `index.html:1032` writes `flags[gi] = note.value || ''` the moment the button
is pressed. Their keys are all members of already-adjudicated classes
(`7|6ab`, `7|16ab+6ab`, `4|8ab`, `3|8be`, `6|8ab`). That is strong inference,
not the chanter's word; it must never be counted as agreement and must never be
synthesized into note text.

Terminology to resolve **with the chanter, not in code**: gi61 calls cluster 8
"petasti" where gi12/45/66 call it klasma (stated effect, +1 beat, is
consistent); gi19 calls cluster 22 "kentimata" where the atlas calls it an
ison-variant — **this one is interval-bearing, not cosmetic**: as an ison-variant
the figure is one slot at +0 (which is what the chanter's stated interval at
gi19 implies, and what `CHANTER_LOCK['3|22ab'] = 0` encodes), while as kentimata
(cluster 17, atlas `interval: 1`, "above an oligon the FIGURE is two notes
+1 +1") it would be a +1 mark forming a two-note figure, net +2. Cluster 22
therefore joins cluster 7 on the split-cluster / colour-context review queue
(the atlas entry itself says "extraction has 22 in the RED klasma-family set;
sheet had no color. RE-REVIEW with color context sheet"); until that review, the
chanter's stated **+0 binds the t03 instances only**, not the cluster.
gi10/71 call cluster 7 "psifiston" while gi48/63 call the same group "vareia"
with no cluster 12 present — cluster 7 may be a mixed cluster, which matters
because `atlas.figures.rest` defines vareia+apli as a REST.

---

## 4. Workstreams

Effort: S ≈ ≤1 day, M ≈ 2-4 days, L ≈ 1-2 weeks.

### EVAL-01 — Honest measurement before any change
**Effort M. Depends on: nothing.**

*Problem.* Every reported number is the model grading itself (§1). The
`--exports-dir` defaults in `ingest_pins.py:177` and `serve.py:39,125` point at
a directory nothing writes to, so a bare invocation is a silent no-op that exits
0 (`ingest_pins.py:206-208`). `align_eval.py:17` counts `.bak-` dirs.
`ingest_pins.py:161-162` reports `dts[len(dts)//2]` and `dts[int(len*0.9)]` as
"median" and "p90" — the upper median and a truncated-index p90, which is why
the ledger says 0.563 s where the median is 0.551 s.

*Change.*
1. `tools/corpus/paths.py` exporting `REPO`, `EXPORTS_DIR = <repo>/datasets/exports`,
   `CORPUS`, `GLYPHS`; default both `serve.py` and `ingest_pins.py` to it, keep
   `--exports-dir` as override, and exit non-zero naming both candidate paths
   when the chosen dir has no piece subdirs but the other does.
2. Pin sanity gate in `ingest_piece`: reject a `pins.json` containing a run of
   ≥3 identical consecutive deltas (UI drag artifacts); refuse to replace a
   staged pin file with a smaller one without `--force`; stamp the source
   export's `history/` timestamp into the ledger row.
3. New `tools/corpus/gold_eval.py`: for every hymn with
   `datasets/exports/<piece>/pins.json`, load `melos_<h>/aligned.json` and report
   median |dt|, frac ≤ 0.15 s, frac ≤ 0.30 s, matched coverage, `E/U` and the
   ceiling `min(1, E/U)`, written into `summary.json` under a `gold` key.
   Support `--holdout-every 3`.
4. `align_eval.py`: skip dirs containing `.bak-` or ending `_pre_reseed` (lift
   `reseed_round.py`'s existing filter into a shared helper); rename the
   `strict` column header to `dtw_residual (diagnostic)`; promote
   `movement_agreement_cents`; add the gold columns; print assisted hymns in a
   separate block excluded from OVERALL. Rename the ledger's `machine_agreement`
   field to `movement_agreement_audio`.

*Files.* `tools/corpus/paths.py` (new), `tools/corpus/gold_eval.py` (new),
`ingest_pins.py`, `align_eval.py`, `reseed_round.py`,
`tools/chant-reel/annotator/serve.py`, `verification_ledger.json`.

*Acceptance.* `gold_eval.py grave-orthros` against the shipped `aligned.json`
reproduces **median |dt| 0.551 s over 54 matched pins, 16 of 76 pins within
0.30 s (0.211)** — and explains the ledger's 0.563 s as `ingest_pins`' upper-
median convention, or, preferably, `ingest_pins.py:161-162` is changed to a real
median and the ledger re-ingested so the two agree exactly. Either way the two
numbers must be reconciled in writing, not left to differ. Scoreboard drops the
two `.bak-` duplicates and shows grave-orthros with 25 hymns (27 summaries on
disk), t01/t03 in an `assisted` block. `ingest_pins.py` with no arguments finds
the gold export (76 pins, 25 flags at revision 2). A synthetic pins file with
six 0.02 s-spaced entries is rejected non-zero.

---

### DECODE-01 — Atlas-driven role table replaces area heuristics
**Effort L. Depends on: EVAL-01.**

*Problem.* Base election by area (133 base=7 units, plus 14 phantom notes on
19/33/57/28 — including all 6 base-33 units, which are the argosyntoma tempo
sign at a hymn heading and are the only reason a scale sign ever lands in a
"based" group, see FTH-01); transitive x-overlap tested against *any* group
member, so a wide orthographic glyph bridges non-touching neighbours (the t03
gi6 `5|36be+6be` case, already fixed by `_note_subgroups` pre-Gate-A for the
x-disjoint variant);
`MARTYRIA_DEG` read only when `base is None` (`:139-143`), so a Ga letter that
overlaps a neume is diverted into the klasma branch and its anchor is lost;
baseless black-mark groups dropped with no warning; `tools/mcr/em_legend.py`
duplicates the grouper.

*Change.* New `tools/mcr/unitlib.py`:
- `load_roles(atlas_path) -> {cluster: role}` with role in
  `{note, interval_mark, duration_mark, orthographic, martyria, fthora, tempo, silent}`,
  derived from `atlas_chanter.json` (`clusters[].interval` plus name/note
  keywords). The atlas covers **49 of 94** clusters and clusters 9, 26, 27, 29,
  36 have no entry or a `null` body, so `load_roles` takes a second explicit
  `unreviewed_overrides` map and, critically, **defaults an unreviewed black
  cluster to `note` rather than dropping it**, emitting it into
  `workdirs/<wd>/unknown_clusters.json` for chanter review. No group is ever
  silently discarded.
- `build_units(glyph_recs, roles)`: base = the glyph whose role is `note`, ties
  by area; `interval_mark`/`duration_mark`/`orthographic`/`tempo` can never be
  base. Transitive closure runs only over note/interval/duration glyphs;
  orthographic spans (36, and 7 where it prints wide) attach afterwards by
  x-centre containment and can never bridge.
- **Note-role is not a licence to split.** Several chanter-verified figures are
  ONE note containing two or more note-role glyphs: `atlas.figures.ison_over_petasti`
  ("bar (ison) printed over a petasti = ONE note, interval 0: the petasti is
  silent/qualitative"), cluster 13 ("the figure key `3|13ab` = petasti+oligon =
  +2 (locked)"), cluster 21 ("carrier oligon ... used orthographically — like a
  table, but has no value") and cluster 22 ("the oligon is ignored here and only
  used for orthographic purposes"). `CHANTER_LOCK` already carries them as
  single-unit keys: `3|22ab` = 0, `3|13ab` = 2, `22|17be+21be` = 1,
  `7|17ab+21ab+22ab` = 1, `47|17be+21be` = −1. t03 unit 19 is exactly one of
  these — clusters 3 (petasti) + 22 (ison) + 8 (klasma), key `3|22ab+8be`, one
  unit, +0, which is the reading the chanter confirms at gi19 — and a
  split-on-two-note-glyphs rule shreds it. So: consult a **figure table**
  (seeded from `atlas.figures` and the existing `CHANTER_LOCK` compound keys)
  *before* splitting, and give clusters 13, 21 and 22 a `carrier` /
  `silent-in-compound` role rather than `note`. Split only when **no known
  figure matches AND the two note glyphs are vertically disjoint neumes** (the
  gi6 oligon+ison case, which `_note_subgroups` already handles by x-disjointness);
  every other multi-note group is **reported, not split**. A unit wider than 1.5× the line's median glyph
  advance is **flagged in a report, not split** (no evidence yet that the cap is
  the right threshold; revisit once the report is read).
- Martyria hits collected from **every** group, attached to the containing unit
  or, if baseless, the previous one. Cluster 23 can never set klasma.
- Leftover black-mark-only groups swept onto the nearest same-line note group by
  x-centre (`em_legend.py:92-100` already does this for red), logged.
- `TWO_SUB` multi-note bases (atlas cluster 18 "yporrhoe (variant) — TWO notes
  -1 -1") emit N slots.
- Every unit gets `uid = f'{page}:{line}:{round(base.x0)}'` alongside the
  positional `gi`.

`hymn_align.load_units` becomes a thin caller. `em_legend.py` calls the same
function **parameterised by its own role table** — it runs on
`score_vec.json` in a different cluster numbering (its comments read
`4=ison 8=oligon 12=RED gorgon 27=apli 21=yporrhoe`), so the two lanes share
code and never share a global; add an `atlas_version` field to `score_vec.json`
and `page*.json` and assert it at load. Identical unit streams across the two
lanes are **not** an acceptance criterion — they read different books.

*Files.* `tools/mcr/unitlib.py` (new), `hymn_align.py:24-110`,
`tools/mcr/em_legend.py:29-100`, `atlas_chanter.json` (roles block).

*Acceptance.* On t03: the five `7|6ab` units and the two `7|16ab+6ab` units
elect base 6; zero units with base in {7, 19, 28, 33, 57}. The t03 unit count
stays at **76** (the gi6 split already landed pre-Gate-A; DECODE-01 must not
change the count again). **The martyria invariant is stated index-free**: the
two anchors are still the two units whose base key is `4|8ab` at the two
cadences, carrying `mart_deg` 1 and 3 respectively, and their `uid` is
unchanged — never "`units[23]`/`units[49]`", which is a stale numbering, and
never a `gi`, which moves with segmentation. If a criterion can only be made
green by suppressing a resegmentation, it is not a gate.
Corpus-wide: zero dropped orphan black-mark groups (count logged), every cluster
seen has a role or appears in `unknown_clusters.json`, and a pytest golden pins
the full t03 key stream and the corpus base histogram.

---

### KEY-01 — Axis-partitioned keys, compositional lookup, per-key chanter legend
**Effort L. Depends on: DECODE-01.**

*Problem.* One key string carries two orthogonal axes, so every duration variant
multiplies the key space and gets its own thin, independent estimate:
`legend_global.json` has `3|16ab` = 3 (locked) but `3|16ab+8be` = **1**, learned
from its own 8 votes. 77 units miss their exact key, in **two distinct failure
modes that must not be conflated**:
- **silent 0** — 23 units whose bare base is *also* absent from the legend, so
  `iv_of` returns the literal 0 default: `33|` ×6 (the argosyntoma **tempo
  sign**, which should carry no slot at all), the base-7 compounds
  `7|16ab+6ab+8ab` ×4, `7|6ab+8ab` ×4, `7|28ab+6ab` ×1, `19|10be+6ab` ×3,
  `19|10be+4ab` ×1, `19|6ab` ×1, `57|` ×2, `28|6be` ×1. Note `18|` (yporrhoe,
  atlas: "TWO notes −1 −1", so net −2) is no longer in this bucket but is worse:
  it now holds a *value* of 0 in `legend_global.json` on only 4 votes.
- **silent mark-discard** — 54 units that return the bare base's interval and
  quietly drop their marks: `20|8ab` ×13, `5|10be+10be` ×6, `3|28ab` ×6 (the
  ypsili's jump discarded — per the atlas petasti+ypsili is +4 in total),
  `6|36be` ×5, `4|10be` ×5, `4|10be+10be` ×4, `3|4ab+8be` ×4, `4|17be+6be` ×4 …
  No fallback-logging rule catches these, because the lookup "succeeds".

The whole census is re-derived after DECODE-01, since regrouping changes which
keys exist. `CHANTER_LOCK` (`hymn_align.py:358-372`) is chanter data living in
Python source. `iv_ovr` is applied as `#ovr{j}` so it cannot generalize.

*Change.*
1. `build_units` emits `key_iv` (base + sorted interval-bearing marks),
   `key_dur` (sorted duration marks) and `ortho` (recorded, never in a lookup).
   Keep the legacy `key` for one release as `key_iv + '#' + key_dur` for diffing.
2. Mark position becomes 2D: `{cluster}{ab|be}{L|C|R}` with `|dx| < 0.25*w_base`
   = C, because the atlas rule for cluster 16 is left/right, not above/below
   ("Below or to the RIGHT of an oligon -> +2. On top in the MIDDLE ... -> +3" —
   figure totals, not mark deltas; see item 3);
   for cluster 17 the dy distribution is unimodal against the fixed −1 pt
   threshold, so key it on dx alone.
3. `iv_of` → `compose_interval(legend, unit)`: exact `key_iv`; else
   `interval(base) + sum(MARK_IV[m])`; else 0 **with a warning**. Always sets
   `interval_source ∈ {lock, chanter, key, composed, fallback, override}`.

   **`MARK_IV` holds deltas relative to the base. The atlas's `interval`/note
   values on mark clusters are FIGURE TOTALS and must never be summed onto the
   base.** Atlas cluster 16 reads "Below or to the RIGHT of an oligon ->
   compound = +2 jump. On top in the MIDDLE of an oligon or petasti (without
   ypsili) -> +3 jump ... resolves t03 gi13 `3|16ab` = petasti+kentima = +3" —
   those are the totals for the whole figure, on a base (oligon/petasti) whose
   own interval is +1, which is exactly what `CHANTER_LOCK` records
   (`6|16be` = 2, `6|16ab` = 3, `3|16ab` = 3). Summing the atlas figures onto the
   base gives 1+2 = 3 and 1+3 = 4 and every kentima compound decodes one degree
   too high — which would break this plan's own targets: the two `7|16ab+6ab`
   units re-elected onto base 6 must read +3, and §1's checksum needs the ruling
   `7|16ab+6ab` → +3 for the martyria segment to sum to +2 (the additive reading
   gives +4 and the segment sums to +4). So:
   - **kentima (16)**: `+1` below/right, `+2` on-top-centre — i.e. oligon → +2/+3
     and petasti → +2/+3, matching `CHANTER_LOCK`.
   - **ypsili (28)** and the **ypsili+kentima compound (83)** are modelled as
     *figure-level totals that REPLACE the base interval* (+4 and +7
     respectively), not as summable marks. The atlas's "ypsili: +4 jump mark in
     combinations" means petasti+ypsili is +4, not 1+4 = 5; cluster 83's
     `interval: 7` ("up 7 (octave jump)") means the figure is an octave, not the
     ninth that 1+7 would give.
   - **kentimata (17)** `+1` as a mark, but note the atlas says "above an oligon
     the FIGURE is two notes (+1 +1)" — a two-slot figure, which is DECODE-01's
     figure table, not a `MARK_IV` sum.
   - durational / orthographic marks: 0.

   **CI assertion (blocking):** `compose_interval` must reproduce every existing
   `CHANTER_LOCK` compound value exactly — `6|16be` = 2, `6|16ab` = 3,
   `3|16ab` = 3, `3|13ab` = 2, `20|41be` = −3, `47|17be+21be` = −1,
   `22|17be+21be` = 1. Any seeding of `MARK_IV` that fails this assertion is
   wrong by construction.
4. `CHANTER_LOCK` moves to `workdirs/<wd>/chanter_legend.json`
   `{key_iv: {interval, provenance, hymn, uid, confirmations, scope}}`, merged
   after EM and immutable to EM. This is the per-KEY chanter sink: one ruling on
   `6|7be` binds every instance. **Key scope is the default only for
   context-free figures.** Clusters 20/41 default to *instance* scope, because
   the atlas says so explicitly: cluster 20 — "The SHAPE is always just elaphron
   — whether an instance participates in a syneches-elaphron figure is a
   PER-INSTANCE call from context ... See `figures.syneches_elaphron` for the
   proximity rule and the −2 vs −3 stakes."
5. Legend entries become `{value, n_votes, vote_histogram, source}`; an EM value
   requires n ≥ 5 and ≥70 % modal agreement. Together with
   `chanter_legend.json`'s immutability this is the **only** guard that catches
   a wrong *exact-key* value such as `3|16ab+8be` = 1 (8 votes) or `18|` = 0
   (4 votes); fallback logging cannot see either.
6. `hymn_align.py:637` (`'interval': int(iv.get(u['key'], 0))`) exports
   `compose_interval(...)` plus `interval_source` instead — today `aligned.json`
   disagrees with the value the DTW actually used on all 77 fallback units.

*Files.* `tools/mcr/unitlib.py`, `hymn_align.py:213-219, 358-372, 503-515, 637`,
`prep_hymn_annotator.py:310`, `chanter_legend.json` (new),
`legend_global.json` (schema migration).

*Acceptance.* t03 gi14 resolves to +3 by **compositional lookup overriding an
existing exact-key entry** — `3|16ab+8be` currently holds a wrong learned value
of 1, so this is not a "missing key" fix and neither "zero units resolve by
silent 0" nor "every fallback logged" would ever surface it; what makes it green
is the n ≥ 5 / 70 %-modal rule plus `chanter_legend.json` immutability, and the
test asserts the value flips 1 → 3 with the klasma carried separately in
`key_dur`. Zero units resolve by silent 0 corpus-wide (every fallback logged
with its unmodelled marks) **and zero units silently discard an
interval-bearing mark** (the 54-unit mode above is counted and driven to 0).
Distinct interval-lookup keys on the corpus fall from 52 to ≤ 40, none written
from fewer than 5 votes. A single
`chanter_legend.json` entry for the regrouped psifiston key changes all 133
former base-7 units. `CHANTER_LOCK` no longer appears in `hymn_align.py` and a
re-run reproduces the pre-migration locked values exactly.

---

### CHECK-01 — Martyria checksum as a hard gate
**Effort M. Depends on: DECODE-01, KEY-01.**

*Problem.* The book states an absolute degree at every cadence; `mart_deg` is
already captured and spent only as a soft DTW cost. Nothing asserts that decoded
intervals between two martyriai sum to the stated delta (t03: −3 vs required
+2).

*Change.* `hymn_align.py checksum <workdir> [--hymn NAME] [--json out]`: segment
each hymn at units carrying `mart_deg`, compare `sum(compose_interval)` between
consecutive anchors against the stated delta, emit per-segment residuals ranked
by magnitude as `workdirs/<wd>/checksum_queue.json` with the offending keys and
their support.

**Residual convention — pick one and print both.** The two definitions differ,
and the difference is not cosmetic. On t03's only closed segment (anchors
`mart_deg` 1 and 3; decoded sum −3):
- `residual_principal = decoded − delta_mod7_principal` = −3 − (+2) = **−5**;
- `residual_lifted = decoded − nearest_lift`, where the lift picks the member of
  `{…, −5, +2, +9, …}` nearest the decoded value (−5, since |−3−(−5)| = 2 <
  |−3−2| = 5) = **+2**.

The gate uses `residual_lifted` (a whole missing octave leap should not be
counted as a 7-degree melodic error), but **`residual_principal` is reported
alongside it in every row**, together with the explicit warning that any
residual ≡ 0 (mod 7) is invisible to the lifted form — the lifted gate is
structurally blind to exactly-one-octave decode errors, so the unlifted column
is what a reviewer reads for that class.

**Per-instance figure detection (from `atlas.figures.syneches_elaphron`).**
KEY-01 makes the interval a function of `key_iv`, which cannot express a figure
whose reading depends on the *distance between two neumes*. Add a detector:
apostrofos closely followed by an elaphron, with the inter-neume gap below a
learned threshold, is the syneches ("running") elaphron and reads as two slots
−1/−1 (net −2) plus its implied-gorgon timing — the implied gorgon halves the
PRECEDING note and the first apostrofos (½ beat each; the second apostrofos is a
regular beat, 2 with a klasma). The same two neumes farther apart are a plain
apostrofos then elaphron, −1 then −2, net −3. The atlas prescribes the
tie-breaker and CHECK-01 is where it belongs: **enumerate both readings for
every ambiguous apostrofos/elaphron proximity inside a martyria segment and
select the combination that closes the checksum**, recording the choice and the
gap that produced it. Report any segment where neither combination closes.
`--gate` exits non-zero on regression against `checksum_baseline.json`. Wire the
gate into `reseed_round.py` before `legend_global.json` is written and into
`cmd_legend` so an EM round that worsens the residual is rejected. Add the
assertion pass: diff the legend against `atlas_chanter.json` cluster intervals
and against every `iv_ovr_*` / `chanter_legend.json`, failing loudly.

**Sequencing constraint:** `--gate` is switched on in CI **only after** the
chanter has reviewed `MARTYRIA_DEG` cluster 26 (marked UNREVIEWED in the source
comment at `hymn_align.py:27-34`) and cluster 29 (43 red occurrences over the 20
grave-orthros pages — the most common red after gorgon at 288 and the
martyria/scale signs 23 and 24 at 94 each; no atlas entry). Until then the checksum runs in report-only mode. A wrong letter mapping
turns the gate into a confident wrong oracle.

*Files.* `hymn_align.py` (new `cmd_checksum`, gate in `cmd_legend`),
`reseed_round.py`, `workdirs/grave-orthros/checksum_baseline.json` (new),
`tests/test_checksum.py` (new).

*Acceptance.* `checksum grave-orthros --hymn t03_` reports, **on the segment
between martyria #1 and martyria #2** (identified by anchor uid, not by gi),
`residual_principal −5` / `residual_lifted +2` against today's legend, and 0 for
both after DECODE-01 + KEY-01; whole-hymn drift −13 before, |drift| ≤ 1 after.
A deliberately corrupted legend entry
(`6|` set to 0) makes `--gate` exit non-zero. The corpus residual work queue's
top entries name the regrouped psifiston keys and `3|16ab+8be` before they are
fixed. Validate the checksum first against the baseless martyria groups, whose
reading is unambiguous.

---

### DUR-01 — One beats function, colour-blind, with non-local rules
**Effort M. Depends on: DECODE-01.**

*Problem.* klasma detected only among red clusters (5 flags vs **199** units
carrying a cluster-8 mark token); the 37 units with cluster-10 dots add nothing;
gorgon's steal from the preceding note is unmodelled across 113 corpus gorgons;
the same formula is duplicated at
`hymn_align.py:197-199, 248, 481-483, 517-520` and
`prep_hymn_annotator.py:290-291`. (`APLI = {36}`'s phantom beat is already gone
pre-Gate-A; `APLI` is now empty and that fix is inside the baseline.)

*Change.* Single `beats_of(units, dur_legend, ovr=None)` in `unitlib.py`, called
from all five sites.
Pass 1 (local, driven by `key_dur` and roles, never colour): base 1.0; `+n` for
n cluster-10 dots (apli/dipli/tripli); `+1` for cluster-8 klasma;
`RED_GORGON = {11: 0.5, 25: 1/3, 30: 0.25}`.
**Cluster 32 (the dotted-gorgon dot) gets an explicit rule in `beats_of`**, not
just a marker. The atlas says "This is part of the dotted gorgon. This is the
dot itself. All the examples are dots on the right of the gorgon", and
`docs/BYZANTINE_SCALES_REFERENCE.md` §7.1 gives the split of the shared beat
between the two notes the gorgon covers: **dot AFTER (to the right of) the
gorgon ⇒ first portion 1/3, second 2/3; dot BEFORE (to the left) ⇒ 2/3 then
1/3**, where "first" is the earlier of the two notes. Encode the side from the
dot's x-position relative to the gorgon, and default to the right-hand form only
with a logged warning.
`RED_ARGON = {58, 90}` +1; `RED_FERMATA = {91}`;
`atlas.figures.rest` (vareia + apli/dipli/tripli) is a rest **of n beats for n
cluster-10 dots** (atlas cluster 10: "if combine with a preceding vareia is
treated as a standalone rest (or two for dipli or rest for three beats with
tripli)").
Pass 2 (non-local): gorgon sets `b[j-1] = max(b[j-1] - 0.5, 0.5)`; digorgon
distributes over prev/carrier/next; argon "adds a beat, removes half from the
two before". **The digorgon distribution is a proposal, not chanter-confirmed**
— it ships behind a `dur_legend` entry flagged `source: proposed` and goes into
the CORR-01 review queue. **The argon rule is chanter-confirmed**
(`atlas_chanter.json` clusters 58 and 90 both read "adds a beat, removes half
from the two before"), so it is marked `source: chanter` and is included in the
CI duration assertions.
Then apply `beats_ovr_<hymn>.json` absolutely (replace, not add). Remove 23, 22,
9 from `RED_TIME` so cluster 23 can serve as the
Ga anchor. Cluster 73 ("diargon+gorgon ... technically not a compound but its
own class") is either given a row in the duration role table or written to
`unknown_clusters.json`; it must not be silently dropped. `w_dur[j] = W_DUR * (2.0 if unit j has a confirmed beats override)`.
Recompute `spb` (`:483`) from corrected beats.

*Files.* `tools/mcr/unitlib.py`, `hymn_align.py:26, 37, 98-99, 197-199, 222-224,
248, 481-483, 517-520`, `prep_hymn_annotator.py:258-261`.

*Acceptance.* Regression test: t03 units {12, 14, 19, 45, 50, 61, 66} report
`klasma True` and 2.0 beats before the gorgon pass; gi6 `apli False`, 1.0 beats;
gi75 3.0 beats; gi12 = 1.5 and gi13 = 0.5 after the steal. **Corpus units with a
duration mark rise from 11 flagged to exactly 236 — the union of units carrying
an `8ab`/`8be` token (199) or a `10ab`/`10be` token (37), which are disjoint** —
and total notated beats rise correspondingly. This is an equality, checkable
against the ceiling; the earlier "≥ 240 (207 klasma + 37 dots)" was
unsatisfiable, since 199 + 37 = 236 is the ceiling and the only way past it is
to start counting something else as a duration mark. The cluster-32
dotted-gorgon split and the chanter-confirmed argon rule are asserted on t03 and
corpus-wide. Zero units get `klasma` from a red glyph. The beats formula exists
exactly once in the tree.

---

### CORR-01 — Typed corrections schema and a chip-based annotator sheet
**Effort L. Depends on: KEY-01.**

*Problem.* `index.html:227` stores `flags = {}` as `gi -> string`; `:1114`
exports `{gi, note}`. The only sink holds one integer, so 9 duration statements,
1 fthora and 1 split had nowhere to go, and 6 flags are empty because
`:1032` persists on button press. A chanter on a phone cannot thumb-type a
paragraph per glyph.

*Change.*
1. `exports/<piece>/corrections.json` v1:
   `{schema: 1, piece_id, data_rev, g0, g1, records: [{gi, uid, key_iv, key_dur,
   status: proposed|confirmed, ack, interval: {value, scope: key|instance},
   beats: {value, steal_prev}, marks: [...], fthora: {preset, scope: {until}},
   split: [{interval, beats}], note}]}`. Every block optional; absent = no
   opinion; the pipeline reads only `status: 'confirmed'`. `uid` + `key_iv` are
   the drift guard.
2. Replace the flagbox body (`index.html:163-165, 1001-1012`) with a stacked chip
   sheet, 44 px targets: row 0 `✓ machine correct` (writes `ack: true`, closes —
   one tap) / `✕ wrong`; row 1 interval chips −4..+4 with the machine value
   outlined; row 2 beats ½ 1 1½ 2 3 4 plus `steals ½ from prev`; row 3
   multi-select mark chips; row 4 collapsed fthora (preset × scope),
   auto-expanded when the unit carries a `fthora_candidate`; row 5 collapsed
   split-into-N; row 6 free textarea, always present, never the only sink.
3. An `✕` record with no block **and** no text is not dropped: it exports as
   `status: 'flagged_unspecified'` and lands in the unresolved queue. Nothing
   the chanter did may disappear.
4. Distinguish TODO (flag without note) from DESCRIBED in the export so the
   ledger counts them separately; paint `ack`ed glyphs green and
   `interval_source == 'fallback'` glyphs amber.
5. `serve.py:28-35` gains `'corrections': 'corrections.json'` in `EXPORT_FILES`
   and `OPTIONAL_KEYS` so a stale cached client still exports. Keep writing
   `mcr_flags.json` unchanged. Ship the sheet behind a toggle that keeps the old
   textarea path alive for one field session.

*Files.* `index.html:163-165, 227, 1001-1012, 1091`, `serve.py:28-35`,
`docs/CORRECTIONS-SCHEMA.md` (new).

*Acceptance.* A phone session confirms a correct glyph in one tap and states
interval + beats + mark identity in three taps with no keyboard. Export produces
a schema-1 `corrections.json` alongside the legacy `mcr_flags.json`. Creating a
t03-style empty flag is impossible — it becomes `flagged_unspecified`. Reload
restores every chip state from localStorage.

---

### CORR-02 — ingest_pins becomes the compiler; migrate the 25 existing notes
**Effort L. Depends on: CORR-01, DUR-01, CHECK-01.**

*Problem.* `ingest_pins.py:151-155` stages two files nothing reads; the docstring
and `tools/corpus/README.md` assert a data flow that does not exist. And where
`unitdeg` exists — all 25 hymns — `hymn_align.py:162-166` overwrites `exp`
wholesale, so `iv_ovr` does not move the alignment by one event.

*Change.*
1. Rewrite the staging half of `ingest_pins.py` as a compiler over
   `corrections.json` (confirmed records only), emitting into the **workdir**,
   where `hymn_align` actually looks: `chanter_legend.json` (interval,
   scope=key — the default), `iv_ovr_<hymn>.json` (scope=instance only),
   `beats_ovr_<hymn>.json`, `fthora_<hymn>.json`, `ack_<hymn>.json`, each with a
   `_provenance` block `{piece_id, export_stamp, data_rev, compiled_at}`.
   Idempotent, machine-owned, never hand-edited; `--dry-run` prints a diff.
   Fold today's hand-made `iv_ovr_t03_.json` in through the migration path.
2. Drift guard: verify `units[gi].uid == record.uid` and `key_iv` match; on
   mismatch re-anchor by unique key within ±3 units, else emit
   `status: 'stale'` into a review queue. `align_eval` prints the stale count.
3. Fix the `exp_abs` swallow: apply `exp[1:] = exp_abs` but re-apply override
   deltas to the suffix at overridden indices; warn loudly whenever overrides
   load and `exp_abs` would discard them; extend `reseed_round.py:86`'s
   `unitdeg_chanter_*` overlay to re-cumulate from corrected intervals.
   **`unitdeg_*.json` and `unitdeg_chanter_*.json` are gi-keyed and must be
   migrated to `uid` in the same commit as DECODE-01's resegmentation** — they,
   not `iv_ovr`, are what actually feeds the DTW.
4. Confirmation semantics: a record whose stated interval equals the current
   decode is recorded as `ack`, not an override. ≥N acks on a key with zero
   contradictions makes it a `chanter_legend` promotion candidate printed for
   sign-off. `align_eval` reports agreement over acked units as a separate
   true-positive rate.
5. One-time `tools/corpus/migrate_flags.py --piece grave-orthros-t03`:
   fixed-vocabulary keyword parser, **no LLM**, not part of the runtime
   pipeline, emits `status: 'proposed'` records the UI renders in amber with a
   Confirm button. Classification of the 25 (revision-2 indices): **15** with a
   stated interval (gi0, 1, 2, 3, 6, 7, 10, 12, 13, 14, 19, 48, 63, 71, 75),
   **3** duration-only (gi45, 50, 66), **7** needing the chanter (gi61's
   ambiguous mark identity and the 6 empty flags) — plus, separately, the
   sub-note representation of gi6, whose decode is now correct but whose
   two-notes-in-one-figure statement still has nowhere to live.

*Files.* `ingest_pins.py`, `migrate_flags.py` (new),
`hymn_align.py:162-166, 433-445`, `reseed_round.py:86`, `align_eval.py`,
`tools/corpus/README.md:132-138`.

*Acceptance.* The parser reproduces all 9 existing `iv_ovr_t03_.json` values
exactly (asserted in a test) before its other records are trusted. One confirmed
key-scope ruling propagates to all matching corpus instances and the CHECK-01
residual for the segment between martyria #1 and martyria #2 goes to 0. Replaying
the 75→76 renumbering (gold revision 1 → 2) through the drift guard reports 0
stale records. `grep -c chanter_pins hymn_align.py > 0`.

---

### FTH-01 — Mid-hymn fthora: a step-vector ladder plus a degree pivot
**Effort M. Depends on: DECODE-01, CORR-02.**

*Problem.* Genus is a scalar per `hymns.json` row (all 25 grave-orthros rows
`diatonic`; other workdirs carry soft/hard chromatic, so this is per-row, not
per-corpus). Red fthora glyphs are extracted and discarded. From t03 gi14
onward, 62 of 76 units quantize Zo 4 moria sharp.

*Change.* Register `RED_FTHORA` as a third red role and attach every red
non-time, non-martyria glyph in a based group as `u['fthora_candidate']`.

**A fthora does two things, and the record must carry both.** The step vector is
only the genus half. Both authoritative sources say the other half is a *degree
pivot*: `atlas_chanter.json` `fthora.semantics` — "a fthora over a melodic note
makes that note take on the quality of the indicated degree in the indicated
scale, **regardless of the degree it lands on**; applies to all fthores"; atlas
cluster 15 — "Over a melodic glyph it is a FTHORA: that note becomes diatonic Pa
regardless of where it lands — ALL fthores work this way"; and
`docs/BYZANTINE_SCALES_REFERENCE.md` §6 — "They operate by reassigning the
current degree to act as a different degree of a new scale (effectively
'pivoting' the tonal center)", with §6.1/6.2/6.3 naming the fthorai by the
degree they impose (Ni…Zo; Di soft-chromatic, Pa hard-chromatic; Ga/Zo
enharmonic). A step vector cannot express "this unit is now Pa", because that is
a shift in *absolute degree* space.

So the record is
`fthora_<hymn>.json = [{at_uid, until: {kind: next_martyria|uid|end}, preset,
steps, becomes_degree}]`, where `steps` is a **step-vector override** of
`DIA_STEPS = [12,10,8,12,12,10,8]` (never per-degree cents; ajem/harmonic =
index 5 10→6, index 6 8→12; assert `sum(steps) == 72` on load so octave
equivalence is automatic and malformed entries are rejected) and
`becomes_degree` **re-anchors the unit's absolute degree for the span**, with
the step vector applied on top. `becomes_degree: null` means a genus-only
fthora.

Build `lad_id[j]` per unit by scanning the span list, resolving
`next_martyria` against units carrying `mart_deg`. Two-pass: pass 1 aligns on
the base ladder and the matched `t0` of the span's first/last unit gives the
window; pass 2 requantizes only cents inside that window under the span ladder
and re-runs the DP. **Degree space is genus-invariant only for genus-only
fthorai such as the t03 ajem** — that one is expressible purely as a step vector
(`[12,10,8,12,12,6,12]`, sum 72, Zo at 60 moria, i.e. the chanter's "6 moria
from ke and 12 from ni"), so for it `unitdeg`/`exp_abs` are untouched. A
**pivoting** fthora (`becomes_degree` set) necessarily rewrites `unitdeg` and
`exp_abs` from `at_uid` to the end of the span, and is **unhandled-and-flagged**
until the chanter has reviewed cluster 29's variants: the pipeline emits it into
the review queue and refuses to apply it. (This does not yet bite grave-orthros:
across the 20 pages the martyria/scale-sign clusters 15/24/35/50/56 never sit
over a melodic note — the only 6 group-sharing instances are cluster 24 over
cluster 33, the argosyntoma tempo sign at a hymn heading, which DECODE-01
removes from base candidacy. The invariant is nonetheless false in general, so
it is scoped rather than asserted.)

For the genus-only case only three sites change — `deg_obs` quantization
(`hymn_align.py:478-479, 512`), the cents-agreement `exp_c` (`:561`, which must
use the unit's own ladder), and `prep_hymn_annotator`'s `step_pos` grid so the
annotator's pitch band visibly shifts. **Span resolution reuses ALIGN-02's
hard-anchor partitioner** rather than writing span machinery twice.

*Files.* `hymn_align.py:88-101, 473, 478-479, 512, 561`, `unitlib.py`,
`prep_hymn_annotator.py`, `workdirs/grave-orthros/fthora_t03_.json` (new).

*Acceptance.* `fthora_t03_.json` with ajem at gi14 (`becomes_degree: null`,
`steps: [12,10,8,12,12,6,12]`) puts Zo at 60 moria from gi14 to the next
contradicting martyria; a steps vector summing to 71 is rejected at load, and a
record with `becomes_degree` set is rejected-and-queued rather than applied.
t03 `movement_agreement_cents` improves and the gold-pin median |dt| in the
gi14..next-martyria span does not regress. All 43 cluster-29 instances in the
grave-orthros page range appear in the annotator as fthora candidates with the dropdown pre-opened.

---

### ALIGN-01 — Extract note_align6's DP into a reusable library
**Effort L. Depends on: nothing (runs in parallel from day one).**

*Problem.* `datasets/eothinon-11-workdir/note_align6.py` implements the model we
want — "NO absolute-pitch term" (`:8`), `CLAIM_BONUS` (`:46`),
`SKIP_SLOT_STATIC/MOVE` (`:50`, `:183`), `DUR_DEFICIT`/`DUR_SURPLUS` (`:44-45`,
`:342`, `:372`), piecewise local tempo, hard/soft anchors with `W_PIN = 0.32`
(`:52`, `:297-299`) — but it is bound to eothinon-specific files and hardcoded
`MANUAL`/`DROP_WI`/`ATTACH_OVR` constants and cannot be called by the corpus
lane.

*Change.* New `tools/mcr/align_mv.py` exposing
`align(slots, events, anchors, opts) -> path, diagnostics`, with
`slots = [{uid, dmov, beats, boundary, ladder_id}]` and
`events = [{t0, t1, cents, gap_before}]`. Port the cost model verbatim; delete
every eothinon-specific constant (they become caller-supplied anchors and
overrides); reduce `note_align6.py` to a thin caller. Degrade cleanly when there
is no `ison_timeline`, no word anchors and no barlines — the corpus lane has
none of those.

*Files.* `tools/mcr/align_mv.py` (new), `note_align6.py` (reduced),
`tools/mcr/mcrlib.py`.

*Acceptance.* `note_align6.py` through the library reproduces its current
`slot_claims.json` and `timing.json` byte-for-byte on eothinon-11 — that
identity is the port's test. `align_mv.py` contains zero references to any
eothinon filename or index. Unit tests cover the hard-anchor span partition, the
virtual-event fallback and the tempo reset at breaths.

---

### ALIGN-02 — Rebuild cmd_melos on align_mv; pins as anchors; identifiable Ni
**Effort L. Depends on: ALIGN-01, KEY-01, DUR-01, EVAL-01.**

*Problem.* `W_ABS, ABS_CAP = 0.55, 2.0` (`hymn_align.py:140`) puts a per-unit
absolute cost of up to 1.10 against `SKIP_U = 1.2`, so deleting a unit is priced
at roughly the cost of keeping a slightly-off one. Audit ablation (2026-08-18,
to be re-derived by `gold_eval`): shipped pre-refit t03 = median 0.464 s / 40 %
within 0.30 s; `W_ABS = 0` = 0.040 s / 88 %, and corpus mean unit coverage
58.0 % → 76.8 %, improving all 25 hymns. The ±80 c refit (`:496-539`) then makes
t03 four times worse while `agree_of` (`:523-529`) scores it in the quantized
space the refit just moved, and `:534` accepts a strictly shorter path.
`MAX_DU = 4` is binding. `SKIP_U` is flat although a large share of consecutive
unit pairs share a degree and are unsegmentable in legato singing.
`hymn_align.py:204-205` hard-locks unit 0 to the first 8 events and the 0.3/event
tail ramp exceeds `SKIP_E = 0.25`.

*Change.* Build slots via DECODE-01/KEY-01/DUR-01/FTH-01 and call
`align_mv.align()`. Specifically:
1. Delete the per-unit `abs_c` term.
2. **Ni identification** is the delicate part: with a shift-invariant movement
   DP, all 8 degree hypotheses produce the same path, so a post-hoc continuous
   fit alone does not select `kdeg`. Identify it from (a) martyria-closed
   absolute anchors — after CHECK-01, every martyria segment fixes the absolute
   degree of its endpoints, which is a far stronger constraint than the current
   4 %-of-units soft cost — and (b) a robust Huber fit of matched event cents
   against `dia_pos(unit_deg[j])*CPM` for the continuous offset, then (c) a
   corpus prior: flag any hymn whose fitted Ni deviates > 150 cents from the
   per-chanter median. Hymns with **zero** martyriai in range are reported as
   `ni_unidentified` rather than silently guessed. Removing `W_ABS` and landing
   this identification are one atomic change.
3. Feed `melos_<h>/chanter_pins.json` as HARD anchors partitioning the DP into
   independently solved spans; SOFT anchors get the capped dead-zoned prior plus
   `SOFT_SKIP`; drop soft anchors contradicting the hard partition. Hold out
   every third pin per §2.3.
4. `CLAIM_BONUS`; `SLOT_SKIP[j] = 0.25 if unit_deg[j] == unit_deg[j-1] else 0.9`
   as a prefix sum replacing `SKIP_U*(j-j2-1)`; `MAX_DU` 4 → 10.
5. Asymmetric duration with the local tempo curve; both end ramps soft and
   symmetric from the same fee vector (hard start/end anchors make them moot
   where pins exist).
6. Refit scored on cents residual against the fixed ladder, requiring
   `n_new >= n_old` — or moved out of the loop entirely as a post-hoc
   relabelling of `degree_obs` with the path fixed.
7. Gate the drone skip discount (`:189-192`) on actual second-voice evidence
   rather than proximity to the modal pitch.
8. `exp_abs` guard: require 100 % `unitdeg` coverage or forward-fill from the
   legend-cumulative interval as `cmd_legend` already does at `:363-370`, and
   record the fill count — the current `>= 0.8` gate at `:449-451` admits
   `None`, which becomes NaN at `:164` and silently makes those units
   unmatchable.
9. Widen `segment_tracks.py`'s pitch search (currently `hi = sr/90`) to roughly
   60-450 Hz so a low-Ni hymn is not truncated by the tracker floor.

*Files.* `hymn_align.py:38-41, 140, 150-247, 258-280, 449-451, 464-539`,
`tools/mcr/segment_tracks.py`, `tools/mcr/align_mv.py`.

*Acceptance.* On t03 against the **held-out** pins, with the §2.2 denominators
spelled out: **median |dt| ≤ 0.15 s over matched held-out pins (n printed) and
≥ 70 % of ALL held-out pins within 0.30 s** — today, over all 76 pins, median
0.551 s over 54 matched and 0.211 within 0.30 s (the r1 figure was 4.1 s / 6 of
44 within 0.35 s = 0.08 over 75 pins).
**Coverage floor (blocking):** matched-pin coverage on t03 must not fall below
the frozen Gate-A baseline of 54/76 = 0.711. Without this floor the onset target
is directly gameable — dropping the hard units out of the match set raises both
the median and the frac — and nothing else in the plan constrains it, since
§2.8 puts assisted hymns (t03 is one) in a separate block excluded from OVERALL
and the corpus coverage target below is scoped to the 15 aligner-bound hymns.
Corpus mean unit
coverage ≥ 70 % on the 15 aligner-bound hymns, with the 10 detector-bound
hymns (E/U < 1) reported against their own `min(1, E/U)` ceiling and excluded
from that target. `movement_agreement_cents` improves on ≥ 20 of the 25
grave-orthros hymns and no hymn regresses on the gold-pin metric. Every hymn's
Ni is either within 150 cents of the corpus median or explicitly flagged.
Because DECODE-01/KEY-01 change `compose_interval`, the cents comparison is run
against a **frozen-legend baseline snapshot** taken at the end of EVAL-01, not
against today's live numbers.

---

### PARA-01 — Harvest the parallagi labels under the new decoder
**Effort L. Depends on: DECODE-01, CHECK-01, ALIGN-02.**

*Problem.* The legend is learned from parallagi supervision but currently rests
on 36 valued keys with thin support (42 keys carry support at all; only **19**
reach n ≥ 5; `legend_global.json` support: `4|` 386, `5|` 181, `6|` 131 at the
head, and a long tail of 1-5), because pairing is weak and every
vote is cast against a wrongly-elected base. The `len(obs) >= 2` gate
(`hymn_align.py:404-414`) counts only adjacent single-step matches, so real
support is lower than the printed number.

*Change.* (a) Re-pair at scale in `re_pair.py`: score candidate parallagi dirs
against each hymn by DTW of the hymn's unit degree sequence versus the
recording's `degree_abs` sequence **under the DECODE-01 units**, keep the best
per hymn with a bootstrap confidence, and write `match_frac`, `n_matched`,
`pair_conf` back into `hymns.json`. (b) Confidence-weighted EM: weight each vote
by `pair_conf` and by whether the containing martyria segment closes
(CHECK-01); cap any single hymn's contribution to a key so one mispaired
recording cannot carry a key. (c) Break the self-confirmation loop: mark each
`unitdeg` entry `matched` or `interpolated` and exclude interpolated entries
from votes and from every reported agreement. (d) Emit
`workdirs/<wd>/review_queue.json` of keys with n < 5 or fallback keys with
support ≥ 2, routed into the CORR-01 sheet.

*Files.* `re_pair.py`, `parallagi_pitchfill.py`, `hymn_align.py:300-380`,
`reseed_round.py`, `wire_anchors.py`.

*Acceptance.* Stated as **support statistics in the post-KEY-01 `key_iv` space**,
not as a key count: a raw "keys with `n_votes >= 5` rise by ≥ 2×" target would
fight KEY-01's own acceptance criterion, which *shrinks* the key space (52 → ≤
40) by merging duration variants, so both cannot be measured in the same units.
Therefore: total matched votes feeding EM rise ≥ 2× against the Gate-A baseline;
**median per-key vote support at least doubles**; and **the fraction of corpus
UNITS whose `key_iv` has ≥ 5 votes** rises from its Gate-A value to an agreed
target. All three baselines are recorded at Gate A **in `key_iv` space**, not in
today's 52-key space (today, for reference, 19 of 42 supported keys reach n ≥ 5).
No key is written from fewer than 5 votes. Corpus martyria residual falls
monotonically across EM iterations — if it does not, the harvest is injecting
noise and is reverted.

---

### GOLD-01 — Gold contract, pins→claims adapter, honest model reporting
**Effort L. Depends on: DUR-01, CORR-02.**

*Problem.* Gold #2 cannot enter the training lane: no `arc/` dir under
`workdirs/grave-orthros`, and no converter from `[gi, time]` pins to
`slot_claims.json` (slot → index into the **cleaned** stream). The required
layout is discoverable only by reading `train_aligner.build_piece`.
`train_arc_silver.py` builds a per-hymn group array and never reads it, so the
silver lane has no measured value, and `eval_arc.py:16` defaults to the eothinon
model. `report_aligner.json`'s 0.655 coverage uses gold claims (255) as the
denominator, not score slots (327).

*Change.*
1. `tools/corpus/pins_to_claims.py`: run `hymn_to_workdir.py grave-orthros t03_`,
   `build_piece` it, map each pin `(gi, t)` to `first_slot[uid]` and to
   `argmin_k |t0_cleaned[k] - t|` with a hard reject above 0.25 s, enforce
   monotonicity in both indices, assert the round trip, emit `slot_claims.json`.
2. `tools/corpus/validate_gold.py` + `docs/GOLD_CONTRACT.md` enforcing:
   `moria_track.npy`/`rms_track.npy` float32, 10 ms hop, equal length, NaN =
   unvoiced; `voice_notes3.json` **raw** (build_piece re-cleans; never
   pre-clean); `slots.json {t, gi, sub}` length S; `mcr_interpretation.json`
   indexed by gi with `beats` length == `sub_notes`; `expected_degrees.json`
   length S, martyria-closed absolute degrees; `barlines.json` with `next_glyph`
   a gi; `ladder.json` length S **required** for any piece with a fthora span
   (build_piece's fallback hardcodes `DIA_STEPS`); `slot_claims.json` length S,
   monotone, into the cleaned stream. `train_aligner` refuses to run without a
   clean validation.
3. Reporting fixes: `--holdout` in `train_arc_silver.py` that uses the group
   array it already builds and writes `report_silver.json`; `eval_arc.py`
   requires `--model`; `report_aligner.json` prints all three coverage
   denominators and headlines `coverage_slots`; add the contiguous-block holdout
   protocol; **add a majority-class baseline for every head to
   `report_gbm.json`** (`y_beats` 0.447, `y_comp` 0.663, computed over the same
   255 structural events — today only the glyph task has one, 0.3451) and quote
   each head against its own baseline. Retire the flat-glyph head from the
   headline (0.4667 GBM / 0.4588 CNN against a 0.4902 interval-rule baseline).
   The **beats head clears its majority baseline (0.569 vs 0.447)**; the
   **compound-position head does not clear its own (0.690 vs 0.663, inside one
   SE)** and is retained only as a feature, not as a headline result. The beats
   head is the one DUR-01 and CORR-02 multiply.
4. **Do not pool gold #1 and gold #2 at arc level.** Pool at feature level with
   a `granularity` indicator and a per-dataset sample weight, and exclude gold
   #2 rows from any sub/compound-conditioned loss until DECODE-01's sub-note
   expansion applies to corpus units — `hymn_to_workdir.py:52-58` hardcodes
   `sub_notes: 1`.

*Files.* `pins_to_claims.py` (new), `validate_gold.py` (new),
`docs/GOLD_CONTRACT.md` (new), `hymn_to_workdir.py:52-58`,
`train_arc_silver.py`, `eval_arc.py:16`, `tools/mcr/train_aligner.py:46-182,
482, 527`.

*Acceptance.* `validate_gold.py` passes on both eothinon-11 and
grave-orthros-t03; `slot_claims.json` exists for t03 and round-trips to
`pins.json` within 0.25 s. `report_silver.json` exists with a held-out hymn
score. `report_aligner.json` prints three coverage denominators and both CV
protocols with fold vectors. Every subsequent config change is quoted on t03
onset MAE and logged against the touch budget.

---

## 5. Sequencing and gates

```
EVAL-01 ──┬─> DECODE-01 ──┬─> KEY-01 ──┬─> CHECK-01 ──┐
          │               ├─> DUR-01 ──┤              ├─> CORR-02 ─> FTH-01
          │               │            └─> CORR-01 ───┘        │
          │               └────────────────────────────────────┼─> PARA-01
ALIGN-01 ─┴─> ALIGN-02 (also needs KEY-01, DUR-01) ────────────┘
                                        CORR-02 ─> GOLD-01
```

**Gate A — before DECODE-01 starts.** `gold_eval.py` exists and reproduces the
ledger's current t03 numbers (or explains the upper-median discrepancy in
writing, per EVAL-01); the `.bak` duplicates are gone from the scoreboard;
`ingest_pins.py` with no arguments finds the real export; a **frozen baseline
snapshot** of `legend_global.json`, `unitdeg_*.json`, all `summary.json`, the
corpus key/vote counts and the `key_iv`-space support statistics PARA-01 needs
is committed, because every later comparison is against it.

**The snapshot is taken from a pinned revision, not from the live tree.** The
tree moved twice while this document was being written (the omalon/`APLI` fix
and `_note_subgroups` landed, then t03 was re-prepped, re-aligned and
re-ingested), which is exactly how §1's and §3's tables went stale mid-draft.
So Gate A: (a) record the exact content hash of `tools/corpus/hymn_align.py`
alongside the frozen legend/unitdeg/summary set — currently sha256
`284e595988627d9e…`, 680 lines; (b) freeze corpus re-runs and annotator exports
while the snapshot is taken; (c) **re-derive §1's and §3's tables, and every
`file:line` citation in §4, against that pinned revision** (the citations in §4
were written against a shorter draft of `hymn_align.py` and several are off by
tens of lines) and replace the quoted scoreboard before Gate A is declared
passed; (d) note in `CHANT-MODEL-ACCURACY-LOG.md` that the omalon/`APLI` and
note-split changes landed *before* Gate A, so their effect is already inside the
baseline and must not later be attributed to DECODE-01 or DUR-01.

**Gate B — before any chanter session resumes.** DECODE-01's `uid` identity, the
`unitdeg_*`/`unitdeg_chanter_*` uid migration and CORR-02's re-anchor-or-stale
rule are all landed. **Annotation sessions are frozen from the start of
DECODE-01 until this gate**, because resegmentation renumbers gi and any
correction authored in between lands on the wrong note.

**Gate C — before CHECK-01's `--gate` is switched on in CI.** The chanter has
reviewed `MARTYRIA_DEG` cluster 26 and red cluster 29, and the checksum has been
validated against the baseless martyria groups. Until then it runs report-only.

**Gate D — before ALIGN-02.** `beats_of` is the single beats implementation and
its t03 regression test passes; `align_mv` reproduces gold #1 byte-for-byte;
the pin holdout split is fixed and recorded.

**Gate E — before PARA-01's harvested votes are written.** CHECK-01 residual is
a live number per hymn and the EM non-regression gate is active. Harvesting at
scale through an ungated EM industrialises whatever error remains.

**Opportunistic exception.** ALIGN-02's item 1+2 (delete `W_ABS`, land Ni
identification) may be landed immediately after Gate A as a measured, revertable
experiment, provided both ship together and the result is quoted on the pin
metric. It is the single largest measured win available and it is two files.

---

## 6. Risks and how each is detected early

| Risk | Early detection |
|---|---|
| **Resegmentation destroys the gold labels.** This has already happened once: the 75 → 76 split shifted every gi-keyed artifact (`pins.json`, `slots_corrected.json`, `unitdeg_t03_`, `unitdeg_chanter_t03_`, `iv_ovr_t03_`) by +1 from old-gi 6 on, and the gold had to be hand-re-indexed into `datasets/grave-orthros-t03-gold/` at revision 2. Any further DECODE-01 resegmentation does it again. | A CI test asserting `pins_to_claims` round-trips all 76 revision-2 pins within 0.25 s, run on every commit that touches `unitlib`. Every acceptance criterion in this plan is stated by `uid` or by anchor ordinal, never by gi or by positional index. Gate B. Non-zero stale count in `align_eval` is a build failure, not a warning. |
| **Clusters 7, 22 (and 36) may be mixed clusters.** The chanter calls the same group "psifiston" (gi10, 71) and "vareia" (gi48, 63) with no cluster 12 present, and cluster 22's own atlas entry asks for a colour-context re-review (ison-variant ⇒ +0 one slot vs kentimata ⇒ two notes, net +2), and `atlas.figures.rest` makes vareia+apli a REST. A single role for a mixed cluster reintroduces the bug DECODE-01 exists to kill. | Split-cluster detection runs **before** roles are frozen: cluster geometry (width, dy to base, glyph bbox) is histogrammed per cluster and any bimodal cluster is reported for chanter review. Cluster 7's 133 instances are the first item on that queue. |
| **The checksum becomes a confident wrong oracle.** `MARTYRIA_DEG` cluster 26 is marked UNREVIEWED in the source; cluster 24 was already removed once as a −3 anchor error. | Gate C. Report-only mode first; residual distribution inspected for a mode-specific bias (a systematic residual on Ga cadences implicates cluster 23/26, not the legend). |
| **Removing `W_ABS` leaves Ni unidentifiable.** The movement DP is shift-invariant. | ALIGN-02 item 2 ships atomically with item 1, and `ni_unidentified` is a first-class reported state. Corpus Ni scatter against the per-chanter median is printed in every scoreboard run. |
| **Detector-bound hymns absorb the blame for aligner work.** 10 of 25 grave-orthros hymns have E/U < 1. | `E/U` and `min(1, E/U)` are columns from EVAL-01 onward; coverage targets are stated only over the aligner-bound set. |
| **PARA-01 scales label noise as well as labels.** A confidently mispaired recording injects a whole hymn of wrong degrees. | Corpus martyria residual is required to fall monotonically across EM iterations; per-key vote histograms make a single-source key visible; per-hymn contribution cap. |
| **Two gold pieces cannot support a defensible split**, and gold #1's 0.761 is selection-biased (`train_aligner.py:36` "hard-negative mining hurt", `:190-192` "CV ablation .714 → .753", `:347-348` ".761 → .702", `train.py:36` "CTX = [] hurt at n=255") and leaks through whole-piece EM anchoring at `:482`. | Quote 0.761 ± 0.14 with the fold vector always; contiguous-block holdout reported alongside; gold #2 touch counter in the changelog. A fold vector spanning 0.465-0.842 is stated in every report. |
| **The chip UI is a rewrite of a tool the chanter already knows.** | Ship behind a toggle keeping the textarea path alive for one field session; keep writing `mcr_flags.json` unconditionally; measure the session by taps-per-glyph and by unresolved-queue size, not by whether it "works". |
| **FTH-01 and ALIGN-02 both need span machinery.** | FTH-01 is sequenced after CORR-02 and explicitly reuses ALIGN-02's hard-anchor partitioner; if ALIGN-02 slips, FTH-01 slips with it rather than forking the code. |
| **The digorgon distribution is a proposal.** (The argon rule is *not* a proposal — atlas clusters 58 and 90 both state it in the chanter's words, so it ships `source: chanter` and is inside the CI duration assertions.) | The digorgon entry ships flagged `source: proposed` in the duration legend, excluded from the CI regression assertions, and is the first item in the chanter review queue. |

---

## 7. Non-goals

- **No new model architecture.** Nothing here trains a bigger network. The one
  model-shaped change (ALIGN-01/02) is a port of `note_align6.py`, which already
  exists in the tree and already works on gold #1.
- **No LLM in the runtime pipeline.** `migrate_flags.py` is a one-time
  fixed-vocabulary keyword parser that emits a file and exits; its output is
  `status: 'proposed'` and requires chanter confirmation before anything reads
  it.
- **No image-MCR / OCR work.** The born-digital text layer supplies the glyph
  stream for this book; the scanned-anthology lane is out of scope.
- **No tuning against `movement_agreement`.** It is demoted to a diagnostic in
  EVAL-01 and no acceptance criterion in this plan is expressed in it.
- **No aligner tuning on detector-bound hymns** (E/U < 1) until
  `segment_tracks.py`'s re-articulation rule (`SEG_DIP = 7.0` dB, a high bar for
  legato chant) is swept against the t03 pins on missed-vs-spurious at 0.15 s.
  That sweep is itself out of scope here and gets its own workstream.
- **No pooling of the two gold pieces** at arc level, and no third-gold-piece
  collection, until `validate_gold.py` and the contract exist.
- **No changes to the tanpura/scales app, the training-app lanes, or anything
  outside `tools/corpus`, `tools/mcr`, `tools/chant-reel/annotator` and
  `datasets/`.**
- **No unit-width hard cap** and no other unevidenced geometric threshold:
  DECODE-01 reports over-wide units, it does not split on a guessed constant.
- **No synthesis of chanter testimony.** The six empty flags stay empty and
  become a pre-filled review queue; class membership is recorded as inference,
  never as his word.
