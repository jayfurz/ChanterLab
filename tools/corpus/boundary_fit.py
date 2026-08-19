#!/usr/bin/env python3
"""boundary_fit.py — re-cut score slices with drop caps as HARD constraints.

Chanter: "the drop cap is the dead giveaway" for where a hymn starts, and "we
can over split and then combine in another pass". So:

  * Drop caps partition the book into SEGMENTS. A segment runs from one drop cap
    to just before the next. This is the over-split.
  * A hymn is one or more CONSECUTIVE segments — never a fraction of one. That
    is the hard constraint, and it is what makes the combine pass necessary,
    because several things that carry a drop cap are not hymns on their own:
      - "the quick short verses after lord i have cried ... should be treated as
        one single hymn"
      - "the verse preceding the stichera ... is actually attached to the
        following hymn"
      - "the same with the glory and both now followed by the theotokia"

The objective deliberately avoids the GLT text, which is not yet reliable enough
to move a boundary by. It uses the recording instead: the audio was already
re-cut per hymn in an earlier session, so a hymn's notated length and its
recorded length must agree under ONE tempo for the tape. beats come from
beats_seq (the chanter-corrected duration model), seconds from the melos audio.

Writes proposals; never edits hymns.json, because re-cutting re-indexes pins.

Usage:  boundary_fit.py --workdir DIR [--max-seg 6]

STATUS 2026-08-18: structurally sound, NOT yet converged. Do not apply blind.

  On grave-orthros it holds t03 in place (independently verified as correct) and
  leaves t09/t13 alone, and mean deviation of implied tempo fell 5.35 -> 0.588
  beats/s across three fixes to the DP itself:
    * a displacement prior, because without it the fit slid all 25 hymns seven
      pages to wherever the durations happened to tile best;
    * a gap transition, because the tape does NOT record every hymn in the book
      and forcing hymns to tile segments contiguously made the first drift
      snowball;
    * explicit span bookkeeping, because reconstructing the span from the
      current DP column attributed skipped tails to the previous hymn (t31 came
      out as 34 segments with 0 beats).

  What is still wrong: several hymns land at implausible tempi — t28 at 0.69 and
  t17 at 0.94 beats/s (slice too short for its audio), t06 at 5.92 (too long).
  A correct fit should have every hymn near one tempo. Likely causes, in order:
  the chanter's structural exceptions are not encoded (the ~15 short verses
  after Lord I Have Cried are ONE hymn; verse+stichera and Glory/Both Now+
  theotokion are single units), so the segment-to-hymn grouping is still free to
  be wrong; and the audio itself is known to be cut slightly early at both ends.
"""
import argparse
import glob
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h, beats_seq

DROPCAPS = '/mnt/data/chant-corpus/scores/dropcaps.json'


def segments(p0, p1):
    """book segments in [p0, p1], each starting at a drop cap"""
    dc = json.load(open(DROPCAPS))
    caps = sorted({(d['page'], d['line']) for d in dc if p0 <= d['page'] <= p1 + 1})
    segs = []
    for i, c in enumerate(caps[:-1]):
        segs.append((c, caps[i + 1]))
    return segs


def audio_seconds(path):
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                              'format=duration', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return None


