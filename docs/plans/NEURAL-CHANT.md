# NEURAL-CHANT — the encoder-decoder, made implementable

**Status:** ready to implement **REPRO-01 and DECIDE-01 only.** Everything after
them is authorised by what those two report, and several stages additionally
depend on open notation work (DECODE-01/KEY-01 before NN-01, CHECK-01 before
NN-03, a chanter-reviewed SYL-01 before NN-05). This is not a green light for
the full staged build — see §0.4.
Numbers below were measured on 2026-08-20 with the command that produced them,
*except* the forced-alignment baseline inherited from earlier docs, which §0.3
shows cannot currently be reproduced and must not be quoted until it is.

**Goal: every note onset within 50 ms of the chanter's pins**, over every note
event. Forced alignment leaves a selection problem, not an availability one (§0.2).

`ONSET-MODEL.md` is the *design* document — why an encoder-decoder, why a
distribution instead of a scalar, why these four base models. It is not
executable: it names no modules, no tensor shapes, no vocabulary, no commands.
This document is the executable half. Read `ONSET-MODEL.md` §4 first for the
reasoning; do not re-litigate it here.

A fresh session should be able to open this file and start at REPRO-01.

---

## 0. The target: every note onset within 50 ms

The deliverable is **note onsets within 50 ms of the chanter's pins, on every
note event.** Each note is one timeline event; none are excluded. The release
criterion is **≥ 90 % within 50 ms with zero slips** (§9).

**The encoder-decoder is a decision, not a hypothesis.** Forced alignment gives
candidate onsets, not note onsets — ~2.8 candidates per note, and 4 % accuracy
if you take its word-level output as-is (§0.2). Something has to select among
them and supply the rest, so a model is being built regardless of what the
baselines say. Generation (§8) is the stated later goal,
which is why the vocabulary in §3 is fixed as the full neume stream from day
one. REPRO-01 exists to *size* the work and give it an honest yardstick — not
to decide whether it happens.

### 0.1 Where we actually stand — measured on gold #2

`grave-orthros-t03`: 76 glyphs, **all 76 pinned by the chanter**, so the
denominator is unambiguous. The annotator's current slot times against them:

```
median |Δt| 0.714 s    mean 1.609    p90 4.560    max 5.837

  within 0.05 s   23/76   (30 %)   <- the target threshold
  within 0.10 s   25/76   (33 %)
  within 0.15 s   25/76   (33 %)
  within 0.35 s   27/76   (36 %)
```

**Every pin is a note event; the denominator is all 76.** Chanter's ruling:
*"none of t03 are melisma interiors. each note event is one timeline event."*
An empty syllable label does not mark a lesser note — it marks a note **sung on
a continuing vowel**, with its own onset like any other. Nothing is excluded.

**Read the shape, not the median.** 30 % of notes are already inside 50 ms, and
widening the tolerance sevenfold buys only four more notes. That is not a
precision problem. Per-glyph, with `.` = within 50 ms, `o` = within 500 ms,
`X` = worse:

```
glyph  0 .o.XXXXXXXXXXXXXXXXXXXXXXXXoXXoooXXXXX
glyph 38 XXXXXXXXXX............o.........XXXXoX

signed drift every 8th glyph:
 +0.0  +2.1  +4.6  +1.7  -0.3  -3.1  -0.0  +0.0  -0.0  +0.5
```

The aligner starts correct, drifts out to **+4.6 s**, comes back through zero,
overshoots to **−3.1 s**, recovers, and then holds a twenty-note run dead-on.
It is not noisy — it is **losing sync and re-acquiring it**.

### 0.2 What forced alignment can and cannot give — measured, not assumed

The chanter's diagnosis:

*"FA probably was low because repeated vowel sound extensions wouldn't get a
syllable onset, instead we would need the chant music aware to know when those
notes get hit which is a mixture of envelope, beat timing, pitch, etc — which is
how a human can tell when a certain note is hit."*

The mechanism is right: CTC emits a token when the *character* changes, so a
note re-articulated on the vowel already sounding produces no new target token.
On t03, 18 of 76 glyphs carry no fresh syllable — ordinary notes (`4|`
apostrophos mostly, some `5|`, one `6|`, 1.0–2.0 beats) that a human places from
envelope re-attack, pitch movement and where the beat says the note is due.

**But an earlier draft turned that into a "42 % structural ceiling," and that
was wrong.** `forced_align.py` aligns every *character* and only aggregates
spans into words at the very end; the 32 stored word records are a
post-processing artefact, not a property of CTC. Measured with
`tools/corpus/fa_char_coverage.py`:

```
t03: 33 words, 179 aligned characters
  distinct character-level onsets in the CTC path      211
  gold pins with SOME character onset within 0.05 s   47/76  (62 %)
  gold pins with SOME character onset within 0.10 s   64/76  (84 %)
  gold pins with SOME WORD onset within 0.05 s         3/76  ( 4 %)
```

Two conclusions, and the second reshapes the plan:

1. **The stored word-level output is nearly useless as a note-onset source —
   4 %.** Whatever the documented 0.028 s measured, it was not this.
2. **The character path already contains evidence for 62 % of notes at 50 ms.**

