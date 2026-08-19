# eothinon-11 piece workdir

Chanter-verified alignment dataset + full pipeline for the Eleventh Matinal
Doxastikon (Karam, EZ fonts). Audio (`master.wav`, trimmed to 4:24.02; raw
backup `master_full.wav`) and rendered reels are kept on disk but out of git —
regenerate the annotator data with `tools/chant-reel/annotator/prep_annotator.py`
and the reel with `render_par.sh` in this directory. Ground truth lives in
`../exports/eothinon-11-plagal4/` (timing anchors, pitch-ghost labels,
melisma boundaries); `pitch_ghosts_classified.json` and
`analytical_interpretations.json` here carry the chanter's taxonomy and
melisma spellings.
