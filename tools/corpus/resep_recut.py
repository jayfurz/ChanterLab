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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h
import subprocess


def _is_speech(piece):
    b = os.path.basename(piece or '')
    return 'speech' in b or 'other' in b


def _nunits(h):
    if not h:
        return 0
    try:
        units, _ = load_units_h(h)
        return len(units)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max-loss', type=float, default=4.5)
    ap.add_argument('--lead', type=float, default=0.20)
    ap.add_argument('--tail', type=float, default=0.60)
    ap.add_argument('--min-ratio', type=float, default=0.6)
    ap.add_argument('--max-ratio', type=float, default=1.8)
    ap.add_argument('--rescue-speech', action='store_true',
                    help='also adopt for hymns whose current audio is a speech/'
                         'other piece. The ratio guard protects good audio; '
                         'these have none, so it is replaced by a pace check.')
    ap.add_argument('--min-spu', type=float, default=0.43)
    ap.add_argument('--max-spu', type=float, default=2.51)
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

    hymns = {h['name']: h for h in json.load(open(
        os.path.join(a.workdir, 'hymns.json')))}
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
        # Duration sanity. A segment run that is wildly longer or shorter than
        # the existing cut means the hymn was assigned to the wrong span, and
        # adopting it would replace good audio with the wrong material. This
        # guard exists because an earlier pass put gold hymn t03 on a 129.8 s
        # span in place of its correct 49.9 s.
        old = loc[r['hymn']]['cur']
        old_d = max(old[1] - old[0], 0.1)
        ratio = (e - s) / old_d
        # A hymn whose current audio is a speech/other piece has no good audio
        # to protect, so the ratio guard has nothing to compare against — the
        # existing cut is known wrong. Substitute a pace check instead: the
        # span must sing the score at a rate the rest of the corpus also uses.
        # 0.43-2.51 s/unit is the 2nd-75th percentile over the 115 hymns with
        # real audio (median 0.95). Spans well above that are whole-psalm runs
        # rather than one hymn, and belong to the boundary problem, not here.
        if a.rescue_speech and _is_speech(piece):
            spu = (e - s) / max(_nunits(hymns.get(r['hymn'])), 1)
            if not (a.min_spu <= spu <= a.max_spu):
                skip += 1
                print('%-22s SKIP  %.1fs at %.2f s/unit (speech rescue)'
                      % (r['hymn'][:22], e - s, spu))
                continue
        elif not (a.min_ratio <= ratio <= a.max_ratio):
            skip += 1
            print('%-22s SKIP  %.1fs vs existing %.1fs (x%.2f)'
                  % (r['hymn'][:22], e - s, old_d, ratio))
            continue
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
