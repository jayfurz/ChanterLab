# Plan: forced-alignment onsets, so pinning stops being a chore

Written to be executed by a session with **no prior context**. Everything needed
is here or at a named path. Read the whole file before starting.

Repo: `/mnt/data/code/byzorgan-web-worktrees/chant-annotator`, branch
`chant-align-dataset`. Merge to `main` and push when done.

---

## 1. What the chanter actually wants

He annotated `s01` and stopped: *"i did half of it but it needed a lot of work
and is annoying."*

The export says exactly why. `datasets/exports/grave-orthros-s01-unset-…/`
holds **30 pins and all 99 slots corrected by hand**, because the machine times
were wrong by a **median of +3.2 s, up to +8.5 s**. The piece has no aligner
output, so its slots were seeded by spreading beats evenly from t=0 — while the
singing starts at 1.579 s and then drifts.

Every slot had to be dragged. That is the job to remove.

**The deliverable is not a better score. It is that opening a piece and pinning
it takes minutes instead of an hour.** Judge every step by that.

---

## 2. Why forced alignment, and what is already proven

Measured, do not re-derive:

| | |
|---|---|
| CTC forced alignment, 32 word onsets vs the NEAREST of the 76 t03 pins | **0.0345 s** median (re-measured 2026-08-20; the old **0.028 s** row mislabelled this as "vs the 76 pins") |
| CTC forced alignment, character path carried to all 76 glyphs | **55.3 %** within 150 ms, median 0.061 s over the 56 it places |
| the DTW aligner, all 76 pins | 0.714 s median, 32.9 % within 150 ms (the often-quoted 0.485 s is over the 52 units it matched — a different denominator) |

> **t03 is training data and a burnt benchmark** (NEURAL-CHANT.md §6.1): every
> figure in the row(s) above is a comparison number against prior work, never
> evidence of generalisation. Rates are over all 76 pins; the DTW aligner's
> often-quoted 0.485 s median is over the 52 units it matched, and over all 76
> it is 0.714 s.

| event detector: events emitted for 259 real notes | **342 (+32 %)** |
| event detector recall at 50 ms | 63 % |
| aligner coverage, median over 173 hymns | 64.0 % — the same number, and not a coincidence |

The event detector invents a third more events than there are notes and misses a
quarter of the real ones, and **the aligner cannot exceed its recall** — a note
whose onset produced no event cannot be claimed at any cost. Forced alignment
skips that layer entirely: a syllable onset *is* the articulation the chanter
pins. Full reasoning in `ONSET-EVENTS.md`.

Two dead ends, already measured, **do not retry without new evidence**:

- Filtering "consonant drag" excursions: removes true and spurious events in
  equal proportion, F1 flat at 0.54 then falling.
- Tuning `SEG_JUMP` / `SEG_DIP`: swept 20 combinations, the optimum **is** the
  shipped 80 / 7.0.
- Trimming the apichima before FA: 2 of 6 spans improved, mean Δ −0.156. FA
  skips the intonation by itself.

---

## 3. What FA needs, per lane — this is the part that unlocks it

FA aligns **known text** to audio. The text differs by lane, and both are
available:

- **melos** — the hymn text. `texts/glt_span_match.json` matches each of the 47
  spans to canonical GLT text. Two match at 0.998, ten at ≥0.55.
- **parallagi** — the **degree names**, which is what he actually sings there.
  Chanter: *"you can use FA on parallagi as long as the parallagi derived
  notenames are accurate."* Build with
  `score_degrees.degree_stream(...)` then `as_text(...)` → `δι γα γα γα βου …`.
  This is proven: it is how the apichima question was answered.

Where text coverage is low, FA has been handed partly wrong text and its output
is not evidence. `s01` itself is coverage 0.357 — treat it as a hard case, not a
baseline.

---

## 4. The work

### FA-01 — a reusable FA onset lane

Write `tools/corpus/fa_onsets.py`. For one piece:

1. Pick the text by lane (§3). Refuse, loudly, if there is none.
2. Run `forced_align.align(wav, text, 'cuda')` — from
   `tools/corpus/forced_align.py`, which returns
   `[{word, t0, t1, score}, …]`.
3. Map word onsets → **unit indices**. A melos word covers one or more units; a
   parallagi degree word is 1:1 with a non-rest unit, which makes parallagi the
   easier case and the one to build first.
4. Write `fa_onsets.json` next to the piece: `{unit_index: t0}` plus the word
   score, so a caller can gate on confidence.

**Environment.** The corpus venv has torch, torchaudio and transformers; the
system python does **not**:

    /mnt/data/chant-corpus/venv/bin/python tools/corpus/fa_onsets.py …

