# Plan: fix the onset model

Written 2026-08-19, after measuring the current one against the chanter's gold.
Companion to `ONSET-MODEL.md`, which designs a learned model for onset
*precision*. This plan is about the layer **underneath** it, and it changes what
that model should be trained on — so read this one first.

---

## 1. The diagnosis, and how it changed

The chanter pinned a note on `grave-orthros-t01` and asked why the engine was
wrong. The first answer was that the engine is systematically **late**: it waits
for pitch to settle on the expected degree, while he pins the articulation, so a
voiced consonant puts them ~0.3 s apart. That story was right about the
mechanism and **wrong about the shape of the error**.

Measured against gold #1 (`eothinon-11`, 259 chanter-verified onsets):

| | |
|---|---|
| detector events | **342** for 259 notes — **+32 %** |
| gold onsets with an event within 50 ms | **63 %** |
| within 100 ms | 75 % |
| **timing where an event IS found** | median **−0.020 s**, sd 0.074 |
| detector events with no gold onset within 50 ms | **57 %** |

So where the detector finds a note it is **essentially unbiased** — 20 ms, not
300. The defect is not lateness. It is that the detector **invents a third more
events than there are notes** while still missing a quarter of the real ones. On
t01 it had split one note into three and the aligner picked the wrong one of the
three; that is the general failure, not a timing offset.

### 1.1 Coverage is capped by this, not by the aligner

Median aligner coverage across the 173 hymns is **64.0 %**. Event recall at
50 ms is **63–64 %**. Those are suspiciously equal, and the mechanism is
obvious: a note whose onset produced no event cannot be claimed by any path, at
any cost setting. **The aligner cannot exceed the event layer's recall.** Every
hour spent on DTW costs while a third of onsets have nothing to attach to is
spent on the wrong layer.

---

## 2. Two things that do NOT work — measured, not assumed

Both were the obvious fixes. Neither survives contact with the gold, and they
are recorded here so nobody spends a week rediscovering it.

### 2.1 Filtering "consonant drag" does not help

The chanter's own discriminator: a consonant makes the pitch dip and **return**,
a melisma moves on and stays. Corpus-wide that classifies 20,149 short unmatched
excursions as 60 % consonant drag, 28 % melisma-like, 4 % breath — so the
signal is real. But applied as a filter it removes true and spurious events in
almost equal proportion:

| filter | events | recall | spurious | F1 |
|---|---|---|---|---|
| none | 342 | 63 % | 57 % | **0.54** |
| drop drag < 0.20 s | 319 | 61 % | 55 % | 0.54 |
| drop drag < 0.30 s | 295 | 57 % | 54 % | 0.53 |
| drop drag < 0.45 s | 249 | 49 % | 54 % | 0.50 |

F1 is flat then falls. The excursions it removes are not the excursions that are
wrong.

### 2.2 The thresholds are already optimal

`segment_tracks.py` has two knobs: `SEG_JUMP` (pitch move that starts a new
note, 80 cents) and `SEG_DIP` (amplitude dip that splits one, 7 dB). Swept over
the cached tracks, 20 combinations:

| | best F1 |
|---|---|
| JUMP 60 | 0.52 |
| **JUMP 80 (today)** | **0.56** |
| JUMP 110 | 0.49 |
| JUMP 150 | 0.43 |
| JUMP 200 | 0.33 |

The optimum is **exactly the shipped setting**, `JUMP=80 DIP=7.0`. Nothing in
the parameter space does better; raising the threshold loses recall faster than
it removes spurious events. **This is not a tuning problem.** Pitch-plateau
segmentation cannot separate a note onset from an articulation event in this
material at any threshold, because both are pitch movements of the same size.

---

## 3. What to do instead

### ONS-01 (M) — forced alignment as the onset source

The strongest option, and it is already half-built. `forced_align.py` does CTC
forced alignment of the **known text** against the audio, and
`PIECE-RESEPARATION.md` records it measured against the chanter's 76 t03 pins:

| | onset error vs 76 chanter pins |
|---|---|
| DTW over detected events | 0.485 s |
| **CTC forced alignment** | **0.028 s** |

That is 17× better, and it is better for the reason this whole plan is about: a
syllable onset **is** the articulation, so forced alignment locates the thing
the chanter pins rather than inferring it from where pitch settles. It needs no
event detector at all.

