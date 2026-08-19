#!/usr/bin/env python3
"""Onboard 'Prosomia 8 and exoposteilaria' tape.

locate_tracks over the full Anastasimatarion (pdf pages 2-673) finds ZERO
melos hymns: the tape's repertoire (automela prosomia, kathisma/kontakion
prologues, exaposteilaria incl. 'Ton nymfona sou', 'Gynaikes akoutisthite',
'Ton listin afthimeron') is chanted from the OLD Heirmologion of Ioannis
Protopsaltis (the chanter announces it on-tape, track 018/023) — a book we
have no glyphs for. Per-track best fuzzy blocks are 6-16 chars vs the
20-char threshold (pure noise, scattered p17-p433). So: no hymns to clean
(monotonic/genus vacuous), and only the book-independent parallagi anchor
lanes are built:
  - whisper lane: parallagi_dataset + parallagi_align ->
    parallagi/prosomia-<stem> for EVERY NNN_parallagi.wav with a transcript
    (no hymns exist to restrict to).
  - CNN lane: classify_parallagi (PAR_CNN=parallagi_cnn_r2.pt) +
    parallagi_align -> parallagi/prosomiacnn-<stem> for every parallagi wav.
wire_anchors/legend/melos/align_eval run afterwards but are vacuous with an
empty hymns.json.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
PIECES = f'{CORPUS}/pieces/Prosomia 8 and exoposteilaria'
WD = f'{CORPUS}/workdirs/prosomia'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ['PAR_CNN'] = f'{CORPUS}/models/parallagi_cnn_r2.pt'

def run(args, **kw):
    return subprocess.run([sys.executable] + args, **kw).returncode

def agree(outdir):
    sf = os.path.join(outdir, 'summary_full.json')
    return json.load(open(sf)).get('match_agreement') \
        if os.path.exists(sf) else None

def main():
    results, crashes = [], []
    stems = [os.path.splitext(fn)[0] for fn in sorted(os.listdir(PIECES))
             if fn.endswith('_parallagi.wav')]
    # whisper lane
    for stem in stems:
        whisper = os.path.join(PIECES, stem + '.json')
        if not os.path.exists(whisper):
            crashes.append((f'prosomia-{stem}', 'no transcript'))
            continue
        outdir = os.path.join(PARA_ROOT, f'prosomia-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'parallagi_dataset.py'),
                  '--audio', os.path.join(PIECES, stem + '.wav'),
                  '--whisper', whisper, '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'prosomia-{stem}', rc))
            continue
        results.append((f'prosomia-{stem}', agree(outdir)))
    # CNN lane
    for stem in stems:
        outdir = os.path.join(PARA_ROOT, f'prosomiacnn-{stem}')
        os.makedirs(outdir, exist_ok=True)
        rc = run([os.path.join(TOOLS, 'classify_parallagi.py'),
                  '--audio', os.path.join(PIECES, stem + '.wav'),
                  '--outdir', outdir])
        if rc == 0:
            rc = run([os.path.join(TOOLS, 'parallagi_align.py'), outdir])
        if rc != 0:
            crashes.append((f'prosomiacnn-{stem}', rc))
            continue
        results.append((f'prosomiacnn-{stem}', agree(outdir)))

    print('HYMNS: 0 (repertoire is Heirmologion, not in Anastasimatarion glyphs)')
    print('PARALLAGI:', results)
    print('CRASHES:', crashes)

if __name__ == '__main__':
    main()