**GPU.** The cards are leased. Take one and give it back:

    /mnt/data/code/infra/platform/qwen38/gpu-swap.sh lease ml claude "<why>" 45m
    …work…
    /mnt/data/code/infra/platform/qwen38/gpu-swap.sh release

CPU works for a 50 s span if the GPU is busy; a 400 s one wants the GPU.

**Acceptance:** all 47 spans produce onsets or an explicit refusal with a reason.
No silent failures.

### FA-02 — seed the annotator from FA instead of from beats

`tools/corpus/prep_span_annotator.py` currently spreads beats evenly from
`t_in_rel` or 0. Replace that with FA onsets where FA-01 produced them, keeping
the beat spread as the fallback, and record which was used in
`meta.seed_method` — it already carries that string.

Interpolate units FA did not place, by beat weight between the ones it did.

**Acceptance, and this is the real test:** re-prep `s01` and compare against his
export. Report median |Δt| against **his 99 corrected slots** and against his
**30 pins** separately. Beat the current median of 3.2 s. State how many slots
land within 0.15 s.

### FA-03 — the same for the 173 hymn pieces

`prep_hymn_annotator.py`, same change. Here FA competes with a real aligner
rather than with a beat spread, so gate it: use FA where its word score beats a
threshold, else keep the DTW time. Report both.

**Acceptance:** median |Δt| against the 76 t03 pins improves on the current
alignment. If it does not, say so and stop — do not ship it on faith.

### FA-04 — correct `t_in` from FA

FA finds where singing starts by itself. Measured on the six spans carrying a
`t_in` mark: on `t01_#5` FA lands on **15.32 s**, which is exactly the value the
chanter confirmed over his own 13.33 mark, and FA agrees with the register
detector to 0.01 s on the two spans that detector was trusted on.

So write the FA-derived onset into the piece meta as a **third estimate** beside
`t_in_rel` and `sung_onset`. Do **not** overwrite `cuts_*.json` — his cut
boundaries are locked: *"all the s# hymns are already cut perfectly do not cut
those. the start/finish of the audios of those and the scores are golden and
locked forever."* Surface disagreements on a review sheet instead.

---

## 5. Traps

- **`cuts_grave-orthros.json` is locked.** 47 hand-marked spans, `t0`/`t1` and
  score ranges. It has been byte-identical all session and must stay so. Only
  unit INDICES in `scorecuts` ever move, and only via
  `reindex_kentimata.py`, which re-derives from `.prekentimata.bak` and is
  idempotent. Run `--verify` after anything that changes segmentation.
- **Never score by CTC loss.** The confidence gate once rated identification
  81 % when the truth was 20 %. Score against the chanter's pins.
- **Movement agreement is not a metric.** It reads 1.00 on t03 while the median
  onset error is 0.485 s — it grades the aligner against its own decode.
- **Gold time bases can differ from their audio.** `eothinon-11`'s
  `audio_full.m4a` runs **1.98 s** ahead of its `note_times.json`. Measuring
  without correcting reports 10 % recall instead of 63 %. Fit the offset, and
  check the rate as well.
- **Nothing writes through `audio.wav`.** Those files are copies of
  irreplaceable recordings; an earlier symlink let `ffmpeg` truncate a source
  from 53.4 s to 4.8 s. Render to a scratch file and `os.replace` it.
- **Never regenerate `span_names_*.json` or the gold sets.**
- **Check the client, not just the API.** A piece can serve 200 from
  `/api/…` and still fail to load in the browser; that happened, and the check
  that catches it drives the page in jsdom rather than parsing the JS.

---

## 6. How to know it worked

Not "the numbers improved". Open
`https://annotator.lab.alwaysdobetterllc.com/`, pick **s01**, and see whether the
markers already sit on the notes. He finished half of it by hand; the other half
is the test. If he still has to drag every slot, this plan failed regardless of
what the medians say.

Ground truth available, all chanter-verified:

| set | labels |
|---|---|
| `datasets/grave-orthros-t03-gold/pins.json` | 76 pins |
| `datasets/eothinon-11-workdir/note_times.json` | 259 onsets |
| `datasets/exports/grave-orthros-s01-…/` | **30 pins + 99 corrected slots** (new) |

**No onset enters gold without the chanter.** Machine onsets are silver; they
train, they never grade.

---

## 7. Not in scope

The neural onset model (`ONSET-MODEL.md`). This plan is the layer beneath it and
may remove most of the error it was designed to absorb — which is why
`ONSET-MODEL.md` §8 now puts this first and sizes the model against what FA
leaves wrong.
