#!/usr/bin/env python3
"""Onboard Mode Plagal 1st "Hymns of Compunction" (vasilikos tape, book
search pages 336-421; taught material actually sits p362-367 + p397).

Transcripts were watermark-cleaned (pl4_clean_watermark.py) before
locate_tracks; locate found 4 melos rows (t00 001, t03 004, t07 008,
t09 010) and missed 006 (garbled ASR -> 'unmatched').

Cleaning of locate_tracks output:
  - t00_ (001_melos, 'Kyrie amartanon ou pavomai') matched p397.11-398.1
    (0.57) — the incipit is unique in 336-421, but the track is 299 s and
    whisper heard only its first 15 s: how many of the katanyktika that
    follow p397.11 it sings is unverifiable, and p397 breaks monotonic
    order vs every other row (p362-367) -> DROP.
  - t03_ (004_melos, 'Egeiras me pesonta') -> tighten to the real hymn
    bounds p362.10-363.3 (locate bled one line each side: 362.9/363.4).
  - ADD t05_006 (006_melos, 'Yperagia Theotoke... Lelytai i katara'):
    locate said unmatched, but windowed match puts it exactly between its
    neighbours at p363.3-363.8; paired with 005_parallagi.
  - t07_ (008_melos, 'O pixas ep' oudenos') matched the argon duplicate
    p374.4-374.13; the in-order syllabic copy (28 s track) is p363.8-363.13
    -> RELOCATE.
  - t09_ (010_melos, 640 s canon-teaching medley) matched p363.11-365.2
    (0.09). Whisper chunks pin every troparion in book order: p364.0,
    364.5, 364.10, 365.4, 365.8, 366.1, 366.5, 366.9, 367.2 at a metronomic
    ~55 s cycle; the remaining 133 s = two more cycles = p367.7 and p367.12
    -> RELOCATE to p364.0-367.16.
  - genus 'diatonic' everywhere; names get the wav stem prefix (locate's
    norm() empties latin/digit stems).

Then parallagi anchors:
  - whisper lane: parallagi_dataset+parallagi_align ->
    parallagi/pl1-compunction-<stem> for each kept hymn's parallagi_track.
  - CNN lane: classify_parallagi (PAR_CNN=parallagi_cnn_r2.pt)
    +parallagi_align -> parallagi/pl1-compunctioncnn-<stem> for EVERY
    parallagi piece of the tape.
(wire_anchors.py is run separately afterwards.)
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
PIECES = f'{CORPUS}/pieces/Mode Plagal 1st Hymns of Compunction'
WD = f'{CORPUS}/workdirs/pl1-compunction'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DROP = {'t00_'}
RELOCATE = {'t03_': (362, 10, 363, 3),
            't07_': (363, 8, 363, 13),
            't09_': (364, 0, 367, 16)}
ADD = [{'name': 't05_', 'p0': 363, 'l0': 3, 'p1': 363, 'l1': 8,
        'melos_audio': os.path.join(PIECES, '006_melos.wav'),
        'parallagi_track': '005_parallagi.wav', 'parallagi_dir': None,
        'match_frac': None}]

os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['PAR_CNN'] = f'{CORPUS}/models/parallagi_cnn_r2.pt'

def run(args):
    return subprocess.run([sys.executable] + args).returncode

def align_agree(outdir):
    sf = os.path.join(outdir, 'summary_full.json')
    return json.load(open(sf)).get('match_agreement', 0.0) \
        if os.path.exists(sf) else None

def main():
    hymns = json.load(open(os.path.join(WD, 'hymns.json')))
    hymns = [h for h in hymns if 'p0' in h] + ADD
    hymns.sort(key=lambda h: h['name'])
    kept, dropped = [], []
    for h in hymns:
        if h['name'] in DROP:
            dropped.append(h['name'])
            continue
        if h['name'] in RELOCATE:
            h['p0'], h['l0'], h['p1'], h['l1'] = RELOCATE[h['name']]
        stem = os.path.splitext(os.path.basename(h['melos_audio']))[0]
        h['name'] = h['name'] + stem.split('_')[0]
        h['melos_whisper'] = os.path.join(PIECES, stem + '.json')
        h['genus'] = 'diatonic'
        # t09: pair with its immediately preceding parallagi piece
        if h['name'] == 't09_010' and not h.get('parallagi_track'):
            h['parallagi_track'] = '009_parallagi.wav'
        kept.append(h)

    results, crashes = [], []
    # whisper lane for kept hymns' parallagi tracks
    for h in kept:
        trk = h.get('parallagi_track')
        if not trk:
            continue
        stem = os.path.splitext(trk)[0]
        outdir = os.path.join(PARA_ROOT, f'pl1-compunction-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'parallagi_dataset.py'),
                  '--audio', os.path.join(PIECES, trk),
                  '--whisper', os.path.join(PIECES, stem + '.json'),
                  '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'pl1-compunction-{stem}', rc))
            continue
        results.append((f'pl1-compunction-{stem}', align_agree(outdir)))
    # CNN lane for every parallagi piece
    for fn in sorted(os.listdir(PIECES)):
        if not fn.endswith('_parallagi.wav'):
            continue
        stem = os.path.splitext(fn)[0]
        outdir = os.path.join(PARA_ROOT, f'pl1-compunctioncnn-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'classify_parallagi.py'),
                  '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'pl1-compunctioncnn-{stem}', rc))
            continue
        results.append((f'pl1-compunctioncnn-{stem}', align_agree(outdir)))

    json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('KEPT:', [(h['name'], f"p{h['p0']}.{h['l0']}-p{h['p1']}.{h['l1']}")
                    for h in kept])
    print('DROPPED:', dropped)
    print('PARALLAGI:', results)
    print('CRASHES:', crashes)

if __name__ == '__main__':
    main()
