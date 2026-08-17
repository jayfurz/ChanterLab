#!/usr/bin/env python3
"""Extract note-bearing neume glyphs + lyric word anchors from the EZ-font PDF,
in strip pixel coordinates. -> score_notes.json"""
import json, sys
from PIL import Image
sys.path.append('/mnt/data/code/byzorgan-web/training-prototype/omr/.venv/lib/python3.11/site-packages')
import fitz
from collections import Counter

PDF = "/mnt/data/code/byzorgan-web/11th eothinon.pdf.pdf"
SCALE = 300/72          # pt -> page pixel at 300dpi
X0, PAD = 290, 14       # crop params used for line strips
S = 940/1915            # line strip resize factor
GAP, PAD_TOP, PASTE_X = 42, 40, 30

SYSTEMS = {
 0: [(918,1132),(1206,1382),(1427,1632),(1676,1882),(1926,2132),(2176,2382),(2426,2632),(2676,2882)],
 1: [(334,545),(587,795),(837,1045),(1116,1295),(1337,1545),(1587,1794),(1837,2044),(2116,2294),(2337,2544),(2628,2794)],
}

NEUME_FONTS = ('EZ-Psaltica', 'EZ-Special', 'EZ-Oxeia')
LYRIC_FONT = 'EZOmega'
EXCLUDE_CP = {0xf02b, 0xf029, 0xf05c, 0xf07c, 0xf07e}   # stavros, bareia, barlines

# strip line tops from actual line images
tops, heights = [], []
y = PAD_TOP
for i in range(1, 19):
    h = Image.open(f'lines/line{i:02d}.png').height
    hs = round(h * S)
    tops.append(y); heights.append(hs)
    y += hs + GAP

def line_of(pnum, ypix):
    for li, (a, b) in enumerate(SYSTEMS[pnum]):
        if a - 20 <= ypix <= b + 20:
            return li + (8 if pnum == 1 else 0)
    return None

def to_strip(pnum, li, xpt, ypt):
    """pdf pt -> strip px"""
    xp, yp = xpt*SCALE, ypt*SCALE
    y0 = SYSTEMS[pnum][li - (8 if pnum == 1 else 0)][0]
    lx = (xp - X0) * S + PASTE_X
    ly = (yp - (y0 - PAD)) * S + tops[li]
    return lx, ly

doc = fitz.open(PDF)
glyphs = []   # note glyphs
tokens = []   # lyric tokens
cp_hist = Counter()
for pnum in range(2):
    d = doc[pnum].get_text("rawdict")
    for b in d['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                font = s['font'].split('+')[-1]
                color = s.get('color', 0)
                is_red = ((color >> 16) & 255) > 120 and (color & 255) < 100
                for ch in s['chars']:
                    x0, y0, x1, y1 = ch['bbox']
                    yc = (y0 + y1) / 2 * SCALE
                    li = line_of(pnum, yc)
                    if li is None: continue
                    cp = ord(ch['c'])
                    if any(f in font for f in NEUME_FONTS):
                        if is_red or cp in EXCLUDE_CP: continue
                        if x1 - x0 < 2.0: continue          # zero-width combining modifier
                        cp_hist[(hex(cp), font[:12])] += 1
                        glyphs.append({'line': li, 'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1, 'cp': cp, 'page': pnum})
                    elif LYRIC_FONT in font and not is_red:
                        tokens.append({'line': li, 'x': x0, 'x1': x1, 'c': ch['c'], 'page': pnum})

# ---- group lyric chars into tokens (split on gaps / spaces) ----
tokens.sort(key=lambda t: (t['line'], t['x']))
words_raw = []
cur = None
for t in tokens:
    if t['c'] == ' ':
        cur = None; continue
    if cur and t['line'] == cur['line'] and t['x'] - cur['x1'] < 1.2:
        cur['s'] += t['c']; cur['x1'] = t['x1']
    else:
        cur = {'line': t['line'], 'x': t['x'], 'x1': t['x1'], 's': t['c'], 'page': t['page']}
        words_raw.append(cur)

# drop pure filler tokens
toks = [w for w in words_raw if set(w['s']) - set('-_—')]

# ---- rebuild words: token ending in '-' continues into next token ----
words = []
acc = None
for w in toks:
    if acc is None:
        acc = {'text': w['s'], 'line': w['line'], 'x': w['x'], 'page': w['page']}
    else:
        acc['text'] += w['s']
    if acc['text'].endswith('-'):
        acc['text'] = acc['text'][:-1]      # syllable continues
    else:
        words.append(acc); acc = None
if acc: words.append(acc)
# restore drop-cap initials
if words and words[0]['text'].startswith('lo'): words[0]['text'] = 'G' + words[0]['text']
for w in words:
    if w['text'] == 'hen': w['text'] = 'When'

# ---- sort note glyphs, drop overlapping stacked modifiers ----
glyphs.sort(key=lambda g: (g['line'], g['x0']))
notes = []
for g in glyphs:
    if notes and g['line'] == notes[-1]['line']:
        p = notes[-1]
        ov = min(p['x1'], g['x1']) - max(p['x0'], g['x0'])
        if ov > 0.55 * min(p['x1']-p['x0'], g['x1']-g['x0']):
            continue                        # stacked modifier / overlay
    notes.append(g)

# ---- to strip coords ----
out_notes = []
for g in notes:
    lx0, ly0 = to_strip(g['page'], g['line'], g['x0'], g['y0'])
    lx1, ly1 = to_strip(g['page'], g['line'], g['x1'], g['y1'])
    out_notes.append({'line': g['line'], 'x0': round(lx0,1), 'x1': round(lx1,1),
                      'y0': round(ly0,1), 'y1': round(ly1,1), 'cp': g['cp']})

# ---- word anchors: word k -> first note glyph at/after its x ----
anchors = []
for wi, w in enumerate(words):
    lx, _ = to_strip(w['page'], w['line'], w['x'], 0)
    best = None
    for gi, g in enumerate(out_notes):
        if g['line'] == w['line'] and g['x1'] > lx - 4:
            best = gi; break
    if best is None:      # word starts past last glyph of its line -> next line's first
        for gi, g in enumerate(out_notes):
            if g['line'] > w['line']: best = gi; break
    anchors.append({'wi': wi, 'text': w['text'], 'gi': best, 'line': w['line']})

json.dump({'notes': out_notes, 'anchors': anchors,
           'words': [w['text'] for w in words]}, open('score_notes.json','w'))

print(f"{len(out_notes)} note glyphs, {len(words)} words")
per_line = Counter(g['line'] for g in out_notes)
print("notes per line:", [per_line[i] for i in range(18)])
print("words:", ' '.join(w['text'] for w in words))
print("top codepoints:", cp_hist.most_common(15))
bad = [a for a in anchors if a['gi'] is None]
print("unanchored words:", bad)
