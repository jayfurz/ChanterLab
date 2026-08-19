#!/usr/bin/env python3
"""Render the chant reel: scrolling Byzantine score + karaoke captions -> raw frames to ffmpeg."""
import json, sys, subprocess, os, math, bisect
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

V2 = os.environ.get('REEL_V2') == '1'
LADDER = os.environ.get('REEL_LADDER') == '1'
W, H = 1080, 1920
FPS = 30
TEAL = (98, 196, 178)
TEAL_DIM = (66, 132, 120)

GOLD = (212, 175, 55)
GOLD_BRIGHT = (245, 210, 90)
CREAM = (232, 226, 214)
MUTED = (160, 140, 102)
PARCH = (247, 242, 232)

FB = "/usr/share/fonts/noto/NotoSerif-Bold.ttf"
FR = "/usr/share/fonts/noto/NotoSerif-Regular.ttf"
FM = "/usr/share/fonts/noto/NotoSerif-Medium.ttf"

f_title = ImageFont.truetype(FB, 58)
f_sub = ImageFont.truetype(FM, 34)
f_cap = ImageFont.truetype(FB, 44)

# ---------- static background ----------
def make_bg():
    g = np.zeros((H, W, 3), np.float64)
    top = np.array([26, 20, 16]); bot = np.array([10, 8, 7])
    for y in range(H):
        g[y, :] = top + (bot - top) * (y / H)
    # vignette
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W/2)/(W/2))**2 + ((yy - H/2)/(H/2))**2)
    g *= (1 - 0.25*np.clip(d-0.4, 0, 1)**1.5)[..., None]
    return Image.fromarray(g.astype(np.uint8))

BG = make_bg()

# card geometry
CX0, CY0, CX1, CY1 = 40, 450, 1040, 985
CARD_H = CY1 - CY0
CARD_CTR = (CY0 + CY1) // 2

def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)

# card base (parchment + shadow) drawn onto bg copy once
def make_card_bg():
    im = BG.copy()
    sh = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(sh)
    rounded(d, (CX0+6, CY0+10, CX1+6, CY1+10), 26, fill=(0,0,0,140))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    im = Image.alpha_composite(im.convert('RGBA'), sh)
    d = ImageDraw.Draw(im)
    rounded(d, (CX0, CY0, CX1, CY1), 24, fill=PARCH+(255,))
    rounded(d, (CX0, CY0, CX1, CY1), 24, outline=(180, 150, 80, 255), width=3)
    return im

CARD_BG = make_card_bg()

# rounded-corner mask for pasting the scrolled strip
CARD_MASK = Image.new('L', (CX1-CX0, CARD_H), 0)
rounded(ImageDraw.Draw(CARD_MASK), (0, 0, CX1-CX0-1, CARD_H-1), 24, fill=255)

# edge fade masks (parchment fading at top/bottom of card)
def make_fade():
    fa = np.zeros((CARD_H, CX1-CX0, 4), np.uint8)
    fh = 70
    for i in range(fh):
        a = int(235 * (1 - i/fh)**1.6)
        fa[i, :] = PARCH + (a,)
        fa[CARD_H-1-i, :] = PARCH + (a,)
    return Image.fromarray(fa)

EDGE_FADE = make_fade()

# sticky line band: follows the line being sung (computed per frame later)
def draw_line_band(win, cy_strip, hh, top):
    ov = Image.new('RGBA', win.size, (0,0,0,0))
    d = ImageDraw.Draw(ov)
    y = cy_strip - top
    rounded(d, (8, y-hh, win.width-8, y+hh), 16, fill=GOLD+((20,) if V2 else (34,)))
    win.alpha_composite(ov.filter(ImageFilter.GaussianBlur(6)))

