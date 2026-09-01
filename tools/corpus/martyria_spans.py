#!/usr/bin/env python3
"""martyria_spans.py -- the score's own checksums, span by span.

Chanter, 2026-08-23: "the scores have martyria interspersed throughout. why
cant we use those as a check -- if a note was wrong in between two martyria,
then we know something in that span is wrong. then we just flag it and reset
to the correct note (following the martyria)."

The RESET half already existed: degree_stream re-anchors at every cadence
martyria (octave-folded, so it corrects drift without hiding it). This adds
the FLAG half: each inter-martyria span is a checkable claim -- the intervals
inside it must carry the contour from one stated degree to the next. A span
that fails localises a wrong glyph to a few dozen notes, from the score
alone, before any audio is consulted. s42 is the proof: its final martyria
prints Ga, the chanter's ear said "ends on ga not dhi", and the derived
contour arrived on Dhi -- the book itself was already flagging the error.

Usage:
  martyria_spans.py --piece <annotator dir>            one piece
  martyria_spans.py --workdir grave-orthros --all      every span piece
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_degrees import degree_stream, leading_anchor, units_for   # noqa: E402
from hymn_align import DEG_NAME                                      # noqa: E402

LEGEND = '/mnt/data/chant-corpus/scores/legend_canon.json'


def spans_for(piece_dir):
    D = json.load(open(os.path.join(piece_dir, 'annotator_data.json')))
    sc = D['meta']['source']['score_range']
    u = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
    leg = json.load(open(LEGEND))
    tr = []
    degree_stream(u, leg, start=leading_anchor(sc['p0'], sc['g0']), trace=tr)
    out, prev = [], 0
    for t in tr:
        out.append({'gi0': prev, 'gi1': t['note'], 'letter': DEG_NAME[t['letter'] % 7],
                    'arrived': (DEG_NAME[t['before'] % 7] if t['before'] is not None else None),
                    'ok': bool(t['ok'])})
        prev = t['note'] + 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--piece')
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args()
    dirs = [a.piece] if a.piece else sorted(glob.glob(
        '/mnt/data/code/byzorgan-web-worktrees/chant-annotator/tools/chant-reel/'
        'annotator/data/%s-s*' % a.workdir)) if a.all else []
    report = {}
    for d in dirs:
        nm = os.path.basename(d.rstrip('/'))[13:18].strip('-')
        try:
            sp = spans_for(d.rstrip('/'))
        except Exception as e:
            print('%-5s error: %s' % (nm, str(e)[:60])); continue
        report[nm] = sp
        bad = [x for x in sp if not x['ok']]
        if not sp:
            print('%-5s no interior martyria -- no checksum' % nm)
        else:
            print('%-5s %d span(s), %d FAIL  %s' % (nm, len(sp), len(bad),
                  '  '.join('gi %d-%d %s (arrived %s)' % (x['gi0'], x['gi1'], x['letter'], x['arrived'])
                            for x in bad)))
    if a.json:
        json.dump(report, open(a.json, 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
