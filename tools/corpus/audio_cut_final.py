#!/usr/bin/env python3
"""audio_cut_final.py — combine the two end estimates, capped by the next piece.

Two independent estimates of where a hymn ends, with complementary failures:

  audio_recut.py     RMS decay + corroborated whisper bounds. On grave-orthros:
                     6/25 clipped, median tail 0.28 s. Conservative — when it
                     finds no gap it stops early.
  audio_cut_bounded  searches only up to the next recorded piece (located by
                     envelope correlation). 9/24 clipped, median tail 0.47 s.
                     Longer tails, but when a hymn sings right up to the bound
                     it stops there, still sounding.

Neither dominates, and both are bounded above by the same hard fact: the audio
cannot run past the start of the next recorded piece. So take the trimmed START
from the RMS pass and the LATER of the two ends, capped by that bound. A too-long
tail is silence; a too-short one is a clipped note, and the chanter's complaint
was the clipped note.

Usage:  audio_cut_final.py --workdir DIR [--apply]
"""
import argparse
import json
import os
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    name = os.path.basename(a.workdir.rstrip('/'))
    T = '/mnt/data/chant-corpus/texts'
    rf, bf = f'{T}/recut_{name}.json', f'{T}/cutbound_{name}.json'
    if not (os.path.exists(rf) and os.path.exists(bf)):
        raise SystemExit('need recut_*.json and cutbound_*.json for this workdir')
    rms = {r['hymn']: r for r in json.load(open(rf))}
    bnd = {r['hymn']: r for r in json.load(open(bf))}
    out = []
    print('%-22s %8s %8s %8s %8s' % ('hymn', 'rms_end', 'bnd_end', 'final', 'bound'))
    for k, r in rms.items():
        b = bnd.get(k)
        if not b:
            continue
        start = r['new'][0]
        end = max(r['new'][1], b['new'][1])
        end = min(end, b['bound'])
        if end <= start:
            continue
        out.append({'workdir': name, 'hymn': k, 'tape': r['tape'],
                    'piece': r['piece'], 'new': [round(start, 3), round(end, 3)],
                    'cur': r['cur'], 'bound': b['bound'],
                    'd_end': round(end - r['cur'][1], 2)})
        print('%-22s %8.1f %8.1f %8.1f %8.1f'
              % (k[:22], r['new'][1], b['new'][1], end, b['bound']))
    jf = f'{T}/cutfinal_{name}.json'
    json.dump(out, open(jf, 'w'), indent=1)
    print(f'\n{len(out)} final cuts')
    if a.apply:
        for r in out:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(r['new'][0]), '-to', str(r['new'][1]),
                            '-ac', '1', '-ar', '44100',
                            r['piece'].replace('.wav', '.recut.wav')], check=True)
        print(f'wrote {len(out)} re-cut files')
    print('->', jf)


if __name__ == '__main__':
    main()
