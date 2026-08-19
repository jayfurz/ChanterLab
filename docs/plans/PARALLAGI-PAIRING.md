# The parallagi/melos pairing is a hard structural prior

Measured on the first hand-cut tape (Grave mode Orthros, `datasets/
grave-orthros-tape-gold`), chanter-cut by ear across 61.6 minutes:

    47 spans   23 parallagi   23 melos   strict alternation   0 orphans

Chanter: "for that tape it looks like every single hymn melos is preceded by
its accompanying paralagi. no orphan parallagi or melos found."

Verified programmatically: every melos span is immediately preceded by a
parallagi span, and every parallagi span is immediately followed by a melos
span. The single exception is the first span of the tape, which carries no
lane and belongs to no pair.

A pair is not necessarily one liturgical item. Chanter: "he does parallagi all
the way through for all the anavathmoi through the two prokeimena, then the
next span is only melos. he does alternate, thats just the way it was done."
So the unit of pairing is the RENDITION, not the hymn -- one 291 s parallagi
covering the anavathmoi and both prokeimena, then its melos. Anything that
assumes a pair maps to a single hymn will mis-slice these.

The two halves of a pair can also carry different score ranges. The doxology
melos stops at "ελπίσαμεν επί σε" where the tape ran out, while its parallagi
runs to the end of the doxology, so the parallagi's score range is longer. The
range belongs to the span, not to the hymn.

## Why this matters more than any scoring change

Identification has been attacked as a text problem and it does not work — the
loss gate said 81%, the hymn names said 20% (`RESEP-IDENTIFICATION.md`), and
the reason is now clear: roughly half the audio is not text at all, it is sung
degrees, so for those spans there is no correct answer in the candidate pool
and the blandest psalm verse wins by default.

The pairing turns that liability into the strongest constraint available:

- A melos span's identity is the identity of the parallagi immediately before
  it. Identify either one and the other is free.
- Parallagi spans should be EXCLUDED from text identification. The lane is
  known from position, and it is ALSO detectable acoustically -- see below.
- The count is a checksum. A tape that does not come out to equal numbers of
  parallagi and melos, strictly alternating, has a boundary error somewhere,
  and the tool can say so before a human looks.

## What it says about the current cuts

Scoring `hymns.json` for this tape by IoU against the 23 gold melos spans:

     4/25  IoU >= 0.90   essentially right
    10/25  IoU 0.50-0.90 overlaps but wrong bounds
    11/25  IoU < 0.50    wrong span
           median IoU 0.56

The dominant failure is over-splitting: `t21`/`t22`/`t23` all fall inside a
single gold melos span, as do `t54`/`t55`/`t57`, `t05`/`t06`, and `t33`/`t34`.
The pipeline was cutting at silences inside a hymn and calling each piece a
separate hymn. The parallagi that precedes each real hymn would have ruled
every one of those splits out.

## Caveats carried by this tape

- The doxology melos is cut off — it did not fit on the 60-minute tape. Its
  parallagi is complete, so the pair is usable on the parallagi side only.
- One hymn was interrupted by the tape flip and restarted; only the complete
  replay is marked, and the truncated attempt is deliberately outside every
  span.
- A stretch of Vasilikos talking about a hymn is deliberately outside every
  span. Uncovered material on this tape is excluded on purpose, never by
  oversight — 5 gaps, 1.1 minutes total, plus a 61.3 s head.

## Next

Cut a second tape, then test whether pairing plus position alone assigns the
right text without any acoustic identification. Score with `name_check.py` and
against these spans — never against loss.


## The lane is acoustically detectable after all

Recorded here because the earlier conclusion in this file was wrong.

A first detector asked what FRACTION of decoded letters belong to the degree
names, thresholded at 0.80, and failed its control (known-parallagi 0.53-0.80
against known-melos 0.49-0.65). From that I concluded the model cannot hear
sung solfege. That conclusion does not follow, and it is false. Reading the
decodes rather than the summary statistic:

    parallagi   ΠΑΨ ΠΑΒΟΎ-ΚΑΡΒΉ ΒΗ ΚΕΖΏ-Ο- ... ΒΟΥΚΑΔ Κ-Ε-ΘΗ ΔΗ Κ-ΕΑ-ΔΙ
    melos       ΑΤΈΛΙΣΑΣΤΌΣΤΑΦΑΏΣΟΥΣ ΤΟΝ ΘΆΡΝΑΚΤΟΝ   (Κατέλυσας τῷ Σταυρῷ...)

The degree names are plainly present; they are surrounded by junk letters,
which is exactly what a letter-fraction measure cannot see. The right unit is
the TOKEN. Counting occurrences of πα/βου/γα/δι/κε/ζω/νη per second, over the
chanter's 46 labelled gold spans (`degree_tokens.py`):

    parallagi   n=23   median 0.72 deg/s   range 0.24 - 1.28
    melos       n=23   median 0.12 deg/s   range 0.00 - 0.28

The medians differ by 6x and the ranges barely touch. A threshold at 0.43
deg/s misreads no melos span as parallagi and misses 2 of 23 parallagi: 96%.

Two things follow. Lane detection no longer depends on a tape being cut in
order, which matters for the three tapes that arrive already split into
per-hymn files. And step 4 -- matching called-out degrees against notated ones
-- has a working front end.

It is not yet good enough for step 4 itself. The recovered sequences are
Vou/Ke-heavy and do not obviously track a melody, so the token stream is
usable as a RATE but not yet as a SEQUENCE. Getting from one to the other is
the open problem, and it should be measured against the score's own degrees
rather than against unitdeg, which was itself derived from parallagi
alignment and would make the test circular.
