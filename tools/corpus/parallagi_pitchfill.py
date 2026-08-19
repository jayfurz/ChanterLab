#!/usr/bin/env python3
"""Densify a parallagi events.jsonl by pitch-class clustering + ASR voting.

Vasilikos chants parallagi precisely, so event pitches form crisp 1-D
clusters (the scale degrees). The ASR word labels are individually sloppy
(whisper timestamps drift on melisma), so instead of trusting each label:
  1. cluster all note-event pitches (split at gaps > GAP_C),
  2. each cluster's name = majority vote of the ASR labels inside it,
  3. voteless clusters get names by DEGREE ORDER interpolation between named
     neighbours (ni<pa<vou<ga<di<ke<zo<ni', octave-aware),
  4. every event is labeled by its cluster; vote purity + margins reported.

Usage: parallagi_pitchfill.py <recording-outdir> [...]
  reads  events.jsonl + tracks/voice_notes.json
  writes events_full.jsonl (source: cluster; vote_purity), summary_full.json
"""
import json, sys, os
from collections import Counter
import numpy as np

GAP_C = 62.0            # cents gap that separates pitch clusters
MIN_CLUSTER = 3         # min events to keep a cluster
DEG_ORDER = ['ni', 'pa', 'vou', 'ga', 'di', 'ke', 'zo']
DEGREE = {'ni': 0, 'pa': 1, 'vou': 2, 'ga': 3, 'di': 4, 'ke': 5, 'zo': 6, 'ne': 0}

def deg_index(s):        # 'ne' sung on the same degree it decorates -> treat as ni-family
    return DEGREE.get(s)

