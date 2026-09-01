#!/usr/bin/env python3
"""prep_hymn_annotator.py — bridge Vasilikos corpus hymns into the interactive
annotator (tools/chant-reel/annotator), one piece per melos track.

For each hymn it renders a score strip from the Ioannou Anastasimatarion PDF
(per-line bands stacked vertically, the annotator's strip format), replays the
aligner's unit stream as the MCR lane, seeds slot markers with the machine
alignment times from aligned.json (unmatched units interpolated by beat
weight), converts the cents track to moria relative to the fitted Νη, and
writes data/<piece-id>/ plus an entry in data/index.json — the piece manifest
the annotator's picker reads.

Usage:
  prep_hymn_annotator.py --workdir /mnt/data/chant-corpus/workdirs/mode1 --hymn t04_
  prep_hymn_annotator.py --workdir .../mode1 --all          # every hymn in the workdir
  prep_hymn_annotator.py --all-workdirs                     # the whole corpus

A hymn is skipped (recorded in the manifest with a reason) when its melos dir
has no summary.json/aligned.json — i.e. the aligner has not run on it yet.
Audio is symlinked, not copied. Page renders (pdftoppm, RGB) are cached in
--render-cache and shared across hymns.
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import GLYPHS, LADDERS, load_units_h, beats_seq

# dot count -> printed duration name (chanter: apli 1 beat, dipli 2, tripli 3)
DUR_NAME = {1: 'apli', 2: 'dipli', 3: 'tripli'}

CORPUS = '/mnt/data/chant-corpus'
EXPORTS = ('/mnt/data/code/byzorgan-web-worktrees/chant-annotator/'
           'datasets/exports')
CPM = 1200.0 / 72.0            # cents per moria
# absolute scale degree -> parallagi syllable (Νη=0 … Ζω=6, wrapping by octave);
# the chanter reads solfege, not degree integers
DEG_NAMES = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo']


def deg_name(d):
    """solfege syllable for an absolute degree; ' = octave up, , = octave down"""
    oct_, i = divmod(int(d), 7)
    return DEG_NAMES[i] + ("'" * oct_ if oct_ > 0 else ',' * -oct_)


def deg_label(d):
    return f'{deg_name(d)} ({int(d)})'
ZOOM = 6                       # render scale (pt -> px); 432 dpi
# BAND_DN raised 144 -> 200 (2026-08-24): lyrics hang below the neume line
# and the 144px lower crop cut them off on dense lines (measured: thousands
# of ink pixels in the last 8 rows of mode1 strips).
BAND_UP, BAND_DN = 144, 200    # strip band split around each line center (px)
LINE_BAND = BAND_UP + BAND_DN
PITCH_SRC_DT = 0.01            # s per cents_track sample
PITCH_DT = 0.02                # s per downsampled pitch sample in the JSON


REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..'))


def load_gold_seed(piece, n_units):
    """Curated chanter work for this piece, from datasets/<piece>-gold/.

    Re-segmenting the score changes data_rev, which by design stops stale
    localStorage edits from landing on the wrong slots — but it would also
    hand the chanter a blank piece and throw away verified pins. Shipping the
    frozen gold as a seed means a re-segmentation costs a re-index, not the
    work. Pins whose index is outside the current stream are dropped loudly:
    that means the gold was not re-indexed after a segmentation change.
    """
    gdir = os.path.join(REPO, 'datasets', piece + '-gold')
    pf = os.path.join(gdir, 'pins.json')
    if not os.path.exists(pf):
        # No frozen gold. For a span piece there never is one -- its curated
        # work lives in the EXPORTS directory the annotator writes to, and
        # nothing was loading it back. Chanter, 2026-08-21: "when i open s02 i
        # dont see my exported pins. its still the original ones but i know
        # yesterday i exported s02."
        #
        # He was right and the cause was a regeneration. Re-prepping a piece
        # changes data_rev, which by design orphans stale localStorage edits so
        # they cannot land on the wrong slots -- but with no seed to fall back
        # on it hands back a blank piece. His export was safe on disk the whole
        # time; the annotator simply had no path from the export back to the
        # screen. Seeding from it closes that loop, so a regeneration costs a
        # reload rather than the work.
        #
        # The frozen gold still wins where it exists: t03's export is the stale
        # 75-unit pre-split copy and must never seed anything.
        gdir = os.path.join(EXPORTS, piece)
        pf = os.path.join(gdir, 'pins.json')
        if not os.path.exists(pf):
            return None
    pins = [p for p in json.load(open(pf)) if isinstance(p, (list, tuple))]
    keep = [p for p in pins if 0 <= p[0] < n_units]
    if len(keep) != len(pins):
        print(f'  WARNING {piece}: {len(pins) - len(keep)} gold pins fall outside '
              f'the current {n_units}-unit stream — re-index the gold')
    seed = {'pins': keep, 'source': os.path.relpath(gdir, REPO),
            # When the chanter last pressed Export. The annotator compares this
            # against its own autosave stamp and takes whichever is newer -- see
            # restore() in index.html for why that comparison has to exist.
            'exported_at': os.path.getmtime(pf)}
    nf = os.path.join(gdir, 'chanter_notes.json')
    if os.path.exists(nf):
        seed['flags'] = [{'gi': n['gi'], 'note': n['note']}
                         for n in json.load(open(nf))
                         if 0 <= n.get('gi', -1) < n_units]
    return seed


