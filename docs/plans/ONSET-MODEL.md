# Neural onset model — design

Design note, 2026-08-18. Companion to `CHANT-MODEL-ACCURACY.md` (workstream
ALIGN-03). Origin: the chanter's observation that *"just calculating the length
of time makes it inconsistent … otherwise we are always gonna have late and
early onsets however slight."*

---

> **Read `ONSET-EVENTS.md` first (2026-08-19).** Measuring the current pipeline
> against gold #1 found that the residual this plan targets — precision within a
> locked passage — is the *second* problem. The first is that the event detector
> emits 32 % more events than there are notes while missing a quarter of the real
> onsets, so a third of them have nothing to be precise about, and machine-aligned
> pairs inherit a 57 % spurious rate as training labels. That changes what this
> model should be trained on and when it should be sized.

## 1. Why arithmetic cannot finish this job

The duration model landed today is now correct against the book: apli/dipli/
triplē counted, the gorgon family taking *k/(k+1)* off a *k+1* window, klasma
colour-blind, rests as units. It moved gold #2's median onset error 0.563 s →
0.485 s. It will not go much further, and the gold says why.

**The residual is bimodal.** At r4, of 52 machine-matched pins, **25 are within
0.15 s and the other 27 are seconds away. Nothing lands in between.** A model
with diffuse timing error produces a smooth error distribution; this produces
two populations. The aligner is either locked on or has slipped a note and
cannot recover.

So there are two separate problems, and only one of them is an onset problem:

- **Re-synchronisation** — the path drops a note and never re-anchors. Fixed by
  hard anchors and a martyria checksum (ALIGN-02, CHECK-01), not by a model.
- **Onset precision within a locked passage** — the ±150 ms that arithmetic
  cannot remove, because beats are a *notional* grid and a chanter's realisation
  of that grid is expressive, not metronomic. This is what the model is for.

A further reason arithmetic caps out, in the chanter's words: *"chanters might
use different kinds of rhythms and sometimes the way a measure is split isn't
the same."* Beat length is a **prior**, not an answer.

---

## 2. The syllable prerequisite — much cheaper than feared

The model must be told *which syllable* it is locating. That needs a syllable
stream, and the concern was that lyric tokens are sometimes whole words.
Measured against the actual text layer of all 178k glyphs:

| measure | value |
|---|---|
| lyric token instances corpus-wide | 94,459 |
| tokens already exactly one syllable | **86,141 (91.5 %)** |
| multi-syllable tokens needing a split | 8,027 (8.5 %) |
| of those, resolved by splitting on **whitespace alone** | **6,578 (81.9 %)** |
| needing a real Greek syllabifier | **1,449 instances** |
| lyric tokens per score unit | **0.87** |

The chanter's point about Greek is the reason this is so cheap:

> a lot of the syllables in greek are actually repeated in the text as lyrics,
> where english ones usually dont repeat the repeated vowel but either leave a
> blank or use a --- or ___ to indicate extension

The corpus bears this out — the most frequent lyric tokens are bare extension
vowels, reprinted once per note: α 5,808, ε 5,773, ο 3,521, η 2,783, ι 2,213,
ω 2,088, υ 1,596. Tokens like `ω ω`, `ου ου`, `θρω ω`, `σω ω` are literally the
melisma spelled out. **Greek gives us a near per-note text stream for free**,
which English EZ-font scores do not — there the extension is a blank or a rule,
so gold #1 (eothinon-11) cannot supply this signal and must be handled by the
melisma-index mechanism in §4 instead.

At 0.87 tokens per unit the text stream is already close to 1:1 with notes.

### 2.1 Syllabification needs the WORD, not the token

The chanter's correction: *"greek syllabication needs to understand the word
that it is in or the previous and next words because the consonants or
inflection might change."* A per-token vowel-nuclei splitter is not enough, and
the corpus shows why — a word is routinely **split across several lyric tokens**
by the melisma (`με νος`, `σον ημας`, `νωσκων με`). Syllabifying `ημων` without
knowing it is ἡμῶν, or deciding where `σεισου Κυ` divides, is a lexical
question, not a character-level one.

`attach_words()` in `prep_hymn_annotator.py` does **not** solve this: it maps
each lyric *token* to its nearest unit and propagates it forward, treating every
token as if it were a word. Word reconstruction does not currently exist
anywhere in the pipeline.

### 2.2 The canonical text solves this — TEXT-01, shipped

The chanter's answer to the whole problem: *"going here https://glt.goarch.org/
and looking at the oktoechos hymns for sunday vespers and orthros. and then
match the text to the hymn."* That is strictly better than reconstructing words
from fragments, because it supplies the answer rather than a way to guess it.

