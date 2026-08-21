#!/usr/bin/env python3
"""degree_range_check.py -- no hymn leaves the two-octave ladder.

Chanter, 2026-08-21: "all hymns sit between low di and di'' with very few
exceptions -- not in this book or any of the hymns at all."

That is a free, label-less correctness check on the whole degree pipeline, and
a blunter one than martyria_check: a stream that reaches three octaves above its
base has not drifted by a step, it has lost an octave outright, and no amount of
per-interval argument explains it.

    valid range   low Δι (-3)  ..  Δι'' (+11)      15 degrees

Measured over the 47 chanter-ranged spans on 2026-08-21, after the cluster-89
octave fix: 4,862 notes inside, 1,036 outside, and every one of the outliers in
just 4 spans -- which are two duplicated pairs, so two distinct pieces:

    t01_ / t01_#21     range +0..+22   407 notes out
    t01_#32 / t01_#33  range -3..+24   111 notes out

Both run to three octaves above the base, which is the signature of the same
fault this check was written after: an opening martyria read in the wrong
register. See MARTYRIA_OCT in hymn_align.py.

Usage:
  degree_range_check.py            # exits 2 if any span leaves the ladder
  degree_range_check.py --worst 10
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_degrees import units_for, degree_stream, leading_anchor, DEG

CUTS = '/mnt/data/chant-corpus/texts/scorecuts_grave-orthros.json'
LEGEND = '/mnt/data/chant-corpus/scores/legend_canon.json'
LO, HI = -3, 11


def name(d):
    o, i = divmod(int(d), 7)
    return DEG[i] + ("'" * o if o > 0 else ',' * -o)


def check():
    leg = json.load(open(LEGEND))
    rows = []
    for c in json.load(open(CUTS))['cuts']:
        u = units_for(c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
        d = [int(x) for x in degree_stream(u, leg, start=leading_anchor(c['p0'], c['g0']))]
        if not d:
            continue
        bad = [v for v in d if not LO <= v <= HI]
        rows.append({'hymn': c['hymn'], 'n': len(d), 'lo': min(d), 'hi': max(d),
                     'out': len(bad)})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--worst', type=int, default=6)
    a = ap.parse_args()
    rows = check()
    tot = sum(r['n'] for r in rows)
    out = sum(r['out'] for r in rows)
    bad = [r for r in rows if r['out']]
    print('%d spans, %d notes' % (len(rows), tot))
    print('  inside low %s .. %s : %d' % (name(LO), name(HI), tot - out))
    print('  outside                : %d  (%.2f%%) in %d span(s)'
          % (out, 100 * out / max(tot, 1), len(bad)))
    if bad:
        print('\n  a span reaching past the ladder has lost an octave, not a step:')
        for r in sorted(bad, key=lambda r: -r['out'])[:a.worst]:
            print('    %-10s %4d notes  range %s(%+d)..%s(%+d)  %d out'
                  % (r['hymn'], r['n'], name(r['lo']), r['lo'],
                     name(r['hi']), r['hi'], r['out']))
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
