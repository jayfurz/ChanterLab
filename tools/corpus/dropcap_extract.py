#!/usr/bin/env python3
"""dropcap_extract.py — drop-cap initials WITH their position on the page.

scores/book_map.json records which initials appear on a page but not where, and
position is the whole point: the chanter's rule is that a drop cap marks where a
hymn STARTS. "the drop cap is the dead giveaway".

Emits scores/dropcaps.json: [{page, line, text, letter, x0, y0, x1, y1}], where
`line` is the score line index used by the glyph layer, so a drop cap can be
compared directly against a hymns.json slice boundary (p0/l0).

The initials layer is ANNA2000 at size > 18 (book_map.font_role), and it
substitutes lookalike codepoints for three capitals — INCREMENT for Delta, OHM
SIGN for Omega, Latin N for Nu.

Usage:  dropcap_extract.py [--pdf PATH]
"""
import argparse
import glob
import json
import os
import unicodedata

import fitz

GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
OUT = '/mnt/data/chant-corpus/scores/dropcaps.json'
LOOKALIKE = {'∆': 'Δ', 'Ω': 'Ω', 'N': 'Ν'}


def fold(ch):
    ch = LOOKALIKE.get(ch, ch)
    d = unicodedata.normalize('NFD', ch)
    return ''.join(c for c in d if not unicodedata.combining(c)).upper()


def line_bands(page):
    """(line_index, y0, y1) for every score line on a page, from the glyphs"""
    f = os.path.join(GLYPHS, f'page{page:03d}.json')
    if not os.path.exists(f):
        return []
    by = {}
    for g in json.load(open(f))['glyphs']:
        a, b = by.get(g['line'], (1e9, -1e9))
        by[g['line']] = (min(a, g['y0']), max(b, g['y1']))
    return sorted((li, y0, y1) for li, (y0, y1) in by.items())


def find_pdf():
    for f in glob.glob('/mnt/data/code/byzorgan-web/*.pdf'):
        if 'Ιωάννου' in unicodedata.normalize('NFC', os.path.basename(f)):
            return f
    raise SystemExit('Ioannou Anastasimatarion PDF not found')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--pdf', default=None)
    a = ap.parse_args()
    doc = fitz.open(a.pdf or find_pdf())
    out = []
    for pno in range(len(doc)):
        # the glyph layer and book_map.json both number pages 1-based, so
        # doc[519] is page 520. Getting this wrong shifts every drop cap onto
        # the next page's lines and makes the whole boundary check nonsense.
        page = pno + 1
        bands = line_bands(page)
        if not bands:
            continue
        for blk in doc[pno].get_text('dict')['blocks']:
            if blk['type'] != 0:
                continue
            for ln in blk['lines']:
                for sp in ln['spans']:
                    t = sp['text'].strip()
                    if not t or 'ANNA2000' not in sp['font'] or sp['size'] <= 18:
                        continue
                    x0, y0, x1, y1 = sp['bbox']
                    cy = (y0 + y1) / 2
                    # the drop cap sits on the LYRIC row, below its neume line;
                    # nearest band by vertical distance is the right owner
                    li = min(bands, key=lambda b: 0 if b[1] <= cy <= b[2]
                             else min(abs(cy - b[1]), abs(cy - b[2])))[0]
                    for ch in t:
                        f = fold(ch)
                        if 'Α' <= f <= 'Ω':
                            out.append({'page': page, 'line': li, 'text': ch,
                                        'letter': f, 'x0': round(x0, 1),
                                        'y0': round(y0, 1), 'x1': round(x1, 1),
                                        'y1': round(y1, 1),
                                        'size': round(sp['size'], 1)})
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    pages = len({d['page'] for d in out})
    print(f'{len(out)} drop caps on {pages} pages -> {OUT}')


if __name__ == '__main__':
    main()
