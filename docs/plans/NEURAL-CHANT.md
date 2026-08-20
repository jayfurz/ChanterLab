# NEURAL-CHANT — the encoder-decoder, made implementable

**Status:** ready to implement. Every number below was measured on 2026-08-20,
with the command that produced it. Nothing here is aspirational.

`ONSET-MODEL.md` is the *design* document — why an encoder-decoder, why a
distribution instead of a scalar, why these four base models. It is not
executable: it names no modules, no tensor shapes, no vocabulary, no commands.
This document is the executable half. Read `ONSET-MODEL.md` §4 first for the
reasoning; do not re-litigate it here.

A fresh session should be able to open this file and start at NN-01.

---

## 0. What the network is actually for

This has to be stated first because it is the single most common way this
project could waste months.

**Forced alignment already solves 80 % of the problem, at 0.028 s.** Measured on
gold #2 (t03, 76 chanter pins): FA median error **0.028 s**, 91 % within 0.15 s,
100 % within 0.35 s. The DTW aligner it replaced sits at 0.485 s. Any network
that reports "beats the DTW" has beaten a corpse.

The reason FA cannot finish the job is structural, not a tuning failure:

```
pieces measured: 220     note slots: 19,868
  notes that START a syllable   15,818   (80 %)  <- FA times these directly
  notes INSIDE a melisma         4,050   (20 %)  <- FA gives NO timestamp
```

CTC gives one timestamp per *character*. When one vowel carries twelve notes,
FA reports when the vowel started and says nothing about the eleven notes
inside it — the text has stopped disambiguating and only the neume sequence
knows what happens next. That is exactly the chanter's point: *"if there is a
lot of melismatic events … it might not know the context."*

```
notes per syllable        syllables
  1                          12,966
  2                           2,364
  3                             490
  4                             108
  5                              14
  6                               7
  8                               1
 12+                              9
```

19 % of syllables are melismatic. **The network's deliverable is the melisma
interior.** Everything else — the encoder choice, the vocabulary, the verifier —
is in service of that, plus the generation direction (§7) that the same weights
give away for free.

Corollary, and it is a hard rule: **FA remains the onset source wherever a
syllable starts.** The network does not replace it. The network fills in
between FA's anchors, and the decode in §6 treats FA onsets as fixed points.

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
   corpus-wide, zero labelling cost. It goes into the decode (§6) as a hard
   gate and into the data builder (NN-03) as a filter on silver.
2. **It is currently violated in 70 % of gaps, asymmetrically.** That is a
   systematic legend gap on the "not climbing enough" side, not solver-shaped
   noise. A solver that collapses each gap independently would paper over it
   with a different local excuse every time. **CHECK-01 (§8) fixes the rule
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

## 3. NN-01 — the vocabulary. Do this first; it is unrecoverable later

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

Gates:
- **A frame's timestamp must be exact.** `t = t0 + i*0.02`. Assert against a
  known FA output on t03: re-deriving FA onsets from cached features must
  reproduce `forced_align.py`'s timestamps to < 1 ms.
- **fp16 must not move the answer.** Re-run the gold #2 FA evaluation from the
  cache; median error must stay at 0.028 s. If fp16 degrades it, store fp32 and
  pay the disk.

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

### 5.4 Size

~40 M trainable parameters: `d_model 512`, 6 decoder layers, 4 audio layers,
8 heads, FFN 2048. This is the top of what 335 verified onsets supports, and it
is only reachable because of NN-03c below.

---

## 6. NN-03 — the data builder, and how the label budget is spent

Three sources, three very different trust levels. **They must never be mixed
into one undifferentiated pile**, and every example carries a `provenance`
field naming which it is.

### 6.1 NN-03a — gold (335 examples)

The 76 t03 pins and the 259 eothinon-11 note times. **Held out, not trained on,
until the very last stage.** These are the only instrument that has ever
detected a real improvement in this project. Spending them as training data
would leave nothing to measure with.

### 6.2 NN-03b — silver from forced alignment (~15,800 examples)