`tools/corpus/glt_fetch.py` fetches and parses the Oktoechos — Sunday Vespers
and Orthros for all eight modes (`Tone{1..8}Sun.html`, where Tone7 = βαρύς and
Tone5/6/8 = plagal 1/2/4) plus the eleven Eothina — into **603 fully accented
polytonic hymns**. `tools/corpus/glt_match.py` matches each corpus hymn's lyric
stream against them on collapsed-normalised text (accents stripped, letters
only, runs of one letter collapsed, because the melisma reprints the vowel once
per note).

Result: **157 of 173 corpus hymns matched at ≥0.55 coverage, median 0.90, 90 of
them ≥0.90.** Gold #2's t03 matches at **1.00** to *Κατέλυσας τῷ Σταυρῷ
σου τὸν θάνατον, ἠνέῳξας τῷ Λῃστῇ τὸν Παράδεισον…* — which is exactly the
text buried in its fragments (`α τε λυ σας τωσταυ ρω ω σου τον θα νατον`).
Output: `texts/glt_oktoechos.json`, `texts/glt_hymn_match.json`.

This gives three things at once, which is why it reorders the plan:

1. **Words and inflections for free.** No lexicon to build, no word
   reconstruction to invent — syllabify the *canonical* word and project the
   syllables onto the fragments by alignment.
2. **Boundary verification.** A slice that runs into the next hymn shows up as
   score text past the end of its match. The 16 low-coverage hymns are the
   audit queue.
3. **A real liturgical lexicon**, rather than one scraped from melisma debris.

**SYL-01 (M) is now GLT-anchored.** Four steps:

1. **Align** the hymn's lyric fragments to its matched GLT text (the matcher
   already computes the alignment blocks).
2. **Syllabify the canonical accented word** — word context is present by
   construction, which is what the chanter said was required.
3. **Project** syllables back onto fragments and units through the alignment.
4. **Review queue** for anything unaligned or low-coverage.

Caveats, honestly: 40 of the 603 GLT entries are still over-long merges (the
appendices run several hymns into one paragraph), and 16 corpus hymns are below
0.55 — some are genuine boundary problems, some are hymns not in the Sunday
Oktoechos at all (a Theotokion of another mode, a Heirmos from a canon). Both
lists are the work, not a reason to distrust the 157.

Acceptance: ≥99 % of units carry a syllable or an explicit melisma-continuation
marker; every word whose reconstruction or split is uncertain goes to a review
sheet for chanter sign-off, because a wrong split is a wrong training label
forever.

**What NOT to over-engineer.** The chanter notes that inflection is often
signalled by the score itself — *"usually inflections are indicated by the score
(going up or holding a note, using a petasti instead of an oligon, being a down
beat or upbeat)"*. So the syllabifier does not need to resolve every linguistic
ambiguity by rule. It needs to produce a **consistent** token stream; the
residual ambiguity is exactly what the encoder is for, since the neume choice
itself carries the disambiguating evidence. Rule-based perfection here is wasted
effort that a learned model gets for free.

---

## 3. Data reality — the scarce thing is verified onsets, not audio

The chanter proposed *"a multimodal model that we train like a 4B-7B parameter
model"*, and clarified: **never from scratch** — fine-tuning a pretrained one,
with synthesised data, imported recordings, and the fact that *"every week more
and more chanters chant every sunday and record online."* That reframes the
constraint correctly. Audio is not scarce and is growing weekly. What is scarce
is **chanter-verified onset labels** and **singer diversity**:

