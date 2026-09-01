#!/usr/bin/env python3
"""lane_modspec.py -- parallagi or melos from the MODULATION spectrum.

Chanter: "just give it the entire cut piece and no windows just as a whole. it
needs to be length invariant because length doesnt matter so just need a
transform of the time series into frequency series, which is length invariant,
then a model would be able to classify easily and it will transfer."

That is the right transform and it is worth saying why. What separates the two
lanes is RATE, not timbre. A parallagi articulates a degree name per note at a
fairly even clip; a melos spreads one syllable over many notes. So the evidence
lives in how fast the energy fluctuates, which is exactly the modulation
spectrum: take the envelope of each mel band over the whole span and Fourier
transform THAT. The result has a fixed size no matter how long the span is --
20 s or 400 s collapse to the same matrix -- and it discards absolute pitch,
absolute loudness and most of the room.

    mel band energy over time  ->  FFT over time  ->  |X| at 0.25 .. 16 Hz

Two earlier attempts and why this differs:

  threshold on deg/s   decode with wav2vec2, count degree names, cut at 0.43.
                       95.7% on grave (fitted there), 81.8% on mode 2. Every
                       error a parallagi called melos; the rate did not change
                       class, the class median moved 0.72 -> 0.44 and the cut
                       stayed put.
  4 s mel patches      0.57 M-parameter 2-D CNN. 54.5% transferring to mode 2,
                       WORSE than the threshold, and 100% memorised on its own
                       data. With one tape per mode, "parallagi" and "this
                       recording" are perfectly confounded, so the cheapest fit
                       is the room. No wav2vec2 was involved in that one.

This representation cannot learn the room in the same way: the per-band envelope
is normalised before the transform, so overall level and static spectral colour
are gone before the model sees anything.

Usage:
  lane_modspec.py --eval-transfer
  lane_modspec.py --train-all --save lane_ms.pt
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn

SR, HOP, NMEL = 16000, 160, 48          # 10 ms envelope sampling -> 100 Hz
NMOD = 40                                # modulation bins
FMIN, FMAX = 0.25, 16.0                  # Hz -- syllable and melisma rates
TAPE = ('/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/'
        'Mode Grave Anastasimatarion 2 Orthros.m4a')
M2 = '/mnt/data/chant-corpus/raw/vasilikos/Mode 2 Anastasimatarion 1 Vespers'
SPANS = '/mnt/data/chant-corpus/texts/span_names_grave-orthros.json'
MODF = np.geomspace(FMIN, FMAX, NMOD)


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


def modspec(y):
    """[NMEL, NMOD] -- how fast each mel band's energy fluctuates.

    Length-invariant by construction: the FFT is taken over the whole span and
    then resampled onto a FIXED log-spaced modulation-frequency grid, so the
    output shape does not depend on duration. Each band envelope is converted to
    dB and standardised first, which removes level and static colour -- the
    parts that identify a RECORDING rather than a lane.
    """
    import librosa
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=1024, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=7000)
    e = librosa.power_to_db(m, ref=np.max)                 # [NMEL, T]
    e = (e - e.mean(axis=1, keepdims=True)) / (e.std(axis=1, keepdims=True) + 1e-6)
    T = e.shape[1]
    if T < 64:
        return None
    win = np.hanning(T)[None, :]
    F = np.abs(np.fft.rfft(e * win, axis=1))               # [NMEL, T//2+1]
    freqs = np.fft.rfftfreq(T, d=HOP / SR)
    out = np.empty((NMEL, NMOD), dtype=np.float32)
    for b in range(NMEL):
        out[b] = np.interp(MODF, freqs, F[b])
    out = np.log1p(out)
    # per-span standardisation: what matters is the SHAPE of the rate profile,
    # not how much total energy the span happens to contain.
    return ((out - out.mean()) / (out.std() + 1e-6)).astype(np.float32)


def load_sets():
    out = []
    for s in json.load(open(SPANS))['spans']:
        if s['lane'] not in ('parallagi', 'melos'):
            continue
        M = modspec(audio(TAPE, s['t0'], s['t1'] - s['t0']))
        if M is not None:
            out.append(('grave', s['lane'], M))
    for f in sorted(glob.glob(os.path.join(M2, '*'))):
        b = os.path.basename(f)
        lab = ('parallagi' if 'ΠΑΡΑΛΛΑΓΗ' in b
               else 'melos' if 'ΜΕΛΟΣ' in b else None)
        if not lab:
            continue
        M = modspec(audio(f))
        if M is not None:
            out.append(('mode2', lab, M))
    return out


class Net(nn.Module):
    """Small on purpose. The feature already did the hard part; a big model here
    would only find room to memorise 79 examples again."""
    def __init__(self, ch=32):
        super().__init__()
        self.f = nn.Sequential(
            nn.Conv2d(1, ch, 3, padding=1), nn.GELU(), nn.BatchNorm2d(ch),
            nn.MaxPool2d(2),
            nn.Conv2d(ch, ch * 2, 3, padding=1), nn.GELU(), nn.BatchNorm2d(ch * 2),
            nn.MaxPool2d(2))
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(ch * 2, 64),
                                  nn.GELU(), nn.Dropout(0.3), nn.Linear(64, 2))

    def forward(self, x):
        h = self.f(x.unsqueeze(1)).mean(dim=(2, 3))
        return self.head(h)


def run(train, test, epochs, dev, tag, jitter=True):
    rng = np.random.default_rng(0)
    Xtr = np.stack([d[2] for d in train])
    Ytr = np.array([1 if d[1] == 'parallagi' else 0 for d in train])
    Xte = torch.from_numpy(np.stack([d[2] for d in test])).to(dev)
    Yte = np.array([1 if d[1] == 'parallagi' else 0 for d in test])
    net = Net().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    lf = nn.CrossEntropyLoss(label_smoothing=0.05)
    xb0 = torch.from_numpy(Xtr).to(dev); yb = torch.from_numpy(Ytr).long().to(dev)
    for e in range(epochs):
        net.train()
        xb = xb0
        if jitter:                       # light noise; 79 examples is very few
            xb = xb0 + 0.1 * torch.randn_like(xb0)
        opt.zero_grad(); lf(net(xb), yb).backward(); opt.step(); sch.step()
    net.eval()
    with torch.inference_mode():
        p = torch.softmax(net(Xte), 1)[:, 1].cpu().numpy()
    pred = (p > 0.5).astype(int)
    ok = int((pred == Yte).sum())
    print('  %-32s %5.1f%%  (%d of %d)' % (tag, 100 * ok / len(Yte), ok, len(Yte)))
    for i in np.where(pred != Yte)[0]:
        print('      MISSED labelled %-9s  p(parallagi)=%.2f'
              % ('parallagi' if Yte[i] else 'melos', p[i]))
    return ok, len(Yte), net


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--epochs', type=int, default=600)
    ap.add_argument('--eval-transfer', action='store_true')
    ap.add_argument('--train-all', action='store_true')
    ap.add_argument('--save')
    ap.add_argument('--device', default='cuda')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    data = load_sets()
    print('%d spans: %s' % (len(data), dict(collections.Counter((d[0], d[1]) for d in data))))
    print('feature %d mel x %d modulation bins (%.2f-%.1f Hz), %.2f M parameters'
          % (NMEL, NMOD, FMIN, FMAX, sum(p.numel() for p in Net().parameters()) / 1e6))
    if a.eval_transfer:
        g = [d for d in data if d[0] == 'grave']
        m = [d for d in data if d[0] == 'mode2']
        print('\nCROSS-MODE TRANSFER  (threshold 81.8%, 4s-mel CNN 54.5%):')
        run(g, m, a.epochs, dev, 'train grave  -> test mode 2')
        run(m, g, a.epochs, dev, 'train mode 2 -> test grave')
    if a.train_all or a.save:
        print('\nTRAINED ON EVERYTHING (for use, not evidence):')
        _, _, net = run(data, data, a.epochs, dev, 'all spans')
        if a.save:
            torch.save(net.state_dict(), a.save); print('-> weights', a.save)
    return 0


if __name__ == '__main__':
    sys.exit(main())
