#!/usr/bin/env python3
"""MCR glyph classifier, contour-CNN lane (torch).

Same protocol as train.py (GroupKFold over score lines, pooled out-of-fold
metrics) so numbers are directly comparable with the GBM lane. The hypothesis
this lane tests: the raw pitch contour around the onset (approach glide,
within-note shape) separates the interval-adjacent classes (ison vs oligon vs
apostrofos, kentimata quickness) better than median-delta features can.

Inputs per event:
  x_ev   3 x 48   event-normalized contour  (pitch rel. own median / voiced mask / rms)
  x_ctx  3 x 100  fixed-rate 10 ms window [t0-0.5s, t0+0.5s] (true-timescale onset shape)
  x_sc   scalar feature vector (same list as the GBM lane)

Multi-task heads: glyph (main) + movement/beats/compound (aux). Augmentation:
pitch scale + ramp, window jitter, mask dropout, rms gain.

Usage: train_cnn.py <workdir> [--epochs N] [--models-out DIR]
"""
import json, sys, os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.model_selection import GroupKFold

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import FEATS, DELTA_FEATS, report

HOP = 0.01
EV_N, CTX_N, CTX_HALF = 48, 100, 0.5
SEQ_PAD = 0.10

def build_tensors(wd, rows, jitter=0.0, rng=None):
    mor = np.load(os.path.join(wd, 'moria_track.npy'))
    rms = np.load(os.path.join(wd, 'rms_track.npy'))
    rms_med = float(np.median(rms[rms > 0]))
    MPS = 10.3
    def grab(t0, t1, n):
        ts = np.linspace(t0, t1, n)
        idx = np.clip((ts / HOP).astype(int), 0, len(mor) - 1)
        p, r = mor[idx], rms[idx] / rms_med
        m = (~np.isnan(p)).astype(np.float32)
        return p, m, r.astype(np.float32)
    ev, ctx = [], []
    for row in rows:
        t0, t1 = row['t0'], row['t1']
        if jitter:
            t0 += rng.uniform(-jitter, jitter)
            t1 += rng.uniform(-jitter, jitter)
            t1 = max(t1, t0 + 0.08)
        p, m, r = grab(t0 - SEQ_PAD, t1 + SEQ_PAD, EV_N)
        ref = np.nanmedian(p) if not np.all(np.isnan(p)) else 0.0
        p = (np.where(np.isnan(p), ref, p) - ref) / MPS
        ev.append(np.stack([p.astype(np.float32), m, r]))
        p2, m2, r2 = grab(t0 - CTX_HALF, t0 + CTX_HALF, CTX_N)
        p2 = (np.where(np.isnan(p2), ref, p2) - ref) / MPS
        ctx.append(np.stack([p2.astype(np.float32), m2, r2]))
    return torch.tensor(np.stack(ev)), torch.tensor(np.stack(ctx))

def scalars(rows):
    X = np.array([[np.nan if r['features'][f] is None else float(r['features'][f])
                   for f in FEATS] for r in rows], dtype=np.float32)
    miss = np.isnan(X[:, [FEATS.index(f) for f in DELTA_FEATS]])
    X = np.hstack([np.nan_to_num(X), miss.astype(np.float32)])
    mu, sd = X.mean(0), X.std(0) + 1e-6
    return torch.tensor((X - mu) / sd), (mu, sd)

class Enc(nn.Module):
    def __init__(self, ch=32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(3, ch, 5, padding=2), nn.BatchNorm1d(ch), nn.ReLU(),
            nn.Conv1d(ch, ch * 2, 5, stride=2, padding=2), nn.BatchNorm1d(ch * 2), nn.ReLU(),
            nn.Conv1d(ch * 2, ch * 2, 3, padding=1), nn.BatchNorm1d(ch * 2), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1))
    def forward(self, x):
        return self.net(x).squeeze(-1)

class Net(nn.Module):
    def __init__(self, n_sc, n_glyph, n_mv, n_beats, n_comp):
        super().__init__()
        self.e1, self.e2 = Enc(), Enc()
        self.sc = nn.Sequential(nn.Linear(n_sc, 48), nn.ReLU(), nn.Dropout(0.2))
        self.trunk = nn.Sequential(nn.Linear(64 + 64 + 48, 96), nn.ReLU(), nn.Dropout(0.35))
        self.h_glyph = nn.Linear(96, n_glyph)
        self.h_mv = nn.Linear(96, n_mv)
        self.h_beats = nn.Linear(96, n_beats)
        self.h_comp = nn.Linear(96, n_comp)
    def forward(self, ev, ctx, sc):
        z = self.trunk(torch.cat([self.e1(ev), self.e2(ctx), self.sc(sc)], -1))
        return self.h_glyph(z), self.h_mv(z), self.h_beats(z), self.h_comp(z)

def augment(ev, ctx, rng):
    B = ev.shape[0]
    scale = torch.tensor(rng.uniform(0.92, 1.08, B), dtype=torch.float32)[:, None]
    for x in (ev, ctx):
        x[:, 0] *= scale
        ramp = torch.linspace(-1, 1, x.shape[-1])[None, :]
        x[:, 0] += torch.tensor(rng.uniform(-0.08, 0.08, B), dtype=torch.float32)[:, None] * ramp
        x[:, 0] += torch.randn_like(x[:, 0]) * 0.04
        x[:, 2] *= torch.tensor(rng.uniform(0.8, 1.25, B), dtype=torch.float32)[:, None]
        drop = (torch.rand(B, x.shape[-1]) < 0.05)
        x[:, 1][drop] = 0.0
    return ev, ctx