**Read (2) as an oracle number.** 211 candidates for 76 notes is ~2.8 per note;
it says the information is *present*, not that it can be picked out. So what FA
leaves is a **selection problem, not an availability problem** — and that is a
much better-posed job for a model than regressing time from nothing. The
decoder's task is to choose among candidate onsets using neume context, the
`beats` prior and the music cues of §4, and to supply an onset where no
candidate exists.

This also corrects the strong claim of the previous draft. The phonetic stream
has no new *target token* for a continuing-vowel note; it does not follow that
it has no *acoustic evidence*. Hidden states and CTC-logit variation may well
carry the re-attack. Stream C is required because it carries those cues
explicitly and cheaply (§4), not because stream A is provably blind.

### 0.3 What that means for the build

The distance from 30 % to a useful number is not closed by a better regressor.
It is closed by a decoder **that cannot desynchronise**: monotonic, anchored,
and able to detect that it has slipped and back up. Concretely, this reorders
the plan:

- **§7's propose/verify/backtrack decode is the primary contribution, not a
  post-process.** The Δt head exists to feed it.
- The 20 ms feature grid is already 2.5× finer than the 50 ms target, so
  **frame resolution is not the bottleneck** and no argument about encoder frame
  rates changes the outcome. Quantisation costs ±10 ms of a 50 ms budget.
- A model that improves median error while still slipping has not delivered.
  **Slip count is a first-class metric** (§9), not a diagnostic.

### 0.4 REPRO-01 — the FA baseline is not currently reproducible. Blocking.

`forced_align.py`, `FA-ONSETS.md` and `ONSET-MODEL.md` all cite **0.028 s median
against the 76 t03 pins**, and that number is load-bearing: it is the baseline
this whole plan is measured against.

**It cannot be reproduced from anything in the repository.** The stored result
(`texts/forced_align/grave-orthros__t03_.json`) holds **32 word onsets** against
76 per-glyph pins; **no word→glyph mapping is stored** and no script computes the
figure. Reconstructing the mapping from the per-glyph syllable labels fails —
18 glyphs carry no label and glyph 0 lost its first syllable, so the match walks
off by up to 35 s.

**The baseline is unverified in both directions.** It may well be right on the
32 words it covers; what does not exist is a reproducible number over the 76-pin
denominator.

**REPRO-01 (S) blocks every stage that consumes a baseline or an FA anchor —
NN-02 onward. It does not block NN-01, which waits on notation work instead.**
It must report character-level and word-level coverage separately (§0.2), and
validate the mapping rather than merely reproduce it. Write `tools/corpus/fa_eval.py`
that emits the word→glyph mapping and scores FA against the 76 pins at
0.05/0.10/0.15 s over a fixed denominator of 76, and record what it says. If FA
turns out to cover only 32 of 76 notes at high precision, that is a *better*
starting point than the plan assumed — but it must be measured, not inherited.
Until then, no number in §9 may be quoted as a baseline.

---

## 1. Ground truth inventory — what actually exists today

| asset | count | where | notes |
|---|---|---|---|
| chanter-verified onsets | **335** | `datasets/grave-orthros-t03-gold/pins.json` (76), `datasets/eothinon-11-workdir/note_times.json` (259) | the only gold. **Nothing else may be called an onset label.** |
| in-progress pins | 37 | `datasets/exports/grave-orthros-s01-.../pins.json` | s01 is half done; will grow |
| note units in the book | **116,043** | `score_degrees.units_for(1,0,0,999,999,10**9)` | score-only, needs no audio — see NN-03c |
| distinct unit keys | 123 | same | over 16 distinct bases |
| cadence martyrias | 3,886 | `u['mart_cad']` | free constraints, no labelling cost |
| fthoras | 642 | `u['fthora']` | genus/degree resets |
| audio | **37.4 h / 264 recordings** | `/mnt/data/chant-corpus/corpus.json` | all one singer (see ATTR-01) |
| span pieces | 47 | `tools/chant-reel/annotator/data/grave-orthros-s*` | chanter-cut, **audio bounds locked forever** |
| hymn pieces | 173 | same dir, `*-t*` | machine-cut |
| annotator note slots | 19,868 | across 220 pieces | 4,050 carry no fresh syllable (§0.2) |

**The label scarcity is the design constraint.** 335 verified onsets is not a
number you train 80 M parameters on from scratch. §4 is built around spending
that budget only where nothing else can pay.

### 1.1 The martyria constraint — measured, and it is not clean

The chanter proposed using martyrias as checks in a constraint-propagation /
wavefunction-collapse solver. Measured over the 47 chanter-ranged spans:

```
$ tools/corpus/martyria_check.py

57 gaps between consecutive cadence martyrias   (deduped -- see below)
  gap length            median 21 units
  ambiguous bars/gap    median  5 units   (p90 13)  -> 2^5..2^13, trivially searchable

  17 gaps already satisfy their two martyrias
  40 gaps VIOLATE the constraint                    (70 %)
     disagreement:  -1 in 14 gaps,  -2 in 13,  +1 in 5, rest scattered
     33 "sum too LOW"  (needs an ison promoted to an oligon) -- 31 have room
      7 "sum too HIGH" (needs an oligon demoted to an ison)  --  6 have room
```

