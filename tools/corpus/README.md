# Vasilikos corpus alignment pipeline

Aligns the Theodoros Vasilikos tape archive (all 8 modes, parallagi + melos)
against the born-digital Ioannou Anastasimatarion, producing note-level
audio↔notation alignments for MCR training.

## State (2026-08-18, final)

Complete alignable corpus: **173 hymns, 10,108 pairs, 0.912 strict at 64.7%
coverage** — all 8 modes, vespers + orthros + compunction + syntomon, on
131 DTW-VERIFIED parallagi anchors (adjacency wiring was audited out:
65/99 mispaired). Anchored workdirs: 0.934-0.942; best hymns 0.97-1.00.

**Why 0.912 is the autonomous ceiling**: correcting existing pairs needs
ground truth (chanter verification); added material arrives at <=0.942 and
cannot lift the average to 0.95. Awaiting: Xatzichronoglou tapes (not on
gdrive), annotator verification pass, Heirmologion PDF, or image-MCR for the
scanned liturgy anthology (E8B593F3AAED0BC6.pdf, identified). Resume with
`selftrain_round.sh <tag>` when any input lands.

## Architecture (what won)

```
extract_book.py      673-page PDF -> 178k glyphs -> 94 exact shape clusters
book_map.py          mode sections, TOC-verified page ranges
separate_pieces.py   hour tapes -> parallagi/melos/speech pieces
slice_transcript.py  tape whisper JSON -> per-piece transcripts
locate_tracks.py     piece text -> (page,line) hymn ranges (drop-cap-stripped,
                     melisma-collapsed fuzzy match; monotonic-order cleanup)
parallagi_dataset/align.py  ASR degree syllables + genus ladders + drone-skip
                     -> absolute degree labels (0.8-1.0 agreement when clean)
classify_parallagi.py CNN syllable labels where whisper fails (the bootstrap:
                     51%-accurate CNN + joint pitch DTW -> 0.84+ anchors)
hymn_align.py        the aligner: units from glyphs; legend (unit-key ->
                     interval) EM-learned from parallagi supervision (atlas
                     seed REQUIRED — zero init provably degenerates); melos
                     DTW with absolute unitdeg anchors, martyria anchors,
                     duration priors, drone-skip, empirical center refit
                     (accept only on agreement — costs aren't comparable
                     across quantizations); vectorized (170x)
wire_anchors.py      best parallagi anchor per hymn (whisper or CNN)
dtw_conf.py          forward-backward posteriors (BETA temperature)
align_eval.py        the scoreboard (strict + cents55 columns)
```

Genus ladders: diatonic 12-10-8-12-12-10-8; soft chromatic = TROCHOS
(fifth-periodic [8,14,8,12][d mod 4], NOT octave-cyclic); hard chromatic
from Πα 6-20-4 tetrachords. Mode 2 mixes genus by genre (stichera soft,
heirmologic hard) — hymns.json 'genus' pins it; unset = hypothesis-test.

## What lost (documented so nobody retries blind)

- eothinon arc-scorer transfer: 0.33 raw; retrained on 441 silver arcs:
  0.57; at 2,530 positives from 47 hymns: **0.508 held-out** with broken
  confidence. The architecture expects word-anchor phase structure this
  corpus lacks. Retired; DTW+parallagi-anchoring is the production aligner.
- cents55 as an "attraction-tolerant" metric: raw sung intervals deviate
  30-70c from Chrysanthine theory systematically (practice, tape). It
  measures intonation-vs-theory, not alignment. Strict integer agreement is
  the alignment metric.
- Hard-negative mining, zero-init legend EM, timestamp-based parallagi
  labeling, octave-cyclic soft chromatic: all documented failures in git
  history / memory.

## Chanter-verified tape heuristics (2026-08-18, from the t03 repair)

Ground rules for any piece-boundary repair, learned fixing grave-orthros-t03
(whisper missed 21s of sung parallagi; the word-gap cutter dropped the whole
melos opening):

