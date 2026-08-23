#!/usr/bin/env python3
"""piece_bounds.py -- where a piece starts and ends on an hour-long tape.

Chanter: "another model like this one with wider frames and instead of note
onsets, find the start and end of pieces ... i have the spans cut from the one
hour long grave orthros tape" and "make it a huge model and overfit -- we want
horsepower to trust it".

WIDER FRAMES, because the event is a different size. The onset model runs at
10 ms because a note attack is a transient. A piece boundary is a seconds-long
event -- a phrase ends, silence, a new incipit begins -- so this runs at 50 ms
and reaches much further: the dilated stack sees +/- 25 s, which covers the end
of one hymn and the start of the next in a single view.

TWO OUTPUTS, not one. Start and end are different events and must not share a
head: a start is silence-then-voice, an end is voice-then-silence, and a model
with one "boundary" channel would have to guess which side it is on.

THE LABELS ARE CLEAN, and that is measured, not assumed. Over the chanter's 47
spans on the grave orthros tape, the 0.4 s just outside each of the 94
boundaries is 14.5x quieter than a random point in the tape, and NOT ONE of the
94 is louder than the tape's own quietest quartile. Every cut sits in real
silence.

WHICH MEANS THERE ARE NO ABRUPT EXAMPLES TO LEARN FROM. He asked for boundaries
that "cut abruptly" to be classified differently rather than discarded, but all
47 of his are clean, so there is no negative class here. Abruptness is therefore
reported, not predicted: a proposed boundary is scored on how much sound is
still going on outside it, and anything above the silence floor is flagged for
review. The moment abrupt examples exist -- the machine-cut tracks are the
obvious source -- this becomes a third head instead.

TRAINED ON RANDOM CROPS. The first onset model trained on whole pieces, one
gradient step per piece per epoch, and its loss flattened after 480 epochs
having barely fit. 100 s crops with a real batch give hundreds of times more
updates for the same compute.

Usage:
  piece_bounds.py --tape <audio> --spans <span_names.json> --steps 4000
  piece_bounds.py ... --out bounds.json
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn

SR, HOP, NMEL = 16000, 800, 128        # 50 ms frames
SIGMA_FR = 6.0                          # target width, 0.3 s
CROP = 2000                             # 100 s
TAPE = ('/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/'
        'Mode Grave Anastasimatarion 2 Orthros.m4a')
SPANS = '/mnt/data/chant-corpus/texts/span_names_grave-orthros.json'


def audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, timeout=3600).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def features(y):
    import librosa
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=2048, hop_length=HOP,
                                       n_mels=NMEL, fmin=40, fmax=7000)
    x = librosa.power_to_db(m, ref=np.max)
    return ((x - x.mean()) / (x.std() + 1e-6)).astype(np.float32)


def bumps(times, T):
    t = np.zeros(T, dtype=np.float32)
    for s in times:
        c = s * SR / HOP
        lo, hi = int(max(0, c - 4 * SIGMA_FR)), int(min(T, c + 4 * SIGMA_FR + 1))
        if hi > lo:
            i = np.arange(lo, hi)
            t[lo:hi] = np.maximum(t[lo:hi], np.exp(-0.5 * ((i - c) / SIGMA_FR) ** 2))
    return t


class Net(nn.Module):
    """Deliberately oversized. Chanter: "we want horsepower to trust it."

    Eight dilated blocks at 384 channels reach +/- 25 s, then a BiLSTM carries
    whatever the convolutions could not. Two heads, start and end.
    """
    def __init__(self, nmel=NMEL, ch=384, lstm=384):
        super().__init__()
        blocks, c = [], nmel
        for d in (1, 2, 4, 8, 16, 32, 64, 128):
            blocks += [nn.Conv1d(c, ch, 5, padding=2 * d, dilation=d),
                       nn.GELU(), nn.GroupNorm(8, ch)]
            c = ch
        self.conv = nn.Sequential(*blocks)
        self.rnn = nn.LSTM(ch, lstm, batch_first=True, bidirectional=True)
        self.head = nn.Linear(2 * lstm, 2)          # [start, end]

    def forward(self, x):
        h = self.conv(x).transpose(1, 2)
        h, _ = self.rnn(h)
        return self.head(h).permute(0, 2, 1)        # [B, 2, T]


def pick(prob, thr=0.3, min_gap=20):
    idx = np.where((prob[1:-1] >= prob[:-2]) & (prob[1:-1] > prob[2:]))[0] + 1
    idx = idx[prob[idx] > thr]
    idx = idx[np.argsort(-prob[idx])]
    out = []
    for i in idx:
        if all(abs(i - j) >= min_gap for j in out):
            out.append(int(i))
    return sorted(out)


def prf(pred, gold, tol):
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
    ap.add_argument('--tape', default=TAPE)
    ap.add_argument('--spans', default=SPANS)
    ap.add_argument('--steps', type=int, default=4000)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--lr', type=float, default=8e-4)
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--out')
    ap.add_argument('--save', help='write the trained weights here')
    ap.add_argument('--load', help='skip training and use these weights')
    ap.add_argument('--lanes', action='store_true',
                    help='label each span parallagi or melos by degree rate')
    ap.add_argument('--infer', action='append',
                    help='tape to cut with the loaded model; repeatable')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')

    sp = json.load(open(a.spans))['spans']
    y = audio(a.tape)
    X = features(y)
    T = X.shape[1]
    starts = [s['t0'] for s in sp]
    ends = [s['t1'] for s in sp]
    Y = np.stack([bumps(starts, T), bumps(ends, T)])
    print('tape %.1f min -> %d frames at %.0f ms' % (len(y) / SR / 60, T, HOP / SR * 1000))
    print('%d spans: %d starts, %d ends' % (len(sp), len(starts), len(ends)))

    net = Net().to(dev)
    if a.load:
        net.load_state_dict(torch.load(a.load, map_location=dev))
        print('loaded weights from', a.load)
    npar = sum(p.numel() for p in net.parameters())
    print('%.1f M parameters' % (npar / 1e6))
    rf = 1 + sum((5 - 1) * d for d in (1, 2, 4, 8, 16, 32, 64, 128))
    print('conv receptive field %d frames = +/- %.1f s' % (rf, rf * HOP / SR / 2))

    Xt = torch.from_numpy(X).to(dev)
    Yt = torch.from_numpy(Y).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.steps)
    lf = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([40.0, 40.0], device=dev)[:, None])
    rng = np.random.default_rng(0)
    net.train()
    if a.load:
        a.steps = 0
    for s in range(a.steps):
        xs, ys = [], []
        for _ in range(a.batch):
            i = int(rng.integers(0, max(1, T - CROP)))
            xs.append(Xt[:, i:i + CROP]); ys.append(Yt[:, i:i + CROP])
        xb = torch.stack(xs); yb = torch.stack(ys)
        opt.zero_grad()
        l = lf(net(xb), yb)
        l.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 5.0)
        opt.step(); sch.step()
        if (s + 1) % max(1, a.steps // 12) == 0:
            print('  step %5d  loss %.4f' % (s + 1, float(l.detach())))

    if a.save:
        torch.save(net.state_dict(), a.save)
        print('-> weights', a.save)
    net.eval()
    with torch.inference_mode():
        # whole tape in one pass, in overlapping windows to bound memory
        P = np.zeros((2, T), dtype=np.float32)
        W, OV = 6000, 500
        i = 0
        while i < T:
            j = min(T, i + W)
            p = torch.sigmoid(net(Xt[:, i:j].unsqueeze(0)))[0].cpu().numpy()
            a0 = i + (OV if i else 0); b0 = j - (OV if j < T else 0)
            P[:, a0:b0] = p[:, (a0 - i):(b0 - i)]
            if j >= T:
                break
            i = j - 2 * OV
    fs = HOP / SR
    ps = [f * fs for f in pick(P[0])]
    pe = [f * fs for f in pick(P[1])]
    print('\npredicted %d starts, %d ends  (gold %d / %d)' % (len(ps), len(pe), len(starts), len(ends)))
    for name, pred, gold in (('START', ps, starts), ('END', pe, ends)):
        print('  %-6s tol      P      R     F1' % name)
        for tol in (0.25, 0.5, 1.0, 2.0):
            p_, r_, f_ = prf(pred, gold, tol)
            print('         %4.2fs  %.3f  %.3f  %.3f' % (tol, p_, r_, f_))
    if a.out:
        json.dump({'starts': [round(x, 3) for x in ps],
                   'ends': [round(x, 3) for x in pe]}, open(a.out, 'w'), indent=1)
        print('->', a.out)

    for tp in (a.infer or []):
        cut_tape(net, tp, dev, a.out, a.lanes)
    return 0


_LANE = {}


def lane_of(path, t0, t1, dev, limit=25.0):
    """parallagi or melos, from the rate of sung degree names.

    Not a neural net and not mine: presplit_map.py's rule, which decodes the
    span with the Greek CTC model and counts degree syllables per second. A
    parallagi sings νη πα βου γα δι κε ζω out loud; a melos sings text. The
    medians differ by 6x and a threshold at 0.43 deg/s gets 96% on the gold tape
    -- it misreads no melos as parallagi and misses 2 of 23 parallagi
    (PARALLAGI-PAIRING.md). 96%, not 99%.

    Only the first 25 s of a span is decoded, which is what presplit_map does:
    the rate is stable early and a whole span costs 10x more for nothing.
    """
    import numpy as np
    import torch
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', 'corpus'))
    from degree_tokens import degrees_in, MODEL, SR as DSR
    if 'm' not in _LANE:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        _LANE['p'] = Wav2Vec2Processor.from_pretrained(MODEL)
        _LANE['m'] = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    end = min(limit, t1 - t0)
    raw = subprocess.run(['ffmpeg', '-v', 'quiet', '-ss', str(t0), '-t', str(end),
                          '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(DSR), '-'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if x.size < DSR:
        return 'short', 0.0
    with torch.inference_mode():
        lg = _LANE['m'](torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits
    d = _LANE['p'].batch_decode(torch.argmax(lg, dim=-1))[0]
    rate = len(degrees_in(d)) / max(end, 0.1)
    return ('parallagi' if rate > 0.43 else 'melos'), rate


def cut_tape(net, path, dev, outbase=None, lanes=False):
    """Run the trained model over a tape it has never seen and report spans.

    Trained on ONE tape, so every number here is out-of-domain by construction:
    a different mode, a different recording, possibly a different room. The
    boundary-quality figure is the thing to read -- a cut whose outside is not
    quiet is either a real abrupt edit or a bad prediction, and either way it
    wants a human.
    """
    y = audio(path)
    X = torch.from_numpy(features(y)).to(dev)
    T = X.shape[1]
    with torch.inference_mode():
        P = np.zeros((2, T), dtype=np.float32)
        W, OV = 6000, 500
        i = 0
        while i < T:
            j = min(T, i + W)
            p = torch.sigmoid(net(X[:, i:j].unsqueeze(0)))[0].cpu().numpy()
            a0 = i + (OV if i else 0); b0 = j - (OV if j < T else 0)
            P[:, a0:b0] = p[:, (a0 - i):(b0 - i)]
            if j >= T:
                break
            i = j - 2 * OV
    fs = HOP / SR
    ps = [f * fs for f in pick(P[0])]
    pe = [f * fs for f in pick(P[1])]
    # pair each start with the LAST end before the next start. First-end-after
    # is wrong: one spurious start steals the next span's end and every span
    # after it shifts by one (0/47 -> 47/47 at IoU 0.9 on the gold tape).
    # A start with no end of its own ends just before the next start.
    spans = []
    for i, st in enumerate(ps):
        nxt = ps[i + 1] if i + 1 < len(ps) else len(y) / SR
        ends = [e for e in pe if st < e < nxt]
        spans.append((st, ends[-1] if ends else max(st + 1.0, nxt - 0.5)))
    # boundary quality, from the audio: how quiet is it just outside the cut?
    sr2, w = SR, int(0.05 * SR)
    e = np.sqrt(np.convolve(y * y, np.ones(w) / w, 'same'))
    floor = float(np.percentile(e, 5))
    def outside(t, side, win=0.4):
        i0 = int(t * sr2); n0 = int(win * sr2)
        seg = e[max(0, i0 - n0):i0] if side == 's' else e[i0:i0 + n0]
        return float(np.median(seg)) if len(seg) > 10 else float('nan')
    rough = []
    for st, en in spans:
        if outside(st, 's') > 4 * floor or outside(en, 'e') > 4 * floor:
            rough.append((st, en))
    lab = []
    if lanes:
        for st, en in spans:
            lab.append(lane_of(path, st, en, dev))
    print('\n%s' % os.path.basename(path))
    print('  %.1f min -> %d starts, %d ends, %d paired spans'
          % (len(y) / SR / 60, len(ps), len(pe), len(spans)))
    print('  median span %.1f s, shortest %.1f s, longest %.1f s'
          % (np.median([b - a for a, b in spans]) if spans else -1,
             min((b - a for a, b in spans), default=-1),
             max((b - a for a, b in spans), default=-1)))
    print('  %d span(s) with a boundary that is NOT in silence -- review these'
          % len(rough))
    if lab:
        npar = sum(1 for l, _ in lab if l == 'parallagi')
        nmel = sum(1 for l, _ in lab if l == 'melos')
        print('  lanes: %d parallagi, %d melos, %d too short'
              % (npar, nmel, len(lab) - npar - nmel))
        alt = sum(1 for i in range(1, len(lab))
                  if lab[i][0] == 'melos' and lab[i - 1][0] == 'parallagi')
        print('  melos preceded by its parallagi: %d of %d melos%s'
              % (alt, nmel, '  -- pairing holds' if nmel and alt == nmel else ''))
    if outbase:
        f = outbase.replace('.json', '') + '.' + os.path.splitext(
            os.path.basename(path))[0].replace(' ', '_')[:40] + '.json'
        json.dump({'tape': path,
                   'spans': [{'t0': round(x, 3), 't1': round(z, 3),
                              'lane': (lab[i][0] if lab else None),
                              'deg_per_s': (round(lab[i][1], 3) if lab else None),
                              'boundary_in_silence': (x, z) not in rough}
                             for i, (x, z) in enumerate(spans)]},
                  open(f, 'w'), indent=1)
        print('  ->', f)


if __name__ == '__main__':
    sys.exit(main())
