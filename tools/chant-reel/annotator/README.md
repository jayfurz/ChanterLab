# Chant Alignment Annotator

Interactive ground-truth editor for the chant alignment pipeline
(see `../DESIGN-V2-ALIGNER.md`): shows the MCR-extracted score against the
audio timeline; the chanter drags note/syllable boundary markers to correct
times and exports them as **hard pins** — the aligner's eval set.

It also renders the machine's *interpretation* of each glyph (name, beats,
gorgon / duration / quality marks, expected degrees, ison) in a lane under the
score strip so extraction errors can be spotted and flagged.

## Run

```sh
# 1. prepare data from a piece's working directory (any pipeline scratch dir)
python3 prep_annotator.py --input /path/to/piece-workdir --piece-id my-piece

# 2. serve this directory (do NOT use port 8765 — it is taken)
python3 -m http.server 8777

# 3. open http://localhost:8777/
```

`prep_annotator.py` expects the standard chant-reel pipeline filenames inside
`--input` (`score_notes.json`, `slots.json`, `strip.png`, `line_centers.npy`,
`master.wav` required; `timing.json`, `modifiers.json`, `expected_degrees.json`,
`ison_timeline.json`, `moria_track.npy`, `barlines.json` optional). Every
filename can be overridden with a flag (`--audio`, `--slots`, ...), so the tool
is reusable for future pieces: re-run the prep with a different `--input` and
`--piece-id`. Per-piece interpretation constants (gorgon/duration codepoint
sets, `WEIGHT_OVR`, `SUBW_OVR`) sit at the top of the script and mirror
`note_align5.py`; the prep verifies its slot expansion against `slots.json`
and warns on mismatch.

## UI

- **Top — score ribbon**: the strip, one horizontal band (lines concatenated
  left-to-right), horizontally scrollable. Under it the **MCR lane**: one badge
  per glyph — short name, beats (`½+½`), `G`=gorgon, `K/A/D`=klasma/apli/diple,
  `ant/oma/psi` quality marks, `+n` unclassified attached marks. Click a glyph
  (strip or lane) to inspect it; double-click to seek. The playing glyph
  highlights yellow; the selection blue. Flagged glyphs get a red border.
- **Detail panel** (right): zoomed crop of the glyph off the strip (red box =
  MCR bounding box) next to the full machine record, its slots (machine vs
  corrected time, pin state), and a **Flag MCR error** button with a free-text
  note — this is the extraction-bug queue.
- **Middle — timeline**: waveform + pitch curve (green, moria vs the
  scale-degree grid) + ison level (dashed orange) + playhead. One vertical
  marker per slot, labelled `glyph-index word`; sub-note markers start lower.
  Blue = machine time, amber = corrected, red + flag = pinned.

## Controls

| action | effect |
|---|---|
| `space` | play / pause |
| click waveform | seek |
| drag marker | correct that slot's time (**auto-pins** — a correction is ground truth) |
| wheel | zoom around cursor; `shift`+wheel / horizontal wheel / drag empty area | pan |
| `←` / `→` | nudge selected marker ±50 ms (pins it); with no selection: seek ±2 s |
| `L` | loop the selected slot's span (toggle) |
| `P` | toggle pin on selected marker |
| `R` / Reset marker | drop correction + pin on selected marker |
| `Esc` | deselect · `Home`/Fit: zoom to piece · `F`/checkbox: follow playback |

All edits autosave to `localStorage` (keyed by `--piece-id`) and survive
reloads. **Clear all** discards them.

## Export

The **Export** button downloads three files:

- **`pins.json`** — the aligner's MANUAL format, exactly
  `[[glyph_index, time_seconds], ...]` sorted by time, one entry per *pinned*
  slot. Feed into `note_align*.py` as `MANUAL = [(gi, t), ...]` (the aligner
  maps a glyph pin to that glyph's first slot). Only `sub == 0` slots are
  exported here, because MANUAL semantics are glyph-start; pins placed on
  sub-note markers are preserved in `slots_corrected.json` (the status bar
  reports how many).
- **`slots_corrected.json`** — full fidelity:
  `{piece_id, t (corrected), gi, sub, machine_t, edited[], pinned[]}`.
- **`mcr_flags.json`** — `[{gi, note}, ...]`: glyphs the chanter marked as
  MCR extraction errors, with notes; these become extraction-fix work items.

## Known limitations

- The psifiston codepoint for the EZ-Psaltic font is not yet confirmed;
  until `PSIFISTON_CPS` in `prep_annotator.py` is filled in, psifiston shows
  up under a glyph's `other marks` (as its hex codepoint) rather than by name.
- Dragging keeps markers monotone (clamped between neighbours); to move a
  marker past its neighbour, move the neighbour first.
- The page must be served over HTTP (fetch + WebAudio do not work from
  `file://`). Waveform appears a few seconds after load (48 MB WAV decode).
