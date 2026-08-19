#!/usr/bin/env python3
"""dropcap_ranges.py — draft score ranges from drop caps.

Measured on the chanter's gold tape: every score range starts on a drop cap,
26 of 26. That is a hard constraint, not a prior, and it has not been used.

If a hymn's score range starts at a drop cap and runs to just before the next
one, then the drop caps alone partition the book into candidate ranges. The
chanter would then verify a draft rather than mark every boundary by hand,
which is the only lever available for the fifteen tapes still outstanding.

This validates the idea against the gold tape first: do drop-cap-delimited
ranges reproduce the ranges he actually marked?

Usage:
  dropcap_ranges.py --validate --workdir grave-orthros
  dropcap_ranges.py --pages 519 557 --draft
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units

SCORES = '/mnt/data/chant-corpus/scores'
TEXTS = '/mnt/data/chant-corpus/texts'


def caps_in(p0, p1, min_size=18.0):
    caps = [c for c in json.load(open(f'{SCORES}/dropcaps.json'))
            if p0 <= c['page'] <= p1 and c.get('size', 0) >= min_size]
    return sorted(caps, key=lambda c: (c['page'], c['line'], c['x0']))


def unit_at(page, line, x0, cache):
    """The unit index on a page nearest a drop cap's position."""
    if page not in cache:
        try:
            cache[page] = load_units(page, 0, page, 10 ** 6)[0]
        except Exception:
            cache[page] = []
    us = cache[page]
    best, bi = None, 0
    for i, u in enumerate(us):
        if u['pl'][1] != line:
            continue
        d = abs(u['x0'] - x0)
        if best is None or d < best:
            best, bi = d, i
    return bi if best is not None else None


def ranges_from_caps(p0, p1, min_size=18.0):
    caps = caps_in(p0, p1, min_size)
    cache = {}
    out = []
    for i, c in enumerate(caps):
        g0 = unit_at(c['page'], c['line'], c['x0'], cache)
        if g0 is None:
            continue
        if i + 1 < len(caps):
            n = caps[i + 1]
            g1 = unit_at(n['page'], n['line'], n['x0'], cache)
            end = (n['page'], n['line'], (g1 - 1) if g1 else 0)
        else:
            us = cache.get(p1) or load_units(p1, 0, p1, 10 ** 6)[0]
            end = (p1, us[-1]['pl'][1] if us else 0, max(len(us) - 1, 0))
        out.append({'p0': c['page'], 'l0': c['line'], 'g0': g0,
                    'p1': end[0], 'l1': end[1], 'g1': end[2],
                    'letter': c.get('letter', '')})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--draft', action='store_true')
    ap.add_argument('--pages', nargs=2, type=int)
    ap.add_argument('--min-size', type=float, default=18.0)
    a = ap.parse_args()

    if a.validate:
        sc = json.load(open(f'{TEXTS}/scorecuts_{a.workdir}.json'))['cuts']
        seen, gold = set(), []
        for c in sc:
            k = (c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
            if k not in seen:
                seen.add(k)
                gold.append(c)
        gold.sort(key=lambda c: (c['p0'], c['l0'], c['g0']))
        p0 = min(c['p0'] for c in gold)
        p1 = max(c['p1'] for c in gold)
        draft = ranges_from_caps(p0, p1, a.min_size)
        print(f'gold distinct ranges: {len(gold)}   drop-cap ranges over '
              f'p{p0}-{p1}: {len(draft)}\n')

        # how many gold STARTS does a drafted range start match exactly?
        dstart = {(d['p0'], d['l0'], d['g0']) for d in draft}
        hit = sum(1 for g in gold if (g['p0'], g['l0'], g['g0']) in dstart)
        near = sum(1 for g in gold
                   if any(d['p0'] == g['p0'] and d['l0'] == g['l0']
                          and abs(d['g0'] - g['g0']) <= 2 for d in draft))
        print(f'  gold starts matched exactly by a drop-cap start: {hit}/{len(gold)}')
        print(f'  matched within 2 units:                          {near}/{len(gold)}')
        # and the converse: how many drafted ranges are spurious?
        gstart = {(g['p0'], g['l0'], g['g0']) for g in gold}
        extra = sum(1 for d in draft if (d['p0'], d['l0'], d['g0']) not in gstart)
        print(f'  drop-cap starts with no gold range:              {extra}/{len(draft)}')
        print('\n  (a drop cap per hymn would give equal counts; more drop caps '
              'than hymns means some open verses or sections inside a hymn)')
        return

    if a.draft:
        if not a.pages:
            raise SystemExit('--draft needs --pages P0 P1')
        d = ranges_from_caps(a.pages[0], a.pages[1], a.min_size)
        for r in d:
            print('  %s  p%d·%d·%-3d -> p%d·%d·%-3d'
                  % (r['letter'], r['p0'], r['l0'], r['g0'],
                     r['p1'], r['l1'], r['g1']))
        print(f'{len(d)} candidate ranges')


if __name__ == '__main__':
    main()
