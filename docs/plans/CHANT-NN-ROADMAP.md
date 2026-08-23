# Chant NN roadmap — from one-hour tape to per-onset parallagi labels

Written 2026-08-22. Owner's framing: *"build up our tools so that we have our
NNs which will help us cut all the audio, cut the scores and map the scores to
the pieces, detect the melos/parallagi and if parallagi be able to map each
onset to an actual parallagi."*

This document is an inventory first and a plan second. Every stage below lists
what exists in the checkout today, what it measured, and what still has to be
built. Numbers are copied from the named script's own docstring or plan doc;
nothing is re-asserted from memory. Where a number only prints at runtime and
was not re-run, it is marked **(runtime)**.

**The owner's belief at the start of this document — "the only thing working is
the audio cutter and the parallagi onset model" — undersells it.** Measured
2026-08-22: the parallagi degree classifier is at 98 % held-out, and the neural
piece cutter fits its one tape at F1 0.99. What is genuinely broken is hymn
identification (stage 3); lane transfer (stage 2) is at 85 % with the hand-feature model.

---

## 0. The pipeline, as six stages

```
 hour tape
   │  1. CUT AUDIO          piece start/end on the tape
   ▼
 pieces
   │  2. LANE               parallagi or melos?
   ▼
 pairs (parallagi → melos, strict alternation)
   │  3. IDENTIFY + CUT SCORE   which hymn; where its score slice starts/ends
   ▼
 (piece, score range)
   │  4. ONSETS             one timeline event per notated unit
   ▼
 (piece, score, onset[i] ↔ unit[i])
   │  5. DEGREE PER ONSET   parallagi only: νη πα βου γα δι κε ζω, two octaves
   ▼
 parallagi with sung degree per onset  →  legend-error detector, training labels
```

Stage 3 is two jobs (identify the hymn; find its score bounds) that the docs
have always treated as one, and the existing evidence says they fail for
different reasons. They are kept together here because both are unblocked by
the same thing — the pairing.

---

## 1. Inventory — what is built, what it measured

