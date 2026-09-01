# Chant dataset + MCR plan — from the Vasilikos tapes to four products

Written 2026-09-01. Owner's framing: *"a perfect byzantine music dataset with
MCR so that we can do several things — score-aware music notation highlighting
via video, automatic transcription in greek/english (eventually arabic too, and
slavonic), melismatic analytical scores, as well as a generative audio model
trained to give authentic chants based off of byzantine OCR."*

Status: **ready**. Roadmap IDs: `DS`, `LAB`, `SCR`, `ALN`, `EAR`, `CUT`, `OMR`,
`LANG`, `ANA`, `GEN`, `OPS` (defined in §3). Feeds `60-one-app` (neume mode)
and `70-expansion` (raster OMR). Depends on `CHANT-NN-ROADMAP.md` and
`NEURAL-CHANT.md`; supersedes neither — it sequences them against the four
products and adds the lanes they do not cover (dataset build, raster OMR,
languages, generation).

**The verdict this plan is built on: the models are ahead of the data
plumbing.** On the one fully hand-cut tape the cascade meets the release gate.
Everything else is throttled by chanter minutes, by an aligner that only works
where a note-for-note parallagi exists, and by a dataset that lives in six
places instead of a versioned build.

---

## 0. Verified today (2026-09-01) — what the plan docs do not yet say

| fact | value | how verified |
|---|---|---|
| Martyria checksum | **53 satisfied / 5 violated (9 %), `martyria_check.py` exit 0** | run today. NEURAL-CHANT §1.1, DECIDE-01-BRIEF and memory still say 26/58 and "NN-03 blocked". **The `< 8` gate is met.** The 2026-08-21..24 notation rulings (ypsili left/right, kentima height, apostrofos-in-petasti, `3|4ab`) closed it |
| Chanter-timed onsets in the registry | 9 COMPLETE pieces = **760 notes**, + t03 75 (burnt) + eothinon-11 259 + s01 37 partial ≈ **1,130** | `gold_times.COMPLETE`, export dirs |
| Chanter exports **outside** the registry, all 2026-08-24 | mode1 `dogmatic-theotokion-lihc` melos 338 + parallagi 338; mode2 `kyrie-ekekraxa` melos 139 + parallagi 139; mode2 `katefthynthito` 94; mode2 `thou-kyrie` 667; mode2 `thou-kyrie-par` 30 partial | chant-annotator worktree `datasets/exports/`. Every slot `pinned: true` except thou-kyrie-par. **No verdict is recorded anywhere machine-readable** |
| Mode-2 lihc | pieces prepped 08-24 17:51, machine-seeded 08-25 10:59, **no export on the server** | annotator `data/` mtimes. If it was pinned, it is in the browser's localStorage autosave only |
| `gold_times.COMPLETE` | hard-coded tuple, last edited 08-23; the worktree copy has 3 entries vs main's 9 | diff |
| Melos onset transfer lock reports | mode 1 vespers: **2 of 16** pieces ≥ 0.9 agreement; mode 2: **1 of 11** seed-ready | `models/mode{1,2}_pipeline/pred.lock_report.json` |
| Neural cutter on the other tapes | **0 of 16** pass the pairing checksum (parallagi under-called) | CHANT-NN-ROADMAP §S1-03 |
| Provenance | `corpus.json` carries only `path/name/dur_s/size`; **37.4 h, 264 recordings, one singer** | corpus.json |
| Score-unit count | **116,043** (NEURAL-CHANT) vs **115,826** (UNIFY-ANNOTATOR) — unreconciled | both docs |
| Annotator pieces | **271** | `data/index.json` |
| GPUs | both 3090s held by the qwen tenant (18.5 / 17.5 GB of 24 used) | nvidia-smi |
| Raster OMR | **neanes/byzantine-chant-ocr** (GPL-3, MobileNetV2 on contour crops) is trained on the **Ioannou Anastasimatarion 1905, Ioannou Heirmologion 1903, Karamanis Liturgy 1990, St Anthony's English Vespers 2006**; outputs `.byzocr` → Neanes → SBMuFL, which `web/score/glyph_import.js` already reads | its SOURCES.md, README |
| Multi-singer data | **DAMASKINOS** (Univ. of Athens): 20 professional chanters, scale exercises per mode + read texts, tagged at syllable / notation-character / expected-pitch / performed-pitch / transcription levels; by request | literature |

