# V2 Aligner: movement-space matching (chanter-specified north star)

Direction set by the chanter, 2026-08-17, after note-by-note review of the
Eothinon XI alignment. Supersedes the v1 (note_align5) approach.

## Principles
1. **Perfect score first**: hand-verified transcription (chantscript), compiled
   through the committed engine (`web/score/timing.js` temporal rules +
   `compiler.js`) for authoritative notes and beats. No ad-hoc weight tables.
   (Engine gap to fix first: gorgon chains — see #129 comment.)
2. **Match movements, not positions**: DTW in interval space (sung pitch deltas
   vs scored movements). Robust to basis drift, attraction, and tetrachords
   tuned by the chanter's ear rather than theory. Accidental inference falls
   out: a raised Vou is detected because the following Ga is only a small step
   above it — relative structure, not absolute rungs.
3. **Piecewise tempo**: moving-average sec/beat, allowed to reset at breaths /
   phrase liberties (the chanter may pause between phrases; rhythm is local).
4. **Never fall back to metronomic interpolation** for display: unclaimed spans
   must interpolate in *performance* time between claimed neighbors, not on the
   beat grid (root cause of the persistent resurrectiON-O-Savior wrong trope).
5. **Eval set**: the chanter's pins and region specs
   (datasets/mcr/*.meta.json caveats) are the regression tests. Any aligner
   change must reproduce all of them before shipping.
6. **End state**: a network over (scored movement features, sung contour,
   local tempo context) -> alignment + accidental labels, trained on the
   accumulating datasets/mcr corpus. The classical v2 aligner is the
   label-bootstrapper and the baseline.
