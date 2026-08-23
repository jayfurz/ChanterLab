#!/usr/bin/env python3
"""degree_match_clf.py -- the 2/23 identification test, with the classifier.

degree_match.py asked whether a parallagi span identifies its own score from
a pitch-quantised degree stream: 1/21, chance. Its --identity-check proved the
matcher is fine (20/21), so the recogniser was the whole gap.

This swaps the recogniser for the learned pair:

    peak onset model (quick_onset.py)  -> one articulation per note
    degree classifier (parallagi_class.py, 98.1% LOO) -> one degree per note

and asks the same question with the same DTW. Nothing else changes.

Two things are deliberately NOT done:
  * No note count from the score. degree_match had no count either; giving the
    onset picker each candidate's own count would leak identity. Onsets are
    picked by threshold.
  * No 60 s limit. The whole span is heard and compared to the whole score.

The classifier is trained on s02/s04/s06, which are three of the 23 spans, so
the honest figure excludes them and is reported alongside the full one.

Usage:
  degree_match_clf.py --onset-weights onset.pt --clf-weights clf.pt
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'neural'))
import quick_onset as QO                     # noqa: E402
import parallagi_class as PC                 # noqa: E402
from degree_match import _dtw, dtw_cost      # noqa: E402
from score_degrees import degree_stream, units_for, leading_anchor  # noqa: E402

TEXTS = '/mnt/data/chant-corpus/texts'
TRAINED_ON = {'t01_#3', 't01_#5', 't01_#7'}      # s02, s04, s06


def tape_audio(tape, t0, t1):
    p = subprocess.run(['ffmpeg', '-v', 'quiet', '-ss', str(t0), '-to', str(t1),
                        '-i', tape, '-f', 'f32le', '-ac', '1', '-ar', str(QO.SR), '-'],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def peaks(prob, thresh, min_gap_fr=18):
    """Local maxima above thresh, greedy by height, min_gap apart, time order."""
    idx = np.where((prob[1:-1] >= prob[:-2]) & (prob[1:-1] > prob[2:])
                   & (prob[1:-1] >= thresh))[0] + 1
    idx = idx[np.argsort(-prob[idx])]
    out = []
    for i in idx:
        if all(abs(i - j) >= min_gap_fr for j in out):
            out.append(int(i))
    return sorted(out)


def abs_dtw(a, b):
    """DTW on absolute two-octave degrees: no rotation, plain step distance."""
    if not a or not b:
        return 1e9
    n, m = len(a), len(b)
    d = np.abs(np.array(a)[:, None] - np.array(b)[None, :]).astype(float)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        row, prev, dd = D[i], D[i - 1], d[i - 1]
        for j in range(1, m + 1):
            row[j] = dd[j - 1] + min(prev[j], row[j - 1], prev[j - 1])
    return D[n, m] / min(n, m)


def rank_all(heard, notated, cost):
    names = [h for h in heard if notated.get(h)]
    rows = []
    for h in names:
        sc = sorted((cost(heard[h], notated[g]), g) for g in names)
        rows.append((h, sc[0][1], [g for _, g in sc].index(h) + 1, len(sc)))
    return rows


def report(title, rows, exclude=()):
    print(f'\n{title}')
    for h, best, r, n in rows:
        flag = '  (train)' if h in exclude else ''
        print('  %-10s best=%-10s %s rank %2d/%d%s'
              % (h, best, 'OK ' if best == h else '   ', r, n, flag))
    for lab, sub in (('all', rows), ('held out', [x for x in rows if x[0] not in exclude])):
        if not sub:
            continue
        hit = sum(1 for h, b, _, _ in sub if h == b)
        print('  %-9s %d/%d identified, median rank %d'
              % (lab, hit, len(sub), int(np.median([r for _, _, r, _ in sub]))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--onset-weights', required=True)
    ap.add_argument('--clf-weights', required=True)
    ap.add_argument('--thresh', type=float, default=0.5)
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--dump', help='write heard/notated sequences here')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    wd = a.workdir

    legend = json.load(open('/mnt/data/chant-corpus/scores/legend_canon.json'))
    cuts = json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts']
    score = {c['hymn']: c for c in json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    tape = json.load(open(f'{TEXTS}/recut_{wd}.json'))[0]['tape']
    spans = [c for c in sorted(cuts, key=lambda c: c['t0'])
             if c.get('lane') == 'parallagi' and c['hymn'] in score]

    onet = QO.Net().to(dev)
    onet.load_state_dict(torch.load(a.onset_weights, map_location=dev)); onet.eval()
    cnet = PC.Clf().to(dev)
    cnet.load_state_dict(torch.load(a.clf_weights, map_location=dev)); cnet.eval()

    heard, notated, dump = {}, {}, {}
    for c in spans:
        h = c['hymn']
        t0 = c.get('t_in') or c['t0']
        y = tape_audio(tape, t0, c['t1'])
        if y.size < QO.SR:
            continue
        with torch.inference_mode():
            prob = torch.sigmoid(onet(torch.from_numpy(QO.features(y)).unsqueeze(0).to(dev)))[0]
        prob = prob.cpu().numpy()
        fr = peaks(prob, a.thresh)
        ts = [f * QO.HOP / QO.SR for f in fr]
        M = PC.mel(y)
        X = [PC.cut(M, t, ts[k + 1] if k + 1 < len(ts) else t + 0.6) for k, t in enumerate(ts)]
        with torch.inference_mode():
            p = torch.softmax(cnet(torch.from_numpy(np.stack(X)).to(dev)), 1)
        conf, idx = p.max(1)
        heard[h] = [int(i) + PC.DEG_LO for i in idx.cpu().numpy()]
        sc = score[h]
        u = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
        notated[h] = [int(v) for v in degree_stream(
            u, legend, start=leading_anchor(sc['p0'], sc['g0']))]
        print('  %-10s %6.1fs  %3d onsets  %3d notated  conf %.2f'
              % (h, c['t1'] - t0, len(ts), len(notated[h]), float(conf.mean())), flush=True)
        dump[h] = {'heard': heard[h], 'notated': notated[h], 'onsets': [round(t, 3) for t in ts]}

    if a.dump:
        json.dump(dump, open(a.dump, 'w'))

    report('ABSOLUTE two-octave degrees, no rotation', rank_all(heard, notated, abs_dtw), TRAINED_ON)
    mod = lambda s: [v % 7 for v in s]
    report('MOD-7 with rotation (degree_match.py\'s metric)',
           rank_all({h: mod(s) for h, s in heard.items()},
                    {h: mod(s) for h, s in notated.items()},
                    lambda x, y: dtw_cost(x, y, rotations=True)), TRAINED_ON)
    print('\nbaselines on the same task: ASR 2/23 (median rank ~9); '
          'pitch quantiser 1/21 (median rank 11); identity 20/21.')


if __name__ == '__main__':
    main()
