#!/usr/bin/env python3
"""parallagi_class.py -- which degree is being sung on each note of a parallagi.

Chanter's plan, 2026-08-21: the peak model finds onsets on parallagi tracks;
"since we have onsets correct we can just classify each note and overfit it on
that, and that will be our parallagi classifier."

So: onsets in, one label per note out. The span from one onset to the next is
cut out of the audio and classified.

TWO OCTAVES, ABSOLUTE -- 15 classes, low Δι to high Δι. Chanter: "extend the
classifier to two octaves. we dont have any low di but we have zo and high zo as
well as ni and pa. but it should still be low di to two octaves above as high
di."

    -3 δι,  -2 κε,  -1 ζω,   0 νη   1 πα   2 βου   3 γα
     4 δι    5 κε    6 ζω    7 νη'  8 πα'  9 βου' 10 γα' 11 δι'

Octave is not thrown away, which a mod-7 collapse would do. It matters: the
parallagi is establishing where in the ladder the hymn sits, so "δι" and "δι an
octave up" are different answers even though they are the same syllable. The
syllable is what is SUNG; the octave is what is MEANT.

Distribution over s02+s04+s06, 258 notes:
    δι 80 (31%)  γα 60  βου 31  κε 31  πα 17  δι' 12  ζω 9  γα' 7  νη 4  βου' 2
Majority-class baseline is 31.0% -- always answer δι. Below that is worse than a
constant.

FIVE NOTES FALL OUTSIDE THE RANGE and they are all in s04: κε'(12) x3, ζω'(13),
νη''(14). They are excluded and reported rather than accommodated by widening
the range, because s04's degree stream looks wrong there rather than high: it
runs 0..6, skips νη'(7) and πα'(8) entirely, then resumes at βου'(9). A stream
that leaps a third and never comes back is the signature of an octave
mis-anchoring, the same class of fault as the martyria anchoring in
score_degrees.py. Widening the class space would have buried it.

WHAT THE LABELS ARE, AND ARE NOT. They come from the score, via
degree_stream() over the legend -- not from listening. So the classifier is
being taught what the SCORE says, and it inherits the legend's errors. On s06
the pitch verifier in onset_match.py already found transitions where the sung
movement and the score disagree at correctly-placed notes (gi 9/10, 59/60, 91).
No parallagi_flags.json exists for these three, so none of it has been reviewed.

That cuts both ways and the second way is the useful one: a parallagi sings the
answer out loud, so a confident disagreement between this model and the score is
evidence about the SCORE, not just about the model. Trained honestly, its
mistakes are a legend-error detector.

Usage:
  parallagi_class.py --piece <dir> --gold <gold.json> ... --epochs 400
  parallagi_class.py ... --loo          # leave-one-hymn-out, the honest number
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'corpus'))

SR, HOP, NMEL = 22050, 220, 64
DEG = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']
DEG_LO, DEG_HI = -3, 11                 # low Δι .. high Δι, two octaves
NCLS = DEG_HI - DEG_LO + 1              # 15


def deg_name(d):
    o, i = divmod(int(d), 7)
    return DEG[i] + ("'" * o if o > 0 else ',' * -o)
MAXFR = 64                      # 0.64 s -- longer notes are centre-cropped


def audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def mel(y):
    import librosa
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=2048, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=6000)
    x = librosa.power_to_db(m, ref=np.max)
    return ((x - x.mean()) / (x.std() + 1e-6)).astype(np.float32)


def degrees(hymn, n):
    from score_degrees import units_for, degree_stream, leading_anchor
    cuts = json.load(open('/mnt/data/chant-corpus/texts/scorecuts_grave-orthros.json'))['cuts']
    c = next(x for x in cuts if x['hymn'] == hymn)
    u = units_for(c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
    leg = json.load(open('/mnt/data/chant-corpus/scores/legend_canon.json'))
    d = degree_stream(u, leg, start=leading_anchor(c['p0'], c['g0']))
    assert len(d) == n, 'degree stream %d vs %d notes' % (len(d), n)
    return [int(x) for x in d]


def cut(M, t0, t1):
    """One note's mel patch, fixed width, centred if the note is long."""
    a, b = int(t0 * SR / HOP), int(t1 * SR / HOP)
    b = max(b, a + 4)
    seg = M[:, a:b]
    if seg.shape[1] >= MAXFR:
        o = (seg.shape[1] - MAXFR) // 2
        return seg[:, o:o + MAXFR]
    pad = np.zeros((NMEL, MAXFR), dtype=np.float32)
    pad[:, :seg.shape[1]] = seg
    return pad


