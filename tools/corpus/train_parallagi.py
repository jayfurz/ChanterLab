#!/usr/bin/env python3
"""Train an 8-way parallagi degree-name classifier from parallagi_dataset.py
outputs.

Input:  one or more dataset dirs (each holding events.jsonl + summary.json,
        summary["wav"] pointing at the mono 16k wav).
Feature: 64-mel x 96-frame log-mel patch @10 ms hop, centered on each event.
Model:  small CNN, class-weighted cross-entropy, grouped train/val split by
        recording (falls back to a time split when only one recording).

Saves <out>/parallagi_cnn<tag>.pt and <out>/parallagi_cnn<tag>_report.json.

Usage:
  python3 train_parallagi.py DATASET_DIR [DATASET_DIR ...] \
      [--epochs 30] [--device cpu] [--out /mnt/data/chant-corpus/models]
NOTE: default device is cpu on purpose (GPUs are reserved for whisper jobs).
"""
import argparse
import json
import math
import random
import wave
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

CLASSES = ["ni", "pa", "vou", "ga", "di", "ke", "zo", "ne"]
N_MELS, N_FRAMES, HOP_S = 64, 96, 0.01
MEL_CFG = {"n_mels": N_MELS, "n_frames": N_FRAMES, "hop_s": HOP_S,
           "n_fft": 1024, "fmin": 60.0, "fmax": 7800.0, "classes": CLASSES}


# --------------------------------------------------------------- features ---
def load_wav(path):
    w = wave.open(str(path), "rb")
    sr = w.getframerate()
    assert w.getsampwidth() == 2 and w.getnchannels() == 1, path
    x = np.frombuffer(w.readframes(w.getnframes()),
                      dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    return x, sr


def hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m, dtype=np.float64) / 2595.0) - 1.0)


def mel_filterbank(sr, n_fft, n_mels, fmin, fmax):
    fmax = min(fmax, sr / 2)
    pts = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        for k in range(a, min(b, fb.shape[1])):
            if b > a:
                fb[m - 1, k] = (k - a) / (b - a)
        for k in range(b, min(c, fb.shape[1])):
            if c > b:
                fb[m - 1, k] = (c - k) / (c - b)
    return torch.from_numpy(fb)


def logmel(x, sr):
    """Full-recording log-mel, frames every 10 ms. (n_mels, n_frames)."""
    n_fft = MEL_CFG["n_fft"]
    hop = int(round(sr * HOP_S))
    xt = torch.from_numpy(x)
    spec = torch.stft(xt, n_fft=n_fft, hop_length=hop,
                      window=torch.hann_window(n_fft), center=True,
                      return_complex=True).abs() ** 2
    fb = mel_filterbank(sr, n_fft, N_MELS, MEL_CFG["fmin"], MEL_CFG["fmax"])
    return torch.log(fb @ spec + 1e-8)  # (n_mels, T)


def patch(mel, t_center):
    """96-frame patch centered at t_center, edge-padded, per-patch CMVN."""
    c = int(round(t_center / HOP_S))
    lo = c - N_FRAMES // 2
    idx = np.clip(np.arange(lo, lo + N_FRAMES), 0, mel.shape[1] - 1)
    p = mel[:, idx].clone()
    return (p - p.mean()) / (p.std() + 1e-5)


# ------------------------------------------------------------------ model ---
class ParallagiCNN(nn.Module):
    def __init__(self, n_classes=len(CLASSES)):
        super().__init__()
        def blk(ci, co):
            return nn.Sequential(nn.Conv2d(ci, co, 3, padding=1),
                                 nn.BatchNorm2d(co), nn.ReLU(),
                                 nn.MaxPool2d(2))
        self.net = nn.Sequential(blk(1, 16), blk(16, 32), blk(32, 64),
                                 nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(),
                                 nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                                 nn.Dropout(0.3), nn.Linear(64, n_classes))

    def forward(self, x):
        return self.net(x)


# ------------------------------------------------------------------- data ---
def load_datasets(dirs):
    """-> X (N,1,64,96) float32 tensor, y (N,), groups (N,) recording ids."""
    X, y, groups = [], [], []
    for d in dirs:
        d = Path(d)
        summ = json.load(open(d / "summary.json"))
        rec = summ.get("recording", d.name)
        x, sr = load_wav(summ["wav"])
        mel = logmel(x, sr)
        for line in open(d / "events.jsonl", encoding="utf-8"):
            e = json.loads(line)
            if e["syllable"] not in CLASSES:
                continue
            X.append(patch(mel, 0.5 * (e["t0"] + e["t1"])))
            y.append(CLASSES.index(e["syllable"]))
            groups.append(rec)
    return torch.stack(X).unsqueeze(1), torch.tensor(y), groups


