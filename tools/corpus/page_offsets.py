#!/usr/bin/env python3
"""page_offsets.py — align glyph boxes to page renders, per page.

The book PDF was assembled with PDFsam and has mixed page sizes: most pages
render 3498x4943, but a block of them renders 3572x5052. The glyph coordinates
were extracted against the smaller crop box, so on the taller pages every box
sits ~50 px too high. A single global mapping would put the tap targets in the
score picker on the wrong neumes for those pages, silently.

Scale is 6.0 px/point everywhere and that is not in doubt -- it is what the
existing renders use and it reproduces on both size classes. Only a translation
is unknown, so this solves dx/dy per page by maximising the ink that falls
inside the glyph boxes, and records the score so a page that does NOT align can
be seen rather than trusted.

Usage:  page_offsets.py [--from 519] [--to 557] [--out FILE]
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

R = '/mnt/data/chant-corpus/scores/page_renders'
G = '/mnt/data/chant-corpus/scores/glyphs'
OUT = '/mnt/data/chant-corpus/scores/page_offsets.json'
PT2PX = 6.0
# Pages that align well score ~0.37 mean ink inside the boxes; a wrong mapping
# scores ~0.10. 0.25 sits clear of both.
MIN_INK = 0.25


def solve(pno, coarse=16, fine=2):
    gf, rf = f'{G}/page{pno}.json', f'{R}/page{pno}.png'
    if not (os.path.exists(gf) and os.path.exists(rf)):
        return None
    g = json.load(open(gf)).get('glyphs', [])[:150]
    if len(g) < 20:
        return None
    im = Image.open(rf).convert('L')
    W, H = im.size
    a = np.asarray(im) < 128
    box = [(int(q['x0'] * PT2PX), int(q['y0'] * PT2PX),
            int(q['x1'] * PT2PX), int(q['y1'] * PT2PX)) for q in g]

    def score(dx, dy):
        ink = []
        for x0, y0, x1, y1 in box:
            x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
            if 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H:
                ink.append(a[y0:y1, x0:x1].mean())
        return float(np.mean(ink)) if len(ink) > len(box) * 0.6 else -1.0

    best = (-1.0, 0, 0)
    for dx in range(-96, 97, coarse):
        for dy in range(-160, 161, coarse):
            v = score(dx, dy)
            if v > best[0]:
                best = (v, dx, dy)
    _, bx, by = best
    for dx in range(bx - coarse, bx + coarse + 1, fine):
        for dy in range(by - coarse, by + coarse + 1, fine):
            v = score(dx, dy)
            if v > best[0]:
                best = (v, dx, dy)
    return {'page': pno, 'w': W, 'h': H, 'scale': PT2PX,
            'dx': best[1], 'dy': best[2], 'ink': round(best[0], 3),
            'ok': best[0] >= MIN_INK}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='lo', type=int, default=519)
    ap.add_argument('--to', dest='hi', type=int, default=557)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()

    have = json.load(open(a.out)) if os.path.exists(a.out) else {}
    bad = []
    for p in range(a.lo, a.hi + 1):
        r = solve(p)
        if not r:
            continue
        have[str(p)] = r
        if not r['ok']:
            bad.append(r)
        print('  page%-4d %4dx%-4d dx%+4d dy%+4d ink %.3f %s'
              % (p, r['w'], r['h'], r['dx'], r['dy'], r['ink'],
                 '' if r['ok'] else '<- DOES NOT ALIGN'))
    json.dump(have, open(a.out, 'w'), indent=1)
    print(f'\n{len(have)} pages mapped -> {a.out}')
    if bad:
        print(f'{len(bad)} page(s) below the {MIN_INK} ink floor: '
              + ', '.join(str(b["page"]) for b in bad))


if __name__ == '__main__':
    main()
