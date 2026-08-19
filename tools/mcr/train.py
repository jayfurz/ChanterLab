#!/usr/bin/env python3
"""MCR glyph + melisma classifiers from audio-only event features (GBM lane).

Protocol: GroupKFold over score lines (a fold never trains on lines it tests),
pooled out-of-fold predictions for every metric. Tasks:

  A. glyph-flat   24-way glyph.sub directly
  B. factored     movement / beats-class / compound-position heads, composed
                  back to a glyph via the train-fold factor->glyph table
  C. ornament     structural vs sung-ornament event detector (melisma layer)

Baselines: majority class; interval-rule (rounded sung movement -> most common
train glyph at that movement) — the model must beat this to prove it hears
more than the interval.

Usage: train.py <events.jsonl> [--models-out DIR]
"""
import json, sys, os
from collections import Counter, defaultdict
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import f1_score, average_precision_score

FEATS = ['dur', 'log_dur', 'dur_rel', 'gap_before', 'gap_after', 'breath_before',
         'breath_after', 'since_breath', 'd_prev', 'd_prev2', 'd_prev_long',
         'd_next', 'ddeg_prev', 'ddeg_prev_long', 'ddeg_next', 'deg_off',
         'mid_frac', 'slope', 'resid', 'range', 'iqr', 'within', 'turns',
         'nan_frac', 'rms_mean', 'attack', 'tail', 'rms_prev_ratio',
         'prev_dur', 'next_dur']
DELTA_FEATS = ['d_prev', 'd_prev2', 'd_prev_long', 'd_next',
               'ddeg_prev', 'ddeg_prev_long', 'ddeg_next', 'deg_off', 'mid_frac']

CTX_FEATS = ['dur', 'dur_rel', 'gap_before', 'gap_after', 'd_prev', 'ddeg_prev',
             'within', 'rms_mean', 'nan_frac']
CTX = []      # neighbour-event feature stacking: hurt at n=255, off by default

def load(path):
    rows = [json.loads(l) for l in open(path)]
    X = np.array([[np.nan if r['features'][f] is None else float(r['features'][f])
                   for f in FEATS] for r in rows])
    miss = np.isnan(X[:, [FEATS.index(f) for f in DELTA_FEATS]])
    base = np.hstack([np.nan_to_num(X), miss.astype(float)])
    ci = [FEATS.index(f) for f in CTX_FEATS]
    ctx = []
    for off in CTX:
        sh = np.zeros((len(rows), len(ci)))
        for k in range(len(rows)):
            if 0 <= k + off < len(rows):
                sh[k] = np.nan_to_num(X[k + off, ci])
        ctx.append(sh)
    return rows, np.hstack([base] + ctx)

def hgb(balanced=False, **kw):
    kw.setdefault('max_iter', 300)
    kw.setdefault('learning_rate', 0.08)
    kw.setdefault('max_leaf_nodes', 15)
    kw.setdefault('min_samples_leaf', 4)
    kw.setdefault('l2_regularization', 1.0)
    if balanced:
        kw['class_weight'] = 'balanced'
    return HistGradientBoostingClassifier(**kw)

def cv_predict(X, y, groups, n_splits=6, model=hgb):
    """pooled out-of-fold predictions; also returns per-fold fitted factor tables"""
    y = np.asarray(y)
    pred = np.empty(len(y), dtype=object)
    folds = []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        m = model()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
        folds.append((tr, te))
    return pred, folds

