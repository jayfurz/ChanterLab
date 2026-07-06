# Multipart Pitch Recognition Spike — score-informed ensemble verification (#84)

**Issue:** #84 (sprint-7, M3) — owner ask: recognize multiple simultaneous choir parts.
**Status:** feasibility spike complete — measurement code in `.scratch/multipitch-spike/` (not
committed, not production), this doc is the deliverable. No production files were touched.
**Verdict:** **GO** — with the score in hand, "which section is flat, and by how much" is answerable
with classical DSP at a cost the existing Rust worklet budget absorbs several times over.

---

## 0. One-page summary

**The reframing (decided in #84, validated here):** this is NOT blind polyphonic transcription.
Blind multi-F0 estimation + part attribution is research-grade and fails exactly where choirs live
(unisons, octaves, fifths). But the app *knows the score*: at every moment the four expected pitches
are known. The problem collapses to **per-part presence + intonation verification** — for each
expected F0, measure harmonic salience in the live spectrum at F0 ± tolerance; parts whose expected
pitches collide (unison/octave/twelfth) are scored jointly and honestly abstained per-part.

**Headline (trisagion_vector, the app's real 4-part piece, realistic voice timbre, mono mix):**

- Which-part-is-detuned, per NOTE (+-30c): detection with correct sign on the detuned part's
  scoreable notes — **S 93-96% / A 72% / T 85-89% / B 58-61%** — at **0.0-1.4% false-alarm** on
  the in-tune parts; still 62-93% detection at <=5.2% FA through reverb + 10 dB SNR noise (§3.1).
- Which-section-is-flat, per SESSION (the actual ensemble-mode question — median over the take):
  **correct in all 40 trisagion detune conditions** — every part x {+-30c, +50c} x {clean, room
  20 dB, room 10 dB} x both timbres. Across the whole matrix: 77/80 correct; the 3 misses are all
  {11-second toy piece x sparse triangle stress timbre x bass}, and they degrade to "no verdict",
  never to accusing the wrong section (§3.1, §3.6).
- Intonation accuracy vs what was actually sung: **median |error| 0.12-0.47 cents, p90 < 3.7
  cents** (§3.2) — negligible against the +-10-15 cent judgments the product makes.
- A silent (missing) section is detected on 80-100% of its unmasked notes at 0.0% false alarms
  (§3.3) — though a missing SOPRANO is provable on only ~4% of this piece's notes (masking, §3.5).
- Cost: one forward FFT + trivial band arithmetic per hop — **~2-3 ms per second of audio**
  extrapolated for the Rust worklet, cheaper than the already-shipping #80 detector (measured
  4.9 ms/s). Real-time is not in question (§3.7).

**The honest limitation — attribution masking:** when expected pitches sit at near-integer
frequency ratios (unison, octave, twelfth...), the upper part's harmonics coincide with the lower
part's and per-part attribution is *physically* impossible (§2.3, §3.5). Catalog-wide (477 4-part
pieces), the per-part attributable fraction of sounding time averages **S 49% / A 50% / T 69% /
B 90%** (§3.5). Session-level verdicts survive this easily — the unmasked moments are plenty —
and for truly doubled lines (e.g. S+A in unison) the joint verdict IS the section verdict.

**Recommendation (§5):** extend the **Rust worklet** (the FFT, ring buffer, and worklet plumbing all
exist; est. 2-4 focused days for the DSP port + protocol). BasicPitch/ONNX loses for this use case
on part attribution (it has none) and pitch resolution (~33-cent contour bins vs our sub-cent), and
stays interesting ONLY for a future no-score upload scenario.

