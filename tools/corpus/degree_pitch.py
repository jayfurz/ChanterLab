#!/usr/bin/env python3
"""degree_pitch.py — Stage 1 of the degree recogniser: pitch alone, no training.

Chanter: the degree is given away by "relative melodic pitches ... as well as
the syllable itself". In parallagi the two are the same fact twice over -- he
sings "δι" ON Di -- so a recogniser has two independent channels. The general
Greek ASR fails on the phonetic one, collapsing seven classes into about three
(Ke and Vou take 78% of all tokens), and never looks at the other.

This looks only at the other. No model, no training: estimate the base, convert
F0 to cents above it, quantise to the mode's steps, read off degrees. Its
purpose is a decision gate, not a product -- if pitch alone beats the ASR's 0.47
histogram cosine against the score, pitch is confirmed as the stronger channel
and Stage 2 is worth building. If it does not, base estimation is wrong and no
amount of training would fix that.

Pitch enters as CENTS ABOVE THE PIECE'S OWN BASE, never Hz: Vasilikos sings at
no fixed concert pitch, and Byzantine steps are not 12-TET, so a chromatic grid
would be the wrong quantiser. The diatonic scale below is in moria (72 to the
octave), the system the notation itself uses.

Usage:  degree_pitch.py --workdir grave-orthros [--genus diatonic]
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEXTS = '/mnt/data/chant-corpus/texts'
SR = 16000
MORIA_CENT = 1200.0 / 72.0

# Steps above the base, in moria. Diatonic is the Byzantine natural scale;
# the others are here so a second tape in another genus can be tried without
# editing code.
GENERA = {
    'diatonic':  [12, 10, 8, 12, 12, 10, 8],
    'chromatic': [8, 14, 8, 12, 8, 14, 8],          # soft chromatic (from Ni)
    'soft_chromatic': [8, 14, 8, 12, 8, 14, 8],     # workdir genus name
    # Hard chromatic is a 6-20-4-12 cycle FROM PA (BYZANTINE_SCALES_REFERENCE
    # §3.2) and does not repeat at Ni, so a Ni-based 7-vector is necessarily
    # an approximation: this is the Pa cycle folded to Ni (sums 72).
    'hard_chromatic': [4, 6, 20, 4, 12, 6, 20],
    'enharmonic': [12, 12, 6, 12, 12, 12, 6],
}


def degrees_cents(genus):
    """Cents above the base for Ni..Zo."""
    steps = GENERA[genus]
    out, acc = [], 0.0
    for s in [0] + steps[:-1]:
        acc += s * MORIA_CENT
        out.append(acc)
    return out


def f0_track(x, sr=SR, hop=160, fmin=70, fmax=500):
    import librosa
    f0, voiced, _ = librosa.pyin(x, sr=sr, fmin=fmin, fmax=fmax,
                                 hop_length=hop, frame_length=1024)
    ok = np.isfinite(f0) & (voiced if voiced is not None else True)
    return f0, ok


def estimate_base(cents_rel, degs_cents):
    """Choose the base offset that best explains the observed pitches.

    The ison is the base sounding, but it is not always present and not always
    the most common note, so instead of assuming, sweep the offset and keep the
    one under which observed pitches sit closest to scale degrees. Sweeping the
    full octave also makes this robust to the chanter starting on any degree.
    """
    best = (1e9, 0.0)
    for off in np.arange(0, 1200, 5.0):
        d = np.abs(((cents_rel - off)[:, None] % 1200.0) - np.array(degs_cents)[None, :])
        d = np.minimum(d, 1200.0 - d).min(axis=1)
        v = float(np.median(d))
        if v < best[0]:
            best = (v, off)
    return best[1], best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--genus', default='diatonic', choices=list(GENERA))
    ap.add_argument('--limit-sec', type=float, default=40.0)
    a = ap.parse_args()

    from score_degrees import units_for, degree_stream
    wd = a.workdir
    legend = json.load(open(f'/mnt/data/chant-corpus/workdirs/{wd}/legend_global.json'))
    cuts = json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts']
    score = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    tape = json.load(open(f'{TEXTS}/recut_{wd}.json'))[0]['tape']
    dc = degrees_cents(a.genus)
    NAMES = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo']

    def audio(t0, t1):
        p = subprocess.run(
            ['ffmpeg', '-v', 'quiet', '-ss', str(t0), '-to', str(t1), '-i', tape,
             '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return np.frombuffer(p.stdout, dtype=np.float32)

    cos_list, dev_list = [], []
    print('%-10s %-7s %-9s %s' % ('span', 'resid', 'cosine', 'pitch histogram'))
    for c in sorted((c for c in cuts if c.get('lane') == 'parallagi'),
                    key=lambda c: c['t0']):
        h = c['hymn']
        if h not in score:
            continue
        t0 = c.get('t_in') or c['t0']          # skip the held νε where marked
        t1 = min(t0 + a.limit_sec, c['t1'])
        x = audio(t0, t1)
        if x.size < SR:
            continue
        f0, ok = f0_track(x)
        f = f0[ok]
        if f.size < 50:
            continue
        cents = 1200.0 * np.log2(f / np.median(f))
        off, resid = estimate_base(cents, dc)
        rel = ((cents - off) % 1200.0)
        d = np.abs(rel[:, None] - np.array(dc)[None, :])
        d = np.minimum(d, 1200.0 - d)
        heard = d.argmin(axis=1)

        us = units_for(score[h]['p0'], score[h]['l0'], score[h]['g0'],
                       score[h]['p1'], score[h]['l1'], score[h]['g1'])
        sd = [x % 7 for x in degree_stream(us, legend)]
        if not sd:
            continue
        hv = np.bincount(heard, minlength=7).astype(float)
        sv = np.bincount(np.array(sd), minlength=7).astype(float)
        hv /= hv.sum(); sv /= sv.sum()
        cos = float(hv @ sv / (np.linalg.norm(hv) * np.linalg.norm(sv) + 1e-9))
        cos_list.append(cos); dev_list.append(resid)
        print('  %-8s %5.0f¢  %.2f      %s'
              % (h[:8], resid, cos,
                 ' '.join('%s%.0f' % (NAMES[i], 100 * hv[i]) for i in range(7))),
              flush=True)

    if cos_list:
        med = float(np.median(cos_list))
        print(f'\nspans scored: {len(cos_list)}')
        print(f'median residual to nearest scale degree: {np.median(dev_list):.0f} cents')
        print(f'median histogram cosine vs score: {med:.2f}')
        print(f'ASR baseline on the same spans:    0.47')
        print('GATE: ' + ('pitch is the stronger channel — build Stage 2'
                          if med > 0.47 else
                          'pitch did NOT beat the ASR — fix base estimation '
                          'before training anything'))


if __name__ == '__main__':
    main()