Standing numbers this plan inherits (unchanged, sources in the named docs):
melos onsets from the parallagi template **92.1 / 94.1 % in gate, 0 slips,
held out cross-melody** (CHANT-NN-ROADMAP §S4b-02); diatonic degree per onset
**98.1 %** LOO; chromatic ear **7/14 classifier vs 11/14 quantiser**;
identification **21/23** grave, **10/11** mode 2 with drop-cap candidates;
FA character path **55.3 %**; pure-audio glyph recognition **0.467**; ornament
detector **AP .435, recall .32 on 34 examples**; whisper misses **55 %** of
sung audio; old EM alignment **173 hymns, 0.930 strict, 66.7 % coverage** on an
event layer with **63 % recall and 57 % spurious events** (silver, not
training grade for onsets); GLT text matched for **157/173** hymns.

---

## 1. The four products and the layers each needs

```
                     cut   lane   identify   onsets   degrees   ornaments   lyrics   provenance
 follow-along video   ●     ●        ●         ●●       ○          ○          ○         ○
 transcription        ●     ●        ○         ●        ●●         ●          ●●        ○
 analytical scores    ●     ●        ●         ●●       ●          ●●         ○         ○
 generative audio     ●     ●        ●         ●●       ●●         ●          ●●        ●●
                                                          ●● = the layer that decides quality
```

- **Follow-along** needs onsets at the release gate on *every* piece, not on
  the grave tape. Blocker: the template-free aligner (ALN).
- **Transcription** is audio → neume stream + lyrics. Pure-audio glyph
  recognition sits at 0.467 because sung intervals are ambiguous at ±0.5
  step; the fix is context — a neume language model plus the martyria
  checksum — not a better per-note classifier (SCR-04, ALN-02). Lyrics need a
  chant-adapted ASR (LANG-01); other languages need recordings that do not
  exist (LANG-03).
- **Analytical scores** need ornament labels at scale (ANA-01) and the
  orthography rules as a typesetter (ANA-02).
- **Generative audio** consumes the release: phoneme timing, pitch in cents on
  the genus ladder, durations, ornaments, and a provenance field that does not
  exist yet (DS-01, GEN-02).

Everything above reads the same dataset. That is why lane DS comes first.

---

## 2. Principles carried over (do not re-derive)

1. No onset enters gold without the chanter. Machine onsets are silver; they
   train, they never grade. `onset_eval.py` is the only scorer.
2. A seed is judged by its worst run, not its mean — never hand over a seed
   with a slip.
3. Never score by CTC loss or movement agreement. Score with `name_check.py`,
   `slip_check.py`, `martyria_spans.py`, and pins.
4. Chanter cuts are truth; machine cuts are drafts that fill blanks.
5. s01 is the sealed test fold, touched once, versioned `s01@<date>`.
6. Read the chanter's existing exports before asking a question.

---

## 3. Lanes, items, gates

Sizes: S ≤ 1 day, M ≤ 1 week, L > 1 week. "Needs" lists hard dependencies.

### Lane DS — the dataset as a build product

- **DS-01 (S) Provenance at ingest.** `corpus.json` records gain `singer`,
  `school`, `source`, `tape`, `language`, `rights`, `sha256`, `sample_rate`;
  backfill all 264 as `vasilikos / greek`. *Gate:* a validator refuses any
  recording without a checksum; nothing lands untagged (this executes
  NEURAL-CHANT ATTR-01).
- **DS-02 (M) Gold registry.** Replace the `gold_times.COMPLETE` tuple with
  `datasets/gold_registry.json`: piece id, lane, mode, genus, n_notes,
  verdict (`gold` / `approved-by-ear` / `draft` / `untrusted`), verdict date,
  the chanter's words, export sha256, audio sha256. Ingest the 2026-08-24
  exports with the owner's verdicts (§5). *Gate:* `gold_times.py`,
  `onset_eval.py`, `parallagi_class.py` and `melos_onset_net.py` read the
  registry; the tuple is deleted; the worktree cannot diverge.
- **DS-03 (L) `tools/corpus/build_dataset.py`.** Emits
  `releases/chant-<date>/` with a manifest and one record per piece: audio
  span + checksum, score range (page, line, unit), lane, genus spans,
  score-variant regions, onsets with a trust tier (`gold` /
  `approved-seed` / `seed` / `silver`), degrees, f0 and RMS tracks, lyrics
  with the FA character path, martyria spans. *Gate:* bit-reproducible from a
  git tag; `--report` regenerates every number in §0 and in
  CHANT-NN-ROADMAP §5.