def beats_of_span(h, a, b):
    cand = dict(h, p0=a[0], l0=a[1], p1=b[0], l1=b[1])
    cand.pop('g0', None); cand.pop('g1', None)
    try:
        u, _ = load_units_h(cand)
    except Exception:
        return 0.0
    return sum(beats_seq(u)) if u else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--max-seg', type=int, default=6,
                    help='most segments one hymn may absorb')
    ap.add_argument('--anchor', type=float, default=0.6,
                    help='cost per LINE of displacement from the current slice; '
                         'the existing boundaries are roughly right (54% already '
                         'sit exactly on a drop cap), so the fit must snap them '
                         'to the nearest correct one, not relocate the hymn')
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/boundary_fit.json')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    hl = sorted(json.load(open(os.path.join(a.workdir, 'hymns.json'))),
                key=lambda h: (h['p0'], h['l0']))
    lo = min(h['p0'] for h in hl); hi = max(h['p1'] for h in hl)
    segs = segments(lo, hi)
    print(f'{name}: {len(hl)} hymns, {len(segs)} drop-cap segments over '
          f'pages {lo}-{hi}')

    secs = []
    for h in hl:
        w = os.path.join(a.workdir, 'melos_' + h['name'], 'audio.wav')
        secs.append(audio_seconds(w) if os.path.exists(w) else None)
    known = [s for s in secs if s]
    if len(known) < 3:
        sys.exit('not enough melos audio to fit a tempo')

    # cache beats for every allowed segment run
    B = {}
    for i in range(len(segs)):
        for n in range(1, a.max_seg + 1):
            if i + n > len(segs):
                break
            B[(i, n)] = beats_of_span(hl[0], segs[i][0], segs[i + n - 1][1])

    # tempo from the CURRENT slices, as a starting scale
    cur_b = [sum(beats_seq(load_units_h(h)[0])) for h in hl]
    ratios = [b / s for b, s in zip(cur_b, secs) if s and b]
    tempo = sorted(ratios)[len(ratios) // 2]           # beats per second
    print(f'tempo prior: {tempo:.3f} beats/s (median of current slices)')

    n, m = len(hl), len(segs)
    INF = float('inf')
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    P = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for j in range(m + 1):
        D[0][j] = 0.0                                   # leading segments free
        P[0][j] = (0, j - 1, (0, 0)) if j else None
    for i in range(1, n + 1):
        s = secs[i - 1]
        for j in range(1, m + 1):
            for k in range(1, min(a.max_seg, j) + 1):
                prev = D[i - 1][j - k]
                if prev == INF:
                    continue
                b = B.get((j - k, k), 0.0)
                if s and b > 0:
                    c = abs(math.log(b / (tempo * s)))
                elif b <= 0:
                    c = 3.0
                else:
                    c = 0.5
                # displacement prior: keep the hymn where it already is unless
                # the audio strongly says otherwise
                sp, sl = segs[j - k][0]
                h0 = hl[i - 1]
                dist = abs((sp - h0['p0']) * 12 + (sl - h0['l0']))
                c += a.anchor * min(dist, 40)
                if prev + c < D[i][j]:
                    D[i][j] = prev + c
                    P[i][j] = (i - 1, j - k, (j - k, j))
            # the tape does NOT record every hymn in the book, so segments may
            # be left unassigned BETWEEN hymns. Without this the first drift
            # snowballs: each hymn is forced to start exactly where the previous
            # one ended and the run lengths run away.
            if D[i][j - 1] < D[i][j] and P[i][j - 1] is not None:
                D[i][j] = D[i][j - 1]
                P[i][j] = P[i][j - 1]      # keeps the ORIGINAL span, not (pj, j)
    jend = min(range(1, m + 1), key=lambda j: D[n][j])
    path, i, j = [], n, jend
    while i > 0:
        pi, pj, span = P[i][j]
        path.append((i - 1, span[0], span[1]))
        i, j = pi, pj
    path.reverse()

    out, moved = [], 0
    for hi_, j0, j1 in path:
        h = hl[hi_]
        a0, b1 = segs[j0][0], segs[j1 - 1][1]
        prop = [a0[0], a0[1], b1[0], b1[1]]
        cur = [h['p0'], h['l0'], h['p1'], h['l1']]
        mv = prop != cur
        moved += mv
        b = B.get((j0, j1 - j0), 0.0)
        s = secs[hi_]
        out.append({'workdir': name, 'hymn': h['name'], 'current': cur,
                    'proposed': prop, 'n_segments': j1 - j0,
                    'beats': round(b, 1), 'audio_s': round(s, 1) if s else None,
                    'implied_bps': round(b / s, 3) if s and b else None,
                    'moved': mv})
        star = '->' if mv else '  '
        print(f'  {star} {h["name"][:20]:20s} {cur[0]}:{cur[1]}-{cur[2]}:{cur[3]}'
              f'  =>  {prop[0]}:{prop[1]}-{prop[2]}:{prop[3]}  '
              f'{j1-j0} seg  {b:6.1f} beats / {s or 0:5.1f}s = '
              f'{(b/s if s and b else 0):.2f} b/s')
    json.dump(out, open(a.out, 'w'), indent=1)
    good = [r['implied_bps'] for r in out if r['implied_bps']]
    if good:
        med = sorted(good)[len(good) // 2]
        spread = sum(abs(g - med) for g in good) / len(good)
        print(f'\n{moved}/{len(out)} moved | tempo {med:.2f} b/s, mean abs '
              f'deviation {spread:.3f} (lower = slices agree with the audio)')
    print(f'-> {a.out}')


if __name__ == '__main__':
    main()
