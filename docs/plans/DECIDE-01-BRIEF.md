# DECIDE-01 — which notes the model must own

Sized against `grave-orthros-t03`, 76 glyphs, all 76 pinned by the chanter.
Answers NEURAL-CHANT.md §10's DECIDE-01 gate: *"characterise the gap on t03 …
a sized brief naming which notes the model must own."*

> **t03 is training data and a burnt benchmark.** Every number in this document
> is a fit diagnostic. None of it is evidence of generalisation, and none of it
> may be quoted as a result. `s01` was not opened. — §6.1, §9

Every number below was produced by `tools/corpus/decide01_gap.py --tmp <dir>`,
which computes no onset of its own: it joins the gold pins, the score units, the
chanter's syllable labels, REPRO-01's 179 CTC character onsets and the signed
error vectors that `tools/corpus/onset_eval.py` — the only scorer, §9 — wrote
for REPRO-01, NN-00 and the annotator. Its result is
`decide01_gap.json`, one row per glyph, and it reproduces that file
byte-identically on a second run. Reproduce:

```
cd /mnt/data/code/byzorgan-web
/mnt/data/chant-corpus/venv/bin/python tools/corpus/decide01_gap.py \
  --tmp <dir holding repro01_*.json and nn00_eval_*.json>
```

---

## 1. Where the 76 notes stand

Whole-piece rates, all from `onset_eval.py`, joined by `decide01_gap.py`:

| system | ≤150 ms | ≤100 ms | ≤50 ms | median \|Δt\| | placed |
|---|---|---|---|---|---|
| annotator today — the shipping system (§0.1) | **32.9 %** | 32.9 % | 30.3 % | 0.714 s | 76/76 |
| `fa_char_first` — REPRO-01's FA character baseline | 55.3 % | 52.6 % | 32.9 % | 0.061 s | 56/76 |
| `nn00_prefix16_ols` — NN-00's best inference-only ruler | 23.7 % | 13.2 % | 5.3 % | 0.464 s | 76/76 |
| `nn00_lad_oracle` — NN-00's fitted-on-the-answer ruler | 43.4 % | 34.2 % | 15.8 % | 0.171 s | 76/76 |
| `fa_oracle` — nearest character to each gold pin | 88.2 % | 81.6 % | 60.5 % | 0.040 s | 76/76 |

The last two rows read the gold answer to produce themselves. They are ceilings,
not systems, and are labelled so everywhere below.

**25 notes are right today. 51 are wrong.** The release gate is ≥ 90 % within
150 ms with zero slips (§9), i.e. **69 of 76**, so **44 of those 51 must be newly
owned** and at most 7 may still be wrong.

---

## 2. The partition

Classes are cut on the current shipping system (the annotator), crossed with
whether REPRO-01's character path holds a candidate within 150 ms of the pin.
They partition all 76 with no overlap.

| class | n | share | annotator ≤150/100/50 | annotator median \|Δt\| | `fa_char_first` ≤150 | oracle ≤150 | continuing vowel |
|---|---|---|---|---|---|---|---|
| **OWNED** | 25 | 32.9 % | 100 / 100 / 92 % | 0.021 s | 56.0 % | 92.0 % | 7 |
| **SELECTION_CLEAN** | 10 | 13.2 % | 0 / 0 / 0 % | 2.393 s | 60.0 % | 100 % | 1 |
| **SELECTION_AMBIGUOUS** | 34 | 44.7 % | 0 / 0 / 0 % | 2.210 s | 64.7 % | 100 % | 9 |
| **SUPPLY_TEXT** | 6 | 7.9 % | 0 / 0 / 0 % | 0.973 s | 0.0 % | 0.0 % | 0 |
| **SUPPLY_VOWEL** | 1 | 1.3 % | 0 / 0 / 0 % | 3.014 s | 0.0 % | 0.0 % | 1 |

`fa_char_first`'s per-class rate is over the class denominator, so the 20 glyphs
REPRO-01 could not place count as misses inside their class.

