#!/usr/bin/env python3
"""separate_pieces_nn.py -- the neural cutter, in separate_pieces.py's shoes.

separate_pieces.py cuts an hour tape at Whisper word gaps and calls each chunk
a piece. Against the chanter's 47 spans on the grave orthros tape that gave
4/25 melos at IoU >= 0.9 and a median IoU of 0.56 -- it splits inside hymns at
every long rest (PARALLAGI-PAIRING.md). Two learned pieces replace it:

    piece_bounds.py     start/end heads over 50 ms mel frames, +/- 25 s context
                        (self-fit on the grave tape: F1 0.989 both heads)
    lane_features.py    parallagi-or-melos from a length-invariant feature
                        vector (84.8% on a mode it never saw, vs 81.8% for the
                        0.43 deg/s rule)

The output is the SAME pieces.json that separate_pieces.py writes, so
slice_transcript.py and everything after it run unchanged. Each span also gets
the two signals a reviewer needs: the lane probability, and whether the cut
sits in silence (piece_bounds' abruptness report).

IT WRITES TO A PARALLEL ROOT. pieces/<tape>/ is referenced by hymns.json and
by every recut, and the chanter's own cuts live downstream of it. This writes
pieces_nn/<tape>/ and never touches pieces/. Adopting a tape's NN cut is a
separate, visible step (--adopt), which backs the old pieces.json up first.

THE PAIRING IS THE CHECKSUM. Every melos is preceded by its own parallagi, so
a tape whose lane sequence does not alternate has a wrong cut or a wrong lane
somewhere, and the report says which spans break it.

Usage:
  separate_pieces_nn.py --tape AUDIO [--cut] [--compare]
  separate_pieces_nn.py --all [--cut] [--compare]          # every tape in pieces/
  separate_pieces_nn.py --tape AUDIO --gold spans.json     # IoU against chanter spans
"""
import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'neural'))
import piece_bounds as PB                 # noqa: E402
import lane_features as LF                # noqa: E402

PIECES_ROOT = '/mnt/data/chant-corpus/pieces'
NN_ROOT = '/mnt/data/chant-corpus/pieces_nn'
TRANSCRIPTS = '/mnt/data/chant-corpus/transcripts'
MODELS = '/mnt/data/chant-corpus/models'
BOUNDS_PT = os.path.join(MODELS, 'piece_bounds_grave_e4000.pt')
LANE_JOBLIB = os.path.join(MODELS, 'lane_feat.joblib')
PAD = 0.35                                # separate_pieces' cut padding
SPEECH_MAX = 20.0                         # separate_pieces' speech_max_dur
MIN_SPAN = 4.0


def bounds(net, path, dev):
    """Spans from the two boundary heads, plus is-the-cut-in-silence."""
    y = PB.audio(path)
    X = torch.from_numpy(PB.features(y)).to(dev)
    T = X.shape[1]
    P = np.zeros((2, T), dtype=np.float32)
    W, OV = 6000, 500
    i = 0
    with torch.inference_mode():
        while i < T:
            j = min(T, i + W)
            p = torch.sigmoid(net(X[:, i:j].unsqueeze(0)))[0].cpu().numpy()
            a0 = i + (OV if i else 0); b0 = j - (OV if j < T else 0)
            P[:, a0:b0] = p[:, (a0 - i):(b0 - i)]
            if j >= T:
                break
            i = j - 2 * OV
    fs = PB.HOP / PB.SR
    ps = [f * fs for f in PB.pick(P[0])]
    pe = [f * fs for f in PB.pick(P[1])]
    # Pair each start with the LAST end before the next start. Greedy
    # first-end-after-start is wrong: one spurious start with no end of its
    # own steals the next span's end and shifts every span after it by one
    # (measured: 0/47 at IoU >= 0.9 on the gold tape, 47/47 after this fix).
    # A start with no end before the next start keeps its audio anyway: the
    # piece must end before the next one begins, so it ends there, less a
    # breath, and is flagged (boundary_in_silence is computed on the real
    # audio, so a wrong guess shows up as a rough edge).
    spans, guessed = [], []
    for i, st in enumerate(ps):
        nxt = ps[i + 1] if i + 1 < len(ps) else len(y) / PB.SR
        ends = [e for e in pe if st < e < nxt]
        spans.append([st, ends[-1] if ends else max(st + 1.0, nxt - 0.5)])
        guessed.append(not ends)
    w = int(0.05 * PB.SR)
    e = np.sqrt(np.convolve(y * y, np.ones(w) / w, 'same'))
    floor = float(np.percentile(e, 5))

    def outside(t, side, win=0.4):
        i0 = int(t * PB.SR); n0 = int(win * PB.SR)
        seg = e[max(0, i0 - n0):i0] if side == 's' else e[i0:i0 + n0]
        return float(np.median(seg)) if len(seg) > 10 else 0.0
    quiet = [outside(a, 's') <= 4 * floor and outside(b, 'e') <= 4 * floor and not g
             for (a, b), g in zip(spans, guessed)]
    return spans, quiet, len(y) / PB.SR


