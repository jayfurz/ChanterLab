# NEURAL-CHANT — the onset encoder-decoder, made implementable

**Goal: every note onset within 50 ms of the chanter's pins.** Each note is one
timeline event; none are excluded. Release criterion: **≥ 90 % within 50 ms with
zero slips** (§9).

**The encoder-decoder is a decision, not a hypothesis.** Forced alignment does
not produce note onsets — it produces *candidates*, at roughly 2.4 per note, and
4 % accuracy if its word-level output is taken as-is (§0.2). Something has to
select among them and supply the rest. Generation (§8) is the stated later goal,
which is why §3 fixes the vocabulary as the full neume stream now.

`ONSET-MODEL.md` holds the design rationale — why an encoder-decoder, why a
distribution rather than a scalar, why these base models. This document is the
executable half: vocabulary, features, tensors, contracts, gates.

Every number below was measured, with the script that produced it named. Where a
number is inherited and unverified it is marked so and may not be used.

*Consolidated rewrite 2026-08-20, superseding four rounds of patching.*

---

## 0. Where we stand

### 0.1 The current aligner loses sync; it is not imprecise

`grave-orthros-t03`: 76 glyphs, **all 76 pinned**, so the denominator is
unambiguous. Chanter's ruling: *"none of t03 are melisma interiors. each note
event is one timeline event."* An empty syllable label marks a note **sung on a
continuing vowel**, not a lesser note.

The annotator's current slot times against those pins:

```
median |Δt| 0.714 s    mean 1.609    p90 4.560    max 5.837

  within 0.05 s   23/76   (30 %)   <- the target threshold
  within 0.15 s   25/76   (33 %)
  within 0.35 s   27/76   (36 %)
```

Widening the tolerance sevenfold buys four notes. Read the shape instead —
`.` within 50 ms, `o` within 500 ms, `X` worse:

```
glyph  0 .o.XXXXXXXXXXXXXXXXXXXXXXXXoXXoooXXXXX
glyph 38 XXXXXXXXXX............o.........XXXXoX

signed drift every 8th glyph:
 +0.0  +2.1  +4.6  +1.7  -0.3  -3.1  -0.0  +0.0  -0.0  +0.5
```

It starts correct, drifts to **+4.6 s**, returns through zero, overshoots to
**−3.1 s**, recovers, then holds twenty notes dead-on. It is **losing sync and
re-acquiring it**, not adding noise.

### 0.2 What forced alignment actually leaves: a selection problem

The chanter's diagnosis: *"repeated vowel sound extensions wouldn't get a
syllable onset, instead we would need the chant music aware to know when those
notes get hit which is a mixture of envelope, beat timing, pitch, etc — which is
how a human can tell when a certain note is hit."*

The mechanism is right. CTC emits a token when the *character* changes, so a
note re-articulated on the vowel already sounding produces no new target token.
On t03, 18 of 76 glyphs carry no fresh syllable — ordinary notes (`4|`
apostrophos mostly, some `5|`, one `6|`, 1.0–2.0 beats).

But `forced_align.py` aligns every *character* and only aggregates spans into
words at the end. The stored 32 word records are a post-processing artefact, not
a property of CTC. Measured by `tools/corpus/fa_char_coverage.py`:

```
t03: 33 words, 179 aligned characters
  distinct character-level onsets in the CTC path      179
  gold pins with SOME character onset within 0.05 s   46/76  (61 %)
  gold pins with SOME character onset within 0.10 s   62/76  (82 %)
  gold pins with SOME WORD onset within 0.05 s         3/76  ( 4 %)
```

1. **The stored word output is nearly useless as an onset source — 4 %.**
   Whatever the inherited 0.028 s measured, it was not this.
2. **The character path holds evidence for 61 % of notes at 50 ms.**

**(2) is an oracle number.** 179 candidates for 76 notes is ~2.4 per note: the
information is present, not picked out. So the model's job is **selection among
candidates, plus supply where no candidate exists** — far better posed than
regressing time from nothing.

