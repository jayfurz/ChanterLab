#!/usr/bin/env python3
"""Extract neume glyphs from a born-digital VECTOR-OUTLINE Byzantine score PDF
(neume font converted to filled bezier paths, e.g. the Ioannou Anastasimatarion).

Not OMR in the fuzzy sense: each glyph is an exact filled path. Outline
conversion adds per-instance subpixel jitter, so clustering renders every
path in isolation (replayed onto a blank page — neighbours can't bleed in)
and matches 28x28 normalized bitmaps by hamming distance + size gate.
Red fills are martyria/fthora material, black fills are neumes.

Outputs (to --out dir):
  score_vec.json   glyphs [{cluster, x0,x1,y0,y1, page, line, red}] in reading
                   order + lyrics [{page, line, x0, x1, text}] + cluster stats
  atlas.png        every cluster's rendered representative labeled with its
                   id — the one-time legend-labeling surface

Usage: extract_vector_glyphs.py <pdf> <first_page> <last_page> --out DIR
       (pages 1-based inclusive)
"""
import json, os, sys
sys.path.append('/mnt/data/code/byzorgan-web/training-prototype/omr/.venv/lib/python3.11/site-packages')
import fitz
import numpy as np
from collections import Counter

BM = 28            # normalized bitmap side
HAM = 0.06         # max hamming distance (fraction of BM*BM) within a cluster
SZ = 1.2           # max width/height difference (pt) within a cluster
LINE_GAP = 14.0    # y gap that separates neume lines (pt)
RENDER_ZOOM = 6

def render_bits(dr):
    """replay the filled path alone on a blank page; return (bits, w, h, img)"""
    r = dr['rect']
    pad = 1.0
    w, h = r.width + 2 * pad, r.height + 2 * pad
    tmp = fitz.open()
    pg = tmp.new_page(width=max(w, 2), height=max(h, 2))
    sh = pg.new_shape()
    ox, oy = r.x0 - pad, r.y0 - pad
    mv = lambda p: fitz.Point(p.x - ox, p.y - oy)
    for it in dr['items']:
        if it[0] == 'l':
            sh.draw_line(mv(it[1]), mv(it[2]))
        elif it[0] == 'c':
            sh.draw_bezier(mv(it[1]), mv(it[2]), mv(it[3]), mv(it[4]))
        elif it[0] == 're':
            rc = it[1]
            sh.draw_rect(fitz.Rect(rc.x0 - ox, rc.y0 - oy, rc.x1 - ox, rc.y1 - oy))
        elif it[0] == 'qu':
            q = it[1]
            sh.draw_polyline([mv(q.ul), mv(q.ur), mv(q.lr), mv(q.ll), mv(q.ul)])
    sh.finish(fill=(0, 0, 0), color=None, even_odd=dr['even_odd'], closePath=True)
    sh.commit()
    pix = pg.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    tmp.close()
    # normalize: fit into BM x BM preserving aspect, centered
    from PIL import Image
    im = Image.fromarray(a)
    im.thumbnail((BM, BM))
    canvas = Image.new('L', (BM, BM), 255)
    canvas.paste(im, ((BM - im.width) // 2, (BM - im.height) // 2))
    bits = (np.asarray(canvas) < 128)
    return bits, r.width, r.height, canvas

def main():
    pdf, p0, p1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out = sys.argv[sys.argv.index('--out') + 1]
    os.makedirs(out, exist_ok=True)
    doc = fitz.open(pdf)
    glyphs, lyrics = [], []
    clusters = []           # (bits, w, h, img, n)
    for pno in range(p0 - 1, p1):
        pg = doc[pno]
        for dr in pg.get_drawings():
            if dr['type'] != 'f' or dr['fill'] is None:
                continue
            r_, g_, b_ = dr['fill']
            if r_ > 0.9 and g_ > 0.9 and b_ > 0.9:
                continue
            red = r_ > 0.3 and g_ < 0.2
            bits, w, h, img = render_bits(dr)
            best, barg = 1.0, None
            for ci, (cb, cw, ch, _, _) in enumerate(clusters):
                if abs(w - cw) > SZ or abs(h - ch) > SZ:
                    continue
                d = np.mean(bits != cb)
                if d < best:
                    best, barg = d, ci
            if barg is None or best > HAM:
                clusters.append([bits, w, h, img, 0])
                barg = len(clusters) - 1
            clusters[barg][4] += 1
            rc = dr['rect']
            glyphs.append({'cluster': barg, 'page': pno + 1, 'red': int(red),
                           'x0': round(rc.x0, 1), 'x1': round(rc.x1, 1),
                           'y0': round(rc.y0, 1), 'y1': round(rc.y1, 1)})
        for b in pg.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    if 'SKAlexander' in sp['font'] and sp['text'].strip():
                        lyrics.append({'page': pno + 1, 'text': sp['text'],
                                       'x0': round(sp['bbox'][0], 1),
                                       'x1': round(sp['bbox'][2], 1),
                                       'y0': round(sp['bbox'][1], 1)})
    # ---- line grouping per page ----
    li_global = 0
    for pno in sorted({g['page'] for g in glyphs}):
        pgl = [g for g in glyphs if g['page'] == pno]
        ys = sorted(g['y1'] for g in pgl)
        breaks = [i for i in range(1, len(ys)) if ys[i] - ys[i - 1] > LINE_GAP]
        edges = [ys[0] - 1] + [(ys[i - 1] + ys[i]) / 2 for i in breaks] + [ys[-1] + 1]
        for g in pgl:
            for li in range(len(edges) - 1):
                if edges[li] < g['y1'] <= edges[li + 1]:
                    g['line'] = li_global + li
                    break
        for w_ in lyrics:
            if w_['page'] != pno:
                continue
            w_['line'] = li_global + max((li for li in range(len(edges) - 1)
                                          if w_['y0'] > edges[li]), default=0)
        li_global += len(edges) - 1
    glyphs.sort(key=lambda g: (g['page'], g.get('line', 0), g['x0']))
    # ---- atlas ----
    from PIL import Image, ImageDraw
    n_cl = len(clusters)
    cell, cols = 96, 12
    rows = (n_cl + cols - 1) // cols
    atlas = Image.new('RGB', (cols * cell, rows * cell), 'white')
    dr_ = ImageDraw.Draw(atlas)
    for c, (_, w, h, img, n) in enumerate(clusters):
        big = img.resize((BM * 2, BM * 2), Image.NEAREST).convert('RGB')
        x, y = (c % cols) * cell, (c // cols) * cell
        atlas.paste(big, (x + (cell - BM * 2) // 2, y + 22))
        dr_.rectangle([x, y, x + cell - 1, y + cell - 1], outline='#bbb')
        dr_.text((x + 4, y + 2), f"{c} n={n}", fill='red' if any(
            g['cluster'] == c and g['red'] for g in glyphs) else 'black')
    atlas.save(os.path.join(out, 'atlas.png'))
    json.dump({'glyphs': glyphs, 'lyrics': lyrics,
               'clusters': {str(c): {'n': cl[4], 'w': round(cl[1], 1),
                                     'h': round(cl[2], 1)} for c, cl in enumerate(clusters)}},
              open(os.path.join(out, 'score_vec.json'), 'w'))
    n_lines = len({(g['page'], g.get('line')) for g in glyphs})
    print(f"{len(glyphs)} glyphs, {n_cl} clusters, {n_lines} lines, "
          f"{len(lyrics)} lyric spans -> {out}/")
    print('top clusters:', Counter(g['cluster'] for g in glyphs).most_common(15))

if __name__ == '__main__':
    main()
