#!/usr/bin/env python3
"""Onboard Mode Plagal 2nd vespers: clean hymns.json (+ genus), wire parallagi.

Cleaning rules (mirrors pl1_vespers_onboard.py):
  - tape order: psalm section p423-427 then stichera section p487-490
    (t12@p487.4 'Eme ypomenousi'+'Simeron o Christos' and t17@p490.4
    'H tafi sou / ta desma tou Adou' verified against glyph lyrics).
  - drop t13_ (p426.9-427.2: breaks monotonic page order after t12@p487 and
    near-duplicates t11_'s p426.11-427.5 range; keep earlier track t11_)
  - drop t15_ (p429.8-430.1: breaks monotonic page order between p487/p490;
    spurious early-copy match of 'Gennithito ta ota sou')
  - genus: hard_chromatic on all kept rows
Then for each kept hymn with parallagi_track set, build parallagi dataset +
align into /mnt/data/chant-corpus/parallagi/pl2-<stem>/ and set parallagi_dir
if summary_full.json exists with match agreement >= 0.4. (No hymn on this
tape got a parallagi pairing from locate_tracks: the tape's parallagi tracks
precede melos tracks whose whisper text failed to match the book.)
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/pl2'
PIECES = f'{CORPUS}/pieces/Mode Plagal 2nd Anastasimatarion 1 Vespers'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = {'t13_', 't15_'}

hymns = json.load(open(os.path.join(WD, 'hymns.json')))
kept, dropped = [], []
for h in hymns:
    if h['name'] in DROP:
        dropped.append(h['name'])
        continue
    h['genus'] = 'hard_chromatic'
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
    outdir = os.path.join(PARA_ROOT, 'pl2-' + stem)
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
        s = json.load(open(summ))
        agree = s.get('agreement', s.get('match_agreement'))
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