One claim from an earlier draft is withdrawn: the phonetic stream having no new
*target token* does not mean it has no *acoustic evidence*. Hidden states and
CTC-logit variation may well carry a re-attack. Stream C (§4) is required
because it carries those cues cheaply and explicitly, not because stream A is
provably deaf.

### 0.3 What that means for the build

- **§7's propose/verify/backtrack decode is the primary contribution**, not a
  post-process. The Δt head exists to feed it.
- The 20 ms grid is 2.5× finer than the target, so **frame rate is not the
  bottleneck**; quantisation costs ±10 ms of a 50 ms budget.
- **Slip count is a first-class gate** (§9). A model that halves median error
  while slipping as often has not delivered.

### 0.4 REPRO-01 — the inherited baseline is unusable

`forced_align.py`, `FA-ONSETS.md` and `ONSET-MODEL.md` all cite **0.028 s median
against the 76 t03 pins**. It cannot be reproduced from this repository: the
stored result holds 32 word onsets against 76 per-glyph pins, **no word→glyph
mapping is stored**, and no script computes the figure. Reconstructing the
mapping from per-glyph syllable labels fails — 18 glyphs carry no label and
glyph 0 lost its first syllable, so the match walks off by up to 35 s.

**The baseline is unverified in both directions.** REPRO-01 (§10) produces a
real one. Until it lands, no inherited number may be quoted as a baseline, and
no gate may be written against one.

---

## 1. Inventory

| asset | count | where | notes |
|---|---|---|---|
| chanter-verified onsets | **335** | `datasets/grave-orthros-t03-gold/pins.json` (76), `datasets/eothinon-11-workdir/note_times.json` (259) | the only gold. t03 tests, the rest trains (§6.1) |
| in-progress pins | 37 | `datasets/exports/grave-orthros-s01-…` | growing; **training** data (§6.1) |
| note units in the book | **116,043** | `score_degrees.units_for(1,0,0,999,999,10**9)` | score-only, no audio needed (§6.3) |
| distinct unit keys | 123 | same | over 16 bases |
| cadence martyrias | 3,886 | `u['mart_cad']` | free constraints (§1.1) |
| audio | **37.4 h / 264 recordings** | `/mnt/data/chant-corpus/corpus.json` | all one singer (ATTR-01) |
| annotator note slots | 19,868 | 220 pieces | 4,050 carry no fresh syllable |

372 pinned onsets is the binding constraint, and only 76 of them are held back.
§5.4 and §6.3 exist because of it, and §6.1 explains why the chanter's pinning
rate is the critical path.

### 1.1 The martyria constraint — real, and currently violated

A cadence martyria states the degree sung at that note, so between two of them
the legend's intervals must sum to the degree difference. `martyria_check.py`:

```
57 gaps between consecutive cadence martyrias
  17 satisfied     40 VIOLATED (70 %)
  33 "sum too LOW"  (an ison should be an oligon) -- 31 have room
   7 "sum too HIGH" (an oligon should be an ison) --  6 have room
```

The asymmetry matters: demoting an oligon to an ison can only *lower* a sum, so
the known ambiguity cannot explain the 33 low gaps. That is a systematic legend
gap, and a solver built on it today would invent a different local excuse per
gap — hence CHECK-01 before any constraint solver.

**Policy, one rule, applied everywhere: the checksum is REPORT-ONLY until Gate
C.** That covers the decode (§7) and the silver filter (§6.2) alike — log what
it *would* have rejected, reject nothing. **Gate C** is defined in
`CHANT-MODEL-ACCURACY.md` §1233: the chanter has reviewed `MARTYRIA_DEG` cluster
26 and red cluster 29, and the checksum is validated against the baseless
martyria groups. A rule violated in 70 % of gaps must not gate anything.

---

## 2. Hardware and environment

```
2 x RTX 3090, 24 GB each. Usually held by the qwen38 tenant.
```

