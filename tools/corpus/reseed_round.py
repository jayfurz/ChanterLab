#!/usr/bin/env python3
"""reseed_round.py — stage-A legend re-seed round (chanter atlas, 2026-08-18).

Per workdir:
  1. back up legend_global.json, unitdeg_*.json, melos_*/aligned.json,
     melos_*/summary.json into <wd>/_pre_reseed/
  2. delete legend_global.json (so cmd_legend starts from CHANTER_LOCK) and
     ALL unitdeg_*.json (rotated-legend products; cmd_legend regenerates the
     parallagi-covered ones — hymns without parallagi run melos with no
     absolute anchors, which is the honest state)
  3. run cmd_legend (EM with chanter-locked core keys)
  4. overlay any unitdeg_chanter_<hymn>.json (chanter-pin ground-truth
     degrees, e.g. grave-orthros t03 head) onto the regenerated unitdeg
  5. run cmd_melos for every hymn
  6. print old-vs-new agreement/coverage per hymn

No unit-segmentation changes: unit indices, iv_ovr_* files, annotator
piece slot structures and chanter pins all stay valid.

Usage: reseed_round.py --workdir <wd> | --all
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

CORPUS = '/mnt/data/chant-corpus/workdirs'
HERE = os.path.dirname(os.path.abspath(__file__))
HA = os.path.join(HERE, 'hymn_align.py')
PY = sys.executable


def reseed(wd):
    wdn = os.path.basename(os.path.normpath(wd))
    hf = os.path.join(wd, 'hymns.json')
    if not os.path.isfile(hf):
        print(f'{wdn}: no hymns.json, skipped')
        return []
    hymns = json.load(open(hf))

    # 1. backup (idempotent: never overwrite an existing backup)
    bak = os.path.join(wd, '_pre_reseed')
    os.makedirs(bak, exist_ok=True)
    old = {}
    for f in (glob.glob(os.path.join(wd, 'legend_global.json'))
              + glob.glob(os.path.join(wd, 'unitdeg_*.json'))):
        dst = os.path.join(bak, os.path.basename(f))
        if not os.path.exists(dst):
            shutil.copyfile(f, dst)
    for mdir in glob.glob(os.path.join(wd, 'melos_*')):
        if not os.path.isdir(mdir) or mdir.endswith(('.bak', '_pre_reseed')):
            continue
        sf = os.path.join(mdir, 'summary.json')
        if os.path.exists(sf):
            s = json.load(open(sf))
            old[s['hymn']] = (s['movement_agreement'], s['coverage_units_pct'])
            dst = os.path.join(bak, os.path.basename(mdir) + '.summary.json')
            if not os.path.exists(dst):
                shutil.copyfile(sf, dst)
        af = os.path.join(mdir, 'aligned.json')
        dst = os.path.join(bak, os.path.basename(mdir) + '.aligned.json')
        if os.path.exists(af) and not os.path.exists(dst):
            shutil.copyfile(af, dst)

    # 2. clear rotated-legend state
    lg = os.path.join(wd, 'legend_global.json')
    if os.path.exists(lg):
        os.remove(lg)
    for f in glob.glob(os.path.join(wd, 'unitdeg_*.json')):
        if 'unitdeg_chanter_' in f or 'unitdeg_ovr' in f or '.orig' in f:
            continue
        os.remove(f)

    # 3. legend EM
    r = subprocess.run([PY, HA, 'legend', wd, '--hymns', hf],
                       capture_output=True, text=True, timeout=3600)
    print(r.stdout.strip().splitlines()[-2] if r.stdout.strip() else '')
    if r.returncode:
        print(f'{wdn}: LEGEND FAILED\n{r.stderr[-800:]}')
        return []

    # 4. chanter unitdeg overlays (ground truth beats regenerated anchors)
    for f in glob.glob(os.path.join(wd, 'unitdeg_chanter_*.json')):
        name = os.path.basename(f)[len('unitdeg_chanter_'):-len('.json')]
        tgt = os.path.join(wd, f'unitdeg_{name}.json')
        base = json.load(open(tgt)) if os.path.exists(tgt) else {}
        base.update(json.load(open(f)))
        json.dump(base, open(tgt, 'w'))
        print(f'  overlaid chanter degrees onto unitdeg_{name}.json')

    # 5. melos per hymn
    rows = []
    for h in hymns:
        name = h['name']
        r = subprocess.run([PY, HA, 'melos', wd, '--hymns', hf, '--hymn', name],
                           capture_output=True, text=True, timeout=1800)
        sf = os.path.join(wd, 'melos_' + name, 'summary.json')
        if r.returncode or not os.path.exists(sf):
            print(f'  {wdn}/{name}: MELOS FAILED\n{r.stderr[-400:]}')
            continue
        s = json.load(open(sf))
        o = old.get(name)
        rows.append((f'{wdn}/{name}', o, (s['movement_agreement'],
                                          s['coverage_units_pct'])))
    for hymn, o, n in rows:
        fo = f'{o[0]:.2f}/{o[1]:.0f}%' if o else '—'
        print(f'  {hymn:36} {fo:>12} -> {n[0]:.2f}/{n[1]:.0f}%')
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    wds = (sorted(glob.glob(os.path.join(CORPUS, '*')))
           if args.all else [args.workdir])
    if not wds or wds == [None]:
        ap.error('need --workdir or --all')
    for wd in wds:
        if os.path.isdir(wd):
            reseed(wd)


if __name__ == '__main__':
    main()