| # | Stage | Tool(s) | Status | Measured |
|---|---|---|---|---|
| 1 | Cut audio | `tools/neural/piece_bounds.py`  | **Built; self-fit only.** 50 ms frames, ±25 s receptive field, separate start/end heads, random 100 s crops. Labels verified clean: every one of 94 chanter boundaries is in silence (14.5× quieter than random). | Self-fit on the grave tape, 2000 steps: 48 starts / 48 ends predicted vs 47/47 gold, **P 0.979 R 1.000 F1 0.989 at every tolerance from 0.25 s to 2 s**, both heads. One labelled tape → this is a fit diagnostic, not generalisation |
| 1 | Cut audio (old) | `tools/corpus/audio_cut_*.py`, `audio_recut*.py`, `separate_pieces.py` | Heuristic, over-splits at in-hymn silences. Against 23 gold melos spans: 4/25 IoU ≥ 0.9, 11/25 IoU < 0.5, median 0.56 (PARALLAGI-PAIRING.md) | 33 % of 157 tracks still end mid-sound |
| 2 | Lane | `presplit_map.py` rule + `lane_eval.py` | **Working, calibration-fragile.** Count degree names/s from wav2vec2-Greek, cut at 0.43 | grave (tuning) 95.7 %, mode 2 (held out) 81.8 %; every error is parallagi→melos |
| 2 | Lane | `tools/neural/lane_net.py`  | Dead end, keep as evidence. 0.57 M CNN on 4 s mel | 100 % train, **54.5 %** transfer — learns the room |
| 2 | Lane | `tools/neural/lane_modspec.py`  | Modulation spectrum, length-invariant. **Does not beat the threshold.** | grave→mode 2 **63.6 %** (21/33), mode 2→grave 60.9 % (28/46); misses are on both sides, so it is not a calibration shift like the rule's |
| 2 | Lane | `tools/neural/lane_features.py`  | Modspec + peakiness + degree-syllable rates (hand features, small head). **Best lane detector measured: beats the rule held-out.** | grave→mode 2 **84.8 %** (28/33), mode 2→grave **95.7 %** (44/46); vs rule 81.8 % / 95.7 % |
| 2 | Pairing | PARALLAGI-PAIRING.md, `piece_bounds.py --lanes` | **Proven structural prior**: 23/23 melos preceded by its parallagi, 0 orphans. Acts as a checksum on stages 1–2 | — |
| 3 | Identify | CTC loss gate + `name_check.py` | **Broken, measured why.** Loss gate says 81 %; free-label truth is **20 %** end-to-end; candidate selection itself ~53 %; margins 0.03–0.48/tok | RESEP-IDENTIFICATION.md |
| 3 | Identify via degrees | `degree_pitch.py`, `degree_match.py` | Stage-1 gate passed (histogram cosine 0.73 vs ASR 0.47, residual 20 cents); stage-3 gate **failed** (1/21, chance). Matcher proven fine (identity 20/21) — the recogniser is the whole gap | DEGREE-CLASSIFIER.md |
| 3 | Score bounds | `boundary_from_fa.py`, `dropcap_*`, `martyria_check.py` | Partial. 110/173 slices start on a drop cap (64 %) | PIECE-RESEPARATION.md |
| 3 | Score → units | `hymn_align.py` decoder, `beats_seq`, legend/atlas | **Working and chanter-audited** (DECODE-01, DUR-01, KEY-01 largely landed) | 76/76 t03 units correct count |
| 4 | Onsets (FA) | `forced_align.py`, `fa_eval.py`, `onset_eval.py` | Baseline. Character path 55.3 % within 150 ms, 56/76 placed | t03 (burnt) |
| 4 | Onsets (peak NN) | `tools/neural/quick_onset.py` | **Works for detection on parallagi.** Held out on s06: recall **1.000 at 50 ms**, but only 69 % on the right glyph — one inserted/dropped peak shifts every index after it | — |
| 4 | Onsets (assign) | `onset_match.py` (peaks as vernier, beats as cue, pitch as verifier) | Landed cf0500a; this is the index-assignment layer the peak model lacks | not yet scored with `onset_eval.py` on a sealed fold |
| 4 | Onsets (enc-dec) | NEURAL-CHANT.md NN-01+ | **Not started**, gated on PIN-REPEAT-01 and the tokenizer contract | — |
| 5 | Degree per onset | `tools/neural/parallagi_class.py` | **Working.** 15 classes low δι…high δι'; 258 gold-onset notes over s02/s04/s06; labels score-derived | **Leave-one-hymn-out 98.1 %** (100 / 96.5 / 97.9) vs 35.7 % majority. The five out-of-range s04 notes are gone since the martyria fix (8b93efd). 5 residual disagreements, listed in §5 — each is a classifier error *or* a legend error, and both are wanted |
| 5 | Degree per onset (old) | `parallagi_cnn*.pt` + `classify_parallagi.py` | Mod-7 syllable CNN from the MCR era; fed `parallagi_align.py` DTW | superseded by the two-octave design |

Gold on hand: 47 chanter-cut spans on the grave orthros tape (one tape), 76 pins
on t03 (burnt), 335 verified onsets total, 30 pins + 99 corrected slots on s01
(sealed test fold), 33 hand-named mode-2 files (lane only).

---

## 2. What is actually blocking, and in what order

The stages are not independent and the dependency is the reverse of the
pipeline order:

1. **Stage 5 needs stage 4's onsets on parallagi** — it has them (peak model
   recall 1.0). It does *not* need identification: a parallagi's labels are its
   own score range, and the three pieces it trains on were ranged by hand.
2. **Stage 4's index assignment needs a correct unit count**, which the decoder
   now gives. It does not need stage 1–3 to be neural.