```bash
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh lease ml neural-chant "training" 6h
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh renew 4h
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh release      # always
```

Environment (provisioned; do not build another):

```
/mnt/data/chant-corpus/venv/bin/python
  python 3.14.7 · torch 2.11.0+cu130 (cuda) · transformers 5.15.0
  torchaudio 2.11.0 · numpy 2.4.1 · librosa 1.0.0 · soundfile 0.14.0
```

48 GB total is why §4 caches features **once, to disk**: 37.4 h at 20 ms is
6.73 M frames, 13.8 GB for stream A in fp16. Training then needs one card and
never loads an encoder.

---

## 3. NN-01 — the vocabulary. Free today, unrecoverable later

The decoder vocabulary is the **full neume stream**, because a decoder trained
on an interval alphabet can never emit a psifiston, and §8 depends on that.

**Factored, not flat.** 123 distinct unit keys exist; a flat vocabulary cannot
emit an unseen base/mark combination. Each unit becomes a short sequence:

```
UNIT_START
  BASE_<id>                 # 16 observed, reserve 64
  MARK_<id> ...             # zero or more, ORDER PER THE RULE BELOW
  DUR_<klasma|apli1..3|dot1..2>
  TEMPO_<gorgon|digorgon|trigorgon|argon|chiasma_*>
  [FTHORA_<genus>_<degree>]
  [MART_<degree>_<cad|open>]
UNIT_END
```

Plus `BARLINE`, `REST`, `LINE_BREAK`, `PAGE_BREAK`, `SPAN_START`, `SPAN_END`,
`BOS`, `EOS`, `PAD`, and the §5.2 conditioning prefix. About **300 tokens**.

**Mark order — one rule.** Marks are emitted in a *canonical* order so a figure
always yields the same token sequence. **Which canonical order is not yet
decided**: sorting by mark id is the default, but DECODE-01 (role-driven base
selection) and KEY-01 (mark position and geometry) may prove that position
carries meaning an id-sort destroys, in which case the order is by confirmed
semantic role. NN-01 does not start until those report (§10), and
`vocab_v1.json` records which order was chosen and **which distinctions the
vocabulary drops**.

Further rules, enforced by tests:

- **Round-trip exact** on all 116,043 units. This is the NN-01 gate.
- **Derived quantities are not tokens.** `iv` and `beats` are computed from the
  figure by `legend_canon` / `beats_seq`; as tokens the decoder could contradict
  the legend. They enter as *features* (§5.2).
- **Unknown ids get `BASE_UNK` / `MARK_UNK`**, not a crash.

Deliverable: `tools/neural/vocab.py`, with `vocab_v1.json` frozen. Never mutate
a shipped vocab file; add v2.

---

## 4. NN-02 — the feature cache, computed once

**Three streams.** A is phonetic, B is musical context, C is the onset cues.

**Stream A (primary): `jonatasgrosman/wav2vec2-large-xlsr-53-greek`, frozen.**
20 ms frames, 1024 dims. Keep the last hidden layer *and* the 41-token CTC
logits — the logits carry "a character is starting here" explicitly, and its
Greek head is what makes forced alignment possible at all.

**Stream B (secondary): `MiniMaxAI/MiniMax-Music3` `condition_encoder`.** 40 ms
frames (`input_hop_length 960` @ 24 kHz). Harmonic and timbral context, where
40 ms is ample. Upsample ×2 to the 20 ms grid. **Whether B helps is open** —
cache it, train with and without, report both.

**Stream C (required): the music cues.** §0.2 says the model must select among
candidates and supply onsets where none exist; envelope, pitch and beat are what
a human uses to do that. Two of the three tracks already exist per workdir at
**10 ms**:

```
cents_track.npy  (5390,) float64   f0 in cents    10.0 ms/frame
rms_track.npy    (5390,) float64   amplitude      10.0 ms/frame
```