`martyria_check.py` keys on the gap, not on the span that found it — the 47
ranges overlap at their edges, so a naive pass double-counts.

Two consequences, both important:

1. **The constraint is real and cheap to compute** — 3,886 checkpoints
   corpus-wide, zero labelling cost. It enters the decode (§7) and the silver
   filter (NN-03) **report-only until Gate C**, and becomes a hard gate only
   after CHECK-01 passes and clusters 26/29 are chanter-reviewed.
2. **It is currently violated in 70 % of gaps, asymmetrically.** That is a
   systematic legend gap on the "not climbing enough" side, not solver-shaped
   noise. A solver that collapses each gap independently would paper over it
   with a different local excuse every time. **CHECK-01 (staged in §10) fixes the rule
   first; the solver ships after.**

A collapsed degree stream is **silver**, never gold. Same standing rule as
onsets: nothing enters gold without the chanter.

---

## 2. Hardware and environment — the real budget

```
2 x RTX 3090, 24 GB each.  Both currently held by the qwen38 tenant.
```

Lease them, do not squat:

```bash
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh lease ml neural-chant "decoder training" 6h
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh renew 4h        # extends safely
/mnt/data/code/infra/platform/qwen38/gpu-swap.sh release         # ALWAYS, when done
```

The lease auto-restores at expiry via a systemd user timer, so a forgotten
release costs hours rather than days — but release anyway.

Environment (already provisioned, do not build a new one):

```
/mnt/data/chant-corpus/venv/bin/python
  python 3.14.7 · torch 2.11.0+cu130 (cuda available) · transformers 5.15.0
  torchaudio 2.11.0 · numpy 2.4.1 · librosa 1.0.0 · soundfile 0.14.0
HF cache: ~/.cache/huggingface/hub  (5.3 G; xlsr-53-greek and faster-whisper present)
```

**48 GB total is the constraint that shapes the whole build.** It is why NN-02
exists: the frozen encoder's features are computed **once, to disk**, and never
loaded again during training. 37.4 h at 20 ms = 6.73 M frames; at 1024 dims in
fp16 that is **13.8 GB** on disk and it decouples every later stage from the
encoder entirely. Training the decoder then needs one card, leaving the other
free to serve the verifier.

Allocation:

| GPU | during NN-02 | during NN-05 (train) | during NN-06/07 (decode) |
|---|---|---|---|
| 0 | frame encoder | decoder training | decoder inference |
| 1 | second stream | free / eval | Ling-3.0-tiny verifier (bf16, ~16 GB) |

Never plan on training and serving a 7.89 B verifier on the same card. It will
fit right up until a batch spikes, and then it will not.

---

## 3. NN-01 — the vocabulary. Free today, unrecoverable later

`ONSET-MODEL.md` §6 states the one commitment that must be made early: the
decoder vocabulary is the **full neume stream** from the start, because a
decoder trained to emit only intervals can never learn to emit a psifiston.
Concretely:

**Factored, not flat.** There are 123 distinct unit keys corpus-wide. A flat
123-way vocabulary is tempting and wrong: it cannot emit a base/mark
combination it never saw, which kills the generation direction and makes the
long tail unlearnable. Emit each unit as a short **factored sequence**:

```
UNIT_START
  BASE_<id>                 # 16 observed bases, reserve 64
  MARK_<id> ...             # zero or more, in canonical (sorted) order
  DUR_<klasma|apli1..3|dot1..2>
  TEMPO_<gorgon|digorgon|trigorgon|argon|chiasma_*>
  [FTHORA_<genus>_<degree>]
  [MART_<degree>_<cad|open>]
UNIT_END
```

Plus structural tokens: `BARLINE`, `REST`, `LINE_BREAK`, `PAGE_BREAK`,
`SPAN_START`, `SPAN_END`, `BOS`, `EOS`, `PAD`, and the conditioning prefix
tokens of §5.4.

Total vocabulary lands around **300 tokens**. Small, which is the point.

Rules that must hold, enforced by tests:

- **Round-trip.** `decode(encode(u)) == u` for all 116,043 units. This is the
  NN-01 gate; anything less and errors get baked into weights where they are
  far more expensive to find than in a JSON file.
- **Canonical mark order**, so the same figure is always the same token
  sequence. Sort by mark id **only once DECODE-01/KEY-01 confirm that position
  and geometry carry no meaning a sorted id-list would destroy** (§10). If they
  do, order by the confirmed semantic role instead. Whichever is chosen, record
  in `vocab_v1.json` exactly which distinctions the vocabulary drops.
- **Derived quantities are NOT tokens.** `iv` (the interval) and `beats` are
  *computed* from the figure by `legend_canon` / `beats_seq`. Emitting them as
  tokens would let the decoder contradict the legend. They enter as *features*
  on the neume-side embedding (§5.2), not as vocabulary.
- **Unknown base/mark ids get a real token**, `BASE_UNK` / `MARK_UNK`, not a
  crash. New books will introduce glyphs.

Deliverable: `tools/neural/vocab.py` — `encode_units(units) -> List[int]`,
`decode_tokens(ids) -> List[unit]`, `VOCAB` frozen and versioned in
`tools/neural/vocab_v1.json`. **Never mutate a shipped vocab file**; add v2.

---

## 4. NN-02 — frozen encoder features, computed once

