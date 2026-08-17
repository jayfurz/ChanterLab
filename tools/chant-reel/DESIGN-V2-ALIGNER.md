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

## Syllable-acoustic anchors (chanter addition, 2026-08-17)
Replace ASR word timestamps ("a low-fidelity meterstick for a millimeter job")
with direct acoustic syllable detection, exploiting chant's structure:
- **Plosive onsets**: broadband transients / closure-burst patterns — near-free.
- **Vowel-shape changes**: formant (F1/F2) trajectory shifts. In chant a melisma
  holds ONE vowel, so a vowel-quality change IS a syllable boundary; within-
  melisma formants are stable. A formant-stability tracker therefore yields
  syllable onsets at ~10ms precision.
- The score supplies the syllable SEQUENCE (no recognition needed): match
  detected onsets to known syllables in order = dense, unbiased anchors,
  one per syllable instead of one per ASR word with melisma-late bias.
- These densified anchors feed the same span-alignment interface; ASR remains
  only as a cross-check. Also first-class NN input features later.