| ch | definition | source |
|---|---|---|
| `f0_cents` | pitch in cents; 0 where unvoiced, with `voiced` marking it | `cents_track.npy` |
| `df0` | first difference, not computed across unvoiced gaps | derived |
| `rms` | amplitude | `rms_track.npy` |
| `drms` | first difference — envelope re-attack | derived |
| `flux` | half-wave-rectified spectral flux, **new in `features.py`**: STFT `n_fft 1024`, `hop 320` @ 16 kHz — i.e. **computed natively on the 20 ms grid**, `sum(max(0, |X_t| − |X_{t-1}|))`, per-piece median-normalised | new |
| `voiced` | 1 where the tracker reports voicing | `cents_track.npy` |

`flux` is already at 20 ms and is never resampled. The four channels derived
from the 10 ms tracks are downsampled 10 → 20 ms by taking the **max of `drms`**
and the mean of `f0_cents`, `rms`, `voiced`: an onset is a peak, and averaging a
two-frame window is how you lose it.

**Encoder-input contract**, identical for all three: resample to the 20 ms grid,
layer-norm, project by a linear map to `d_model`, **concatenate along the
feature axis** before the audio self-attention stack. All three are audio-side
and frame-aligned, so local cross-attention addresses them on one index.

Stream C is not an ablation candidate. Stream A can be ablated and B is an open
question, but C is the only stream carrying explicit envelope and pitch, and
those are the cues §0.2 names.

Cache layout, one `.npz` per recording:

```
/mnt/data/chant-corpus/features/<recording_id>.npz
   a_hidden  float16 [T, 1024]   stream A last hidden
   a_logits  float16 [T, 41]     stream A CTC logits
   b_cond    float16 [T, D_b]    stream B, upsampled to 20 ms
   c_music   float16 [T, 6]      stream C, per the table above
   t0        float32             start offset of frame 0, seconds
   sr, hop   int                 16000, 320
```

Each file also stores **provenance**: model repo id and revision, the code
revision that wrote it, the sha256 of the source audio, and the frame-origin
convention (`t = t0 + i*hop/sr`; frame *i* covers `[t, t+hop/sr)`). A cache whose
producer is unidentifiable is a correctness hazard the moment an encoder moves.

Gates:
- **Timestamps exact.** Re-deriving FA onsets from the cache must reproduce
  `forced_align.py` to < 1 ms.
- **fp16 must not move the answer.** Re-run the REPRO-01 evaluation from the
  cache; it must reproduce REPRO-01's numbers, whatever they are. If fp16
  degrades them, store fp32 and pay the disk.

---

## 5. NN-04 — the model

Layer counts are `N`/`M`, fixed by the §5.4 curve. **The starting model is
N=2, M=3**; the ceiling the data plausibly supports is N=4, M=6.

```
                         ┌──────────────────────────────────────┐
  A+B+C frames  ────────►│ N x local self-attn, window ±64 fr    │  20 ms grid
  (cached)               │ (±1.28 s — onset evidence IS local)   │
                         └───────────────┬──────────────────────┘
                                         │
                         ┌───────────────┴──────────────────────┐
                         │ mean-pool /25  ->  0.5 s summary      │  global memory
                         └───────────────┬──────────────────────┘
                                         │
  neume stream ─────────►┌───────────────┴──────────────────────┐
  (NN-01 tokens)         │ M x decoder block:                   │
  + iv, beats, FA cands  │   causal self-attn over neumes (full) │
  + genre/mode prefix    │   cross-attn LOCAL  -> ±150 frames    │  (3 s window,
                         └───────────────┬──────────────────────┘   pointer-centred)
                                         │
                          Δt head (201 bins)   ·   neume head (§6.3)
```

### 5.1 Hybrid attention

- **Audio self-attention is windowed**, ±64 frames. Onset evidence is local;
  full attention over 15,000 frames is 225 M pairs per layer and buys nothing.
