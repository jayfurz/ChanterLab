#!/usr/bin/env python3
"""propagate_identity.py -- a melos is whatever the parallagi before it was.

PARALLAGI-PAIRING.md: every melos on the tape is immediately preceded by its
own parallagi (23/23, 0 orphans). degree_match_clf.py identifies a parallagi
from its sung degrees (21/23). Put together, a melos needs no identification of
its own: it inherits the score range of the parallagi before it.

This script does that and SCORES it. The chanter gave every melos span its own
score range (scorecuts_<wd>.json), so the inherited range can be compared with
his by unit-set IoU. That is the end-to-end melos identification number, the
one the text route could only get to 20%.

Two honesty notes:
  * The parallagi identity comes from the classifier sequences that
    degree_match_clf.py --dump wrote, re-ranked here with the same DTW. Three
    of the 23 parallagi (s02/s04/s06) trained the classifier; their melos are
    marked.
  * A pair's two halves can carry different ranges by design (the doxology
    melos stops where the tape ran out; an anavathmoi parallagi covers several
    melos). IoU < 1 on those is not an error, which is why the gold pair IoU is
    printed beside the predicted one.

Usage:
  propagate_identity.py --seqs <clf_seqs.json> [--out identity.json]
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from degree_match import dtw_cost          # noqa: E402
from score_degrees import units_for        # noqa: E402

TEXTS = '/mnt/data/chant-corpus/texts'
TRAINED_ON = {'t01_#3', 't01_#5', 't01_#7'}


def unit_keys(sc):
    u = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
    return {(x['pl'], x['x0'], x['y0']) for x in u}


def iou(a, b):
    return len(a & b) / max(len(a | b), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--seqs', required=True, help='degree_match_clf.py --dump output')
    ap.add_argument('--out')
    a = ap.parse_args()
    wd = a.workdir

    cuts = sorted(json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts'], key=lambda c: c['t0'])
    score = {c['hymn']: c for c in json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    seqs = json.load(open(a.seqs))
    mod = lambda s: [v % 7 for v in s]

    # 1. identify every parallagi from its classifier sequence
    ident = {}
    names = list(seqs)
    for h in names:
        sc = sorted((dtw_cost(mod(seqs[h]['heard']), mod(seqs[g]['notated'])), g) for g in names)
        ident[h] = {'best': sc[0][1], 'margin': round(sc[1][0] - sc[0][0], 4),
                    'rank_of_truth': [g for _, g in sc].index(h) + 1}

    # 2. each melos inherits the range of the parallagi immediately before it
    keys = {h: unit_keys(score[h]) for h in score}
    rows, prev = [], None
    for c in cuts:
        lane = c.get('lane')
        if lane == 'parallagi':
            prev = c
            continue
        if lane != 'melos':
            prev = None
            continue
        h = c['hymn']
        if prev is None or prev['hymn'] not in ident:
            rows.append({'melos': h, 'parallagi': None})
            prev = None
            continue
        p = prev['hymn']
        got = ident[p]['best']
        rows.append({'melos': h, 'parallagi': p, 'identified_as': got,
                     'parallagi_correct': got == p,
                     'inherited_range': {k: score[got][k] for k in ('p0', 'l0', 'g0', 'p1', 'l1', 'g1')},
                     'iou_vs_gold': round(iou(keys[got], keys[h]), 3),
                     'iou_gold_pair': round(iou(keys[p], keys[h]), 3),
                     'margin': ident[p]['margin'],
                     'trained_on_parallagi': p in TRAINED_ON})
        prev = None

    print('  %-9s %-9s %-10s  %-5s  %6s  %6s   %s' % (
        'melos', 'from', 'identified', 'ok', 'IoU', 'gold', 'margin'))
    for r in rows:
        if r['parallagi'] is None:
            print('  %-9s (no parallagi before it)' % r['melos']); continue
        print('  %-9s %-9s %-10s  %-5s  %6.3f  %6.3f   %.3f%s' % (
            r['melos'], r['parallagi'], r['identified_as'],
            'OK' if r['parallagi_correct'] else 'WRONG', r['iou_vs_gold'],
            r['iou_gold_pair'], r['margin'], '  (train)' if r['trained_on_parallagi'] else ''))

    paired = [r for r in rows if r.get('parallagi')]
    held = [r for r in paired if not r['trained_on_parallagi']]
    for lab, sub in (('all', paired), ('held out', held)):
        ok = sum(r['parallagi_correct'] for r in sub)
        # the inherited range is "right" when it matches the chanter's melos
        # range as well as his own parallagi range does
        match = sum(r['iou_vs_gold'] >= r['iou_gold_pair'] - 1e-9 for r in sub)
        hi = sum(r['iou_vs_gold'] >= 0.9 for r in sub)
        print('  %-9s %d/%d melos inherit the right parallagi; %d/%d inherit a range '
              'as good as the chanter pair; %d/%d IoU >= 0.9 vs his melos range'
              % (lab, ok, len(sub), match, len(sub), hi, len(sub)))
    print('  text route on this tape: 20% end to end (RESEP-IDENTIFICATION.md)')

    if a.out:
        json.dump({'workdir': wd, 'parallagi': ident, 'melos': rows},
                  open(a.out, 'w'), indent=1, ensure_ascii=False)
        print('->', a.out)


if __name__ == '__main__':
    main()