Two audio streams, per `ONSET-MODEL.md` §4.1.1.

**Stream A (primary): `jonatasgrosman/wav2vec2-large-xlsr-53-greek`, frozen.**
20 ms frames, 1024 dims. It is the encoder every number in this project was
measured on, and its Greek character head is what makes FA possible at all.
Take the hidden states of the **last transformer layer** and, separately, the
**CTC logits** (41 tokens) — the logits are cheap and carry the "is a new
character starting here" evidence explicitly.

**Stream C (REQUIRED, and cheap): pitch, envelope, and their derivatives.**
§0.2 is an argument about what evidence exists, not about model capacity: for a
note re-articulated on a sounding vowel the phonetic stream carries **no
signal**, and no amount of cross-attention recovers information the encoder
never represented. The cues a chanter actually uses have to be supplied
directly.

They already exist, per workdir, at **10 ms — finer than the encoder grid and
5× finer than the 50 ms target**:

```
  cents_track.npy   (5390,) float64   f0 in cents      10.0 ms/frame
  rms_track.npy     (5390,) float64   amplitude        10.0 ms/frame
```

**Encoder-input contract**, same footing as stream B: the six channels are
resampled to the 20 ms grid, layer-normed, projected by a linear map to
`d_model`, and **concatenated with A and B along the feature axis** before the
audio self-attention stack. They are audio-side, frame-aligned inputs — not
neume-side features — so local cross-attention addresses them on the same index
as A. Channels:

| ch | definition | source |
|---|---|---|
| `f0_cents` | pitch in cents, NaN where unvoiced → 0 with the mask bit | `cents_track.npy`, 10 ms |
| `df0` | first difference of `f0_cents`, masked across unvoiced gaps | derived |
| `rms` | amplitude | `rms_track.npy`, 10 ms |
| `drms` | first difference — envelope re-attack, *the* cue for a re-articulation | derived |
| `flux` | half-wave-rectified spectral flux, **new: computed in `features.py`** — STFT n_fft 1024, hop 320 @ 16 kHz (aligning it to the 20 ms grid by construction), magnitude, `sum(max(0, |X_t| - |X_{t-1}|))`, per-piece median-normalised | new |
| `voiced` | 1 where the tracker reports voicing, else 0 | `cents_track.npy` |

Downsampling 10 ms → 20 ms **takes the max of `drms` and `flux` over each pair**
and the mean of the rest: an onset is a peak, and averaging a two-frame window
is how you lose it.

**This stream is not an ablation.** Stream A can be ablated; B is a question;
C is load-bearing, because it is the only stream that sees 24 % of the notes.
If an experiment shows C is unnecessary, something is wrong with the
experiment — check for label leakage before believing it.

**Stream B (secondary): `MiniMaxAI/MiniMax-Music3` `condition_encoder`.** 40 ms
frames (`input_hop_length 960` @ 24 kHz = 25 Hz). It is a *second stream, not a
replacement* — a 40 ms grid cannot resolve a 28 ms onset, and a condition
encoder feeding an RVQ codec discards exactly the attack detail an onset is.
What it brings is harmonic and timbral context, where 40 ms is ample.
**Upsample ×2 by linear interpolation to the 20 ms grid** and concatenate.

Cache layout, one `.npz` per recording:

```
/mnt/data/chant-corpus/features/<recording_id>.npz
   a_hidden  float16 [T, 1024]     stream A last hidden
   a_logits  float16 [T, 41]       stream A CTC logits
   b_cond    float16 [T, D_b]      stream B, already upsampled to the 20 ms grid
   c_music   float16 [T, 6]        stream C: f0_cents, df0, rms, drms, flux, voiced
   t0        float32               start offset of frame 0, seconds
   sr, hop   int                   16000, 320
```

`13.8 GB` for stream A over the full 37.4 h; budget ~25 GB with stream B.

Every cache file also stores **provenance**: the model repo id and revision
hash, the code revision that wrote it, the sha256 of the source audio, and the
frame-origin convention (`t = t0 + i*hop/sr`, frame *i* covers `[t, t+hop/sr)`).
A feature cache whose producer is unidentifiable is a silent correctness hazard
the moment the encoder is upgraded.

Gates:
- **A frame's timestamp must be exact.** `t = t0 + i*0.02`. Assert against a
  known FA output on t03: re-deriving FA onsets from cached features must
  reproduce `forced_align.py`'s timestamps to < 1 ms.
- **fp16 must not move the answer.** Re-run the gold #2 FA evaluation from the
  cache; it must reproduce **REPRO-01's numbers exactly**, whatever they turn
  out to be. Do not hard-code 0.028 s here — §0.4 invalidated it.

Deliverable: `tools/neural/features.py --recording <id>` and `--all`.
Run it under an `ml` lease; it is the only stage that needs both cards.

**Ablation, not a decision.** Whether stream *B* helps is an open question
(`ONSET-MODEL.md` §4.1 explicitly refuses to pre-decide it). Cache it, train
with and without, report both on the same held-out pins. If it does not help,
drop it — a smaller model that ties is the better model.

---

## 5. NN-04 — the model

Layer counts are `N`/`M`, fixed by the §5.4 learning curve — **the starting
model is N=2, M=3**; the ceiling the data plausibly supports is N=4, M=6.

