# SATB score extraction — pipeline & bake-off artifacts

PDF in → 4-voice (S/A/T/B) MusicXML out, for the choir-training feature.
Full findings and the bake-off scoreboard: `docs/choir-training-roadmap.md`
§"OMR bake-off". Source-score provenance and the library API notes:
[`SOURCES.md`](SOURCES.md).

## TL;DR

The Antiochian Sacred Music Library PDFs are **born-digital Dorico
engravings** (Bravura SMuFL font glyphs + vector paths at exact
coordinates). Reading those primitives directly out of the PDF
(**vector extraction**) beats raster OMR outright: 100% note/voice/measure
accuracy on the hand-encoded ground truth, ~0.2 s per piece, deterministic.
`oemer` and Audiveris both collapse or mangle the 4-voice structure.

## Usage

```sh
cd training-prototype/omr
uv venv --python 3.11 .venv          # once
uv pip install --python .venv/bin/python pymupdf

# PDF -> MusicXML + confidence report (exit 2 if integrity < 90%)
.venv/bin/python pipeline.py pdfs/01_trisagion_lozowchuk_satb.pdf \
    -o out/vector/trisagion_vector.musicxml
```

- `--pages 2,3` restricts pages (1-based); title/blank pages are skipped
  automatically.
- `--report path.json` sets the confidence-report path (default `<out>.report.json`).
- `pipeline.py` refuses scanned PDFs (no music-font glyphs → exit 3);
  raster OMR is out of scope for this pipeline.

The engine is [`vector_extract.py`](vector_extract.py) (importable:
`vector_extract.run(pdf, out, report, pages)`).

### What the engine handles

- 4-staff systems (one voice per staff) and **2-staff choral reductions**
  (S+A treble / T+B bass), including mid-piece layout switches.
- Voice separation on shared staves: stem direction, single-stem chord
  splitting, written unisons (a2), stacked/side-by-side whole pairs,
  shared vs voice-specific rests — resolved per measure by a small
  constrained search (both voices must sum to the same length; both staves
  of a system must agree; engraving-convention priors break ties).
- Durations: notehead type, stems, beams (incl. 16th stub beams), flags,
  augmentation dots. Unmetered music (no time signature) is emitted with
  hidden per-measure meters so renderers stay happy.
- Key signatures, printed accidentals + measure-scoped accidental memory,
  clefs (treble, treble-8vb, bass), ties vs slurs, tempo marks
  ("♩ = NN"), lyrics (syllables + hyphenation → per-note `<lyric>`),
  repeat barlines (noted in the report), parenthesized optional notes
  (excluded, reported), divisi a2 on single-voice staves (chord-merged when
  aligned, otherwise the secondary stream is dropped **and reported** —
  correction-UI material).

### Confidence report

Every run writes JSON with `stats` (counts of every assumption taken:
unison duplications, chord splits, divisi drops, ambiguous routings...),
`warnings` (measure-level inconsistencies with locations), and per-voice
note counts. The headline number is `measure_integrity_pct` — the share of
measures where all four voices agree on total beats. On the 3-piece corpus
it is 100% for all pieces.

## Verification harness (`verify/`)

Full-score audit against the original PDFs (see
`docs/omr-verification-2026-07-02.md` for the 2026-07-02 findings):

```sh
.venv/bin/python verify/coverage.py          # every PDF notehead/rest accounted for (exit 1 if not)
.venv/bin/python verify/annotate.py          # extraction overlaid on the PDF, per system
.venv/bin/python verify/annotate.py cherubic -m 14   # 6x zoom of one measure
.venv/bin/python verify/render_compare.py    # verovio render vs PDF crop, per system
.venv/bin/python verify/split_halves.py      # L/R half crops for reading
```

Outputs land in `verify/out/` (gitignored — derived from copyrighted PDFs);
curated proof images in `verify/proof/`. Layout emission (measure splitting for
unmetered chant, beams, `<print new-system>`, engraved widths) is exercised by
`render_compare.py` since it renders the emitted MusicXML verbatim.

## Bake-off tooling

- `ground_truth/trisagion_p2_gt.json` — hand-encoded 8 measures × 4 voices
  of the Trisagion (from 7–9× zoomed renders; committed).
- `score_extraction.py` — the judge: candidate MusicXML vs ground truth →
  per-voice note recall/precision, duration accuracy, voice-assignment,
  measure integrity.

```sh
.venv/bin/python score_extraction.py ground_truth/trisagion_p2_gt.json \
    out/vector/trisagion_p2_vector.musicxml --label vector
```

## Files

| File | Purpose |
|---|---|
| `pipeline.py` | CLI: PDF → MusicXML + confidence report (winner engine) |
| `vector_extract.py` | The engine (PyMuPDF glyph/path reassembly) |
| `score_extraction.py` | Bake-off judge vs ground truth |
| `ground_truth/` | Hand-encoded reference (committed) |
| `SOURCES.md` | Score provenance + library API notes + oemer repro |
| `shot.mjs` | Headless prototype screenshots (Playwright) |
| `pdfs/ pages/ out/ shots/*vector*` | Gitignored (copyrighted source material) |