3. **Stage 3 identification has been attacked twice as a text problem and once
   as a degree problem, and the only thing that moved it was the pairing.**
   A melos inherits its identity from the parallagi before it, and a parallagi
   can be identified by its sung degree *sequence* once stage 5 emits an
   ordered sequence — which is exactly what `degree_match.py --identity-check`
   proved the matcher can consume (20/21).
4. **Stage 1 needs a second labelled tape** to say anything about
   generalisation, and the chanter is the only source.

So the critical path is **5 → 3, with 4 feeding 5**, and stages 1–2 are
data-limited rather than model-limited. That inverts the intuition that the
cutter comes first.

---

## 3. Plan, by stage, with gates

### S5 — parallagi degree per onset (first, because it unlocks S3)

Owner's plan, already half-executed: *"since we have onsets correct we can just
classify each note and overfit it on that."*

- **S5-01 DONE 2026-08-22.** `--loo` = **98.1 %** over 258 notes. Gate passed.
- **S5-02 DONE** by 8b93efd (low-octave martyria) — no note falls outside the
  two-octave range any more.
- **S5-02b** Send the five §5 disagreements to the chanter: s04 notes 13/49/84,
  s06 notes 29/61. The model hears βου where the score says νη twice on s06
  and once on s04 at a δι — a consistent pattern worth one listen.
- **S5-03** Add the pitch channel explicitly: F0 in cents from the piece's base
  (ison → opening martyria → histogram mode, per DEGREE-CLASSIFIER.md). The
  model may already find it in mel, but cents-from-base is what makes the next
  tape's data usable.
- **S5-04** Grow labels: run the peak model + classifier over all 23 gold
  parallagi spans, route confident disagreements with the score to the
  annotator as the chanter's review queue. **Every disagreement is either a
  classifier error or a legend error, and both are wanted.**
- Gate for the stage: a held-out *span* (not frames) accuracy, and the
  sequence it emits, fed to `degree_match.py`, identifies its own span (§S3-01).

### S4 — onsets (keep the working half, score the new half)

- **S4-01** Score `onset_match.py` with `onset_eval.py` on the sealed s01 fold.
  Nothing else counts (ONSET-SCORING contract). Target is the FA-ONSETS
  deliverable: pinning takes minutes, i.e. ≥ 90 % within 150 ms, zero slips.
- **S4-02** Keep the peak model as the parallagi onset source for S5 — it is
  already at recall 1.0 there. Melos onsets (open vowels, no consonant between
  notes) are where the enc-dec of NEURAL-CHANT.md earns its cost; do not start
  NN-01 until S4-01 is scored and PIN-REPEAT-01 is done.

### S3 — identify the hymn and cut the score

- **S3-01** Re-run the 2/23 test with S5's sequence in place of
  `degree_pitch.py`'s quantised stream. This is the single number that decides
  whether degree-based identification works. Matcher is proven; recogniser is
  the variable.
- **S3-02** Propagate: melos identity := identity of preceding parallagi.
  Parallagi spans leave the text-identification pool entirely (they were
  poisoning it — half the audio "is not text at all").
- **S3-03** Score bounds: with identity fixed, `boundary_from_fa.py` +
  drop-cap + right-aligned-martyria rules get a correct hymn to bound. Measure
  with the 110/173 drop-cap figure and the clipped-track count.
- **S3-04** Only if S3-01 fails: text-side pool repair (4/15 correct text
  absent from the 8-candidate pool) — a pool problem, not a scorer problem.

### S2 — lane

- **S2-01 measured.** Raw modulation spectrum **63.6 %** — worse than the
  rule. The hand-feature model (`lane_features.py`: modspec + peakiness +
  degree-syllable rates) transfers at **84.8 %** to mode 2 and 95.7 % back to
  grave, the first thing to beat 81.8 % held out. Adopt it as the lane
  detector; its 5 mode-2 misses are still worth a look (3 melos at p≈0.7, 2
  parallagi at p≈0.3 — both sides, so not a threshold shift).
