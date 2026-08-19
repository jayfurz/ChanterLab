#!/usr/bin/env python3
"""Posterior confidence for hymn DTW alignments: forward-backward over the
same banded lattice (costs as -log potentials) -> per-match posteriors.
Confidence-gated agreement is the honest 'accuracy on what the aligner
trusts' metric (eothinon precedent).

Usage: dtw_conf.py <mode-workdir> <hymn> [...] -> melos_<h>/aligned_conf.json
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hymn_align as HA
BETA = float(os.environ.get('DTW_BETA', '3.0'))
from hymn_align import iv_of, load_units_h, LADDERS, CPM

def lattice_terms(units, deg_obs, iv, start, times, spb, drone_c):
    N, K = len(units), len(deg_obs)
    exp = np.zeros(N + 1)
    for j, u in enumerate(units):
        exp[j + 1] = exp[j] + iv_of(iv, u)
    deg = np.asarray(deg_obs, dtype=float)
    node = HA.W_ABS * np.minimum(np.abs(deg[None, :] - (start + exp[1:])[:, None]),
                                 HA.ABS_CAP)
    for j, u in enumerate(units):
        md = u.get('mart_deg')
        if md is not None:
            node[j] += HA.W_MART * np.min(np.abs(
                deg[None, :] - (md + 7 * np.arange(-1, 2))[:, None]), axis=0)
    dd = {o: deg[o:] - deg[:-o] for o in range(1, HA.MAX_DE + 1)}
    t = np.asarray(times, dtype=float)
    dt = {o: np.maximum(t[o:] - t[:-o], 0.02) for o in range(1, HA.MAX_DE + 1)}
    beats = np.array(HA.beats_seq(units))
    CB = np.concatenate([[0.0], np.cumsum(beats)])
    fee = np.where(np.abs(np.asarray(drone_c[1]) - drone_c[0]) <= 45.0, 0.05,
                   HA.SKIP_E) if drone_c is not None else np.full(K, HA.SKIP_E)
    FEE = np.concatenate([[0.0], np.cumsum(fee)])
    return exp, dd, dt, CB, FEE, node

def trans_cost(exp, dd, dt, CB, FEE, spb, j2, j, o, K):
    ce = exp[j + 1] - exp[j2 + 1]
    c = (HA.W_MV * np.minimum(np.abs(dd[o] - ce), HA.MV_CAP)
         + HA.SKIP_U * (j - j2 - 1))
    B = max(CB[j + 1] - CB[j2 + 1], 0.25)
    c = c + HA.W_DUR * np.minimum(np.abs(np.log(dt[o] / (B * spb))), HA.DUR_CAP)
    if o > 1:
        c = c + (FEE[o:K] - FEE[1:K - o + 1])
    return c            # length K - o, index k = o..K-1

def marginals(units, deg_obs, iv, start, times, spb, drone_c):
    N, K = len(units), len(deg_obs)
    exp, dd, dt, CB, FEE, node = lattice_terms(units, deg_obs, iv, start,
                                               times, spb, drone_c)
    NEG = -1e18
    A = np.full((N, K), NEG)
    k0 = min(8, K)
    A[0, :k0] = -BETA * (0.3 * np.arange(k0) + node[0, :k0])
    for j in range(1, N):
        acc = np.full(K, NEG)
        for j2 in range(max(0, j - HA.MAX_DU), j):
            for o in range(1, HA.MAX_DE + 1):
                if o >= K:
                    break
                w = A[j2, :K - o] - BETA * trans_cost(exp, dd, dt, CB, FEE, spb, j2, j, o, K)
                np.logaddexp(acc[o:], w, out=acc[o:])
        A[j] = acc - BETA * node[j]
    end_fee = BETA * 0.3 * (K - 1 - np.arange(K))
    Z = float(np.logaddexp.reduce(A[N - 1] - end_fee))
    Bk = np.full((N, K), NEG)
    Bk[N - 1] = -end_fee
    for j2 in range(N - 2, -1, -1):
        acc = np.full(K, NEG)
        for j in range(j2 + 1, min(j2 + HA.MAX_DU + 1, N)):
            for o in range(1, HA.MAX_DE + 1):
                if o >= K:
                    break
                w = (Bk[j, o:] - BETA * node[j, o:]
                     - BETA * trans_cost(exp, dd, dt, CB, FEE, spb, j2, j, o, K))
                np.logaddexp(acc[:K - o], w, out=acc[:K - o])
        Bk[j2] = acc
    M = A + Bk - Z
    return np.exp(np.clip(M, -50, 0)), exp

def main():
    wd = sys.argv[1]
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    hymns = json.load(open(os.path.join(wd, 'hymns.json')))
    for name in sys.argv[2:]:
        h = next(x for x in hymns if x['name'] == name)
        mdir = os.path.join(wd, 'melos_' + name)
        summ = json.load(open(os.path.join(mdir, 'summary.json')))
        al = json.load(open(os.path.join(mdir, 'aligned.json')))
        vn = json.load(open(os.path.join(mdir, 'voice_notes.json')))
        units, _ = load_units_h(h)
        cents = np.array([v[2] for v in vn])
        pos = LADDERS[summ['genus']]
        ni = summ['ni_cents_rel55']
        lad = {d: ni + pos(d) * CPM for d in range(-8, 16)}
        deg_obs = [min(lad, key=lambda dd_: abs(lad[dd_] - c)) for c in cents]
        times = [v[0] for v in vn]
        beats_tot = sum(HA.beats_seq(units))
        spb = max((times[-1] - times[0]) / max(beats_tot, 1.0), 0.05)
        hist, edges = np.histogram(cents, bins=np.arange(cents.min(),
                                   cents.max() + 30, 30),
                                   weights=np.clip(np.diff([v[0] for v in vn] +
                                                           [vn[-1][1]]), 0, 3))
        drone = float(edges[np.argmax(hist)] + 15)
        M, exp = marginals(units, deg_obs, iv, summ['start'], times, spb,
                           (drone, cents))
        ev_by_t0 = {round(v[0], 3): k for k, v in enumerate(vn)}
        out = []
        for a in al:
            k = ev_by_t0.get(round(a['t0'], 3))
            if k is None:
                continue
            a2 = dict(a)
            a2['conf'] = round(float(M[a['unit'], k]), 3)
            a2['degree_exp'] = int(round(summ['start'] + exp[a['unit'] + 1]))
            out.append(a2)
        json.dump(out, open(os.path.join(mdir, 'aligned_conf.json'), 'w'))
        confs = np.array([a['conf'] for a in out])
        print(f"{name:22s} matches {len(out):4d} conf median {np.median(confs):.2f} "
              f">=0.5: {(confs >= 0.5).sum()} >=0.8: {(confs >= 0.8).sum()}")

if __name__ == '__main__':
    main()