Every syllable-initial note across the 220 pieces, timed by
`forced_align_batch.py`. This is 80 % of all notes and it is *good* silver —
0.028 s median where it applies.

Filters, all mandatory:
- drop any piece whose FA CTC path fails `name_check.py` (**never gate on CTC
  loss** — the confidence gate rated mode2 15/15 when 5 of 15 were right)
- drop any martyria gap that fails CHECK-01
- drop machine-cut hymn boundaries that `ONSET-EVENTS.md` flagged; the 47
  chanter-cut spans are trusted, the 173 machine cuts are not

The 4,050 melisma-interior notes have **no silver label**. That is the point of
the project; do not invent one by interpolating, and above all do not
manufacture labels from our own duration model (`ONSET-MODEL.md` §9).

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
   - satisfies CHECK-01 at the next cadence martyria — free, label-less
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

## 8. Generation, and the one thing it demands today

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

**Baseline to beat is forced alignment, not the DTW.**

| system | median &#124;Δt&#124; | ≤ 0.15 s | scope |
|---|---|---|---|
| DTW aligner (r4) | 0.485 s | 48 % | all notes |
| **forced alignment** | **0.028 s** | **91 %** | syllable-initial only (80 % of notes) |
| target | ≤ 0.028 s overall | ≥ 91 % | **all notes, melisma interior included** |

Report **three populations separately** — a single median hides everything:

1. syllable-initial notes (must not regress below FA)
2. **melisma-interior notes** (the deliverable; FA has no number here)
3. all notes over a fixed denominator, where an unmatched pin is a **miss**

Plus the **slip count**: how many times the path loses sync.

Disqualified metrics, both with the reason:
- **Movement agreement.** Reads 1.00 on t03 while median onset error is 0.485 s.
  It grades the aligner against its own decode.
- **CTC loss as a correctness signal.** The confidence gate rated mode2 15/15
  when 5 of 15 were right. Score with `name_check.py`.

Synthetic data gates nothing. A metric computed on synthetic audio is not
evidence; only real held-out pins are.

---

## 10. Staging

| id | work | gate |
|---|---|---|
| **CHECK-01** (M) | find the systematic −1/−2 in the 40 violated martyria gaps; fix the legend rule | `martyria_check.py` exits 0: violated < 8 of 57 |
| **NN-01** (S) | `vocab.py`, factored neume tokenizer | round-trip exact on all 116,043 units |
| **NN-02** (M) | `features.py`, frozen 2-stream cache | FA re-derived from cache reproduces 0.028 s |
| **NN-03** (M) | `dataset.py`; gold/silver/score-only, provenance on every example | gold never appears in a train split, asserted in code |
| **NN-04** (M) | `model.py`, hybrid attention + Δt head | forward/backward runs in < 20 GB at batch 8 |
| **NN-05** (L) | `train.py`; neume-LM pretrain → silver align | beats FA on melisma-interior held-out pins |
| **NN-06** (M) | `decode.py`, propose/verify/backtrack with FA + martyria gates | slip count falls; **no regression on syllable-initial** |
| **NN-07** (M) | `verify_llm.py`, Ling-3.0-tiny on GPU 1 | improves accepted-prefix length; no regression |
| **WFC-01** (M) | martyria constraint solver over ambiguous bars, scored against the pitch curves | ships only after CHECK-01 |
| **ATTR-01** (S) | provenance schema at ingest; backfill 264 as `vasilikos` | nothing lands untagged |

**Ordering rules that must not be broken:**

- **CHECK-01 before NN-03.** 70 % of martyria gaps currently disagree with the
  printed music. Using that as a silver filter today would filter on a broken
  rule.
- **SYL-01 chanter-reviewed before NN-05.** Training on mis-split syllables
  bakes the error into weights, where it is far more expensive to find than in
  a JSON file.
- **NN-01 before anything else.** The vocabulary is the one decision that is
  free today and unrecoverable later.

---

## 11. Non-goals

- Replacing forced alignment. The network fills melisma interiors *between*
  FA anchors.
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
