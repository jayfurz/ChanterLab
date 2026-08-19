#!/usr/bin/env python3
"""Bridge a hymn's DTW workdir into the learned arc-scorer's piece format
(tools/mcr/train_aligner.build_piece), so decode_em can align it with
calibrated per-note confidence.

Usage: hymn_to_workdir.py <mode-workdir> <hymn-name>
  reads  <wd>/melos_<name>/ (tracks + summary) + book units + legend
  writes <wd>/melos_<name>/arc/  (aligner-format piece dir)
"""
import json, os, shutil, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcr'))
from hymn_align import load_units_h, LADDERS, beats_seq

# dot count -> printed duration name (chanter: apli 1 beat, dipli 2, tripli 3)
DUR_NAME = {1: 'apli', 2: 'dipli', 3: 'tripli'}
from mcrlib import clean_stream

CPM = 1200.0 / 72.0

def main():
    wd, name = sys.argv[1], sys.argv[2]
    hymns = json.load(open(os.path.join(wd, 'hymns.json')))
    h = next(x for x in hymns if x['name'] == name)
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    mdir = os.path.join(wd, 'melos_' + name)
    summ = json.load(open(os.path.join(mdir, 'summary.json')))
    out = os.path.join(mdir, 'arc')
    os.makedirs(out, exist_ok=True)
    units, _ = load_units_h(h)
    start = summ['start']
    genus = summ['genus']
    pos = LADDERS[genus]

    cents = np.load(os.path.join(mdir, 'cents_track.npy'))
    rms = np.load(os.path.join(mdir, 'rms_track.npy'))
    ni_c = summ['ni_cents_rel55']
    mor = (cents - ni_c) * (72.0 / 1200.0)
    np.save(os.path.join(out, 'moria_track.npy'), mor)
    np.save(os.path.join(out, 'rms_track.npy'), rms)
    vn_raw = json.load(open(os.path.join(mdir, 'voice_notes.json')))
    vn = clean_stream([list(v) for v in vn_raw], mor, rms, None)
    json.dump(vn, open(os.path.join(out, 'voice_notes3.json'), 'w'))

    E, interp, gis = [], [], []
    bseq = beats_seq(units)
    deg = start
    for j, u in enumerate(units):
        deg += iv.get(u['key'], 0)
        E.append(deg)
        gis.append(j)
        beat = bseq[j]
        interp.append({'gi': j, 'cp': u['key'], 'name': u['key'],
                       'line': u['pl'][0] * 100 + u['pl'][1], 'sub_notes': 1,
                       'beats': [beat], 'gorgon': bool(u['gorgon']),
                       'duration_mark': 'klasma' if u['klasma'] else
                       (DUR_NAME.get(u.get('dots', 0), 'apli') if u.get('dots') else 'none'),
                       'quality_marks': [], 'other_marks': [],
                       'expected_degrees': [deg], 'ison_at_start': 0,
                       'slot_ids': [j], 'word': None, 'word_start': False})
    json.dump({'t': [0.0] * len(units), 'gi': gis, 'sub': [0] * len(units)},
              open(os.path.join(out, 'slots.json'), 'w'))
    json.dump(interp, open(os.path.join(out, 'mcr_interpretation.json'), 'w'))
    json.dump(E, open(os.path.join(out, 'expected_degrees.json'), 'w'))
    json.dump([], open(os.path.join(out, 'barlines.json'), 'w'))
    json.dump([pos(e) for e in E], open(os.path.join(out, 'ladder.json'), 'w'))
    print(f"{name}: {len(units)} slots, {len(vn)} cleaned events "
          f"(raw {len(vn_raw)}), genus {genus}, start {start} -> {out}")

if __name__ == '__main__':
    main()
