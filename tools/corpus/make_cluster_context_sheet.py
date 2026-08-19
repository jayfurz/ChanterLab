#!/usr/bin/env python3
"""make_cluster_context_sheet.py — chanter review sheet for cluster identities
with REAL PAGE CONTEXT: for every cluster, 3 instances cropped from the color
page renders with generous surroundings and the instance outlined in blue.

Fixes the two blind spots of cluster_match_sheet.png (chanter feedback
2026-08-18): no color (red gorgon/martyria/fthora looked black) and no
context (in-combination-only marks like klasma/apli could not be judged,
and compound structure was invisible).

Output: <annotator>/cluster_context_sheet.png  (served by serve.py)
"""
import glob
import json
import os
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
RENDERS = '/mnt/data/chant-corpus/scores/page_renders'
STORE = '/mnt/data/chant-corpus/scores/clusters.npz'
ATLAS = '/mnt/data/chant-corpus/scores/atlas_chanter.json'
MATCHES = '/mnt/data/chant-corpus/scores/cluster_font_matches.json'
OUT = os.path.normpath(os.path.join(
    HERE, '..', 'chant-reel', 'annotator', 'cluster_context_sheet.png'))
Z = 6                      # render zoom (px per pt)
CTX_X, CTX_UP, CTX_DN = 22.0, 14.0, 14.0    # context margin around instance, pt
TILE_H = 150               # context crop display height, px
N_INST = 3


def main():
    z = np.load(STORE, allow_pickle=True)
    counts = z['counts']
    chanter = {int(k): v for k, v in
               json.load(open(ATLAS))['clusters'].items()}
    matches = json.load(open(MATCHES)) if os.path.exists(MATCHES) else {}

    rendered = {int(os.path.basename(p)[4:7])
                for p in glob.glob(os.path.join(RENDERS, 'page*.png'))}
    inst = defaultdict(list)          # cluster -> [(page, glyph), ...]
    for pg in sorted(rendered):
        f = os.path.join(GLYPHS, f'page{pg:03d}.json')
        if not os.path.exists(f):
            continue
        for g in json.load(open(f))['glyphs']:
            inst[g['cluster']].append((pg, g))

    order = list(np.argsort(-counts))
    rows = []
    page_cache = {}

    def page(pg):
        if pg not in page_cache:
            if len(page_cache) > 24:
                page_cache.clear()
            page_cache[pg] = Image.open(os.path.join(RENDERS, f'page{pg:03d}.png'))
        return page_cache[pg]

    for c in order:
        pool = inst.get(int(c), [])
        if not pool:
            continue
        pool.sort(key=lambda x: x[0])
        picks = ([pool[0], pool[len(pool) // 2], pool[-1]]
                 if len(pool) >= N_INST else pool)
        tiles = []
        for pg, g in picks:
            im = page(pg)
            x0 = max(0, (g['x0'] - CTX_X) * Z)
            x1 = min(im.width, (g['x1'] + CTX_X) * Z)
            y0 = max(0, (g['y0'] - CTX_UP) * Z)
            y1 = min(im.height, (g['y1'] + CTX_DN) * Z)
            t = im.crop((int(x0), int(y0), int(x1), int(y1))).convert('RGB')
            dr = ImageDraw.Draw(t)
            dr.rectangle([g['x0'] * Z - x0, g['y0'] * Z - y0,
                          g['x1'] * Z - x0, g['y1'] * Z - y0],
                         outline=(30, 90, 255), width=3)
            s = TILE_H / t.height
            t = t.resize((max(1, int(t.width * s)), TILE_H), Image.LANCZOS)
            tiles.append((pg, t))
        red_frac = np.mean([g['red'] for _, g in pool])
        rows.append((int(c), tiles, red_frac))

    W = 2200
    ROW_H = TILE_H + 46
    sheet = Image.new('RGB', (W, ROW_H * len(rows) + 20), 'white')
    dr = ImageDraw.Draw(sheet)
    y = 8
    for c, tiles, red_frac in rows:
        ch = chanter.get(c)
        m = matches.get(str(c), {})
        top = m.get('matches', [{}])[0]
        label = (f"cluster {c}   n={int(counts[c])}   "
                 f"{'RED ' if red_frac > 0.5 else ''}"
                 + (f"CHANTER: {ch['name']}" if ch else
                    f"match? {top.get('name', '?')} ({top.get('score', '')})"))
        dr.text((10, y), label, fill=(180, 0, 0) if ch else (0, 0, 0))
        x = 10
        for pg, t in tiles:
            if x + t.width > W - 10:
                break
            sheet.paste(t, (x, y + 18))
            dr.text((x, y + 18 + TILE_H + 2), f'p{pg}', fill=(120, 120, 120))
            x += t.width + 24
        y += ROW_H
    sheet.save(OUT)
    print(f'{len(rows)} clusters -> {OUT}')


if __name__ == '__main__':
    main()
