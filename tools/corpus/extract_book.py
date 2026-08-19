#!/usr/bin/env python3
"""Book-wide vector-glyph extraction with a PERSISTENT cluster store.

Same algorithm as tools/mcr/extract_vector_glyphs.py (render each filled
path in isolation on a blank page, normalize to 28x28, hamming-cluster with
a size gate), but industrialized for the whole Anastasimatarion:

  * clusters live in an appendable store  <scores>/clusters.npz
    (bitmaps (N,28,28) bool, w (N,), h (N,), counts (N,)) — loaded at start,
    appended across runs, so cluster ids are STABLE across page ranges.
  * per-page glyph records -> <scores>/glyphs/page<NNN>.json
    {page, n_lines, glyphs:[{cluster,x0,x1,y0,y1,red,line}],
     lyrics:[{text,x0,x1,y0,line}]}   (line = 0-based within the page)
  * --atlas renders the current store to <scores>/atlas.png with ids+counts.

Usage:
  extract_book.py <pdf> <first_page> <last_page> [--store F] [--glyphs-dir D]
  extract_book.py --atlas [--store F] [--out atlas.png]
Pages are 1-based inclusive.
"""
import argparse, json, os, sys, time
sys.path.append('/mnt/data/code/byzorgan-web/training-prototype/omr/.venv/lib/python3.11/site-packages')
import fitz
import numpy as np
from PIL import Image, ImageDraw

BM = 28            # normalized bitmap side
HAM = 0.06         # max hamming distance (fraction of BM*BM) within a cluster
SZ = 1.2           # max width/height difference (pt) within a cluster
LINE_GAP = 14.0    # y gap that separates neume lines (pt)
RENDER_ZOOM = 6
SAVE_EVERY = 20    # checkpoint the store every N pages

SCORES = '/mnt/data/chant-corpus/scores'
DEF_STORE = os.path.join(SCORES, 'clusters.npz')
DEF_GLYPHS = os.path.join(SCORES, 'glyphs')
DEF_ATLAS = os.path.join(SCORES, 'atlas.png')