def process(outdir):
    name = os.path.basename(os.path.normpath(outdir))
    rows = [json.loads(l) for l in open(os.path.join(outdir, 'events.jsonl'))]
    vn = json.load(open(os.path.join(outdir, 'tracks', 'voice_notes.json')))
    cents = np.array([v[2] for v in vn])
    order = np.argsort(cents)
    # 1) 1-D clustering by gaps
    cl_id = np.zeros(len(vn), dtype=int)
    cid = 0
    for i, j in zip(order, order[1:]):
        if cents[j] - cents[i] > GAP_C:
            cid += 1
        cl_id[j] = cid
    cl_id[order[0]] = 0
    # re-walk to assign contiguously (first pass mislabels: redo cleanly)
    cid = 0
    prev = None
    for k in order:
        if prev is not None and cents[k] - cents[prev] > GAP_C:
            cid += 1
        cl_id[k] = cid
        prev = k
    n_cl = cid + 1
    centers = np.array([np.median(cents[cl_id == c]) for c in range(n_cl)])
    sizes = np.array([(cl_id == c).sum() for c in range(n_cl)])
    # 2) unfold the ASR syllable sequence into a RELATIVE degree path
    #    (nearest-octave: consecutive degrees move by the smallest wrap)
    asr = [deg_index(r['syllable']) for r in sorted(rows, key=lambda r: r['t0'])
           if r['syllable'] in DEGREE]
    D = [asr[0]] if asr else []
    for d in asr[1:]:
        step7 = (d - D[-1]) % 7
        D.append(D[-1] + (step7 if step7 <= 3 else step7 - 7))
    # 3) movement-DTW: events <-> ASR notes (whisper merges syllables -> event
    #    skips are cheap; ASR rarely inserts -> asr skips cost more)
    STEP = 165.0
    W_MV, SKIP_EV, SKIP_ASR, MAX_D = 1.0, 0.35, 0.9, 4
    N, K = len(D), len(vn)
    if N < 5:
        print(f"{name[:55]:55s} SKIPPED (only {N} ASR syllables)")
        return
    BIG = 1e18
    Dp = np.full((N, K), BIG)
    Pp = np.full((N, K, 2), -1, dtype=int)
    Dp[0, :min(8, K)] = 0.25 * np.arange(min(8, K))
    for i in range(1, N):
        for k in range(1, K):
            b, ba = BIG, (-1, -1)
            for i2 in range(max(0, i - MAX_D), i):
                for k2 in range(max(0, k - MAX_D - 1), k):
                    if Dp[i2, k2] >= BIG:
                        continue
                    obs = (cents[k] - cents[k2]) / STEP
                    c = (Dp[i2, k2] + W_MV * min(abs(obs - (D[i] - D[i2])), 3.0)
                         + SKIP_ASR * (i - i2 - 1) + SKIP_EV * (k - k2 - 1))
                    if c < b:
                        b, ba = c, (i2, k2)
            Dp[i, k] = b
            Pp[i, k] = ba
    ends = [(Dp[N - 1, k] + 0.25 * (K - 1 - k), k) for k in range(K)
            if Dp[N - 1, k] < BIG]
    _, k = min(ends)
    path, i = [], N - 1
    while i >= 0 and k >= 0:
        path.append((i, k))
        i, k = Pp[i, k]
    path.reverse()
    # 4) per-degree pitch centers from sequence-matched pairs -> label all
    by_deg = {}
    for i, k in path:
        by_deg.setdefault(D[i], []).append(cents[k])
    deg_center = {d: float(np.median(cs_)) for d, cs_ in by_deg.items() if len(cs_) >= 2}
    if not deg_center:
        print(f"{name[:55]:55s} SKIPPED (no stable degree centers)")
        return
    resid = [abs(cents[k] - deg_center[D[i]]) for i, k in path if D[i] in deg_center]
    seq_agree = float(np.mean([r < 70 for r in resid]))
    out = []
    for k, v in enumerate(vn):
        d, dc = min(deg_center.items(), key=lambda x: abs(x[1] - v[2]))
        if abs(dc - v[2]) > 110:
            continue
        out.append({'t0': v[0], 't1': v[1], 'syllable': DEG_ORDER[d % 7],
                    'degree': d % 7, 'degree_abs': int(d), 'cents': v[2],
                    'source': 'seqdtw', 'seq_agree': round(seq_agree, 2),
                    'margin_c': round(float(abs(dc - v[2])), 1)})
    centers_view = sorted(deg_center.items())
    cen_sorted = [c for _, c in centers_view]
    cs = list(range(len(centers_view)))
    names = {i: DEG_ORDER[d % 7] for i, (d, _) in enumerate(centers_view)}
    base = centers_view[0][0] % 7
    step_est = float(np.median(np.diff(cen_sorted))) if len(cen_sorted) > 1 else STEP
    with open(os.path.join(outdir, 'events_full.jsonl'), 'w') as f:
        for r in out:
            f.write(json.dumps(r) + '\n')
    summ = {'recording': name, 'n_notes': len(vn), 'n_labeled': len(out),
            'coverage_pct': round(100 * len(out) / max(len(vn), 1), 1),
            'n_clusters': int(n_cl), 'n_kept': len(cs),
            'base_degree': DEG_ORDER[base], 'seq_agreement': round(seq_agree, 3),
            'step_est_c': round(step_est, 1),
            'cluster_centers_c': [round(float(x), 0) for x in cen_sorted],
            'cluster_names': [names[c] for c in cs],
            'per_syllable': dict(Counter(r['syllable'] for r in out))}
    json.dump(summ, open(os.path.join(outdir, 'summary_full.json'), 'w'), indent=1)
    print(f"{name[:55]:55s} cov {summ['coverage_pct']:5.1f}% "
          f"({len(out)}/{len(vn)}) seq-agree {seq_agree:.2f} step {step_est:.0f}c")
    print(f"{'':55s} scale: " + ' '.join(
        f"{nm}@{int(c)}" for nm, c in zip(summ['cluster_names'],
                                          summ['cluster_centers_c'])))

if __name__ == '__main__':
    for d in sys.argv[1:]:
        process(d)