def lanes(clf, path, spans, dev):
    out = []
    for a, b in spans:
        v = LF.feat(LF.audio(path, a, b - a), dev)
        if v is None:
            out.append((None, 0.0)); continue
        p = float(clf.predict_proba(v[None, :])[0, 1])
        out.append((p, float(v[LF.NMOD + 4])))       # p(parallagi), deg/s
    return out


def load_words(tj):
    if not os.path.exists(tj):
        return []
    d = json.load(open(tj))
    return [w for s in d.get('segments', []) for w in s.get('words', [])]


def iou(a, b):
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return inter / max((a[1] - a[0]) + (b[1] - b[0]) - inter, 1e-6)


def run_tape(path, bnet, clf, dev, cut, compare, gold, outroot):
    stem = os.path.splitext(os.path.basename(path))[0]
    outdir = os.path.join(outroot, stem)
    os.makedirs(outdir, exist_ok=True)
    for f in glob.glob(os.path.join(outdir, '[0-9][0-9][0-9]_*.*')):
        os.remove(f)                    # a re-run must not leave stale pieces
    spans, quiet, dur = bounds(bnet, path, dev)
    lab = lanes(clf, path, spans, dev)
    words = load_words(os.path.join(TRANSCRIPTS, stem + '.json'))

    segs = []
    for (a, b), q, (p, rate) in zip(spans, quiet, lab):
        ws = [w for w in words if a <= w['start'] < b]
        if b - a < MIN_SPAN or p is None:
            kind = 'other'
        elif p >= 0.5:
            kind = 'parallagi'
        elif b - a < SPEECH_MAX and rate < 0.05 and p < 0.2:
            kind = 'speech'
        else:
            kind = 'melos'
        segs.append({'t0': round(a, 3), 't1': round(b, 3), 'kind': kind,
                     'head_text': ' '.join(w['word'].strip() for w in ws[:12]),
                     'n_words': len(ws), 'lex_frac': round(rate, 3),
                     'p_parallagi': (round(p, 3) if p is not None else None),
                     'boundary_in_silence': bool(q)})
    for i, s in enumerate(segs, 1):
        s['wav'] = '%03d_%s.wav' % (i, s['kind'])
        if cut:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(max(0.0, s['t0'] - PAD)),
                            '-to', str(min(dur, s['t1'] + PAD)), '-i', path,
                            '-ac', '1', '-ar', '44100', '-sample_fmt', 's16',
                            os.path.join(outdir, s['wav'])], check=True)

    # the checksum
    lane_seq = [s['kind'] for s in segs if s['kind'] in ('parallagi', 'melos')]
    npar = lane_seq.count('parallagi'); nmel = lane_seq.count('melos')
    breaks = [i for i in range(1, len(lane_seq)) if lane_seq[i] == lane_seq[i - 1]]
    rough = sum(1 for s in segs if not s['boundary_in_silence'])

    doc = {'audio': os.path.abspath(path), 'method': 'piece_bounds+lane_features',
           'models': {'bounds': BOUNDS_PT, 'lane': LANE_JOBLIB},
           'transcript': os.path.join(TRANSCRIPTS, stem + '.json'),
           'n_words': len(words), 'params': {'pad': PAD, 'speech_max_dur': SPEECH_MAX},
           'checksum': {'parallagi': npar, 'melos': nmel, 'alternation_breaks': len(breaks),
                        'boundaries_not_in_silence': rough},
           'segments': segs}
    json.dump(doc, open(os.path.join(outdir, 'pieces.json'), 'w'), ensure_ascii=False, indent=1)

    print('\n%s' % stem)
    print('  %.1f min -> %d spans: %d parallagi, %d melos, %d speech, %d other'
          % (dur / 60, len(segs), npar, nmel,
             sum(s['kind'] == 'speech' for s in segs), sum(s['kind'] == 'other' for s in segs)))
    print('  pairing checksum: %s; %d boundaries not in silence'
          % ('holds' if npar == nmel and not breaks else
              '%d alternation break(s), %d par vs %d mel' % (len(breaks), npar, nmel), rough))
    res = {'tape': stem, 'n': len(segs), 'par': npar, 'mel': nmel, 'breaks': len(breaks), 'rough': rough}

    if compare:
        old = os.path.join(PIECES_ROOT, stem, 'pieces.json')
        if os.path.exists(old):
            oseg = json.load(open(old))['segments']
            osp = [(s['t0'], s['t1']) for s in oseg if s['kind'] in ('parallagi', 'melos')]
            nsp = [(s['t0'], s['t1']) for s in segs if s['kind'] in ('parallagi', 'melos')]
            best = [max((iou(n, o) for o in osp), default=0) for n in nsp]
            opar = sum(s['kind'] == 'parallagi' for s in oseg); omel = sum(s['kind'] == 'melos' for s in oseg)
            print('  vs heuristic: %d chant pieces there, %d here; %d/%d NN spans match one '
                  'at IoU >= 0.9, median IoU %.2f; heuristic lanes %d par / %d mel'
                  % (len(osp), len(nsp), sum(b >= 0.9 for b in best), len(nsp),
                     float(np.median(best)) if best else 0, opar, omel))
            res['vs_heuristic'] = {'old_n': len(osp), 'match_090': sum(b >= 0.9 for b in best),
                                   'median_iou': float(np.median(best)) if best else 0}
    if gold:
        g = [s for s in json.load(open(gold))['spans']]
        gs = [(s['t0'], s['t1'], s.get('lane')) for s in g]
        hit = [max(((iou((s['t0'], s['t1']), (a, b)), l) for a, b, l in gs), default=(0, None)) for s in segs]
        n09 = sum(h[0] >= 0.9 for h in hit)
        miss = [(a, b) for a, b, _ in gs if max((iou((a, b), (s['t0'], s['t1'])) for s in segs), default=0) < 0.9]
        if miss:
            print('  gold spans without an NN match at 0.9: %s' % ', '.join('%.0f-%.0f' % m for m in miss))
        lane_ok = sum(1 for s, h in zip(segs, hit) if h[0] >= 0.5 and h[1] == s['kind'])
        chant = sum(1 for s in segs if s['kind'] in ('parallagi', 'melos'))
        print('  vs gold: %d chanter spans; %d/%d NN spans at IoU >= 0.9, median IoU %.3f; '
              'lane right on %d/%d matched chant spans'
              % (len(gs), n09, len(segs), float(np.median([h[0] for h in hit])), lane_ok, chant))
        res['vs_gold'] = {'gold_n': len(gs), 'iou_090': n09, 'lane_ok': lane_ok, 'chant': chant}
    print('  ->', os.path.join(outdir, 'pieces.json'))
    return res


