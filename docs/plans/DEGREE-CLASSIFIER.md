# A seven-way degree recogniser for parallagi

## The gap this fills

Identification is the one step of the chanter's five-step process with no
working implementation. Two routes have been measured and both failed:

    hymn text, whole corpus                      20% end to end
    hymn text, restricted to melos spans          2/8 against his labels
    score degrees -> forced align to parallagi    2/23, chance

The third failure is the informative one, because it is not the matching logic.
Across the 23 gold parallagi spans the general Greek ASR heard 405 degree
tokens distributed like this:

    Ni 1.0%   Pa 4.9%   Vou 32.3%   Ga 1.0%   Di 11.4%   Ke 45.4%   Zo 4.0%

Seven classes collapsed into about three. The score side is discriminative --
its degree histograms differ sharply between hymns -- and the audio side is
not. Median cosine between heard and notated histograms: 0.47.

So the missing component is specific and small: something that can tell the
seven degrees apart.

## Why this is easier than it sounds

Chanter: "it would naturally pick up on relative melodic pitches as well since
that is the dead giveaway as well as the syllable itself."

That is the whole design. In parallagi the degree name and the pitch are the
same fact twice over -- the chanter sings "δι" ON Di. Two independent channels
carry the same label:

  - **phonetic**: the syllable νη / πα / βου / γα / δι / κε / ζω
  - **pitch**: the note's position relative to the mode's base

The general ASR fails on the first channel and never looks at the second. The
second is likely the stronger of the two here, because sustained sung vowels
are exactly where phonetic recognition degrades while pitch estimation gets
BETTER -- a long steady note is the easiest possible case for F0.

This also explains the specific confusion pattern above. Ke and Vou take 78% of
the mass: the ASR is guessing from vowel colour, and the degree names share
vowels (βου/ζω both round, πα/γα both open). Pitch does not have that problem.

## Feature design

The one decision that matters: **pitch must enter as cents relative to the
piece's own base, never as Hz.**

  - Vasilikos does not sing at a fixed concert pitch, and each tape sits where
    it sits. Absolute Hz would make the model memorise tapes.
  - Byzantine intervals are not 12-TET. The diatonic steps are unequal (the
    72-moria system), and the model must learn the actual step sizes rather
    than be handed a chromatic grid. Cents-from-base lets it.
  - Transposition invariance is what makes one tape's training data useful for
    the next seven.

Base estimation, in order of preference:
  1. the ison drone where present -- it IS the base, sounding
  2. the martyria at the span's start, which names the absolute degree, plus
     the F0 at that moment
  3. the mode of the F0 histogram over the span, as a fallback

Feature stack per frame: log-mel (phonetic channel) + F0 in cents relative to
base + voicing confidence. Both channels in, so the model can lean on whichever
is cleaner in a given frame.

## Labels without frame alignment

There are no frame-level degree labels and hand-making them is not worth it.
Two usable sources:

  - **score-derived sequences.** A picked score range yields its degree stream
    via `score_degrees.py`. That is a SEQUENCE, not an alignment, which is
    exactly what CTC consumes. 23 spans of it exist today.
  - **unitdeg_*.json**, 172 files of parallagi-anchored per-unit degrees from
    the existing pipeline. Weaker -- it came from the aligner being replaced --
    but usable as pre-training and abundant.

Train with CTC against the degree sequence. No alignment needed, and the
alignment falls out of the trained model as a by-product, which is separately
useful for onsets.

## Data on hand

    gold parallagi, grave-orthros      23 spans     32.6 min   score-derived labels
    pipeline-classified parallagi      58 pieces    47.9 min   unitdeg labels
    every further tape the chanter cuts            ~30 min each

~80 minutes total today. Small for speech, but this is a seven-class problem
over sustained monophonic singing by ONE voice, which is a far easier target
than open-vocabulary ASR.

## Staging, with a decision gate at each step