```
                         ┌──────────────────────────────────────┐
  A+B+C frames  ────────►│ N x local self-attn, window ±64 fr    │  20 ms grid
  (cached, frozen)       │ (±1.28 s — onset evidence IS local)   │
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
                         │   cross-attn GLOBAL -> pooled summary │   pointer-centred)
                         └───────────────┬──────────────────────┘
                                         │
                                    Δt head: softmax over 201 bins
```

### 5.1 Hybrid attention, concretely

This is the chanter's "hybrid attention", made specific:

- **Audio self-attention is windowed**, ±64 frames. Onset evidence is local to
  tens of milliseconds; full quadratic attention over a 300 s piece (15,000
  frames) is 225 M pairs per layer and buys nothing.
- **Neume self-attention is full and causal.** Sequences are ≤ ~2,000 units per
  hymn; quadratic is affordable and melisma context is genuinely long-range.
- **Cross-attention is two paths.** LOCAL attends to ±150 frames (3 s) around a
  running alignment pointer — the previous accepted onset. GLOBAL attends to the
  0.5 s-pooled summary of the entire piece, which is 600 vectors for a 300 s
  track. Local carries the onset evidence; global carries "where am I in this
  hymn", which is what stops a slip becoming permanent.

The pointer is not learned from scratch: it is initialised at the previous
confirmed onset and advanced by the `beats_seq` prediction (§5.2). The model
learns the *residual*.

### 5.2 The neume-side input

Per the chanter's framing — *"the previous syllable AND the syllable of the note
it is looking for the onset for as well as a sliver of audio time in a window"*
— extended with what the duration model already knows:

| feature | source | why |
|---|---|---|
| unit tokens | NN-01 | the figure itself |
| `iv` | `legend_canon` | the melodic step, as a *feature* not a token (§3) |
| `beats` | `beats_seq` | **the arithmetic prediction, entering as a prior** |
| melisma index / length | syllabification | which of the twelve notes on this vowel |
| previous + target syllable | SYL-01 | the chanter's query unit |
| mode / genre / book / incipit | directory + hymn name | **as plain text**, so an unseen genre degrades instead of failing |
| FA candidate onsets in the window | `forced_align` character path | §0.2 — the decoder *selects* among these |
| syllable-present mask bit | SYL-01 | absent syllable must not look like a real zero |

f0, RMS, Δ and flux are **audio-side** and enter through stream C (§4), not
here; they are frame-aligned time series, not per-unit features.

Note what the table now says about coverage: the syllable features are
**absent** for the 24 % of notes sung on a continuing vowel, and that is exactly
where f0/RMS have to carry the decision. Do not let a missing syllable be
encoded as a zero that looks like a real value — it needs its own mask bit.

The `beats` prior is the single most important input. The network is not
learning to time chant from nothing; it is learning where the chanter *departs*
from the beat grid — and that departure is the signal, not noise
(`ONSET-MODEL.md` §9).

### 5.3 The Δt head — a distribution, never a scalar

Δt from the previous confirmed onset, quantised to **20 ms bins over [0, 4 s]**
= 200 bins plus one overflow bin. Softmax over 201.

Point regression is disqualified, and the reason is concrete: the model must be
able to say *"0.31 s, or possibly 0.62 s if a note was skipped"* and let the
search in §6 arbitrate. A regressor averages those into 0.47 s, which is wrong
in a way that no amount of training fixes.

Loss: cross-entropy with **label smoothing onto ±1 adjacent bins**, because the
onset labels have their own human jitter and a 20 ms grid is finer than a
chanter's pin is repeatable.

### 5.4 Size — start small, and let a learning curve choose

**Do not start at 40 M.** No measurement in this project justifies that number;
it was picked to sound reasonable. Start at the smallest model that can test the
hypothesis — `d_model 192`, 2 audio layers, 3 decoder layers, ~4 M — and grow
only along a measured learning curve on held-out pins. 40 M is the *ceiling* the
data plausibly supports, not the starting point, and if 4 M closes the sync
problem then the extra parameters are pure overfitting surface.

Report the curve (4 M / 12 M / 40 M) in the NN-05 result. A tie means ship the
small one.

---

### 5.5 The training and decoding contract — write it before `model.py`

NN-04's gate is a *document*, not a forward pass. Specify on paper, and commit
it, before any tensor is allocated:

- **Target definition.** Δt from *what* — the previous note's onset, or the
  previous *accepted* onset? They differ during teacher forcing and at decode,
  and getting this wrong produces a model that trains well and decodes badly.
- **Teacher forcing.** Trained on gold-previous, decoded on own-previous, is the
  classic exposure-mismatch trap for an autoregressive timing model. Schedule
  sampling or a mixed regime, decided up front.
- **Masks.** Exactly which audio frames the local cross-attention may see at
  step *n*, and how the pointer moves when a step is rejected.
- **Overflow.** What bin 200 (> 4 s) means at decode, and what the decoder does
  with it — a rest, a slip, or an abstention.
- **Anchors at train time.** FA onsets are inputs at decode (§7). If they are
  not also inputs at train time the model never learns to use them.

## 6. NN-03 — the data builder, and how the label budget is spent

