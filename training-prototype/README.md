# ChanterLab — Choir Training (SATB) prototype

A standalone, no-build spike of the choir-practice experience: render a 4-part
SATB score, pick your voice, mute it in playback, and follow your gold-highlighted
part with a cursor. See the full plan in
[`../docs/choir-training-roadmap.md`](../docs/choir-training-roadmap.md).

## Run

```sh
# from this directory
python3 -m http.server 8791
# open http://localhost:8791/
```

Everything is client-side. OpenSheetMusicDisplay and Tone.js are vendored in
`vendor/`; no npm install needed.

## What it does

- **S | A | T | B** selector — tap your voice.
- Selected voice noteheads turn **gold (#d4af37)**; the other voices dim to gray.
- A **gold follow cursor** advances through the score as it plays.
- Your voice is **muted** in the audio mix (each voice is its own synth) so you
  sing it — toggle "also hear my part" to un-mute.
- **Tempo** slider and **loop a measure range** for drilling a passage.

## Content

- **Control** (`content/control_satb.musicxml`) — a hand-made, deliberately
  clean 4-part sample. Known-good, so the UI is verifiable independent of
  extraction quality.
- **Trisagion / Cherubic Hymn / Anaphora** (`content/*_vector.musicxml`) —
  produced by the **vector-extraction pipeline** (`omr/pipeline.py`) from the
  real Antiochian Sacred Music Library PDFs; 100% measure integrity, full
  lyrics, all four voices (the Cherubic even splits its 2-staff reduction
  pages into S/A/T/B). Gitignored — regenerate via `omr/README.md`.
- **Trisagion (oemer OMR)** (`content/trisagion_omr.musicxml`) — the losing
  raster-OMR output, kept for comparison (1 collapsed part, 1 measure).

## Layout

```
index.html            practice UI shell
app.js                MusicXML parse + OSMD render + Tone.js voices + interaction
style.css             dark theme
vendor/               opensheetmusicdisplay.min.js, Tone.js
content/              MusicXML scores
omr/                  OMR pipeline: source PDFs, rendered pages, oemer output,
                      Playwright screenshot helper (shot.mjs), SOURCES.md
```
