# NEURAL-CHANT — the encoder-decoder, made implementable

**Status:** ready to implement **REPRO-01 and DECIDE-01 only.** Everything after
them is authorised by what those two report, and several stages additionally
depend on open notation work (DECODE-01/KEY-01 before NN-01, CHECK-01 before
NN-03, a chanter-reviewed SYL-01 before NN-05). This is not a green light for
the full staged build — see §0.3.
Numbers below were measured on 2026-08-20 with the command that produced them,
*except* the forced-alignment baseline inherited from earlier docs, which §0.3
shows cannot currently be reproduced and must not be quoted until it is.

**Goal: every note onset within 50 ms of the chanter's pins.** Melisma interiors
are deferred to MEL-01 (§10).

`ONSET-MODEL.md` is the *design* document — why an encoder-decoder, why a
distribution instead of a scalar, why these four base models. It is not
executable: it names no modules, no tensor shapes, no vocabulary, no commands.
This document is the executable half. Read `ONSET-MODEL.md` §4 first for the
reasoning; do not re-litigate it here.

A fresh session should be able to open this file and start at REPRO-01.

---

## 0. The target: every note onset within 50 ms

The deliverable is **note onsets within 50 ms of the chanter's pins**. The
release criterion is **≥ 90 % of eligible notes with zero slips** (§9); "every
note" is the aspiration, 90 %/0-slips is what NN-06 is graded on. Melisma interiors are explicitly **out of scope for this plan** and come
much later; they appear as MEL-01 in §10 so the vocabulary decision stays
compatible with them, and nowhere else.

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

**The eligible denominator, since interiors are deferred.** The chanter pinned
**every** score unit in t03, interiors included — 58 syllable-initial and 18
melisma-interior. Excluding the interiors barely moves the headline:

```
  all 76 pins                    23/76  within 50 ms   (30 %)
  eligible (syllable-initial)    16/58  within 50 ms   (28 %)   <- the gate
  interior (deferred, MEL-01)     7/18  within 50 ms   (39 %)
```

Interiors scoring *better* than syllable-initial is not noise — it is more
evidence for §0.2. An interior note sits milliseconds from its neighbours, so
wherever the region is in sync it comes along for free.

Every gold note therefore carries `syllable_initial: true|false`, the gate is
computed over the eligible subset, and the excluded interior count is reported
per piece. No metric in this plan may be quoted without saying which.

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

### 0.2 What that means for the build

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

### 0.3 REPRO-01 — the FA baseline is not currently reproducible. Blocking.

`forced_align.py`, `FA-ONSETS.md` and `ONSET-MODEL.md` all cite **0.028 s median
against the 76 t03 pins**, and that number is load-bearing: it is the baseline
this whole plan is measured against.

**It cannot be reproduced from anything in the repository.** Attempted
2026-08-20:

- The stored FA result (`texts/forced_align/grave-orthros__t03_.json`) contains
  **32 word onsets**, not 76 note onsets. The pins are per glyph.
- **No word→glyph mapping is stored anywhere**, and no script in `tools/`
  computes the 0.028 s figure. There is nothing to re-run.
- Reconstructing the mapping from the chanter's per-glyph syllable labels fails:
  18 of 76 glyphs carry no label at all and glyph 0 is missing its first
  syllable, so a letter-stream match walks off and mismatches by up to 35 s.
- Aligning the syllable labels directly as FA tokens (71 tokens) gives
  **median 0.076 s, 37 % within 50 ms** — but that is confounded by the same
  incomplete labels and is *not* evidence that the documented number is wrong.

So the honest position is: **the FA baseline is unverified, in both
directions.** It may well be right on the 32 words it covers; what does not
exist is a reproducible number over the 76-pin denominator this plan needs.

**REPRO-01 (S) blocks every other stage.** Write `tools/corpus/fa_eval.py`
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
| annotator note slots | 19,868 | across 220 pieces | the melisma numbers above |

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

The 47 chanter ranges overlap at their edges, so the same martyria pair falls
inside two spans; the first pass counted 103 gaps and 71 violations by counting
some of them twice. The ratio was unchanged at ~70 %, the counts were not.
`martyria_check.py` keys on the gap, not on the span that found it.

Two consequences, both important:

1. **The constraint is real and cheap to enforce** — 3,886 checkpoints
   corpus-wide, zero labelling cost. It goes into the decode (§7) as a hard
   gate and into the data builder (NN-03) as a filter on silver.
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
  sequence. Sort by mark id.
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
  out to be. Do not hard-code 0.028 s here — §0.3 invalidated it.

Deliverable: `tools/neural/features.py --recording <id>` and `--all`.
Run it under an `ml` lease; it is the only stage that needs both cards.

**Ablation, not a decision.** Whether stream B helps is an open question
(`ONSET-MODEL.md` §4.1 explicitly refuses to pre-decide it). Cache it, train
with and without, report both on the same held-out pins. If it does not help,
drop it — a smaller model that ties is the better model.

---

## 5. NN-04 — the model