- **Neume self-attention is full and causal.** ≤ ~2,000 units per hymn.
- **Cross-attention is two paths.** LOCAL over ±150 frames (3 s) around a
  pointer at the previous accepted onset — the onset evidence. GLOBAL over the
  0.5 s-pooled summary (600 vectors for a 300 s track) — "where am I in this
  hymn", which is what stops a slip becoming permanent.

The pointer is initialised at the previous confirmed onset and advanced by the
`beats_seq` prediction; the model learns the residual.

### 5.2 Neume-side input

| feature | source | why |
|---|---|---|
| unit tokens | NN-01 | the figure |
| `iv` | `legend_canon` | melodic step, as a feature not a token (§3) |
| `beats` | `beats_seq` | the arithmetic prediction, as a prior |
| melisma index / length | SYL-01 | which note of several on this vowel |
| previous + target syllable | SYL-01 | the chanter's query unit |
| syllable-present mask bit | SYL-01 | an absent syllable must not read as a real zero |
| FA candidate onsets in window | `forced_align` character path | §0.2 — the decoder *selects* among these |
| mode / genre / book / incipit | directory + hymn name | **plain text**, so an unseen genre degrades rather than fails |

f0, RMS, Δ and flux are **audio-side**, entering through stream C (§4); they are
frame-aligned time series, not per-unit features.

The `beats` prior is the most important input: the network learns where the
chanter *departs* from the grid, and that departure is signal, not noise.

### 5.3 The Δt head

Δt from the previous confirmed onset, quantised to **20 ms bins over [0, 4 s]**
= 200 bins plus overflow. Softmax over 201. Cross-entropy with label smoothing
onto ±1 bins, because pins carry their own jitter.

Point regression is disqualified: the model must be able to say *"0.31 s, or
possibly 0.62 s if a note was skipped"* and let §7 arbitrate. A regressor
averages those to 0.47 s, which no amount of training fixes.

### 5.4 Size — a curve, not a guess

Start at **~4 M** (`d_model 192`, N=2, M=3) and grow only along a measured
learning curve — 4 M / 12 M / 40 M — **scored on the silver dev fold** (§9), not
on pins. 40 M is the ceiling the data plausibly supports, not a starting point.
A tie ships the small one.

### 5.5 The training and decoding contract — write it before `model.py`

NN-04's gate is a committed *document*, not a forward pass:

- **Target definition.** Δt from the previous note's onset, or the previous
  *accepted* onset? They differ between teacher forcing and decode.
- **Teacher forcing.** Trained on gold-previous and decoded on own-previous is
  the classic exposure mismatch; choose scheduled sampling or a mixed regime.
- **Masks.** Exactly which frames local cross-attention sees at step *n*, and how
  the pointer moves when a step is rejected.
- **Overflow.** What bin 200 (> 4 s) means at decode — rest, slip, or abstention.
- **Anchors at train time.** FA candidates are decode inputs (§7); if they are
  not also train inputs the model never learns to use them.

---

## 6. NN-03 — the data

Three sources, three trust levels, never mixed. Every example carries
`provenance` and `source_recording_id`.

### 6.1 Gold — and why some of it must be trained on

76 t03 pins (Greek, Ioannou vector), 259 eothinon-11 note times (English, Karam
EZ fonts), 37 s01 pins and growing. **372 chanter-pinned onsets today.**

**The hole this plan had, and the fix.** An earlier revision reserved *all* gold
for evaluation. That is unimplementable, and the reason is exact: the model
exists to place notes on a continuing vowel (§0.2); those notes have **no FA
anchor by construction**, so §6.2 silver cannot label them; and if gold is also
withheld, **the Δt head never sees a single labelled example of the class it is
being built to solve.** On t03 that is 18 of 76 notes with no target anywhere in
the training set.

So gold is split **by fold**, not withheld wholesale:

