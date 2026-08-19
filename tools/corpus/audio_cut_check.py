#!/usr/bin/env python3
"""audio_cut_check.py — how cleanly is each hymn's audio cut?

Chanter: the tracks "seem to cut off too early and the hymns end up having a
long silence in the beginning and the last note gets cut off too early", and
"some modes are already precut, like plagal 1". Both are measurable without
touching the score, from the rms_track.npy every melos dir already carries
(10 ms hop, written by segment_tracks.py).

Reports per hymn:
  lead_s    silence before the first sung note      (should be small)
  tail_s    silence after the last sung note        (should be small but > 0;
                                                     0.00 means the last note is
                                                     clipped, which is the exact
                                                     failure the chanter names)
  voiced_s  sung span between them
  clipped   the track ends while still above the floor -> a cut note

Usage:  audio_cut_check.py [--workdir DIR] [--floor 0.06]
"""
import argparse
import glob
import json
import os

import numpy as np

HOP = 0.01


def analyse(rms_path, floor):
    r = np.load(rms_path)
    if r.size < 10:
        return None
    r = np.nan_to_num(r.astype(float))
    thr = max(float(np.percentile(r, 95)) * floor, 1e-9)
    on = r > thr
    if not on.any():
        return None
    first, last = int(np.argmax(on)), int(len(on) - 1 - np.argmax(on[::-1]))
    tail_frames = len(on) - 1 - last
    # is the very end still sounding? then the last note was cut
    clipped = bool(on[-3:].any())
    return {'dur_s': round(len(r) * HOP, 2),
            'lead_s': round(first * HOP, 2),
            'tail_s': round(tail_frames * HOP, 2),
            'voiced_s': round((last - first) * HOP, 2),
            'clipped': clipped}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--floor', type=float, default=0.06,
                    help='fraction of the 95th-percentile RMS counted as sound')
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/audio_cut_check.json')
    a = ap.parse_args()
    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    rows = []
    print('%-18s %-22s %7s %7s %7s %7s %s'
          % ('workdir', 'hymn', 'dur', 'lead', 'tail', 'voiced', 'clipped'))
    for wd in wds:
        hy = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hy):
            continue
        name = os.path.basename(wd.rstrip('/'))
        for h in json.load(open(hy)):
            rp = os.path.join(wd, 'melos_' + h['name'], 'rms_track.npy')
            if not os.path.exists(rp):
                continue
            r = analyse(rp, a.floor)
            if not r:
                continue
            r.update({'workdir': name, 'hymn': h['name']})
            rows.append(r)
    json.dump(rows, open(a.out, 'w'), indent=1)
    by = {}
    for r in rows:
        by.setdefault(r['workdir'], []).append(r)
    print()
    print('%-18s %4s %8s %8s %8s %s' % ('workdir', 'n', 'med lead', 'med tail',
                                        'clipped', 'worst lead'))
    for k in sorted(by):
        v = by[k]
        ld = sorted(x['lead_s'] for x in v)
        tl = sorted(x['tail_s'] for x in v)
        cl = sum(x['clipped'] for x in v)
        print('%-18s %4d %8.2f %8.2f %6d/%-3d %.2f'
              % (k, len(v), ld[len(ld) // 2], tl[len(tl) // 2], cl, len(v), ld[-1]))
    print(f'\n{len(rows)} tracks -> {a.out}')


if __name__ == '__main__':
    main()
