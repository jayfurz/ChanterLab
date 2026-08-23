#!/usr/bin/env python3
"""lane_net.py -- parallagi or melos, learned from audio instead of thresholded.

The rule it replaces is presplit_map.py's: decode with the Greek CTC model,
count degree names per second, threshold at 0.43. Measured 2026-08-21:

    grave orthros   95.7%   tuning set -- 0.43 was fitted here
    mode 2 vespers  81.8%   held out

and every one of the errors, on both sets, is a parallagi called melos. Never
the reverse. The rates say why: parallagi sit at a median 0.72 deg/s on grave
and collapse to 0.44 on mode 2 -- right on the threshold -- while melos stay
near 0.06 on both. The classes never overlapped. One class moved and the
threshold did not follow. That is a calibration failure, and re-fitting the
threshold on the only held-out set available would just move the problem.

So: learn it, and evaluate the thing that actually broke -- transfer to a mode
the model has never heard.

WINDOWS, NOT SPANS. Each labelled span contributes many 4 s windows. 79 spans is
far too few examples for a CNN, but 79 spans is thousands of windows, and the
question "is this person singing degree names" is answerable from four seconds.
It also makes the model length-invariant, which matters because a span here can
be 20 s or 400 s. At inference the windows vote.

TRAINED ON MEL, NOT ON THE CTC OUTPUT. The threshold rule can only see what the
Greek recogniser chose to emit, so a parallagi it mis-decodes is invisible to
it. Mel keeps the evidence -- the flat, evenly-spaced, vowel-heavy delivery of a
parallagi against the melismatic line of a melos -- whether or not a recogniser
tuned on modern Greek speech happens to spell it.

Usage:
  lane_net.py --eval-transfer          # train grave -> test mode2, and back
  lane_net.py --train-all --save lane.pt
"""
import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn

SR, HOP, NMEL = 16000, 160, 64          # 10 ms
WIN = 400                                # 4 s
TAPE = ('/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/'
        'Mode Grave Anastasimatarion 2 Orthros.m4a')
M2 = '/mnt/data/chant-corpus/raw/vasilikos/Mode 2 Anastasimatarion 1 Vespers'
SPANS = '/mnt/data/chant-corpus/texts/span_names_grave-orthros.json'


def audio(path, t0=None, dur=None):
    cmd = ['ffmpeg', '-v', 'quiet']
    if t0 is not None:
        cmd += ['-ss', str(t0)]
    if dur is not None:
        cmd += ['-t', str(dur)]
    cmd += ['-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-']
    raw = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, timeout=1800).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def mel(y):
    import librosa
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=1024, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=7000)
    x = librosa.power_to_db(m, ref=np.max)
    return ((x - x.mean()) / (x.std() + 1e-6)).astype(np.float32)


def load_sets():
    """[(name, label, mel)] for both labelled corpora."""
    out = []
    for s in json.load(open(SPANS))['spans']:
        if s['lane'] not in ('parallagi', 'melos'):
            continue
        y = audio(TAPE, s['t0'], s['t1'] - s['t0'])
        if y.size > SR:
            out.append(('grave', s['lane'], mel(y)))
    for f in sorted(glob.glob(os.path.join(M2, '*'))):
        b = os.path.basename(f)
        lab = ('parallagi' if 'ΠΑΡΑΛΛΑΓΗ' in b
               else 'melos' if 'ΜΕΛΟΣ' in b else None)
        if not lab:
            continue
        y = audio(f)
        if y.size > SR:
            out.append(('mode2', lab, mel(y)))
    return out


