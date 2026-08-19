#!/usr/bin/env python3
"""Onboard Mode Plagal 4th vespers (mirrors pl1_vespers_onboard.py).

Cleaning: locate_tracks output is already monotonic in page order with no
duplicate ranges (t08 p589.7-12, t10 p591.5-8, t15 p594.9-13, t20 p600.9-
601.5) -> nothing dropped; set genus diatonic on every row.
Then for each hymn with parallagi_track: parallagi_dataset.py +
parallagi_align.py into /mnt/data/chant-corpus/parallagi/pl4-<stem>/ and set
parallagi_dir when summary_full.json exists with match_agreement >= 0.4.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/pl4'
PIECES = f'{CORPUS}/pieces/Mode Plagal 4th Anastasimatarion 1 Vespers'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = set()

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
    outdir = os.path.join(PARA_ROOT, f'pl4-{stem}')
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
    agree = None
    if os.path.exists(sf):
        agree = json.load(open(sf)).get('match_agreement')
    if agree is not None and agree >= 0.4:
        h['parallagi_dir'] = outdir
        built.append((h['name'], outdir, agree))
    else:
        skipped.append((h['name'], stem, f'agreement={agree}'))

json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
