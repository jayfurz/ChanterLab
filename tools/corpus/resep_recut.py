#!/usr/bin/env python3
"""resep_recut.py — RESEP-02: cut each hymn at its silence-bounded segment edges.

This is the payoff of the rebuild. Every earlier cutter had to SEARCH for the
end and had no principled place to stop:
    unbounded silence walk      ran into following hymns (+480 s)
    padded forced-align window  final melisma smeared to the window edge (+18.45 s)
    next-melos bound            a parallagi sits between, so it permits tens of
                                seconds; measured WORSE than no bound at all
                                (33% clipped -> 50% -> 53%)

A segment edge is not a search result. tape_segments.py derives it from real
silence in the recording, and tape_solve.py has established which hymn occupies
which segment. So the cut is simply the segment, and the hymn's end is bounded
by the next segment's start by construction.

Only assigned hymns are cut, and only where identification is confident — an
uncertain assignment must not move audio.

Usage:  resep_recut.py --workdir DIR [--apply] [--max-loss 4.5]
"""
import argparse
import json
import os
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max-loss', type=float, default=4.5)
    ap.add_argument('--lead', type=float, default=0.20)
    ap.add_argument('--tail', type=float, default=0.60)
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    af = f'/mnt/data/chant-corpus/texts/tapeassign_{name}.json'
    rf = f'/mnt/data/chant-corpus/texts/recut_{name}.json'
    if not os.path.exists(af):
        raise SystemExit(f'no assignment at {af} — run tape_solve.py')
    asg = json.load(open(af))['assigned']
    loc = {r['hymn']: r for r in json.load(open(rf))} if os.path.exists(rf) else {}
    tape = next((loc[h]['tape'] for h in loc), None)
    if tape is None:
        raise SystemExit('no tape path (need recut_*.json)')

    out, skip = [], 0
    print('%-22s %9s %9s %8s %8s' % ('hymn', 'seg_t0', 'seg_t1', 'dur', 'lpt'))
    for r in asg:
        if r['lpt'] > a.max_loss:
            skip += 1
            continue
        piece = loc.get(r['hymn'], {}).get('piece')
        if not piece:
            skip += 1
            continue
        s = max(0.0, r['t0'] - a.lead)
        e = r['t1'] + a.tail
        out.append({'workdir': name, 'hymn': r['hymn'], 'tape': tape,
                    'piece': piece, 'new': [round(s, 3), round(e, 3)],
                    'dur': round(e - s, 2), 'lpt': r['lpt'],
                    'old': loc[r['hymn']]['cur']})
        print('%-22s %9.1f %9.1f %8.1f %8.2f'
              % (r['hymn'][:22], r['t0'], r['t1'], e - s, r['lpt']))
    jf = f'/mnt/data/chant-corpus/texts/resepcut_{name}.json'
    json.dump(out, open(jf, 'w'), indent=1)
    print(f'\n{len(out)} cut from segment edges, {skip} skipped '
          f'(unassigned or above {a.max_loss}/tok)')
    if a.apply:
        for r in out:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(r['new'][0]), '-to', str(r['new'][1]),
                            '-ac', '1', '-ar', '44100',
                            r['piece'].replace('.wav', '.recut.wav')], check=True)
        print(f'wrote {len(out)} files')
    print('->', jf)


if __name__ == '__main__':
    main()
