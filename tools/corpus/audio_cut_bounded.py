#!/usr/bin/env python3
"""audio_cut_bounded.py — extend a clipped end, bounded by the NEXT recorded piece.

Every previous end-finder failed for the same reason: it had no principled right
edge.
  * "walk until silence" ran into following hymns (+480 s) because the tape is
    near-continuous;
  * a fixed look-ahead made forced alignment smear the final melisma to exactly
    the window edge (+18.45 s);
  * pinning with the next HYMN's start only works when two melos tracks are
    adjacent, which they seldom are;
  * the parallagi-length rule is real (chanter: "paralagi then melos right after
    of the same hymn and length") but unusable, because the parallagi FILES are
    not one per hymn — one 179 s parallagi covers two melos, so the measured
    ratio is 1.55 with a 21.65 s median gap.

pair_by_tape.py locates every piece in the tape, of any kind. That supplies the
missing edge: a hymn's audio cannot run past the start of the next recorded
piece, whatever it is. Search for the decay only inside that interval, and the
bound is real rather than a guessed constant.

Usage:  audio_cut_bounded.py --workdir DIR [--apply]
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_recut import envelope, find_tape, HOP


def main():
    import numpy as np
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--tail', type=float, default=0.5)
    ap.add_argument('--floor', type=float, default=0.18)
    ap.add_argument('--min-gap', type=float, default=0.25)
    ap.add_argument('--margin', type=float, default=0.35,
                    help='stop this far short of the next piece')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    pf = f'/mnt/data/chant-corpus/texts/pairs_{name}.json'
    rf = f'/mnt/data/chant-corpus/texts/recut_{name}.json'
    for f in (pf, rf):
        if not os.path.exists(f):
            raise SystemExit(f'missing {f} — run pair_by_tape.py and audio_recut.py')
    loc = {r['hymn']: r for r in json.load(open(rf))}

    # every located piece on this tape, so the next one can bound the search
    starts = {}
    for r in json.load(open(pf)):
        starts.setdefault(r['workdir'], [])
    allp = json.load(open(pf))
    tape_pieces = sorted({(round(x['gap_s'] or 0, 3), x['melos']) for x in allp})
    # rebuild absolute positions from pairs_*.json (melos t0 == t1 - dur)
    pos = []
    for x in allp:
        pos.append((x['melos'], x['melos_dur']))
    # locate afresh: cheap, and keeps this tool independent of field drift
    tapes, ends = {}, {}
    out = []
    print('%-22s %8s %8s %8s %8s' % ('hymn', 'cur_end', 'bound', 'new_end', 'delta'))
    for h in json.load(open(os.path.join(a.workdir, 'hymns.json'))):
        r = loc.get(h['name'])
        if not r:
            continue
        tp = r['tape']
        key = os.path.basename(tp)
        if key not in tapes:
            tapes[key] = envelope(tp, key)
        env = tapes[key]
        cs, ce = r['cur']
        # the next recorded piece on this tape, from every located melos start
        nxt = min([o['cur'][0] for o in loc.values()
                   if o['tape'] == tp and o['cur'][0] > ce + 0.5] or [None]) \
            if any(o['tape'] == tp and o['cur'][0] > ce + 0.5 for o in loc.values()) else None
        bound = (nxt - a.margin) if nxt else (ce + 12.0)
        i0, i1 = int(ce / HOP), int(min(bound, len(env) * HOP) / HOP)
        if i1 <= i0:
            continue
        seg = env[max(0, i0 - 40):i1]
        if seg.size < 3:
            continue
        fl = float(np.percentile(env, 20))
        lo = float(np.percentile(env, 90))
        thr = fl + a.floor * max(lo - fl, 1e-9)
        gap = max(1, int(a.min_gap / HOP))
        j = i0
        while j < i1 - gap:
            if (env[j:j + gap] <= thr).all():
                break
            j += 1
        else:
            j = i1                      # sings right up to the next piece
        ne = min(bound, j * HOP + a.tail)
        out.append({'workdir': name, 'hymn': h['name'], 'tape': tp,
                    'piece': r['piece'], 'cur': [cs, ce],
                    'new': [cs, round(ne, 3)], 'bound': round(bound, 2),
                    'd_end': round(ne - ce, 2)})
        print('%-22s %8.1f %8.1f %8.1f %+8.2f'
              % (h['name'][:22], ce, bound, ne, ne - ce), flush=True)
    jf = f'/mnt/data/chant-corpus/texts/cutbound_{name}.json'
    json.dump(out, open(jf, 'w'), indent=1)
    if out:
        d = sorted(r['d_end'] for r in out)
        print(f'\n{len(out)} ends bounded; median extension {d[len(d)//2]:+.2f} s')
    if a.apply:
        for r in out:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(r['new'][0]), '-to', str(r['new'][1]),
                            '-ac', '1', '-ar', '44100',
                            r['piece'].replace('.wav', '.recut.wav')], check=True)
        print(f'wrote {len(out)} re-cut files')
    print('->', jf)


if __name__ == '__main__':
    main()