- **DS-04 (M) Validators in the build.** Pairing alternation per tape,
  martyria checksum per piece, timebase (audio checksum vs every FA / pin
  artefact), unit count = pin count, gold immutability (a build that would
  move a gold onset fails), `legend_canon.rules_rev`. *Gate:* runs on every
  push; the 116,043 vs 115,826 discrepancy is resolved and recorded.
- **DS-05 (S) `legend_canon.json` under version control** with tests and a
  `rules_rev` assertion in every reader. *Gate:* a stale worktree can no
  longer revert it.

### Lane LAB — chanter labels: registry and queue

- **LAB-01 (owner, S) Verdicts on the unregistered exports** — see §5. Recover
  mode-2 lihc from the browser autosave if it was pinned (open the piece in
  the same browser, press Export).
- **LAB-02 (M) The review queue.** Only seeds that pass all three readers
  reach the chanter: ensemble lock ≥ 95 % agreement, longest run ≤ 3,
  monotonic; `slip_check` CLEAN ≥ 0.9; `martyria_spans` pass. The queue
  routes **unit ranges**, not pieces, ordered by information value. *Gate:*
  the queue is a build output; no slipping seed is ever shown.
- **LAB-03 (chanter, ~1 h total) The three asks.** (a) one more hand-cut tape
  in a chromatic mode — unlocks CUT generalisation; (b) s01 finished (58
  slots) — the sealed test; (c) mode-2 lihc exported. A new mode-2 parallagi
  pin request is **not** needed if LAB-01 rules `kyrie-ekekraxa-par` gold.
- **LAB-04 (S) PIN-REPEAT-01.** 20 notes of t03 re-pinned blind; report
  signed differences, stdev, p95. *Gate:* an annotation floor exists; it sets
  the label-smoothing width and forbids any claim tighter than it.

### Lane SCR — score side

- **SCR-01 (S) Record the passed gate.** Update NEURAL-CHANT §1.1 / §10,
  DECIDE-01-BRIEF and `legend_canon_shared_artefact` memory: CHECK-01 met at
  53/58. NN-03 (silver dataset) is no longer blocked by it.
- **SCR-02 (M) Stage B unit segmentation, then one pin remap.** Black-klasma
  beats, kentimata two-note (41 figures still unruled: 23 ypsili, 2 running
  elafron), syneches-elaphron proximity decoder, rest compounds,
  martyria-checksum decode of ambiguous figures, role-driven base election
  (the open half of DECODE-01), clusters 26 / 29 reviewed (Gate C). These
  shift unit indices, so they land together, followed by one
  `reindex_*`-style remap of every pin and a re-freeze of every gold set with
  checksums. *Gate:* violations stay < 8; all gold pieces pass
  `martyria_spans`; unit counts reconciled.
- **SCR-03 (M) NN-01 vocabulary frozen.** Factored tokens per NEURAL-CHANT §3;
  round-trip exact on every unit; dropped distinctions recorded. Free today,
  unrecoverable later.
- **SCR-04 (M) Neume language model.** Autoregressive over the whole
  Anastasimatarion, the Heirmologion (after OMR-02) and the 93 chant-guide
  scores; per-token surprise as an extraction-error detector and the decoder
  prior for ALN-02 and GEN-01. *Gate:* held-out perplexity reported; of the
  top-100 surprise flags on 20 pages, at least half are real extraction
  errors, or the detector is dropped.

### Lane ALN — alignment at scale

- **ALN-01 (M) Own-voice synthetic parallagi.** Most of the corpus has no
  note-for-note parallagi (mode-1 vespers is abbreviated by the chanter's
  ruling; cherubic hymns, canons and doxologies have none; s01 has none).
  Build the template instead: concatenate gold parallagi note samples in
  the singer's own voice per the score's degree and `beats_seq` sequence,
  then run the existing `melos_onset_net` DTW unchanged. *Gate:* on s03 and
  s05 with their real parallagi withheld, ≥ 85 % in gate and 0 slips; on
  mode-1 vespers, a seed-ready count that is > 2 of 16.
- **ALN-02 (L) The encoder-decoder** (NEURAL-CHANT NN-02..NN-06), gates
  unchanged. Its blockers are now only LAB-04 and SCR-03. s01 is touched once.
- **ALN-03 (M) Corpus-wide onset run.** For every piece the best aligner by
  structure (real template / synthetic template / encoder-decoder), with lock
  and slip verdicts and tiers written into the release. *Gate:* seed-ready
  fraction reported per mode; ≥ 70 % of pieces seed-ready before the chanter
  pass starts.
- **ALN-04 (S) Follow-along from the release.** The reel renderer, the book
  view and the timed-score adapter (`contract/from_chant.js`) read release
  onsets. *Gate:* one video per gold piece regenerated from the release alone.

