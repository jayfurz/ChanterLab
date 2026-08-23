#!/usr/bin/env python3
"""melos_onset_net.py -- S4b-02: melos onsets from the parallagi, with a LEARNED match cost.

What the DTW baseline (parallagi_template.py) established, on real gold:
    mel cost, anchored        s03 84.2 %  1 slip      s05 85.9 %  1 slip
    + free ends within 2 s    s03 84.2 %  1 slip      s05 87.1 %  1 slip
and where it fails: a mid-piece run at the SAME place in both renditions of
the hymn (a melisma -- many notes on one vowel, where timbre has nothing to
lock to and pitch is the only channel with information) and s05's ending.
A fixed global channel weighting cannot know where to trust which channel
(`multi` was worse than `mel` alone). So the thing to learn is the COST.

THE MODEL IS THE COST, NOT THE ALIGNMENT. A small conv encoder embeds every
10 ms frame of either rendition from its mel, cents and onset strength with
+/- 100 ms of context. The match cost between a parallagi frame and a melos
frame is the distance between their embeddings. The alignment is still the
same monotonic DTW, so the net cannot invent a slip of its own; it can only
make the right path cheaper than the wrong one where the hand-built costs
could not tell them apart.

WHY THIS CAN LEARN FROM 161 NOTES. The labels are not 161 onsets, they are
frame CORRESPONDENCES: every frame of parallagi note i lies at some fraction
r of that note, and the matching melos frame is at the same fraction of melos
note i (both onsets are gold). That is ~5,000 positive pairs per piece, and
every other melos frame within a few seconds is a hard negative. Trained with
InfoNCE, the encoder learns which channels distinguish note i from note i+1
in THIS kind of music -- per frame, which is what the fixed weighting lacked.

HELD OUT BY PIECE. Two gold pairs exist (s02->s03, s04->s05). Train on one,
score the other, both directions. Same piece in train and test would be
meaningless, and frames within a piece are correlated.

Usage:
  melos_onset_net.py --pair <par_dir>:<par_gold>:<mel_dir>:<mel_gold> [--pair ...] \\
      --xval [--epochs 30] [--out prefix]
  melos_onset_net.py --pair ... --train-all --save melos_cost.pt
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'corpus'))
from degree_pitch import f0_track, SR           # noqa: E402
from parallagi_template import dtw_path, contour_from, load_onsets, audio  # noqa: E402

HOP = 160                    # 10 ms
NMEL = 40
CTX = 10                     # +/- 100 ms of context per frame
DIM = NMEL + 2               # mel + cents + onset strength


def frames(path):
    """Per-frame features [T, DIM], each block z-scored over the piece."""
    import librosa
    y = audio(path)
    c, _ = contour_from(y)
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=1024, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=6000)
    m = librosa.power_to_db(m, ref=np.max).T
    o = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    T = min(len(c), len(m), len(o))
    m = (m[:T] - m[:T].mean(0)) / (m[:T].std(0) + 1e-6)
    c = ((c[:T] - c[:T].mean()) / (c[:T].std() + 1e-6))[:, None]
    o = ((o[:T] - o[:T].mean()) / (o[:T].std() + 1e-6))[:, None]
    return np.concatenate([m, c, o], 1).astype(np.float32)


def sung_start(d):
    m = json.load(open(os.path.join(d, 'annotator_data.json')))['meta']
    return float(m.get('sung_onset') or m.get('t_in_rel') or 0.0)


class Encoder(nn.Module):
    """Frame -> 64-d unit embedding, from a [DIM, 2*CTX+1] patch."""
    def __init__(self, dim=DIM, ch=96, out=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(dim, ch, 5, padding=2), nn.GELU(), nn.GroupNorm(8, ch),
            nn.Conv1d(ch, ch, 5, padding=4, dilation=2), nn.GELU(), nn.GroupNorm(8, ch),
            nn.Conv1d(ch, ch, 3, padding=1), nn.GELU(),
        )
        self.head = nn.Linear(ch, out)

    def forward(self, x):                      # x [B, T, DIM] -> [B, T, out]
        h = self.net(x.transpose(1, 2)).transpose(1, 2)
        return F.normalize(self.head(h), dim=-1)


def embed(net, X, dev, chunk=4000):
    """Embed a whole piece; the conv is translation-equivariant so the
    per-frame embedding sees exactly its +/- context whatever the chunking."""
    out = []
    with torch.inference_mode():
        for i in range(0, len(X), chunk):
            lo, hi = max(0, i - 2 * CTX), min(len(X), i + chunk + 2 * CTX)
            e = net(torch.from_numpy(X[lo:hi]).unsqueeze(0).to(dev))[0]
            out.append(e[i - lo:i - lo + min(chunk, len(X) - i)].cpu().numpy())
    return np.concatenate(out)


def correspondences(par_on, mel_on, Tp, Tm):
    """(parallagi frame, melos frame) for every frame of every note, by
    relative position inside the note. Last note runs 0.6 s."""
    n = len(par_on)
    gp = [par_on[i] for i in range(n)]; gm = [mel_on[i] for i in range(n)]
    pairs, note = [], []
    for i in range(n):
        p0 = gp[i]; p1 = gp[i + 1] if i + 1 < n else p0 + 0.6
        m0 = gm[i]; m1 = gm[i + 1] if i + 1 < n else m0 + 0.6
        for fp in range(int(p0 * SR / HOP), int(p1 * SR / HOP)):
            r = (fp * HOP / SR - p0) / max(p1 - p0, 1e-3)
            fm = int((m0 + r * (m1 - m0)) * SR / HOP)
            if 0 <= fp < Tp and 0 <= fm < Tm:
                pairs.append((fp, fm)); note.append(i)
    return np.array(pairs), np.array(note)


def load_pair(spec):
    pd, pg, md, mg = spec.split(':')
    po, mo = load_onsets(pg), load_onsets(mg)
    assert len(po) == len(mo), 'note counts differ: %d vs %d' % (len(po), len(mo))
    Xp, Xm = frames(os.path.join(pd, 'audio.wav')), frames(os.path.join(md, 'audio.wav'))
    pairs, note = correspondences([po[i] for i in sorted(po)], [mo[i] for i in sorted(mo)],
                                  len(Xp), len(Xm))
    return {'name': os.path.basename(md)[14:40], 'par_dir': pd, 'mel_dir': md,
            'Xp': Xp, 'Xm': Xm, 'po': po, 'mo': mo, 'pairs': pairs, 'note': note,
            'mel_gold': mg}


def train(net, data, epochs, dev, lr=1e-3, bs=192, neg_s=6.0, tau=0.07):
    """InfoNCE: for a parallagi frame, its melos partner against melos frames
    from OTHER notes within +/- neg_s seconds (hard) plus a few random ones."""
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    negw = int(neg_s * SR / HOP)
    steps = sum(len(d['pairs']) for d in data) // bs
    for ep in range(epochs):
        net.train(); tot = 0.0
        for _ in range(steps):
            d = data[np.random.randint(len(data))]
            idx = np.random.randint(len(d['pairs']), size=bs)
            fp, fm = d['pairs'][idx, 0], d['pairs'][idx, 1]
            # 24 negatives per anchor: melos frames near fm but in another note
            nm = np.clip(fm[:, None] + np.random.randint(-negw, negw, size=(bs, 24)), 0, len(d['Xm']) - 1)
            # patches
            def patch(X, f):
                f = np.clip(f, CTX, len(X) - CTX - 1)
                return np.stack([X[a - CTX:a + CTX + 1] for a in f.ravel()]).reshape(*f.shape, 2 * CTX + 1, DIM)
            A = torch.from_numpy(patch(d['Xp'], fp)).to(dev)                 # [bs, 21, DIM]
            P = torch.from_numpy(patch(d['Xm'], fm)).to(dev)
            N = torch.from_numpy(patch(d['Xm'], nm)).to(dev)                 # [bs, 24, 21, DIM]
            ea = net(A)[:, CTX]                                               # [bs, 64]
            ep_ = net(P)[:, CTX]
            en = net(N.reshape(-1, 2 * CTX + 1, DIM))[:, CTX].reshape(bs, 24, -1)
            # mask negatives that fall inside the same note (they are not negatives)
            note_of = np.full(len(d['Xm']), -1)
            mo = [d['mo'][i] for i in sorted(d['mo'])]
            for i, t in enumerate(mo):
                t1 = mo[i + 1] if i + 1 < len(mo) else t + 0.6
                note_of[int(t * SR / HOP):int(t1 * SR / HOP)] = i
            same = torch.from_numpy(note_of[nm] == d['note'][idx][:, None]).to(dev)
            pos = (ea * ep_).sum(-1, keepdim=True)                            # [bs,1]
            neg = torch.einsum('bd,bkd->bk', ea, en).masked_fill(same, -1e4)  # [bs,24]
            logits = torch.cat([pos, neg], 1) / tau
            loss = F.cross_entropy(logits, torch.zeros(bs, dtype=torch.long, device=dev))
            opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss.detach())
        sch.step()
        if (ep + 1) % max(1, epochs // 6) == 0:
            print('  epoch %3d  loss %.3f' % (ep + 1, tot / max(steps, 1)), flush=True)
    net.eval()
    return net


def align(net, d, dev, band_s=8.0, free_s=2.0):
    """Learned-cost DTW, parallagi onsets carried across. Same geometry as
    parallagi_template: parallagi from its sung start, melos free within 2 s."""
    sp = sung_start(d['par_dir']); fp0 = int(sp * SR / HOP)
    Ep = embed(net, d['Xp'], dev)[fp0:]
    Em = embed(net, d['Xm'], dev)
    path = dtw_path(Ep, Em, band=int(band_s * SR / HOP), free=int(free_s * SR / HOP))
    first = {}
    for i, j in path:
        first.setdefault(i, j)
    pred = {}
    for g, t in d['po'].items():
        i = min(max(int((t - sp) * SR / HOP), 0), len(Ep) - 1)
        j = first.get(i)
        if j is None:
            k = min(first, key=lambda x: abs(x - i)); j = first[k]
        pred[g] = j * HOP / SR
    return pred


def score(pred, gold_file, label, out):
    json.dump({str(g): round(t, 4) for g, t in sorted(pred.items())}, open(out, 'w'), indent=1)
    r = subprocess.run([sys.executable, os.path.join(HERE, '..', 'corpus', 'onset_eval.py'),
                        '--pred', out, '--pins', gold_file, '--label', label],
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    print('\n'.join('  ' + l for l in lines[-8:]))
    g = {int(a): b for a, b in json.load(open(gold_file))}
    bad = [(i, round(pred[i] - g[i], 2)) for i in sorted(g) if i in pred and abs(pred[i] - g[i]) > 0.15]
    print('  out of gate (gi, dt):', bad)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--pair', action='append', required=True,
                    help='par_dir:par_gold:mel_dir:mel_gold')
    ap.add_argument('--xval', action='store_true', help='train on all but one pair, score it; every fold')
    ap.add_argument('--train-all', action='store_true')
    ap.add_argument('--epochs', type=int, default=30)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--save')
    ap.add_argument('--out', default='melos_net')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    data = [load_pair(s) for s in a.pair]
    for d in data:
        print('%-28s parallagi %5d frames  melos %5d frames  %3d notes  %5d frame pairs'
              % (d['name'], len(d['Xp']), len(d['Xm']), len(d['po']), len(d['pairs'])))
    print('encoder %.2f M parameters' % (sum(p.numel() for p in Encoder().parameters()) / 1e6))

    if a.xval:
        for k, held in enumerate(data):
            tr = [d for i, d in enumerate(data) if i != k]
            if not tr:
                print('need >= 2 pairs for --xval'); return 1
            print('\nHOLD OUT %s  (train on %s)' % (held['name'], ', '.join(d['name'] for d in tr)))
            net = train(Encoder().to(dev), tr, a.epochs, dev)
            pred = align(net, held, dev)
            score(pred, held['mel_gold'], 'learned_cost', '%s_%s.json' % (a.out, held['name'][:3]))
    if a.train_all:
        net = train(Encoder().to(dev), data, a.epochs, dev)
        if a.save:
            torch.save(net.state_dict(), a.save); print('->', a.save)
    return 0


if __name__ == '__main__':
    sys.exit(main())