def report(name, y, pred, min_support=5):
    y = np.asarray(y).astype(str)
    pred = np.asarray([str(p) for p in pred])
    acc = float((y == pred).mean())
    mf1 = float(f1_score(y, pred, average='macro'))
    sup = Counter(y)
    core = np.array([sup[v] >= min_support for v in y])
    acc_core = float((y[core] == pred[core]).mean()) if core.any() else float('nan')
    print(f"{name:34s} acc {acc:.3f}  macroF1 {mf1:.3f}  "
          f"acc(classes n>={min_support}) {acc_core:.3f}  (n={len(y)})")
    return {'name': name, 'acc': acc, 'macro_f1': mf1, 'acc_core': acc_core, 'n': len(y)}

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'events.jsonl'
    out_dir = 'models'
    if '--models-out' in sys.argv:
        out_dir = sys.argv[sys.argv.index('--models-out') + 1]
    rows, X = load(path)
    res = []

    st = [i for i, r in enumerate(rows) if r['event_kind'] == 'structural']
    Xs = X[st]
    g = np.array([rows[i]['line'] for i in st])
    y_glyph = np.array([rows[i]['glyph'] for i in st])
    # observable movement: degree delta from the previous CLAIMED slot — the
    # quantity audio can actually express (per-slot semantic deltas include
    # slots whose onsets were merged away in performance)
    y_mv = np.array([0 if rows[i]['mv_from_prev_claimed'] is None
                     else int(np.clip(rows[i]['mv_from_prev_claimed'], -3, 3)) for i in st])
    y_beats = np.array([str(min(max(rows[i]['beats'], 0.5), 3.0)) for i in st])
    y_comp = np.array(['single' if rows[i]['n_subs'] == 1 else f"of2.{rows[i]['sub']}"
                       for i in st])
    d_prev_col = X[:, FEATS.index('d_prev')][st]

    print(f"structural events: {len(st)}; glyph classes: {len(set(y_glyph))}; "
          f"lines: {len(set(g))}\n")

    # ---- baselines ----
    maj, folds = cv_predict(Xs, y_glyph, g, model=lambda: _Majority())
    res.append(report('baseline: majority', y_glyph, maj))
    dd_col = X[:, FEATS.index('ddeg_prev_long')][st]
    for nm, col in [('interval rule', d_prev_col), ('ladder rule', dd_col)]:
        ir = np.empty(len(st), dtype=object)
        for tr, te in folds:
            table = defaultdict(Counter)
            for i in tr:
                table[int(round(col[i]))][y_glyph[i]] += 1
            fallback = Counter(y_glyph[tr]).most_common(1)[0][0]
            for i in te:
                got = table.get(int(round(col[i])))
                ir[i] = got.most_common(1)[0][0] if got else fallback
        res.append(report(f'baseline: {nm}', y_glyph, ir))

    # ---- A. flat glyph ----
    pf, _ = cv_predict(Xs, y_glyph, g)
    res.append(report('A  GBM flat glyph', y_glyph, pf))

    # ---- B. factored ----
    pm, _ = cv_predict(Xs, y_mv, g)
    res.append(report('B1 movement head', y_mv, pm))
    pb, _ = cv_predict(Xs, y_beats, g)
    res.append(report('B2 beats head', y_beats, pb))
    pc, _ = cv_predict(Xs, y_comp, g)
    res.append(report('B3 compound-position head', y_comp, pc))
    comp = np.empty(len(st), dtype=object)
    for tr, te in folds:
        t3, t2, t1 = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        for i in tr:
            t3[(y_mv[i], y_beats[i], y_comp[i])][y_glyph[i]] += 1
            t2[(y_mv[i], y_comp[i])][y_glyph[i]] += 1
            t1[y_mv[i]][y_glyph[i]] += 1
        fallback = Counter(y_glyph[tr]).most_common(1)[0][0]
        for i in te:
            got = (t3.get((pm[i], pb[i], pc[i])) or t2.get((pm[i], pc[i]))
                   or t1.get(pm[i]))
            comp[i] = got.most_common(1)[0][0] if got else fallback
    res.append(report('B  factored -> composed glyph', y_glyph, comp))

    # ---- confusions of the best glyph lane ----
    best = pf if (y_glyph == pf).mean() >= (y_glyph == comp).mean() else comp
    conf = Counter((t, p) for t, p in zip(y_glyph, best) if t != p)
    print('\ntop confusions (true -> predicted):')
    for (t, p), n in conf.most_common(10):
        print(f'  {n:3d}  {t:28s} -> {p}')

    # ---- movement diagnostics ----
    mv_conf = Counter((t, p) for t, p in zip(y_mv, pm) if t != p)
    print('\nmovement confusions:', dict(mv_conf.most_common(8)))

    # ---- C. ornament / melisma detector ----
    oi = [i for i, r in enumerate(rows) if r['event_kind'] in ('structural', 'ornament')]
    Xo, yo = X[oi], np.array([int(rows[i]['event_kind'] == 'ornament') for i in oi])
    go = np.array([rows[i]['line'] for i in oi])
    prob = np.zeros(len(oi))
    for tr, te in GroupKFold(n_splits=6).split(Xo, yo, go):
        m = hgb(balanced=True)
        m.fit(Xo[tr], yo[tr])
        prob[te] = m.predict_proba(Xo[te])[:, 1]
    ap = float(average_precision_score(yo, prob))
    po = (prob >= 0.5).astype(int)
    tp = int(((po == 1) & (yo == 1)).sum()); fp = int(((po == 1) & (yo == 0)).sum())
    fn = int(((po == 0) & (yo == 1)).sum())
    print(f"\nC  ornament detector: AP {ap:.3f}  @0.5: precision "
          f"{tp / max(tp + fp, 1):.2f} recall {tp / max(tp + fn, 1):.2f} "
          f"({tp}tp/{fp}fp/{fn}fn of {int(yo.sum())} ornaments)")
    res.append({'name': 'C ornament detector', 'ap': ap, 'tp': tp, 'fp': fp, 'fn': fn})

    # ---- fit final models on ALL structural events; save ----
    os.makedirs(out_dir, exist_ok=True)
    import joblib
    final = {}
    for nm, yy in [('glyph_flat', y_glyph), ('movement', y_mv),
                   ('beats', y_beats), ('compound', y_comp)]:
        m = hgb(); m.fit(Xs, yy); final[nm] = m
    mo = hgb(balanced=True); mo.fit(Xo, yo); final['ornament'] = mo
    factor_map = defaultdict(Counter)
    for i in range(len(st)):
        factor_map[str((int(y_mv[i]), y_beats[i], y_comp[i]))][y_glyph[i]] += 1
    joblib.dump(final, os.path.join(out_dir, 'mcr_gbm.joblib'))
    json.dump({'features': FEATS + ['d_prev_missing', 'd_next_missing'],
               'factor_to_glyph': {k: c.most_common(1)[0][0] for k, c in factor_map.items()}},
              open(os.path.join(out_dir, 'mcr_gbm.spec.json'), 'w'), indent=1)
    json.dump(res, open(os.path.join(out_dir, 'report_gbm.json'), 'w'), indent=1)
    print(f"\nsaved models + spec + report -> {out_dir}/")

class _Majority:
    def fit(self, X, y):
        self.c = Counter(y).most_common(1)[0][0]
    def predict(self, X):
        return np.array([self.c] * len(X), dtype=object)

if __name__ == '__main__':
    main()