def encode(vals):
    classes = sorted(set(vals), key=str)
    idx = {c: i for i, c in enumerate(classes)}
    return np.array([idx[v] for v in vals]), classes

def main():
    wd = sys.argv[1] if len(sys.argv) > 1 else '.'
    epochs = int(sys.argv[sys.argv.index('--epochs') + 1]) if '--epochs' in sys.argv else 350
    out_dir = sys.argv[sys.argv.index('--models-out') + 1] if '--models-out' in sys.argv else os.path.join(wd, 'models')
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(0)
    rng = np.random.default_rng(0)

    rows = [json.loads(l) for l in open(os.path.join(wd, 'events.jsonl'))]
    st = [r for r in rows if r['event_kind'] == 'structural']
    y_glyph, cls_glyph = encode([r['glyph'] for r in st])
    y_mv, cls_mv = encode([0 if r['mv_from_prev_claimed'] is None
                           else int(np.clip(r['mv_from_prev_claimed'], -3, 3)) for r in st])
    y_beats, cls_beats = encode([min(max(r['beats'], 0.5), 3.0) for r in st])
    y_comp, cls_comp = encode(['single' if r['n_subs'] == 1 else f"of2.{r['sub']}" for r in st])
    groups = np.array([r['line'] for r in st])

    ev0, ctx0 = build_tensors(wd, st)
    sc0, norm = scalars(st)
    w_glyph = torch.tensor(1.0 / np.sqrt(np.bincount(y_glyph, minlength=len(cls_glyph)) + 1),
                           dtype=torch.float32).to(dev)

    def fit(tr_idx, seed):
        torch.manual_seed(seed)
        net = Net(sc0.shape[1], len(cls_glyph), len(cls_mv), len(cls_beats), len(cls_comp)).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
        yt = {k: torch.tensor(v[tr_idx]).to(dev) for k, v in
              dict(g=y_glyph, m=y_mv, b=y_beats, c=y_comp).items()}
        r_local = np.random.default_rng(seed)
        for ep in range(epochs):
            net.train()
            # fresh boundary-jittered tensors every 40 epochs
            if ep % 40 == 0:
                evj, ctxj = build_tensors(wd, [st[i] for i in tr_idx],
                                          jitter=0.03, rng=r_local)
            ev_a, ctx_a = augment(evj.clone(), ctxj.clone(), r_local)
            lo_g, lo_m, lo_b, lo_c = net(ev_a.to(dev), ctx_a.to(dev), sc0[tr_idx].to(dev))
            loss = (F.cross_entropy(lo_g, yt['g'], weight=w_glyph)
                    + 0.5 * F.cross_entropy(lo_m, yt['m'])
                    + 0.3 * F.cross_entropy(lo_b, yt['b'])
                    + 0.3 * F.cross_entropy(lo_c, yt['c']))
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        return net

    def predict(net, idx):
        net.eval()
        with torch.no_grad():
            lo = net(ev0[idx].to(dev), ctx0[idx].to(dev), sc0[idx].to(dev))
        return [l.argmax(1).cpu().numpy() for l in lo]

    oof = {k: np.zeros(len(st), dtype=int) for k in 'gmbc'}
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=6).split(sc0, y_glyph, groups)):
        net = fit(tr, seed=fold)
        pg, pm, pb, pc = predict(net, te)
        oof['g'][te], oof['m'][te], oof['b'][te], oof['c'][te] = pg, pm, pb, pc
        print(f"fold {fold}: glyph acc {(pg == y_glyph[te]).mean():.3f} (n={len(te)})")

    res = [report('CNN glyph', [cls_glyph[i] for i in y_glyph], [cls_glyph[i] for i in oof['g']]),
           report('CNN movement (aux)', [cls_mv[i] for i in y_mv], [cls_mv[i] for i in oof['m']]),
           report('CNN beats (aux)', [cls_beats[i] for i in y_beats], [cls_beats[i] for i in oof['b']]),
           report('CNN compound (aux)', [cls_comp[i] for i in y_comp], [cls_comp[i] for i in oof['c']])]

    from collections import Counter
    conf = Counter((cls_glyph[t], cls_glyph[p]) for t, p in zip(y_glyph, oof['g']) if t != p)
    print('\ntop confusions (true -> predicted):')
    for (t, p), n in conf.most_common(10):
        print(f'  {n:3d}  {t:28s} -> {p}')

    os.makedirs(out_dir, exist_ok=True)
    net = fit(np.arange(len(st)), seed=99)
    torch.save({'state': net.state_dict(), 'classes': {'glyph': cls_glyph,
               'mv': cls_mv, 'beats': cls_beats, 'comp': cls_comp},
               'scalar_norm': [norm[0].tolist(), norm[1].tolist()],
               'features': FEATS}, os.path.join(out_dir, 'mcr_cnn.pt'))
    json.dump(res, open(os.path.join(out_dir, 'report_cnn.json'), 'w'), indent=1)
    print(f"\nsaved -> {out_dir}/mcr_cnn.pt")

if __name__ == '__main__':
    main()