### OWNED — 25 notes, nobody must own them
The annotator is already inside the gate; 23 of 25 are inside 50 ms. All 25 lie
outside both slip runs. A model must not lose these: they are 25 of the 69 the
gate needs.
*Example — glyph 0, `6|`, 1.0 beat, no syllable (the drop cap, §0.4). Annotator
Δt +0.016 s; nearest character candidate +0.086 s.*

### SELECTION_CLEAN — 10 notes, 13.2 %
Exactly one character candidate sits inside 150 ms and no other pin claims it.
The answer is present and unambiguous, and the current system is nowhere near it
(median \|Δt\| 2.393 s). `fa_char_first` already takes 6 of these 10; the oracle
takes 10 of 10. This is a pure **selection** failure: the candidate exists and
was not chosen.
*Example — glyph 3, `5|`, 1.0 beat, syllable «σας», pin 3.310 s. Annotator
Δt +0.530 s; the single in-gate candidate is at Δt −0.049 s.*

### SELECTION_AMBIGUOUS — 34 notes, 44.7 %
A candidate is inside 150 ms, but more than one is (mean 4.91 candidates within
±500 ms), or the nearest one is also the nearest to a neighbouring pin. Choosing
correctly needs more than proximity. The oracle takes 34 of 34 and
`fa_char_first` 22 of 34, so the 12-note difference between them is precisely
"which of the several nearby characters is the note".
*Example — glyph 4, `5|`, 1.0 beat, syllable «τωσταυ», pin 3.800 s. Three
candidates inside the gate; the nearest is Δt +0.021 s, the annotator is at
+0.960 s.*

### SUPPLY_TEXT — 6 notes, 7.9 %
No candidate inside 150 ms and the glyph *does* carry a fresh syllable: glyphs
7, 22, 72, 73, 74, 75. Four of the six (72–75) are the final cadence, where
NN-00's own fitted ruler runs −1.16 to −2.57 s because the singer slows and a
constant tempo cannot. The oracle scores 0 % here — there is nothing to select.
*Example — glyph 7, `5|`, 1.0 beat, syllable «ω», pin 5.293 s. One candidate
within ±500 ms, at Δt +0.388 s; annotator Δt +1.977 s.*

### SUPPLY_VOWEL — 1 note, 1.3 %
The §0.2 archetype in its pure form, and there is exactly one of it on this
piece. No syllable, no candidate inside the gate.
*Example — glyph 46, `4|`, 1.0 beat, no syllable, pin 28.484 s. Five candidates
within ±500 ms but none inside 150 ms (nearest +0.161 s); annotator Δt −3.014 s.*

### Nine notes with no candidate at any tolerance
Union of SUPPLY_TEXT, SUPPLY_VOWEL and two OWNED notes that the annotator
happens to get right without help: **7, 22, 46, 58, 61, 72, 73, 74, 75**. For
these the model must generate an onset from nothing — no candidate-selecting
system, oracle included, can place them.

---

## 3. RESYNC is not a separate class — it is all of the failure

`decide01_gap.py` extracts the spans that `onset_eval.slips()` counts, asserting
on every run that its walk returns the same count. The annotator's 2 slips are:

```
glyphs 3-47   45 notes
glyphs 70-75   6 notes
```

**All 51 failing notes lie inside those two runs, and no OWNED note does.** On
t03 there is no scattered-error class at all: the classes above describe *what
evidence is available to repair a desynchronised stretch*, not four independent
failure modes. Reported as overlap, not double-counted — SELECTION_CLEAN 10/10
in slip, SELECTION_AMBIGUOUS 34/34, SUPPLY_TEXT 6/6, SUPPLY_VOWEL 1/1.

This is §0.1's finding at note resolution: the aligner loses sync and
re-acquires it. It also means the zero-slip half of the §9 gate and the 90 %
half are the same problem on this piece, not two.

---

## 4. Evidence-class split (§9 requires it reported)

