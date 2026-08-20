#!/usr/bin/env python3
"""anchor_sheet.py — the range starts with no opening martyria to anchor them.

leading_anchor() wants the RIGHT-ALIGNED martyria that announces a hymn's
starting pitch. For 6 of the 47 chanter-cut spans there is none in the three
units before the range, and the nearest martyria of any kind is 26, 34 or 97
units back — far enough that real sung notes intervene, so it cannot be naming
the range's first note.

Chanter, 2026-08-19: "some might start with a name of the hymn or something
maybe the mode title/intro and might be assumed or the martyria is there but
back further a bit because of the headings or subheadings … show me the glyphs
youre still stuck on and we will adjust."

Checked: these are not heading cases. Every intervening line carries 13-20 sung
units with lyrics under them. Each of the three distinct starts opens a fresh
line on a drop cap with no martyria printed before it, so the pitch looks
genuinely assumed rather than mislaid — but that is his call, not a guess to
make here.

Renders the end of the preceding line and the start of the range, side by side,
so the question is visible on the page.

Usage:  anchor_sheet.py [--workdir grave-orthros]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units
from score_degrees import leading_anchor
from kentimata_sheet import CACHE
from prep_hymn_annotator import find_pdf, render_page

TEXTS = '/mnt/data/chant-corpus/texts'
DEG = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']
ZOOM = 6


def band(pdf, page, line, units, cache, out):
    """Whole-line crop, so the margins are visible — that is where an opening
    martyria would be if there were one."""
    from PIL import Image
    im = Image.open(render_page(pdf, page, cache))
    ys = [u for u in units if u['pl'] == (page, line)]
    if not ys:
        return False
    y0 = min(u['y0'] for u in ys) - 16
    y1 = max(u['y1'] for u in ys) + 22
    im.crop((0, max(0, int(y0 * ZOOM)), im.width,
             min(im.height, int(y1 * ZOOM)))).save(out)
    return True


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--annotator-dir', default=os.path.normpath(
        os.path.join(here, '..', 'chant-reel', 'annotator')))
    ap.add_argument('--render-cache', default=CACHE)
    a = ap.parse_args()

    sc = {c['hymn']: c for c in
          json.load(open(f'{TEXTS}/scorecuts_{a.workdir}.json'))['cuts']}
    names = {s['span']: s for s in
             json.load(open(f'{TEXTS}/span_names_{a.workdir}.json'))['spans']}
    stuck = [h for h, c in sc.items()
             if leading_anchor(c['p0'], c['g0']) is None]

    pdf = find_pdf()
    outdir = os.path.join(a.annotator_dir, 'anchors')
    os.makedirs(outdir, exist_ok=True)
    items, cache = [], {}
    for h in sorted(stuck):
        c = sc[h]
        p0, g0 = c['p0'], c['g0']
        if p0 not in cache:
            cache[p0] = load_units(p0, 0, p0, 10 ** 6)[0]
        us = cache[p0]
        if g0 >= len(us):
            continue
        line = us[g0]['pl'][1]
        near = next((i for i in range(g0 - 1, -1, -1)
                     if us[i].get('mart_deg') is not None), None)
        rec = {'span': h, 'page': p0, 'g0': g0, 'line': line,
               'incipit': names.get(h, {}).get('incipit', ''),
               'lane': names.get(h, {}).get('lane'),
               'back': None if near is None else g0 - near,
               'back_deg': None if near is None else DEG[us[near]['mart_deg'] % 7],
               'imgs': []}
        for L in (line - 1, line):
            f = f'anchors/p{p0:03d}-l{L:02d}.png'
            if band(pdf, p0, L, us, a.render_cache,
                    os.path.join(a.annotator_dir, f)):
                rec['imgs'].append({'src': f, 'line': L,
                                    'role': 'the line before'
                                    if L == line - 1 else 'the range starts here'})
        items.append(rec)
        print(f"  {h}: page {p0} line {line} g0={g0}")
    json.dump({'items': items},
              open(os.path.join(a.annotator_dir, 'anchors.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'\n{len(items)} stuck range starts -> {outdir}')


if __name__ == '__main__':
    main()
