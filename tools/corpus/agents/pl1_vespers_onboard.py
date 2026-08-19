#!/usr/bin/env python3
"""Onboard Mode Plagal 1st vespers: clean hymns.json, build parallagi dirs.

Cleaning rules (task B):
  - drop t09 (p405 range breaks monotonic page order between p341/p342)
  - drop t24 (duplicates t14's p347 range)
  - t26/t28 share the p353-354 range -> keep earlier track t26, drop t28
  - genus: diatonic on all kept rows
Then for each kept hymn with parallagi_track, run parallagi_dataset.py +
parallagi_align.py into /mnt/data/chant-corpus/parallagi/<track-stem>/ and
set parallagi_dir (skip if transcript missing).
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
SRC = f'{CORPUS}/workdirs/pl1-vespers-hymns.json'
WD = f'{CORPUS}/workdirs/pl1-vespers'
AUDIO_DIR = f'{CORPUS}/raw/vasilikos/Mode Plagal 1st Anastasimatarion 1 Vespers'
TRANS_DIR = f'{CORPUS}/transcripts'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DROP = {'t09_ηχπλαεσπερινοσ', 't24_ηχπλαεσπερινοσ', 't28_ηχπλαεσπερινοσ'}

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
    audio = os.path.join(AUDIO_DIR, trk)
    whisper = os.path.join(TRANS_DIR, stem + '.json')
    if not os.path.exists(audio) or not os.path.exists(whisper):
        skipped.append((h['name'], stem,
                        'audio' if not os.path.exists(audio) else 'transcript'))
        continue
    outdir = os.path.join(PARA_ROOT, stem)
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
    h['parallagi_dir'] = outdir
    built.append((h['name'], outdir))

json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