18 of 76 glyphs carry no fresh syllable — glyphs 0, 5, 12, 20, 21, 24, 32, 33,
38, 43, 44, 46, 50, 55, 56, 65, 67, 68 — matching NN-00's independently derived
count.

| system | ≤150 ms on the 18 | median \|Δt\| |
|---|---|---|
| annotator | 38.9 % | 1.131 s |
| `fa_char_first` | **0.0 %** (0 of 18 placed) | — |
| `nn00_prefix16_ols` | 22.2 % | 0.476 s |
| `nn00_lad_oracle` (fitted on the answer) | 44.4 % | 0.184 s |
| `fa_oracle` (reads the answer) | 94.4 % | 0.033 s |

The two rows worth staring at are the second and the last. The FA character rule
supplies **nothing** for any of the 18 — it has no character to attach — yet a
candidate lands within 150 ms of 17 of them anyway. So §0.2's framing needs one
correction: on t03 the continuing-vowel class is mostly **not** an absence of
nearby candidates; it is an absence of any *rule* that attaches one. That
correction is worth less than it looks — see §5.

NN-00's warning stands: `nn00_lad_oracle` reaches 44.4 % here while listening to
nothing at all. **An acoustic system scoring below ~44 % on continuing-vowel
notes has been beaten there by a ruler.**

---

## 5. The candidate ceiling, and how much of it is real

Counting pins with at least one character candidate inside the threshold:

| | ≤150 ms | ≤100 ms | ≤50 ms |
|---|---|---|---|
| candidate exists | **67 / 76 (88.2 %)** | 62 / 76 (81.6 %) | 46 / 76 (60.5 %) |
| density null — pins shifted 0.5–2.0 s off the music, median | 69.7 % | 58.6 % | 37.5 % |
| density null, worst case (max over shifts) | 80.3 % | 75.0 % | 53.9 % |

179 candidates over the sung span is dense enough that a pin placed at a
musically *wrong* time still finds a candidate within 150 ms about 70 % of the
time. The oracle beats its own density null by **18.4 points at 150 ms and 23.0
points at 50 ms** — real, but far smaller than the raw 88.2 % suggests, and the
gap between the oracle and the gate (88.2 % vs 90 %) is smaller than the gap
between the oracle and chance. Two consequences:

1. **Candidate proximity is not by itself a training signal.** A model rewarded
   for landing near some candidate is largely being rewarded for landing
   anywhere in the sung span.
2. **Selection cannot be the whole system.** Even a perfect selector tops out at
   88.2 %, below the 90 % gate, before the 9 candidate-less notes are placed.

A best-of-three combiner over the annotator, `fa_char_first` and
`nn00_prefix16_ols`, choosing per glyph by reading the gold answer, reaches
**77.6 % at 150 ms** (median \|Δt\| 0.046 s). **No arbitration among today's
systems reaches the gate**, which is the concrete form of §10's "the
encoder-decoder is a decision, not a hypothesis".

---

## 6. The sized problem

To reach **69 of 76** with **zero slips**:

| what must be newly owned | count | what has to happen |
|---|---|---|
| SELECTION_AMBIGUOUS | 34 | choose among ~4.9 nearby candidates using acoustics and the beats prior |
| SELECTION_CLEAN | 10 | take the single in-gate candidate instead of drifting past it |
| SUPPLY_TEXT | 6 | emit an onset with no candidate; 4 of the 6 are the final cadence |
| SUPPLY_VOWEL | 1 | emit an onset with no candidate and no syllable |
| **total failing** | **51** | of which **44** must be fixed; 7 may remain wrong |
| plus: hold OWNED | 25 | a regression here costs the gate one-for-one |

Selection versus supply, as the gate sees it: **44 of the 51 failures are
selection** (86 %) and **7 are supply** (14 %) — but supply is the class with a
hard ceiling of zero from every candidate-based method, and 4 of the 7 sit in
the closing cadence where the arithmetic prior also collapses.

