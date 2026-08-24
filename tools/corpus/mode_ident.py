#!/usr/bin/env python3
"""mode_ident.py -- the grave identification stack, pointed at another mode.

What generalises from grave orthros (degree_match_clf.py, 21/23 there):
count-free peak onsets -> degree classifier -> DTW against every candidate's
score-derived degree stream. What changes: candidates come from a WORKDIR's
hymns.json (machine-located line-level ranges, all modes), and ground truth
comes from the chanter's own hymn-named files where they exist (mode 2
vespers), so the result is a measured transfer number, not a hope.

The open question this answers: mode 2 is soft chromatic, and both the
classifier and the peak model were trained on diatonic grave. Degree STREAMS
are genus-independent (steps are steps), so if the classifier's ear survives
the chromatic intervals, identification should too.

Usage:
  mode_ident.py --workdir mode2 [--json out]
  mode_ident.py --workdir pl1-vespers
"""
import argparse
import glob
import json
import os
import re
import sys
import unicodedata

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'neural'))
import quick_onset as QO                    # noqa: E402
import parallagi_class as PC                # noqa: E402
from degree_match import dtw_cost           # noqa: E402
from score_degrees import degree_stream, leading_anchor, units_for  # noqa: E402

LEGEND = '/mnt/data/chant-corpus/scores/legend_canon.json'
MODELS = '/mnt/data/chant-corpus/models'
WD = '/mnt/data/chant-corpus/workdirs'


def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    tr = {'κ': 'k', 'υ': 'y', 'ρ': 'r', 'ι': 'i', 'ε': 'e', 'ξ': 'x', 'α': 'a',
          'β': 'v', 'γ': 'g', 'δ': 'd', 'ζ': 'z', 'η': 'i', 'θ': 'th', 'λ': 'l',
          'μ': 'm', 'ν': 'n', 'ο': 'o', 'π': 'p', 'σ': 's', 'ς': 's', 'τ': 't',
          'φ': 'f', 'χ': 'ch', 'ψ': 'ps', 'ω': 'o'}
    s = ''.join(tr.get(c, c) for c in s)
    return re.sub(r'[^a-z]', '', s)


def peaks_and_degrees(onet, cnet, path, dev, thresh=0.5):
    y = QO.audio(path)
    with torch.inference_mode():
        prob = torch.sigmoid(onet(torch.from_numpy(QO.features(y)).unsqueeze(0).to(dev)))[0]
    prob = prob.cpu().numpy()
    idx = np.where((prob[1:-1] >= prob[:-2]) & (prob[1:-1] > prob[2:])
                   & (prob[1:-1] >= thresh))[0] + 1
    fr = []
    for i in idx[np.argsort(-prob[idx])]:
        if all(abs(i - j) >= 18 for j in fr):
            fr.append(int(i))
    ts = [f * QO.HOP / QO.SR for f in sorted(fr)]
    if len(ts) < 8:
        return ts, []
    M = PC.mel(y[:])
    X = [PC.cut(M, t, ts[k + 1] if k + 1 < len(ts) else t + 0.6) for k, t in enumerate(ts)]
    with torch.inference_mode():
        p = torch.softmax(cnet(torch.from_numpy(np.stack(X)).to(dev)), 1)
    return ts, [int(i) + PC.DEG_LO for i in p.argmax(1).cpu().numpy()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--json')
    a = ap.parse_args()
    dev = torch.device(a.device if torch.cuda.is_available() else 'cpu')
    onet = QO.Net().to(dev)
    onet.load_state_dict(torch.load(f'{MODELS}/quick_onset_s020406_e200.pt', map_location=dev)); onet.eval()
    cnet = PC.Clf().to(dev)
    cnet.load_state_dict(torch.load(f'{MODELS}/parallagi_class_s020406.pt', map_location=dev)); cnet.eval()
    leg = json.load(open(LEGEND))

    hymns = json.load(open(f'{WD}/{a.workdir}/hymns.json'))
    hymns = hymns if isinstance(hymns, list) else hymns.get('hymns', [])
    cand = {}
    for h in hymns:
        try:
            u = units_for(h['p0'], h['l0'], 0, h['p1'], h['l1'], 10 ** 6)
            cand[h['name']] = [int(v) % 7 for v in degree_stream(
                u, leg, start=leading_anchor(h['p0'], 0))]
        except Exception as e:
            print('  candidate %s failed: %s' % (h['name'], str(e)[:60]))
    print('%d candidates with degree streams' % len(cand))

    # the parallagi audio files: chanter-named where available
    par_files = []
    dirs = set()
    for h in hymns:
        ma = h.get('melos_audio') or ''
        dirs.add(ma if os.path.isdir(ma) else os.path.dirname(ma))
    for dd in dirs:
        for f in sorted(glob.glob(os.path.join(dd, '*'))):
            if 'ΠΑΡΑΛΛΑΓ' in os.path.basename(f).upper():
                par_files.append(f)
    if not par_files:                      # tape-span workdirs: parallagi_track is a
        for h in hymns:                    # bare filename beside melos_audio
            t = h.get('parallagi_track')
            ma = h.get('melos_audio') or ''
            if t and not os.path.isabs(t):
                t = os.path.join(os.path.dirname(ma), t)
            if t and os.path.isfile(t):
                par_files.append(t)
    par_files = sorted(set(par_files))
    print('%d parallagi files' % len(par_files))

    mod = lambda s: [v % 7 for v in s]
    rows, hit, scored = [], 0, 0
    for f in par_files:
        nm = os.path.basename(f)
        ts, degs = peaks_and_degrees(onet, cnet, f, dev)
        if not degs:
            print('%-58s too few peaks' % nm[:58]); continue
        sc = sorted((dtw_cost(mod(degs), cand[c]) for c in cand), )
        ranked = sorted(((dtw_cost(mod(degs), cand[c]), c) for c in cand))
        best, margin = ranked[0][1], ranked[1][0] - ranked[0][0]
        truth = None
        fn = norm(nm)
        for c in cand:
            if norm(c) and norm(c)[:10] in fn:
                truth = c; break
        ok = (truth == best) if truth else None
        if truth: scored += 1; hit += bool(ok)
        rows.append({'file': nm, 'n_onsets': len(ts), 'best': best,
                     'margin': round(margin, 3), 'truth': truth, 'ok': ok})
        print('%-58s -> %-22s margin %.3f %s' % (nm[:58], best, margin,
              ('OK' if ok else 'WRONG (truth %s)' % truth) if truth else ''))
    if scored:
        print('\nidentified %d/%d against the chanter\'s own filenames' % (hit, scored))
    if a.json:
        json.dump({'workdir': a.workdir, 'rows': rows,
                   'hit': hit, 'scored': scored}, open(a.json, 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
