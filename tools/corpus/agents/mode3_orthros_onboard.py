#!/usr/bin/env python3
"""Onboard Mode 3 ORTHROS (vasilikos tape 'Anastasimatarion 2 orthros plus
cherubic hymn', book pages 170-253; orthros text lives ~p188-233).

Cleaning of locate_tracks output (18 rows):
  - drop speech recitations located as melos: t02(003), t15(016), t37(038)
    (same rule as mode 3 vespers: spoken psalm/doxology verses, not melos).
  - t22 (023_melos, 'Tin timioteran'+pasapnoaria) matched p246.4-246.10 — a
    later duplicate setting — breaking monotonic order; windowed rematch in
    p215-219 is weak (0.19) and its first half (megalynarion) is not in the
    book stream here -> DROP.
  - t26 (027_melos, 'Defte panta ta ethni gnote tou friktou mystiriou')
    matched p247.0-247.2, the argon duplicate of the same sticheron; the
    in-order copy starts p218.13 (windowed rematch 0.43) and must end where
    029_melos picks up (p219.12) -> RELOCATE to p218.13-219.12.
  - remaining 14 rows are monotonic p188.8 .. p233.2, no duplicate ranges.
  - genus 'diatonic' everywhere; names get the wav stem suffix (locate's
    norm() empties latin/digit stems).

Then parallagi anchors:
  - whisper lane: parallagi_dataset+parallagi_align ->
    parallagi/mode3orth-<stem> for each kept hymn's parallagi_track.
  - CNN lane: classify_parallagi+parallagi_align ->
    parallagi/mode3orthcnn-<stem> for EVERY parallagi piece of the tape.
(wire_anchors.py is run separately afterwards.)
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
PIECES = f'{CORPUS}/pieces/Mode 3 Anastasimatarion 2 orthros plus cherubic hymn'
WD = f'{CORPUS}/workdirs/mode3-orthros'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DROP = {'t02_', 't15_', 't22_', 't37_'}
RELOCATE = {'t26_': (218, 13, 219, 12)}

def run(args):
    return subprocess.run([sys.executable] + args).returncode

def align_agree(outdir):
    sf = os.path.join(outdir, 'summary_full.json')
    return json.load(open(sf)).get('match_agreement', 0.0) \
        if os.path.exists(sf) else None

def main():
    hymns = json.load(open(os.path.join(WD, 'hymns.json')))
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
        kept.append(h)

    results, crashes = [], []
    # whisper lane for kept hymns' parallagi tracks
    for h in kept:
        trk = h.get('parallagi_track')
        if not trk:
            continue
        stem = os.path.splitext(trk)[0]
        outdir = os.path.join(PARA_ROOT, f'mode3orth-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'parallagi_dataset.py'),
                  '--audio', os.path.join(PIECES, trk),
                  '--whisper', os.path.join(PIECES, stem + '.json'),
                  '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'mode3orth-{stem}', rc))
            continue
        results.append((f'mode3orth-{stem}', align_agree(outdir)))
    # CNN lane for every parallagi piece
    for fn in sorted(os.listdir(PIECES)):
        if not fn.endswith('_parallagi.wav'):
            continue
        stem = os.path.splitext(fn)[0]
        outdir = os.path.join(PARA_ROOT, f'mode3orthcnn-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'classify_parallagi.py'),
                  '--audio', os.path.join(PIECES, fn), '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'mode3orthcnn-{stem}', rc))
            continue
        results.append((f'mode3orthcnn-{stem}', align_agree(outdir)))

    json.dump(kept, open(os.path.join(WD, 'hymns.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('KEPT:', [(h['name'], f"p{h['p0']}.{h['l0']}-p{h['p1']}.{h['l1']}")
                    for h in kept])
    print('DROPPED:', dropped)
    print('PARALLAGI:', results)
    print('CRASHES:', crashes)

if __name__ == '__main__':
    main()
