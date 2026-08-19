#!/usr/bin/env python3
"""Genus-aware joint syllable-pitch decoder for parallagi recordings.

The two constraints that make parallagi self-labeling:
  * the ASR syllable IS the degree (δι is always δι), and
  * the degree has an exact pitch meaning under the mode's genus ladder
    (diatonic / soft chromatic / hard chromatic moria intervals).
A sequence-DTW aligns the ASR degree path to the note events where the match
cost punishes pitch-vs-syllable disagreement (ASR says δι but the pitch sits
on πα -> expensive -> the blip is skipped, not trusted). Ison-singer captures
(events at the persistent drone level) skip nearly free. Genus is chosen by
best fit across all three ladders and reported against the filename hint.

Usage: parallagi_align.py <recording-outdir> [--tracks SUBDIR]
  reads  tracks/voice_notes.json (+ whisper via events.jsonl's source or
         transcripts dir), writes events_full.jsonl + summary_full.json
"""
import json, os, sys
from collections import Counter
import numpy as np

DEG_ORDER = ['ni', 'pa', 'vou', 'ga', 'di', 'ke', 'zo']
DEGREE = {'ni': 0, 'pa': 1, 'vou': 2, 'ga': 3, 'di': 4, 'ke': 5, 'zo': 6, 'ne': 0}
CPM = 1200.0 / 72.0                       # cents per moria
# genus ladders. diatonic/hard: moria step ABOVE each degree ni..zo, octave-
# cyclic. Soft chromatic is NOT octave-periodic: it is the trochos (wheel) —
# the tetrachord+tone pattern 8-14-8-12 repeats every FIFTH (42 moria), so
# the step above degree d is [8,14,8,12][d mod 4] (ni->pa 8 low, ni'->pa' 12
# an octave up). In practice it rarely extends below ni (usually switches
# back to diatonic there); we keep the trochos both ways, low notes are rare.
GENUS_STEPS = {
    'diatonic':       [12, 10, 8, 12, 12, 10, 8],
    'soft_chromatic': 'trochos-8-14-8-12',
    'hard_chromatic': [4, 6, 20, 4, 12, 6, 20],   # ni-pa 4, pa-vou 6, vou-ga 20, ...
}
SOFT_CYCLE = [8, 14, 8, 12]
DRONE_TOL = 45.0
W_MV, MV_CAP = 1.0, 320.0                 # cents-domain movement cost
SKIP_ASR, SKIP_EV, SKIP_DRONE = 0.9, 0.55, 0.06
MAX_DA, MAX_DE = 4, 6

def ladder(genus):
    steps = GENUS_STEPS[genus]
    pos = {0: 0.0}
    if genus == 'soft_chromatic':
        for d in range(0, 40):
            pos[d + 1] = pos[d] + SOFT_CYCLE[d % 4]
        for d in range(0, -40, -1):
            pos[d - 1] = pos[d] - SOFT_CYCLE[(d - 1) % 4]
    else:
        for d in range(0, 40):
            pos[d + 1] = pos[d] + steps[d % 7]
        for d in range(0, -40, -1):
            pos[d - 1] = pos[d] - steps[(d - 1) % 7]
    return pos

def unfold(asr_degs):
    D = [asr_degs[0]]
    for d in asr_degs[1:]:
        s7 = (d - D[-1]) % 7
        D.append(D[-1] + (s7 if s7 <= 3 else s7 - 7))
    return D

def decode(cents, dur, D, genus, drone_c, exp_abs=None):
    lad = ladder(genus)
    N, K = len(D), len(cents)
    exp = (np.array([lad[d] * CPM for d in D]) if exp_abs is None
           else np.array([exp_abs[d] for d in D]))
    is_drone = np.abs(cents - drone_c) <= DRONE_TOL if drone_c is not None \
        else np.zeros(K, bool)
    skip_ev = np.where(is_drone, SKIP_DRONE, SKIP_EV)
    BIG = 1e18
    Dp = np.full((N, K), BIG)
    Pp = np.full((N, K, 2), -1, dtype=int)
    for k in range(min(10, K)):
        Dp[0, k] = float(skip_ev[:k].sum())
    for i in range(1, N):
        for k in range(1, K):
            b, ba = BIG, (-1, -1)
            for i2 in range(max(0, i - MAX_DA), i):
                for k2 in range(max(0, k - MAX_DE - 1), k):
                    if Dp[i2, k2] >= BIG:
                        continue
                    obs = cents[k] - cents[k2]
                    mv = min(abs(obs - (exp[i] - exp[i2])), MV_CAP) / 100.0
                    c = (Dp[i2, k2] + W_MV * mv + SKIP_ASR * (i - i2 - 1)
                         + float(skip_ev[k2 + 1:k].sum()))
                    if c < b:
                        b, ba = c, (i2, k2)
            Dp[i, k] = b
            Pp[i, k] = ba
    ends = [(Dp[N - 1, k] + float(skip_ev[k + 1:].sum()), k) for k in range(K)
            if Dp[N - 1, k] < BIG]
    if not ends:
        return None
    cost, k = min(ends)
    path, i = [], N - 1
    while i >= 0 and k >= 0:
        path.append((i, k))
        i, k = Pp[i, k]
    path.reverse()
    return cost / max(N, 1), path, lad, is_drone

