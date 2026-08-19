#!/usr/bin/env python3
"""Onboard Mode Plagal 4th ORTHROS (mirrors pl4_vespers_onboard.py).

Cleaning (locate_tracks over pdf pages 588-673):
  - drop t14 (p607.10-608.4 duplicates t06's range and breaks monotonic
    order after t11 p610; constrained rematch only reproduces t06's range
    at 0.22)
  - relocate t38 039_melos p668.2-668.6 -> p638.0-638.4 (book prints the
    praises stichera twice; matcher took the later printing, breaking
    monotonic order — constrained rematch in the first printing: 0.38)
  - drop t40 (same double-printing problem at p668.10-669.2, but the
    constrained rematch is too weak to trust: 0.16-0.20)
  - relocate t49 050_other p612.4-p612.12 -> p649.11-650.2 (trisagion
    asmatikon follows the p646-649 doxology; p612 match was spurious)
  - genus diatonic on every kept row.
Then whisper-lane parallagi datasets (parallagi_dataset + parallagi_align)
into /mnt/data/chant-corpus/parallagi/pl4orth-<stem> for hymns with a
parallagi_track; CNN lane (classify_parallagi + parallagi_align) into
pl4orthcnn-<stem> for EVERY parallagi piece. Anchor wiring is done after
by wire_anchors.py.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/pl4-orthros'
PIECES = f'{CORPUS}/pieces/Mode Plagal 4th Anastasimatarion 2 Orthros'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t14_', 't40_'}
RELOC = {'t38_': (638, 0, 638, 4, 0.38), 't49_': (649, 11, 650, 2, 0.24)}

hymns = json.load(open(os.path.join(WD, 'hymns.json')))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    if h['name'] in RELOC:
        h['p0'], h['l0'], h['p1'], h['l1'], h['match_frac'] = RELOC[h['name']]
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
    outdir = os.path.join(PARA_ROOT, f'pl4orth-{stem}')
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
    agree = json.load(open(sf)).get('match_agreement') if os.path.exists(sf) else None
    built.append((h['name'], f'pl4orth-{stem}', agree))

cnn_built, cnn_failed = [], []
for fn in sorted(os.listdir(PIECES)):
    if not fn.endswith('_parallagi.wav'):
        continue
    stem = os.path.splitext(fn)[0]
    outdir = os.path.join(PARA_ROOT, f'pl4orthcnn-{stem}')
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'classify_parallagi.py'),
                        '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
    if r.returncode != 0:
        cnn_failed.append((stem, f'classify rc={r.returncode}'))
        continue
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        cnn_failed.append((stem, f'align rc={r.returncode}'))
        continue
    sf = os.path.join(outdir, 'summary_full.json')
    agree = json.load(open(sf)).get('match_agreement') if os.path.exists(sf) else None
    cnn_built.append((stem, agree))

json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
          ensure_ascii=False, indent=1)
print('KEPT:', [(h['name'], f"p{h['p0']}.{h['l0']}-p{h['p1']}.{h['l1']}") for h in kept])
print('DROPPED:', dropped)
print('WHISPER BUILT:', built)
print('WHISPER SKIPPED:', skipped)
print('CNN BUILT:', cnn_built)
print('CNN FAILED:', cnn_failed)