# ---------- header (static) ----------
def draw_header(im):
    d = ImageDraw.Draw(im)
    t1 = "Eleventh Matinal Doxastikon"
    w1 = d.textlength(t1, font=f_title)
    d.text(((W-w1)/2+2, 260+2), t1, font=f_title, fill=(0,0,0,160))
    d.text(((W-w1)/2, 260), t1, font=f_title, fill=GOLD)
    t2 = "Byzantine Chant  ·  Plagal Fourth Mode"
    w2 = d.textlength(t2, font=f_sub)
    d.text(((W-w2)/2, 344), t2, font=f_sub, fill=MUTED)
    # thin rules
    d.line((W/2-330, 412, W/2-40, 412), fill=(120,100,60), width=2)
    d.line((W/2+40, 412, W/2+330, 412), fill=(120,100,60), width=2)
    d.regular_polygon((W/2, 412, 9), 4, rotation=45, fill=GOLD)
    f_credit = ImageFont.truetype(FR, 26)
    t3 = "Translation © Holy Transfiguration Monastery  ·  Notation: Chadi Karam"
    w3 = d.textlength(t3, font=f_credit)
    d.text(((W-w3)/2, 1032), t3, font=f_credit, fill=(120, 105, 80))
    return im

STATIC = draw_header(CARD_BG.copy())

# ---------- timing data ----------
strip = Image.open('strip.png').convert('RGB')
centers = np.load('line_centers.npy')
timing = json.load(open('timing.json'))
line_times = timing['line_times']          # 18 anchor times (sec)
captions = timing['captions']              # [{words:[{w,t0,t1}], t0, t1}]
DUR = timing['duration']

