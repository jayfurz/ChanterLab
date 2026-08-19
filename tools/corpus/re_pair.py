#!/usr/bin/env python3
"""Correct anchor pairing: a parallagi dataset anchors a hymn only if the
hymn's own units ALIGN with the parallagi's degree sequence (DTW single-step
agreement >= threshold), not because it sat nearby on the tape. Size gate
first (unit/note ratio 0.65-1.7), then verify by alignment.

Usage: re_pair.py <workdir> <pieces_dir_substring> [--min 0.7]
"""
import glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h, dtw, iv_of

def pair_agreement(units, deg, iv):
    got = dtw(units, deg, iv)
    if not got:
        return 0.0, 0
    path = got[0]
    ok = n = 0
    for (j2, k2), (j, k) in zip(path, path[1:]):
        e = sum(iv_of(iv, units[x]) for x in range(j2 + 1, j + 1))
        n += 1
        ok += (deg[k] - deg[k2] == e)
    return (ok / n if n else 0.0), n

def main():
    wd = sys.argv[1]
    sub = sys.argv[2]
    mn = float(sys.argv[sys.argv.index('--min') + 1]) if '--min' in sys.argv else 0.7
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    hymns = json.load(open(os.path.join(wd, 'hymns.json')))
    # candidate datasets: any parallagi dir whose 16k wav traces to a piece
    # wav in a pieces dir matching `sub`
    cands = []
    for d in glob.glob('/mnt/data/chant-corpus/parallagi/*/'):
        ef = os.path.join(d, 'events_full.jsonl')
        if not os.path.exists(ef):
            continue
        src = None
        sj = os.path.join(d, 'summary.json')
        if os.path.exists(sj):
            src = json.load(open(sj)).get('audio') or json.load(open(sj)).get('wav')
        if src is None or sub not in src:
            # fall back: match by outdir name containing the mode tag
            if sub not in d:
                continue
        rows = [json.loads(l) for l in open(ef)]
        deg = [r['degree_abs'] for r in rows]
        if len(deg) >= 15:
            cands.append((d, deg))
    print(f'{len(cands)} candidate datasets for {sub}')
    wired = 0
    for h in hymns:
        if h.get('parallagi_dir'):
            continue
        units, _ = load_units_h(h)
        best = (0.0, None)
        for d, deg in cands:
            r = len(units) / max(len(deg), 1)
            if not (0.65 <= r <= 1.7):
                continue
            agr, n = pair_agreement(units, deg, iv)
            if n >= 15 and agr > best[0]:
                best = (agr, d)
        if best[0] >= mn:
            h['parallagi_dir'] = best[1]
            wired += 1
            print(f"  {h['name']:26s} <- {os.path.basename(os.path.normpath(best[1]))} "
                  f"(pair-agreement {best[0]:.2f})")
    json.dump(hymns, open(os.path.join(wd, 'hymns.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'{wired} verified anchors wired in {wd}')

if __name__ == '__main__':
    main()
