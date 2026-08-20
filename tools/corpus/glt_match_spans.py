#!/usr/bin/env python3
"""glt_match_spans.py — match the chanter's own cut SPANS to the canonical text.

glt_match.py matches hymns.json rows, whose boundaries are the machine's guess
and are known to be wrong (4/25 right at IoU>=0.90 on the gold tape). The 47
grave-orthros spans are the chanter's own cuts, score range included, and the
melos/parallagi halves are paired — "match the s# ones only. we should have the
correct parallagi as well as now the melos".

That matters for forced alignment specifically: FA is only as good as the text
it is given, and a span with a bad text match cannot be evidence about FA at
all. So this reports coverage per span, and marks which halves are worth
aligning: a MELOS sings the hymn text, a PARALLAGI sings degree names and has no
business being aligned against a hymn.

Usage:  glt_match_spans.py --workdir grave-orthros
"""
import argparse
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glt_match import collapse, norm, sim, WD_MODE, services_for
from score_degrees import units_for
from hymn_align import load_units

TEXTS = '/mnt/data/chant-corpus/texts'
GLT_JSON = f'{TEXTS}/glt_oktoechos.json'


def span_text(sc):
    """the span's own lyric stream, collapsed-normalised, from ITS score range"""
    words = []
    for p in range(sc['p0'], sc['p1'] + 1):
        try:
            us, lyr = load_units(p, 0, p, 10 ** 6)
        except Exception:
            continue
        keep = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
        keep = [u for u in keep if u['pl'][0] == p]
        if not keep:
            continue
        lo, hi = min(u['x0'] for u in keep), max(u['x1'] for u in keep)
        l0, l1 = min(u['pl'][1] for u in keep), max(u['pl'][1] for u in keep)
        for w in lyr:
            ln = w.get('line', 0)
            if ln < l0 or ln > l1:
                continue
            if ln == l0 and w['x1'] < lo - 2:
                continue
            if ln == l1 and w['x0'] > hi + 2:
                continue
            words.append((p, ln, w['x0'], w['text']))
    words.sort()
    return collapse(norm(''.join(w[3] for w in words)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--out', default=f'{TEXTS}/glt_span_match.json')
    a = ap.parse_args()

    glt = json.load(open(GLT_JSON))
    mode = WD_MODE.get(a.workdir)
    svc = services_for(a.workdir)
    cands = [g for g in glt
             if g['mode'] == 'ordinary' or (g['mode'] == mode and g.get('service') in svc)]
    if not cands:
        cands = glt
    sc = {c['hymn']: c for c in json.load(open(f'{TEXTS}/scorecuts_{a.workdir}.json'))['cuts']}
    names = {s['span']: s for s in
             json.load(open(f'{TEXTS}/span_names_{a.workdir}.json'))['spans']}
    rows = []
    for span in sorted(sc, key=lambda s: names.get(s, {}).get('ordinal', 0)):
        t = span_text(sc[span])
        if not t:
            continue
        best = max(cands, key=lambda g: sim(t, collapse(norm(g['text']))))
        cov = sim(t, collapse(norm(best['text'])))
        nm = names.get(span, {})
        rows.append({'span': span, 'ordinal': nm.get('ordinal'), 'lane': nm.get('lane'),
                     'incipit': nm.get('incipit'), 'score_chars': len(t),
                     'coverage': round(cov, 3), 'glt_heading': best.get('heading'),
                     'glt_text': best['text']})
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=1)
    mel = [r for r in rows if r['lane'] == 'melos']
    print(f'{len(rows)} spans matched -> {a.out}')
    import statistics as st
    for lane in ('melos', 'parallagi'):
        g = [r for r in rows if r['lane'] == lane]
        if g:
            print('  %-10s %2d spans, coverage median %.3f, >=0.55: %d'
                  % (lane, len(g), st.median([r['coverage'] for r in g]),
                     sum(1 for r in g if r['coverage'] >= 0.55)))
    print('\n  the melos halves, which are the ones FA can use:')
    for r in sorted(mel, key=lambda r: -r['coverage'])[:8]:
        print('     s%02d cov %.3f  %s' % (r['ordinal'], r['coverage'], (r['incipit'] or '')[:44]))


if __name__ == '__main__':
    main()
