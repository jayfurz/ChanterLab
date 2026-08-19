#!/usr/bin/env python3
"""cluster7_sheet.py — is cluster 7 one neume or two?

Chanter, 2026-08-19, while ruling the kentimata figures: "most have psifiston
underneath and maybe gorgon or argo on top. about half have omalon underneath
and maybe gorgon or argon on top."

The atlas has psifiston as cluster 7 and omalon as cluster 36, and cluster 36
does not appear in those figures at all — so on the atlas he should have been
seeing psifiston every time. He was not, and the glyph boxes agree with him:
cluster 7's height is bimodal with an EMPTY GAP, 7295 instances at 6.2-6.4 pt
and 175 at 6.7-6.9 pt, nothing at 6.5 or 6.6. Rendered, the short one is a deep
U-shaped swoop (psifiston) and the tall one a flat level stroke — which is what
omalon means.

Inside the 78 kentimata-under figures the two sort almost perfectly by what sits
on top of them: omalon-shaped 37/38 carry an argon, psifiston-shaped 40/40 carry
a gorgon.

Neither neume carries an interval, so the degree stream is unaffected either
way. What is affected is the atlas, the beat model (omalon ties two notes and
carries no beat; cluster 36 was already found adding a spurious beat to ~261
units) and any later work that trusts cluster identity. Hence this sheet.

Usage:  cluster7_sheet.py [--annotator-dir DIR]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kentimata_sheet import crop, CACHE
from prep_hymn_annotator import find_pdf

TALL = 6.6              # the empty gap in the height histogram


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--annotator-dir', default=os.path.normpath(
        os.path.join(here, '..', 'chant-reel', 'annotator')))
    ap.add_argument('--render-cache', default=CACHE)
    a = ap.parse_args()

    tall, short = [], []
    for f in sorted(glob.glob('/mnt/data/chant-corpus/scores/glyphs/page*.json')):
        for g in json.load(open(f))['glyphs']:
            if g['cluster'] != 7:
                continue
            h = g['y1'] - g['y0']
            r = {'page': g['page'], 'line': g['line'], 'h': round(h, 2),
                 'box': [g['x0'], g['y0'], g['x1'], g['y1']]}
            (tall if h >= TALL else short).append(r)
    # controls spread across the book, not one engraver's page
    ctrl = [short[i * len(short) // 12] for i in range(12)]
    for r in tall:
        r['group'] = 'tall'
    for r in ctrl:
        r['group'] = 'short'

    pdf = find_pdf()
    outdir = os.path.join(a.annotator_dir, 'cluster7')
    os.makedirs(outdir, exist_ok=True)
    items = ctrl + tall
    for i, r in enumerate(items):
        r['img'] = f"cluster7/{r['group']}-{r['page']:03d}-{r['line']:02d}-{i}.png"
        crop(pdf, r, os.path.join(a.annotator_dir, r['img']), a.render_cache)
    json.dump({'items': [{k: v for k, v in r.items() if k != 'box'} for r in items],
               'n_tall': len(tall), 'n_short_total': len(short)},
              open(os.path.join(a.annotator_dir, 'cluster7.json'), 'w'), indent=1)
    print(f'{len(ctrl)} psifiston controls + {len(tall)} tall -> {outdir}')


if __name__ == '__main__':
    main()
