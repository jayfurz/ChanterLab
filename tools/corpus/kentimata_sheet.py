#!/usr/bin/env python3
"""kentimata_sheet.py — a review sheet for the figures whose key cannot say
which way round the oligon and the kentimata are.

Chanter, 2026-08-19: "yes oligon kentimata are two notes … the other variation
is the kentimata under the oligon", and separately "kentimata over oligon never
have klasma/apli ever". load_units now splits the figure into its two notes and
reads the order off the GEOMETRY, because the unit key cannot always carry it:

    6|17ab   2609   'ab' is measured against the oligon -> unambiguous, above
    6|17be    942   unambiguous, below
    7|17ab+6ab 1012 'ab' is measured against the PSIFISTON, so both the oligon
                    and the kentimata are 'above the base' and the key says
                    nothing about which of them is above the OTHER.

On the geometry those 1012 come apart 934 above / 78 below, and the split is
bimodal with a wide empty middle (below +4.65..+4.85 pt, above -5.15..-4.70 pt),
so it is not a threshold sitting in noise. But the only evidence that the 78 are
the real second variant rather than an extraction artifact is the chanter's eye,
which is what this sheet is for.

Renders one crop per figure, plus calibration crops from the two unambiguous
keys, into <annotator>/kentimata/ with a sheet at <annotator>/kentimata.html —
so it is reachable over the path he already uses,
https://annotator.lab.alwaysdobetterllc.com/kentimata.html

Usage:
  kentimata_sheet.py [--annotator-dir DIR] [--limit N]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hymn_align as H
from prep_hymn_annotator import find_pdf, render_page

ZOOM = 6                       # matches the cached page renders (432 dpi)
PAD_X, PAD_UP, PAD_DN = 26, 20, 16     # pt of context around the figure
CACHE = '/mnt/data/chant-corpus/scores/page_renders'


def collect():
    """Every split figure, with the pre-split key and the ken-vs-oligon offset."""
    rows = []
    orig = H._split_kentimata

    def spy(pl, mine, fig, oli, ken):
        base = max([x for x in mine if not x['red']
                    and x['cluster'] not in H.SILENT_BLACK
                    and x['cluster'] not in H.MARK_ONLY],
                   key=lambda x: (x['x1'] - x['x0']) * (x['y1'] - x['y0']))
        marks = []
        for x in mine:
            if x is base or x['red'] or x['cluster'] in H.SILENT_BLACK:
                continue
            pos = ('ab' if (x['y0'] + x['y1']) / 2
                   < (base['y0'] + base['y1']) / 2 - 1 else 'be')
            marks.append(f"{x['cluster']}{pos}")
        kc = (ken['y0'] + ken['y1']) / 2
        oc = (oli['y0'] + oli['y1']) / 2
        rows.append({
            'page': pl[0], 'line': pl[1],
            'key': f"{base['cluster']}|{'+'.join(sorted(marks))}",
            'below': kc > oc + 1, 'dy': round(kc - oc, 2),
            'box': [min(x['x0'] for x in mine), min(x['y0'] for x in mine),
                    max(x['x1'] for x in mine), max(x['y1'] for x in mine)],
        })
        return orig(pl, mine, fig, oli, ken)

    H._split_kentimata = spy
    pages = sorted(int(re.search(r'(\d+)', os.path.basename(f)).group(1))
                   for f in glob.glob('/mnt/data/chant-corpus/scores/glyphs/page*.json'))
    for p in pages:
        try:
            H.load_units(p, 0, p, 10 ** 6)
        except Exception:
            continue
    H._split_kentimata = orig
    return rows


def crop(pdf, r, out, cache):
    from PIL import Image
    im = Image.open(render_page(pdf, r['page'], cache))
    x0, y0, x1, y1 = r['box']
    box = (max(0, int((x0 - PAD_X) * ZOOM)), max(0, int((y0 - PAD_UP) * ZOOM)),
           min(im.width, int((x1 + PAD_X) * ZOOM)),
           min(im.height, int((y1 + PAD_DN) * ZOOM)))
    im.crop(box).save(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--annotator-dir', default=os.path.normpath(
        os.path.join(here, '..', 'chant-reel', 'annotator')))
    ap.add_argument('--render-cache', default=CACHE)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    rows = collect()
    pdf = find_pdf()
    outdir = os.path.join(a.annotator_dir, 'kentimata')
    os.makedirs(outdir, exist_ok=True)

    amb = [r for r in rows if r['key'] == '7|17ab+6ab' and r['below']]
    amb.sort(key=lambda r: (r['page'], r['line']))
    if a.limit:
        amb = amb[:a.limit]
    # calibration: the two keys that ARE unambiguous, spread across the book so
    # he is not calibrating on one engraver's page
    def sample(key, below, n=6):
        xs = [r for r in rows if r['key'] == key and r['below'] == below]
        xs.sort(key=lambda r: (r['page'], r['line']))
        return [xs[i * len(xs) // n] for i in range(n)] if len(xs) >= n else xs
    cal = ([dict(r, group='cal-above') for r in sample('6|17ab', False)]
           + [dict(r, group='cal-below') for r in sample('6|17be', True)])
    for r in amb:
        r['group'] = 'ambiguous'

    items = cal + amb
    for i, r in enumerate(items):
        r['img'] = f"kentimata/{r['group']}-{r['page']:03d}-{r['line']:02d}-{i}.png"
        crop(pdf, r, os.path.join(a.annotator_dir, r['img']), a.render_cache)
        print(f"  {r['img']}", flush=True)

    json.dump({'items': [{k: v for k, v in r.items() if k != 'box'} for r in items],
               'n_ambiguous': len(amb)},
              open(os.path.join(a.annotator_dir, 'kentimata.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f"\n{len(cal)} calibration + {len(amb)} ambiguous crops -> {outdir}")


if __name__ == '__main__':
    main()
