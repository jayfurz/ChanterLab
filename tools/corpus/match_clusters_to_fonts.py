#!/usr/bin/env python3
"""match_clusters_to_fonts.py — propose identities for the Ioannou book's 94
shape clusters by shape-matching against Byzantine chant fonts with KNOWN
glyph names (Neanes/SBMuFL metadata names + the EZ-Psaltica legend).

Why: the original atlas seed was chanter-disproven (rotated: 4/5/6 were
oligon/apostrofos/ison-rotated — see scores/atlas_chanter.json). Rather than
having the chanter name 94 clusters one at a time, render every named font
glyph, normalize it exactly like extract_book normalizes cluster bitmaps
(ink-crop -> thumbnail 28x28 centered), and rank matches by pixel IoU with an
aspect-ratio penalty. The chanter then reviews ONE proposal sheet.

Outputs:
  /mnt/data/chant-corpus/scores/cluster_font_matches.json   top-3 per cluster
  <annotator>/cluster_match_sheet.png                       review sheet
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.normpath(os.path.join(HERE, '..', '..', 'docs', 'references'))
STORE = '/mnt/data/chant-corpus/scores/clusters.npz'
OUT_JSON = '/mnt/data/chant-corpus/scores/cluster_font_matches.json'
OUT_PNG = os.path.normpath(os.path.join(
    HERE, '..', 'chant-reel', 'annotator', 'cluster_match_sheet.png'))
BM = 28
RENDER_PX = 160

# chanter-verified identities override any match (atlas_chanter.json)
CHANTER = {3: 'petasti', 4: 'apostrofos', 5: 'ison', 6: 'oligon',
           7: 'psifiston', 8: 'klasma', 17: 'oligon+kentimata'}

# EZ-Psaltica keystroke legend (chanter/eothinon-verified subset)
EZ_NAMES = {
    0xF021: 'apostrofos', 0xF030: 'ison', 0xF031: 'oligon',
    0xF05F: 'running-elafron', 0xF029: 'yporrhoe', 0xF050: 'ison+kentimata',
    0xF059: 'elafron+kentimata', 0xF075: 'oligon+ypsili+kentimata',
    0xF077: 'petasti+oligon', 0xF065: 'petasti+kentima', 0xF070: 'ison+petasti',
    0xF034: 'oligon+ypsili', 0xF049: 'apostrofos+klasma',
    0xF055: 'apostrofos+kentimata', 0xF060: 'kentimata',
    0xF053: 'gorgon', 0xF073: 'gorgon', 0xF048: 'gorgon(dotted)',
    0xF044: 'digorgon', 0xF061: 'klasma', 0xF041: 'klasma', 0xF027: 'apli',
    0xF06B: 'diple', 0xF022: 'antikenoma', 0xF05B: 'omalon',
    0xF0F8: 'psifiston', 0xF02B: 'stavros',
}

FONTS = [
    ('neanes', os.path.join(REF, 'sbmufl', 'fonts', 'Neanes.otf')),
    ('ez-psaltica', os.path.join(REF, 'ByzMusicFonts', 'Fonts', 'EZ Psaltica.TTF')),
    ('ez-special1', os.path.join(REF, 'ByzMusicFonts', 'Fonts', 'EZ Special-I.TTF')),
    ('ez-special2', os.path.join(REF, 'ByzMusicFonts', 'Fonts', 'EZ Special-II.TTF')),
]


def font_glyph_names(path):
    """{codepoint: name} — SBMuFL production names from post/cmap where
    available, EZ legend names for the EZ family, else hex."""
    tt = TTFont(path)
    cmap = tt.getBestCmap()
    if cmap is None:
        # legacy symbol-encoded TTF (3,0): codepoints live at 0xF000+keystroke
        cmap = {}
        for t in tt['cmap'].tables:
            cmap.update(t.cmap)
    names = {}
    for cp, gname in cmap.items():
        if os.path.basename(path).lower().startswith('ez'):
            names[cp] = EZ_NAMES.get(cp, f'{cp:#06x}')
        else:
            names[cp] = gname          # Neanes glyph names ARE semantic
    return names


def render_norm(font, cp):
    """render one glyph -> (bits 28x28 bool, w, h ink px) like extract_book."""
    img = Image.new('L', (RENDER_PX * 3, RENDER_PX * 3), 255)
    dr = ImageDraw.Draw(img)
    try:
        dr.text((RENDER_PX, RENDER_PX), chr(cp), font=font, fill=0)
    except Exception:
        return None
    a = np.asarray(img)
    ys, xs = np.nonzero(a < 128)
    if len(xs) < 4:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = img.crop((x0, y0, x1 + 1, y1 + 1))
    crop.thumbnail((BM, BM))
    canvas = Image.new('L', (BM, BM), 255)
    canvas.paste(crop, ((BM - crop.width) // 2, (BM - crop.height) // 2))
    return (np.asarray(canvas) < 128), (x1 - x0 + 1), (y1 - y0 + 1)


def main():
    z = np.load(STORE, allow_pickle=True)
    bitmaps, W, H, counts = z['bitmaps'], z['w'], z['h'], z['counts']

    lib = []       # (fontname, name, bits, aspect, cp)
    for tag, path in FONTS:
        if not os.path.exists(path):
            print(f'missing font {path}', file=sys.stderr)
            continue
        font = ImageFont.truetype(path, RENDER_PX)
        for cp, name in sorted(font_glyph_names(path).items()):
            r = render_norm(font, cp)
            if r is None:
                continue
            bits, gw, gh = r
            lib.append((tag, name, bits, gw / gh, cp))
    print(f'{len(lib)} font glyphs rendered from {len(FONTS)} fonts')

    out = {}
    rows = []
    order = np.argsort(-counts)
    for c in order:
        cb = bitmaps[c]
        ar_c = (W[c] / H[c]) if H[c] > 0 else 1.0
        scored = []
        for tag, name, gb, ar_g, cp in lib:
            inter = np.logical_and(cb, gb).sum()
            union = np.logical_or(cb, gb).sum()
            iou = inter / union if union else 0.0
            pen = 0.25 * abs(math.log(max(ar_c, 1e-3) / max(ar_g, 1e-3)))
            scored.append((iou - pen, iou, tag, name, cp))
        scored.sort(reverse=True)
        top = scored[:3]
        out[int(c)] = {
            'count': int(counts[c]), 'w_pt': round(float(W[c]), 1),
            'h_pt': round(float(H[c]), 1),
            'chanter': CHANTER.get(int(c)),
            'matches': [{'score': round(s, 3), 'iou': round(i, 3),
                         'font': t, 'name': n, 'cp': f'{cp:#06x}'}
                        for s, i, t, n, cp in top],
        }
        rows.append((int(c), cb, top))

    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=1)

    # ---- review sheet ----
    SC = 3          # bitmap upscale
    ROW_H = BM * SC + 26
    sheet = Image.new('RGB', (1250, ROW_H * len(rows) + 30), 'white')
    dr = ImageDraw.Draw(sheet)
    y = 10
    lib_by = {(t, n, cp): b for t, n, b, _, cp in lib}
    for c, cb, top in rows:
        im = Image.fromarray((~cb * 255).astype(np.uint8)).resize(
            (BM * SC, BM * SC), Image.NEAREST)
        sheet.paste(im, (10, y))
        chan = out[c]['chanter']
        dr.text((10 + BM * SC + 8, y),
                f"cluster {c}  n={out[c]['count']}  {out[c]['w_pt']}x{out[c]['h_pt']}pt"
                + (f'  CHANTER: {chan}' if chan else ''), fill=(180, 0, 0))
        x = 10 + BM * SC + 8
        yy = y + 18
        for k, (s, i, t, n, cp) in enumerate(top):
            gb = lib_by.get((t, n, cp))
            if gb is not None:
                gi = Image.fromarray((~gb * 255).astype(np.uint8)).resize(
                    (BM * 2, BM * 2), Image.NEAREST)
                sheet.paste(gi, (x, yy))
            dr.text((x, yy + BM * 2 + 1), f'{n[:18]}\n{t} {s:.2f}', fill=(60, 60, 60))
            x += 300
        y += ROW_H
    sheet.save(OUT_PNG)
    print(f'wrote {OUT_JSON}\nwrote {OUT_PNG}')


if __name__ == '__main__':
    main()