| fold | role |
|---|---|
| **eothinon-11** (259) | **trains.** The only supervision covering continuing-vowel onsets |
| **s01…** (37, growing) | **trains.** Same corpus and engraving as the target material |
| **t03** (76) | **tests, once.** Never trained on, never selected on |

This costs the cross-script transfer claim — t03 becomes the only held-out
fold — and that is the right trade: a transfer claim about a model that could
not learn the task is worth nothing. Hyperparameters are still chosen on the
silver dev fold (§9), so t03 is touched exactly once, at the end.

**This makes chanter pinning the critical path.** Continuing-vowel notes are the
scarce label, and only the chanter can produce them. Pinning priority is: notes
with no FA candidate first, then notes where candidates disagree. Every new
pinned piece goes to training except the reserved t03.

### 6.2 Silver from forced alignment

Syllable-initial notes across the 220 pieces, timed by `forced_align_batch.py`.
Per §0.2 this is a *candidate* set, not a label set: notes on a continuing vowel
get no FA anchor of their own, and even where an anchor exists there are ~2.4
candidates per note. Silver therefore supervises **candidate ranking on syllable-initial notes only**.
It cannot supervise a continuing-vowel onset, because it has no anchor there —
that supervision comes from gold (§6.1). Its quality is what REPRO-01 measures.
**NN-03 does not start before REPRO-01 reports.**

**Lane-specific admission.** A *melos* track sings the hymn text, so FA on the
canonical GLT text applies. A *parallagi* track sings **degree names**, so FA
must run against `score_degrees.as_text()` instead — and that stream is only as
good as the legend, with score-derived degree identification measured at 2 of 23
(chance). Parallagi silver is admitted only where pairing is known by position
(23/23 reliable). One blanket rule would pour the worse lane into the better.

Filters, all mandatory:
- drop pieces whose FA path fails `name_check.py` — **never gate on CTC loss**;
  that gate rated mode2 15/15 when 5 of 15 were right
- drop the machine-cut boundaries `ONSET-EVENTS.md` flagged; the 47 chanter-cut
  spans are trusted, the 173 machine cuts are not
- CHECK-01 runs **report-only** here, per §1.1 — log what it would drop

Never interpolate labels, and never manufacture them from our own duration
model: that trains the network to reproduce the arithmetic it should correct.

### 6.3 Score-only pretraining — 116,043 units, zero labels

**This is what makes the model affordable on 335 labels.** The decoder's neume
side — which compounds follow which, cadence formulae, melisma shapes — is
learned as a plain autoregressive LM over the neume stream with no audio and no
onset labels. This trains the **neume output head** shown in §5, which is
therefore part of this plan, not deferred.

Be honest about scale: ~500 k factored tokens teaches local n-gram structure and
cadence formulae, not a deep model of style. That suffices, because the onset
labels then only have to train the cross-attention and the Δt head.

Stage: neume-LM pretrain → warm-start → train alignment on silver → evaluate on
gold once. Report the ablation *without* 6.3 so the claim is measured.

---

## 7. NN-06 — decode: propose, verify, backtrack

1. **Propose.** Emit the next *k* onsets (k = 4–8), selecting among the FA
   candidates in the window and emitting a free onset where none fits.
2. **Verify.** Accept the longest prefix that is monotonic, within the
   `beats_seq` tolerance, and consistent with high-trust anchors. CHECK-01 is
   evaluated and **logged, not enforced**, until Gate C (§1.1).
3. **Backtrack.** Keep a beam of anchors; when accepted-prefix length collapses
   or entropy spikes, roll back and take the next branch.

**Beam branches may insert and delete score units.** This is required for
CHECK-01 to mean anything later: a martyria constrains a sum of *intervals*,
which is invariant to timing, so against a fixed unit sequence every timing
hypothesis gives the same checksum and it discriminates nothing. It becomes
informative only because the §0.1 failure *is* skip/repeat — a desynchronised
path has consumed the wrong number of units against the audio.

Anchor trust, strict: **chanter pins > FA character candidates the model has
accepted > martyria-satisfied cadences (post-Gate-C) > model onsets.**

