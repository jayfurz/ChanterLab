#!/usr/bin/env python3
"""Onboard Mode 3 vespers (vasilikos tape, pdf pages 170-253 -> vespers ends
~p186): corrected hymns.json + parallagi dirs.

locate_tracks.py output could not be used as-is: the tape's whisper transcript
is heavily hallucinated on melismatic singing, so locate_tracks classified the
clearly-spoken psalm-verse recitations (007/008/009/010 speech pieces) as
melos and missed most real melos pieces. Rows were rebuilt by hand from the
glyph lyric stream (pages 170-186) + content words / word-timestamps /
durations of each piece transcript:

  002 kyrie-ekekraxa      p170.2-170.6   1st invocation (168s, ~48s/line)
  003 katefthynthito      p170.6-171.2   2nd invocation + katefthynthito
                                         (003 head words = p170.7-9)
  006 paidefsei-me        p171.10-172.1  verse (head words match p171.10-11)
  011 ekekraxa-pros-se    p174.1-174.4   verse (head words match p174.1-2)
  013 to-stavro-sou       p175.3-176.7   Exagage(mel)+To stavro sou+Eme
                                         ypomenousi+Pefotistai; 'kath ekastin
                                         prosferei' heard at t=255 = p175.11
  015 ek-vatheon-doxazo   p176.7-177.5   inferred by continuity+duration
                                         (LOW CONFIDENCE, no content words)
  016 ean-anomias         p178.1-178.10  Ean anomias(head words)+Ymnoumen
                                         (MED confidence on end line)
  018 pos-mi-thavmasomen  p181.9-184.3   dogmatikon; 'To pathei sou Christe'
                                         heard at t=377 = p182.11; 845s ~= 28
                                         lines at ~30s/line -> ends p184.2
  019 ina-to-genos-frag   p185.10-185.14 32s fragment 'eafto synanestisas...'
                                         (locate_tracks match 0.58)
  023 asporos             p186.1-186.12  Doxa/Kai nyn theotokion (announced
                                         by 020_other)

Dropped locate_tracks rows: 007/008/009/010 (speech/other recitations, not
melos). Tape appears to skip p177.5-178.0 (Genithito+Ton Stavron sou) and
p184.3-185.9 (Kai gar, Theos yparchon, To oiko sou, start of Ina to genos).

Parallagi pairing (this tape sings melos first, parallagi after; pairing by
adjacency + duration): 004->kyrie-ekekraxa, 005->katefthynthito,
014->ek-vatheon-doxazo (10s intonation only), 017->pos-mi-thavmasomen,
022->asporos (021 is an earlier take, used as fallback).
Wire parallagi_dir only when parallagi_align match_agreement >= 0.4.
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
PIECES = f'{CORPUS}/pieces/mode 3 Anastasimatarion 1 vespers vasilikos'
WD = f'{CORPUS}/workdirs/mode3'
PARA_ROOT = f'{CORPUS}/parallagi'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROWS = [
    ('kyrie-ekekraxa',      170, 2, 170, 6,  '002_melos', ['004_parallagi']),
    ('katefthynthito',      170, 6, 171, 2,  '003_melos', ['005_parallagi']),
    ('paidefsei-me',        171, 10, 172, 1, '006_melos', []),
    ('ekekraxa-pros-se',    174, 1, 174, 4,  '011_melos', []),
    ('to-stavro-sou',       175, 3, 176, 7,  '013_melos', []),
    ('ek-vatheon-doxazo',   176, 7, 177, 5,  '015_melos', ['014_parallagi']),
    ('ean-anomias',         178, 1, 178, 10, '016_melos', []),
    ('pos-mi-thavmasomen',  181, 9, 184, 3,  '018_melos', ['017_parallagi']),
    ('ina-to-genos-frag',   185, 10, 185, 14, '019_melos', []),
    ('asporos',             186, 1, 186, 12, '023_melos',
     ['022_parallagi', '021_parallagi']),
]

def build_parallagi(stem):
    audio = os.path.join(PIECES, stem + '.wav')
    whisper = os.path.join(PIECES, stem + '.json')
    if not (os.path.exists(audio) and os.path.exists(whisper)):
        return None, 'missing input'
    outdir = os.path.join(PARA_ROOT, f'mode3-{stem}')
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'parallagi_dataset.py'),
                        '--audio', audio, '--whisper', whisper, '--outdir', outdir])
    if r.returncode != 0:
        return None, f'dataset rc={r.returncode}'
    r = subprocess.run([sys.executable,
                        os.path.join(TOOLS, 'parallagi_align.py'), outdir])
    if r.returncode != 0:
        return None, f'align rc={r.returncode}'
    sf = os.path.join(outdir, 'summary_full.json')
    if not os.path.exists(sf):
        return None, 'no summary_full.json'
    agree = json.load(open(sf)).get('match_agreement', 0.0)
    return (outdir, agree), None

def main():
    hymns, wired, unwired = [], [], []
    for name, p0, l0, p1, l1, melos, para_cands in ROWS:
        row = {'name': name, 'p0': p0, 'l0': l0, 'p1': p1, 'l1': l1,
               'melos_audio': os.path.join(PIECES, melos + '.wav'),
               'melos_whisper': os.path.join(PIECES, melos + '.json'),
               'parallagi_track': para_cands[0] + '.wav' if para_cands else None,
               'parallagi_dir': None, 'genus': 'diatonic'}
        for stem in para_cands:
            res, err = build_parallagi(stem)
            if err:
                unwired.append((name, stem, err))
                continue
            outdir, agree = res
            if agree >= 0.4:
                row['parallagi_dir'] = outdir
                row['parallagi_track'] = stem + '.wav'
                wired.append((name, stem, agree))
                break
            unwired.append((name, stem, f'agreement {agree}'))
        hymns.append(row)
    os.makedirs(WD, exist_ok=True)
    json.dump(hymns, open(os.path.join(WD, 'hymns.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('HYMNS:', [h['name'] for h in hymns])
    print('WIRED:', wired)
    print('UNWIRED:', unwired)

if __name__ == '__main__':
    main()