---

## 7. What the §5 encoder-decoder can and cannot fix

**Architecturally able:**

- **SELECTION_CLEAN (10) and SELECTION_AMBIGUOUS (34).** §5.2 feeds "FA
  candidate onsets in window" to the decoder and §7 decodes by selecting among
  them; §5.1's local cross-attention (±150 frames, 3 s) covers a neighbourhood
  that on this piece holds ~4.9 candidates. This is the case the architecture
  was chosen for.
- **The 51-note and 6-note slip runs.** §5.1's GLOBAL path over the 0.5 s-pooled
  summary is the stated mechanism for "where am I in this hymn", and §7's
  backtracking with unit insert/delete is the stated mechanism for recovering a
  path that consumed the wrong number of units. Both slip runs are long, so
  local evidence alone cannot end them.
- **The 9 candidate-less notes.** §5.3's Δt head is a distribution over 201
  bins, not a pointer into a candidate list, so it *can* emit an onset where no
  candidate exists. Whether it does so accurately rests entirely on stream C
  (§4) and the `beats` prior, since neither text nor candidates say anything
  there.
- **Ambiguity representation.** §5.3 explicitly rejects point regression so the
  model can say "0.31 s, or 0.62 s if a note was skipped". SELECTION_AMBIGUOUS
  at 44.7 % of the piece is why that clause is load-bearing.

**Not fixable by §5, and must be booked elsewhere:**

- **Wrong or missing syllable labels.** The model consumes SYL-01's stream; it
  cannot repair it. §10 already gates SYL-01 chanter review before NN-05, and
  §0.4 records that t03's labels are known incomplete.
- **The 4-note closing cadence (72–75) as an arithmetic problem.** No prior and
  no candidate helps; only audio. If stream C carries no usable attack there,
  those 4 notes are lost and the gate has 3 of its 7 slack notes left.
- **Genuinely ambiguous adjacent notes.** §9.1's shortest inter-onset interval
  is 0.287 s, so ±150 ms windows on adjacent notes overlap by 13 ms. A handful
  of notes cannot be disambiguated by the gate itself.
- **The interval/martyria constraint.** §7 evaluates CHECK-01 and *logs* it
  until Gate C (§1.1). CHECK-01 reported **FAIL** against its own gate — 26 of 58
  gaps still violated against a bar of fewer than 8 — so it is not yet an anchor
  the decoder may trust, and that number is CHECK-01's, not re-measured here.
- **The word-level FA path.** REPRO-01 measures it at 26.3 % (recovered) and
  23.7 % (stored artefact, re-aligned on the current audio) at 150 ms, against
  the character path's 55.3 %. §5.2's candidate input must be the character
  path. *Corrected 2026-08-20:* an earlier draft of this line read 1.3 % for the
  stored artefact — that was a stale time base, not a property of the word path;
  see NEURAL-CHANT.md §0.4. The conclusion is unchanged, and for a better
  reason: the word path is weak because a word onset times only the first note
  of its word, not because the aligner is imprecise.

---

## 8. What this brief does not show

- Every ceiling quoted — `fa_oracle`, `nn00_lad_oracle`, the best-of-three
  combiner — was computed with the gold answer in hand. None of them is
  achievable, and nothing here says a real selector approaches one.
- One piece, 76 notes, one singer, one recording. The class shares (44.7 %
  ambiguous, 1.3 % pure continuing-vowel supply) are t03's, and a piece with
  longer melismata would move them sharply. In particular, **SUPPLY_VOWEL has a
  sample size of one**; §0.2's claim that this is the class the model exists for
  is not measurable on t03 and must be re-sized on a piece that has more of it —
  never on s01.
- t03 is trained on. Re-running this brief after NN-05 measures fit, not skill.
- No annotation floor exists yet. PIN-REPEAT-01 (§10) sets it, and until it
  reports, the 50 ms column here is a diagnostic that may be partly measuring
  pinning noise (§9.1).