def grouped_split(y, groups, val_frac, seed):
    uniq = sorted(set(groups))
    rng = random.Random(seed)
    if len(uniq) >= 2:
        rng.shuffle(uniq)
        n_val = max(1, min(len(uniq) - 1, math.ceil(val_frac * len(uniq))))
        val_groups = set(uniq[:n_val])
        val = np.array([g in val_groups for g in groups])
        mode = f"grouped ({len(uniq)} recordings, {n_val} held out)"
    else:  # single recording: last val_frac of events by index (time order)
        n = len(groups)
        val = np.arange(n) >= int(n * (1 - val_frac))
        mode = "time-split fallback (single recording)"
    return ~val, val, mode


# ------------------------------------------------------------------ train ---
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", nargs="+", help="dataset dirs from parallagi_dataset.py")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu",
                    help="cpu by default; GPUs are reserved for whisper")
    ap.add_argument("--out", default="/mnt/data/chant-corpus/models")
    ap.add_argument("--tag", default="", help="suffix for output filenames")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    dev = torch.device(args.device)

    X, y, groups = load_datasets(args.data)
    tr, va, split_mode = grouped_split(y, groups, args.val_frac, args.seed)
    Xtr, ytr, Xva, yva = X[tr], y[tr], X[va], y[va]

    cnt = torch.bincount(ytr, minlength=len(CLASSES)).float()
    w = torch.where(cnt > 0, cnt.sum() / (len(CLASSES) * cnt.clamp(min=1)),
                    torch.zeros_like(cnt))
    model = ParallagiCNN().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    lossf = nn.CrossEntropyLoss(weight=w.to(dev))

    def augment(x):
        """SpecAugment-style: noise + time/frequency masking + gain jitter.
        (Formant-preserving PSOLA pitch-shift augmentation is the planned
        next tier — these are the transforms safe for vowel identity.)"""
        x = x + torch.randn_like(x) * 0.05
        x = x + torch.randn(x.shape[0], 1, 1, 1) * 0.15        # gain (log-mel)
        B, _, F, T = x.shape
        for _ in range(2):
            f0s = torch.randint(0, F - 8, (B,))
            w = torch.randint(2, 8, (B,))
            for bi in range(B):
                x[bi, :, f0s[bi]:f0s[bi] + w[bi], :] = 0
        t0s = torch.randint(0, max(T - 12, 1), (B,))
        wt = torch.randint(2, 12, (B,))
        for bi in range(B):
            x[bi, :, :, t0s[bi]:t0s[bi] + wt[bi]] = 0
        return x

    best = {"val_acc": -1.0}
    for ep in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(len(ytr))
        tl = 0.0
        for i in range(0, len(perm), args.batch):
            b = perm[i:i + args.batch]
            opt.zero_grad()
            loss = lossf(model(augment(Xtr[b].clone()).to(dev)), ytr[b].to(dev))
            loss.backward()
            opt.step()
            tl += loss.item() * len(b)
        model.eval()
        with torch.no_grad():
            preds = []
            for i in range(0, len(yva), 256):
                preds.append(model(Xva[i:i + 256].to(dev)).argmax(1).cpu())
            pv = torch.cat(preds) if preds else torch.empty(0, dtype=torch.long)
        acc = (pv == yva).float().mean().item() if len(yva) else float("nan")
        print(f"ep {ep:3d} loss {tl / max(1, len(ytr)):.4f} val_acc {acc:.3f}")
        if len(yva) and acc > best["val_acc"]:
            conf = np.zeros((len(CLASSES), len(CLASSES)), dtype=int)
            for t, p in zip(yva.tolist(), pv.tolist()):
                conf[t][p] += 1
            per_cls = {CLASSES[k]: round(conf[k][k] / max(1, conf[k].sum()), 3)
                       for k in range(len(CLASSES))}
            best = {"val_acc": acc, "epoch": ep, "confusion": conf.tolist(),
                    "per_class_recall": per_cls,
                    "state": {k: v.cpu().clone()
                              for k, v in model.state_dict().items()}}

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    mpath = outdir / f"parallagi_cnn{tag}.pt"
    rpath = outdir / f"parallagi_cnn{tag}_report.json"
    torch.save({"state_dict": best.get("state", model.state_dict()),
                "classes": CLASSES, "mel_cfg": MEL_CFG}, mpath)
    report = {
        "datasets": [str(Path(d).resolve()) for d in args.data],
        "n_events": int(len(y)), "n_train": int(tr.sum()),
        "n_val": int(va.sum()), "split": split_mode,
        "class_counts": {CLASSES[k]: int((y == k).sum())
                         for k in range(len(CLASSES))},
        "class_weights": [round(float(x), 3) for x in w],
        "epochs": args.epochs, "device": args.device,
        "best_val_acc": round(best["val_acc"], 4),
        "best_epoch": best.get("epoch"),
        "per_class_recall": best.get("per_class_recall"),
        "confusion_rows_true_cols_pred": best.get("confusion"),
        "model": str(mpath),
    }
    json.dump(report, open(rpath, "w"), indent=2)
    print(json.dumps({k: report[k] for k in
                      ("n_events", "n_train", "n_val", "split",
                       "best_val_acc", "model")}))


if __name__ == "__main__":
    main()
