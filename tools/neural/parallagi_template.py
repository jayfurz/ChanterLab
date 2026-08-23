#!/usr/bin/env python3
"""parallagi_template.py -- melos onsets from the parallagi that precedes it.

Owner, 2026-08-23: "since we are able to map parallagi can we create parallagi
informed onset and mapping neural net of the melos pieces?"

The parallagi is a sung TEMPLATE of the melos: the same notes, the same singer,
the same tape, at a median length ratio of 1.02 (PARALLAGI-PAIRING.md), and on
the parallagi every onset is known (peak model, recall 1.000) and every degree
is known (classifier, 98.1%). So the melos does not need its onsets found from
scratch against a score it has never heard -- it needs them TRANSFERRED from a
rendition whose onsets are already right, note for note.

This is the no-learning baseline for that idea, so that a model later has a
number to beat: align the two renditions' pitch contours by DTW and carry each
parallagi onset across the path. Two controls are scored beside it:

  stretch   parallagi onsets scaled by the duration ratio (the prior only)
  dtw       DTW on --cost pitch | mel | multi, onsets carried across the path

Scored by onset_eval.py against the chanter's pins on the melos -- which he
has said are a draft with onsets probably too EARLY (gold_times.UNTRUSTED), so
read slips and bias here, not the 150 ms rate.

Measured 2026-08-23 (gate / slips / bias):
    cost     s02->s03                 s04->s05
    pitch    59.2 %  1 slip  +0.06    6.2 %  3 slips  -2.23   <- slipped
    mel      63.3 %  2 slips +0.10   84.6 %  1 slip   -0.04   <- both lock
    multi    59.2 %  1 slip  +0.08   60.0 %  3 slips  +0.08
Timbre locks where pitch cannot: a melisma is many pitches on one vowel, and
the vowel is what says which syllable the melos is in. Adding pitch back to
mel (multi) makes it worse on both. mel is the default.

Usage:
  parallagi_template.py --par <dir> --par-onsets gold.json --mel <dir> \\
      --mel-pins pins.json [--out pred.json]
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'corpus'))
from degree_pitch import f0_track, SR   # noqa: E402
HOP = 160                                # f0_track's hop: 10 ms


def audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR),
                          '-f', 'f32le', '-'], capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def channels(path, start_s, kind):
    """Per-frame features on f0_track's 10 ms grid, from the sung start.

    pitch   cents from the piece's median F0 (1 dim)          -- the original
    mel     40 log-mel bands, each standardised over the piece
    multi   pitch + mel + onset strength, each block scaled to unit variance
            so no one channel owns the cost. Pitch alone locks on one pair and
            slips on the other: a melisma is many pitches on one syllable, so
            the contour alone cannot say which syllable it is in. Timbre (the
            vowel) and articulation (the onset) can.
    """
    import librosa
    y = audio(path)
    c, ok = contour_from(y)
    f0 = int(start_s * SR / HOP)
    blocks = []
    if kind == 'pitch':
        blocks.append(c[:, None] / 100.0)                       # semitones
    if kind == 'multi':
        # standardised, so pitch weighs the same as the mel block as a whole.
        # In semitone units it weighed ~10x more and the multi cost behaved
        # like pitch alone (s05: 13.8 %, slipped) while mel alone locked it.
        blocks.append(((c - c.mean()) / (c.std() + 1e-6))[:, None])
    if kind in ('mel', 'multi'):
        m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=1024, hop_length=HOP,
                                           n_mels=40, fmin=60, fmax=6000)
        m = librosa.power_to_db(m, ref=np.max).T[:len(c)]
        m = (m - m.mean(0)) / (m.std(0) + 1e-6)
        blocks.append(m / np.sqrt(m.shape[1]))                  # unit total variance
    if kind == 'multi':
        o = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)[:len(c)]
        o = (o - o.mean()) / (o.std() + 1e-6)
        blocks.append(o[:, None])
    n = min(len(b) for b in blocks)
    X = np.concatenate([b[:n] for b in blocks], axis=1).astype(np.float32)
    return X[f0:]


def contour_from(y):
    f0, ok = f0_track(y)
    if ok.sum() < 10:
        return np.zeros(len(f0)), ok
    med = np.median(f0[ok])
    c = 1200.0 * np.log2(np.maximum(f0, 1.0) / med)
    c[~ok] = np.nan
    last = 0.0
    for i in range(len(c)):
        if np.isnan(c[i]):
            c[i] = last
        else:
            last = c[i]
    return c, ok


def dtw_path(A, B, band=None):
    """DTW on frame-feature matrices with a Sakoe-Chiba band; returns the path."""
    A = np.atleast_2d(A.T).T if A.ndim == 1 else A
    B = np.atleast_2d(B.T).T if B.ndim == 1 else B
    n, m = len(A), len(B)
    band = band or max(n, m)
    D = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        jc = int(i * m / n)
        lo, hi = max(1, jc - band), min(m, jc + band)
        d = np.sqrt(((B[lo - 1:hi] - A[i - 1]) ** 2).sum(1))     # one row of costs
        row, prev = D[i], D[i - 1]
        for j in range(lo, hi + 1):
            row[j] = d[j - lo] + min(prev[j], row[j - 1], prev[j - 1])
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        k = np.argmin((D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]))
        if k == 0:
            i, j = i - 1, j - 1
        elif k == 1:
            i -= 1
        else:
            j -= 1
    return path[::-1]


def load_onsets(f):
    raw = json.load(open(f))
    if isinstance(raw, dict) and 'onsets' in raw:
        raw = raw['onsets']
    if isinstance(raw, dict):
        return {int(k): float(v) for k, v in raw.items()}
    if isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
        return {int(k): float(v) for k, v in raw}
    return {i: float(t) for i, t in enumerate(raw)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--par', required=True, help='parallagi piece dir (audio.wav)')
    ap.add_argument('--par-onsets', required=True)
    ap.add_argument('--mel', required=True, help='melos piece dir')
    ap.add_argument('--mel-pins', required=True)
    ap.add_argument('--band-s', type=float, default=8.0, help='DTW band, seconds')
    ap.add_argument('--cost', default='mel', choices=('pitch', 'mel', 'multi'))
    ap.add_argument('--out', help='prefix for the two prediction files')
    a = ap.parse_args()

    po = load_onsets(a.par_onsets)
    # The apichima. A parallagi often opens with a held intonation before the
    # first note (s04: 13-15 s of it), and a melos may too. The annotator's
    # meta records where the singing proper starts; align from there, or the
    # intonation absorbs the first seconds of the other rendition and every
    # onset after it slips (s05: +6.2 s bias, 0 % in gate, before this).
    def sung_start(d):
        m = json.load(open(os.path.join(d, 'annotator_data.json')))['meta']
        return float(m.get('sung_onset') or m.get('t_in_rel') or 0.0)
    sp, sm = sung_start(a.par), sung_start(a.mel)
    cp = channels(os.path.join(a.par, 'audio.wav'), sp, a.cost)
    cm = channels(os.path.join(a.mel, 'audio.wav'), sm, a.cost)
    dp, dm = len(cp) * HOP / SR, len(cm) * HOP / SR
    print('parallagi %.1fs from %.1fs, melos %.1fs from %.1fs, ratio %.3f, %d parallagi onsets, cost=%s (%d dims)'
          % (dp, sp, dm, sm, dm / dp, len(po), a.cost, cp.shape[1]))

    # control: pure time stretch from the sung starts
    stretch = {g: sm + max(t - sp, 0.0) * dm / dp for g, t in po.items()}

    # DTW on pitch contour, parallagi onsets carried across the path
    path = dtw_path(cp, cm, band=int(a.band_s * SR / HOP))
    first = {}
    for i, j in path:
        first.setdefault(i, j)
    dtw = {}
    for g, t in po.items():
        i = min(max(int((t - sp) * SR / HOP), 0), len(cp) - 1)
        j = first.get(i)
        if j is None:                     # frame skipped by the path: nearest
            k = min(first, key=lambda x: abs(x - i))
            j = first[k]
        dtw[g] = sm + j * HOP / SR

    out = a.out or os.path.join(os.path.dirname(a.mel_pins), 'template')
    for nm, pred in (('stretch', stretch), ('dtw_' + a.cost, dtw)):
        f = '%s_%s.json' % (out, nm)
        json.dump({str(g): round(t, 4) for g, t in sorted(pred.items())}, open(f, 'w'), indent=1)
        print('->', f)
        r = subprocess.run([sys.executable, os.path.join(HERE, '..', 'corpus', 'onset_eval.py'),
                            '--pred', f, '--pins', a.mel_pins, '--label', nm],
                           capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        print('\n'.join('  ' + l for l in lines[-14:]))
        if r.returncode:
            print(r.stderr[-800:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
