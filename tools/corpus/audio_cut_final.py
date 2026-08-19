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

STATUS 2026-08-19: DO NOT USE. Measured worse than audio_recut.py alone.

  Same 157 tracks, one metric:
      original                          126 clipped (80%)
      audio_recut.py alone               52 clipped (33%)   <- SHIPPED
      + next-piece bound as hard cap     79 clipped (50%)
      + bound as extend-only             78 clipped (50%)
      + extension capped at 2.5 s        83 clipped (53%)

  Every refinement made it worse. The extend-only pass was a genuine bug fix —
  0 tracks shortened, 143 extended — and still did not recover, because the
  failure was never truncation: extending past the true end lands the file
  inside the NEXT hymn's audio, which the clipped metric cannot distinguish from
  a cut-off final note.

  The idea is sound (a hymn cannot run past the next recorded piece) but the
  bound available today is useless: it comes from the next located MELOS, and a
  parallagi normally sits between, so it permits tens of seconds where a real
  final-note decay is under a second. A usable bound needs the next piece of ANY
  kind, which needs the pieces to be correctly separated in the first place.
"""
import argparse
import json
import os
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max-extra', type=float, default=2.5,
                    help='most the next-piece bound may add to the RMS end')
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
        # The bound may sit BEFORE the RMS end when the next located piece is
        # close — applying it as a hard cap truncated tracks the RMS pass had
        # right and regressed the corpus from 36% clipped to 50%. The bound may
        # only ever EXTEND: never cut below what RMS already found.
        rms_end = r['new'][1]
        # The bound is the next located MELOS, but a parallagi normally sits
        # between two melos tracks, so that bound is far too loose: extending
        # toward it runs through the parallagi and the file ends mid-sound
        # again (corpus went 36% -> 50% "clipped" even though no cut was
        # shortened — the extensions overshot). A real final-note decay is
        # short, so cap how far the bound may extend a cut.
        ceiling = min(b['bound'], rms_end + a.max_extra)
        cand = min(b['new'][1], ceiling)
        end = max(rms_end, cand)
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