- **S2-01a** Add the pairing checksum (equal counts, strict alternation) as a
  per-tape post-hoc correction: any tape whose lane sequence breaks
  alternation has a wrong call, and the lowest-margin span is the suspect.
- **S2-01b** Once S5's classifier exists, the cheapest lane detector may be it:
  run the degree classifier over a span's onsets and look at its mean
  confidence. A melos yields low-confidence garbage; a parallagi yields a
  confident ladder. That is mode-invariant by construction and costs nothing
  new. Measure on the 33 mode-2 files.
- **S2-02** The chanter's strongest idea — align the span against the hymn
  text *and* against the degree-name text, take the better fit — is a direct
  test, not a proxy. Needs a scored second corpus; lands when one exists.

### S1 — cut the tape

- **S1-01 DONE**: self-fit F1 0.989 at every tolerance (§5). One false start +
  one false end at 48 vs 47 — find which span they split and whether it is a
  real boundary the chanter merged.
- **S1-02** Ask the chanter for one more hand-cut tape in a *different mode and
  genus* (chromatic). That is the highest-value 30 minutes of labelling in the
  whole project: it unblocks S1 generalisation, S2 transfer, and S5's second
  genus at once.
- **S1-03** Replace the heuristic cutter in the reseparation pipeline with
  `piece_bounds` + the pairing checksum, then re-run PIECE-RESEPARATION's
  scoreboard. Abrupt boundaries stay "reported, not predicted" until examples
  exist.

---

## 4. What to do with the uncommitted files right now

`tools/neural/{lane_features,lane_modspec,lane_net,piece_bounds}.py` and
`tools/corpus/lane_eval.py` are untracked on `main`. They are evidence as well
as code — `lane_net.py` in particular documents a measured dead end that should
not be retried. Commit all five under `feat(neural)` with their runtime numbers
pasted into §5 of this file, then push (see `always_push_merge_deploy`).

---

## 5. Runtime numbers (filled as measured)

| script | set | result | run date |
|---|---|---|---|
| `lane_modspec.py --eval-transfer` | grave→mode2 / mode2→grave | 63.6 % (21/33) / 60.9 % (28/46) | 2026-08-22 |
| `lane_features.py --eval-transfer --device cpu` | grave→mode2 / mode2→grave | **84.8 %** (28/33) / **95.7 %** (44/46) | 2026-08-22 |
| `parallagi_class.py --loo --errors` | s02 / s04 / s06 (76 / 85 / 97 notes) | 100 % / 96.5 % / 97.9 %, mean **98.1 %**, baseline 35.7 % | 2026-08-22 |
| `piece_bounds.py --steps 2000` self-fit | grave orthros tape, 47 spans | 48/48 predicted; START & END P 0.979 R 1.000 F1 0.989 @ 0.25–2 s | 2026-08-22 |

Classifier disagreements with the score (model is right until proven wrong):

```
s04  note 13  score νη'   model δι
s04  note 49  score δι    model βου
s04  note 84  score ζω,   model νη
s06  note 29  score νη    model βου
s06  note 61  score νη    model βου
```

Reproduce (gold from `gold_times.py --piece <export> --out`, pieces from the
chant-annotator worktree's `annotator/data`, hymn = `meta.source.span`):

```
/mnt/data/chant-corpus/venv/bin/python tools/neural/parallagi_class.py \
  --piece <s02 dir> --gold gold_s02.json --hymn 't01_#3' \
  --piece <s04 dir> --gold gold_s04.json --hymn 't01_#5' \
  --piece <s06 dir> --gold gold_s06.json --hymn 't01_#7' --loo --errors
```

A vLLM worker was holding 22 GB of the GPU during these runs; `lane_features`
had to go to `--device cpu`.
