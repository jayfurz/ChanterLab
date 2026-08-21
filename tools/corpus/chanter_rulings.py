#!/usr/bin/env python3
"""chanter_rulings.py -- the chanter's per-glyph rulings, as a regression suite.

25 rulings sit in datasets/grave-orthros-t03-gold/chanter_notes.json as free
text. Nine carried `pending_transcription: true` and were never compiled into
anything a test could read, which meant nobody could tell whether the code still
agreed with them. One of those nine (gi=63) turned out to be the only genuinely
held-out evidence for CHECK-01's largest legend change -- it had been sitting
there unread the whole time.

Compiled 2026-08-21. Every one of the nine is ALREADY SATISFIED by the current
code; none required a change. The `machine_beats: 1.0` recorded beside them is
stale, captured before the klasma/dipli duration rules were fixed, which is why
they looked outstanding.

The claims, transcribed from his words, with the phrase each is drawn from:

  gi=19  3|22ab+8be   iv +0, 2 beats   "Ison plus kentimata with klasma below.
                                        2 beats, +0 interval"
  gi=45  3|8be              2 beats    "Petasti with KLASMA on bottom. Should
                                        add an extra beat"
  gi=48  7|6ab        iv +1            "Vareia is qualitative. Oligon makes it +1"
  gi=50  4|8ab              2 beats    "Apostrophos with KLASMA on top. Two beats"
  gi=61  6|8ab              2 beats    "Oligon with petasti. Hold an extra beat"
  gi=63  7|16ab+6ab   iv +3            "Oligon with kentima on top like this is
                                        +3. Vareia underneath qualitative"
  gi=66  3|8be              2 beats    "Petasti with klasma compound. Should be
                                        plus one beat"
  gi=71  7|6ab        iv +1            "an oligon with psifiston underneath.
                                        Should be +1 interval"
  gi=75  6|10be+10be        3 beats    "a oligon with a dipli"  (dipli adds two)

"Should add an extra beat" is read as 1 + 1 = 2 and "a dipli" as 1 + 2 = 3, per
his own duration rule recorded in beats_written(): "apli is one beat, dipli is
two beats, tripli is 3".

NOT a ruling, and still open -- gi=50 ends with a question to us: "The martyria
afterwards says ga. Is that degree 3? Just use the solfege syllables." Ga is
degree 3. The second half is a request about presentation, not notation, and the
annotator does show solfege (deg_label). Left here so it is not lost.

This file does not decide anything. It reads the rulings and the live code and
reports disagreement, so a legend or duration change that contradicts the
chanter fails loudly instead of silently.

Usage:
  chanter_rulings.py            # exits 2 on any disagreement
  chanter_rulings.py --verbose
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))

GOLD = os.path.join(ROOT, 'datasets/grave-orthros-t03-gold')
CUTS = '/mnt/data/chant-corpus/texts/scorecuts_grave-orthros.json'
LEGEND = '/mnt/data/chant-corpus/scores/legend_canon.json'
HYMN = 't01_#4'                 # the melos of Katelysas == gold t03's score

# glyph -> what he ruled. Transcribed by hand from the free-text notes above;
# the note text stays the source of truth and is re-printed on failure.
CLAIMS = {
    19: {'iv': 0, 'beats': 2.0},
    45: {'beats': 2.0},
    48: {'iv': 1},
    50: {'beats': 2.0},
    61: {'beats': 2.0},
    63: {'iv': 3},
    66: {'beats': 2.0},
    71: {'iv': 1},
    75: {'beats': 3.0},
}


def load():
    from score_degrees import units_for
    from hymn_align import beats_seq
    c = {x['hymn']: x for x in json.load(open(CUTS))['cuts']}[HYMN]
    units = units_for(c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
    return units, beats_seq(units)


def check(verbose=False):
    units, beats = load()
    keys = json.load(open(LEGEND))['keys']
    notes = {r['gi']: r for r in json.load(open(os.path.join(GOLD, 'chanter_notes.json')))}
    fails = []
    for gi, claim in sorted(CLAIMS.items()):
        u = units[gi]
        got_iv = u.get('iv')
        if got_iv is None:
            got_iv = keys.get(u['key'], keys.get('%s|' % u['base']))
        got_b = beats[gi]
        for field, want, got in (('iv', claim.get('iv'), got_iv),
                                 ('beats', claim.get('beats'), got_b)):
            if want is None:
                continue
            ok = (got is not None and abs(got - want) < 1e-6)
            if verbose or not ok:
                print('%s gi=%-3d %-16s %-6s chanter %-6s code %s'
                      % ('ok  ' if ok else 'FAIL', gi, u['key'], field, want, got))
            if not ok:
                fails.append((gi, field, want, got, (notes.get(gi, {}).get('note') or '').strip()))
    print('\n%d rulings checked, %d disagreements' % (
        sum(len([k for k in c if k in ('iv', 'beats')]) for c in CLAIMS.values()), len(fails)))
    for gi, field, want, got, note in fails:
        print('\n  gi=%d %s: chanter %s, code %s' % (gi, field, want, got))
        print('    "%s"' % note)
    return 2 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--verbose', action='store_true')
    return check(ap.parse_args().verbose)


if __name__ == '__main__':
    sys.exit(main())
