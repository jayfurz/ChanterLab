#!/usr/bin/env python3
"""pair_by_tape.py — pair each melos with its parallagi by position on the tape.

Chanter: "the hymns always had a paralagi then melos right after of the same
hymn and length". That is a structural fact about the recording, and it is
directly checkable now that audio_recut.py can locate any piece inside its
source tape by envelope correlation (0.90-1.00 on every grave-orthros piece).

So: locate EVERY piece in the tape — parallagi and melos alike — order them by
offset, and pair each melos with the parallagi immediately before it.

Why not re_pair.py: that verifies a pairing by DTW single-step agreement, i.e.
by the aligner whose median onset error is 0.485 s and which movement agreement
cannot even measure honestly. Tape position is independent of all of that.

The pairing then yields the constraint the audio cutter is missing: a melos
should be about as long as its own parallagi, so a melos much shorter than its
parallagi is clipped, and by how much.

Usage:  pair_by_tape.py --workdir DIR [--apply]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_recut import envelope, locate, find_tape, HOP


def main():
    import numpy as np
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--min-corr', type=float, default=0.5)
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    hy = json.load(open(os.path.join(a.workdir, 'hymns.json')))
    pdirs = sorted({os.path.dirname(h['melos_audio']) for h in hy
                    if h.get('melos_audio')})
    rows, tapes = [], {}
    for pd in pdirs:
        tape = find_tape(os.path.join(pd, 'x.wav'))
        if not tape:
            print(f'  no tape for {os.path.basename(pd)}'); continue
        key = os.path.basename(tape)
        if key not in tapes:
            tapes[key] = envelope(tape, key)
        env = tapes[key]
        pieces = sorted(glob.glob(os.path.join(pd, '*.wav')))
        placed = []
        for w in pieces:
            if w.endswith('.recut.wav'):
                continue
            pe = envelope(w)
            if pe.size < 4:
                continue
            off, corr = locate(env, pe)
            if off is None or corr < a.min_corr:
                continue
            kind = ('parallagi' if 'parallagi' in os.path.basename(w).lower()
                    else 'melos' if 'melos' in os.path.basename(w).lower()
                    else 'other')
            placed.append({'path': w, 'kind': kind, 't0': off * HOP,
                           't1': (off + pe.size) * HOP,
                           'dur': pe.size * HOP, 'corr': round(corr, 3)})
        placed.sort(key=lambda r: r['t0'])
        for i, p in enumerate(placed):
            if p['kind'] != 'melos':
                continue
            prev = next((q for q in reversed(placed[:i])
                         if q['kind'] == 'parallagi'), None)
            rows.append({'workdir': name, 'melos': p['path'],
                         'melos_dur': round(p['dur'], 1),
                         'parallagi': prev['path'] if prev else None,
                         'par_dur': round(prev['dur'], 1) if prev else None,
                         'gap_s': round(p['t0'] - prev['t1'], 2) if prev else None,
                         'ratio': round(p['dur'] / prev['dur'], 3) if prev else None,
                         'corr': p['corr']})
    ok = [r for r in rows if r['ratio']]
    print(f'{name}: {len(rows)} melos located, {len(ok)} with a preceding parallagi')
    if ok:
        rr = sorted(r['ratio'] for r in ok)
        near = sum(1 for r in rr if 0.85 <= r <= 1.15)
        gg = sorted(r['gap_s'] for r in ok)
        print(f'  melos/parallagi length ratio: median {rr[len(rr)//2]:.2f}  '
              f'within +-15%: {near}/{len(rr)} ({100*near/len(rr):.0f}%)')
        print(f'  gap parallagi->melos: median {gg[len(gg)//2]:.2f} s')
        short = [r for r in ok if r['ratio'] < 0.85]
        print(f'  melos SHORTER than its parallagi by >15%: {len(short)} '
              f'(candidates for a clipped end)')
        for r in short[:8]:
            print('     %-28s melos %6.1fs vs parallagi %6.1fs (%.2f)'
                  % (os.path.basename(r['melos'])[:28], r['melos_dur'],
                     r['par_dur'], r['ratio']))
    jf = f'/mnt/data/chant-corpus/texts/pairs_{name}.json'
    json.dump(rows, open(jf, 'w'), indent=1)
    print('->', jf)


if __name__ == '__main__':
    main()
