#!/usr/bin/env python3
"""Onboard Mode Grave ORTHROS: clean hymns.json, build parallagi anchor dirs.

Cleaning rules:
  - drop t45_ (046_speech, p549.2-p549.4 duplicates t44_'s p549.0-p549.3
    range -> keep earlier track t44_, whose audio 045_melos is the sung one)
  - t28_ loses its parallagi_track (027_parallagi immediately precedes
    028_melos = t27_'s audio; locate_tracks paired it to both)
  - genus: diatonic on all kept rows
Then:
  - for each kept hymn with parallagi_track: parallagi_dataset.py +
    parallagi_align.py -> /mnt/data/chant-corpus/parallagi/graveorth-<stem>
    (whisper json = sliced per-piece transcript in the pieces dir)
  - for EVERY parallagi wav in the pieces dir: classify_parallagi.py +
    parallagi_align.py -> /mnt/data/chant-corpus/parallagi/graveorthcnn-<stem>
Anchor wiring is done separately by wire_anchors.py.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/grave-orthros'
SRC = f'{WD}/hymns.json'
PIECES = f'{CORPUS}/pieces/Mode Grave Anastasimatarion 2 Orthros'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t45_'}
UNPAIR = {'t28_'}

hymns = json.load(open(SRC))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    if h['name'] in UNPAIR:
        h['parallagi_track'] = None
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
    outdir = os.path.join(PARA_ROOT, f'graveorth-{stem}')
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
    agree = json.load(open(summ)).get('match_agreement') \
        if os.path.exists(summ) else None
    built.append((h['name'], f'graveorth-{stem}', agree))

# CNN fallback for every parallagi piece
cnn_built, cnn_skipped = [], []
for fn in sorted(os.listdir(PIECES)):
    if not fn.endswith('_parallagi.wav'):
        continue
    stem = os.path.splitext(fn)[0]
    outdir = os.path.join(PARA_ROOT, f'graveorthcnn-{stem}')
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'classify_parallagi.py'),
                        '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
    if r.returncode != 0:
        cnn_skipped.append((stem, f'classify rc={r.returncode}'))
        continue
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        cnn_skipped.append((stem, f'align rc={r.returncode}'))
        continue
    summ = os.path.join(outdir, 'summary_full.json')
    agree = json.load(open(summ)).get('match_agreement') \
        if os.path.exists(summ) else None
    cnn_built.append((stem, agree))

json.dump(kept, open(SRC, 'w'), ensure_ascii=False, indent=1)
print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
print('CNN_BUILT:', cnn_built)
print('CNN_SKIPPED:', cnn_skipped)
