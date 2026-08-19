#!/usr/bin/env python3
"""glt_match.py — match each corpus hymn's score text to its canonical GLT text.

The score lyric layer is unaccented and fragmented by the melisma
('τω','σταυ','ρω','ω'); glt_fetch.py gives the same hymns fully accented. Match
them and three problems get evidence at once:

  * SYL-01 gets the real word and inflection behind each lyric fragment
  * hymn BOUNDARIES get checked — a slice that runs into the next hymn shows up
    as text past the end of its GLT match, which is exactly the t01 bug that was
    fixed by hand with g0/g1
  * mis-slotted hymns (wrong mode, wrong service) surface as a poor best match

Comparison is on collapsed-normalised text: accents stripped, lowercase, letters
only, runs of one letter collapsed — because the melisma reprints the vowel once
per note, so 'ωωω' and 'ω' are the same word.

Usage:  glt_match.py [--workdir DIR] [--all-modes] [--min 0.55]
"""
import argparse
import difflib
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h
from glt_fetch import norm, collapse, OUT as GLT_JSON

# workdir name -> GLT mode key
WD_MODE = {'mode1': 'mode1', 'mode1-orthros': 'mode1', 'mode2': 'mode2',
           'mode2-orthros': 'mode2', 'mode3': 'mode3', 'mode3-orthros': 'mode3',
           'mode4': 'mode4', 'grave': 'grave', 'grave-orthros': 'grave',
           'pl1-vespers': 'pl1', 'pl1-compunction': 'pl1', 'pl2': 'pl2',
           'pl4': 'pl4', 'pl4-orthros': 'pl4'}


def score_text(h):
    """the hymn slice's lyric stream, in reading order, collapsed-normalised"""
    _, lyr = load_units_h(h)
    lyr = sorted(lyr, key=lambda w: (w['page'], w.get('line', 0), w['x0']))
    return collapse(norm(''.join(w['text'] for w in lyr)))


def best(s, cands):
    """highest matched-character coverage of the SCORE text by a GLT hymn"""
    out = []
    for g in cands:
        sm = difflib.SequenceMatcher(None, s, g['collapsed'], autojunk=False)
        cov = sum(b.size for b in sm.get_matching_blocks()) / max(len(s), 1)
        out.append((cov, g))
    out.sort(key=lambda x: -x[0])
    return out[:3]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--all-modes', action='store_true')
    ap.add_argument('--min', type=float, default=0.55)
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/glt_hymn_match.json')
    a = ap.parse_args()

    glt = json.load(open(GLT_JSON))
    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    rows = []
    for wd in wds:
        hy = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hy):
            continue
        name = os.path.basename(wd.rstrip('/'))
        mode = WD_MODE.get(name)
        cands = glt if (a.all_modes or not mode) else [g for g in glt if g['mode'] == mode]
        if not cands:
            cands = glt
        print(f'\n=== {name}  ({len(cands)} candidate GLT hymns)')
        for h in json.load(open(hy)):
            s = score_text(h)
            if len(s) < 12:
                print(f'  {h["name"][:24]:24s} NO LYRICS'); continue
            top = best(s, cands)
            cov, g = top[0]
            flag = 'ok ' if cov >= a.min else 'LOW'
            rows.append({'workdir': name, 'hymn': h['name'], 'coverage': round(cov, 3),
                         'glt_page': g['page'], 'glt_service': g['service'],
                         'glt_heading': g['heading'], 'glt_text': g['text'],
                         'score_chars': len(s), 'glt_chars': len(g['collapsed']),
                         'runner_up': round(top[1][0], 3) if len(top) > 1 else None})
            print(f'  {flag} {h["name"][:22]:22s} cov {cov:.2f}  '
                  f'{g["service"][:14]:14s} {g["text"][:52]}')
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=1)
    good = sum(1 for r in rows if r['coverage'] >= a.min)
    print(f'\n{good}/{len(rows)} matched at >= {a.min} coverage -> {a.out}')


if __name__ == '__main__':
    main()