Three sources, three very different trust levels. **They must never be mixed
into one undifferentiated pile**, and every example carries a `provenance`
field naming which it is.

### 6.1 NN-03a — gold (335 labels, two folds, never pooled)

The 76 t03 pins and the 259 eothinon-11 note times — **reported separately, per
§9**; they differ in script, language and engraving, and pooling them hides
exactly the transfer question worth asking. **Held out, not trained on, until
the very last stage.** These are the only instrument that has ever
detected a real improvement in this project. Spending them as training data
would leave nothing to measure with.

### 6.2 NN-03b — silver from forced alignment (~15,800 examples)

Every syllable-initial note across the 220 pieces, timed by
`forced_align_batch.py`. This is 80 % of all notes. Whether it is *good* silver is precisely what
REPRO-01 measures; until then it is silver of unknown quality, and NN-03 must
not start before that number exists.

**Lane-specific admission — melos and parallagi are not the same problem.**
A *melos* track sings the hymn text, so FA on the canonical GLT text applies
directly. A *parallagi* track sings **degree names** (νη πα βου γα δι κε ζω),
not the hymn text, so the canonical text is the wrong target entirely; FA must
be run against the degree-name stream from `score_degrees.as_text()`. And that
stream is only as good as the legend — score-derived degree identification hit
**2 of 23**, i.e. chance, so parallagi silver is admitted **only** where the
parallagi/melos pairing is known by position (23/23 reliable) and the degree
stream survives CHECK-01. Blanket-aligning all 220 pieces with one rule would
pour the worse lane into the better one.

Filters, all mandatory:
- drop any piece whose FA CTC path fails `name_check.py` (**never gate on CTC
  loss** — the confidence gate rated mode2 15/15 when 5 of 15 were right)
- drop any martyria gap that fails CHECK-01
- drop machine-cut hymn boundaries that `ONSET-EVENTS.md` flagged; the 47
  chanter-cut spans are trusted, the 173 machine cuts are not

**Notes on a continuing vowel get no silver label**, because FA cannot place
them (§0.2) — on t03 that is 44 of 76 note events left unlabelled by FA even
though all 76 are pinned. Do not invent labels for them by interpolating, and
above all do not manufacture them from our own duration model
(`ONSET-MODEL.md` §9): that would train the network to reproduce the arithmetic
it is supposed to correct.

This is the central asymmetry of the data. **The gold pins are the only
supervision that covers the hard class**, which is why §9 spends them once and
why NN-05's gate names that class explicitly.

### 6.3 NN-03c — score-only pretraining (116,043 units, zero labels)

**This is what makes a 40 M model affordable on 335 labels.**

The decoder's neume side — which compounds follow which, cadence formulae,
melisma shapes, what a psifiston does — can be learned as a plain autoregressive
LM over the neume stream, with **no audio and no onset labels at all**. The full
book is 116,043 units, roughly 500 k factored tokens.

Be honest about the size: 500 k tokens teaches local n-gram structure and
cadence formulae. It does not teach a deep model of style. That is sufficient,
because the onset labels then only have to train the **cross-attention and the
Δt head** — not the whole decoder.

Stage it: pretrain neume-LM → freeze nothing, but warm-start → train alignment
on silver → evaluate on gold. Report the ablation *without* NN-03c so the claim
is measured rather than assumed.

Deliverable: `tools/neural/dataset.py`, emitting JSONL with an explicit
`provenance` in `{gold, silver_fa, score_only}` on every example.

---

## 7. NN-06 — decode: propose, verify, backtrack

Straight from the chanter's description, made concrete, and unchanged in spirit
from `ONSET-MODEL.md` §5:

1. **Propose.** Emit the next *k* onsets (k = 4–8) in one pass.
2. **Verify.** Accept the longest prefix that survives all of:
   - monotonic in time
   - within the `beats_seq` tolerance
   - **does not cross an FA anchor** (§0: syllable-initial onsets are fixed)
   - satisfies CHECK-01 at the next cadence martyria — **but only because beam
     branches may skip or repeat score units.** This needs stating plainly: a
     martyria constrains a sum of *intervals*, which is invariant to timing, so
     against a fixed known neume sequence every timing hypothesis yields the
     identical checksum and it discriminates nothing. It earns its place only
     because the failure in §0.1 *is* skip/repeat — a path that desynchronises
     has effectively consumed the wrong number of units against the audio, and
     that a checksum does see. Branch semantics therefore include unit
     insertion and deletion, or CHECK-01 must be dropped from the verifier.
     Free, label-less.
     **Report-only until Gate C.** `CHANT-MODEL-ACCURACY.md` requires the
     checksum stay advisory until clusters 26 and 29 have chanter review, so
     it does not become a confident wrong oracle; §1.1's 70 % violation rate is
     exactly that risk. Log what it would have rejected; do not reject yet.
3. **Backtrack.** Keep a beam of anchors. When accepted-prefix length collapses
   or predictive entropy spikes, roll back to the last anchor and take the next
   branch.

Anchor trust order, strict: **chanter pins > FA syllable onsets >
martyria-satisfied cadences > high-confidence model onsets.**

This directly attacks the failure gold #2 exposes: today a slip is permanent
because nothing detects it. Here, rising error *is* the detector.