### Lane EAR — chromatic genera

- **EAR-01 (S) Measure what already exists.** Hold out the 2026-08-24 mode-2
  `kyrie-ekekraxa-par` pins (139 notes) and evaluate the classifier, the
  quantiser and their fusion. Record in CHANT-NN-ROADMAP §5. *Gate:* a
  held-out soft-chromatic number exists.
- **EAR-02 (M) Genus-conditioned ear.** Cents-from-base channel (S5-03),
  genus conditioning, per-span genus annotation (pthora spans) replacing the
  per-row field, and augmentation by re-laddering diatonic gold notes onto
  the chromatic ladders (parallagi notes are sustained, so the shift is
  exact). *Gate:* ≥ 90 % held out on a chromatic parallagi; mode-2
  identification stays ≥ 10/11.
- **EAR-03 (M) Attraction model.** Per-degree cents residual against phrase
  context, learned from gold; this is the byzorgan attraction engine's
  training signal and GEN-02's pitch target. *Gate:* explained variance of
  the residual reported; the Ζω/Κε band ambiguity on the pitch-ghost
  regression set reduced.

### Lane CUT — cutting and lanes across all tapes

- **CUT-01 (S) Checksum as self-calibration.** Per-tape lane-threshold
  recalibration so the sequence alternates; lane from the degree
  classifier's mean confidence; re-run `separate_pieces_nn.py` on all 16
  tapes. *Gate:* ≥ 12 of 16 tapes pass alternation; the rest listed with the
  offending span.
- **CUT-02 (M) Adoption with re-freeze.** Adopt per tape only after the
  checksum passes and the chanter has adopted the ghost drafts in the book
  view; shift pins by each hymn's start delta; re-freeze golds. *Gate:* no
  gold onset moves without a recorded delta.

### Lane OMR — raster scores, without building an OMR

- **OMR-01 (S) Evaluate neanes/byzantine-chant-ocr.** Run it on five pages
  of the scanned liturgy anthology (`E8B593F3AAED0BC6.pdf`) and five pages of
  the Ioannou scan; import `.byzocr` → Neanes → SBMuFL → `glyph_import`;
  compare against the vector atlas units (Ioannou) and the chanter's ear
  (anthology). *Gate:* a per-page glyph agreement number and a go / no-go on
  adopting it versus training our own.
- **OMR-02 (M) The Heirmologion.** Same tool on the Ioannou Heirmologion,
  which onboards the Prosomia tape (its 7 parallagi are already labelled).
  *Gate:* the prosomia workdir gets score ranges and first alignments.
- **OMR-03 (M) Extend it with our glyphs.** Render the 178k vector glyphs at
  224×224 with blur / skew / bleed into its class folders (atlas → its class
  names), retrain, measure on the anthology. *Gate:* accuracy on the anthology
  above the OMR-01 baseline. Contribute upstream if it holds.

### Lane LANG — lyrics and languages

- **LANG-01 (M) Chant-adapted Greek ASR.** Fine-tune
  `wav2vec2-large-xlsr-53-greek` on chanter-cut melos spans paired with GLT
  text (≥ 157 hymns, free pairs). *Gate:* FA character-path in-gate rate on
  t03 and the gold melos rises above 55.3 %; WER on held-out spans reported.
- **LANG-02 (S) Language-agnostic forced alignment.** Add torchaudio's MMS
  forced aligner (romanised text) as the path for non-Greek text; score
  Eothinon 11 (English) against its 259 onsets. *Gate:* an English FA number.
- **LANG-03 (owner) Arabic and Slavonic.** Zero recordings exist. Recruit one
  chanter per language with a matching book; DS-01's language field is ready.
  No modelling before data.

### Lane ANA — analytical melisma scores

- **ANA-01 (M) Ornament labels from the pair difference.** On note-for-note
  tapes, melos notes absent from the parallagi rendition are the
  sung-but-unwritten notes; emit candidates with pitch and duration, chanter
  verifies a sample. *Gate:* ≥ 500 ornament examples; detector AP above the
  .435 baseline.
- **ANA-02 (M) Typesetter v2.** The 106 orthography rules as constraints;
  `compose_analytical.py` generalised beyond eothinon-11; flagged choices to
  the chanter. *Gate:* 10 melismas typeset and approved.
- **ANA-03 (S) Parallel highlighting** of the bracketed figure in the reel and
  the annotator.

### Lane GEN — generation