**Stage 1 — pitch-only baseline, no learning.** Estimate the base, convert F0
to cents, quantise to the mode's expected steps, read off degrees. Cheap, and
it establishes whether pitch alone carries the signal.
*Gate:* degree-histogram cosine against score, versus the ASR's 0.47. If a
hand-built quantiser beats 0.47, pitch is confirmed as the stronger channel and
Stage 2 is worth it. If it does not, the base estimation is wrong and that must
be fixed before any model is trained.

**Stage 2 — small supervised classifier.** Conv/BiLSTM over the feature stack,
8 outputs (7 degrees + CTC blank), trained on the gold spans with unitdeg as
pre-training. Small enough to train in minutes on the leased GPU.
*Gate:* held-out span accuracy, and the histogram cosine again.

**Stage 3 — put it back in the pipeline.** Re-run `score_degrees.py` matching
with the new recogniser in place of the general ASR.
*Gate:* the 2/23 figure. This is the number that decides whether the whole
approach works; nothing else is a substitute for it.

**Stage 4 — fine-tune wav2vec2 instead**, only if Stage 2 plateaus. More data
hungry and the phonetic channel is the weaker one here, so it is the fallback
rather than the opening move.

## How this must be evaluated

  - **Never on loss.** The loss gate said 81% when the truth was 20%.
  - **Never against unitdeg alone** -- it was derived from parallagi alignment,
    so scoring against it is circular. Score against the chanter's spans and
    against score-derived degrees.
  - **Hold out whole spans**, not frames. Frames within a span are correlated
    and a frame split would flatter the result badly.
  - **The end-to-end number is 2/23.** Improvements to intermediate metrics
    that do not move it have not been demonstrated to matter.

## Known risks

  - Score-derived labels inherit the unit-key legend, which was itself learned
    from parallagi alignments. The intervals agree with canon (oligon +1, ison
    0, apostrofos -1), so the contour is sound, but a canon-only legend would
    remove the circularity entirely and is worth building first.
  - One gold tape. Grave mode is diatonic; the model may not transfer to
    chromatic modes without examples of them. A second tape in a different
    genus is the highest-value data.
  - Apichima and the held νε at section openings are not degree names in the
    ordinary sense; the chanter's `t_in` marks let them be excluded from
    training rather than learned as noise.

---

## Results so far

**Stage 1 gate: PASSED, decisively.** `degree_pitch.py`, no training:

    median histogram cosine vs score   0.73   (ASR 0.47)
    median residual to a scale degree  20 cents
    spans scored                       21 of 23

A moria is 16.7 cents, so a 20-cent residual means the sung pitches land
essentially ON the notated diatonic degrees. The quantiser is not being forced;
it fits. Pitch is confirmed as the stronger channel, exactly as the chanter
said, and base estimation is sound.

**Stage 3 gate: FAILED.** `degree_match.py` compares the pitch-recovered degree
sequence against each candidate's score-derived sequence by DTW:

    pitch-vs-score identification   1/21, median rank 11 of 21
    ASR baseline                    2/23, median rank ~9

No better than chance and no better than the ASR it replaced. Two flaws were
found and fixed along the way -- long spans were being matched on 60 s of audio
against their WHOLE score, and DTW normalised by n+m rewarded candidates merely
for being long -- and neither changed the outcome. A single candidate still
absorbs nearly every comparison; fixing the normalisation only moved which one.

## What that combination means

Aggregate pitch statistics are good and symbol-level sequence recovery is not.
A histogram can be right while the ordering is wrong, and identification needs
the ordering. So the untrained quantiser is sufficient evidence that the signal
is there, and insufficient as a recogniser.

This makes Stage 2 necessary rather than optional. The specific job for a
trained model is now much clearer than when this plan was written: not "tell the
degrees apart" -- the quantiser already does that well enough in aggregate --
but produce a degree SEQUENCE whose ordering survives comparison. That argues
for CTC over frame-wise classification, since CTC is trained on sequence
agreement directly.

Open question worth settling before Stage 2: whether the failure is in the
recovered sequence or in DTW as the comparison. A cheap check is to run
degree_match with the SCORE's own sequence substituted for the audio side --
if identity does not then score 21/21, the matcher is broken independently of
the recogniser, and no model will rescue it.
