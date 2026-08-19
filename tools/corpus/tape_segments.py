#!/usr/bin/env python3
"""tape_segments.py — RESEP-01 step 1: cut the tape at real silence.

Every failed end-finder in this pipeline lacked a hard right edge. Silence
supplies one: a sung span bounded by silence on both sides has edges that are
facts about the recording, not estimates. The chanter said the same thing when
the pieces were first cut — "every piece transition has a REAL PAUSE — cut at
RMS-quiet runs, never whisper word gaps".

This produces the segment inventory that the text assignment (step 2) then maps
hymns onto, one hymn per segment or per run of consecutive segments. Because the
segments tile the tape, a hymn's end is bounded by the next segment's start by
construction — the property audio_cut_final.py could not obtain from the next
located melos, since a parallagi sits in between.

Usage:  tape_segments.py [--tape PATH] [--min-sil 0.45] [--min-seg 4.0]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_recut import envelope, HOP

OUT = '/mnt/data/chant-corpus/texts/tape_segments.json'


def segments(env, min_sil, min_seg, floor):
    import numpy as np
    fl = float(np.percentile(env, 20))
    lo = float(np.percentile(env, 90))
    thr = fl + floor * max(lo - fl, 1e-9)
    on = env > thr
    runs, i, n = [], 0, on.size
    gap = max(1, int(min_sil / HOP))
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        quiet = 0
        while j < n:
            if on[j]:
                quiet = 0
            else:
                quiet += 1
                if quiet >= gap:
                    break
            j += 1
        end = j - quiet + 1
        if (end - i) * HOP >= min_seg:
            runs.append((i * HOP, end * HOP))
        i = max(j, i + 1)
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--tape')
    ap.add_argument('--min-sil', type=float, default=0.8)
    ap.add_argument('--min-seg', type=float, default=8.0)
    ap.add_argument('--floor', type=float, default=0.18)
    a = ap.parse_args()

    if a.tape:
        tapes = [a.tape]
    else:
        seen = set()
        tapes = []
        for f in sorted(glob.glob('/mnt/data/chant-corpus/texts/recut_*.json')):
            for r in json.load(open(f)):
                if r['tape'] not in seen:
                    seen.add(r['tape'])
                    tapes.append(r['tape'])
    out = {}
    for tp in tapes:
        env = envelope(tp, os.path.basename(tp))
        segs = segments(env, a.min_sil, a.min_seg, a.floor)
        out[tp] = [[round(s, 2), round(e, 2)] for s, e in segs]
        dur = env.size * HOP
        cov = sum(e - s for s, e in segs)
        print('%-52s %6.0f s  %4d segments  %.0f%% covered  median %5.1f s'
              % (os.path.basename(tp)[:52], dur, len(segs), 100 * cov / max(dur, 1),
                 sorted(e - s for s, e in segs)[len(segs) // 2] if segs else 0))
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\n{sum(len(v) for v in out.values())} segments over {len(out)} tapes -> {OUT}')


if __name__ == '__main__':
    main()
