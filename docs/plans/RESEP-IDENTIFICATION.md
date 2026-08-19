# RESEP — why identification fails, measured

The re-separation effort was steering on the CTC loss gate (`lpt <= 4.5`),
which rated 129/160 hymns confident. `tools/corpus/name_check.py` shows that
number does not mean what it looked like.

## The free evaluation set

56 hymns are named with a transliterated incipit rather than a sequence
number, because that is how the chanter foldered them — `kyrie-ekekraxa`,
`ean-anomias`, `ek-vatheon-doxazo`. Those names predate anything CTC does, so
they are an independent accuracy check that costs no labelling. The
romanisation reproduces exactly (Κύριε ἐκέκραξα -> kyrieekekraxa, Ἐκ βαθέων ->
ekvatheon, Ἄσπορος -> asporos), so the comparison is sound.

25 of them have assignments to check.

## End-to-end result

     5/25 (20%)  start on their own incipit
     5/25 (20%)  contain it but start early — right hymn, wrong boundary
    15/25 (60%)  do not contain it at all — wrong text

mode2 is the case that settles it: the gate called it 15/15 confident, and 5
are right. The gate measures acoustic plausibility, not correctness.

## Where the error actually enters

Reading the cached per-segment candidate scores back for mode2's 15 named
hymns separates three distinct failures that the 20% figure conflates:

    8/15  the solver picked the correct candidate (rank 1)
          — of these, 3 have a candidate whose TEXT opens on the preceding
            psalm verse, so the hymn is right and the boundary is not
    3/15  correct text was in the pool at rank 4-8; solver took rank 1
    4/15  correct text was not among the 8 cached candidates at all

So candidate SELECTION is ~53% right, not 20%. The remaining error splits into
a pool-construction problem and a boundary problem, and each needs its own fix.

## The decisive number

In all three near-miss cases the margin is nothing:

    ton-pro-aionon    correct 4.38/tok   chosen 3.90/tok
    dia-xylou         correct 4.15/tok   chosen 4.10/tok
    en-to-stavro      correct 3.80/tok   chosen 3.77/tok

0.03-0.48 per token. The scorer barely discriminates between the right text
and a generic psalm verse, which is why the same boilerplate ("Τοῦ ποιῆσαι ἐν
αὐτοῖς κρῖμα", "οῦ δῆσαι τοὺς βασιλεῖς") wins over and over: bland common verse
text is cheap to align to anything. Any genuinely independent signal would
dominate a margin this thin.

## What was tried and did not work

Syllables per score-unit, as a duration/length prior. Measured over mode2's
120 candidate/hymn pairs: 1.05 median for candidates matching the hymn name,
1.19 for those not. No separation — refuted. (It does establish that this
chant runs near one syllable per notated unit, which is worth keeping.)

## Consequences already applied

- The 44 adopted segment-edge cuts are reverted. At 20% end-to-end precision
  they replace good audio more often than they fix bad. `hymns.json` restored
  from the `.pre-resep` backups.
- Gold is back at revision 4, pins unshifted against `004_melos_fixed.wav`.
- `resep_recut.py` keeps its duration guard and its speech-rescue path; both
  are correct, but neither should be run again until selection improves.

## Next, in order of expected value

1. Pool construction — 4/15 never had the right answer available. Find out
   whether the run is missing from the pool or pruned out of the top-8, since
   the fixes differ.
2. A tie-breaker for the near-ties. The hymn name gives one free for 56
   hymns; for the rest, position on the tape and the drop cap are the
   candidates. Do not use syllable count.
3. Candidate runs that open on the preceding verse — this is the chanter's
   "starts an entire line too early", appearing in the text runs rather than
   in the score.

Score `name_check.py`, not loss.