def find_pdf():
    for f in glob.glob('/mnt/data/code/byzorgan-web/*.pdf'):
        if 'Ιωάννου' in unicodedata.normalize('NFC', os.path.basename(f)):
            return f
    sys.exit('Ioannou Anastasimatarion PDF not found in /mnt/data/code/byzorgan-web')


def render_page(pdf, page, cache_dir):
    """Rendered page png (ZOOM x pt), cached."""
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, f'page{page:03d}.png')
    if not os.path.exists(out):
        # Render to a scratch name and rename into place. The cache is keyed on
        # existence alone, so a pdftoppm killed part-way (a timeout, a Ctrl-C)
        # used to leave a truncated PNG that every later run happily reused and
        # then failed to decode. os.replace is atomic within the directory.
        tmp = os.path.join(cache_dir, f'.page{page:03d}.{os.getpid()}')
        # -cropbox: glyph JSON coords are CropBox-relative (fitz page space)
        subprocess.run(['pdftoppm', '-png', '-cropbox', '-r', str(72 * ZOOM),
                        '-f', str(page), '-l', str(page),
                        '-singlefile', pdf, tmp], check=True)
        os.replace(tmp + '.png', out)
    return out


def line_extent(page, line):
    """(top, bottom) content extent of one page line in pt (neumes + lyrics)."""
    d = json.load(open(os.path.join(GLYPHS, f'page{page:03d}.json')))
    y0, y1 = 1e9, -1e9
    for g in d['glyphs']:
        if g['line'] == line:
            y0, y1 = min(y0, g['y0']), max(y1, g['y1'])
    for w in d.get('lyrics', []):
        if w.get('line', 0) == line:
            y0 = min(y0, w['y0'])
            y1 = max(y1, w.get('y1', w['y0'] + 9))
    if y1 < y0:
        return None
    return y0, y1


def hymn_lines(h):
    """ordered [(page, line), ...] of the hymn slice."""
    out = []
    for p in range(h['p0'], h['p1'] + 1):
        d = json.load(open(os.path.join(GLYPHS, f'page{p:03d}.json')))
        lines = sorted({g['line'] for g in d['glyphs']})
        for li in lines:
            if p == h['p0'] and li < h['l0']:
                continue
            if p == h['p1'] and li >= h['l1']:
                continue
            out.append((p, li))
    return out