```
                         ┌──────────────────────────────────────┐
  audio frames  ────────►│ 4 x local self-attn, window ±64 fr    │  20 ms grid
  (cached, frozen)       │ (±1.28 s — onset evidence IS local)   │
                         └───────────────┬──────────────────────┘
                                         │
                         ┌───────────────┴──────────────────────┐
                         │ mean-pool /25  ->  0.5 s summary      │  global memory
                         └───────────────┬──────────────────────┘
                                         │
  neume stream ─────────►┌───────────────┴──────────────────────┐
  (NN-01 tokens)         │ 6 x decoder block:                   │
  + iv, beats, melisma   │   causal self-attn over neumes (full) │
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

The 4,050 melisma-interior notes have **no silver label and no gold label**.
That is why MEL-01 is deferred (§10) rather than scheduled: it has no supervised
signal at all today. Do not invent one by interpolating, and above all do not
manufacture labels from our own duration model (`ONSET-MODEL.md` §9). For this
plan they are simply out of scope — the 50 ms target is measured on pinned
notes, and every pinned note in gold #2 is one the chanter placed by hand.

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

## 8. GEN-01 — generation (deferred), and the one thing it demands today

**Deferred to its own plan** (§10). Recorded here only because one dependency
is cheap now and impossible to retrofit.

Trained on (audio ↔ neume stream), the same weights run backwards: conditioned
on text and a target phrase, the decoder emits neumes — compounds, qualitative
marks, melismatic extension included, because those are simply the tokens it was
trained to emit. Melismas falling out is not a bonus; it is what the neume
stream *is*. §3's factored vocabulary is the whole reason this stays possible.

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
pinned note.** An unmatched note is a miss, not an exclusion. Medians are
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

**Development folds are silver-only.** Stream B, score-only pretraining, and the
4 M/12 M/40 M curve must all be chosen on grouped silver folds, never on the
gold pins. Two gold pieces cannot absorb repeated model selection —
`CHANT-MODEL-ACCURACY.md` already records that two pieces cannot support a
defensible split — and a number tuned on them stops being an estimate of
anything. Gold is touched **once**, for the final claim, with no fine-tuning.

Baselines, once REPRO-01 has produced them honestly:

| system | ≤ 0.05 s | median | slips |
|---|---|---|---|
| annotator today (t03, eligible 58) | **28 %** | 0.714 s | 4 |
| forced alignment | **unverified — see §0.3** | cited 0.028 s, unreproducible | — |
| target | **≥ 90 % of eligible** | — | **0** |

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
| **REPRO-01** (S) | `fa_eval.py`: word→glyph mapping + FA scored on all 76 t03 pins | a number exists that a second run reproduces. **Blocks everything.** |
| **DECIDE-01** (S) | read REPRO-01: does FA already meet the gate on eligible notes? | **stop the neural work if yes.** If no, publish coverage, within-50 ms rate, misses and failure categories, and size NN-02..NN-06 from them |
| **NN-00** (S) | honest arithmetic baseline: `beats_seq` + one fitted tempo, same protocol | reproduced by a script, not by hand |
| **CHECK-01** (M) | find the systematic −1/−2 in the 40 violated martyria gaps | `martyria_check.py` exits 0: violated < 8 of 57 |
| **NN-01** (S) | `vocab.py`, factored neume tokenizer | round-trip exact on all 116,043 units |
| **NN-02** (M) | `features.py`, frozen feature cache + provenance (§4) | FA re-derived from cache matches REPRO-01 exactly |
| **NN-03** (M) | `dataset.py`; lane-specific silver, provenance + `source_recording_id` on every example | no gold **source recording** in any train split — including derived cuts, overlapping excerpts and duplicates under other piece ids. Split by recording, asserted in code |
| **NN-04** (M) | `model.py` at 4 M, hybrid attention + Δt head | forward/backward runs; contract doc written first (§5.5) |
| **NN-05** (L) | train; learning curve 4 M / 12 M / 40 M | **≥ 60 % within 50 ms on held-out pins, slips < 2** |
| **NN-06** (M) | `decode.py`, propose/verify/backtrack — **contract first**, as §5.5: beam state and width, score equation, anchor-crossing semantics, beat tolerance, entropy threshold, rollback state, termination, and what "high confidence" numerically means. Tuned on silver dev folds only | **≥ 90 % of eligible within 50 ms, 0 slips** — the actual deliverable |
| **ATTR-01** (S) | provenance schema at ingest; backfill 264 as `vasilikos` | nothing lands untagged |

**Deferred to their own plans, deliberately.** These were milestones in an
earlier draft and should not have been; each is an unsupported hypothesis, and
none is needed to put onsets within 50 ms:

- **MEL-01 — melisma interiors.** 4,050 of 19,868 notes, and *they have no
  supervised signal*: FA times syllable starts only, and score-only pretraining
  cannot teach acoustic timing. This needs chanter-pinned interior notes before
  it needs a model. §3's factored vocabulary keeps it reachable; nothing else
  here depends on it.
- **NN-07 — the Ling-3.0-tiny verifier.** Ships only if NN-06 misses its gate
  and the failures are ones a language model could plausibly catch.
- **GEN-01 — the reverse direction (neume generation, style personas).** Blocked
  on ATTR-01 regardless: all 264 recordings are one singer, so every persona
  collapses to one point. Keep ATTR-01; move the rest out.

**Ordering rules that must not be broken:**

- **REPRO-01, then DECIDE-01, before anything.** The plan quotes a baseline
  nobody can re-derive. With interiors deferred, it is genuinely possible that
  FA already meets the gate on the eligible 58 — in which case the correct
  outcome is to build no network at all. That has to be a decision point, not a
  discovery at NN-05.
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
- **SYL-01 chanter-reviewed before NN-05** — and note §0.3: t03's syllable
  labels are already known to be incomplete (18 of 76 glyphs unlabelled).

---

## 11. Non-goals

- Replacing forced alignment. FA stays the onset source wherever it is
  reliable; the network's job is to stop the path desynchronising between
  anchors and to tighten what is left to 50 ms.
- Melisma interiors. Deferred to MEL-01 (§10) — no supervised signal exists yet.
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
