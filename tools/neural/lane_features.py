#!/usr/bin/env python3
"""lane_features.py -- parallagi or melos from signals that survive a mode change.

Chanter's design, and every piece of it is aimed at the same failure: a model
that learns the RECORDING instead of the LANE.

  1 RATE.  "just give it the entire cut piece and no windows ... a transform of
    the time series into frequency series, which is length invariant". The
    modulation spectrum -- the FFT of each mel band's envelope over the whole
    span -- is fixed-size whatever the duration, and it captures how fast the
    energy fluctuates.
  2 THE SYLLABLES THEMSELVES.  "its also frequency of ni pa voi ga dhi ke zo ni.
    those syllables dont really appear in melos ever and not at those rates."
  3 EVERY NOTE IS A SYLLABLE.  "everynote is a parallagi" -- in a parallagi the
    articulation count and the note count agree, which they do not in a melos.
  4 PEAKINESS.  "the note onset mel NN works really great at parallagi, but
    thats because they have really clear peaks ... melos doesnt have as many
    peaks because you dont necessarily make a consonant between every note,
    sometimes they are just open vowels. that can also be weighed in figuring
    out parallagi or melos which is invariant of mode."

WHY A FEATURE VECTOR AND NOT A BIG NET. There are 79 labelled spans from TWO
recordings, one per mode, so "parallagi" and "this tape" are perfectly
confounded. A 0.57 M-parameter CNN on 4 s mel patches memorised its own data at
100% and transferred to mode 2 at 54.5% -- worse than the 0.43 deg/s threshold
it was meant to replace (81.8%). More capacity makes that worse, not better.
These features are chosen so the room is not in them: envelopes are
standardised per band before the transform, and the counts are ratios.

WHAT IS NOT IN HERE YET is the chanter's strongest idea: "if we give it the
score as well it will be able to tell when it matches the lyrics underneath or
not. parallagi only matches notes." That is a direct test rather than a proxy --
align the span against the hymn text and against the degree-name text and see
which fits -- and it needs a score and a text for every span. Both exist for
grave orthros; neither exists for mode 2, which is the only held-out set. It
goes in when a second scored corpus does.

Usage:
  lane_features.py --eval-transfer
  lane_features.py --train-all --save lane_feat.joblib   # for separate_pieces_nn

"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'corpus'))

SR, HOP, NMEL = 16000, 160, 40
NMOD = 24
MODF = np.geomspace(0.25, 12.0, NMOD)
TAPE = ('/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/'
        'Mode Grave Anastasimatarion 2 Orthros.m4a')
M2 = '/mnt/data/chant-corpus/raw/vasilikos/Mode 2 Anastasimatarion 1 Vespers'
SPANS = '/mnt/data/chant-corpus/texts/span_names_grave-orthros.json'
_CTC = {}


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


def feat(y, dev='cuda'):
    """A fixed-length description of a span, whatever its duration."""
    import librosa
    if y.size < SR * 2:
        return None
    f = {}

    # --- 1 RATE: modulation spectrum, length-invariant ------------------------
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=1024, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=7000)
    e = librosa.power_to_db(m, ref=np.max)
    e = (e - e.mean(1, keepdims=True)) / (e.std(1, keepdims=True) + 1e-6)
    T = e.shape[1]
    F = np.abs(np.fft.rfft(e * np.hanning(T)[None, :], axis=1))
    fr = np.fft.rfftfreq(T, d=HOP / SR)
    ms = np.stack([np.interp(MODF, fr, F[b]) for b in range(NMEL)])
    ms = np.log1p(ms).mean(0)                       # average over bands
    ms = (ms - ms.mean()) / (ms.std() + 1e-6)
    f['mod'] = ms                                   # [NMOD]

    # --- 4 PEAKINESS: is there an articulation on every note? -----------------
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP,
                                       aggregate=np.median)
    env = np.maximum(env - np.percentile(env, 10), 0)
    env = env / (np.percentile(env, 99) + 1e-9)
    idx = np.where((env[1:-1] >= env[:-2]) & (env[1:-1] > env[2:]))[0] + 1
    dur = len(y) / SR
    strong = idx[env[idx] > 0.35]
    f['peaks'] = np.array([
        len(strong) / dur,                          # strong peaks per second
        float(np.mean(env[strong])) if len(strong) else 0.0,
        float(np.percentile(env, 75) - np.percentile(env, 25)),  # contrast
        float(np.mean(env > 0.35)),                 # duty cycle
    ], dtype=np.float32)

    # --- 2 THE SYLLABLES: how often do degree names come out? -----------------
    import torch
    from degree_tokens import degrees_in, MODEL, SR as DSR
    if 'm' not in _CTC:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        _CTC['p'] = Wav2Vec2Processor.from_pretrained(MODEL)
        _CTC['m'] = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    clip = y[:int(30 * SR)]
    if DSR != SR:
        clip = librosa.resample(clip, orig_sr=SR, target_sr=DSR)
    with torch.inference_mode():
        lg = _CTC['m'](torch.from_numpy(clip.copy()).unsqueeze(0).to(dev)).logits
    txt = _CTC['p'].batch_decode(torch.argmax(lg, dim=-1))[0]
    sec = len(clip) / DSR
    degs = degrees_in(txt)
    letters = sum(c.isalpha() for c in txt)
    f['deg'] = np.array([
        len(degs) / max(sec, .1),                   # the old 0.43 rule, as input
        len(degs) / max(letters, 1),                # 3 EVERY NOTE: share of the
        letters / max(sec, .1),                     #   decode that IS a degree
    ], dtype=np.float32)
    return np.concatenate([f['mod'], f['peaks'], f['deg']]).astype(np.float32)


def load_sets(dev):
    out = []
    for s in json.load(open(SPANS))['spans']:
        if s['lane'] not in ('parallagi', 'melos'):
            continue
        v = feat(audio(TAPE, s['t0'], s['t1'] - s['t0']), dev)
        if v is not None:
            out.append(('grave', s['lane'], v))
    for fp in sorted(glob.glob(os.path.join(M2, '*'))):
        b = os.path.basename(fp)
        lab = ('parallagi' if 'ΠΑΡΑΛΛΑΓΗ' in b
               else 'melos' if 'ΜΕΛΟΣ' in b else None)
        if not lab:
            continue
        v = feat(audio(fp), dev)
        if v is not None:
            out.append(('mode2', lab, v))
    return out


def fit_eval(train, test, tag):
    """Logistic regression. 79 examples does not support anything larger."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    Xtr = np.stack([d[2] for d in train]); Ytr = np.array([d[1] == 'parallagi' for d in train]).astype(int)
    Xte = np.stack([d[2] for d in test]); Yte = np.array([d[1] == 'parallagi' for d in test]).astype(int)
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=5000))
    clf.fit(Xtr, Ytr)
    p = clf.predict_proba(Xte)[:, 1]
    pred = (p > 0.5).astype(int)
    ok = int((pred == Yte).sum())
    print('  %-32s %5.1f%%  (%d of %d)' % (tag, 100 * ok / len(Yte), ok, len(Yte)))
    for i in np.where(pred != Yte)[0]:
        print('      MISSED labelled %-9s  p=%.2f'
              % ('parallagi' if Yte[i] else 'melos', p[i]))
    return clf


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--eval-transfer', action='store_true')
    ap.add_argument('--ablate', action='store_true')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--train-all', action='store_true',
                    help='fit on every labelled span (grave + mode 2) and --save')
    ap.add_argument('--save', help='joblib path for the fitted pipeline')
    a = ap.parse_args()
    data = load_sets(a.device)
    if a.train_all:
        import joblib
        clf = fit_eval(data, data, 'train all -> resubstitution (not a test)')
        joblib.dump(clf, a.save)
        print('->', a.save)
        return 0
    print('%d spans: %s' % (len(data), dict(collections.Counter((d[0], d[1]) for d in data))))
    print('feature: %d modulation bins + 4 peakiness + 3 degree = %d dims'
          % (NMOD, len(data[0][2])))
    g = [d for d in data if d[0] == 'grave']
    m = [d for d in data if d[0] == 'mode2']
    print('\nCROSS-MODE TRANSFER  (0.43 threshold 81.8%, 4s-mel CNN 54.5%):')
    fit_eval(g, m, 'train grave  -> test mode 2')
    fit_eval(m, g, 'train mode 2 -> test grave')
    if a.ablate:
        print('\nwhich signal is carrying it (train grave -> test mode 2):')
        sl = {'rate only': slice(0, NMOD), 'peakiness only': slice(NMOD, NMOD + 4),
              'degree only': slice(NMOD + 4, NMOD + 7),
              'peakiness+degree': slice(NMOD, NMOD + 7)}
        for nm, s in sl.items():
            gg = [(a_, b_, c_[s]) for a_, b_, c_ in g]
            mm = [(a_, b_, c_[s]) for a_, b_, c_ in m]
            fit_eval(gg, mm, nm)
    return 0


if __name__ == '__main__':
    sys.exit(main())
