#!/usr/bin/env python3
"""tape_lane.py -- sliding-window lane classifier over whole tapes.

Classes: 0 speech/other, 1 parallagi, 2 melos.  Training labels come from the
chanter's cut spans (cuts_<wd>.json): inside a span the lane is the label,
outside any span on a FULLY-CUT tape the audio is speech/talk/other by
omission.  Windows are ~4 s of log-mel; the label is the majority frame label
with a purity gate, so windows straddling a boundary are simply not trained on.

Held out BY TAPE: one singer, so a random split would leak the voice and the
room.  Three folds (grave-orthros, mode1, mode2), each trained on the other
two.  A final model trained on all three tapes is what propose_cuts.py uses on
un-cut tapes.

Models are written as NEW files under /mnt/data/chant-corpus/models/
(tape_lane_heldout_<wd>.pt, tape_lane_all.pt); existing files are never
overwritten unless --force.
"""
import argparse, hashlib, json, os, subprocess, sys
import numpy as np
import torch
import torch.nn as nn

SR, HOP, NMEL = 22050, 512, 64
FPS = SR / HOP                       # 43.07 frames/s
WIN = 344                            # ~8.0 s
CLS = ['speech', 'parallagi', 'melos']
TEXTS = '/mnt/data/chant-corpus/texts'
MODELS = '/mnt/data/chant-corpus/models'
CACHE = os.environ.get('TAPE_LANE_CACHE',
    '/tmp/claude-1000/-mnt-data-code-byzorgan-web/1660574c-a353-4fce-87dd-1d42ff5a83ac/scratchpad/melcache')

FOLDS = ['grave-orthros', 'mode1', 'mode2']


def tape_for(wd):
    r = json.load(open(f'{TEXTS}/recut_{wd}.json'))
    tapes = {row['tape'] for row in r}
    assert len(tapes) == 1, (wd, tapes)
    return tapes.pop()


def audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, timeout=1800).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def mel(path):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(path.encode()).hexdigest()[:16]
    fn = f'{CACHE}/{key}.npy'
    if os.path.exists(fn):
        return np.load(fn)
    import librosa
    y = audio(path)
    m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=2048, hop_length=HOP,
                                       n_mels=NMEL, fmin=60, fmax=6000)
    x = librosa.power_to_db(m, ref=np.max)
    x = ((x - x.mean()) / (x.std() + 1e-6)).astype(np.float32)
    np.save(fn, x)
    return x


def lane_of(c):
    return c.get('lane') or ('parallagi' if c['hymn'].endswith('#par') else 'melos')


def frame_labels(wd, T):
    """Per-frame labels; 255 = ignore (conflicting overlap)."""
    d = json.load(open(f'{TEXTS}/cuts_{wd}.json'))
    lab = np.zeros(T, dtype=np.uint8)
    for c in d['cuts']:
        li = 1 if lane_of(c) == 'parallagi' else 2
        a, b = int(c['t0'] * FPS), min(T, int(c['t1'] * FPS))
        seg = lab[a:b]
        conflict = (seg != 0) & (seg != li) & (seg != 255)
        seg[:] = li
        seg[conflict] = 255
        for iv in c.get('skips') or []:
            lab[int(iv[0] * FPS):int(iv[1] * FPS)] = 0
    return lab


def windows(lab, stride, purity=0.9):
    """(start, label) pairs for training/val."""
    out = []
    for s in range(0, len(lab) - WIN, stride):
        w = lab[s:s + WIN]
        w = w[w != 255]
        if len(w) < 0.8 * WIN:
            continue
        cnt = np.bincount(w, minlength=3)
        li = int(cnt.argmax())
        if cnt[li] / len(w) < purity:
            continue
        out.append((s, li))
    return out


class Net(nn.Module):
    def __init__(self, nmel=NMEL, ch=128, ncls=3):
        super().__init__()
        L, c = [], nmel
        for _ in range(4):
            L += [nn.Conv1d(c, ch, 5, padding=2), nn.GELU(),
                  nn.GroupNorm(1, ch), nn.MaxPool1d(2)]
            c = ch
        self.conv = nn.Sequential(*L)
        self.head = nn.Linear(2 * ch, ncls)

    def forward(self, x):                       # [B, NMEL, T]
        h = self.conv(x)                        # [B, ch, T/16]
        h = torch.cat([h.mean(-1), h.amax(-1)], -1)
        return self.head(h)


def cmvn(xs):
    """Per-window, per-mel-bin normalisation: strips the tape's channel
    fingerprint so the classifier has to hear content, not the recorder."""
    m = xs.mean(axis=-1, keepdims=True)
    v = xs.std(axis=-1, keepdims=True) + 1e-5
    return (xs - m) / v