def hymn_x_clip(units):
    """(page,line) -> x range in pt that actually belongs to THIS hymn.

    A band is cropped to the full page width, so the last line of a span also
    draws whatever is printed to the right of the final cadence martyria. In
    this book that is the NEXT hymn's opening martyria, flung out to the margin,
    plus its red title. Chanter on s04: "the martyria ends at zo but then the
    score goes on ... where it says glory both now in greek and then there is a
    ga martyria. the issue was it cut the score too long."

    Measured, p521 line 4: the notes end at x1 159.6, the Zo CADENCE martyria
    sits at 160.8-178.8, then a 332 pt gap, then the Ga OPENING martyria at
    510.6-523.4. Both are red, both attach to the same unit (mart_all [6, 3]),
    and only the first is a claim about this hymn.

    They separate on the same bimodal x-gap that hymn_align already uses to tell
    a cadence martyria from an opening one (MART_OPEN_GAP, 40 pt: 679 martyrias
    inline within 20 pt, 254 flung out at 80 pt or more). So the cut is not a
    new threshold -- it is the existing chanter-derived one, applied to the
    picture instead of to the degrees.

    Only the first and last lines are clipped; interior lines are wholly inside
    the hymn by construction.
    """
    from hymn_align import MART_OPEN_GAP
    if not units:
        return {}
    first, last = units[0], units[-1]
    clip = {}
    pl0, pl1 = tuple(first['pl']), tuple(last['pl'])
    lo0 = first['x0'] - 2.0
    # The drop cap is printed LEFT of the first neume and belongs to THIS
    # hymn — clipping at the neume's x whitewashed the Κ of every hymn that
    # opens one (chanter caught it on mode2 katefthynthito). 26/26 measured
    # hymn starts land on a cap, so look one up and keep it.
    try:
        caps = json.load(open('/mnt/data/chant-corpus/scores/dropcaps.json'))
        for c in caps:
            if c.get('page') == pl0[0] and c.get('size', 0) >= 18.0 \
                    and abs(c.get('line', -9) - pl0[1]) <= 1 \
                    and first['x0'] - 70 <= c['x0'] < first['x0']:
                lo0 = min(lo0, c['x0'] - 3.0)
    except Exception:
        pass
    clip[pl0] = [lo0, None]
    xs = sorted(_line_glyph_spans(*pl1))
    keep = last['x1']
    for x0, x1 in xs:                       # walk right from the last note
        if x0 <= keep + 1:
            keep = max(keep, x1)
            continue
        if x0 - keep >= MART_OPEN_GAP:      # flung to the margin: next hymn
            break
        keep = max(keep, x1)                # inline: still this hymn
    lo = clip.get(pl1, [None, None])[0]
    clip[pl1] = [lo, keep + 2.0]
    return clip


def _line_glyph_spans(page, line):
    """(x0, x1) of every glyph printed on a page line, from the glyph store."""
    import glob as _glob
    from hymn_align import GLYPHS
    f = os.path.join(GLYPHS, 'page%03d.json' % page)
    if not os.path.exists(f):
        hits = _glob.glob(os.path.join(GLYPHS, '*%d*' % page))
        if not hits:
            return []
        f = hits[0]
    rows = json.load(open(f))
    rows = rows if isinstance(rows, list) else rows.get('glyphs', [])
    return [(r['x0'], r['x1']) for r in rows if r.get('line') == line]


def build_strip(pdf, lines, cache_dir, out_png, clip=None):
    """Stack one LINE_BAND-tall band per hymn line; content centered.

    `clip` is {(page,line): [x0_pt or None, x1_pt or None]} -- content outside
    that range is painted white rather than cropped away, so every strip x
    coordinate still equals page x and the annotator's unit boxes keep working.
    See hymn_x_clip().

    Returns (strip_w, strip_h, line_centers, {(page,line): band_top_pt})."""
    from PIL import Image, ImageDraw
    clip = clip or {}
    pages = {}
    for p, _ in lines:
        if p not in pages:
            pages[p] = Image.open(render_page(pdf, p, cache_dir))
    strip_w = max(im.width for im in pages.values())
    strip = Image.new('RGB', (strip_w, LINE_BAND * len(lines)), 'white')
    centers, tops = [], {}
    for i, (p, li) in enumerate(lines):
        im = pages[p]
        ext = line_extent(p, li)
        if ext is None:
            ext = (0, LINE_BAND / ZOOM)
        cy_px = (ext[0] + ext[1]) / 2 * ZOOM
        top_px = cy_px - BAND_UP           # content centered in the band
        band = im.crop((0, int(round(max(0, top_px))),
                        im.width, int(round(max(0, top_px))) + LINE_BAND))
        strip.paste(band, (0, i * LINE_BAND))
        cx = clip.get((p, li))
        if cx:
            d = ImageDraw.Draw(strip)
            if cx[0] is not None:
                d.rectangle([0, i * LINE_BAND,
                             max(0, int(cx[0] * ZOOM)), (i + 1) * LINE_BAND - 1],
                            fill='white')
            if cx[1] is not None:
                d.rectangle([int(cx[1] * ZOOM), i * LINE_BAND,
                             strip_w, (i + 1) * LINE_BAND - 1], fill='white')
        tops[(p, li)] = max(0, top_px) / ZOOM     # band top in pt
        centers.append(i * LINE_BAND + BAND_UP)
    strip.save(out_png)
    return strip_w, strip.height, centers, tops