class Net(nn.Module):
    def __init__(self, ch=48):
        super().__init__()
        def blk(i, o, p=(2, 2)):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.GELU(),
                                 nn.BatchNorm2d(o), nn.MaxPool2d(p))
        self.f = nn.Sequential(blk(1, ch), blk(ch, ch * 2), blk(ch * 2, ch * 4),
                               blk(ch * 4, ch * 4))
        self.head = nn.Sequential(nn.Dropout(0.4), nn.Linear(ch * 4, 128),
                                  nn.GELU(), nn.Dropout(0.4), nn.Linear(128, 2))

    def forward(self, x):
        h = self.f(x.unsqueeze(1))               # [B, C, F, T]
        h = h.mean(dim=(2, 3))                   # pool both axes
        return self.head(h)


def windows(M, n, rng):
    T = M.shape[1]
    if T <= WIN:
        pad = np.zeros((NMEL, WIN), dtype=np.float32)
        pad[:, :T] = M
        return [pad] * n
    return [M[:, i:i + WIN] for i in rng.integers(0, T - WIN, n)]


def batches(data, rng, per_span=8):
    X, Y = [], []
    for _, lab, M in data:
        for w in windows(M, per_span, rng):
            X.append(w); Y.append(1 if lab == 'parallagi' else 0)
    X = np.stack(X); Y = np.array(Y)
    p = rng.permutation(len(X))
    return X[p], Y[p]


def span_vote(net, M, dev, stride=200):
    T = M.shape[1]
    ws = ([M[:, i:i + WIN] for i in range(0, max(1, T - WIN), stride)]
          if T > WIN else windows(M, 1, np.random.default_rng(0)))
    x = torch.from_numpy(np.stack(ws)).to(dev)
    with torch.inference_mode():
        p = torch.softmax(net(x), 1)[:, 1].mean()
    return float(p)


def run(train, test, epochs, dev, tag):
    rng = np.random.default_rng(0)
    net = Net().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-3)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    lf = nn.CrossEntropyLoss(label_smoothing=0.05)
    for e in range(epochs):
        X, Y = batches(train, rng)
        xb = torch.from_numpy(X).to(dev); yb = torch.from_numpy(Y).long().to(dev)
        net.train()
        for i in range(0, len(xb), 64):
            opt.zero_grad()
            lf(net(xb[i:i + 64]), yb[i:i + 64]).backward()
            opt.step()
        sch.step()
    net.eval()
    ok, bad = 0, []
    for nm, lab, M in test:
        p = span_vote(net, M, dev)
        pred = 'parallagi' if p > 0.5 else 'melos'
        ok += pred == lab
        if pred != lab:
            bad.append((lab, p))
    print('  %-34s %5.1f%%  (%d of %d)' % (tag, 100 * ok / len(test), ok, len(test)))
    for lab, p in bad:
        print('      MISSED labelled %-9s  p(parallagi)=%.2f' % (lab, p))
    return ok, len(test), net


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--epochs', type=int, default=60)
    ap.add_argument('--eval-transfer', action='store_true')
    ap.add_argument('--train-all', action='store_true')
    ap.add_argument('--save')
    ap.add_argument('--device', default='cuda')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    data = load_sets()
    import collections
    c = collections.Counter((d[0], d[1]) for d in data)
    print('%d labelled spans: %s' % (len(data), dict(c)))
    print('%.2f M parameters' % (sum(p.numel() for p in Net().parameters()) / 1e6))

    if a.eval_transfer:
        g = [d for d in data if d[0] == 'grave']
        m = [d for d in data if d[0] == 'mode2']
        print('\nCROSS-MODE TRANSFER -- the thing the threshold failed at:')
        print('  (threshold rule for comparison: grave 95.7%, mode2 81.8%)')
        run(g, m, a.epochs, dev, 'train grave  -> test mode 2')
        run(m, g, a.epochs, dev, 'train mode 2 -> test grave')
    if a.train_all or a.save:
        print('\nTRAINED ON EVERYTHING (for use, not for evidence):')
        _, _, net = run(data, data, a.epochs, dev, 'all 79 spans')
        if a.save:
            torch.save(net.state_dict(), a.save)
            print('-> weights', a.save)
    return 0


if __name__ == '__main__':
    sys.exit(main())
