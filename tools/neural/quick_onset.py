#!/usr/bin/env python3
"""quick_onset.py -- audio in, onset timestamps out. A deliberate overfit.

Chanter: "make a quick neural net which will take as an input this entire audio
and output timestamps. let's make it big enough that we can overfit it but still
have room to grow if we give it another hymn. just train it on my pins."

So that is what this is, and the honesty about it matters more than the number:
trained on one piece and scored on that same piece, this measures MEMORISATION,
not skill. A 0.5 M-parameter network fitting 82 labels will reproduce them.
What it is actually for is (a) proving the pipeline end to end -- features,
targets, decode, scoring -- and (b) giving the size curve somewhere to start
when more hymns arrive. --holdout exists so the difference stays visible.

NOT the NEURAL-CHANT model. That one (NN-04) is an encoder-decoder over the
neume stream, gated on PIN-REPEAT-01 and a written contract. This is a frame
tagger with no score input at all: it never sees how many notes there are, or
which, and it cannot know it has skipped one. It is the floor that architecture
has to beat, not a step toward it.

Architecture, sized to overfit one hymn and still have room for a hundred:

    log-mel 80 x 10 ms
      -> 4 dilated Conv1d blocks (256 ch, k=5, dil 1/2/4/8), GELU + LayerNorm
      -> BiGRU 192
      -> linear -> per-frame onset logit

The dilations reach +/- 1.5 s, which spans a couple of notes at chant tempo, and
the BiGRU carries the phrase. Targets are Gaussian bumps at the pins rather than
single frames, because a hand-placed pin carries its own scatter and a
one-frame target teaches the net to be confident about a precision nobody has.

Usage:
  quick_onset.py --piece <data dir> --pins <pins.json> --epochs 900
  quick_onset.py --piece A --pins A.json --piece B --pins B.json   # more hymns
  quick_onset.py ... --holdout          # train on all but the last, score it
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn

SR, HOP, NMEL = 22050, 220, 80
EXPORTS = ('/mnt/data/code/byzorgan-web-worktrees/chant-annotator/'
           'datasets/exports')          # 9.98 ms frames
SIGMA_FR = 2.0                          # target bump width, ~20 ms


def audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def features(y):
    import librosa
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=2048, hop_length=HOP,
                                       n_mels=NMEL, fmin=50, fmax=8000)
    x = librosa.power_to_db(m, ref=np.max)
    x = (x - x.mean()) / (x.std() + 1e-6)
    return x.astype(np.float32)                     # [NMEL, T]


def targets(times, T):
    """Gaussian bumps at the pins. Soft on purpose -- see the docstring."""
    t = np.zeros(T, dtype=np.float32)
    for s in times:
        c = s * SR / HOP
        lo, hi = int(max(0, c - 4 * SIGMA_FR)), int(min(T, c + 4 * SIGMA_FR + 1))
        if hi <= lo:
            continue
        i = np.arange(lo, hi)
        t[lo:hi] = np.maximum(t[lo:hi], np.exp(-0.5 * ((i - c) / SIGMA_FR) ** 2))
    return t


class Net(nn.Module):
    def __init__(self, nmel=NMEL, ch=256, gru=192):
        super().__init__()
        blocks, c = [], nmel
        for d in (1, 2, 4, 8):
            blocks += [nn.Conv1d(c, ch, 5, padding=2 * d, dilation=d),
                       nn.GELU(), nn.GroupNorm(1, ch)]
            c = ch
        self.conv = nn.Sequential(*blocks)
        self.gru = nn.GRU(ch, gru, batch_first=True, bidirectional=True)
        self.head = nn.Linear(2 * gru, 1)

    def forward(self, x):                            # x [B, NMEL, T]
        h = self.conv(x).transpose(1, 2)             # [B, T, ch]
        h, _ = self.gru(h)
        return self.head(h).squeeze(-1)              # [B, T] logits


def pick(prob, k, min_gap_fr=18):
    """The k strongest local maxima, at least min_gap_fr apart, in time order."""
    p = prob.copy()
    idx = np.where((p[1:-1] >= p[:-2]) & (p[1:-1] > p[2:]))[0] + 1
    idx = idx[np.argsort(-p[idx])]
    out = []
    for i in idx:
        if all(abs(i - j) >= min_gap_fr for j in out):
            out.append(int(i))
        if len(out) == k:
            break
    return sorted(out)


def detection_prf(pred, gold, tol):
    """Greedy one-to-one match. Detection only -- says nothing about WHICH note.

    This is NOT onset_eval and does not replace it. onset_eval asks "is glyph i
    at the right time", which needs an assignment; this asks "was the
    articulation found at all", which is what a frame tagger actually does. On
    s06 the two disagreed violently -- 22% by onset_eval against recall 1.000
    here -- and the gap was the whole finding: every onset located to within
    20 ms, and the index assignment desynchronised anyway.
    """
    used, tp = set(), 0
    for g in gold:
        best = None
        for i, x in enumerate(pred):
            if i in used or abs(x - g) > tol:
                continue
            if best is None or abs(x - g) < abs(pred[best] - g):
                best = i
        if best is not None:
            used.add(best); tp += 1
    P = tp / max(len(pred), 1); R = tp / max(len(gold), 1)
    return P, R, (2 * P * R / (P + R) if P + R else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--piece', action='append', required=True,
                    help='annotator data dir (holds annotator_data.json + audio.wav)')
    ap.add_argument('--pins', action='append', required=True)
    ap.add_argument('--epochs', type=int, default=900)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--holdout', action='store_true',
                    help='train on all but the LAST piece and score that one')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--out')
    ap.add_argument('--save', help='write trained weights here')
    ap.add_argument('--load', help='use these weights instead of training')
    ap.add_argument('--infer-dir', action='append',
                    help='annotator piece dir to place onsets for; repeatable')
    ap.add_argument('--write-seed', action='store_true',
                    help="write each inferred piece's onsets into its export "
                         "dir as slots_corrected.json, so the annotator opens "
                         "on them")
    a = ap.parse_args()
    assert len(a.piece) == len(a.pins)
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')

    data = []
    for d, pf in zip(a.piece, a.pins):
        D = json.load(open(os.path.join(d, 'annotator_data.json')))
        raw = json.load(open(pf))
        pins = {int(g): float(t) for g, t in (raw['pins'] if isinstance(raw, dict) else raw)}
        x = features(audio(os.path.join(d, 'audio.wav')))
        y = targets(sorted(pins.values()), x.shape[1])
        data.append({'name': os.path.basename(d)[:38], 'x': x, 'y': y,
                     'pins': pins, 'n_notes': len(D['slots']['gi'])})
        print('%-40s %5d frames (%.1f s)  %d pins  %d notes'
              % (data[-1]['name'], x.shape[1], x.shape[1] * HOP / SR,
                 len(pins), data[-1]['n_notes']))

    train = data[:-1] if (a.holdout and len(data) > 1) else data
    test = [data[-1]] if (a.holdout and len(data) > 1) else data
    print('\ntrain on %d piece(s), score %d' % (len(train), len(test)))

    net = Net().to(dev)
    if a.load:
        net.load_state_dict(torch.load(a.load, map_location=dev))
        a.epochs = 0
        print('loaded weights from', a.load)
    npar = sum(p.numel() for p in net.parameters())
    print('%.2f M parameters' % (npar / 1e6))
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.epochs)
    pw = torch.tensor([12.0], device=dev)            # onsets are sparse
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)

    X = [torch.from_numpy(d['x']).unsqueeze(0).to(dev) for d in train]
    Y = [torch.from_numpy(d['y']).unsqueeze(0).to(dev) for d in train]
    for e in range(a.epochs):
        net.train(); tot = 0.0
        for x, y in zip(X, Y):
            opt.zero_grad()
            l = lossf(net(x), y)
            l.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step(); tot += float(l)
        sched.step()
        if (e + 1) % max(1, a.epochs // 10) == 0:
            print('  epoch %4d  loss %.4f' % (e + 1, tot / len(X)))

    if a.save:
        torch.save(net.state_dict(), a.save)
        print('-> weights', a.save)
    net.eval()
    out = {}
    for d in test:
        with torch.inference_mode():
            p = torch.sigmoid(net(torch.from_numpy(d['x']).unsqueeze(0).to(dev)))[0]
        prob = p.detach().cpu().numpy()
        fr = pick(prob, d['n_notes'])
        onsets = {i: fr[i] * HOP / SR for i in range(len(fr))}
        out[d['name']] = onsets
        print('\n%s: picked %d onsets for %d notes' % (d['name'], len(fr), d['n_notes']))
        gold = sorted(d['pins'].values())
        print('  DETECTION (set, not assignment):   tol      P      R     F1')
        for tol in (0.02, 0.05, 0.10, 0.15):
            P, R, F = detection_prf(sorted(onsets.values()), gold, tol)
            print('                                    %3.0fms  %.3f  %.3f  %.3f'
                  % (tol * 1000, P, R, F))
        if a.out:
            f = a.out if len(test) == 1 else '%s.%s.json' % (a.out, d['name'])
            json.dump({str(g): round(t, 4) for g, t in onsets.items()}, open(f, 'w'), indent=1)
            print('->', f)

    for pd in (a.infer_dir or []):
        place(net, pd, dev, a.out, a.write_seed)
    return 0


def place(net, piece_dir, dev, outbase=None, write_seed=False):
    """Onsets for a piece the model has never seen.

    The score supplies the note COUNT and nothing else -- the network never sees
    which notes they are, so it cannot tell that it has skipped one. Held out on
    s06 it found every onset (recall 1.000 at 50 ms) while only 69% landed on the
    right glyph, because a single inserted or dropped peak shifts every index
    after it. So these are candidate onsets to correct, not an answer: the count
    is right by construction and the ALIGNMENT is what needs an eye.
    """
    name = os.path.basename(piece_dir.rstrip('/'))
    D = json.load(open(os.path.join(piece_dir, 'annotator_data.json')))
    n = len(D['slots']['gi'])
    x = features(audio(os.path.join(piece_dir, 'audio.wav')))
    with torch.inference_mode():
        p = torch.sigmoid(net(torch.from_numpy(x).unsqueeze(0).to(dev)))[0]
    prob = p.detach().cpu().numpy()
    # No onset can precede the piece's sung start: pick() takes the k strongest
    # peaks over the WHOLE file, so peaks inside an apichima or opening silence
    # consume note indexes and shift every note after them (s46: 12 intro peaks
    # -> the melos transfer collapsed). The chanter's t_in mark wins over the
    # detector unless they agree within 3 s -- prep_span_annotator's own rule.
    meta = D.get('meta', {})
    t_in, det = meta.get('t_in_rel'), meta.get('sung_onset')
    sp = det if (t_in and det and abs(det - t_in) <= 3.0) else (t_in or det or 0.0)
    if sp:
        prob[:int(sp * SR / HOP)] = 0.0
    fr = pick(prob, n)
    ts = [f * HOP / SR for f in fr]
    conf = float(np.mean([prob[f] for f in fr])) if fr else 0.0
    iois = np.diff(ts)
    print('  %-46s %3d notes  %3d onsets  conf %.2f  median IOI %.3f s'
          % (name[:46], n, len(ts), conf, float(np.median(iois)) if len(iois) else -1))
    rec = {'piece_id': name, 'n_notes': n,
           'onsets': [round(t, 4) for t in ts],
           'mean_peak_confidence': round(conf, 4)}
    if outbase:
        f = '%s.%s.json' % (outbase.replace('.json', ''), name[:44])
        json.dump(rec, open(f, 'w'), indent=1)
    if write_seed and len(ts) == n:
        ed = os.path.join(EXPORTS, name)
        os.makedirs(ed, exist_ok=True)
        json.dump({'piece_id': name, 't': [round(t, 4) for t in ts],
                   'gi': list(D['slots']['gi']), 'sub': list(D['slots']['sub']),
                   'machine_t': list(D['slots']['t']),
                   'edited': [True] * n, 'pinned': [False] * n,
                   'source': 'quick_onset.py -- MODEL OUTPUT, not chanter work'},
                  open(os.path.join(ed, 'slots_corrected.json'), 'w'), indent=1)
    return rec


if __name__ == '__main__':
    sys.exit(main())
