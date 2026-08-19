#!/usr/bin/env python3
"""Onboard Mode 1 ORTHROS (Vasilikos tape 2): clean hymns.json, build
parallagi anchor dirs (whisper + CNN lanes).

Cleaning rules:
  - page order p21..p68 is fully monotonic; no two rows duplicate a range
  - drop t16_ (017_speech.wav) and t35_ (036_speech.wav): separate_pieces
    classified them speech (recited text, no melody); t35 additionally
    overlaps t36's p67 range
  - genus: diatonic on all kept rows (mode 1)

Anchor lanes (parallagi_dir left to wire_anchors.py):
  - whisper: hymns with parallagi_track -> parallagi_dataset + parallagi_align
    into /mnt/data/chant-corpus/parallagi/mode1orth-<stem>
  - CNN: EVERY NNN_parallagi.wav in the pieces dir -> classify_parallagi +
    parallagi_align into /mnt/data/chant-corpus/parallagi/mode1orthcnn-<stem>
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/mode1-orthros'
PIECES = (f'{CORPUS}/pieces/Mode 1 Anastasimatarion 2 Orthros Vasilikos '
          'plus partial cherubic hymn vasilikos')
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t16_', 't35_'}

hymns = json.load(open(os.path.join(WD, 'hymns.json')))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    h['genus'] = 'diatonic'
    kept.append(h)
json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)

built, skipped = [], []
# whisper lane
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
    outdir = os.path.join(PARA_ROOT, f'mode1orth-{stem}')
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
    agr = json.load(open(sf)).get('match_agreement') if os.path.exists(sf) else None
    built.append(('whisper', stem, agr))

# CNN lane: every parallagi piece
for fn in sorted(os.listdir(PIECES)):
    if not fn.endswith('_parallagi.wav'):
        continue
    stem = os.path.splitext(fn)[0]
    outdir = os.path.join(PARA_ROOT, f'mode1orthcnn-{stem}')
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'classify_parallagi.py'),
                        '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
    if r.returncode != 0:
        skipped.append(('cnn', stem, f'classify rc={r.returncode}'))
        continue
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        skipped.append(('cnn', stem, f'align rc={r.returncode}'))
        continue
    sf = os.path.join(outdir, 'summary_full.json')
    agr = json.load(open(sf)).get('match_agreement') if os.path.exists(sf) else None
    built.append(('cnn', stem, agr))

print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
