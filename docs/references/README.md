# Byzantine notation references (St. Anthony's Monastery)

Source hub: https://stanthonysmonastery.org/pages/writing-with-byzantine-notation

| File | What it is |
|---|---|
| `ByzOrthography.pdf` | **106 Rules of Byzantine Music Orthography** (English, 27pp) — formal rules for accented syllables (vareia/petaste/psifiston selection), upbeat characters (antikenoma placement), and ~100 more, with correct/wrong examples and per-scribe exceptions (Hourmouzios, Stephanos, …). The rule base for the analytical-rendering engine and for orthography-validating OMR output. |
| `ByzOrthographyGreek.pdf` | Same rules in Greek (nuances of the original terminology). |
| `ByzMusicFonts.zip` / `ByzMusicFonts/` | The **EZ font package** — the very fonts the Karam scores are set in. `Fonts/*.ttf` (EZ Psaltica, Special-I/II, Fthora, Oxeia, Omega) enable *typing* correct orthography (e.g. bracketed melismatic interpretations) instead of crop-pasting; also enable synthetic training data for the neume detector. |
| `ByzMusicFonts/EZ-CharacterTables.pdf` | **The authoritative keystroke→glyph legend** (cp = 0xF000 + ASCII). Confirms chanter identifications of 2026-08-17: `)`=0xf029 yporrhoe, `d/D`=0xf044 digorgon two-step staircase, gorgon s/S pair, dotted gorgon h/H. TODO: full cross-check of our extraction legend against these tables — e.g. `\` appears to be the VAREIA (0xf05c currently assumed "barline" in the exclude list). |
| `ByzMusicFonts/Editor (optional)/EZcoduri.txt` | Editor's code list — machine-readable-ish keystroke reference. |
| `ByzMusicMacros.pdf` | The Word macros' automatic alignment semantics (how marks position relative to neumes — relevant to zero-width modifier offsets). |
| `ByzMusicFontsComparison.pdf` | EZ vs ED Psaltica font comparison. |

## concerning-notation/
The 24 images from https://stanthonysmonastery.org/pages/concerning-notation ("Concerning Adaptation of Byzantine Chant" — ten adaptations of «Κύριε ἐκέκραξα» compared across languages/traditions; the images broke on the live page because they still point at the dead `music.stanthonysmonastery.org` subdomain — they live on at `music.samonastery.org/Vespers/Adaptation/`). Key ones: `zoe4.gif` (Petros the Peloponnesian original), `Petros.jpg` (1820 Ephesios in OLD notation), `pringos4.GIF` (Pringos 1952), `HTM4.GIF` (Holy Transfiguration), `doohickey.GIF` (comparative summary). Relevant to the analytical-rendering work: real examples of the same melody re-notated at different fidelities/traditions.

Vendored from https://github.com/neanes/sbmufl (trimmed: kept fonts/, metadata/, scripts/, sources/ez + name data; upstream has full docs/tutorials).
