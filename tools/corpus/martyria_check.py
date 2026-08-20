#!/usr/bin/env python3
"""martyria_check.py — score the legend against the printed martyrias.

A cadence martyria is a claim about which degree is being sung at that note.
Between two consecutive cadence martyrias the intervals the legend assigns must
sum to the difference in degree. That is a free, label-less check on the whole
interval model: 3,886 checkpoints corpus-wide, no chanter time spent.

This is the CHECK-01 gate in docs/plans/NEURAL-CHANT.md.  Measured 2026-08-20
over the 47 chanter-ranged spans:

    57 gaps   17 satisfied   40 VIOLATED  (70%)
    disagreement:  -1 in 14 gaps, -2 in 13, +1 in 5, rest scattered
    33 "sum too LOW"  (an ison should have been an oligon) -- 31 have room
     7 "sum too HIGH" (an oligon should have been an ison) --  6 have room

(The 47 chanter ranges overlap at their edges; before deduping the same gap was
counted up to twice, giving 103/71. The ratio was unchanged, the counts were
not.)

The asymmetry matters. Turning an oligon into an ison can only LOWER a sum, so
the ison/oligon ambiguity cannot explain the 57 low gaps -- those are a
systematic rule gap on the "not climbing enough" side. Fix the rule before
building a constraint solver on top of it, or the solver invents a different
local excuse for every gap.

Usage:
  martyria_check.py                 # the 47 chanter-ranged spans (the gate)
  martyria_check.py --all           # every hymn with a scorecut
  martyria_check.py --worst 20      # list the worst-disagreeing gaps
"""
import argparse, json, os, sys, collections, statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_degrees import units_for

CORPUS = '/mnt/data/chant-corpus'
LEGEND = f'{CORPUS}/scores/legend_canon.json'
CUTS   = f'{CORPUS}/texts/scorecuts_grave-orthros.json'


def interval(u, keys):
    """The legend's melodic step for a unit, or None if it has no opinion."""
    v = u.get('iv')
    if v is None:
        v = keys.get(u['key'], keys.get(f"{u['base']}|"))
    return v


def gaps_for(units, keys):
    """Yield one record per span between consecutive cadence martyrias."""
    notes = [u for u in units if not u.get('rest')]
    cps = [(i, u['mart_cad'][0]) for i, u in enumerate(notes) if u.get('mart_cad')]
    for (a, deg_a), (b, deg_b) in zip(cps, cps[1:]):
        seg = notes[a + 1:b + 1]
        ivs = [interval(u, keys) for u in seg]
        if any(v is None for v in ivs):
            continue                      # legend has no opinion; not a violation
        # a bar read as an oligon could be an ison  -> each demotion lowers by 1
        room_down = sum(1 for u in seg if u['base'] == 6)
        # a bar read as an ison could be an oligon  -> each promotion raises by 1
        room_up = sum(1 for u in seg if u['base'] in (5, 22))
        yield {
            'units': len(seg),
            'delta': sum(ivs) - (deg_b - deg_a),
            'room_down': room_down,
            'room_up': room_up,
            'p0': seg[0]['pl'][0], 'l0': seg[0]['pl'][1],
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--worst', type=int, default=0,
                    help='list the N worst-disagreeing gaps')
    a = ap.parse_args()

    keys = json.load(open(LEGEND))['keys']
    cuts = json.load(open(CUTS))['cuts']

    # The 47 chanter ranges overlap at their edges, so the same martyria pair
    # can fall inside two spans. Key on the gap itself, not on the span that
    # found it -- counting it twice would inflate the gate.
    uniq = {}
    for c in cuts:
        us = units_for(c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
        for g in gaps_for(us, keys):
            g['hymn'] = c['hymn']
            uniq.setdefault((g['p0'], g['l0'], g['units'], g['delta']), g)
    recs = list(uniq.values())

    if not recs:
        print('no gaps found — is the scorecut file present?')
        return 1

    ok = [g for g in recs if g['delta'] == 0]
    bad = [g for g in recs if g['delta'] != 0]
    low = [g for g in bad if g['delta'] < 0]
    high = [g for g in bad if g['delta'] > 0]

    print(f'{len(recs)} gaps between consecutive cadence martyrias')
    print(f'  gap length         median {st.median(g["units"] for g in recs):.0f} units')
    print()
    print(f'  SATISFIED  {len(ok):4d}')
    print(f'  VIOLATED   {len(bad):4d}   ({100*len(bad)/len(recs):.0f}%)')
    print()
    print(f'    sum too LOW  (needs an ison promoted to an oligon): {len(low):4d}'
          f'   of which enough bars exist: {sum(1 for g in low if g["room_up"] >= -g["delta"]):d}')
    print(f'    sum too HIGH (needs an oligon demoted to an ison):  {len(high):4d}'
          f'   of which enough bars exist: {sum(1 for g in high if g["room_down"] >= g["delta"]):d}')
    print()
    dist = collections.Counter(g['delta'] for g in bad)
    print('  disagreement sizes:',
          ', '.join(f'{d:+d}: {n}' for d, n in sorted(dist.items(), key=lambda x: -x[1])[:8]))

    if a.worst:
        print(f'\n  worst {a.worst} gaps:')
        for g in sorted(bad, key=lambda g: -abs(g['delta']))[:a.worst]:
            print(f'    {g["delta"]:+3d}  {g["units"]:3d} units  '
                  f'p{g["p0"]} l{g["l0"]}  {g["hymn"]}')

    # CHECK-01 gate: fewer than 8 of 57 violated.
    return 0 if len(bad) < 8 else 2


if __name__ == '__main__':
    sys.exit(main())