def machine_times(units, aligned, beats, duration):
    """Per-unit machine onset: aligned t0 where matched, beat-weighted
    interpolation elsewhere; strictly increasing, clamped to [0, duration]."""
    t = [None] * len(units)
    for a in aligned:
        if 0 <= a['unit'] < len(units):
            t[a['unit']] = a['t0']
    matched = [j for j, v in enumerate(t) if v is not None]
    if not matched:
        # never aligned: spread evenly (annotator still usable, all machine)
        total = sum(beats)
        acc = 0.0
        for j in range(len(units)):
            t[j] = duration * acc / total if total else 0.0
            acc += beats[j]
        return t, 0
    # seconds-per-beat estimate from matched spans
    spans = [(t[b] - t[a]) / max(1e-6, sum(beats[a:b]))
             for a, b in zip(matched, matched[1:]) if t[b] > t[a]]
    spans.sort()
    spb = spans[len(spans) // 2] if spans else 0.5
    first, last = matched[0], matched[-1]
    for j in range(first - 1, -1, -1):          # extrapolate backwards
        t[j] = max(0.0, t[j + 1] - beats[j] * spb)
    for j in range(last + 1, len(units)):       # extrapolate forwards
        t[j] = min(duration - 0.05, t[j - 1] + beats[j - 1] * spb)
    for a, b in zip(matched, matched[1:]):      # interpolate gaps by beats
        if b - a < 2:
            continue
        gap_b = sum(beats[a:b])
        acc = 0.0
        for j in range(a + 1, b):
            acc += beats[j - 1]
            t[j] = t[a] + (t[b] - t[a]) * (acc / gap_b if gap_b else 0)
    for j in range(1, len(t)):                  # enforce monotone
        if t[j] <= t[j - 1]:
            t[j] = t[j - 1] + 0.01
    return t, len(matched)


def attach_words(units, lyrics):
    """word text per unit from lyric x spans (same page line).
    Returns (word_of_unit, word_start flags)."""
    word = [''] * len(units)
    start = [False] * len(units)
    by_line = {}
    for j, u in enumerate(units):
        by_line.setdefault(tuple(u['pl']), []).append(j)
    for w in lyrics:
        pl = (w['page'], w.get('line', 0))
        js = by_line.get(pl)
        if not js:
            continue
        wx = w['x0']
        best = min(js, key=lambda j: abs(units[j]['x0'] - wx))
        if not start[best] or abs(units[best]['x0'] - wx) < 3:
            start[best] = True
            word[best] = w['text']
    cur = ''
    for j in range(len(units)):
        if start[j]:
            cur = word[j]
        word[j] = cur
    return word, start


def audio_duration(path):
    import wave
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def prep_hymn(wd, h, pdf, ann_data_dir, cache_dir):
    """Prep one hymn; returns manifest record."""
    import numpy as np
    name = h['name']
    wdname = os.path.basename(os.path.normpath(wd))
    piece = f"{wdname}-{name.strip('_')}"
    rec = {'id': piece, 'workdir': wd, 'hymn': name, 'genus': h.get('genus'),
           'prepped_at': time.strftime('%Y-%m-%d %H:%M')}
    mdir = os.path.join(wd, 'melos_' + name)
    summ_f = os.path.join(mdir, 'summary.json')
    alig_f = os.path.join(mdir, 'aligned.json')
    wav_f = os.path.join(mdir, 'audio.wav')
    for f, why in ((summ_f, 'no summary.json (unaligned)'),
                   (alig_f, 'no aligned.json'), (wav_f, 'no audio.wav')):
        if not os.path.exists(f):
            rec['status'] = 'skipped: ' + why
            return rec
    summ = json.load(open(summ_f))
    aligned = json.load(open(alig_f))
    # aligned.json is the ALIGNER's output, and its 'unit' fields index the unit
    # stream as it was when the aligner ran. Re-segmenting the score — the
    # kentimata split, the silenced chiasma — moves those indices, so a stale
    # aligned.json does not just crash on the tail (it did, on 6 hymns), it
    # quietly hangs the right times on the WRONG glyphs for every hymn where it
    # does not crash. Detected here rather than papered over: the piece is still
    # built, because the score side and the chanter's own pins are what he works
    # from, but the machine times are marked untrustworthy and the manifest says
    # so. Fixing it properly means re-running the aligner, which is its own job.
    genus = summ['genus']
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    units, lyrics = load_units_h(h)
    if not units:
        rec['status'] = 'skipped: no units in slice'
        return rec
    n_over = sum(1 for a in aligned if not 0 <= a['unit'] < len(units))
    stale = n_over > 0 or (summ.get('n_units') not in (None, len(units)))

    out = os.path.join(ann_data_dir, piece)
    os.makedirs(out, exist_ok=True)

    # ---- strip + note geometry ----
    lines = hymn_lines(h)
    # Drop lines that contribute NO units: a stray red glyph on its own line
    # (p12 l2, one 7pt rubric mark) got a full band whose crop showed the line
    # above AGAIN, and the follower glided across the duplicate. A band with
    # nothing to point at is only noise.
    unit_pls = {tuple(u['pl']) for u in units}
    lines = [pl for pl in lines if pl in unit_pls] or lines
    if h.get('g0') is not None or h.get('g1') is not None:
        # g0/g1-trimmed hymn: only strip the lines its units actually occupy
        occ = {tuple(u['pl']) for u in units}
        lines = [pl for pl in lines if pl in occ]
    line_ix = {pl: i for i, pl in enumerate(lines)}
    strip_w, strip_h, centers, tops = build_strip(
        pdf, lines, cache_dir, os.path.join(out, 'strip.png'), clip=hymn_x_clip(units))
    notes = []
    for j, u in enumerate(units):
        pl = tuple(u['pl'])
        li = line_ix[pl]
        ty = tops[pl]
        notes.append({
            'cp': u['base'], 'key': u['key'], 'line': li,
            **({'iv': u['iv']} if u.get('iv') is not None else {}),
            **({'part': u['part']} if u.get('part') is not None else {}),
            'x0': round(u['x0'] * ZOOM, 1), 'x1': round(u['x1'] * ZOOM, 1),
            'y0': round((u['y0'] - ty) * ZOOM + li * LINE_BAND, 1),
            'y1': round((u['y1'] - ty) * ZOOM + li * LINE_BAND, 1),
        })

    # ---- machine interpretation + slot times ----
    duration = audio_duration(wav_f)
    beats = beats_seq(units)
    times, n_matched = machine_times(units, aligned, beats, duration)
    word, wstart = attach_words(units, lyrics)
    pos = LADDERS[genus]
    # absolute expected degrees: parallagi-derived unitdeg anchors where
    # available (the aligner's own anchor source) — the raw cumulative legend
    # sum drifts over a hymn, which is exactly why the aligner needs anchors
    unitdeg = {}
    udf = os.path.join(wd, f'unitdeg_{name}.json')
    if os.path.exists(udf):
        unitdeg = {int(k): v for k, v in json.load(open(udf)).items()}
    expected, mcr = [], []
    matched_units = {a['unit'] for a in aligned}
    for j, u in enumerate(units):
        # A per-instance reading set by hymn_align (kentima height split,
        # running elaphron, orphan kentima, chanter rulings on the row) beats
        # the key's legend value. Chanter, 2026-09-01, thou-kyrie-par glyphs
        # 313/602 (7|16ab+6ab, low kentima): "Should be +2 only" -- the
        # aligner already knew, this line printed the legend's +3 / a 0.
        interval = (u['iv'] if u.get('iv') is not None
                    else iv.get(u['key'], iv.get(f"{u['base']}|", 0)))
        exp = unitdeg.get(j)
        expected.append(exp)
        mcr.append({
            'gi': j, 'cp': u['key'], 'name': u['key'], 'line': notes[j]['line'],
            'sub_notes': 1, 'beats': [beats[j]],
            'gorgon': bool(u['gorgon']),
            'duration_mark': '+'.join(
                (['klasma'] if u['klasma'] else [])
                + ([DUR_NAME.get(u.get('dots', 0), f"{u['dots']} dots")]
                   if u.get('dots') else [])) or 'none',
            'quality_marks': [], 'other_marks':
                ([f'interval {interval:+d}'] if isinstance(interval, int) else
                 [f'interval {interval:+.1f}'])
                + (['martyria: %s' % deg_label(u['mart_deg'])] if 'mart_deg' in u else [])
                + (['tempo: %s' % u['tempo']] if u.get('tempo') else [])
                + ([] if j in matched_units else ['UNMATCHED (interpolated time)'])
                + (['ALIGNMENT STALE: times predate a re-segmentation'] if stale else []),
            'expected_degrees': [exp] if exp is not None else None,
            'ison_at_start': None,
            'slot_ids': [j], 'word': word[j], 'word_start': bool(wstart[j]),
        })

    # ---- pitch: cents -> moria rel fitted Νη ----
    pitch = None
    cents_f = os.path.join(mdir, 'cents_track.npy')
    if os.path.exists(cents_f) and summ.get('ni_cents_rel55') is not None:
        cents = np.load(cents_f)
        mor = (cents - summ['ni_cents_rel55']) / CPM
        step = max(1, round(PITCH_DT / PITCH_SRC_DT))
        ds = mor[::step]
        pitch = {'dt': PITCH_SRC_DT * step,
                 'moria': [None if not np.isfinite(v) else round(float(v), 1)
                           for v in ds]}

    # ---- genus-correct degree grid + pitch range, from OBSERVED degrees
    # (aligned degree_obs + parallagi unitdeg anchors; the drifting legend
    # sum would blow the grid up) ----
    seen = ([a['degree_obs'] for a in aligned if a.get('degree_obs') is not None]
            + [v for v in unitdeg.values() if v is not None]) or [0, 7]
    dmin, dmax = int(min(seen)) - 2, int(max(seen)) + 2
    step_deg = list(range(dmin, dmax + 1))
    step_pos = [round(pos(d), 1) for d in step_deg]
    step_name = [deg_name(d) for d in step_deg]
    mor_min, mor_max = min(step_pos) - 10, max(step_pos) + 10

    gis = list(range(len(units)))
    data_rev = hashlib.md5(json.dumps([gis, [0] * len(units)]).encode()).hexdigest()[:10]
    data = {
        'meta': {
            'piece_id': piece, 'data_rev': data_rev,
            'duration': round(duration, 3),
            'strip_w': strip_w, 'strip_h': strip_h, 'line_centers': centers,
            'audio': 'audio.wav', 'strip': 'strip.png',
            'slot_struct_verified': True,
            'alignment_stale': stale,
            'band_up': BAND_UP, 'band_dn': BAND_DN,
            'step_pos': step_pos, 'step_deg': step_deg, 'step_name': step_name,
            'mor_min': mor_min, 'mor_max': mor_max,
            'source': {'workdir': wd, 'hymn': name, 'genus': genus,
                       'pages': [h['p0'], h['p1']]},
        },
        'notes': notes,
        'anchors': [{'gi': j, 'text': word[j]} for j in range(len(units)) if wstart[j]],
        'slots': {'t': [round(t, 3) for t in times], 'gi': gis,
                  'sub': [0] * len(units), 'w': beats,
                  'label': [word[j] if wstart[j] else '' for j in range(len(units))]},
        'words': [], 'pitch': pitch, 'ison': [], 'barlines': [], 'analytical': [],
    }
    seed = load_gold_seed(piece, len(units))
    if seed:
        data['seed'] = seed
    with open(os.path.join(out, 'annotator_data.json'), 'w') as f:
        json.dump(data, f)
    with open(os.path.join(out, 'mcr_interpretation.json'), 'w') as f:
        json.dump(mcr, f, indent=1)
    link = os.path.join(out, 'audio.wav')
    if os.path.islink(link) or os.path.exists(link):
        os.remove(link)
    os.symlink(os.path.abspath(wav_f), link)

    rec.update({
        'status': 'ready', 'data_rev': data_rev, 'n_units': len(units),
        'alignment_stale': stale,
        'aligned_out_of_range': n_over,
        'n_matched': n_matched,
        'coverage_pct': summ.get('coverage_units_pct'),
        'movement_agreement': summ.get('movement_agreement'),
        'duration': round(duration, 1), 'n_lines': len(lines),
    })
    return rec


def update_manifest(ann_data_dir, recs):
    """Merge records into data/index.json (keyed by piece id)."""
    path = os.path.join(ann_data_dir, 'index.json')
    man = {'pieces': []}
    if os.path.exists(path):
        man = json.load(open(path))
    by_id = {p['id']: p for p in man['pieces']}
    for r in recs:
        by_id[r['id']] = {**by_id.get(r['id'], {}), **r}
    man['pieces'] = sorted(by_id.values(), key=lambda p: p['id'])
    man['generated_at'] = time.strftime('%Y-%m-%d %H:%M')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(man, f, indent=1)
    os.replace(tmp, path)
    return path


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_ann = os.path.normpath(os.path.join(here, '..', 'chant-reel', 'annotator'))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', help='mode workdir (has hymns.json)')
    ap.add_argument('--hymn', help='hymn name inside the workdir (e.g. t04_)')
    ap.add_argument('--all', action='store_true', help='all hymns in --workdir')
    ap.add_argument('--all-workdirs', action='store_true',
                    help=f'every workdir under {CORPUS}/workdirs')
    ap.add_argument('--annotator-dir', default=default_ann)
    ap.add_argument('--render-cache', default=f'{CORPUS}/scores/page_renders')
    args = ap.parse_args()

    pdf = find_pdf()
    ann_data = os.path.join(args.annotator_dir, 'data')
    os.makedirs(ann_data, exist_ok=True)

    jobs = []           # (workdir, hymn-record)
    if args.all_workdirs:
        wds = sorted(glob.glob(os.path.join(CORPUS, 'workdirs', '*')))
    elif args.workdir:
        wds = [args.workdir]
    else:
        ap.error('need --workdir or --all-workdirs')
    for wd in wds:
        hf = os.path.join(wd, 'hymns.json')
        if not os.path.isfile(hf):
            continue
        hymns = json.load(open(hf))
        for h in hymns:
            if args.hymn and h['name'] != args.hymn:
                continue
            jobs.append((wd, h))
    if args.hymn and not jobs:
        sys.exit(f'hymn {args.hymn!r} not found')
    if not (args.hymn or args.all or args.all_workdirs):
        sys.exit('refusing to prep a whole workdir without --all (or give --hymn)')

    recs, n_ok = [], 0
    for wd, h in jobs:
        try:
            r = prep_hymn(wd, h, pdf, ann_data, args.render_cache)
        except Exception as e:
            r = {'id': f"{os.path.basename(os.path.normpath(wd))}-{h['name'].strip('_')}",
                 'workdir': wd, 'hymn': h['name'], 'status': f'ERROR: {e}',
                 'prepped_at': time.strftime('%Y-%m-%d %H:%M')}
        recs.append(r)
        n_ok += r['status'] == 'ready'
        print(f"{r['id']}: {r['status']}"
              + (f" — {r['n_units']} units, {r['n_matched']} matched, "
                 f"{r['n_lines']} lines, {r['duration']}s"
                 if r['status'] == 'ready' else ''), flush=True)
    path = update_manifest(ann_data, recs)
    print(f"\n{n_ok}/{len(recs)} pieces ready; manifest: {path}")


if __name__ == '__main__':
    main()
