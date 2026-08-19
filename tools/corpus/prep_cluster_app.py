#!/usr/bin/env python3
"""prep_cluster_app.py — data for the interactive cluster classifier
(annotator/clusters.html): per cluster, several in-context COLOR crops from
the page renders (instance outlined), plus metadata, current chanter
identity (atlas_chanter.json), and font-match proposals as hints.

Writes <annotator>/data/clusters/{index.json, c<id>_<k>.png}.
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
    HERE, '..', 'chant-reel', 'annotator', 'data', 'clusters'))
Z = 6
CTX_X, CTX_UP, CTX_DN = 26.0, 16.0, 16.0    # context margin, pt
N_INST = 6


def main():
    os.makedirs(OUT, exist_ok=True)
    z = np.load(STORE, allow_pickle=True)
    bitmaps, W, H, counts = z['bitmaps'], z['w'], z['h'], z['counts']
    atlas = json.load(open(ATLAS))['clusters'] if os.path.exists(ATLAS) else {}
    matches = json.load(open(MATCHES)) if os.path.exists(MATCHES) else {}

    rendered = {int(os.path.basename(p)[4:7])
                for p in glob.glob(os.path.join(RENDERS, 'page*.png'))}
    inst = defaultdict(list)
    for pg in sorted(rendered):
        f = os.path.join(GLYPHS, f'page{pg:03d}.json')
        if not os.path.exists(f):
            continue
        for g in json.load(open(f))['glyphs']:
            inst[g['cluster']].append((pg, g))

    page_cache = {}

    def page(pg):
        if pg not in page_cache:
            if len(page_cache) > 20:
                page_cache.clear()
            page_cache[pg] = Image.open(
                os.path.join(RENDERS, f'page{pg:03d}.png'))
        return page_cache[pg]

    entries = []
    for c in np.argsort(-counts):
        c = int(c)
        pool = inst.get(c, [])
        if not pool:
            continue
        # spread across the book; prefer showing both red and black instances
        pool.sort(key=lambda x: x[0])
        reds = [p for p in pool if p[1]['red']]
        blacks = [p for p in pool if not p[1]['red']]
        picks = []
        for src in (blacks, reds):
            if not src:
                continue
            n = min(len(src), N_INST - len(picks)) if src is blacks else \
                min(len(src), max(1, N_INST - len(picks)))
            idx = np.linspace(0, len(src) - 1, n).astype(int)
            picks += [src[i] for i in idx]
        picks = picks[:N_INST]

        # normalized bitmap thumb
        bm = Image.fromarray((~bitmaps[c] * 255).astype(np.uint8)) \
            .resize((84, 84), Image.NEAREST)
        bm.save(os.path.join(OUT, f'c{c}_bm.png'))

        crops = []
        for k, (pg, g) in enumerate(picks):
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
            fn = f'c{c}_{k}.png'
            t.save(os.path.join(OUT, fn))
            crops.append({'file': fn, 'page': pg, 'red': int(g['red']),
                          'bbox': [round(g['x0'], 1), round(g['y0'], 1),
                                   round(g['x1'], 1), round(g['y1'], 1)],
                          'line': g.get('line')})

        a = atlas.get(str(c))
        m = matches.get(str(c), {}).get('matches', [])[:3]
        entries.append({
            'id': c, 'count': int(counts[c]),
            'w_pt': round(float(W[c]), 1), 'h_pt': round(float(H[c]), 1),
            'red_frac': round(float(np.mean([g['red'] for _, g in pool])), 2),
            'bitmap': f'c{c}_bm.png', 'crops': crops,
            'preset': ({'name': a['name'], 'interval': a.get('interval'),
                        'note': a.get('note', ''), 'source': 'chanter-atlas'}
                       if a else None),
            'hints': [{'name': x['name'], 'font': x['font'],
                       'score': x['score']} for x in m],
        })

    with open(os.path.join(OUT, 'index.json'), 'w') as f:
        json.dump({'clusters': entries}, f)
    n_pre = sum(1 for e in entries if e['preset'])
    print(f'{len(entries)} clusters, {n_pre} preset from chanter atlas -> {OUT}')


if __name__ == '__main__':
    main()
