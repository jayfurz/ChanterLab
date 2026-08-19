#!/usr/bin/env python3
"""Domain-adapt the arc-scorer on SILVER claims from the DTW hymn alignments
(0.87 movement agreement -> usable supervision), with hymn-level holdout.

For each hymn: silver claims = melos_<name>/aligned.json (unit j <-> raw event)
remapped onto the cleaned stream of melos_<name>/arc/. Arcs from consecutive
claims train the same Bag-of-GBMs as train_aligner; evaluation decodes
held-out hymns with the new model via eval_arc's metric.

Usage: train_arc_silver.py <wd> --train h1 h2 ... --out model.joblib
"""
import json, os, sys
import numpy as np
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcr'))
import train_aligner as TA

def silver_gold(wd, name):
    mdir = os.path.join(wd, 'melos_' + name)
    arc = os.path.join(mdir, 'arc')
    aligned = json.load(open(os.path.join(mdir, 'aligned.json')))
    vn_clean = json.load(open(os.path.join(arc, 'voice_notes3.json')))
    c_t0 = [v[0] for v in vn_clean]
    def remap(t0):
        k = 0
        for i, t in enumerate(c_t0):
            if t <= t0 + 1e-6:
                k = i
            else:
                break
        return k
    gold, seen = [], set()
    for a in aligned:
        k = remap(a['t0'])
        if k in seen:
            continue
        seen.add(k)
        gold.append((k, a['unit']))
    gold.sort(key=lambda p: p[1])
    # enforce monotonicity in k
    out, last = [], -1
    for k, s in gold:
        if k > last:
            out.append((k, s))
            last = k
    return arc, out

def main():
    wd = sys.argv[1]
    names = sys.argv[sys.argv.index('--train') + 1:
                     sys.argv.index('--out') if '--out' in sys.argv else None]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv \
        else os.path.join(wd, 'arc_scorer.joblib')
    Xs, ys, gs = [], [], []
    for hi, name in enumerate(names):
        wdi, name = name.split(':', 1) if ':' in name else (wd, name)
        arc, gold = silver_gold(wdi, name)
        P = TA.build_piece(arc, use_word=False)
        if len(gold) < 10:
            print(f"{name}: too few silver claims ({len(gold)}), skipped")
            continue
        X, y, grp = TA.training_arcs(P, gold)
        Xs.append(X)
        ys.append(y)
        gs.append(grp + hi * 1000000)
        print(f"{name}: {len(gold)} silver claims -> {len(y)} arcs "
              f"({int(y.sum())} pos)")
    X = np.vstack(Xs)
    y = np.concatenate(ys)
    rng = np.random.default_rng(0)
    models = []
    for b in range(7):
        idx = rng.choice(len(y), len(y), replace=True) if b else np.arange(len(y))
        m = TA.HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
            min_samples_leaf=10, l2_regularization=2.0, class_weight='balanced')
        m.fit(X[idx], y[idx])
        models.append(m)
    joblib.dump(TA.Bag(models), out)
    print(f"trained on {len(y)} arcs ({int(y.sum())} pos) from "
          f"{len(Xs)} hymns -> {out}")

if __name__ == '__main__':
    main()