def specaug(x, rng):
    B, F, T = x.shape
    for b in range(B):
        for _ in range(2):
            f0 = rng.integers(0, F - 8); x[b, f0:f0 + rng.integers(1, 9)] = 0
            t0 = rng.integers(0, T - 48); x[b, :, t0:t0 + rng.integers(1, 49)] = 0
    return x


def batches(M, wins, idxs, bs, dev, rng=None):
    for i in range(0, len(idxs), bs):
        ix = idxs[i:i + bs]
        xs = cmvn(np.stack([M[wins[j][2]][:, wins[j][0]:wins[j][0] + WIN]
                            for j in ix]))
        if rng is not None:
            xs = specaug(xs, rng)
        ys = np.array([wins[j][1] for j in ix])
        yield (torch.from_numpy(xs).to(dev), torch.from_numpy(ys).to(dev))


def run_fold(mels, labs, train_wds, test_wd, epochs, dev, seed=0):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    tr = [(s, l, wd) for wd in train_wds for s, l in windows(labs[wd], 21)]
    te = [(s, l, wd) for wd in ([test_wd] if test_wd else [])
          for s, l in windows(labs[wd], 43)]
    cnt = np.bincount([w[1] for w in tr], minlength=3)
    print(f'  train windows {len(tr)} (spe/par/mel {cnt.tolist()}), test {len(te)}')
    net = Net().to(dev)
    wt = torch.tensor((cnt.sum() / np.maximum(cnt, 1)) ** 0.5,
                      dtype=torch.float32, device=dev)
    lossf = nn.CrossEntropyLoss(weight=wt)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    for ep in range(epochs):
        net.train()
        idxs = rng.permutation(len(tr))
        tot = n = 0
        for x, y in batches(mels, tr, idxs, 128, dev, rng):
            x = x + 0.1 * torch.randn_like(x)        # light noise aug
            opt.zero_grad()
            loss = lossf(net(x), y)
            loss.backward(); opt.step()
            tot += loss.item() * len(y); n += len(y)
        msg = f'  ep {ep+1:02d} loss {tot/n:.4f}'
        if te and (ep + 1) % 5 == 0 or ep == epochs - 1:
            msg += '  ' + evaluate(net, mels, te, dev)
        print(msg, flush=True)
    return net, (evaluate(net, mels, te, dev, conf=True) if te else '')


def evaluate(net, mels, te, dev, conf=False):
    net.eval()
    C = np.zeros((3, 3), dtype=int)
    with torch.no_grad():
        for x, y in batches(mels, te, np.arange(len(te)), 256, dev):
            p = net(x).argmax(-1).cpu().numpy()
            for a, b in zip(y.cpu().numpy(), p):
                C[a, b] += 1
    acc = C.diagonal().sum() / max(1, C.sum())
    per = [C[i, i] / max(1, C[i].sum()) for i in range(3)]
    s = ('acc %.3f  spe %.3f par %.3f mel %.3f' % (acc, *per))
    if conf:
        s += '\n  confusion (rows=true spe/par/mel):\n' + str(C)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=20)
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--final-only', action='store_true')
    a = ap.parse_args()
    dev = a.device if (a.device == 'cpu' or torch.cuda.is_available()) else 'cpu'
    print('device', dev)
    mels, labs = {}, {}
    for wd in FOLDS:
        tape = tape_for(wd)
        mels[wd] = mel(tape)
        labs[wd] = frame_labels(wd, mels[wd].shape[1])
        c = np.bincount(labs[wd][labs[wd] != 255], minlength=3)
        print(f'{wd}: {mels[wd].shape[1]} frames  spe/par/mel '
              f'{(c/FPS/60).round(1).tolist()} min')
    if not a.final_only:
        for wd in FOLDS:
            out = f'{MODELS}/tape_lane_heldout_{wd}.pt'
            if os.path.exists(out) and not a.force:
                print(f'fold {wd}: {out} exists, skip'); continue
            print(f'== fold: held out {wd}')
            tr = [w for w in FOLDS if w != wd]
            net, rep = run_fold(mels, labs, tr, wd, a.epochs, dev)
            print(rep)
            torch.save({'state': net.state_dict(), 'cfg': dict(
                sr=SR, hop=HOP, nmel=NMEL, win=WIN, cls=CLS,
                heldout=wd, train=tr)}, out)
            print('saved', out)
    out = f'{MODELS}/tape_lane_all.pt'
    if os.path.exists(out) and not a.force:
        print(f'{out} exists, skip')
    else:
        print('== final: all three tapes')
        net, _ = run_fold(mels, labs, FOLDS, None, a.epochs, dev)
        torch.save({'state': net.state_dict(), 'cfg': dict(
            sr=SR, hop=HOP, nmel=NMEL, win=WIN, cls=CLS,
            heldout=None, train=FOLDS)}, out)
        print('saved', out)


if __name__ == '__main__':
    main()
