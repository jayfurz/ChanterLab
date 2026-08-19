#!/usr/bin/env python3
"""degree_match.py — identify a parallagi span by its pitch contour vs the score.

Stage 3 gate from DEGREE-CLASSIFIER.md. The end-to-end number to beat is 2/23:
score-derived degree streams force-aligned against ASR output picked the right
span 2 times in 23, at chance, because the ASR collapses seven degree classes
into three.

Stage 1 showed pitch recovers the degrees far better (histogram cosine 0.73
against the ASR's 0.47, residual 20 cents to a notated degree). This asks the
question that matters: with pitch in place of the ASR, does a span's own score
now identify it?

Both sides are degree sequences, so they are compared by DTW rather than CTC --
no acoustic model is involved at match time at all. Sung parallagi holds each
degree for many frames while the score lists each note once, so the audio side
is run-length collapsed first; DTW then absorbs the remaining rate difference.

Usage:  degree_match.py --workdir grave-orthros
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from degree_pitch import (GENERA, SR, degrees_cents, estimate_base, f0_track)
from score_degrees import degree_stream, units_for

TEXTS = '/mnt/data/chant-corpus/texts'


def collapse(seq, min_run=3):
    """Run-length collapse: a held degree becomes one symbol."""
    out, i = [], 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        if j - i >= min_run:
            out.append(int(seq[i]))
        i = j
    return out


def dtw_cost(a, b):
    """Normalised DTW distance between two degree sequences (circular, mod 7)."""
    if not a or not b:
        return 1e9
    n, m = len(a), len(b)
    A = np.array(a)[:, None]
    B = np.array(b)[None, :]
    d = np.abs(A - B) % 7
    d = np.minimum(d, 7 - d).astype(float)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        row, prev = D[i], D[i - 1]
        dd = d[i - 1]
        for j in range(1, m + 1):
            row[j] = dd[j - 1] + min(prev[j], row[j - 1], prev[j - 1])
    # normalise by the shorter sequence: dividing by n+m rewards a candidate
    # merely for being long, which let one span win nearly every comparison
    return D[n, m] / min(n, m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--genus', default='diatonic', choices=list(GENERA))
    ap.add_argument('--limit-sec', type=float, default=60.0)
    ap.add_argument('--identity-check', action='store_true',
                    help='substitute each score sequence for its own audio. If '
                         'this does not score 100%%, the MATCHER is broken '
                         'independently of the recogniser and no model helps.')
    a = ap.parse_args()

    wd = a.workdir
    legend = json.load(open(f'/mnt/data/chant-corpus/workdirs/{wd}/legend_global.json'))
    cuts = json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts']
    score = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    tape = json.load(open(f'{TEXTS}/recut_{wd}.json'))[0]['tape']
    dc = degrees_cents(a.genus)

    spans = [c for c in sorted(cuts, key=lambda c: c['t0'])
             if c.get('lane') == 'parallagi' and c['hymn'] in score]

    heard, notated = {}, {}
    for c in spans:
        h = c['hymn']
        t0 = c.get('t_in') or c['t0']
        t1 = min(t0 + a.limit_sec, c['t1'])
        p = subprocess.run(
            ['ffmpeg', '-v', 'quiet', '-ss', str(t0), '-to', str(t1), '-i', tape,
             '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        x = np.frombuffer(p.stdout, dtype=np.float32)
        if x.size < SR:
            continue
        f0, ok = f0_track(x)
        f = f0[ok]
        if f.size < 50:
            continue
        cents = 1200.0 * np.log2(f / np.median(f))
        off, _ = estimate_base(cents, dc)
        rel = (cents - off) % 1200.0
        d = np.abs(rel[:, None] - np.array(dc)[None, :])
        d = np.minimum(d, 1200.0 - d)
        heard[h] = collapse(d.argmin(axis=1))
        sc = score[h]
        full = [v % 7 for v in degree_stream(
            units_for(sc['p0'], sc['l0'], sc['g0'],
                      sc['p1'], sc['l1'], sc['g1']), legend)]
        # Only part of a long span is listened to, so only the corresponding
        # PREFIX of its score may be compared. Matching 60 s of audio against
        # 671 notated notes is not a failure of the method, it is a failure to
        # compare like with like -- and it was scoring long scores as
        # mismatches regardless of content.
        frac = (t1 - t0) / max(c['t1'] - t0, 1e-6)
        notated[h] = full[:max(int(round(len(full) * frac)), 8)]
        print('  %-10s heard %3d symbols, score %3d of %3d (%.0f%% of span)'
              % (h, len(heard[h]), len(notated[h]), len(full), 100 * frac),
              flush=True)

    if a.identity_check:
        # Same comparison, but the "audio" side is the score's own sequence,
        # run-length collapsed the way a sung rendition would be. Any failure
        # here is the matcher, not the recogniser.
        for h in list(heard):
            n = notated.get(h) or []
            heard[h] = [n[i] for i in range(len(n)) if i == 0 or n[i] != n[i - 1]]
    names = [h for h in heard if notated.get(h)]
    hit, ranks = 0, []
    print()
    for h in names:
        sc = sorted(((dtw_cost(heard[h], notated[g]), g) for g in names))
        best = sc[0][1]
        r = [g for _, g in sc].index(h) + 1
        hit += best == h
        ranks.append(r)
        print('  %-10s best=%-10s %s rank %d/%d'
              % (h, best, 'OK ' if best == h else '   ', r, len(sc)))
    print(f'\npitch-vs-score identification: {hit}/{len(names)}')
    print(f'median rank of the correct answer: {int(np.median(ranks))} of {len(names)}')
    print(f'ASR baseline on the same task: 2/23, median rank ~9')


if __name__ == '__main__':
    main()