class Clf(nn.Module):
    """Small 2-D CNN over the note's mel patch.

    A parallagi syllable is as much a spoken sound as a pitch -- νη, πα and βου
    differ in their consonant and vowel, not only in frequency -- so the patch
    keeps both axes and the convolutions see formant structure, not just where
    the energy sits.
    """
    def __init__(self, ncls=NCLS, ch=64):
        super().__init__()
        def blk(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.GELU(),
                                 nn.BatchNorm2d(o), nn.MaxPool2d(2))
        self.f = nn.Sequential(blk(1, ch), blk(ch, ch * 2), blk(ch * 2, ch * 2))
        self.head = nn.Sequential(nn.Flatten(), nn.Dropout(0.3),
                                  nn.Linear(ch * 2 * (NMEL // 8) * (MAXFR // 8), 256),
                                  nn.GELU(), nn.Dropout(0.3), nn.Linear(256, ncls))

    def forward(self, x):
        return self.head(self.f(x.unsqueeze(1)))


def load(piece_dir, gold_file, hymn):
    D = json.load(open(os.path.join(piece_dir, 'annotator_data.json')))
    n = len(D['slots']['gi'])
    raw = json.load(open(gold_file))
    if isinstance(raw, dict) and 'onsets' in raw:
        # quick_onset.place() output: model onsets, in time order, one per note.
        g = {i: float(t) for i, t in enumerate(raw['onsets'])}
    elif isinstance(raw, dict):
        g = {int(k): float(v) for k, v in raw.items()}
    else:
        g = {int(k): float(v) for k, v in raw}
    M = mel(audio(os.path.join(piece_dir, 'audio.wav')))
    y = degrees(hymn, n)
    X, Y, dropped = [], [], []
    ts = [g[i] for i in sorted(g)]
    for k, i in enumerate(sorted(g)):
        t1 = ts[k + 1] if k + 1 < len(ts) else ts[k] + 0.6
        if not DEG_LO <= y[i] <= DEG_HI:
            dropped.append((i, y[i])); continue
        X.append(cut(M, g[i], t1)); Y.append(y[i] - DEG_LO)
    if dropped:
        print('    %d note(s) outside the two-octave range, excluded: %s'
              % (len(dropped), ', '.join('gi=%d %s(%+d)' % (i, deg_name(d), d)
                                         for i, d in dropped)))
    return np.stack(X), np.array(Y), os.path.basename(piece_dir)[14:44]


def predict(net, piece_dir, onsets_file, dev, hymn=None):
    """Degree per note for a piece, from its audio and a set of onsets.

    The onsets can be the chanter's or the onset model's. Where a score exists
    the prediction is compared against it, and a DISAGREEMENT IS THE POINT: a
    parallagi sings its answer out loud, so a confident mismatch is evidence
    about the score, not only about the model. On s06 this heard γα where the
    score said βου, and the chanter confirmed γα -- the score was wrong.

    It cannot tell a wrong onset from a wrong degree. If the onsets came from
    the model rather than from him, a note misplaced by one articulation reads
    as a misclassification here, so low agreement means "look at this piece",
    not "the score is wrong".
    """
    D = json.load(open(os.path.join(piece_dir, 'annotator_data.json')))
    n = len(D['slots']['gi'])
    raw = json.load(open(onsets_file))
    if isinstance(raw, dict) and 'onsets' in raw:
        ts = list(raw['onsets'])
    elif isinstance(raw, dict):
        ts = [float(raw[k]) for k in sorted(raw, key=int)]
    else:
        ts = [float(t) for _, t in raw]
    M = mel(audio(os.path.join(piece_dir, 'audio.wav')))
    X = []
    for k, t0 in enumerate(ts):
        t1 = ts[k + 1] if k + 1 < len(ts) else t0 + 0.6
        X.append(cut(M, t0, t1))
    x = torch.from_numpy(np.stack(X)).to(dev)
    with torch.inference_mode():
        p = torch.softmax(net(x), 1)
    conf, idx = p.max(1)
    pred = [int(i) + DEG_LO for i in idx.cpu().numpy()]
    conf = [float(c) for c in conf.cpu().numpy()]
    row = {'piece_id': os.path.basename(piece_dir.rstrip('/')),
           'n_notes': n, 'n_onsets': len(ts),
           'degrees': pred, 'names': [deg_name(d) for d in pred],
           'confidence': [round(c, 3) for c in conf],
           'mean_confidence': round(float(np.mean(conf)), 3)}
    if hymn:
        try:
            want = degrees(hymn, n)
            if len(want) == len(pred):
                agree = sum(1 for a, b in zip(want, pred) if a == b)
                row['score_agreement'] = round(agree / len(want), 3)
                row['disagreements'] = [
                    {'note': i, 'score': deg_name(want[i]), 'heard': deg_name(pred[i]),
                     'conf': round(conf[i], 3)}
                    for i in range(len(want)) if want[i] != pred[i]]
        except Exception as e:
            row['score_error'] = str(e)
    return row


def run(train, test, epochs, lr, dev, tag):
    Xtr = torch.from_numpy(np.concatenate([t[0] for t in train])).to(dev)
    Ytr = torch.from_numpy(np.concatenate([t[1] for t in train])).long().to(dev)
    Xte = torch.from_numpy(np.concatenate([t[0] for t in test])).to(dev)
    Yte = torch.from_numpy(np.concatenate([t[1] for t in test])).long().to(dev)
    net = Clf().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-3)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    cnt = np.bincount(Ytr.cpu().numpy(), minlength=NCLS).astype(float)
    w = torch.tensor((cnt.sum() / np.maximum(cnt, 1)) ** 0.5, dtype=torch.float32, device=dev)
    lf = nn.CrossEntropyLoss(weight=w, label_smoothing=0.05)
    bs = 32
    for e in range(epochs):
        net.train(); perm = torch.randperm(len(Xtr), device=dev)
        for i in range(0, len(perm), bs):
            j = perm[i:i + bs]
            opt.zero_grad(); l = lf(net(Xtr[j]), Ytr[j]); l.backward(); opt.step()
        sch.step()
    net.eval()
    with torch.inference_mode():
        pr = net(Xte).argmax(1)
        tr = net(Xtr).argmax(1)
    acc = float((pr == Yte).float().mean()); tacc = float((tr == Ytr).float().mean())
    print('  %-34s train %5.1f%%   %s %5.1f%%  (n=%d)'
          % (tag, 100 * tacc, 'TEST', 100 * acc, len(Yte)))
    return pr.cpu().numpy(), Yte.cpu().numpy(), acc, net


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--piece', action='append', required=True)
    ap.add_argument('--gold', action='append', required=True)
    ap.add_argument('--hymn', action='append', required=True)
    ap.add_argument('--epochs', type=int, default=400)
    ap.add_argument('--lr', type=float, default=6e-4)
    ap.add_argument('--loo', action='store_true', help='leave one hymn out')
    ap.add_argument('--out-degrees')
    ap.add_argument('--errors', action='store_true',
                    help='list every note where the model and the score disagree')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--save', help='write trained weights here')
    ap.add_argument('--load', help='use these weights instead of training')
    ap.add_argument('--infer', action='append', metavar='DIR:ONSETS',
                    help='piece dir and an onsets json, colon separated; '
                         'repeatable. Predicts the degree of every note.')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    data = [load(p, g, h) for p, g, h in zip(a.piece, a.gold, a.hymn)]
    for X, Y, nm in data:
        print('%-34s %3d notes' % (nm, len(Y)))
    allY = np.concatenate([d[1] for d in data])
    base = np.bincount(allY, minlength=NCLS).max() / len(allY)
    print('\n%d classes, low %s .. high %s' % (NCLS, deg_name(DEG_LO), deg_name(DEG_HI)))
    print('majority-class baseline %.1f%% (always %s)\n'
          % (100 * base, deg_name(int(np.bincount(allY, minlength=NCLS).argmax()) + DEG_LO)))

    if a.loo:
        print('LEAVE-ONE-HYMN-OUT -- the honest number:')
        accs = []
        for i in range(len(data)):
            _last = run([d for j, d in enumerate(data) if j != i], [data[i]],
                        a.epochs, a.lr, dev, 'hold out ' + data[i][2])
            acc = _last[2]
            accs.append(acc)
            if a.errors:
                pr, gt = _last[0], _last[1]
                nm_ = data[i][2]
                bad = [(k, gt[k], pr[k]) for k in range(len(gt)) if gt[k] != pr[k]]
                print('      %d disagreement(s) with the score on %s:' % (len(bad), nm_))
                for k, t, p_ in bad:
                    print('        note %-3d score says %-6s model hears %-6s'
                          % (k, deg_name(int(t) + DEG_LO), deg_name(int(p_) + DEG_LO)))
        print('\n  mean held-out accuracy %.1f%%  vs %.1f%% baseline'
              % (100 * np.mean(accs), 100 * base))
    else:
        print('TRAINED AND SCORED ON EVERYTHING -- memorisation, not skill:')
        pr, gt, _, net = run(data, data, a.epochs, a.lr, dev, 'all three')
        if a.save:
            torch.save(net.state_dict(), a.save)
            print('-> weights', a.save)
        cm = np.zeros((NCLS, NCLS), int)
        for p, t in zip(pr, gt):
            cm[t][p] += 1
        seen = [i for i in range(NCLS) if cm[i].sum() or cm[:, i].sum()]
        print('\n  confusion (row = score says, col = model says):')
        print('         ' + ' '.join('%5s' % deg_name(i + DEG_LO) for i in seen))
        for i in seen:
            print('  %-6s ' % deg_name(i + DEG_LO)
                  + ' '.join('%5d' % cm[i][j] for j in seen))
    if a.infer:
        net = Clf().to(dev)
        net.load_state_dict(torch.load(a.load, map_location=dev))
        net.eval()
        print('\nDEGREE PER NOTE (weights %s):' % a.load)
        rows = []
        for spec in a.infer:
            pd, of = spec.rsplit(':', 1)
            r = predict(net, pd, of, dev)
            rows.append(r)
            print('  %-46s %3d notes  mean confidence %.2f'
                  % (r['piece_id'][:46], r['n_onsets'], r['mean_confidence']))
        if a.out_degrees:
            json.dump(rows, open(a.out_degrees, 'w'), ensure_ascii=False, indent=1)
            print('->', a.out_degrees)
    return 0


if __name__ == '__main__':
    sys.exit(main())
