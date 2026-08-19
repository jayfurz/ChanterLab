#!/usr/bin/env python3
"""heuristics_eval.py — score the chanter's boundary heuristics against gold.

He described how he finds boundaries by hand:

  audio start   silence, then an inhaling breath
  audio end     he holds the last note and slows into it, and the waveform fades
  score start   always a drop cap
  score end     a compound glyph, with a martyria to the right like an endcap
  structure     the parallagi is always followed by its melos

Every one of these is checkable against the finished Grave Orthros tape -- 47
audio spans and 47 score ranges, all cut by ear. This measures each separately,
because a rule that holds 47/47 can be a hard constraint and one that holds 30/47
can only be a prior, and treating the second like the first is how the earlier
automatic passes went wrong.

Usage:  heuristics_eval.py [--workdir grave-orthros]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units, DOTS, APLI_COMPOUND, KLASMA, MARTYRIA_DEG

TEXTS = '/mnt/data/chant-corpus/texts'
SCORES = '/mnt/data/chant-corpus/scores'
PPS = 20                       # peak buckets per second


def pct(n, d):
    return f'{n}/{d} ({100.0*n/d:.0f}%)' if d else 'n/a'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--sil-window', type=float, default=1.5,
                    help='seconds before a start / after an end to inspect')
    a = ap.parse_args()
    wd = a.workdir

    spans = sorted(json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts'],
                   key=lambda c: c['t0'])
    score = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    peaks = open(f'{TEXTS}/peaks/{wd}.u8', 'rb').read()
    caps = json.load(open(f'{SCORES}/dropcaps.json'))
    capset = {(c['page'], c['line']) for c in caps}
    capx = {}
    for c in caps:
        capx.setdefault((c['page'], c['line']), []).append(c['x0'])

    units = {}

    def page_units(p):
        if p not in units:
            try:
                units[p] = load_units(p, 0, p, 10 ** 6)[0]
            except Exception:
                units[p] = []
        return units[p]

    def env(t0, t1):
        i0, i1 = max(int(t0 * PPS), 0), min(int(t1 * PPS), len(peaks))
        seg = peaks[i0:i1]
        return (sum(seg) / len(seg), max(seg)) if seg else (0, 0)

    print(f'=== {wd}: {len(spans)} spans, {len(score)} score ranges\n')

    # ---- audio ---------------------------------------------------------
    quiet_before = quiet_after = fade = 0
    body_lv = []
    for s in spans:
        body_lv.append(env(s['t0'], s['t1'])[0])
    med_body = sorted(body_lv)[len(body_lv) // 2]
    for s in spans:
        pre = env(max(s['t0'] - a.sil_window, 0), s['t0'])[0]
        post = env(s['t1'], s['t1'] + a.sil_window)[0]
        body = env(s['t0'], s['t1'])[0]
        # "silence" relative to the hymn's own loudness, not an absolute floor
        quiet_before += pre < body * 0.5
        quiet_after += post < body * 0.5
        # the last second against the middle: he holds and fades
        tail = env(max(s['t1'] - 1.0, s['t0']), s['t1'])[0]
        mid = env(s['t0'] + (s['t1'] - s['t0']) * 0.4,
                  s['t0'] + (s['t1'] - s['t0']) * 0.6)[0]
        fade += tail < mid
    print('AUDIO')
    print(f'  silence before the start   {pct(quiet_before, len(spans))}')
    print(f'  silence after the end      {pct(quiet_after, len(spans))}')
    print(f'  fades into the last second {pct(fade, len(spans))}')

    # ---- score ---------------------------------------------------------
    cap_start = comp_end = mart_end = 0
    n = 0
    miss_cap, miss_comp, miss_mart = [], [], []
    # A parallagi and its melos usually share one score range, so counting per
    # SPAN double-counts every shared range. Score distinct ranges instead.
    seen_range = set()
    for s in spans:
        sc = score.get(s['hymn'])
        if not sc:
            continue
        rk = (sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
        if rk in seen_range:
            continue
        seen_range.add(rk)
        n += 1
        us = page_units(sc['p0'])
        u0 = us[sc['g0']] if sc['g0'] < len(us) else None
        ue_us = page_units(sc['p1'])
        u1 = ue_us[sc['g1']] if sc['g1'] < len(ue_us) else None

        # start: a drop cap on that line, at or before the first unit
        if u0 is not None:
            xs = capx.get((sc['p0'], sc['l0']), [])
            if any(x <= u0['x1'] + 6 for x in xs):
                cap_start += 1
            else:
                miss_cap.append((s['hymn'], sc['p0'], sc['l0']))
        # end: a compound carrying apli/dipli/triple or klasma
        if u1 is not None:
            if u1.get('apli') or u1.get('klasma') or u1.get('dots'):
                comp_end += 1
            else:
                miss_comp.append((s['hymn'], sc['p1'], sc['l1'], u1.get('base')))
            # endcap: a martyria at or after the final unit on its line
            later = [q for q in ue_us if q['pl'] == u1['pl']
                     and q['x0'] >= u1['x0'] - 2]
            if any(q.get('mart_deg') is not None for q in later) or \
               u1.get('mart_deg') is not None:
                mart_end += 1
            else:
                miss_mart.append((s['hymn'], sc['p1'], sc['l1']))
    print('\nSCORE')
    print(f'  starts on a drop cap       {pct(cap_start, n)}')
    print(f'  ends on a compound         {pct(comp_end, n)}')
    print(f'  martyria as an endcap      {pct(mart_end, n)}')
    print('    NB: MARTYRIA_DEG recognises only 6 clusters and 21% of red '
          'glyphs on these pages, so this number bounds the DETECTOR, not the '
          "chanter's rule.")
    for name, lst in (('no drop cap', miss_cap), ('plain end unit', miss_comp),
                      ('no martyria', miss_mart)):
        if lst:
            print(f'    {name}: ' + ', '.join(f'{h}' for h, *_ in lst[:8])
                  + (' …' if len(lst) > 8 else ''))

    # ---- structure -----------------------------------------------------
    ok = bad = 0
    for i, s in enumerate(spans):
        if s.get('lane') != 'melos':
            continue
        prev = spans[i - 1] if i else None
        if prev and prev.get('lane') == 'parallagi':
            ok += 1
        else:
            bad += 1
    print('\nSTRUCTURE')
    print(f'  melos preceded by its parallagi  {pct(ok, ok + bad)}')


if __name__ == '__main__':
    main()