Everything else about the beam — width, score equation, anchor-crossing
semantics, beat tolerance, entropy threshold, rollback state, termination, and
what "high confidence" numerically means — is specified in an NN-06 contract
written before `decode.py`, parallel to §5.5, and tuned on dev folds only.

---

## 8. GEN-01 — generation, and the one thing it demands today

**What this architecture does and does not give.** §5's model consumes neume
tokens and emits Δt; §6.3 adds a neume output head for pretraining. What is
missing for generation is a **text / target-phrase encoder** to condition on.
"The same weights run backwards" is false as shorthand — but the gap is one
encoder, not a new model, because the vocabulary and the neume head already
exist.

What is free today and unrecoverable later is §3's vocabulary: because it emits
the full factored stream, a generative head can emit a psifiston. An interval
alphabet never can.

**Style personas are blocked, and not by the model.** `corpus.json` carries only
`path/name/dur_s/size`. All 264 recordings are one singer; every persona would
collapse to one point because there is one point.

**ATTR-01 (S), before the next ingest.** Singer, school, place, date, source URL
and attributor at ingest; backfill the 264 as `vasilikos`. Retrofitting costs
far more than capturing at the door, and distinct clusters need meaningful hours
*per* style — months of the flywheel, wasted if the field does not exist now.

---

## 9. Evaluation

**Primary metric: `frac(|Δt| ≤ 0.05 s)`** over a fixed denominator of every
pinned note. **Comparison semantics, because one note sits on the edge:** errors
are compared as `round(|Δt|, 3) <= 0.050`, inclusive, in milliseconds. On t03,
glyph 63 has an error of `0.04999999999999716` — it currently passes by
floating-point luck, and an undefined comparison would let a rebuild silently
move the headline by a note. Define it once, here — all 76 on t03, all 259 on eothinon-11. An unmatched note is a
miss. Medians are reported but never gate: §0.1 is a median of 0.714 s on an
aligner that is dead-on for twenty consecutive notes.

**Secondary and equally binding: slip count** — maximal runs where signed drift
leaves ±0.05 s and does not return within 3 notes. t03 today: 4.

**Two-tier data discipline, one rule.**

| tier | what it is | what it may decide |
|---|---|---|
| **silver dev fold** | whole source recordings held out of §6.2, scored against their FA character-path anchors | stream B, §6.3 ablation, the §5.4 size curve, all NN-06 thresholds |
| **gold train** | eothinon-11 (259) + s01… (37, growing) | nothing — it is training data (§6.1) |
| **gold test — t03 (76)** | the reserved fold | the final claim, **touched once** |

No hyperparameter is ever chosen on gold, train or test. The gold *train* fold
exists because the continuing-vowel class has no other supervision; the gold
*test* fold is never fitted, selected on, or inspected until the final run.

The dev fold is a weaker instrument than pins — that is the price of not
spending them, and why NN-05's bar (60 %) sits below NN-06's (90 %). Two gold
pieces cannot absorb repeated model selection; a number tuned on them estimates
nothing.

Report alongside the headline a **split by evidence class** — notes with an FA
candidate versus notes on a continuing vowel — because a system can look fine
overall while failing the class §0.2 is about. Diagnostic, not a denominator.

**Timebase manifests, fixed before scoring.** eothinon-11 needs a known 1.98 s
offset; a stale time base once turned 63 % recall into a reported 10 %. Each
fold carries audio sha256, offset, rate and derivation. **The transform is never
fitted against model predictions.**

**Disqualified metrics.** Movement agreement reads 1.00 on t03 at 0.485 s median
error — it grades the aligner against its own decode. CTC loss as correctness —
that gate rated mode2 15/15 when 5 of 15 were right. Synthetic data gates
nothing.

**Baselines** (all from REPRO-01 except the first two, measured here):