# scroll position: piecewise-linear through (line_time, center), smoothed
anchor_t = np.array([0.0] + line_times + [DUR])
anchor_y = np.array([centers[0]-40] + list(centers) + [centers[-1]+40], dtype=float)
tt = np.arange(0, DUR, 1/FPS)
raw_y = np.interp(tt, anchor_t, anchor_y)
k = int(FPS*1.2) | 1  # ~1.2 s smoothing window
pad = np.pad(raw_y, k//2, mode='edge')
smooth_y = np.convolve(pad, np.ones(k)/k, mode='valid')


# ---------- v2: per-note highlight data (beat slots) ----------
NOTES_G = json.load(open('score_notes.json'))['notes']
if V2:
    _slots = json.load(open('slots.json'))
    NOTE_T = _slots['t']
    SLOT_GI = _slots['gi']
    ORN = json.load(open('ornaments.json'))
    ORN_T0 = [o[0] for o in ORN]

# ---------- v2.7: progressive sub-glyph parts (chanter-corrected figures) ----
# annotator_data.json carries per-glyph ink boxes: parts.subs (one entry per
# sung sub-note, entry = box or list of boxes lit together) and parts.marks
# (one box per ADDED beat of a klasma/apli/diple).  Same fill rules as the
# annotator: subs cumulative in sung order, marks one per extension beat.
PARTS, MCR_BEATS, MCR_DUR, SLOT_SUB = {}, {}, {}, None
FIRST_SLOT, LAST_SLOT = {}, {}
ADDED_BEATS = {'klasma': 1, 'apli': 1, 'diple': 2, 'tripli': 3}
try:
    ANA = json.load(open('analytical.json'))     # bracketed analytical figures
except Exception:
    ANA = {}

def draw_analytical(win, t, top):
    for e in ANA.values():
        if not e.get('span'):
            continue                      # static annotation (e.g. tempo mark)
        a, b = e['span']
        if not (a - 0.4 <= t <= b + 0.4):
            continue
        ramp = min(1.0, (t - (a - 0.4)) / 0.4, ((b + 0.4) - t) / 0.4)
        bx = e['box']
        ov = Image.new('RGBA', win.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        y0, y1 = bx[1] - top, bx[3] - top
        if y1 < 0 or y0 > win.height:
            continue
        d.rounded_rectangle((bx[0] - 4, y0 - 4, bx[2] + 4, y1 + 4), radius=10,
                            outline=GOLD_BRIGHT + (int(90 * ramp),), width=2)
        for nn in e.get('notes', []):     # parallel per-note timeline
            if t < nn['t0']:
                continue
            cur = t < nn['t1']
            nb = nn['box']
            aa = int((95 if cur else 38) * ramp)
            d.rounded_rectangle((nb[0], nb[1] - top, nb[2], nb[3] - top),
                                radius=6, fill=GOLD_BRIGHT + (aa,))
        win.alpha_composite(ov.filter(ImageFilter.GaussianBlur(1)))

if V2:
    try:
        _ad = json.load(open('annotator_data.json'))
        for _g, _n in enumerate(_ad['notes']):
            if _n.get('parts'):
                PARTS[_g] = _n['parts']
        for _r in json.load(open('mcr_interpretation.json')):
            MCR_BEATS[_r['gi']] = _r['beats']
            MCR_DUR[_r['gi']] = _r['duration_mark']
        SLOT_SUB = _slots['sub']
        for _j, _g in enumerate(SLOT_GI):
            FIRST_SLOT.setdefault(_g, _j)
            LAST_SLOT[_g] = _j
        print(f'parts: {len(PARTS)} glyphs with sub/mark boxes', file=sys.stderr)
    except Exception as _e:
        print(f'parts unavailable ({_e}) — whole-glyph pills only', file=sys.stderr)
        PARTS = {}

def _norm_subs(subs):
    return [[e] if len(e) == 4 and not isinstance(e[0], list) else e for e in subs]

def _slot_end(j):
    return NOTE_T[j + 1] if j + 1 < len(NOTE_T) else min(NOTE_T[j] + 3.0, DUR)

def _mark_fill(gi, t):
    added = ADDED_BEATS.get(MCR_DUR.get(gi, 'none'), 0)
    if not added:
        return 0
    j0, j1 = FIRST_SLOT[gi], LAST_SLOT[gi]
    if j1 > j0:                       # split figure: extension inside last sub's slot
        a, b = NOTE_T[j1], _slot_end(j1)
        if b <= a: return 0
        f = max(0.0, min(1.0, (t - a) / (b - a)))
        return min(added, int(f * (added + 1)))
    total = sum(MCR_BEATS.get(gi, [1.0]))
    t0, t1 = NOTE_T[j0], _slot_end(j0)
    if t1 <= t0 or total <= 0: return 0
    el = max(0.0, min(total, (t - t0) / (t1 - t0) * total))
    base = min(total, max(1.0, total - added))
    if el < base or total <= base: return 0
    return max(0, min(added, int(el - base) + 1))

# ---------- sticky band track: line being sung, smoothed ----------
LINE_HH = [Image.open(f'lines/line{i:02d}.png').height * (940/1915) / 2 + 16
           for i in range(1, 19)]
band_c = np.zeros(len(tt)); band_h = np.zeros(len(tt))
for _fi, _t in enumerate(tt):
    if V2:
        _j = max(0, bisect.bisect_right(NOTE_T, _t) - 1)
        _li = NOTES_G[SLOT_GI[_j]]['line']
    else:
        _li = max(0, bisect.bisect_right(line_times, _t) - 1)
    band_c[_fi] = centers[_li]; band_h[_fi] = LINE_HH[_li]
k2 = int(FPS*0.45) | 1
band_c = np.convolve(np.pad(band_c, k2//2, mode='edge'), np.ones(k2)/k2, 'valid')
band_h = np.convolve(np.pad(band_h, k2//2, mode='edge'), np.ones(k2)/k2, 'valid')

def note_rect(j):
    g = NOTES_G[SLOT_GI[j]]
    x0, x1 = g['x0'] - 7, g['x1'] + 7
    if x1 - x0 < 34:
        c = (x0 + x1) / 2; x0, x1 = c - 17, c + 17
    return [x0, g['y0'] - 5, x1, g['y1'] + 5]

def draw_note_pill(win, t, top):
    j = bisect.bisect_right(NOTE_T, t) - 1
    if j < 0: return
    rect = note_rect(j)
    dt = t - NOTE_T[j]
    if j > 0 and dt < 0.09:                     # ease from previous note
        s = dt / 0.09; s = s * s * (3 - 2 * s)
        pr = note_rect(j - 1)
        rect = [pr[k] + (rect[k] - pr[k]) * s for k in range(4)]
    # ornament pulse: extra unscored notes being sung -> pill breathes brighter
    a, col = 58, GOLD
    if LADDER and LT_CHROA[min(int(t*FPS), len(LT_CHROA)-1)]:
        col = TEAL
    oi = bisect.bisect_right(ORN_T0, t) - 1
    if oi >= 0 and ORN[oi][0] <= t <= ORN[oi][1]:
        p = 0.5 - 0.5 * math.cos(2 * math.pi * 2.2 * (t - ORN[oi][0]))
        a = int(58 + 72 * p)
        col = tuple(int(GOLD[k] + (GOLD_BRIGHT[k] - GOLD[k]) * p) for k in range(3))
    gi = SLOT_GI[j]
    pp = PARTS.get(gi)
    subs = _norm_subs(pp['subs']) if pp and pp.get('subs') else None
    if subs and dt >= 0:              # same pill styling, per printed component
        ov = Image.new('RGBA', win.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        s_cur = min(SLOT_SUB[j] if SLOT_SUB else 0, len(subs) - 1)
        # ease the sounding box from the previous slot's box (classic pill morph)
        cur_boxes = subs[s_cur]
        if dt < 0.09 and j > 0 and len(cur_boxes) == 1:
            ppp = PARTS.get(SLOT_GI[j - 1])
            if ppp and ppp.get('subs'):
                ps = _norm_subs(ppp['subs'])
                pb = ps[min(SLOT_SUB[j - 1] if SLOT_SUB else 0, len(ps) - 1)]
                if len(pb) == 1:
                    s = dt / 0.09; s = s * s * (3 - 2 * s)
                    b0, b1 = pb[0], cur_boxes[0]
                    cur_boxes = [[b0[k] + (b1[k] - b0[k]) * s for k in range(4)]]
        drawn = False
        for si in range(s_cur + 1):   # cumulative, sung order
            aa = min(255, a + 42) if si == s_cur else max(34, a - 14)
            for bx in (cur_boxes if si == s_cur else subs[si]):
                x0, y0, x1, y1 = bx[0] - 4, bx[1] - 4 - top, bx[2] + 4, bx[3] + 4 - top
                if y1 < 0 or y0 > win.height: continue
                d.rounded_rectangle((x0, y0, x1, y1), radius=7, fill=col + (aa,),
                                    outline=col + (min(255, aa + 60),), width=2)
                drawn = True
        marks = pp.get('marks') or []
        for k2 in range(min(_mark_fill(gi, t), len(marks))):
            bx = marks[k2]
            x0, y0, x1, y1 = bx[0] - 3, bx[1] - 3 - top, bx[2] + 3, bx[3] + 3 - top
            if y1 < 0 or y0 > win.height: continue
            d.rounded_rectangle((x0, y0, x1, y1), radius=6,
                                fill=GOLD_BRIGHT + (min(255, a + 42),),
                                outline=GOLD_BRIGHT + (min(255, a + 100),), width=2)
            drawn = True
        if drawn:
            win.alpha_composite(ov.filter(ImageFilter.GaussianBlur(1)))
            return
    ov = Image.new('RGBA', win.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = rect[0], rect[1] - top, rect[2], rect[3] - top
    if y1 < 0 or y0 > win.height: return
    d.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=col + (a,),
                        outline=col + (min(255, a + 60),), width=2)
    win.alpha_composite(ov.filter(ImageFilter.GaussianBlur(1)))
    if pp and pp.get('marks'):        # marked single-note glyph without tight subs
        mf = _mark_fill(gi, t)
        if mf:
            ov2 = Image.new('RGBA', win.size, (0, 0, 0, 0))
            d2 = ImageDraw.Draw(ov2)
            for k2 in range(min(mf, len(pp['marks']))):
                bx = pp['marks'][k2]
                d2.rounded_rectangle((bx[0] - 3, bx[1] - 3 - top, bx[2] + 3, bx[3] + 3 - top),
                                     radius=6, fill=GOLD_BRIGHT + (min(255, a + 42),),
                                     outline=GOLD_BRIGHT + (min(255, a + 100),), width=2)
            win.alpha_composite(ov2.filter(ImageFilter.GaussianBlur(1)))

# ---------- v2.5: parallagi ladder ----------
if LADDER:
    _lt = json.load(open('ladder_track.json'))
    LT_M = np.array([x[0] if x[0] is not None else np.nan for x in _lt])
    LT_NAME = [x[1] for x in _lt]
    LT_CHROA = [x[3] for x in _lt]
    # smooth dot position, forward-fill unvoiced, alpha decay when silent
    LT_Y = LT_M.copy()
    valid = np.where(~np.isnan(LT_Y))[0]
    LT_Y[:valid[0]] = LT_Y[valid[0]]          # backfill leading silence
    for i in range(1, len(LT_Y)):
        if np.isnan(LT_Y[i]): LT_Y[i] = LT_Y[i-1]
    k3 = 5
    LT_Y = np.convolve(np.pad(LT_Y, k3//2, mode='edge'), np.ones(k3)/k3, 'valid')
    LT_Y = np.nan_to_num(LT_Y, nan=0.0)
    LT_A = np.zeros(len(LT_M))
    a = 0.0
    for i in range(len(LT_M)):
        a = min(1.0, a + 0.25) if not np.isnan(LT_M[i]) else max(0.0, a - 0.05)
        LT_A[i] = a
    LAD_Y0, LAD_Y1 = 1245, 1490       # maps moria 84 .. -8 (TikTok-safe)
    def m2y(m): return LAD_Y0 + (84 - m) * (LAD_Y1 - LAD_Y0) / 92
    LAD_X = 500
    f_rung = ImageFont.truetype(FB, 26)
    f_cur = ImageFont.truetype(FB, 44)
    f_flat = ImageFont.truetype('/usr/share/fonts/gnu-free/FreeSerifBold.otf', 44)
    f_chroa = ImageFont.truetype("/usr/share/fonts/noto/NotoSerif-Italic.ttf", 24)
    DIA_R = [('Ζω',-8),('Νη',0),('Πα',12),('Βου',22),('Γα',30),('Δι',42),('Κε',54),('Ζω',64),("Νη'",72),("Πα'",84)]
    CHR_R = [('Ζω',-8),('Νη',0),('Πα',12),('Βου',20),('Γα',34),('Δι',42),('Κε',50),('Ζω',64),("Νη'",72),("Πα'",84)]

def draw_ladder(im, fi):
    fi = min(fi, len(LT_Y)-1)
    alpha = LT_A[fi]
    if alpha <= 0.02: return
    chroa = LT_CHROA[fi]
    accent = TEAL if chroa else GOLD
    dim = TEAL_DIM if chroa else (120, 100, 60)
    layer = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    d.line((LAD_X, LAD_Y0-10, LAD_X, LAD_Y1+10), fill=dim+(160,), width=3)
    rungs = CHR_R if chroa else DIA_R
    # name from the smoothed dot position, so label/dot/rung always agree;
    # in the 58-moria attraction region defer to the track's arsis/thesis call
    m_now = LT_Y[fi]
    if not chroa and abs(m_now - 58) < 5 and LT_NAME[fi] in ('Κε↑', 'Ζω'):
        name_now = 'Ζω♭' if LT_NAME[fi] == 'Ζω' and _lt[fi][2] else LT_NAME[fi]
        if LT_NAME[fi] == 'Κε↑': name_now = 'Κε↑'
    else:
        cands = list(rungs) + ([('Ζω♭', 58)] if not chroa else [])
        name_now = min(cands, key=lambda g: abs(g[1] - m_now))[0]
    for nm, m in rungs:
        y = m2y(m)
        active = (nm == name_now.replace('♭','').replace('↑','')) and abs(m2y(LT_Y[fi]) - y) < 26
        col = accent if active else dim
        d.line((LAD_X-16, y, LAD_X+16, y), fill=col+(230 if active else 150,), width=4 if active else 2)
        wpx = d.textlength(nm, font=f_rung)
        d.text((LAD_X-30-wpx, y-16), nm, font=f_rung, fill=col+(255 if active else 170,))
    # continuous pitch dot
    dy = m2y(LT_Y[fi])
    glow = int(90*alpha)
    d.ellipse((LAD_X-13, dy-13, LAD_X+13, dy+13), fill=accent+(glow,))
    d.ellipse((LAD_X-7, dy-7, LAD_X+7, dy+7), fill=accent+(int(235*alpha),))
    # current degree name (flat/arrow signs composed from FreeSerif, NotoSerif lacks them)
    if name_now:
        base = name_now.replace('♭', '').replace('↑', '')
        d.text((LAD_X+42, dy-30), base, font=f_cur, fill=accent+(int(235*alpha),))
        suffix = '♭' if '♭' in name_now else ('↑' if '↑' in name_now else '')
        if suffix:
            bw = d.textlength(base, font=f_cur)
            d.text((LAD_X+46+bw, dy-32), suffix, font=f_flat, fill=accent+(int(235*alpha),))
    if chroa:
        txt = "φθορά · soft chromatic"
        wpx = d.textlength(txt, font=f_chroa)
        d.text(((W-wpx)/2, LAD_Y0-46), txt, font=f_chroa, fill=TEAL+(230,))
    im.alpha_composite(layer)

# ---------- caption layout ----------
MAXW = 780
def layout_caption(cap):
    """pre-compute per-word (line, x, y-offset) positions, centered lines"""
    words = [w['w'] for w in cap['words']]
    space = f_cap.getlength(' ')
    rows, cur, curw = [], [], 0
    for i, w in enumerate(words):
        wl = f_cap.getlength(w)
        if cur and curw + space + wl > MAXW:
            rows.append(cur); cur, curw = [], 0
        cur.append((i, w, wl))
        curw += (space if len(cur) > 1 else 0) + wl
    if cur: rows.append(cur)
    placed = {}
    LH = 74
    for r, row in enumerate(rows):
        total = sum(wl for _,_,wl in row) + space*(len(row)-1)
        x = (W-total)/2
        for i, w, wl in row:
            placed[i] = (x, r*LH)
            x += wl + space
    return placed, len(rows)*74

CAP_LAYOUTS = [layout_caption(c) for c in captions]
CAP_Y = 1060

def draw_caption(im, t):
    ci = None
    for i, c in enumerate(captions):
        if c['t0'] - 0.35 <= t:
            ci = i          # hold caption until the next one takes over
    if ci is None:
        if 0.6 < t < captions[0]['t0'] - 0.4:   # unwritten intonation formula
            f_ap = ImageFont.truetype("/usr/share/fonts/noto/NotoSerif-Italic.ttf", 40)
            d = ImageDraw.Draw(im)
            txt = "Ne aghie  ·  apichima"
            wpx = d.textlength(txt, font=f_ap)
            d.text(((W-wpx)/2+2, CAP_Y+42), txt, font=f_ap, fill=(0,0,0,160))
            d.text(((W-wpx)/2, CAP_Y+40), txt, font=f_ap, fill=MUTED)
        return
    cap = captions[ci]
    placed, capH = CAP_LAYOUTS[ci]
    y0 = CAP_Y + max(0, (300-capH)//2 - 40)
    layer = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    for i, wd in enumerate(cap['words']):
        x, dy = placed[i]
        sung = t >= wd['t0']
        active = wd['t0'] <= t <= wd['t1']
        col = GOLD_BRIGHT if active else (GOLD if sung else CREAM)
        d.text((x+2, y0+dy+2), wd['w'], font=f_cap, fill=(0,0,0,190))
        if active:
            d.text((x, y0+dy), wd['w'], font=f_cap, fill=col,
                   stroke_width=2, stroke_fill=(212,175,55,90))
        else:
            d.text((x, y0+dy), wd['w'], font=f_cap, fill=col)
    im.alpha_composite(layer)

# ---------- frame loop ----------
def frame(t, fi):
    im = STATIC.copy()
    # scrolled strip window
    cy = smooth_y[min(fi, len(smooth_y)-1)]
    top = int(cy - CARD_H/2)
    win = Image.new('RGB', (CX1-CX0, CARD_H), PARCH)
    sy0, sy1 = max(0, top), min(strip.height, top + CARD_H)
    if sy1 > sy0:
        seg = strip.crop((0, sy0, min(strip.width, CX1-CX0), sy1))
        win.paste(seg, (0, sy0 - top))
    win = win.convert('RGBA')
    fi_c = min(fi, len(band_c)-1)
    if (not V2) or t >= NOTE_T[0] - 0.3:
        draw_line_band(win, band_c[fi_c], band_h[fi_c], top)
    if V2:
        draw_note_pill(win, t, top)
        draw_analytical(win, t, top)
    win.alpha_composite(EDGE_FADE)
    im.paste(win, (CX0, CY0), CARD_MASK)
    d = ImageDraw.Draw(im)
    # progress bar
    prog = min(1.0, t / DUR)
    d.line((CX0+10, CY1+26, CX1-10, CY1+26), fill=(60, 50, 36), width=4)
    d.line((CX0+10, CY1+26, CX0+10 + prog*(CX1-CX0-20), CY1+26), fill=GOLD, width=4)
    draw_caption(im, t)
    if LADDER:
        draw_ladder(im, fi)
    return im.convert('RGB')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'preview':
        for t in [float(x) for x in sys.argv[2:]]:
            frame(t, int(t*FPS)).save(f'preview_{t:.0f}.png')
        print('previews written')
        sys.exit(0)

    n_frames = int(DUR * FPS)
    # chunk mode: REEL_RANGE="a:b" renders frames [a,b) video-only to REEL_OUT (for parallel NVENC)
    rng = os.environ.get('REEL_RANGE')
    if rng:
        a, b = (int(x) for x in rng.split(':'))
        ff = subprocess.Popen([
            os.environ.get('FFMPEG_BIN', 'ffmpeg'), '-y', '-v', 'error',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
            '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15', '-threads', '2',
            os.environ['REEL_OUT']], stdin=subprocess.PIPE)
        for fi in range(a, min(b, n_frames)):
            ff.stdin.write(frame(fi/FPS, fi).tobytes())
        ff.stdin.close(); ff.wait()
        print(f'chunk {a}:{b} done'); sys.exit(0)
    ff = subprocess.Popen([
        'ffmpeg', '-y', '-v', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', 'master.wav',
        '-map', '0:v', '-map', '1:a',
        '-vf', f'fade=t=in:st=0:d=0.7,fade=t=out:st={DUR-2.2}:d=2.2,format=yuv420p',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-r', str(FPS),
        '-c:a', 'aac', '-b:a', '192k', '-ar', '44100',
        '-shortest', '-movflags', '+faststart',
        'chant_reel_v2.5.mp4' if (V2 and LADDER) else ('chant_reel_v2.mp4' if V2 else 'chant_reel.mp4')
    ], stdin=subprocess.PIPE)
    for fi in range(n_frames):
        ff.stdin.write(frame(fi/FPS, fi).tobytes())
        if fi % (FPS*30) == 0:
            print(f'{fi}/{n_frames} frames', flush=True)
    ff.stdin.close()
    ff.wait()
    print('done')