### 7.1 NN-07 — the LLM verifier

`inclusionAI/Ling-3.0-tiny` (7.89 B MoE, 8 of 128 experts active, 131 k context)
takes the verifier slot. It needs **no onset labels** — it accepts or rejects a
proposed run — which is why it scales when labels do not. Its 131 k context
holds a whole hymn's neume stream, which §8's generation direction wants.

It is emphatically **not** the alignment decoder. A 7.89 B model trained on 335
labels memorises them.

Serve it on GPU 1 in bf16 (~16 GB) behind a local endpoint; the decoder never
loads it in-process.

---

## 8. GEN-01 — generation, and the one thing it demands today

**A stated goal of this project**, on its own timeline (§10). Recorded here
because one dependency is cheap now and impossible to retrofit.

**What this plan's architecture does and does not give.** The model in §5
*consumes* neume tokens and emits only a Δt distribution; it has no neume output
head and no text encoder, so "the same weights run backwards" is false as
written. What carries over is the decoder stack and its learned neume-side
representation. GEN-01 must add two things: a neume-token output head trained
with an LM objective (NN-03c already trains exactly that, so it is not new
work), and a text/target-phrase encoder to condition on. Budget it as a real
increment, not a free reinterpretation.

What *is* free today, and unrecoverable later, is the vocabulary: because §3
emits the full factored neume stream — compounds, qualitative marks, duration —
a future generative head can emit a psifiston. A decoder trained on an interval
alphabet never can.

**Style personas are blocked, and not by the model.** `corpus.json` carries only
`path/name/dur_s/size`: no singer, no school, no date, no provenance. All 264
recordings are one singer. Every persona would collapse to one point in latent
space because there *is* one point.

**ATTR-01 (S) — do it before the next ingest.** Add singer / school / place /
date / source-URL / attributed-by at ingest; backfill the existing 264 as
`vasilikos`. Retrofitting attribution onto audio already in the tree costs far
more than capturing it at the door. Distinct style clusters need meaningful
hours *per* style — months of the weekly-recording flywheel — but the field has
to exist from the first new file or those months are wasted.

---

## 9. Evaluation — the protocol, non-negotiable

**Primary metric: `frac(|Δt| ≤ 0.05 s)` over a fixed denominator of every
pinned note — all 76 on t03, all 259 on eothinon-11.** An unmatched note is a miss, not an exclusion. Medians are
reported but never gate — §0.1 is the demonstration of why: a median of 0.714 s
and a p90 of 4.56 s describe the same aligner that is dead-on for twenty
consecutive notes.

**Secondary metric, equally binding: slip count.** Number of maximal runs where
signed drift leaves ±0.05 s and does not return within 3 notes. On t03 today
that is 4 excursions reaching +4.6 s, −3.1 s and back. A model that halves
median error while slipping the same number of times has not delivered.

**Report per piece, never pooled.** `CHANT-MODEL-ACCURACY.md` and both gold
READMEs already record that the two gold sets must not be pooled naively and
that *piece is the only honest fold*: t03 is Greek from the Ioannou vector
book, eothinon-11 is English from Karam EZ fonts, and they share neither script
nor engraving. An earlier draft of this plan pooled them into "335 gold"; that
was wrong and is corrected here. Report:

| fold | notes | what it tests |
|---|---|---|
| `t03` (Greek, Ioannou) | 76 | the corpus everything else is measured on |
| `eothinon-11` (English, Karam) | 259 | cross-script, cross-engraving transfer |
| `s01…` (as the chanter pins them) | growing | **final test set — untouched** |

Report alongside it the split by **evidence class** — notes with an FA anchor
versus notes on a continuing vowel — because a system can look fine overall
while failing the whole class §0.2 is about. This is a diagnostic breakdown, not
a change of denominator.

**The intermediate gates run on a silver dev fold**, built by holding out whole
source recordings from NN-03b and scoring against their FA character-path
anchors. It is a weaker instrument than pins — that is the price of not
spending them — and it is why NN-05's bar (60 %) sits below NN-06's (90 %).

**Development folds are silver-only.** Stream B, score-only pretraining, and the
4 M/12 M/40 M curve must all be chosen on grouped silver folds, never on the
gold pins. Two gold pieces cannot absorb repeated model selection —
`CHANT-MODEL-ACCURACY.md` already records that two pieces cannot support a
defensible split — and a number tuned on them stops being an estimate of
anything. Gold is touched **once**, for the final claim, with no fine-tuning.

Baselines, once REPRO-01 has produced them honestly:

| system | ≤ 0.05 s | median | slips |
|---|---|---|---|
| annotator today (t03, all 76) | **30 %** | 0.714 s | 4 |
| FA word onsets (t03) | **4 %** | — | — |
| FA character path, oracle pick | **62 %** (upper bound, §0.2) | — | — |
| target | **≥ 90 % of all notes** | — | **0** |

Disqualified metrics, both with the reason on record:

- **Movement agreement.** Reads 1.00 on t03 while median onset error is 0.485 s.
  It grades the aligner against its own decode.
- **CTC loss as a correctness signal.** The confidence gate rated mode2 15/15
  when 5 of 15 were right. Score with `name_check.py`.

