# Glyph Import Testing Guide

This guide covers the hidden Phase 6 glyph import test panel. It is a developer/tester workflow for the source-agnostic chant import layer, not a public notation editor yet.

## Open The Hidden Panel

Use the feature-branch server, not the live `8765` server.

```sh
python3 -m http.server 8432 --bind 127.0.0.1 --directory web
```

Then open:

```text
http://127.0.0.1:8432/?scoreImport=1
```

Optional query parameters:

```text
scoreImportSample=soft-chromatic-di
scoreImportSource=glyph
scoreImportStart=Di
scoreImportBpm=84
```

Do not use port `8765` for this workflow.

## What To Test

The hidden panel appears under the Score Practice controls. On mobile it starts collapsed; tap `Import` to open it and `Hide` to return to the practice view.

1. Choose a sample, then press `Load`.
2. Confirm the target bars restart and align with the singscope crosshair.
3. Confirm pthora labels appear on pthora-bearing notes.
4. Confirm the ladder retunes when a compiled pthora event becomes active.
5. Change source mode between `Glyph names`, `SBMuFL/Neanes`, and `Unicode`, then load the matching samples.
6. Use the virtual glyph keyboard to insert quantity, rest, timing, duration, pthora, chroa, and tempo tokens.
7. Insert an unknown token such as `notAGlyph`, press `Load`, and confirm diagnostics appear without replacing the active score.

## Current Seed Samples

- `basic-ladder`: glyph-name text with quantity, gorgon, and rest tokens.
- `soft-chromatic-di`: prefix soft chromatic pthora attached to Di.
- `hard-chromatic-pa`: prefix hard chromatic pthora attached to Pa.
- `sbmufl-basic`: private-use SBMuFL/Neanes codepoint text.
- `unicode-basic`: Unicode Byzantine Musical Symbols text.

These samples live in `web/score/glyph_import_samples.js` and are compiled by `web/score/tests/glyph_import.test.mjs`.

## Supported Token Families

The virtual keyboard is generated from `listMinimalGlyphImportTokens()` in `web/score/glyph_import.js`.

Supported Phase 6 seed families:

- Quantity: `ison`, `oligon`, `apostrofos`, `yporroi`, `elafron`, `chamili`
- Rests: `leimma1`, `leimma2`, `leimma3`, `leimma4`
- Timing: `gorgonAbove`, `digorgon`, `trigorgon`, `argon`
- Duration: `apli`, `klasma`, `dipli`, `tripli`
- Tempo: `agogiMetria`, `agogiGorgi`
- Pthora: hard chromatic Pa/Di and soft chromatic Di/Ke seed signs
- Chroa: zygos, kliton, spathi seed signs

`argon` is preserved as a qualitative warning because full argon timing rewrite behavior is not implemented yet.

## Expected Checks

Run these before handoff:

```sh
node --check web/app.js
node --check web/score/glyph_import.js
node --check web/score/glyph_import_samples.js
node web/score/tests/run_tests.mjs
git diff --check
```

For browser verification, use the already-running branch server on `8432` when available. Do not stop, restart, or bind over the live `8765` server.

## Known Limits

- This is not OCR and does not parse real scanned chant pages.
- Full Byzantine orthographic generation and attraction grammar remain out of scope for this phase.
- Ison/drone events are available in chant script fixtures, but the glyph import seed layer currently treats the `ison` glyph as a quantity sign, not as a drone command.
- Real hymn editions should not be added unless source, reviewer, and copyright status are documented.