def process(outdir, tracks='tracks'):
    name = os.path.basename(os.path.normpath(outdir))
    vn = json.load(open(os.path.join(outdir, tracks, 'voice_notes.json')))
    rows = [json.loads(l) for l in open(os.path.join(outdir, 'events.jsonl'))]
    asr = [DEGREE[r['syllable']] for r in sorted(rows, key=lambda r: r['t0'])
           if r['syllable'] in DEGREE]
    if len(asr) < 5:
        print(f"{name[:52]:52s} SKIPPED ({len(asr)} ASR syllables)")
        return
    cents = np.array([v[2] for v in vn])
    dur = np.array([v[1] - v[0] for v in vn])
    # drone: most time-weighted persistent level
    hist, edges = np.histogram(cents, bins=np.arange(cents.min(), cents.max() + 30, 30),
                               weights=np.clip(dur, 0, 3))
    drone_c = float(edges[np.argmax(hist)] + 15)
    D = unfold(asr)

    def run_genus(genus):
        """theory-initialized decode, then EM: refit per-degree centers
        empirically (clamped +-80c from theory) and re-decode"""
        got = decode(cents, dur, D, genus, drone_c)
        if not got:
            return None
        lad = ladder(genus)
        cost, path, lad, is_drone = got
        ni = float(np.median([cents[k] - lad[D[i]] * CPM for i, k in path]))
        theory_abs = {d: ni + m * CPM for d, m in lad.items()}
        exp_abs = dict(theory_abs)
        for _ in range(2):
            by_d = {}
            for i, k in path:
                by_d.setdefault(D[i], []).append(cents[k])
            for d, th in theory_abs.items():
                if d in by_d and len(by_d[d]) >= 2:
                    exp_abs[d] = float(np.clip(np.median(by_d[d]), th - 80, th + 80))
            got = decode(cents, dur, D, genus, drone_c, exp_abs=exp_abs)
            cost, path, lad, is_drone = got
        cost, path, lad, is_drone = got
        matched = {k: D[i] for i, k in path}
        resid = [abs(cents[k] - exp_abs[d]) for k, d in matched.items()]
        agree = float(np.mean([r < 70 for r in resid])) if resid else 0.0
        return agree, cost, path, exp_abs, is_drone, matched

    best = None
    for genus in GENUS_STEPS:
        got = run_genus(genus)
        if got and (best is None or got[0] > best[1][0]):
            best = (genus, got)
    genus, (agree, cost, path, lad_abs, is_drone, matched) = best
    ni = lad_abs[0] - ladder(genus)[0] * CPM
    out = []
    for k, v in enumerate(vn):
        if is_drone[k] and k not in matched:
            continue
        if k in matched:
            d, src = matched[k], 'asr+pitch'
        else:
            d = min(lad_abs, key=lambda dd: abs(lad_abs[dd] - v[2]))
            src = 'ladder'
            if abs(lad_abs[d] - v[2]) > 95:
                continue
        out.append({'t0': v[0], 't1': v[1], 'syllable': DEG_ORDER[d % 7],
                    'degree': d % 7, 'degree_abs': int(d), 'cents': v[2],
                    'source': src, 'margin_c': round(float(abs(lad_abs[d] - v[2])), 1)})
    with open(os.path.join(outdir, 'events_full.jsonl'), 'w') as f:
        for r in out:
            f.write(json.dumps(r) + '\n')
    summ = {'recording': name, 'genus': genus, 'mean_path_cost': round(cost, 2),
            'n_notes': len(vn), 'n_drone_skipped': int(is_drone.sum()),
            'n_matched': len(matched), 'n_labeled': len(out),
            'coverage_pct': round(100 * len(out) / max(len(vn), 1), 1),
            'match_agreement': round(agree, 2),
            'ni_cents_rel55': round(ni, 0),
            'ni_hz': round(55 * 2 ** (ni / 1200), 1),
            'per_syllable': dict(Counter(r['syllable'] for r in out))}
    json.dump(summ, open(os.path.join(outdir, 'summary_full.json'), 'w'), indent=1)
    print(f"{name[:52]:52s} {genus[:4]:4s} agree {agree:.2f} cov "
          f"{summ['coverage_pct']:5.1f}% ({len(out)}/{len(vn)}, drone-skip "
          f"{int(is_drone.sum())}) Ni {summ['ni_hz']}Hz")

if __name__ == '__main__':
    for d in sys.argv[1:]:
        if not d.startswith('--'):
            process(d)