| system | ≤ 0.05 s | notes |
|---|---|---|
| annotator today, t03 | 30 % | 4 slips |
| FA word onsets, t03 | 4 % | the stored output |
| FA character path, oracle pick | 61 % | **upper bound**, ~2.4 candidates/note |
| target | **≥ 90 %** | **0 slips** |

---

## 10. Staging

| id | work | gate |
|---|---|---|
| **REPRO-01** (S) | `fa_eval.py`: character- and word-level FA scored on all 76 t03 pins, mapping validated not merely reproduced | a number a second run reproduces. **Blocks NN-02 onward** |
| **DECIDE-01** (S) | characterise the gap: coverage, ≤50 ms rate, misses, failure classes, split by evidence class | a sized brief naming which notes the model must own |
| **NN-00** (S) | arithmetic baseline: `beats_seq` + one fitted tempo | reproduced by a script |
| **CHECK-01** (M) | find the systematic −1/−2 in the 40 violated gaps | `martyria_check.py` exits 0: violated < 8 of 57 |
| **NN-01** (S) | `vocab.py` — **after DECODE-01/KEY-01 settle mark order** (§3) | round-trip exact on 116,043 units; dropped distinctions recorded |
| **NN-02** (M) | `features.py`, three-stream cache with provenance | FA re-derived from cache matches REPRO-01 |
| **NN-03** (M) | `dataset.py`, lane-specific silver | no gold **source recording** in any train split — including derived cuts, overlapping excerpts and duplicates. Split by `source_recording_id` |
| **NN-04** (M) | `model.py` at 4 M | §5.5 contract committed first |
| **NN-05** (L) | train on silver + the gold train fold; curve 4 M / 12 M / 40 M | **≥ 60 % ≤50 ms on the silver dev fold, slips < 2**, no collapse on continuing-vowel notes. **t03 untouched** |
| **NN-06** (M) | `decode.py` — contract first (§7) | **≥ 90 % ≤50 ms, 0 slips** on t03, evaluated once |
| **ATTR-01** (S) | provenance at ingest; backfill 264 | nothing lands untagged |

**On their own timelines**, neither needed for 50 ms onsets:

- **GEN-01** — generation. §8: needs a text encoder; the vocabulary and neume
  head land here. Style personas additionally blocked on ATTR-01.
- **NN-07** — the `inclusionAI/Ling-3.0-tiny` verifier (7.89 B MoE, 131 k ctx),
  on GPU 1 in bf16. Ships if NN-06 misses its gate and the failures are ones a
  language model could catch. It needs no onset labels, which is why it scales
  when labels do not.

**Ordering rules:**

- **REPRO-01, then DECIDE-01, before NN-02.** Not to decide *whether* to build —
  that is settled — but because a model with no trustworthy yardstick cannot be
  told from one that works.
- **DECODE-01 / KEY-01 before NN-01.** The tokenizer freezes how a figure is
  written down; mark order is theirs to settle (§3).
- **CHECK-01 before NN-03.** 70 % of gaps disagree with the printed music today.
- **SYL-01 chanter-reviewed before NN-05** — and t03's labels are already known
  incomplete (§0.4).

---

## 11. Non-goals

- Replacing forced alignment. The CTC character path is the candidate generator;
  the network selects, supplies where it has none, and keeps the path in sync.
- Replacing the DTW's global structure.
- Training on machine-aligned onsets as if they were truth.
- A model that outputs a bare number.
- Rhythm normalisation — the chanter's deviation from the grid is the signal.
- Synthetic audio whose *timing* comes from our own duration model.
- Any onset entering gold without the chanter. Machine onsets are silver — and
  since gold now trains (§6.1), that rule is load-bearing in a new way: a
  machine onset admitted to gold would be trained on as truth.
- OCR on the Ioannou book: it is born-digital and `extract_book.py` reads the
  stream exactly. `baidu/Unlimited-OCR` (3.34 B) earns its place on **scanned**
  scores — a real need, but a different corpus from the one measured here.
