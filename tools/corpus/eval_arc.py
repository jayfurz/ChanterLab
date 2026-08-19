#!/usr/bin/env python3
"""Decode hymn arc-dirs with the learned arc-scorer (EM-marginal, confidence
out) and score movement agreement — raw and confidence-gated.

Usage: eval_arc.py <mode-workdir> <hymn> [...more hymns]
"""
import json, os, sys
import numpy as np
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcr'))
import train_aligner as TA

MODEL = os.environ.get('ARC_MODEL', '/mnt/data/code/byzorgan-web-worktrees/chant-annotator/datasets/eothinon-11-workdir/models/aligner_gbm.joblib')

def main():
    wd = sys.argv[1]
    sys.modules['__main__'].Bag = TA.Bag      # model was pickled from __main__
    model = joblib.load(MODEL)
    rows = []
    for name in sys.argv[2:]:
        wdi, name = name.split(':', 1) if ':' in name else (wd, name)
        arc = os.path.join(wdi, 'melos_' + name, 'arc')
        P = TA.build_piece(arc, use_word=False)
        asn, conf = TA.decode_em(P, model, rounds=2)
        lad = np.array(json.load(open(os.path.join(arc, 'ladder.json'))))
        E = json.load(open(os.path.join(arc, 'expected_degrees.json')))
        pairs = sorted(asn.items())          # (event k, slot s) by k
        stats = {th: [0, 0] for th in (0.0, 0.5, 0.8)}
        for (k2, s2), (k, s) in zip(pairs, pairs[1:]):
            if P['med'][k] != P['med'][k]: continue
            if P['med'][k2] != P['med'][k2]: continue
            obs_m = P['med'][k] - P['med'][k2]
            exp_m = lad[s] - lad[s2]
            ok = abs(obs_m - exp_m) < 5.5    # within half a small step (moria)
            c = min(conf.get(k, 0), conf.get(k2, 0))
            for th in stats:
                if c >= th:
                    stats[th][0] += ok
                    stats[th][1] += 1
        cov = len(asn) / max(P['S'], 1)
        line = {'hymn': name, 'claimed': len(asn), 'S': P['S'],
                'coverage': round(100 * cov, 1)}
        for th, (ok, n) in stats.items():
            line[f'agree@{th}'] = round(ok / max(n, 1), 3)
            line[f'n@{th}'] = n
        rows.append(line)
        print(f"{name:22s} cov {line['coverage']:5.1f}% "
              f"raw {line['agree@0.0']:.3f} (n={line['n@0.0']}) "
              f"conf.5 {line['agree@0.5']:.3f} (n={line['n@0.5']}) "
              f"conf.8 {line['agree@0.8']:.3f} (n={line['n@0.8']})")
    for th in (0.0, 0.5, 0.8):
        N = sum(r[f'n@{th}'] for r in rows)
        OK = sum(r[f'agree@{th}'] * r[f'n@{th}'] for r in rows)
        print(f"OVERALL @conf>={th}: agreement {OK / max(N, 1):.3f} (n={N})")

if __name__ == '__main__':
    main()