- **GEN-01 (M) Symbolic.** SCR-04 plus a text encoder generates notation for a
  new text in a given mode; validators = martyria checksum + 106 rules;
  chanter rates 10 samples. *Gate:* ≥ 8 of 10 rated "could be in the book".
- **GEN-02 (L) Audio.** Score-conditioned singing-voice synthesis fine-tuned
  on the release: phonemes from the FA character path, pitch in cents on the
  genus ladder (not MIDI), gold / approved durations, ornaments; the cents
  residual from EAR-03 as the έλξεις target. Do not train an audio model
  from scratch. *Gate:* chanter ABX on held-out hymns; the pipeline's own
  onset and degree readers re-measure the synthesized audio (the closed loop
  turned on the generator).
- **GEN-03 (owner) Second singers.** DAMASKINOS request; the other tapes on
  gdrive; every ingest through DS-01. "Authentic across schools" is
  impossible with one singer.

### OPS

- **OPS-01 (S)** `make dataset` and `make eval` as single commands with the
  GPU-lease wrapper; nightly on the box; results to the release dir.
- **OPS-02 (S)** Long batches in foreground chunks (background tasks get
  phantom-killed here).

---

## 4. Sequencing

| wave | items | why this order |
|---|---|---|
| **1 — now** | SCR-01, LAB-01, DS-01, DS-02, EAR-01, OMR-01, CUT-01, ALN-01 prototype | all unblocked today; three of them are one-day measurements that change later asks |
| **2** | DS-03, DS-04, DS-05, SCR-02, LAB-02, LAB-03, LAB-04, ALN-03, LANG-01, LANG-02, OMR-02 | the build and the remap must exist before pins scale; SCR-02 shifts indices, so it lands before ALN-03 and LAB-02 |
| **3** | SCR-03, SCR-04, ALN-02, EAR-02, EAR-03, ANA-01, ANA-02, CUT-02, OMR-03 | models on top of a reproducible release |
| **4** | ALN-04, ANA-03, GEN-01, GEN-02; LANG-03 and GEN-03 as data arrives | the products |

Critical path: **DS-02 → SCR-02 → ALN-03 → LAB-02 → GEN-02.** The chanter's
minutes bind everywhere; LAB-02 exists so each minute buys the most.

---

## 5. Owner decisions needed

Collected at **`https://annotator.lab.alwaysdobetterllc.com/d`** (annotator route
`/d`, content in `tools/chant-reel/annotator/d/decisions.json` on the
chant-align-dataset branch). Answers are written to the chant-annotator
worktree's `datasets/exports/decisions/answers.json` with history copies;
DS-02 reads the `verdict:*` answers into the registry.

1. **Verdicts** for the 2026-08-24 exports: mode1 lihc (melos, parallagi),
   mode2 kyrie-ekekraxa (melos, parallagi), mode2 katefthynthito, mode2
   thou-kyrie, mode2 thou-kyrie-par (30 of many). Gold, approved by ear, or
   draft? Without a verdict they cannot enter the registry.
2. **Mode-2 lihc**: was it pinned? If yes, export it from the browser that
   holds the autosave. The row's genus is also unset.
3. **Chanter time**: agree the three asks in LAB-03.
4. **Melodos**: record playback on the Windows laptop as reference audio, or
   drop it.
5. **DAMASKINOS**: send the request email.
6. **Languages**: who chants Arabic and Slavonic for us, and from which books.

---

## 6. Non-goals

- OCR on the vector Ioannou book (`extract_book.py` reads it exactly).
- Training a raster OMR from scratch before OMR-01 reports.
- A from-scratch audio language model.
- Retuning the RMS cutter or using whisper as a primary signal.
- Any machine onset entering gold; any hyperparameter chosen on s01.
- Style personas before a second singer exists.

## 7. Owned files and parallel safety

Lanes are disjoint except: DS-03 rewrites the readers of every label
source (serialize after DS-02); SCR-02 shifts unit indices (serialize before
ALN-03, LAB-02, CUT-02); CUT-02 changes timebases (re-freeze golds inside the
same PR). New code lands under `tools/corpus/` and `tools/neural/`; the
registry and releases under `datasets/`; the external OMR tool in its own
checkout, never vendored.

## 8. Verification, rollback, handoff

- Every item reports through the existing scorers; every number in this plan
  is regenerated by `build_dataset.py --report` once DS-03 lands.
- Rollback: releases are immutable directories; golds carry checksums; a pin
  remap keeps the pre-remap export beside it (`.prekentimata.bak` pattern).
- Handoff per item: the number, the script that produced it, and the release
  tag it was measured on, appended to CHANT-NN-ROADMAP §5.