def adopt(stem):
    """Make pieces/<stem> read the NN cut. Backs the old pieces.json up."""
    src = os.path.join(NN_ROOT, stem); dst = os.path.join(PIECES_ROOT, stem)
    assert os.path.exists(os.path.join(src, 'pieces.json')), 'run the cutter first'
    os.makedirs(dst, exist_ok=True)
    old = os.path.join(dst, 'pieces.json')
    if os.path.exists(old):
        os.replace(old, old + '.heuristic')
    for f in os.listdir(src):
        if f.endswith('.wav') or f == 'pieces.json':
            subprocess.run(['cp', '-p', os.path.join(src, f), os.path.join(dst, f)], check=True)
    print('adopted %s (old pieces.json -> pieces.json.heuristic; old NNN_*.wav left in place)' % stem)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--tape', action='append')
    ap.add_argument('--all', action='store_true', help='every tape that has pieces/<stem>/')
    ap.add_argument('--cut', action='store_true')
    ap.add_argument('--compare', action='store_true', help='against pieces/<stem>/pieces.json')
    ap.add_argument('--gold', help='chanter spans json (span_names_*.json) for one --tape')
    ap.add_argument('--out-root', default=NN_ROOT)
    ap.add_argument('--bounds', default=BOUNDS_PT)
    ap.add_argument('--lane', default=LANE_JOBLIB)
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--adopt', action='append', metavar='STEM',
                    help='copy pieces_nn/<stem> over pieces/<stem> (old pieces.json kept)')
    ap.add_argument('--summary', help='write one json with every tape\'s numbers')
    a = ap.parse_args()
    if a.adopt:
        for s in a.adopt:
            adopt(s)
        return 0
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    import joblib
    bnet = PB.Net().to(dev)
    bnet.load_state_dict(torch.load(a.bounds, map_location=dev)); bnet.eval()
    clf = joblib.load(a.lane)

    tapes = list(a.tape or [])
    if a.all:
        allraw = glob.glob('/mnt/data/chant-corpus/raw/vasilikos/**/*.*', recursive=True)
        by_stem = {os.path.splitext(os.path.basename(p))[0]: p for p in allraw}
        for d in sorted(os.listdir(PIECES_ROOT)):
            if d.startswith('_') or not glob.glob(os.path.join(PIECES_ROOT, d, '0*.json')):
                continue
            if d in by_stem:
                tapes.append(by_stem[d])
            else:
                print('no raw tape found for pieces/%s' % d)
    out = []
    for t in tapes:
        out.append(run_tape(t, bnet, clf, dev, a.cut, a.compare,
                            a.gold if len(tapes) == 1 else None, a.out_root))
    if a.summary:
        json.dump(out, open(a.summary, 'w'), indent=1, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