1. **Pieces are separated by real pauses.** Every hymn/parallagi/melos
   transition has an audible pause. Cut boundaries belong at RMS-quiet runs
   (>=1s), NEVER at whisper word gaps — whisper goes silent on melisma, so a
   word gap says nothing about where singing stops.
2. **A hymn's parallagi and melos have roughly equal duration.** A large
   mismatch (t03: 28s parallagi cut vs 53s true melos) means at least one cut
   is truncated. Use as a cheap corpus-wide diagnostic.
3. **Tape intros are not trainable.** Long tapes open with the chanter
   announcing book/page; that speech (and any melos_audio that points at a
   `speech`-kind piece) must not enter hymn material.
4. **Movement agreement can hide absolute-frame errors.** t03 scored 0.96
   in a frame one whole tone off (Νη 112.9 vs true 126.8Hz); relative deltas
   still agreed. Arbitrate frames with anchored-degree agreement (sung degree
   == parallagi unitdeg at matched units: 37/46 right frame vs 3/46 wrong).
5. **unitdeg files are slice-shaped.** They are keyed by unit index against
   the hymns.json slice they were built from; after a p/l range fix, trim or
   regenerate them (t03: orig kept as unitdeg_t03_.orig91.json).
6. **The Ioannou font prints some neume pairs SHAPE-IDENTICALLY** (t03 head,
   chanter-verified): the same cluster-6 bar is ison (96% of 1,810 supervised
   pairs) in most contexts but oligon (+1) at the t03 opening — pixel-equal
   outlines, disambiguated only by context (initial martyria, parallagi,
   the chanter). Shape-level extraction has a hard ceiling here. Chanter
   corrections land in `<wd>/iv_ovr_<hymn>.json` ({unit_index: interval},
   from annotator mcr_flags); cmd_melos and ingest_pins apply them over the
   legend. Chanter-pin sung degrees can also replace poisoned unitdeg head
   anchors directly (they are the same quantity, chanter-grade).

## Metric definition

strict = fraction of consecutive matched pairs whose sung degree delta
(quantized on the hymn's genus ladder + fitted Νη) equals the notation's
expected delta. Coverage = matched units / score units. Both reported;
accuracy without coverage is gaming.

## Compounding path to higher accuracy

1. Classifier self-training: each round of parallagi CNN retraining on the
   grown corpus -> better bootstrap anchors -> better alignments -> more
   training data. (CNN: 40.5% -> 60.4% -> 51.3%-on-30x-harder-val so far.)
2. Orthros + syntomon + remaining albums onboarding (more anchors per key).
3. Attraction engine (byzorgan): models the cents-level deviations, turning
   the cents residuals from noise into signal.
4. Chanter spot-verification via the interactive annotator on low-confidence
   hymns (the eothinon precedent: a few pins lock a piece).

## Annotator verification lane (path 4, wired 2026-08-18)

All 173 tracks are bridged into the interactive annotator
(tools/chant-reel/annotator) as individual pieces:

```
prep_hymn_annotator.py   corpus hymn -> annotator piece: strip rendered from
                         the Ioannou PDF (per-line bands, note boxes from the
                         SAME load_units stream the aligner sees), machine
                         times from aligned.json (unmatched units interpolated
                         by beat weight, labeled UNMATCHED), pitch in moria
                         rel fitted Νη, genus ladder as the degree grid;
                         maintains the picker manifest data/index.json
ingest_pins.py           annotator exports -> timing confirm/contradict +
                         strict-on-pins (ground-truth analogue of align_eval
                         strict) -> verification_ledger.json; stages
                         chanter_pins.json into each melos dir for the aligner
```

Chanter workflow: `serve.py` in the annotator dir, pick low-agreement hymns
in the piece picker, pin, Export, then `ingest_pins.py`. The
`annotator-batch` subagent (worktree `.claude/agents/`) runs prep / validate
/ ingest / record keeping end to end. Pins staged as `chanter_pins.json` are
the awaited ground-truth input for lifting 0.912 -> 0.95.
