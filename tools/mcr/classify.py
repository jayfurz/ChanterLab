#!/usr/bin/env python3
"""Pure-audio glyph + melisma classification for a chant recording.

Consumes the audio-derived event table (build_events.py output — features come
only from the f0/rms tracks and segmentation, never the score) and the trained
GBM models, and emits a predicted glyph stream:

  each event -> ornament probability; events below the ornament threshold get
  a glyph.sub prediction (flat GBM head) + observable-movement prediction.

Usage: classify.py <events.jsonl> <models_dir> [out.jsonl]

If the events table carries labels, an accuracy summary is printed. NOTE: on
the training piece that summary is resubstitution (models saw every event);
the honest numbers are the grouped-CV ones in models/report_gbm.json.
"""
import json, sys, os
import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import load

ORN_THRESH = 0.5

def main():
    ev_path, mdir = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(ev_path) or '.', 'predicted_glyphs.jsonl')
    rows, X = load(ev_path)
    M = joblib.load(os.path.join(mdir, 'mcr_gbm.joblib'))

    p_orn = M['ornament'].predict_proba(X)[:, 1]
    glyph = M['glyph_flat'].predict(X)
    mv = M['movement'].predict(X)

    preds = []
    for i, r in enumerate(rows):
        is_orn = bool(p_orn[i] >= ORN_THRESH)
        preds.append({'event': r['event'], 't0': r['t0'], 't1': r['t1'],
                      'kind_pred': 'ornament' if is_orn else 'structural',
                      'p_ornament': round(float(p_orn[i]), 3),
                      'glyph_pred': None if is_orn else str(glyph[i]),
                      'movement_pred': None if is_orn else int(mv[i])})
    with open(out, 'w') as f:
        for p in preds:
            f.write(json.dumps(p) + '\n')
    n_orn = sum(p['kind_pred'] == 'ornament' for p in preds)
    print(f"{len(preds)} events -> {out}  ({n_orn} flagged as ornament/melisma)")

    if any(r['event_kind'] == 'structural' for r in rows):
        st = [i for i, r in enumerate(rows) if r['event_kind'] == 'structural']
        acc = float(np.mean([rows[i]['glyph'] == preds[i]['glyph_pred'] for i in st]))
        kinds = [(r['event_kind'] == 'ornament', p['kind_pred'] == 'ornament')
                 for r, p in zip(rows, preds) if r['event_kind'] in ('structural', 'ornament')]
        kacc = float(np.mean([a == b for a, b in kinds]))
        print(f"labels present: glyph acc {acc:.3f}, structural/ornament acc {kacc:.3f} "
              f"(RESUBSTITUTION if this is the training piece — see report_gbm.json for CV)")

if __name__ == '__main__':
    main()