| asset | size |
|---|---|
| aligned hymns | 173 |
| score units | 16,602 |
| machine-aligned unit↔event pairs | ~10,535 |
| **chanter-verified onsets** | **76** (gold #2) + 259 (gold #1 note_times) |
| raw audio on disk | 264 files, **37.4 hours** |
| **distinct singers** | **exactly one** — `raw/` has a single top-level dir, `vasilikos` |

So the parameter budget is fine — a pretrained 4-7 B multimodal model fine-tuned
with adapters is well within reach. Two constraints survive regardless of scale:

- **Fine-tune, don't fully update.** ~10.5 k silver pairs and 335 verified
  onsets support adapter/LoRA fine-tuning of a pretrained encoder plus a small
  (~30-80 M) cross-attention head over the neume stream. Full fine-tuning of
  every parameter on this label count overfits whatever the label count is.
- **The big model as verifier, not predictor** — the chanter's own proposal,
  and the right shape: *"multi token prediction where it might suggest a
  sequence of onsets and then we will only take the first few that the bigger
  model accepts."* Verification needs no onset labels at all, which is why it
  scales when labels don't.

**Singer monoculture is the real risk.** Not "nearly" one voice — `raw/`
contains exactly one top-level directory. All 37.4 hours are Vasilikos. (The
Phokaeos and Oinoussai names in piece titles are the *composer of the setting*,
not the singer.) A model fit to this will learn one man's rubato as if it were
notation. That is the strongest argument for the weekly recordings, and the
argument is *variance*, not volume — 37 hours of unlabeled single-singer audio
is already plenty for encoder adaptation.

### 3.1 What each data source can and cannot label

| source | gives | must NOT be used for |
|---|---|---|
| weekly Sunday recordings, imported archives | unlabeled audio: encoder adaptation, singer variance, pseudo-labels behind a confidence gate | onset truth, until a chanter pins them |
| label-preserving augmentation of *aligned* audio (pitch shift, known-factor time-stretch, reverb, noise, voice conversion) | **exact onsets** — the labels transform deterministically with the signal | nothing; this is the safe multiplier |
| concatenative synthesis: real recorded syllables spliced at chosen times | **exact onsets with real acoustics** — the classic onset-detection trick | modelling long-range expressive rubato, which splicing destroys |
| generative music models (incl. any trained on Byzantine chant) | unlabeled audio, and possibly useful pretrained representations | onset truth — their timing is *model* timing |

**The circularity trap, stated plainly.** Do not render training audio from the
score using `beats_seq` timing. The model would learn to reproduce the
arithmetic it exists to transcend, score perfectly on synthetic data, and change
nothing on gold. Synthetic audio may borrow its timing from a *real* performance
or from splices of real singing; never from our own duration model. This is the
one way the synthesis idea can quietly fail while looking like it worked, so
every synthetic corpus must record where its timing came from.

### 3.2 The flywheel

Weekly recordings only become labels through the annotator. The lane already
exists: prep → chanter pins → `ingest_pins` → gold. Each newly pinned piece adds
verified onsets *and* a new singer. Pseudo-labelling closes the loop — the model
proposes, the confidence gate filters, the chanter reviews only what is
uncertain — but the gate must be tuned so review effort falls without silently
promoting machine timing into gold.

Rule that does not bend: **no onset enters gold without the chanter.** Machine
onsets are silver; they train, they never grade.

---

## 4. Architecture

```
audio ──► frozen SSL encoder ──► local window features (20 ms frames)
                                        │
score ──► neume/syllable stream ──► decoder with CROSS-ATTENTION ──► onset head
                    ▲                       │
genre/meta text ────┘              (Δt distribution, not a point)
```

### 4.1 The base model — THREE slots, not one

The plan said "frozen SSL encoder" and "a pretrained 4-7 B multimodal model" and
never named either, which hid that these are **three different models with three
different jobs**. Conflating them is how a project ends up trying to regress a
20 ms onset out of a 7 B chat model.

| slot | job | choice | why |
|---|---|---|---|
| **frame encoder** | audio → 20 ms features | **`jonatasgrosman/wav2vec2-large-xlsr-53-greek`**, frozen | the only encoder MEASURED on this material, and it already hits the target |
| **alignment decoder** | neume/syllable stream ↔ audio, emits Δt | trained here, ~30-80 M, cross-attention | 335 verified onsets support this size and nothing larger |
| **verifier / generator** | accept-or-reject a proposed onset run; later, emit neumes (§6) | a large multimodal model, unchosen | needs no onset labels, so it scales when labels do not — and it is not needed until ONSET-02 |

**Why wav2vec2-XLSR-Greek is the encoder, on evidence rather than taste:**

- **It already delivers the target.** CTC forced alignment on this encoder gives
  **0.028 s** median onset error against the chanter's 76 pins, where the DTW
  path gives 0.485 s. The model this plan proposes must beat 0.028 s to be worth
  building; anything that starts from a weaker encoder starts behind.
- **20 ms frames**, from a conv stride product of 320 at 16 kHz — exactly the
  resolution §4 assumes, with no resampling of features.
- **It brings a Greek character vocabulary (41 tokens).** That is not incidental:
  it is what let forced alignment run on a *parallagi* using the score's own
  degree names as text, which is how the apichima question got answered at all.
  An encoder without a text head cannot do that.
- **The obvious alternative is measured to fail here.** Whisper misses 55 % of
  the sung audio and emits 463 s of segments over silence on the grave orthros
  tape — it was never trained on ecclesiastical Greek or melismatic chant.
  `faster-whisper-large-v3` is on disk; it is not a candidate for this.

**What would change the choice, and how to test it.** A music-pretrained SSL
encoder (MERT and its kin) has better pitch and timbre representations and a
finer frame rate, which is plausibly worth more than speech pretraining on
*sung* audio. That is a hypothesis, not a reason to switch. Test it the same way
everything else here was tested: same 335 verified onsets, same protocol, report
both. If a music encoder wins, use it as a second stream rather than a
replacement — the Greek text head has to stay, because forced alignment depends
on it.

**What is NOT decided, deliberately.** The verifier's base model. It is the last
thing needed, its requirements depend on what ONSET-01 actually gets wrong, and
choosing it now would be choosing before there is evidence. The one commitment
that must be made early is the §6 tokenisation — the decoder vocabulary is the
full neume stream from the start — because that is unrecoverable later and free
today.

**Input per query.** The chanter's framing — *"the previous syllable AND the
syllable of the note it is looking for the onset for as well as a sliver of
audio time in a window"* — is the right query unit, extended with what the
duration model now knows:

- audio window from the previous confirmed onset, plus lookahead
- previous syllable, target syllable
- the target unit's neume key, interval, and **`beats` from `beats_seq`** — the
  arithmetic prediction enters as a prior, and the model learns the residual
- position within a melisma (index and length), which is what carries gold #1
  where the text repeats give it away in Greek

**Output.** A distribution over Δt, not a scalar. The bimodality above is
exactly why: the model must be able to say *"0.31 s, or possibly 0.62 s if a
note was skipped"* and let the search arbitrate. Point regression would average
those into a wrong answer.

**Hybrid attention.** As proposed. Local windowed attention over audio frames
(onset evidence is local — tens of milliseconds), full cross-attention from the
neume stream to a pooled audio summary (melisma context is long-range). Full
quadratic attention over raw frames is unaffordable and unnecessary.

**Melisma context.** The chanter's concern: *"if there is a lot of melismatic
events … it might not know the context."* Cross-attention over the neume stream
is the answer, because within a melisma the *text* stops disambiguating and only
the neume sequence says which of the twelve notes on this vowel is next.

**Genre conditioning.** *"eirmologic short hymns dont extend that often,
argosyntoma more so and then argo extend a lot."* This is a strong prior on beat
length and on melisma density, and it is already implicit in the corpus
directory structure and hymn names. Feed it as **plain text** — mode, genre,
book, incipit — so it degrades gracefully on an unseen genre rather than
failing a categorical lookup.

---

## 5. Decoding: propose, verify, backtrack

Straight from the chanter's description, made concrete:

1. **Propose.** The head emits the next *k* onsets (k ≈ 4-8) in one pass.
2. **Verify.** Accept the longest prefix that survives: monotonic, inside the
   beat prior's tolerance, and — free and label-less — consistent with the
   martyria checksum at the next cadence (CHECK-01). Reject the rest.
3. **Backtrack.** *"if the predictions start to become increasingly wrong and
   error increases, it will restart from the next best path from the last known
   good high confidence one."* Keep a beam of high-confidence anchor points;
   when accepted-prefix length collapses or predictive entropy spikes, roll back
   to the last anchor and take the next branch.

This directly attacks the failure the gold exposes. Today a slip is permanent
because nothing detects it; here, rising error *is* the detector, and the
martyria are free ground truth for "you are now in the wrong place."

Anchors are: chanter pins (absolute), martyria-satisfied cadences, and
high-confidence model onsets, in that order of trust.

---

## 6. The reverse direction: generation and style personas

The chanter's observation that the same machinery runs backwards is correct and
worth designing for now, because it changes one decision today:

> when we turn it around and ask it to generate a certain melodic phrase with
> all the compounds and everything even the qualitative, it might produce even
> the melismas! … we could prompt it "arabic style" or "vasilikos style" or
> "constantinople style" or mt athos style … and it would cluster and have
> multiple personas in its latent space

An encoder-decoder over (audio ↔ neume stream) is already a translation model.
Trained in the alignment direction it learns which acoustic evidence a given
compound predicts; run the other way, conditioned on text and a target phrase,
it emits neumes — compounds, qualitative marks and melismatic extension
included, because those are simply the tokens it was trained to emit. Melismas
falling out is not a bonus feature, it is what the neume stream *is*.

Two things must be true for that to work, and only one of them is free:

- **The decoder vocabulary must be the full neume stream from the start** —
  compounds, qualitative marks, span marks, duration marks — not a reduced
  interval alphabet. A decoder trained to emit only intervals can never learn to
  emit a psifiston. This costs nothing today and is unrecoverable later, so the
  tokenisation decision in ONSET-01 should be made with generation in mind.
- **Style personas require attribution the corpus does not have.** Measured:
  `raw/` has one top-level directory and `corpus.json` carries only
  `path/name/dur_s/size`. There is no singer field, no school, no date, no
  provenance of any kind. Every persona would currently collapse to the same
  point in latent space because there is only one point.

**ATTR-01 (S), do it before the next ingest.** Add a provenance record at
ingest — singer, school/tradition, place, date, source URL, and who attributed
it — for every new recording, and backfill `vasilikos` for the existing 264.
Retrofitting attribution onto audio already in the tree is far more expensive
than capturing it at the door, and personas are impossible without it. This is a
small schema change that must not wait for the model.

Honest expectation: distinct style clusters need meaningful hours *per* style,
not a handful of examples. This is a real target for the weekly-recording
flywheel over months, not a next-quarter deliverable — but the attribution field
has to exist from the first new file or the months are wasted.

---

## 7. Evaluation

Gold #2's 76 pins are the only instrument that has detected any real improvement
today, so the protocol is inherited from `CHANT-MODEL-ACCURACY.md` §2 with one
addition: **report the two populations separately.** A single median hides
everything. Report `frac(|Δt| ≤ 0.15 s)` over **all 76 pins** (an unmatched pin
is a miss), plus the slip count — how many times the path loses sync.

Non-negotiable: **movement agreement is not an evaluation metric.** At r4 it
reads **1.00** on t03 while the median onset error is 0.485 s. It grades the
aligner against its own decode.

Baseline to beat, r4: median |Δt| 0.485 s, 25 of 52 matched pins within 0.15 s,
25 of 76 pins within 0.15 s over the fixed denominator.

---

## 8. Staging

| stage | work | gate |
|---|---|---|
| **TEXT-01** (S) | *shipped* — `glt_fetch.py` + `glt_match.py`: 603 canonical hymns, 157/173 matched | median coverage 0.90 |
| **SYL-01** (M) | GLT-anchored syllabification; chanter review of unaligned spans and the 16 low-coverage hymns | ≥99 % units carry a syllable |
| **ONSET-00** (S) | honest baseline: `beats_seq` + one global tempo, scored on gold | numbers reproduced from a script, not by hand |
| **ONSET-01** (M) | frozen encoder + small cross-attention head, single next-onset, Δt distribution | beats ONSET-00 on held-out pins |
| **ONSET-02** (M) | multi-onset proposal + verification + backtracking beam | slip count falls; no regression in within-0.15 s |
| **ONSET-03** (L) | genre/meta conditioning; larger verifier | improvement on argo pieces specifically |
| **DATA-01** (M) | label-preserving augmentation + concatenative synthesis, each tagged with the provenance of its timing | synthetic gain reproduces on REAL held-out pins, not just synthetic |
| **DATA-02** (M) | ingest weekly/imported recordings; encoder adaptation on unlabeled audio; pseudo-label gate feeding the annotator | ≥1 new singer pinned into gold; no drop on gold #2 |
| **ATTR-01** (S) | provenance schema (singer/school/place/date/source) at ingest; backfill the existing 264 as `vasilikos` | every new file carries attribution; nothing lands untagged |

**Re-order, 2026-08-19.** `ONSET-EVENTS.md` measured the current pipeline and
found the event layer emits 32 % more events than there are notes while missing a
quarter of the real onsets — so machine-aligned pairs carry a 57 % spurious rate
as labels. And forced alignment on the same encoder this plan would freeze
already gets 0.028 s. Both point the same way: **ONS-01 (forced alignment as the
onset source) runs before ONSET-01**, and ONSET-01 is then sized against what FA
leaves wrong rather than against the DTW's 0.485 s. It may be a much smaller job
than this document assumes, which is the good outcome.

ONSET-01 must not start before SYL-01 is chanter-reviewed. Training a model on
mis-split syllables bakes the error into the weights, where it is far more
expensive to find than in a JSON file.

---

## 9. Non-goals

- Replacing the DTW. The model supplies onsets *within* a locked passage; global
  structure stays with the anchored aligner and the martyria checksum.
- Training anything on machine-aligned onsets as if they were truth.
- A model that outputs a bare number. Distributions, or the search has nothing
  to arbitrate.
- Rhythm normalisation. The chanter's expressive deviation from the beat grid is
  the signal, not noise to be removed.
- Synthetic audio whose *timing* comes from our own duration model (§3.1).
- Treating a metric computed on synthetic data as evidence. Synthetic results
  gate nothing; only real held-out pins do.
