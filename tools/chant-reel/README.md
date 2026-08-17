# chant-reel: score-aligned chant video + dataset pipeline

Turns (born-digital chant PDF + solo recording) into a TikTok-ready reel with
per-note score following, a live parallagi ladder, and a score-aligned dataset
(`datasets/mcr/`). Built 2026-08-16 against the Eleventh Eothinon (EZ fonts, Karam).

## Stages

1. `extract_glyphs.py` — PDF text layer → note glyphs + lyric word anchors in
   line-strip pixel coords (EZ fonts: codepoint = 0xF000 + keystroke; barlines
   bareia stavros excluded; red = martyria/fthora; zero-width = modifiers).
   Also emits modifiers (gorgon 0xf053, klasma 0xf061/41, apli 0xf027, dipli 0xf022).
2. `voice_segment.py` — recording → note events (f0 @10ms, onset/pitch splits, breath gaps).
3. whisper (openai CLI, `--word_timestamps True`) + `convert.py` + `align.py` —
   lyric word times; melisma-late words corrected downstream.
4. `note_align5.py` — beat-weighted slots (gorgon steals 0.5 from previous;
   klasma/apli=2, dipli=3; yporrhoe & kentimata compounds = 2 sub-notes) +
   manual/breath pins + pitch-aware DTW with EM interval learning.
   Emits slots.json, ornaments.json (sung-but-unwritten quick notes),
   learned_intervals.json, and rewrites timing.json (captions/lines from slot times).
5. ladder track (see session scratchpad / dataset meta) — per-frame parallagi
   degree with Ζω♭/Κε↑ attraction (diatonic only), soft-chromatic chroa spans,
   time-varying root for intonation drift.
6. `render.py` — 1080x1920@30 renderer. Env flags: `REEL_V2=1` per-note pill,
   `REEL_LADDER=1` parallagi ladder. Audio master: highpass/EQ/comp + shimmer
   bell at H6-H12 of the voice + `make_cathedral_ir.py` convolution + loudnorm.

Paths inside scripts are session-relative (line strips, wavs); parameterize when
running on a new piece. See `datasets/mcr/README.md` for the dataset contract and
GitHub issue #136 for the roadmap (Anastasia legend, attraction engine, compiler A/B).
