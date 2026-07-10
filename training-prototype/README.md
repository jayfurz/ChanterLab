# ChanterLab — Choir Training (SATB) prototype

A standalone, no-build spike of the choir-practice experience: render a 4-part
SATB score, pick your voice, mute it in playback, follow your gold-highlighted
part with a cursor, and **sing it into the mic while the singscope shows your
pitch hitting the gold notes**. See the full plan in
[`../docs/choir-training-roadmap.md`](../docs/choir-training-roadmap.md).

Live at [chanterlab.com](https://chanterlab.com) (root-mounted there) and at
`https://byz.alwaysdobetterllc.com/training/` (legacy path) — both served
from this directory via the `web/training` symlink.

## Run

```sh
# from this directory
python3 -m http.server 8791
# open http://localhost:8791/
```

Everything is client-side. OpenSheetMusicDisplay and Tone.js are vendored in
`vendor/`; no npm install needed.

## What it does

- **S | A | T | B** selector — tap your voice (48px tap targets on mobile).
- Selected voice noteheads turn **gold (#d4af37)**; the other voices dim to gray.
- A **gold follow cursor** advances through the score as it plays, and the
  score container **auto-scrolls to keep the cursor in view**.
- Your voice is **muted** in the audio mix (each voice is its own synth) so you
  sing it — toggle "hear my part" to un-mute.
- **Tempo** slider and **loop a measure range** for drilling a passage.
- **🎤 Singscope** (`scope.js`): tap Mic → a piano-roll lane shows your voice's
  target notes in gold scrolling toward a fixed now-line; your live pitch draws
  as a cyan trace. Within **±50 cents** of the active target — **octave-tolerant**
  (sung pitch is folded to the octave nearest the target, so an octave-down
  bass or octave-up soprano still matches) — the trace and the note-name/cents
  readout **glow gold**: the "hitting the note" moment. Other voices appear as
  faint context bars; a dashed line marks the loop end.
- **Mobile-first**: on phones the singscope is the prominent element (~38vh)
  and the score collapses to a scrollable mini view; verified at 360/390 px.

### Pitch detection — what it is and why

Plain-JS **autocorrelation** (cwilso-style ACF, parabolic peak interpolation,
RMS noise gate, peak-confidence gate, median-of-3 + EMA smoothing) on a
2048-sample `AnalyserNode` window, evaluated per animation frame. This was the
deliberate works-tonight choice: the app's Rust/WASM detector lives in the
`pkg-worklet` bundle and needs the AudioWorklet plumbing to host it — swapping
it in later only replaces `detectPitch()` in `scope.js`.

Honest numbers: 2048 samples @ 48 kHz ≈ **43 ms** analysis window + ≤16 ms
rAF + smoothing ≈ **~80–120 ms** perceived latency; detection range 60–1100 Hz;
accuracy after interpolation is comfortably better than the ±50¢ hit band for
a steady sung tone. Known weaknesses: soft onsets get gated, low bass (< ~80 Hz)
can wobble an octave before the median filter settles, and speaker playback can
bleed into the mic (echoCancellation is on; **headphones recommended**).

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
scope.js              singscope: JS autocorrelation pitch detection + piano-roll canvas
style.css             dark theme, mobile-first responsive
vendor/               opensheetmusicdisplay.min.js, Tone.js
content/              MusicXML scores
omr/                  OMR pipeline: source PDFs, rendered pages, oemer output,
                      Playwright screenshot helper (shot.mjs), SOURCES.md
```

Screenshot helper (headless chromium, incl. mobile emulation + fake-mic):

```sh
node omr/shot.mjs http://localhost:8765/training/ out.png S \
  --mobile --mic --click="#micBtn" --play --viewport-only
```
