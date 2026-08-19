#!/usr/bin/env python3
"""Onboard Mode Grave vespers: clean hymns.json, build parallagi dirs.

Cleaning rules:
  - drop t21 (duplicates t14's p506.10-p507.1 range; keep earlier track)
  - drop t31 (p516 range breaks monotonic page order between p577/p579)
  - genus: diatonic on all kept rows
Then for each kept hymn with parallagi_track, run parallagi_dataset.py +
parallagi_align.py into /mnt/data/chant-corpus/parallagi/grave-<stem>/ and
set parallagi_dir only if summary_full.json exists with match_agreement >= 0.4.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/grave'
SRC = f'{WD}/hymns.json'
PIECES = f'{CORPUS}/pieces/Mode Grave Anastasimatarion 1 Vespers'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t21_', 't31_'}

hymns = json.load(open(SRC))
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
    outdir = os.path.join(PARA_ROOT, f'grave-{stem}')
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
    if not os.path.exists(summ):
        skipped.append((h['name'], stem, 'no summary_full.json'))
        continue
    agree = json.load(open(summ)).get('match_agreement', 0)
    if agree is None or agree < 0.4:
        skipped.append((h['name'], stem, f'agreement {agree} < 0.4'))
        continue
    h['parallagi_dir'] = outdir
    built.append((h['name'], outdir, agree))

json.dump(kept, open(SRC, 'w'), ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