def render_bits(dr):
    """replay the filled path alone on a blank page; return (bits, w, h)"""
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
    im = Image.fromarray(a)
    im.thumbnail((BM, BM))
    canvas = Image.new('L', (BM, BM), 255)
    canvas.paste(im, ((BM - im.width) // 2, (BM - im.height) // 2))
    bits = (np.asarray(canvas) < 128)
    return bits, r.width, r.height


class Store:
    """persistent cluster store: bitmaps/w/h/counts, appended across runs"""

    def __init__(self, path):
        self.path = path
        if os.path.exists(path):
            z = np.load(path)
            self.bitmaps = [b.astype(bool) for b in z['bitmaps']]
            self.w = list(z['w'].astype(float))
            self.h = list(z['h'].astype(float))
            self.counts = list(z['counts'].astype(np.int64))
        else:
            self.bitmaps, self.w, self.h, self.counts = [], [], [], []
        self._rebuild()

    def _rebuild(self):
        n = len(self.bitmaps)
        self._flat = (np.stack(self.bitmaps).reshape(n, BM * BM)
                      if n else np.zeros((0, BM * BM), bool))
        self._wh = (np.array([self.w, self.h]).T if n else np.zeros((0, 2)))

    def match(self, bits, w, h):
        """return cluster id, appending a new cluster when nothing matches"""
        mask = ((np.abs(self._wh[:, 0] - w) <= SZ)
                & (np.abs(self._wh[:, 1] - h) <= SZ))
        idx = np.nonzero(mask)[0]
        if len(idx):
            d = np.mean(self._flat[idx] != bits.reshape(-1), axis=1)
            k = int(np.argmin(d))
            if d[k] <= HAM:
                ci = int(idx[k])
                self.counts[ci] += 1
                return ci
        self.bitmaps.append(bits)
        self.w.append(float(w))
        self.h.append(float(h))
        self.counts.append(1)
        self._rebuild()
        return len(self.bitmaps) - 1

    def save(self):
        tmp = self.path + '.tmp.npz'
        np.savez_compressed(tmp,
                            bitmaps=np.stack(self.bitmaps) if self.bitmaps
                            else np.zeros((0, BM, BM), bool),
                            w=np.array(self.w), h=np.array(self.h),
                            counts=np.array(self.counts, dtype=np.int64))
        os.replace(tmp, self.path)

    def __len__(self):
        return len(self.bitmaps)


def group_lines(glyphs, lyrics):
    """assign 0-based per-page line index by y1 gaps; return line count"""
    if not glyphs:
        for w_ in lyrics:
            w_['line'] = 0
        return 0
    ys = sorted(g['y1'] for g in glyphs)
    breaks = [i for i in range(1, len(ys)) if ys[i] - ys[i - 1] > LINE_GAP]
    edges = [ys[0] - 1] + [(ys[i - 1] + ys[i]) / 2 for i in breaks] + [ys[-1] + 1]
    for g in glyphs:
        for li in range(len(edges) - 1):
            if edges[li] < g['y1'] <= edges[li + 1]:
                g['line'] = li
                break
    for w_ in lyrics:
        w_['line'] = max((li for li in range(len(edges) - 1)
                          if w_['y0'] > edges[li]), default=0)
    return len(edges) - 1


def process_page(doc, pno, store):
    """extract one 0-based page; return (glyphs, lyrics, n_lines)"""
    pg = doc[pno]
    glyphs, lyrics = [], []
    for dr in pg.get_drawings():
        if dr['type'] != 'f' or dr['fill'] is None:
            continue
        r_, g_, b_ = dr['fill']
        if r_ > 0.9 and g_ > 0.9 and b_ > 0.9:
            continue
        red = r_ > 0.3 and g_ < 0.2
        bits, w, h = render_bits(dr)
        ci = store.match(bits, w, h)
        rc = dr['rect']
        glyphs.append({'cluster': ci, 'page': pno + 1, 'red': int(red),
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
    n_lines = group_lines(glyphs, lyrics)
    glyphs.sort(key=lambda g: (g.get('line', 0), g['x0']))
    return glyphs, lyrics, n_lines


def render_atlas(store, out):
    n_cl = len(store)
    cell, cols = 96, 12
    rows = max(1, (n_cl + cols - 1) // cols)
    atlas = Image.new('RGB', (cols * cell, rows * cell), 'white')
    dr_ = ImageDraw.Draw(atlas)
    for c in range(n_cl):
        img = Image.fromarray(np.where(store.bitmaps[c], 0, 255).astype(np.uint8))
        big = img.resize((BM * 2, BM * 2), Image.NEAREST).convert('RGB')
        x, y = (c % cols) * cell, (c // cols) * cell
        atlas.paste(big, (x + (cell - BM * 2) // 2, y + 22))
        dr_.rectangle([x, y, x + cell - 1, y + cell - 1], outline='#bbb')
        dr_.text((x + 4, y + 2), f"{c} n={store.counts[c]}", fill='black')
    atlas.save(out)
    print(f"atlas: {n_cl} clusters -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf', nargs='?')
    ap.add_argument('first', nargs='?', type=int)
    ap.add_argument('last', nargs='?', type=int)
    ap.add_argument('--store', default=DEF_STORE)
    ap.add_argument('--glyphs-dir', default=DEF_GLYPHS)
    ap.add_argument('--atlas', action='store_true')
    ap.add_argument('--out', default=DEF_ATLAS)
    args = ap.parse_args()

    store = Store(args.store)
    if args.atlas:
        render_atlas(store, args.out)
        return
    if not (args.pdf and args.first and args.last):
        ap.error('need <pdf> <first_page> <last_page> (or --atlas)')

    os.makedirs(args.glyphs_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.store), exist_ok=True)
    doc = fitz.open(args.pdf)
    t0 = time.time()
    tot_g = tot_l = 0
    for pno in range(args.first - 1, args.last):
        tp = time.time()
        glyphs, lyrics, n_lines = process_page(doc, pno, store)
        tot_g += len(glyphs)
        tot_l += len(lyrics)
        out = os.path.join(args.glyphs_dir, f'page{pno + 1:03d}.json')
        with open(out + '.tmp', 'w') as f:
            json.dump({'page': pno + 1, 'n_lines': n_lines,
                       'glyphs': glyphs, 'lyrics': lyrics}, f,
                      ensure_ascii=False)
        os.replace(out + '.tmp', out)
        print(f"page {pno + 1}: {len(glyphs)} glyphs, {len(lyrics)} lyric spans, "
              f"{n_lines} lines | clusters={len(store)} total_glyphs={tot_g} "
              f"({time.time() - tp:.1f}s)", flush=True)
        if (pno + 1 - args.first) % SAVE_EVERY == SAVE_EVERY - 1:
            store.save()
    store.save()
    dt = time.time() - t0
    print(f"DONE pages {args.first}-{args.last}: {tot_g} glyphs, "
          f"{tot_l} lyric spans, {len(store)} clusters, {dt:.0f}s "
          f"-> {args.glyphs_dir}, store {args.store}", flush=True)


if __name__ == '__main__':
    main()