**Timebase manifests, fixed before scoring.** eothinon-11 needs a known 1.98 s
offset — a stale time base once turned 63 % recall into a reported 10 %. Each
fold carries a manifest with the audio sha256, the offset, the rate, and where
each came from. **The transform is never fitted against model predictions**;
that is how a scoring bug becomes an accuracy claim.

Synthetic data gates nothing. Only real held-out pins do.

---

## 10. Staging

| id | work | gate |
|---|---|---|
| **REPRO-01** (S) | `fa_eval.py`: character- and word-level FA scored on all 76 t03 pins, mapping validated | a number exists that a second run reproduces. **Blocks NN-02 onward** |
| **DECIDE-01** (S) | read REPRO-01 and characterise the gap: FA coverage, within-50 ms rate, misses, failure categories, and the split by evidence class | a sized brief for NN-02..NN-06 — which notes the model must own, and what it must beat on each class |
| **NN-00** (S) | honest arithmetic baseline: `beats_seq` + one fitted tempo, same protocol | reproduced by a script, not by hand |
| **CHECK-01** (M) | find the systematic −1/−2 in the 40 violated martyria gaps | `martyria_check.py` exits 0: violated < 8 of 57 |
| **NN-01** (S) | `vocab.py`, factored neume tokenizer | round-trip exact on all 116,043 units |
| **NN-02** (M) | `features.py`, frozen feature cache + provenance (§4) | FA re-derived from cache matches REPRO-01 exactly |
| **NN-03** (M) | `dataset.py`; lane-specific silver, provenance + `source_recording_id` on every example | no gold **source recording** in any train split — including derived cuts, overlapping excerpts and duplicates under other piece ids. Split by recording, asserted in code |
| **NN-04** (M) | `model.py` at 4 M, hybrid attention + Δt head | forward/backward runs; contract doc written first (§5.5) |
| **NN-05** (L) | train; learning curve 4 M / 12 M / 40 M | **≥ 60 % within 50 ms on the silver dev fold, slips < 2**, no collapse on continuing-vowel notes. **Gold is not touched here** — see §9 |
| **NN-06** (M) | `decode.py`, propose/verify/backtrack — **contract first**, as §5.5: beam state and width, score equation, anchor-crossing semantics, beat tolerance, entropy threshold, rollback state, termination, and what "high confidence" numerically means. Tuned on silver dev folds only | **≥ 90 % of all notes within 50 ms, 0 slips** — the actual deliverable |
| **ATTR-01** (S) | provenance schema at ingest; backfill 264 as `vasilikos` | nothing lands untagged |

**On their own timelines**, neither needed to put onsets within 50 ms:

- **NN-07 — the Ling-3.0-tiny verifier.** Ships if NN-06 misses its gate and the
  failures are ones a language model could plausibly catch.
- **GEN-01 — generation. A stated goal of this project, on its own timeline.**
  The same encoder-decoder run backwards emits neumes, which is why §3's
  vocabulary is the full neume stream and not an interval alphabet — that
  decision is made here, now, and is unrecoverable later. What is deferred is
  only the *work*, and only because style personas are blocked on ATTR-01: all
  264 recordings are one singer, so every persona collapses to one point.

**Ordering rules that must not be broken:**

- **REPRO-01, then DECIDE-01, before the build.** Not to decide *whether* to
  build — that is settled — but because a model with no trustworthy yardstick
  cannot be told from one that works. Both are small; neither blocks NN-01.
- **REPRO-01 must validate the mapping, not just reproduce it.** Reproducibility
  alone will faithfully reproduce a *wrong* word→glyph mapping. Acceptance
  requires a chanter-checked sample of the mapping, explicit handling of
  unmatched words, and word-initial and syllable-initial metrics reported
  separately.
- **Notation prerequisites before NN-01.** The tokenizer freezes how a figure is
  written down; DECODE-01 (role-driven base selection) and KEY-01 (mark position
  and geometry) are still open, and sorting marks by id would discard a
  distinction those workstreams may prove load-bearing. Confirm both, or
  explicitly record which distinctions the vocabulary is choosing to drop.
- **CHECK-01 before NN-03.** 70 % of martyria gaps disagree with the printed
  music today; using that as a silver filter would filter on a broken rule.
- **SYL-01 chanter-reviewed before NN-05** — and note §0.4: t03's syllable
  labels are already known to be incomplete (18 of 76 glyphs unlabelled).

---

## 11. Non-goals

- Replacing forced alignment. The CTC character path is the candidate
  generator; the network selects among its candidates, supplies onsets where it
  has none, and keeps the path from desynchronising between anchors (§0.2).
- Replacing the DTW's global structure. Passage-level layout stays with the
  anchored aligner and the martyria checksum.
- Training on machine-aligned onsets as if they were truth.
- A model that outputs a bare number.
- Rhythm normalisation. The chanter's expressive deviation from the grid is the
  signal.
- Synthetic audio whose *timing* comes from our own duration model.
- Any onset entering gold without the chanter. Machine onsets are silver,
  permanently.
- OCR on the Ioannou book. It is born-digital; `extract_book.py` reads the neume
  stream out of the text layer exactly. `baidu/Unlimited-OCR` (3.34 B) earns its
  place on **scanned and photographed** scores — a real and growing need, but a
  different corpus from the one every number here was measured on.
