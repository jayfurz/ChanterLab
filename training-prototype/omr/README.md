# SATB score extraction — pipeline & bake-off artifacts

PDF in → 4-voice (S/A/T/B) MusicXML out, for the choir-training feature.
Full findings and the bake-off scoreboard: `docs/choir-training-roadmap.md`
§"OMR bake-off". Source-score provenance and the library API notes:
[`SOURCES.md`](SOURCES.md).

## TL;DR

The three prototype pieces are **born-digital Dorico engravings** (Bravura
SMuFL font glyphs + vector paths at exact coordinates). Reading those
primitives directly out of the PDF (**vector extraction**) beats raster OMR
outright: 100% note/voice/measure accuracy on the hand-encoded ground truth,
~0.2 s per piece, deterministic. `oemer` and Audiveris both collapse or
mangle the 4-voice structure.

### Catalog survey (2026-07-02, `survey_catalog.py`)

A 45-piece random sample of the full ~3,800-item catalog (30 choral / 15
chant) says the library is **almost entirely born-digital vector PDFs, but
mostly OLDER engravings** — the Dorico/Bravura slice the prototype uses is
the minority:

| PDF kind | choral (n=30) | chant (n=15) | pipeline today |
|---|---|---|---|
| SMuFL fonts (Bravura/Leland) | 1 | 3 | ✅ native |
| Legacy Finale fonts (Maestro/Petrucci, Sonata-compatible encoding) | 28 | 11 | ✅ via `legacy_glyph_map.json` (see below) |
| Text-only / Byzantine-neume fonts | 1 | 1 | out of SATB scope (refused, exit 3) |
| Raster scans | 0 | 0 | — |

Catalog access is documented in `SOURCES.md`; the survey downloads live in
`pdfs/survey/` (gitignored).

### Legacy Finale font support (2026-07-02)

Maestro and Petrucci share the Sonata codepoint layout, emitted per glyph as
either a MacRoman-mapped char or its PUA twin (0xF000+byte). The table in
`legacy_glyph_map.json` (97 codepoints) was derived EMPIRICALLY: 
`legacy_glyph_atlas.py` crops every distinct codepoint from the survey corpus
into contact sheets (`pdfs/survey/atlas/`), each symbol was classified
visually in context, and the high-risk rows (˙=open half notehead,
∑=whole rest vs Ó=half rest, j/J flag directions, V=treble-8vb clef) were
double-checked against crops. `vector_extract.py` remaps legacy→SMuFL at
glyph ingestion, so the whole downstream engine is font-agnostic; unmapped
music glyphs are counted in the confidence report (>2% ⇒ warning). A related
fix: this Finale family draws each staff line as bundles of parallel
hairline strokes, which the old single-segment path filter dropped.

### Batch ingester (`ingest_catalog.py`)

Catalog → filter → polite download → `pipeline.py` (auto page selection —
mixed Byzantine/Western books contribute their Western-notation pages) →
confidence gate → `out/ingest/manifest.json` (accepted pieces; the training
app lists them automatically) + review queue in `out/ingest/ingest_state.json`.
Resumable and idempotent; `--report-only` summarizes without network.

**Full-catalog run (2026-07-03, post staff-grouping fix):** all 3,793
eligible items processed with zero download/extract errors. **1,487
accepted** (mean integrity 99.6%, median 100%) → the app library, organized
by the liturgical taxonomy (Menaion 892, Theotokia 125, Divine Liturgy 121,
Triodion 107, Pentecostarion 101, Anastasimatarion 54, other services 87);
1,996 in review; 300 non-Western/no-music; 10 Type3. A voice-collapse
tripwire keeps choral-marked single-voice extractions out of the library
(that failure mode passed the integrity gate vacuously before the
connector-line staff-grouping fix). The review pile is dominated by the
Joseph of Damascus service books and multi-tone "series" volumes whose
dense shared-staff layouts trip voice-beat reconciliation — the known
frontier for the next engine iteration.

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
