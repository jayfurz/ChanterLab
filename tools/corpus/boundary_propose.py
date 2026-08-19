#!/usr/bin/env python3
"""boundary_propose.py — re-cut hymn slices at drop caps, scored by canonical text.

Chanter, 2026-08-18, on why so many hymns fail to match their GLT text:

  "i dont think the sheet music ever had a pass at starting and ending in the
   right places ... a common trope i see is the sheet music starts maybe an
   entire line too early, giving the last line of the hymn before it, and
   sometimes it doesnt end at the end but goes on to the next few lines of the
   next hymn ... the drop cap is the dead giveaway"

The audio was re-cut in an earlier session; the SCORE side never was. So the
score slice and the recording disagree, and no amount of matcher tuning fixes a
slice that contains the wrong lines.

Method, using only signals the chanter named: a hymn starts AT a drop cap and
runs until just before the next one. For each hymn try every drop cap near its
current start, take the slice that runs to the following drop cap, and score the
resulting lyric stream against the canonical GLT text for that mode and service.
Keep the best. Starts are forced to be monotonically increasing, because the
book and the liturgy are both in order.

Reports proposed vs current and the change in text similarity; writes proposals
rather than editing hymns.json, because a boundary change re-indexes pins.

Usage:  boundary_propose.py [--workdir DIR] [--window 6]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h
from glt_fetch import OUT as GLT_JSON
from glt_match import score_text, sim, WD_MODE, services_for

DROPCAPS = '/mnt/data/chant-corpus/scores/dropcaps.json'


def caps_ordered():
    d = json.load(open(DROPCAPS))
    return sorted({(x['page'], x['line']) for x in d})


def best_sim(h, cands):
    try:
        s = score_text(h)
    except Exception:
        return 0.0, None, ''
    if len(s) < 12:
        return 0.0, None, s
    b = max(cands, key=lambda g: sim(s, g['collapsed']))
    return sim(s, b['collapsed']), b, s


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--window', type=int, default=6)
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/boundary_proposals.json')
    a = ap.parse_args()

    glt = json.load(open(GLT_JSON))
    caps = caps_ordered()
    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    out = []
    for wd in wds:
        hy = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hy):
            continue
        name = os.path.basename(wd.rstrip('/'))
        mode, svc = WD_MODE.get(name), services_for(name)
        cands = [g for g in glt if (not mode or g['mode'] == mode)
                 and g['service'] in svc] or glt
        hl = sorted(json.load(open(hy)), key=lambda h: (h['p0'], h['l0']))
        print(f'\n=== {name}')
        floor = None                    # monotonic starts
        for h in hl:
            cur, _, _ = best_sim(h, cands)
            near = [c for c in caps
                    if abs((c[0] - h['p0']) * 100 + (c[1] - h['l0'])) <= a.window
                    and (floor is None or c > floor)]
            best = (cur, (h['p0'], h['l0'], h['p1'], h['l1']), None)
            for (cp, cl) in near:
                nxt = next((c for c in caps if c > (cp, cl)), None)
                if not nxt:
                    continue
                ep, el = nxt
                if (ep, el) <= (cp, cl):
                    continue
                cand = dict(h, p0=cp, l0=cl, p1=ep, l1=el)
                cand.pop('g0', None); cand.pop('g1', None)
                sc, _, _ = best_sim(cand, cands)
                if sc > best[0]:
                    best = (sc, (cp, cl, ep, el), (cp, cl))
            if best[2]:
                floor = best[2]
            p0, l0, p1, l1 = best[1]
            moved = (p0, l0, p1, l1) != (h['p0'], h['l0'], h['p1'], h['l1'])
            out.append({'workdir': name, 'hymn': h['name'],
                        'current': [h['p0'], h['l0'], h['p1'], h['l1']],
                        'proposed': [p0, l0, p1, l1],
                        'sim_current': round(cur, 3), 'sim_proposed': round(best[0], 3),
                        'moved': moved})
            flag = '->' if moved else '  '
            print(f'  {flag} {h["name"][:20]:20s} {h["p0"]}:{h["l0"]}-{h["p1"]}:{h["l1"]}'
                  f'  sim {cur:.2f}' + (f'   =>  {p0}:{l0}-{p1}:{l1}  sim {best[0]:.2f}'
                                        if moved else ''))
    json.dump(out, open(a.out, 'w'), indent=1)
    mv = [r for r in out if r['moved']]
    if out:
        b = sum(r['sim_current'] for r in out) / len(out)
        aft = sum(r['sim_proposed'] for r in out) / len(out)
        print(f'\n{len(mv)}/{len(out)} boundaries moved; mean text similarity '
              f'{b:.3f} -> {aft:.3f}')
    print(f'-> {a.out}')


if __name__ == '__main__':
    main()
