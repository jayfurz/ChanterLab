#!/usr/bin/env python3
"""martyria_check.py — score the legend against the printed martyrias.

A cadence martyria is a claim about which degree is being sung at that note.
Between two consecutive cadence martyrias the intervals the legend assigns must
sum to the difference in degree. That is a free, label-less check on the whole
interval model: 3,886 checkpoints corpus-wide, no chanter time spent.

This is the CHECK-01 gate in docs/plans/NEURAL-CHANT.md.  Measured 2026-08-20
over the 47 chanter-ranged spans, before and after the two legend_canon rule
fixes of the same day (the kentima composing one step too high, and the
qualitative base never being promoted):

    before   57 gaps + 1 underivable   17 satisfied   40 VIOLATED  (70%)
             -1: 14, -2: 13, +1: 5, -7: 2, -9: 1, +4: 1, +5: 1, -5: 1
             33 "sum too LOW"   7 "sum too HIGH"

    after    58 gaps                   32 satisfied   26 VIOLATED  (45%)
             -1: 10, +1: 7, -2: 2, +2: 2, -9: 1, +4: 1, +5: 1, -4: 1
             15 "sum too LOW"  11 "sum too HIGH"

The gap count moves from 57 to 58 because the qualitative-base rule gives an
interval to a key that had none, so a gap that used to be skipped is now scored.

(The 47 chanter ranges overlap at their edges; before deduping the same gap was
counted up to twice, giving 103/71. The ratio was unchanged, the counts were
not.)

The asymmetry was the evidence. Turning an oligon into an ison can only LOWER a
sum, so the ison/oligon ambiguity could not explain the 33 low gaps -- those
were a systematic rule gap on the "not climbing enough" side. --contingency
names the suspect: it sweeps every unit key against every correction in
-2..+2 and reports which single change satisfies the most gaps. On the old
legend it put 7|16ab+6ab +1 at 25/57, eight above the 17-gap baseline and four
clear of the next DISTINCT key (the same key's +2 entry sits between them at
24/57; 6|8ab is next at 21/57), and that figure is where the dropped kentima
was. The sweep only NAMED the suspect. What settles it is the chanter's own
uncompiled ruling on gold t03 gi=63, which is that very key: "Oligon with
kentima on top like this is +3." See legend_canon.py.
Fifth in the same list was 6|16ab -1, which is the other rule fix.

After the fix the residue is no longer one-sided: 15 low against 11 high, where
it was 33 against 7. (10 and 7 are the -1 and +1 histogram bins, not the low and
high counts -- an earlier revision of this line confused the two.) And 23
of the 26 remaining violations are within the ison/oligon ambiguity budget the
"enough bars exist" line counts. This does NOT clear the gate (violated < 8),
and the honest reading is that what is left is per-instance ambiguity plus a
handful of endpoint problems, not another rule. The three that are not covered
by ambiguity room are the p521 l2 -9, the p545 l2 +5 and the p525 l3 +4; the
+5 is an endpoint artefact rather than a legend error, since that gap closes on
a martyria stack carrying two degrees, [2, 6], and this script takes the first.
Taking the 6 would make it +1.

Usage:
  martyria_check.py                 # the 47 chanter-ranged spans (the gate)
  martyria_check.py --worst 20      # list the worst-disagreeing gaps
  martyria_check.py --contingency   # single-key correction sweep
  martyria_check.py --json OUT      # write the full per-gap record
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
            'deg_a': deg_a, 'deg_b': deg_b,
            'mart_end': list(seg[-1]['mart_cad']),
            'keys': collections.Counter(u['key'] for u in seg
                                        if u.get('iv') is None),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--worst', type=int, default=0,
                    help='list the N worst-disagreeing gaps')
    ap.add_argument('--contingency', action='store_true',
                    help='sweep every unit key against every correction in '
                         '-2..+2 and report which single change satisfies the '
                         'most gaps')
    ap.add_argument('--json', help='write the full per-gap record here')
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

    n_multi = sum(1 for g in recs if len(g['mart_end']) > 1)
    if n_multi:
        print(f'\n  {n_multi} gap(s) close on a martyria stack naming more than '
              f'one degree; the first is taken')

    if a.contingency:
        # delta = sum(iv) - (deg_b - deg_a), so raising key k's interval by v
        # raises the gap's delta by v for each occurrence of k in it. A single
        # wrong key shows up as one (k, v) that zeroes far more gaps than the
        # count already satisfied. This is a diagnostic, not a fitter: a move it
        # names still has to be justified from the atlas before it is made.
        allk = sorted(set().union(*(set(g['keys']) for g in recs)))
        sweep = []
        for k in allk:
            for v in (-2, -1, 1, 2):
                sweep.append((sum(1 for g in recs
                                  if g['delta'] + g['keys'][k] * v == 0), k, v))
        print(f'\n  single-key correction sweep ({len(allk)} keys), '
              f'baseline {len(ok)}/{len(recs)}:')
        for n, k, v in sorted(sweep, reverse=True)[:10]:
            print(f'    {k:24s} {v:+d}  ->  {n:2d}/{len(recs)} satisfied')

    if a.json:
        json.dump({'gaps': len(recs), 'satisfied': len(ok), 'violated': len(bad),
                   'legend': LEGEND, 'records': [
                       {kk: vv for kk, vv in g.items() if kk != 'keys'}
                       for g in sorted(recs, key=lambda g: (g['p0'], g['l0']))]},
                  open(a.json, 'w'), indent=1)
        print(f'\n  -> {a.json}')

    if a.worst:
        print(f'\n  worst {a.worst} gaps:')
        for g in sorted(bad, key=lambda g: -abs(g['delta']))[:a.worst]:
            print(f'    {g["delta"]:+3d}  {g["units"]:3d} units  '
                  f'p{g["p0"]} l{g["l0"]}  {g["hymn"]}')

    # CHECK-01 gate: fewer than 8 violated. 26 as of 2026-08-20.
    return 0 if len(bad) < 8 else 2


if __name__ == '__main__':
    sys.exit(main())
