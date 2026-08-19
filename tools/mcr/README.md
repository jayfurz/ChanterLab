# MCR model lane — glyph + melisma classification from audio

Two regimes, honest grouped-CV numbers for both:

| regime | inputs | glyph acc (full output) | at >=90% accuracy |
|---|---|---|---|
| pure audio (below) | recording only | .467 | — |
| score-informed (`train_aligner.py`) | recording + notation | **.761** | **90.4% acc @ 65% coverage** (conf>=0.7) |

## Score-informed lane (train_aligner.py)

Given the recording AND the piece's Byzantine notation (glyph stream, expected
degrees, beats, lyrics, ison letters), a bagged GBM scores alignment arcs
"event k' realized slot s', next structural event k realizes slot s" (movement
match, duration-vs-beats under an anchor-derived local tempo, breath/barline
bar-phase counting, absolute pitch vs expected degree, ASR word-anchor timing).
Decoding is posterior-marginal (forward-backward) over the monotonic
event x slot graph, then an EM pass: conf>=0.9 claims become new time anchors,
the melisma-aware phase map is rebuilt, decode repeats. It replaces
note_align6's ~20 hand-tuned constants and its 11 manual pins.

Grouped-CV (a fold never trains on its test lines): glyph .761 / exact-slot
.714; five of six folds sit at .78–.84. Per-event confidence is honest:
conf>=0.7 covers 65% of notes at .904 accuracy, conf>=0.9 covers 44% at .955.
Melisma detection improves to recall .76.

The one bad fold (.47) is lines 10/12/14 — the same melisma runs where the
hand-built pipeline needed MANUAL pins (gi150/157/218) and where the ASR word
anchors are scrambled. Hard-won negative results, so nobody retries them
blindly: hard-negative mining (-6pts, decoded-but-plausible arcs mislabeled),
absolute phase-deviation features (-4pts, over-trusted where the anchor map
mis-stretches across melismas), dropping word anchors after EM pass 1 (-6pts).

Path to >=90% full-output: (1) more aligned recordings — the arc scorer is
piece-relative and fold instability is a 254-positive-arcs symptom; (2) or ~3
human pins per piece in the annotator UI exactly where confidence is low —
v6 proved pins lock those regions. The confidence output makes review cheap:
2/3 of every new piece needs no human at all.

## Pure-audio lane

First trained models for the MCR direction (`datasets/mcr/README.md`): given a
chant recording only — no score — classify, per segmented note event, which
neume glyph is being performed, and flag melisma/ornament events (sung notes
with no written glyph). Trained on the one chanter-verified aligned recording
(11th Eothinon, plagal 4th, 318 cleaned events / 255 glyph-labeled / 34
ornaments, 24 glyph.sub classes).

## Pipeline

```
build_events.py <workdir>          # audio-only features + alignment labels -> events.jsonl
train.py <events.jsonl>            # GBM lane: baselines, flat + factored heads, ornament detector
train_cnn.py <workdir>             # contour-CNN lane (torch, multi-task)
classify.py <events.jsonl> models/ # inference: predicted glyph stream + melisma flags
```

- `build_events.py` replicates `note_align6.py`'s stream cleaning **exactly**
  (short-note + ison-bleed merge) — `slot_claims.json` indexes the *cleaned*
  stream; using raw indices silently mislabels everything (found the hard way:
  movement agreement 24% -> 52% after the fix).
- Features are strictly audio-derivable: durations/gaps, pitch deltas vs
  neighbouring events (moria/10.3 and diatonic-ladder-quantized), within-note
  contour shape, RMS envelope, passing-tone position (`mid_frac`). Labels come
  from the chanter-verified alignment (`mcr_interpretation.json` + claims).
- Without the label files, `build_events.py` runs features-only, so
  `classify.py` works on a new unlabeled recording once the existing
  f0/segmentation stage (voice_notes3 + moria/rms tracks) has run.

## Results — grouped CV over score lines (a fold never trains on its test lines)

255 structural events, 24 classes. `acc(core)` = accuracy on classes with >=5
examples.

| lane                          | acc  | macro-F1 | acc(core) |
|-------------------------------|------|----------|-----------|
| majority class                | .345 | .021     | .389      |
| interval rule (round d_prev)  | .490 | .070     | .553      |
| ladder rule                   | .451 | .058     | .509      |
| GBM flat glyph                | .467 | .110     | .522      |
| GBM factored->composed        | .455 | .102     | .513      |
| contour CNN (multi-task)      | .459 | **.152** | .509      |

Aux heads (GBM): movement .471, beats-class .569, compound-position .690.
Ornament/melisma detector: AP .435; precision .52 / recall .32 @0.5
(base rate .12).

## Honest reading

- Every glyph lane sits in the 44–49% band because the bottleneck is not the
  model: the sung interval between claimed events deviates from the notated
  movement with **MAD ≈ 0.5 steps** (rounding matches only 52%). The
  score-aware DP aligner needed anchors + duration priors to resolve exactly
  this ambiguity; a pure-audio per-event classifier can't see around it.
  The 0-vs-±1 movement boundary dominates every confusion table
  (ison ↔ apostrofos ↔ oligon, kentimata-halves ↔ oligon).
- ML beats the interval rule where it matters for coverage: macro-F1 doubles
  (CNN .152 vs .070), i.e. tail classes (yporrhoe, running-elafron, kentimata)
  start being found at all.
- Absolute-degree features are capped by performance practice: the voice sits
  up to ±9 moria off the nominal diatonic ladder (drift + έλξεις + soft-
  chromatic spans). A proper attraction-aware ladder (the attraction engine
  this dataset was built for) is the principled fix.
- One recording, 24 classes, top-3 classes = 62% of events: the ceiling here
  is data, not architecture. The pipeline is piece-agnostic; each new aligned
  recording (`datasets/mcr`) drops straight in.

## Next data, in order of value

1. More aligned recordings (same chanter first — the alignment pipeline is
   proven; other chanters next for generalization).
2. Melisma-rich pieces: 34 ornament examples is why detector recall is .32.
3. Same piece re-recorded — separates chanter variance from piece identity.

Artifacts land in `<workdir>/models/`: `mcr_gbm.joblib` + spec,
`mcr_cnn.pt`, `report_gbm.json`, `report_cnn.json`.