**Proposed first slice (§6):** post-hoc "Section check" on an in-app recording (#67's recorder) —
no real-time work, no worklet changes, reuses the loaded score + bpm the app already has.

---

## 1. Product target: ensemble mode

One phone in the rehearsal room. The choir sings a piece the app has loaded; the app listens with
the mic and reports per SECTION (S/A/T/B): in tune / trending flat by ~N cents / not audible /
cannot attribute here. Two properties make this *easier* than the current solo scoring path:

- **No playback bleed.** In ensemble mode the accompaniment is not playing — the mic hears only the
  choir. (Solo practice mode records accompaniment + voice mixed; that path is NOT what this spike
  targets.)
- **Slow harmonic rhythm.** Chant moves at quarter ~ 60-90 bpm with long sustains — many analysis
  frames per note, so per-note medians are robust and reverb smear between notes matters less.

## 2. Method

All measurement code lives in `.scratch/multipitch-spike/` (`score_parse.py`, `synth_render.py`,
`salience_detector.py`, `run_experiments.py`, `posthoc_truth.py`, `catalog_coverage.py`,
`render_demos.py`; run each with `python3`, no arguments; needs numpy/scipy only).

### 2.1 Ground truth — render the mix from the app's own recipes

Deterministic numpy ports of the app's two instrument timbres, so truth is exact and no browser is
involved:

- **`triangle`** — `js/transport.js buildAudio()` synth mode: triangle oscillator (odd harmonics,
  1/k^2), envelope A=8 ms / D=0.1 / S=0.85 / R=0.12, per-part Gain 0.25. The *easy, stationary*
  case — and the sparse-spectrum stress test (no even harmonics at all).
- **`voice`** — `samples/generate-voices.mjs`: additive ~1/h source through the 4-peak "ah" formant
  bank, **vibrato to ~20 cents at 5.5 Hz, clamped random-walk pitch jitter ~ +-7 cents**, onset
  breath, amplitude shimmer. The *realistic, moving-pitch* case; per-part detune multiplies f0 on
  top, so the "singer model" wanders exactly like the app's own voices do.

Note scheduling matches `transport.js scheduleAll()` (start = start_beat x spb, dur = max(0.05,
durBeat x spb x 0.95)). Pieces (parsed from the repo's MusicXML, same files the app loads):

| piece | source | tempo | notes/part | character |
|---|---|---|---|---|
| control | `content/control_satb.musicxml` | 90 | 13 | 11 s toy, deliberately tight voicing (worst case for masking) |
| trisagion | `content/trisagion_vector.musicxml` | 70 (score) | 136/128/126/119 | 103 s real piece — the headline numbers |

Conditions per piece x timbre: all-in-tune; each part detuned +30c / -30c / +50c (12); each part
silent (4); tenor octave-up; bass octave-down; and (voice timbre) every in-tune/+-30c condition
re-rendered through a synthetic room (RT60 0.8 s exponential-noise IR, 30% wet — a carpeted parish
hall with the phone across the room) plus pink noise at 20 and 10 dB SNR. Mono mix throughout (one
mic). Listenable examples: `demo_in_tune.wav`, `demo_alto+30c.wav`, `demo_room10dB_alto+30c.wav`
in the spike dir.

### 2.2 The detector

Frame the mono mix — **4096-sample Hann @ 48 kHz (85 ms), hop 1024 (~47 Hz), rFFT zero-padded to
8192**. Per frame, per part with an expected pitch (rests are *expected silence* — the score gives
breath/rest handling for free; note edges gated 90/60 ms):

1. For harmonic k = 1..6 of the expected F0: search band = k·F0 x 2^(+-70/1200).
2. **Collision mask:** the band is *contested* if another part's plausibly-strong harmonic
   (nearest-integer test, interferer index jj <= 4k — an interferer ~12 dB below on a 1/h amplitude
   model can't move the peak) lands within the band + a 2-bin skirt margin. Contested bands are
   excluded from per-part math — this is what makes unisons/octaves/twelfths *joint* instead of
   wrong.
3. In each free band: peak bin + parabolic interpolation on log-magnitude -> (freq, magnitude);
   local floor = median |FFT| within +-300 cents.
4. **Presence** = mean of the top-3 per-band dB-over-floor (timbres owe you no particular harmonic
   — a triangle has no even ones). A **missing** verdict additionally requires >=2 measured bands.
5. **Intonation**: per-band cents offsets (gated >6 dB over floor and within 30 dB of the
   strongest usable harmonic) must **agree** — cluster within +-12c of the median; a lone
   estimate is only trusted from a solid low harmonic (k<=3, >15 dB). Estimate = weighted mean
   (weight = k x dB, since higher harmonics carry more Hz per cent).
6. Per NOTE: medians over the note's frames; a note >50%-masked is an **abstention** (reported,
   not guessed). Octave diagnostics ride along: odd-vs-even harmonic salience (octave-up
   signature) and a sub-harmonic probe at 0.5x/1.5x F0 (octave-down signature).

Classification per note: abstain (masked / <2 frames) | missing (presence < 5 dB, >=2 bands) |
off-pitch (|median cents| > 15) | ok.

### 2.3 Why masking is physics, not a tunable

A soprano A4 (440 Hz) over a bass D3 (146.8 Hz — a twelfth) puts EVERY soprano harmonic within ~2
cents of a bass harmonic (3:1 ratio; ET twelfth vs just twelfth differ by 0.05c). No detector,
neural or classical, can attribute that energy from a mono mix. The honest options are the ones
implemented: declare the collision (abstain per-part, score jointly), and lean on the moments the
voicing opens up — which the session-level aggregation does automatically. In an octave pair the
LOWER part's odd harmonics stay free, so the lower part often remains scoreable while the upper is
masked — the mask is per-part, per-frame, not per-interval.

## 3. Results

All numbers below are the final run (`matrix.log` / `results.json`, 2026-07-05). Metric
definitions: **det** = fraction of the detuned part's scored (non-abstained) notes flagged
off-pitch with the correct sign; **uniq** = det AND no time-overlapping in-tune note was falsely
flagged; **cov** = scored / total notes for that part (the rest are masking abstentions);
**FA** = fraction of in-tune parts' scored notes falsely flagged (off-pitch or missing);
**session** = whether the per-part median over the whole take names the detuned part, right sign,
above the 15c flag threshold. Note thresholds: presence 5 dB, flag 15 cents.

### 3.1 Which part is detuned? (trisagion, voice timbre, mono mix)

In-tune baseline: **FA 0.0%** (clean), 0.6% (room 20 dB SNR), 2.3% (room 10 dB); abstain 29-32%.

| condition | det | uniq | cov | FA | session |
|---|---|---|---|---|---|
| Soprano +30c / -30c | 96% / 93% | 94% / 93% | 53% | 0.3% / 0.0% | OK / OK |
| Alto +30c / -30c | 72% / 72% | 71% / 67% | 59% | 0.3% / 1.4% | OK / OK |
| Tenor +30c / -30c | 89% / 85% | 87% / 84% | 78% | 1.1% / 0.4% | OK / OK |
| Bass +30c / -30c | 61% / 58% | 61% / 58% | 97% / 92% | 0.0% / 0.0% | OK / OK |
| +50c (S/A/T/B) | 97/79/87/66% | 96/79/82/66% | 53/59/75/93% | <=1.9% | all OK |

Under the room simulation (RT60 0.8 s + pink noise):

| condition (all parts, +-30c) | det range | uniq range | FA range | session |
|---|---|---|---|---|
| room 20 dB SNR | 61-92% | 61-90% | 0.4-2.1% | 8/8 OK |
| room 10 dB SNR | 67-93% | 62-79% | 0.4-5.2% | 8/8 OK |

Reading: soprano/tenor detune is caught on ~9 of 10 scoreable notes with essentially zero false
accusations; alto ~3 of 4; bass ~3 of 5 per note (its +-30c is only ~2-6 Hz, and its cluster
evidence is thinner) — but bass has the *highest coverage* (92-97%), so the session median nails
it every time. The per-note bass weakness is a per-note UI caveat, not a product blocker: the
session verdict — "basses are ~30c flat today" — was correct in all 40 trisagion conditions.
The 11 s control piece (13 notes/part, deliberately tight voicing) tells the same story with more
variance: session verdict correct in all 12 voice-timbre detune conditions at FA <=4%, det 15-75%
per note on 31-100% coverage.

### 3.2 Intonation accuracy — measured against what was actually SUNG

The voice timbre wanders by design (the app's own recipe: +-7c random-walk jitter + vibrato), so
error vs the *nominal* detune (~6.7c median across the matrix) conflates detector error with true
singer wander. Replaying the render's exact RNG (`posthoc_truth.py`) gives each note's true sung
offset; against THAT truth, in the full 4-part mix:

| part | in-tune: median err / p90 | alto+30c condition: median err / p90 |
|---|---|---|
| Soprano | 0.29c / 1.81c | 0.16c / 2.49c |
| Alto | 0.44c / 3.65c | 0.31c / 3.11c |
| Tenor | 0.19c / 1.58c | 0.12c / 2.16c |
| Bass | 0.40c / 3.03c | 0.47c / 2.97c |

Bias is +-0.06c or less everywhere. On stationary pitch (triangle) the error vs nominal is
0.0-0.2c. **The detector measures what the section actually sang to well under a cent**; the
+-15c flag threshold has an order of magnitude of headroom.

### 3.3 A section is missing (silent part, trisagion, voice)

| silent part | detected missing (of scoreable notes) | coverage | FA on others |
|---|---|---|---|
| Soprano | 80% | 4% | 0.0% |
| Alto | 100% | 19% | 0.0% |
| Tenor | 100% | 47% | 0.9% |
| Bass | 100% | 55% | 0.0% |

The catch is coverage, not accuracy: proving absence needs >=2 free harmonic bands, and a
soprano's bands are the most-masked (§3.5) — on this piece a silent soprano is *provably* absent
on only 4% of its notes. (Silence of the lower parts is easy.) Product framing: "not heard" plus
low confidence, never a hard accusation.

### 3.4 Octave errors — a session signal, not a note verdict

Per-note octave flags are unreliable: octave-up (tenor) flagged 27% of notes with 20%
false-positive on in-tune; octave-down (bass) 25% at 7% FP (`posthoc_truth.py`). But the session
medians of the two designed signatures separate cleanly:

- Tenor sung an octave UP: odd-minus-even harmonic salience median **-21.7 dB** (in-tune: +2.5 dB)
  — the expected-F0's odd harmonics vanish, the evens (the sung octave) stay.
- Bass sung an octave DOWN: sub-harmonic probe (energy at 0.5x/1.5x expected F0) median
  **+13.3 dB** (in-tune: ~+3.8 dB).

Ship as session-level advisories ("basses: check your octave"), not per-note marks.

### 3.5 The masking ceiling — catalog-wide

Attribution masking is computable from the score alone (no audio), so it was measured across the
entire ingest library (`catalog_coverage.py`, same contested rule as the detector): **477
four-part pieces**, per-part fraction of sounding time with at least one attributable harmonic:

| part | mean | min | max |
|---|---|---|---|
| Soprano | 49% | 0% | 98% |
| Alto | 50% | 0% | 96% |
| Tenor | 69% | 0% | 100% |
| Bass | 90% | 0% | 100% |

All-parts mean 64%. The trisagion measured above sits near the average (S 42 / A 60 / T 71 /
B 98). The 0% outliers are honest and instructive: e.g. `vespers-toensing-*` encodes S=A and T=B
(two real lines duplicated across four staves) — everything is a genuine unison/octave, so
per-part attribution is impossible AND unnecessary: the joint verdict covers everyone singing
that line. A near-unison-throughout piece (`rich_men_tone_7_bbe`, ~9%) is the true worst case:
there, ensemble mode can only say "the unison is flat", which is still the right feedback.

### 3.6 The sparse-timbre stress case (triangle)

The triangle render (only odd harmonics, zero noise floor) is deliberately hostile: half of every
part's harmonic bands are empty by construction, and empty bands over a synthetic noiseless floor
breed junk peaks. After the consensus rules (§2.2 step 5), false OFF-PITCH flags are gone
(control in-tune: 0 false off-flags), intonation on scored notes is exact (0.0-0.2c), and the
session verdict still lands (12/15 trisagion+control conditions; the 3 misses are control-bass
"no verdict" cases). What remains is a ~10-19% false-MISSING rate (in-tune FA, almost all
'missing') — a part whose only free bands are its timbre's empty ones looks absent. Real voices
put energy at every harmonic (this is what the voice timbre models, FA 0.0% there), and real
rooms have real noise floors; the residual is reported for honesty, and the §7 field recordings
are the arbiter.

### 3.7 Cost

Python prototype: ~20 ms per second of audio for the full pipeline (numpy STFT 4.7 ms/s + pure-
Python band loops). The band math is trivial (24 band scans of ~100 bins + medians per frame at
~47 fps); the FFT dominates in any compiled implementation. The shipped Rust worklet already runs
a bigger transform (5120-pt forward+inverse cepstrum pair at up to 62 Hz) inside its measured
**4.88 ms/s** (#80 A/B harness, re-run 2026-07-05); salience needs only a forward 4096-pt rFFT at
47 Hz plus that band math. **Estimate: 2-3 ms/s of audio — under 0.5% of one core; cheaper than
the pitch detector the app already ships.**

## 4. Limitations (what synthetic tests cannot settle)

- **One synthetic singer per part.** A real section is several voices with +-10-20c spread (chorus
  effect): harmonic peaks widen into clusters. The peak-interpolated cents then approximate the
  amplitude-weighted section mean — which is exactly the quantity the product reports — but this is
  *plausible, not proven*. The §7 field protocol is designed to settle it.
- **Room realism.** RT60 0.8 s + pink noise at 10-20 dB SNR is a fair rehearsal-hall model; a stone
  church at RT60 2-3 s will smear note transitions further (wider edge gates, slower pieces still
  fine). Phone-mic nonlinearity/AGC are untested — the in-app recorder captures through the same
  mic path, so field recordings answer this directly.
- **Wrong NOTES (not wrong intonation).** A singer on an entirely different pitch than scored puts
  energy where the collision mask doesn't expect it; it can corrupt a neighbor part's band. The
  detuned conditions here (+-30/50c) stay within the search bands; gross wrong-note detection is a
  different feature (the solo scoring path already handles the solo case).
- **Reference pitch / ensemble drift.** Cents are measured against the score at A440 equal
  temperament. Choirs drift globally; the product should report intonation RELATIVE to the
  ensemble median (trivially computable from the same per-part streams — subtract the cross-part
  median before flagging) or anchor to the given starting chord.
- **Octave errors are a section-level signal, not a per-note one** (§3.4): per-note octave flag
  rates are weak (~20-30%) with nontrivial false positives, but the session medians of the
  odd-vs-even and sub-harmonic signatures separate cleanly. Ship octave hints as session-level
  "check your octave, basses" advisories, not note verdicts.
- **Measurable detune range is ~ +-65 cents** (search band +-70c minus edge effects). Beyond that a
  part reads as missing/unattributable rather than "very flat". Fine for intonation coaching; not a
  gross-error detector.

## 5. Architecture recommendation

### 5.1 Recommended: extend the Rust worklet (`src/dsp`, `worklet` feature)

Everything expensive already exists and is measured:

- `src/dsp/detector.rs` `FftDetector` already runs a **5120-point forward+inverse realfft pair at
  up to ~62 Hz** inside the shipped wasm worklet; #80's harness measured the whole VoiceProcessor
  at **4.88 ms per second of audio** (Node proxy; `tests/detector-ab.mjs`, re-run 2026-07-05).
- Salience needs **less**: one forward 4096 rFFT at ~47 Hz (the 8192-sample `audio_raw` ring buffer
  in `FftDetector` already holds enough history) plus ~24 band scans of ~100 bins and a handful of
  medians per frame. The Python split confirms the FFT dominates (stft 4.7 ms/s in optimized C vs
  9.3 ms/s for *interpreted* band math; in Rust the band math is noise). **Estimate: 2-3 ms/s
  audio, i.e. <0.5% of one core — cheaper than the detector we already ship.**
- Port scope: `salience_detector.py` is ~230 lines of numpy; a `SalienceScorer` in `src/dsp` is an
  estimated **300-400 lines of Rust + tests**, no new crates (realfft is already a `worklet`
  dependency). Plumbing: the worklet needs the expected-pitch timeline — post the per-part
  {startSec, endSec, f0} windows for the loop range through the existing worklet message port
  (same channel #80 built for pitch results, reverse direction), and post per-part
  {presence, cents, nHarm, masked} back at ~10 Hz. **Estimated cost: 2-4 focused days** (1 DSP
  port + property tests against the Python reference vectors, 1 protocol + main-thread wiring,
  1-2 calibration/verify harness mirroring `tests/detector-ab.mjs`).

### 5.2 Compared: BasicPitch (Spotify) via TF.js/ONNX — the blind-transcription route

Facts (checked July 2026): Apache-2.0, browser package `@spotify/basic-pitch` runs on TF.js;
deliberately tiny (<17k parameters, <20 MB peak memory; ICASSP 2022 paper). Input resampled to
22.05 kHz; outputs onset/note/contour posteriorgrams on a CQT grid of **3 bins per semitone
(~33-cent resolution)** at ~11 ms hop; own README: "works best on one instrument at a time."

Why it loses for ensemble mode: (a) **no part attribution** — it emits pitch events, not "the altos
are flat"; attaching events to parts needs exactly the score-matching we already do, at which point
the network adds nothing; (b) **~33-cent contour bins** cannot support +-10-15 cent intonation
verdicts (our measured accuracy is sub-cent on the same task); (c) polyphonic *vocal* unisons /
octaves collapse into single detections — the masking problem again, minus the honest mask. Where
it WINS: a future "upload audio without a score" feature (transcribe-to-score, rehearsal archive
indexing). Keep it on the shelf for that product, not this one.

## 6. Product slice proposal (the GO path)

1. **MVP — post-hoc "Section check" (recommended next slice).** After an ensemble take recorded
   with #67's in-app recorder (music leg at 0 — mic only), decode the blob
   (`decodeAudioData`), run the salience pass offline against the loaded piece's note model +
   bpm (`js/model.js` already exposes per-part notes in beats), and render a per-section report
   reusing the score-report surface: per section of the piece (via `js/sections.js`), each part
   gets in-tune / flat N cents / sharp N cents / not heard / not attributable-here. No real-time
   constraint, no worklet change, no new assets; even a plain-JS analyzer at ~10x the numpy cost
   finishes a 3-minute take in seconds, and the wasm module can take it over later unchanged.
   Risk: low. This is also the vehicle for validating real-choir audio (§7) — the analysis and the
   field test are the same code path.
2. **Slice 2 — live ensemble meters.** Port to the Rust worklet per §5.1; live per-section
   presence/intonation chips while the choir sings, driven at ~10 Hz from the worklet stream.
3. **Slice 3 (only if the no-score use case materializes)** — BasicPitch offline for un-scored
   uploads.

## 7. Owner field-recording protocol (the next contribution this needs)

No real polyphonic recordings exist in the repo (checked; `.scratch/issue-71/` clips are
synth-only) — real-choir validation is deliberately the owner's next step, with the in-app
recorder (#67). Room: the usual rehearsal space; phone where it would really sit (center,
2-4 m from the choir), recorder's Voice/Music balance at full Voice (music leg silent).
Piece: the Trisagion already in the library (it is the piece measured here). For each take note
BPM used, headcount per section, and phone position.

| # | take | purpose |
|---|---|---|
| 1 | Each section ALONE singing its line (4 takes, same bpm, start pitch from the app) | **the most valuable data**: real stems -> we can mix any condition (detune via resample, drop a part, octave shift) with real voices |
| 2 | Full choir, best in-tune effort | false-alarm baseline in a real room |
| 3 | Full choir, ONE agreed section sings everything a quarter-tone flat (repeat for 2 sections if patience allows — tenor and alto first) | the headline detection test; a quarter-tone (~50c) is holdable by ear, 30c is not |
| 4 | Full choir, one section silent (basses out) | missing-section detection |
| 5 | (optional) Basses an octave down where the line sits high | octave-signature check on real voices |

If assembling the choir is hard: the owner multitracking HIMSELF (sing each part alone against the
app at a fixed bpm, 4 takes) unlocks the same stem-mixing analysis — take #1 without needing four
other people. Analysis of all of the above runs with the spike scripts as-is (decode to wav,
`analyze()` against the piece's parsed notes).

## 8. Repro

```
cd .scratch/multipitch-spike
python3 run_experiments.py      # full matrix -> results.json + report (about 5 min)
python3 posthoc_truth.py        # truth-aware accuracy + octave-signature rates
python3 catalog_coverage.py     # attributability across all ingested 4-part pieces
python3 render_demos.py         # listenable wavs
```

Sources: [basic-pitch](https://github.com/spotify/basic-pitch) /
[basic-pitch-ts](https://github.com/spotify/basic-pitch-ts) (Apache-2.0; model + browser runtime),
[Spotify engineering announcement](https://engineering.atspotify.com/2022/6/meet-basic-pitch)
(<17k params, <20 MB), Bittner et al., *A Lightweight Instrument-Agnostic Model for Polyphonic
Note Transcription and Multipitch Estimation*, ICASSP 2022 ([arXiv:2203.09893](https://arxiv.org/abs/2203.09893))
(22.05 kHz, CQT 3 bins/semitone, harmonic stacking). #80 A/B numbers:
`training-prototype/tests/detector-ab.mjs` (re-run 2026-07-05: JS 63.9 ms/s, WASM 4.88 ms/s).
