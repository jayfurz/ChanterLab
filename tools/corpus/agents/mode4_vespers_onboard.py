#!/usr/bin/env python3
"""Onboard Mode 4 vespers: clean hymns.json, build parallagi dirs.

Cleaning rules (mirror pl1_vespers_onboard.py):
  - drop t18 (p329 range breaks monotonic page order between t17 p271 and
    t19 p272)
  - no duplicated ranges
  - genus left ABSENT (aligner hypothesis-tests ladders; mode 4 may mix
    legetos/soft and diatonic)
Then for each kept hymn with parallagi_track, run parallagi_dataset.py +
parallagi_align.py into /mnt/data/chant-corpus/parallagi/mode4-<stem>/ and
set parallagi_dir only if summary_full.json exists with match_agreement >= 0.4.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/mode4'
SRC = f'{WD}/hymns.json'
PIECES = f'{CORPUS}/pieces/Mode 4 Anastasimatarion 1 Vespers'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t18_'}

hymns = json.load(open(SRC))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    h.pop('genus', None)
    kept.append(h)

built, skipped = [], []
for h in kept:
    trk = h.get('parallagi_track')
    if not trk:
        continue
    stem = os.path.splitext(trk)[0]
    audio = os.path.join(PIECES, trk)
    whisper = os.path.join(PIECES, stem + '.json')
    if not os.path.exists(audio) or not os.path.exists(whisper):
        skipped.append((h['name'], stem,
                        'audio' if not os.path.exists(audio) else 'transcript'))
        continue
    outdir = os.path.join(PARA_ROOT, f'mode4-{stem}')
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_dataset.py'),
                        '--audio', audio, '--whisper', whisper, '--outdir', outdir])
    if r.returncode != 0:
        skipped.append((h['name'], stem, f'dataset rc={r.returncode}'))
        continue
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        skipped.append((h['name'], stem, f'align rc={r.returncode}'))
        continue
    summ = os.path.join(outdir, 'summary_full.json')
    agree = None
    if os.path.exists(summ):
        agree = json.load(open(summ)).get('match_agreement')
    if agree is not None and agree >= 0.4:
        h['parallagi_dir'] = outdir
        built.append((h['name'], outdir, agree))
    else:
        skipped.append((h['name'], stem, f'agreement={agree}'))

json.dump(kept, open(SRC, 'w'), ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
