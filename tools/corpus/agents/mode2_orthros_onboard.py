#!/usr/bin/env python3
"""Onboard Mode 2 ORTHROS (Vasilikos tape, pdf pages 92-169): clean
locate_tracks hymns.json + build parallagi dataset dirs (whisper + CNN lanes).

Cleaning rules (mirror mode3_vespers_onboard.py precedent):
  - drop rows whose melos_audio is a NNN_speech.wav (psalm-verse/apolytikion
    recitations matched the book text but are spoken, not melos):
    t12(013) t18(019) t20(021) t21(022) t23(024)
  - drop t32_ (033_melos matched p163.11-164.5 at 0.17 between the p136/p138
    rows -> breaks monotonic page order)
  - drop t50_ (051_melos matched p133.3-133.9 at 0.33 after p148 -> breaks
    monotonic page order)
  - no two remaining rows duplicate a range -> nothing else dropped
  - genus left ABSENT (mode 2 mixes soft/hard chromatic; cmd_melos
    hypothesis-tests the ladders)
Parallagi lanes (parallagi_dir wiring left to wire_anchors.py):
  - whisper: kept hymns with parallagi_track -> parallagi_dataset +
    parallagi_align into parallagi/mode2orth-<stem>
  - CNN: EVERY NNN_parallagi.wav in the pieces dir -> classify_parallagi +
    parallagi_align into parallagi/mode2orthcnn-<stem>
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/mode2-orthros'
PIECES = f'{CORPUS}/pieces/Mode 2 Anastasimatarion 2 orthros vasilikos'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t12_', 't18_', 't20_', 't21_', 't23_', 't32_', 't50_'}

os.environ['CUDA_VISIBLE_DEVICES'] = ''      # no GPU jobs

hymns = json.load(open(os.path.join(WD, 'hymns.json')))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    kept.append(h)
json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)

built, skipped = [], []

# ---- whisper lane -----------------------------------------------------------
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
    outdir = os.path.join(PARA_ROOT, f'mode2orth-{stem}')
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
    agree = json.load(open(summ)).get('match_agreement') if os.path.exists(summ) else None
    built.append(('whisper', stem, agree))

# ---- CNN lane (every parallagi piece; whisper often fails) ------------------
for fn in sorted(os.listdir(PIECES)):
    if not fn.endswith('_parallagi.wav'):
        continue
    stem = os.path.splitext(fn)[0]
    outdir = os.path.join(PARA_ROOT, f'mode2orthcnn-{stem}')
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'classify_parallagi.py'),
                        '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
    if r.returncode != 0:
        skipped.append(('cnn', stem, f'classify rc={r.returncode}'))
        continue
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        skipped.append(('cnn', stem, f'align rc={r.returncode}'))
        continue
    summ = os.path.join(outdir, 'summary_full.json')
    agree = json.load(open(summ)).get('match_agreement') if os.path.exists(summ) else None
    built.append(('cnn', stem, agree))

print('KEPT:', [h['name'] for h in kept])
print('DROPPED:', dropped)
print('BUILT:', built)
print('SKIPPED:', skipped)
