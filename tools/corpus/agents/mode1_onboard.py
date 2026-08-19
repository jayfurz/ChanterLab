#!/usr/bin/env python3
"""Onboard Mode 1 vespers (Vasilikos tape): clean hymns.json, build parallagi.

Cleaning rules (mirror pl1_vespers_onboard.py):
  - drop t02_ (003_melos matched p76.6-77.1 at 0.12, breaking the monotonic
    p5 -> p20 page chain of every other row)
  - no two rows duplicate a range -> nothing else dropped
  - genus: diatonic on all kept rows
Then for each kept hymn with parallagi_track: piece wav + sliced whisper json
live in the pieces dir; run parallagi_dataset.py + parallagi_align.py into
/mnt/data/chant-corpus/parallagi/mode1-<stem>; set parallagi_dir only when
summary_full.json exists with match_agreement >= 0.4.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/mode1'
PIECES = f'{CORPUS}/pieces/Mode 1 Anastasimatarion 1 Vespers Vasilikos'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t02_'}

hymns = json.load(open(os.path.join(WD, 'hymns.json')))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    h['genus'] = 'diatonic'
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
    outdir = os.path.join(PARA_ROOT, f'mode1-{stem}')
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
    sf = os.path.join(outdir, 'summary_full.json')
    if not os.path.exists(sf):
        skipped.append((h['name'], stem, 'no summary_full'))
        continue
    agree = json.load(open(sf)).get('match_agreement', 0)
    if agree < 0.4:
        skipped.append((h['name'], stem, f'agreement {agree} < 0.4'))
        continue
    h['parallagi_dir'] = outdir
    built.append((h['name'], outdir, agree))

json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
