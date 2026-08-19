# Boundary heuristics, measured on the first gold tape

The chanter cut Grave Orthros end to end — 47 audio spans, 47 score ranges —
and then described how he does it:

> "the beginning is usually preceded by a silence and inhaling breath, and the
> endings were found in the same place. (also he likes to hold the last note a
> little longer and does a retardando for most of the hymns near the end) and
> the waveform is pretty easy to spot (fades out). For the scores, the start of
> each hymn is always a dropcap, and ends with a compound glyph and there would
> be martyria on the right send of the page almost like an endcap to each hymn
> ... and in general the parallagi is always followed by its melos."

Every one of those is checkable against what he cut. `heuristics_eval.py`
measures them separately, because a rule that holds 26/26 can be a hard
constraint while one that holds 21/26 can only be a prior, and treating the
second like the first is exactly how the earlier automatic passes failed.

## Measured

    AUDIO                                 (47 spans)
      silence before the start            46/47   98%
      silence after the end               42/47   89%
      fades into the last second          47/47  100%

    SCORE                                 (26 distinct ranges)
      starts on a drop cap                26/26  100%
      ends on a compound                  21/26   81%
      martyria as an endcap               23/26   88%

    STRUCTURE
      melos preceded by its parallagi     23/23  100%

Counting note: a parallagi and its melos usually share one score range, so the
47 score ranges collapse to 26 distinct ones. Scoring per span would
double-count every shared range and flatter the result.

The martyria figure was 62% and that was the detector, not the rule. It was
testing `mart_deg`, which records only the six LETTER clusters that can anchor
a degree. The chanter's atlas labels eleven martyria-family clusters -- letters
AND scale signs -- and a cadence is marked by the whole compound. Testing for
presence over the full family (`MARTYRIA_ANY`) gives 23/26. Only two ranges end
without one.

Note the distinction that keeps this safe: a scale sign says which SCALE, the
letter says which DEGREE, so only letters may anchor a degree. Cluster 24 was
wrongly used as an anchor once before and removed. `MARTYRIA_ANY` is for
presence only and does not touch `MARTYRIA_DEG`.

## Three hard constraints

Two of these are exact on the gold tape and one is a definition:

1. **Every score range starts on a drop cap.** 26/26. This can prune the search
   rather than merely rank it — a proposed start that is not a drop cap is
   wrong.
2. **The recording fades into its last second.** 47/47. The ritardando is
   measurable, not impressionistic.
3. **Every melos is immediately preceded by its parallagi.** 23/23. See
   `PARALLAGI-PAIRING.md`; the pairing unit is the rendition, so one pair can
   cover several liturgical items (all the anavathmoi through both prokeimena;
   the whole doxology).

## The order the steps have to run in

The chanter: "that makes this a 4 or 5 step process with all the hueristics
that i told you about, and each step and hueristic is important."

    1. segment the audio      silence + inhale before, fade + silence after
    2. label the lanes        alternation: parallagi, then its melos
    3. bound the score        drop cap opens, compound closes, martyria endcaps
    4. bind score to audio    transcribe the melos words, OR read the parallagi's
                              called-out degrees against the score's degrees
    5. check                  equal alternating lane counts; every start on a
                              drop cap; ranges monotonic down the book

Step 4 is the one with no working implementation. Text identification was
measured at 20% end to end and 2/8 even when restricted to melos spans
(`RESEP-IDENTIFICATION.md`), because roughly half the audio is sung degrees and
has no text to match. The chanter's alternative — match the DEGREES the
parallagi calls out against the degrees the score notates — has not been tried
and does not depend on the failed component.

## Where the misses cluster

The score-end rules miss on the same handful: the long composite spans (the
anavathmoi run, the doxology) and the unlabelled first span. That is consistent
with the rule being about hymn endings rather than span endings: a span covering
several hymns ends where the LAST one ends, and the intermediate compounds and
martyria fall inside it. Worth checking against a second tape before drawing
conclusions from one.

## Caveats carried by this tape

- The doxology melos is truncated by the 60-minute tape; its parallagi is whole,
  so the two halves of that pair carry different score ranges.
- Span #01 has no lane and no partner: the anavathmoi and both prokeimena.
- Vasilikos speaks inside the anavathmoi parallagi. Skip intervals exist for
  this in the tool; none are recorded on this tape yet.

## Snapping, and what it is worth

Two of these rules are usable as tap aids in the score picker, and their
strength differs:

    starts -> nearest drop cap    26/26 recall, hard    167/168 recovery
    ends   -> nearest compound    21/26 recall, soft    123/175 vs 25 unaided

Recovery is measured by replaying every gold boundary tapped 1-5 units off in
either direction. On a score of ~6,400 units this is the difference between
marking a boundary and hunting for one.

Two things were tried for ends and rejected:

  - Predicting the end outright as the last compound before the NEXT drop cap:
    7/26. Drop caps over-generate 4:1 because they also open verses inside a
    hymn, so the next cap is usually not the next hymn.
  - Adding martyria positions to the end snap targets: 58%, DOWN from 70%.
    The rule is a good description of where ends fall and a bad snap target,
    because more candidates dilute the snap. Descriptive accuracy and snapping
    utility are not the same property.
