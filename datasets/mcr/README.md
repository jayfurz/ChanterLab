# MCR / Attraction-Engine Datasets

Score-aligned chanting recordings: each `.notes.jsonl` row is one sung note slot
aligned to its source neume glyph in a born-digital chant PDF, in the record shape
`docs/BYZANTINE_CHANT_SCORE_PROPOSAL.md` (~line 1086) calls for:

> score phrase context + intended base target + actual singer pitch + expert correction/label

## How a dataset is produced

1. **Glyph stream** from the PDF text layer (EZ/Anastasia/Neanes fonts expose
   codepoint + bbox per neume — no vision needed; see memory `ez_font_pdf_extraction`).
2. **Voice** segmented into note events (autocorrelation f0 @10 ms, onset + pitch-change splits).
3. **Alignment**: Whisper word anchors → breath↔barline pins → beat-weighted slots
   (gorgon steals 0.5 from previous; klasma/apli=2, dipli=3; two-note compounds expand)
   → pitch-aware DTW (expected vs sung interval) with EM re-learning of per-codepoint intervals.
4. **Labels**: degree (parallagi), soft-chromatic chroa spans, attraction
   (Ζω♭ on thesis descent vs Κε↑ mid-arsis — diatonic only).

## Files

- `<piece>.notes.jsonl` — per-note records (see any row for the schema)
- `<piece>.meta.json` — Ni reference, chroa spans, learned EZ interval table,
  ornament list (sung-but-unwritten quick notes), caveats

## Intended consumers

- **MCR training/eval**: (bbox, codepoint) pairs give ground truth for the image
  recognizers in `web/ocr/`; the learned interval table doubles as an EZ→semantic
  bridge seed for `web/score/glyph_import.js`.
- **Attraction engine**: sung_moria vs degree grid under phrase context is exactly
  the έλξεις training signal (see the arsis/thesis Κε↑/Ζω♭ rule in meta).

Pipeline scripts live in the 2026-08-16 chant-reel session scratchpad
(extract_glyphs.py, note_align5.py, ladder track builder); promote them into
`tools/` when a second recording is added.