Why it is not already the source: it currently only proposes *hymn boundaries*,
and on `grave-orthros/t01_` it recorded `"skipped: low FA confidence",
loss_per_token 4.759`. The chanter's diagnosis of that, which is testable and
cheap: *"i think the forced alignment having a low fa confidence might be
because there is a long apichima in the beginning. that should probably be cut
when put into the forced alignment."* Every span already records `t_in`, the
apichima end.

Steps:

1. Re-run FA on the spans with the apichima trimmed — feed `[t_in, t1]`, not
   `[t0, t1]` — and compare `loss_per_token` before and after. Test first on the
   spans where `t_in` is furthest from `t0`.
2. Extend FA output from hymn boundaries to **per-syllable onsets**.
3. Project syllables onto units via the GLT text match (`SYL-01` in
   `ONSET-MODEL.md` §2.2 — 157/173 hymns matched, median 0.90 coverage).
4. Use FA onsets as the aligner's event stream in place of `voice_notes.json`,
   or as hard anchors that the DTW must pass through.

Acceptance: median onset error against the 76 t03 pins **and** the 259
eothinon-11 onsets, both reported. Beat DTW's 0.485 s on t03. Recall at 50 ms
above 63 % on eothinon-11, which is what the event layer manages today.

**Gate:** English scores. Gold #1 is English EZ-font, where the melisma is a
blank or a rule rather than a reprinted vowel, so the text stream is not 1:1
with notes there. FA may work well on Greek and poorly on English; report the
two separately rather than averaging them into one number.

### ONS-02 (S) — score-informed event recovery, for what FA cannot reach

Where FA has no text (parallagi spans are sung degree names, not hymn text;
melismas run many notes per syllable), the event layer still has to work. The
lever not yet tried is the **score**: the unit stream says how many notes there
are and roughly how long each is. A segmenter that must emit *n* events in a
window is a different problem from one emitting events greedily.

Not a threshold sweep — that is closed. A per-piece constraint: given `beats_seq`
and the audio duration, take the *n* best boundary candidates rather than every
candidate above a fixed threshold.

Acceptance: recall at 50 ms above 63 % **with** event count within 10 % of the
score's note count. Both, not either.

### ONS-03 (S) — pin more gold, on purpose

335 verified onsets exist: 76 (t03) + 259 (eothinon-11). Every number in this
plan rests on one of the two. The pieces to pin next are the ones that
discriminate: a Greek melismatic hymn (tests FA where text repeats per note) and
a parallagi span (tests the no-text path). The annotator lane already exists —
prep → pin → `ingest_pins` → gold.

**No onset enters gold without the chanter.** Machine onsets are silver; they
train, they never grade.

---

## 4. Traps

- **Time bases differ between a gold set and its audio.** `eothinon-11`'s
  `audio_full.m4a` runs 1.98 s ahead of `note_times.json`, and durations differ
  (273.18 s vs the 264.02 s the gold index records). Measuring without correcting
  it reports 10 % recall instead of 63 %, which is what happened on the first
  pass here. Fit the offset before scoring, and check the **rate** too — it is
  1.000 here, so a constant offset is correct for this pair, but do not assume it.
- **Never score by CTC loss.** The confidence gate rated identification 81 %
  when the truth was 20 %. Score against the chanter's pins, with
  `name_check.py` / `heuristics_eval.py`.
- **Movement agreement is anti-correlated with gold pin accuracy.** Never tune
  on it alone.
- **Do not render training audio from `beats_seq` timing.** The model would
  learn to reproduce the arithmetic it exists to transcend. See
  `ONSET-MODEL.md` §3.1.
- **The +32 % is not all error.** Gold #1 has 327 slots but only 259 verified
  onsets, so the chanter himself did not mark a distinguishable onset for every
  notated slot. Some detector events may be real notes he did not pin. That is
  an argument for ONS-03, and a reason to report recall and spurious rate
  separately rather than collapsing them into accuracy.

---

## 5. What this changes in ONSET-MODEL.md

That plan assumes the residual is *precision within a locked passage* — the
±150 ms arithmetic cannot remove. That is real, but it is the second problem.
The first is that a third of onsets have no event to be precise about. Two
consequences:

1. **Training data.** A learned model trained on machine-aligned unit↔event
   pairs inherits the event layer's 57 % spurious rate as labels. If ONS-01
   lands, retrain on FA onsets instead — better labels, and far more of them.
2. **Ordering.** ONS-01 is cheaper than the model and may remove most of the
   error the model was designed to absorb. Measure after it before sizing the
   model.
