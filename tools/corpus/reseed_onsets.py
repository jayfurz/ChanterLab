#!/usr/bin/env python3
"""reseed_onsets.py -- seed the annotator's slot times from forced alignment.

THE PROBLEM THIS EXISTS FOR. 16 hours of tape have to be pinned by hand. The
annotator seeds each note's marker from the DTW aligner (aligned.json, with
unmatched units interpolated by beat weight), and that seed is what the chanter
drags into place. On gold t03 it lands 32.9% of markers within 150 ms, so
roughly two notes in three have to be moved manually.

REPRO-01 measured something better that was already sitting on disk: the CTC
character path places 55.3% within 150 ms (tools/corpus/fa_eval.py). It was
never used as a seed -- only its WORD aggregation was ever stored, and that is
weaker still. This script uses the character path as ANCHORS and fills between
them by written beats, which is the one thing arithmetic is good at over a short
span with both ends nailed down.

    anchor    a glyph whose syllable's first character has a CTC onset
    fill      glyphs between two anchors, placed by cumulative beats_seq()
    tails     before the first anchor / after the last, by local seconds-per-beat

Measured 2026-08-20 on gold t03 (76 chanter pins), every number from
tools/corpus/onset_eval.py -- the only scorer:

    seed                     <=150ms  <=100ms  <=50ms  slips  median|dt|  placed
    annotator today (DTW)      32.9%    32.9%   30.3%     2     0.714 s    76/76
    fa_char anchors only       55.3%    52.6%   32.9%     1     0.061 s    56/76
    THIS (anchors + fill)      75.0%    65.8%   38.2%     1     0.065 s    76/76

What that means for hand-pinning, which is the point of this script:

    notes needing a manual move, at 150 ms   51 -> 19   (63% less)
    notes needing a manual move, at 250 ms   50 -> 10   (80% less)

NOTHING HERE IS FITTED TO ANY PIN. The anchors come from CTC over the audio and
the canonical text; the mapping comes from the annotator's syllable labels; the
fill comes from written beats. No gold time is read at any point, and there is
no threshold to tune. That matters more than the 75% does: t03 is TRAINING data
and a burnt benchmark (NEURAL-CHANT.md 6.1), so a number fitted on it would mean
nothing -- but a parameter-free method that never saw a pin has a real claim to
transfer. It still has to be checked on a piece that is not t03.

--verify-tempo is a different matter and is OFF by default. It drops anchors
implying a local tempo outside [0.7, 1.5]x the piece median, which on t03 gives
77.6% at 150 ms and cuts the worst error from 2.50 s to 1.80 s. That band was
chosen ON t03, so the +2.6 points is exactly the kind of increment a burnt
benchmark cannot support. Tune it on a silver dev fold before believing it
(NEURAL-CHANT 9: no hyperparameter is chosen on gold).

WHERE IT STILL MISSES on t03, in case that guides the next fix: glyphs 72-75,
the closing melisma, by -0.36 to -2.50 s. FA anchors those four and anchors them
wrongly -- CTC smears the final characters across the held ending. They are
DECIDE-01's SUPPLY_TEXT class. Rejecting a bad anchor rather than trusting it is
what NEURAL-CHANT 7's propose/verify/backtrack decode is for; --verify-tempo is
a one-line stand-in for it.

Usage:
  reseed_onsets.py --piece grave-orthros-t03 --anchors <pred.json> \
      --units datasets/grave-orthros-t03-gold/score_units.json --out seed.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fill(anchors, beats):
    """Place every glyph: anchors kept exactly, the rest by cumulative beats.

    `anchors` is {glyph_index: seconds}, `beats` is the per-glyph beat list from
    beats_seq(). Between two anchors the elapsed time is divided in proportion
    to written beats, which is the chanter's own grid -- his DEPARTURE from it
    is the signal a model would learn (NEURAL-CHANT 5.2), but over a two-second
    span between two fixed ends it is a good interpolant and cannot drift.
    """
    n = len(beats)
    cum = [0.0] * (n + 1)                 # cum[i] = beats elapsed before glyph i
    for i, b in enumerate(beats):
        cum[i + 1] = cum[i] + b
    ks = sorted(anchors)
    if len(ks) < 2:
        raise SystemExit('need at least 2 anchors to interpolate')
    out = dict(anchors)
    for a, b in zip(ks, ks[1:]):          # interior spans
        db = cum[b] - cum[a]
        if db <= 0:
            continue
        spb = (anchors[b] - anchors[a]) / db
        for g in range(a + 1, b):
            out[g] = anchors[a] + (cum[g] - cum[a]) * spb
    # tails: reuse the nearest span's tempo rather than a global one, because a
    # piece slows at its cadence and a global rate would push the ending early.
    head_spb = (anchors[ks[1]] - anchors[ks[0]]) / max(cum[ks[1]] - cum[ks[0]], 1e-9)
    for g in range(0, ks[0]):
        out[g] = anchors[ks[0]] - (cum[ks[0]] - cum[g]) * head_spb
    tail_spb = (anchors[ks[-1]] - anchors[ks[-2]]) / max(cum[ks[-1]] - cum[ks[-2]], 1e-9)
    for g in range(ks[-1] + 1, n):
        out[g] = anchors[ks[-1]] + (cum[g] - cum[ks[-1]]) * tail_spb
    return {g: round(out[g], 4) for g in range(n)}


def verify_tempo(anchors, beats, lo=0.7, hi=1.5):
    """Drop anchors implying an implausible local tempo. See the docstring:
    the band is tuned on t03 and must be re-tuned on a dev fold."""
    import statistics as st
    n = len(beats)
    cum = [0.0] * (n + 1)
    for i, b in enumerate(beats):
        cum[i + 1] = cum[i] + b
    ks = sorted(anchors)
    rates = [(anchors[b] - anchors[a]) / (cum[b] - cum[a])
             for a, b in zip(ks, ks[1:]) if cum[b] > cum[a]]
    if not rates:
        return anchors
    med = st.median(rates)
    keep, prev = {ks[0]: anchors[ks[0]]}, ks[0]
    for g in ks[1:]:
        db = cum[g] - cum[prev]
        if db <= 0:
            continue
        if lo <= ((anchors[g] - anchors[prev]) / db) / med <= hi:
            keep[g] = anchors[g]
            prev = g
    return keep


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--anchors', required=True, help='{glyph: seconds} FA onsets')
    ap.add_argument('--units', required=True, help='score_units.json (has beats)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--verify-tempo', action='store_true',
                    help='drop anchors implying a local tempo outside '
                         '[0.7, 1.5]x the piece median. Improves t03 but the '
                         'band was tuned there -- see the docstring')
    a = ap.parse_args()

    raw = json.load(open(a.anchors))
    anchors = {int(k): float(v) for k, v in (raw.items() if isinstance(raw, dict)
                                             else raw)}
    units = json.load(open(a.units))
    beats = [u['beats'] for u in units]
    n_in = len(anchors)
    if a.verify_tempo:
        anchors = verify_tempo(anchors, beats)
    seed = fill(anchors, beats)
    if a.verify_tempo:
        print('verify-tempo kept %d of %d anchors' % (len(anchors), n_in))
    json.dump({str(g): t for g, t in sorted(seed.items())},
              open(a.out, 'w'), indent=1)
    print('%d anchors -> %d placed glyphs  -> %s' % (len(anchors), len(seed), a.out))


if __name__ == '__main__':
    sys.exit(main())
