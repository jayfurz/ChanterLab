#!/usr/bin/env python3
"""serve.py — boundary cutter: mark each hymn's start and end by ear.

Every automatic attempt at this has been measured and found wanting: silence
walks overran into the next hymn, forced-alignment windows smeared the final
melisma, and CTC identification turned out ~20% correct (see
docs/plans/RESEP-IDENTIFICATION.md). The chanter can settle a boundary in
seconds that the pipeline gets wrong in minutes, so this hands him the tape.

Serves the tapes with HTTP Range support -- SimpleHTTPRequestHandler does not,
and without it a browser cannot seek inside a two-hour recording, which is the
one thing a cutter must do.

  GET  /api/tapes           workdirs, tape URL, hymn list, existing bounds
  GET  /tape/<workdir>      the audio, range-enabled
  POST /api/cuts            {workdir, cuts:[{hymn,t0,t1}]} -> cuts_<wd>.json

Writes to /mnt/data/chant-corpus/texts/cuts_<workdir>.json and never touches
hymns.json; adopting is a separate, reviewable step.

Usage:  serve.py [--port 8790] [--bind 0.0.0.0]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))       # tools/corpus
TEXTS = '/mnt/data/chant-corpus/texts'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
WD_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
MAX_BODY = 8 * 1024 * 1024
MIME = {'.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
PEAKS = f'{TEXTS}/peaks'
SCORES = '/mnt/data/chant-corpus/scores'
RENDERS = f'{SCORES}/page_renders'
GLYPHS = f'{SCORES}/glyphs'
THUMBS = f'{TEXTS}/page_thumbs'
OFFSETS = f'{SCORES}/page_offsets.json'
# The page renders are exactly 6x the PDF points the glyph boxes are given in.
# Solved rather than assumed: at 6.000 the mean ink inside a glyph box is 0.373
# against 0.100 at the A4 guess, and 53% of all page ink lands inside a box
# (the rest is lyric text, which is stored separately).
PT2PX = 6.0
THUMB_W = 1100
PAD_BEFORE = 2
PAD_AFTER = 12
PPS = 20                # peak buckets per second -> 50 ms resolution
PEAK_SR = 8000          # decode rate for the envelope; plenty for amplitude


def peaks_for(wd, path):
    """Amplitude envelope as one uint8 per 50 ms, cached on disk.

    A browser cannot decode a two-hour tape to draw a waveform, and without a
    waveform there is nothing to zoom into -- which is the whole reason the
    first version was unusable. So ffmpeg does it once, server side, and the
    page fetches ~80 KB of bytes instead of 200 MB of audio.
    """
    os.makedirs(PEAKS, exist_ok=True)
    out = f'{PEAKS}/{wd}.u8'
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out
    import array
    p = subprocess.Popen(
        ['ffmpeg', '-v', 'quiet', '-i', path, '-f', 's16le',
         '-ac', '1', '-ar', str(PEAK_SR), '-'],
        stdout=subprocess.PIPE)
    step = PEAK_SR // PPS
    buf, tmp = bytearray(), b''
    while True:
        chunk = p.stdout.read(step * 2 * 256)
        if not chunk:
            break
        tmp += chunk
        n = len(tmp) // (step * 2)
        if not n:
            continue
        a = array.array('h')
        a.frombytes(tmp[:n * step * 2])
        tmp = tmp[n * step * 2:]
        for i in range(n):
            seg = a[i * step:(i + 1) * step]
            m = 0
            for v in seg:
                if v < 0:
                    v = -v
                if v > m:
                    m = v
            buf.append(min(255, m >> 7))
    p.stdout.close(); p.wait()
    with open(out, 'wb') as fh:
        fh.write(bytes(buf))
    return out


EXTRA = f'{TEXTS}/extra_tapes.json'


def _clean_skips(raw, row):
    """Intervals to drop from inside a span.

    Vasilikos sometimes speaks mid-span -- "this is the final ending of the
    prokeimenon" sits inside the anavathmoi parallagi. That audio has no neumes
    behind it, so an aligner handed it stretches the surrounding notes over the
    talking. Excluding a whole span for a few spoken seconds would throw away a
    five-minute parallagi, so the skip is an interval, not a boundary.
    """
    out = []
    for iv in raw or []:
        a, b = float(iv[0]), float(iv[1])
        if b <= a:
            raise ValueError(f'skip {a:.2f}-{b:.2f} is empty or reversed')
        if a < row['t0'] - 0.001 or b > row['t1'] + 0.001:
            raise ValueError(
                f"skip {a:.2f}-{b:.2f} is outside the span "
                f"{row['t0']:.2f}-{row['t1']:.2f}")
        out.append([round(a, 3), round(b, 3)])
    out.sort()
    for i in range(1, len(out)):
        if out[i][0] < out[i - 1][1] - 0.001:
            raise ValueError(f'skips {out[i-1]} and {out[i]} overlap')
    return out


def _saved_spans(wd):
    f = f'{TEXTS}/cuts_{wd}.json'
    if not os.path.exists(f):
        return {}
    try:
        return {c['hymn']: c for c in json.load(open(f))['cuts']}
    except Exception:
        return {}


def tapes():
    out = {}
    for f in sorted(glob.glob(f'{TEXTS}/recut_*.json')):
        wd = os.path.basename(f)[6:-5]
        try:
            rows = json.load(open(f))
        except Exception:
            continue
        tape = rows[0].get('tape') if rows else None
        if not tape or not os.path.exists(tape):
            continue
        cur = {r['hymn']: r.get('cur') for r in rows}
        hj = f'{WORKDIRS}/{wd}/hymns.json'
        if not os.path.exists(hj):
            continue
        saved = {}
        sf = f'{TEXTS}/cuts_{wd}.json'
        if os.path.exists(sf):
            try:
                saved = {c['hymn']: c for c in json.load(open(sf))['cuts']}
            except Exception:
                saved = {}
        hymns = []
        for h in json.load(open(hj)):
            n = h['name']
            s = saved.get(n)
            hymns.append({'name': n, 'cur': cur.get(n),
                          't0': s['t0'] if s else None,
                          't1': s['t1'] if s else None,
                          'label': (s or {}).get('label'),
                          'lane': (s or {}).get('lane'),
                          't_in': (s or {}).get('t_in'),
                          'skips': (s or {}).get('skips') or [],
                          'page': h.get('p0'), 'line': h.get('l0')})
        # spans the chanter added with "+ span" have no hymns.json row, so
        # carry them back in after their base, or they vanish on reload
        known = {h['name'] for h in hymns}
        for n, c in saved.items():
            if n in known:
                continue
            row = {'name': n, 'cur': None, 't0': c.get('t0'), 't1': c.get('t1'),
                   'label': c.get('label'), 'lane': c.get('lane'),
                   't_in': c.get('t_in'), 'skips': c.get('skips') or [],
                   'extra': True, 'page': None, 'line': None}
            base = n.split('#')[0]
            at = next((i for i, h in enumerate(hymns)
                       if h['name'].split('#')[0] == base), len(hymns) - 1)
            hymns.insert(at + 1, row)
        out[wd] = {'tape': tape, 'basename': os.path.basename(tape),
                   'hymns': hymns}
    # Tapes with no workdir. The goal is every mode for both services, and two
    # of those tapes had no hymns.json so the tool could not see them at all.
    # They start with no rows; spans are added from scratch with "+ span".
    if os.path.exists(EXTRA):
        for wd, tape in json.load(open(EXTRA)).items():
            if wd in out or not os.path.exists(tape):
                continue
            saved = _saved_spans(wd)
            hymns = [{'name': n, 'cur': None, 't0': c.get('t0'),
                      't1': c.get('t1'), 'label': c.get('label'),
                      'lane': c.get('lane'), 't_in': c.get('t_in'),
                      'skips': c.get('skips') or [], 'extra': True, 'page': None, 'line': None}
                     for n, c in sorted(saved.items(),
                                        key=lambda kv: kv[1].get('t0', 0))]
            out[wd] = {'tape': tape, 'basename': os.path.basename(tape),
                       'hymns': hymns, 'no_workdir': True}
    return out


def page_thumb(pno):
    """Downscaled page, cached. The masters are 3498x4943 and 104 MB for the
    book; a phone needs neither."""
    os.makedirs(THUMBS, exist_ok=True)
    out = f'{THUMBS}/page{pno}.jpg'
    src = f'{RENDERS}/page{pno}.png'
    if not os.path.exists(src):
        # No master render: the book view wants EVERY page of the
        # Anastasimatarion, so rasterise straight from the PDF at thumbnail
        # width. Cached like the master path; a miss costs one pdftoppm.
        if os.path.exists(out):
            return out
        bm = _book_map()
        pdf = (bm or {}).get('pdf')
        if not pdf or not os.path.exists(pdf) or pno < 1:
            return None
        tmp = f'{THUMBS}/.pdf{pno}.{os.getpid()}'
        subprocess.run(['pdftoppm', '-jpeg', '-cropbox',
                        '-scale-to-x', str(THUMB_W), '-scale-to-y', '-1',
                        '-f', str(pno), '-l', str(pno), pdf, tmp],
                       check=False)
        got = glob.glob(tmp + '*')
        if not got:
            return None
        os.replace(got[0], out)
        return out
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        from PIL import Image
        im = Image.open(src).convert('RGB')
        im.thumbnail((THUMB_W, THUMB_W * 4), Image.LANCZOS)
        im.save(out, 'JPEG', quality=82, optimize=True)
    return out


def beats(u):
    """Written beats for a unit, for display only."""
    try:
        from hymn_align import beats_written
        return beats_written(u)
    except Exception:
        return 1.0


def _save_guarded(out, payload, hist, kind):
    """Write a cuts file, keeping what is ALREADY there rather than what is
    arriving, and refusing a save that throws most of it away.

    The history copy used to be of the INCOMING payload, which is backwards: it
    preserved the destructive write and lost the thing being destroyed. On
    2026-08-19 a stray POST of {"cuts": []} took
    scorecuts_grave-orthros.json from 47 chanter-marked score ranges to 0
    (6440 -> 77 bytes), and the only surviving snapshot was an unrelated older
    one. These are hand-marked by ear over hours and cannot be regenerated.

    So: snapshot the existing file first, and treat a save that drops more than
    a third of the rows as a mistake unless the caller says otherwise with
    "confirm_shrink": true. Growing, or editing in place, is always allowed.
    """
    os.makedirs(hist, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    old = None
    if os.path.exists(out):
        try:
            old = json.load(open(out))
        except Exception:
            old = None
        shutil.copy2(out, f'{hist}/{kind}_PREV_{stamp}.json')
    n_old = len(old.get('cuts', [])) if isinstance(old, dict) else 0
    n_new = len(payload['cuts'])
    if n_old and n_new < n_old * 2 / 3 and not payload.pop('confirm_shrink', False):
        return (f'refusing to drop {n_old - n_new} of {n_old} marked rows '
                f'(saving {n_new}). The previous file is unchanged and also '
                f'copied to {hist}/{kind}_PREV_{stamp}.json. Re-POST with '
                f'"confirm_shrink": true if this is deliberate.')
    json.dump(payload, open(f'{hist}/{kind}_{stamp}.json', 'w'),
              indent=1, ensure_ascii=False)
    tmp = out + '.tmp'
    json.dump(payload, open(tmp, 'w'), indent=1, ensure_ascii=False)
    os.replace(tmp, out)
    return None


def score_pages(wd):
    OFF = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    # Drop caps. Measured on the gold tape, 26 of 26 score-range starts land
    # exactly on one, so snapping a start to the nearest cap cannot lose a
    # correct answer -- it can only prevent a wrong one. There are ~4x more
    # caps than hymns (they also open verses inside a hymn), so this narrows
    # the choice rather than making it.
    CAPS = {}
    try:
        for c in json.load(open(f'{SCORES}/dropcaps.json')):
            if c.get('size', 0) >= 18.0:
                CAPS.setdefault(c['page'], []).append(c)
    except Exception:
        pass
    hj = f'{WORKDIRS}/{wd}/hymns.json'
    if not os.path.exists(hj):
        return None
    hy = json.load(open(hj))
    # hymns.json's page bounds are the thing being corrected, so they must not
    # also bound what can be SEEN. The doxology runs past the last page any
    # hymns.json row mentions, which made its ending unreachable in the picker.
    p0 = min(h['p0'] for h in hy) - PAD_BEFORE
    p1 = max(h['p1'] for h in hy) + PAD_AFTER
    pages = []
    for pno in range(p0, p1 + 1):
        gf = f'{GLYPHS}/page{pno}.json'
        if not os.path.exists(gf) or not os.path.exists(f'{RENDERS}/page{pno}.png'):
            continue
        d = json.load(open(gf))
        off = OFF.get(str(pno), {})
        # Tap targets are UNITS, not raw glyphs. A unit is the compound the
        # chanter actually reads -- base note plus the apli/dipli/tripli/klasma
        # that only augment its beat count -- and it is also the g0/g1
        # coordinate load_units_h already indexes by. Picking a sub-glyph out
        # of a compound was both confusing and the wrong granularity.
        from hymn_align import load_units
        try:
            us, _ = load_units(pno, 0, pno, 10 ** 6)
        except Exception:
            us = []
        gl = [{'i': i, 'l': u['pl'][1],
               'x0': round(u['x0'], 1), 'y0': round(u['y0'], 1),
               'x1': round(u['x1'], 1), 'y1': round(u['y1'], 1),
               'k': ('rest' if u.get('rest') else str(u.get('base'))),
               'b': round(beats(u), 2),
               # carries apli/dipli/tripli or klasma: hymns tend to end on one
               'c': 1 if (u.get('apli') or u.get('klasma') or u.get('dots')) else 0}
              for i, u in enumerate(us)]
        caps = []
        for c in sorted(CAPS.get(pno, []), key=lambda c: (c['line'], c['x0'])):
            near = [u for u in gl if u['l'] == c['line']]
            if not near:
                continue
            best = min(near, key=lambda u: abs(u['x0'] - c['x0']))
            caps.append({'i': best['i'], 'l': c['line'],
                         'letter': c.get('letter', '')})
        pages.append({
            'page': pno, 'lines': d.get('n_lines', 0), 'scale': PT2PX,
            'n_units': len(gl), 'caps': caps,
            # per page: the book has mixed page sizes and the glyph boxes were
            # extracted against the smaller crop, so the taller pages need a
            # vertical shift. Solved by page_offsets.py, never assumed.
            'w': off.get('w', 0), 'h': off.get('h', 0),
            'dx': off.get('dx', 0), 'dy': off.get('dy', 0),
            'ink': off.get('ink'), 'aligned': off.get('ok', True),
            # index within the page, in reading order -- this is the g0/g1
            # coordinate hymns.json already understands
            'glyphs': gl,
        })
    sf = f'{TEXTS}/scorecuts_{wd}.json'
    saved = json.load(open(sf))['cuts'] if os.path.exists(sf) else []
    # The rows to mark are the chanter's own audio spans, not hymns.json --
    # he can hear those, and hymns.json's boundaries are the thing being
    # corrected. Falls back to hymns.json only when a tape has not been cut.
    af = f'{TEXTS}/cuts_{wd}.json'
    spans = json.load(open(af))['cuts'] if os.path.exists(af) else []
    spans = sorted(spans, key=lambda c: c['t0'])
    return {'workdir': wd, 'pages': pages, 'thumb_w': THUMB_W,
            'spans': spans,
            'hymns': [{'name': h['name'], 'p0': h['p0'], 'l0': h['l0'],
                       'p1': h['p1'], 'l1': h['l1']} for h in hy],
            'saved': saved}



# --------------------------------------------------------------------------
# Book view: the whole Anastasimatarion with every workdir's spans in context.
ANNOT_DATA = os.path.normpath(os.path.join(
    HERE, '..', '..', 'chant-reel', 'annotator', 'data'))
EXPORTS_DIR = os.path.normpath(os.path.join(
    HERE, '..', '..', '..', 'datasets', 'exports'))
BOOK_MAP = f'{SCORES}/book_map.json'
_BM = {}


def _book_map():
    if not os.path.exists(BOOK_MAP):
        return None
    m = os.path.getmtime(BOOK_MAP)
    if _BM.get('m') != m:
        _BM['m'], _BM['d'] = m, json.load(open(BOOK_MAP))
    return _BM['d']


def _piece_index():
    """(workdir_basename, hymn_name) -> annotator piece manifest entry."""
    f = os.path.join(ANNOT_DATA, 'index.json')
    if not os.path.exists(f):
        return {}
    out = {}
    try:
        for p in json.load(open(f)).get('pieces', []):
            wd, hy = p.get('workdir'), p.get('hymn')
            if wd and hy and p.get('status') == 'ready':
                out[(os.path.basename(wd), hy)] = p
    except Exception:
        pass
    return out


def _piece_audio(pid):
    """URL path of the piece's audio as the ANNOTATOR serves it, or None."""
    d = os.path.join(ANNOT_DATA, pid)
    for n in ('audio.wav', 'audio.m4a', 'audio.mp3'):
        if os.path.exists(os.path.join(d, n)):
            return f'/data/{pid}/{n}'
    return None


_BOOK = {}


def book():
    """Everything the book view needs, cached on the source files' mtimes.

    Spans come from every workdir's hymns.json — the machine/chanter score
    ranges — with audio-cut times joined on where a tape has been cut. A span
    is shown even when no audio exists for it: the book IS the context.
    """
    hj = sorted(glob.glob(f'{WORKDIRS}/*/hymns.json'))
    sig = tuple((f, os.path.getmtime(f)) for f in hj)
    sig += tuple((f, os.path.getmtime(f))
                 for f in sorted(glob.glob(f'{TEXTS}/cuts_*.json')))
    mi = os.path.join(ANNOT_DATA, 'index.json')
    if os.path.exists(mi):
        sig += ((mi, os.path.getmtime(mi)),)
    if _BOOK.get('sig') == sig:
        return _BOOK['d']
    from hymn_align import load_units_h
    OFF = json.load(open(OFFSETS)) if os.path.exists(OFFSETS) else {}
    pieces = _piece_index()
    bm = _book_map() or {}
    hymns = []
    for f in hj:
        wd = os.path.basename(os.path.dirname(f))
        try:
            rows = json.load(open(f))
        except Exception:
            continue
        rows = rows if isinstance(rows, list) else rows.get('hymns', [])
        cuts = {}
        cf = f'{TEXTS}/cuts_{wd}.json'
        if os.path.exists(cf):
            try:
                cuts = {c['hymn']: c for c in json.load(open(cf))['cuts']}
            except Exception:
                cuts = {}
        for r in rows:
            try:
                us, _ = load_units_h(r)
            except Exception:
                us = []
            if not us:
                continue
            box = lambda u: {'p': u['pl'][0], 'l': u['pl'][1],
                             'x0': round(u['x0'], 1), 'y0': round(u['y0'], 1),
                             'x1': round(u['x1'], 1), 'y1': round(u['y1'], 1)}
            pc = pieces.get((wd, r['name']))
            c = cuts.get(r['name'], {})
            hymns.append({
                'wd': wd, 'name': r['name'], 'genus': r.get('genus'),
                'start': box(us[0]), 'end': box(us[-1]),
                'piece': pc['id'] if pc else None,
                'audio': _piece_audio(pc['id']) if pc else None,
                't0': c.get('t0'), 't1': c.get('t1'),
                'label': c.get('label'), 'lane': c.get('lane'),
            })
    hymns.sort(key=lambda h: (h['start']['p'], h['start']['l'],
                              h['start']['x0']))
    n_pages = int(bm.get('n_pages') or 673)
    pages = []
    for pno in range(1, n_pages + 1):
        off = OFF.get(str(pno), {})
        pages.append({'page': pno, 'w': off.get('w', 0), 'h': off.get('h', 0),
                      'dx': off.get('dx', 0), 'dy': off.get('dy', 0)})
    d = {'pages': pages, 'thumb_w': THUMB_W, 'hymns': hymns,
         'sections': bm.get('sections', [])}
    _BOOK['sig'], _BOOK['d'] = sig, d
    return d


def book_hymn(wd, name):
    """One hymn's playable detail: unit boxes in page space plus the
    annotator's slot times (chanter corrections included) for highlighting."""
    hj = f'{WORKDIRS}/{wd}/hymns.json'
    if not os.path.exists(hj):
        return None
    rows = json.load(open(hj))
    rows = rows if isinstance(rows, list) else rows.get('hymns', [])
    r = next((x for x in rows if x['name'] == name), None)
    if r is None:
        return None
    from hymn_align import load_units_h
    us, _ = load_units_h(r)
    units = [{'p': u['pl'][0], 'l': u['pl'][1],
              'x0': round(u['x0'], 1), 'y0': round(u['y0'], 1),
              'x1': round(u['x1'], 1), 'y1': round(u['y1'], 1)}
             for u in us]
    pc = _piece_index().get((wd, name))
    slots = None
    audio = None
    if pc:
        audio = _piece_audio(pc['id'])
        f = os.path.join(ANNOT_DATA, pc['id'], 'annotator_data.json')
        if os.path.exists(f):
            try:
                D = json.load(open(f))
                s = D.get('slots') or {}
                t, gi = list(s.get('t') or []), list(s.get('gi') or [])
                # chanter-corrected times, index-aligned with the seed
                cf = os.path.join(EXPORTS_DIR, pc['id'],
                                  'slots_corrected.json')
                if os.path.exists(cf):
                    ct = (json.load(open(cf)) or {}).get('t') or []
                    for i, v in enumerate(ct[:len(t)]):
                        if v is not None:
                            t[i] = v
                if t and gi:
                    slots = {'t': t, 'gi': gi}
            except Exception:
                slots = None
    c = {}
    cf = f'{TEXTS}/cuts_{wd}.json'
    if os.path.exists(cf):
        try:
            c = {x['hymn']: x for x in
                 json.load(open(cf))['cuts']}.get(name, {})
        except Exception:
            c = {}
    tape = f'/tape/{wd}' if wd in tapes() else None
    return {'wd': wd, 'name': name, 'units': units, 'slots': slots,
            'piece': pc['id'] if pc else None, 'audio': audio,
            'tape': tape, 't0': c.get('t0'), 't1': c.get('t1')}



def book_units(pno):
    """Tap/drag targets for one page: every unit box in page space."""
    from hymn_align import load_units
    us, _ = load_units(pno, 0, pno, 10 ** 6)
    return [{'i': i, 'l': u['pl'][1],
             'x0': round(u['x0'], 1), 'y0': round(u['y0'], 1),
             'x1': round(u['x1'], 1), 'y1': round(u['y1'], 1)}
            for i, u in enumerate(us)]


def book_span_save(payload):
    """Move one hymn's start or end to a tapped unit, editing hymns.json.

    g0/g1 are indices into the row's OWN (p0,l0)..(p1,l1) unit stream, so both
    are recomputed here rather than trusted from the client: moving the start
    shifts every index after it, and the end must survive that shift. The old
    end unit is resolved to its printed identity (page, line, x0) first and
    found again in the new stream.
    """
    from hymn_align import load_units, load_units_h
    wd, name = payload.get('workdir'), payload.get('hymn')
    which = payload.get('which')
    page, i = payload.get('page'), payload.get('i')
    if not WD_RE.match(wd or '') or which not in ('start', 'end') \
            or not isinstance(page, int) or not isinstance(i, int):
        return None, 'bad request'
    hj = f'{WORKDIRS}/{wd}/hymns.json'
    if not os.path.exists(hj):
        return None, 'unknown workdir'
    rows = json.load(open(hj))
    rows = rows if isinstance(rows, list) else rows.get('hymns', [])
    r = next((x for x in rows if x['name'] == name), None)
    if r is None:
        return None, 'unknown hymn'
    us_p, _ = load_units(page, 0, page, 10 ** 6)
    if not (0 <= i < len(us_p)):
        return None, 'unit out of range'
    u = us_p[i]
    ident = lambda x: (x['pl'][0], x['pl'][1], round(x['x0'], 1))
    # the boundary NOT being moved, by printed identity, before any mutation
    try:
        cur, _ = load_units_h(r)
    except Exception:
        cur = []
    keep = None
    if cur:
        keep = ident(cur[-1]) if which == 'start' else ident(cur[0])
    old = {k: r.get(k) for k in ('p0', 'l0', 'g0', 'p1', 'l1', 'g1')}
    if which == 'start':
        r['p0'], r['l0'] = page, u['pl'][1]
    else:
        r['p1'], r['l1'] = page, u['pl'][1] + 1
    # rebuild both g indices against the new stream
    try:
        stream, _ = load_units(r['p0'], r['l0'], r['p1'], r['l1'])
    except Exception:
        stream = []
    ids = [ident(x) for x in stream]
    tgt = ident(u)
    lo = ids.index(tgt) if tgt in ids else None
    ko = ids.index(keep) if keep in ids else None
    g0 = (lo if which == 'start' else ko)
    g1 = (ko if which == 'start' else lo)
    if g0 is None or g1 is None or g0 > g1:
        for k, v in old.items():
            if v is None:
                r.pop(k, None)
            else:
                r[k] = v
        return None, 'start would land after end (or unit not in range)'
    r['g0'], r['g1'] = g0, g1
    stamp = time.strftime('%Y%m%d-%H%M%S')
    shutil.copy2(hj, f'{hj}.bak-book-{stamp}')
    json.dump(rows, open(hj, 'w'), indent=1, ensure_ascii=False)
    open(hj, 'a').write('\n')
    box = lambda x: {'p': x['pl'][0], 'l': x['pl'][1],
                     'x0': round(x['x0'], 1), 'y0': round(x['y0'], 1),
                     'x1': round(x['x1'], 1), 'y1': round(x['y1'], 1)}
    return {'name': name, 'wd': wd,
            'start': box(stream[g0]), 'end': box(stream[g1])}, None


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p in ('/', '/index.html'):
            f = os.path.join(HERE, 'index.html')
            return self._send(200, open(f, 'rb').read(),
                              'text/html; charset=utf-8')
        if p == '/api/tapes':
            return self._send(200, json.dumps(tapes(), ensure_ascii=False))
        if p.startswith('/api/peaks/'):
            wd = unquote(p[11:])
            if not WD_RE.match(wd):
                return self._send(400, '{"error":"bad workdir"}')
            t = tapes().get(wd)
            if not t:
                return self._send(404, '{"error":"unknown workdir"}')
            try:
                f = peaks_for(wd, t['tape'])
            except Exception as e:
                return self._send(500, json.dumps({'error': str(e)}))
            body = open(f, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('X-Peaks-Per-Second', str(PPS))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p in ('/book', '/book.html'):
            f = os.path.join(HERE, 'book.html')
            return self._send(200, open(f, 'rb').read(),
                              'text/html; charset=utf-8')
        if p == '/api/book/units':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                pno = int((q.get('page') or ['x'])[0])
            except ValueError:
                return self._send(400, '{"error":"bad page"}')
            try:
                return self._send(200, json.dumps(book_units(pno)))
            except Exception as e:
                return self._send(500, json.dumps({'error': str(e)[:120]}))
        if p == '/api/book':
            return self._send(200, json.dumps(book(), ensure_ascii=False))
        if p == '/api/book/hymn':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            wd = (q.get('wd') or [''])[0]
            name = (q.get('name') or [''])[0]
            if not WD_RE.match(wd):
                return self._send(400, '{"error":"bad workdir"}')
            d = book_hymn(wd, name)
            if d is None:
                return self._send(404, '{"error":"unknown hymn"}')
            return self._send(200, json.dumps(d, ensure_ascii=False))
        if p in ('/score', '/score.html'):
            f = os.path.join(HERE, 'score.html')
            return self._send(200, open(f, 'rb').read(),
                              'text/html; charset=utf-8')
        if p.startswith('/api/score/'):
            wd = unquote(p[11:])
            if not WD_RE.match(wd):
                return self._send(400, '{"error":"bad workdir"}')
            d = score_pages(wd)
            if d is None:
                return self._send(404, '{"error":"unknown workdir"}')
            return self._send(200, json.dumps(d, ensure_ascii=False))
        if p.startswith('/page/'):
            m = re.match(r'^(\d{1,4})\.jpg$', p[6:])
            if not m:
                return self._send(400, '{"error":"bad page"}')
            f = page_thumb(int(m.group(1)))
            if not f:
                return self._send(404, '{"error":"no render"}')
            body = open(f, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p.startswith('/tape/'):
            return self.serve_tape(unquote(p[6:]))
        self._send(404, '{"error":"not found"}')

    def serve_tape(self, wd):
        if not WD_RE.match(wd):
            return self._send(400, '{"error":"bad workdir"}')
        t = tapes().get(wd)
        if not t:
            return self._send(404, '{"error":"unknown workdir"}')
        path = t['tape']
        size = os.path.getsize(path)
        ctype = MIME.get(os.path.splitext(path)[1].lower(),
                         'application/octet-stream')
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng.strip())
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    start = min(int(a), size - 1)
                    if b:
                        end = min(int(b), size - 1)
                else:                       # suffix range: last N bytes
                    start = max(size - int(b or 0), 0)
                code = 206
        if start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        n = end - start + 1
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(n))
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with open(path, 'rb') as fh:
            fh.seek(start)
            left = n
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # Normal: the browser seeked away or aborted the probe.
                    # But we have now written fewer bytes than Content-Length
                    # promised, so this keep-alive connection is desynchronised
                    # and the NEXT request on it would be parsed as body. Safari
                    # aborts the initial no-Range probe immediately, so leaving
                    # it open is what made playback fail on iOS.
                    self.close_connection = True
                    return
                left -= len(chunk)

    def patch_span(self):
        """Update one field of one audio span, in place.

        The score picker needs to set the apichima mark, which lives on the
        AUDIO span, but it must not rewrite the whole cuts file from its own
        copy -- that would let a stale page silently drop spans. So it patches
        a single named span and leaves every other byte alone.
        """
        try:
            n = int(self.headers.get('Content-Length', 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError('bad length')
            b = json.loads(self.rfile.read(n))
            wd, hymn = b.get('workdir', ''), str(b.get('hymn', ''))
            if not WD_RE.match(wd):
                raise ValueError('bad workdir')
            f = f'{TEXTS}/cuts_{wd}.json'
            if not os.path.exists(f):
                raise ValueError('this tape has no audio cuts yet')
            doc = json.load(open(f))
            row = next((c for c in doc['cuts'] if c['hymn'] == hymn), None)
            if row is None:
                raise ValueError(f'no span named {hymn!r}')
            if 't_in' in b:
                ti = b['t_in']
                if ti is not None:
                    ti = float(ti)
                    if not (row['t0'] - 0.001 <= ti <= row['t1'] + 0.001):
                        raise ValueError(
                            f"apichima end {ti:.2f} is outside the span "
                            f"{row['t0']:.2f}-{row['t1']:.2f}")
                    ti = round(ti, 3)
                row['t_in'] = ti
            if 'label' in b and b['label'] is not None:
                row['label'] = str(b['label'])[:300]
            if 'skips' in b:
                row['skips'] = _clean_skips(b['skips'], row)
        except Exception as e:
            return self._send(400, json.dumps({'error': str(e)}))
        hd = f'{TEXTS}/cuts_history'
        os.makedirs(hd, exist_ok=True)
        json.dump(doc, open(
            f'{hd}/cuts_{wd}_{time.strftime("%Y%m%d-%H%M%S")}.json', 'w'),
            indent=1, ensure_ascii=False)
        doc['saved'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        json.dump(doc, open(f, 'w'), indent=1, ensure_ascii=False)
        self._send(200, json.dumps({'ok': True, 'hymn': hymn,
                                    't_in': row.get('t_in'),
                                    'skips': row.get('skips') or []}))

    def save_scorecuts(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError('bad length')
            body = json.loads(self.rfile.read(n))
            wd = body.get('workdir', '')
            if not WD_RE.match(wd):
                raise ValueError('bad workdir')
            cuts = []
            for c in body.get('cuts', []):
                if c.get('p0') is None or c.get('p1') is None:
                    continue
                a = (int(c['p0']), int(c['l0']), int(c['g0']))
                b = (int(c['p1']), int(c['l1']), int(c['g1']))
                if b < a:
                    raise ValueError(f"{c.get('hymn')}: end precedes start")
                cuts.append({'hymn': str(c['hymn']),
                             'p0': a[0], 'l0': a[1], 'g0': a[2],
                             'p1': b[0], 'l1': b[1], 'g1': b[2],
                             'label': (str(c['label'])[:300]
                                       if c.get('label') else None)})
        except Exception as e:
            return self._send(400, json.dumps({'error': str(e)}))
        out = f'{TEXTS}/scorecuts_{wd}.json'
        payload = {'workdir': wd, 'saved': time.strftime('%Y-%m-%dT%H:%M:%S'),
                   'cuts': cuts}
        payload['confirm_shrink'] = bool(body.get('confirm_shrink'))
        err = _save_guarded(out, payload, f'{TEXTS}/cuts_history',
                            f'scorecuts_{wd}')
        if err:
            return self._send(409, json.dumps({'error': err}))
        self._send(200, json.dumps({'ok': True, 'n': len(cuts), 'path': out}))

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/book/span':
            try:
                n = int(self.headers.get('Content-Length', 0))
                if not 0 < n <= MAX_BODY:
                    raise ValueError('bad length')
                payload = json.loads(self.rfile.read(n))
            except Exception as e:
                return self._send(400, json.dumps({'error': str(e)[:120]}))
            try:
                d, err = book_span_save(payload)
            except Exception as e:
                return self._send(500, json.dumps({'error': str(e)[:120]}))
            if err:
                return self._send(400, json.dumps({'error': err}))
            return self._send(200, json.dumps(d, ensure_ascii=False))
        if path == '/api/scorecuts':
            return self.save_scorecuts()
        if path == '/api/span':
            return self.patch_span()
        if path != '/api/cuts':
            return self._send(404, '{"error":"not found"}')
        try:
            n = int(self.headers.get('Content-Length', 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError('bad length')
            body = json.loads(self.rfile.read(n))
            wd = body.get('workdir', '')
            if not WD_RE.match(wd):
                raise ValueError('bad workdir')
            cuts = []
            for c in body.get('cuts', []):
                t0, t1 = c.get('t0'), c.get('t1')
                if t0 is None or t1 is None:
                    continue
                t0, t1 = float(t0), float(t1)
                if t1 <= t0:
                    raise ValueError(f"{c.get('hymn')}: end is not after start")
                lane = c.get('lane')
                if lane is not None and lane not in (
                        'melos', 'parallagi', 'speech', 'other'):
                    raise ValueError(f'bad lane {lane!r}')
                lab = c.get('label')
                if lab is not None:
                    lab = str(lab)[:300]
                # Apichima: some sections open with Vasilikos holding a note
                # on "νε" before the hymn proper. The score has no neumes for
                # it, so an aligner handed that audio will smear the first
                # notes across it. Marked as an interior point, not a second
                # span, because it belongs to the hymn's recording.
                ti = c.get('t_in')
                if ti is not None:
                    ti = float(ti)
                    if not (t0 - 0.001 <= ti <= t1 + 0.001):
                        raise ValueError(
                            f"{c.get('hymn')}: apichima end {ti:.2f} is outside "
                            f"the span {t0:.2f}-{t1:.2f}")
                    ti = round(ti, 3)
                row = {'t0': round(t0, 3), 't1': round(t1, 3)}
                cuts.append({'hymn': str(c['hymn']),
                             't0': row['t0'], 't1': row['t1'],
                             't_in': ti,
                             'skips': _clean_skips(c.get('skips'), row),
                             'label': lab or None, 'lane': lane})
        except Exception as e:
            return self._send(400, json.dumps({'error': str(e)}))
        out = f'{TEXTS}/cuts_{wd}.json'
        payload = {'workdir': wd, 'saved': time.strftime('%Y-%m-%dT%H:%M:%S'),
                   'cuts': cuts}
        payload['confirm_shrink'] = bool(body.get('confirm_shrink'))
        err = _save_guarded(out, payload, f'{TEXTS}/cuts_history', f'cuts_{wd}')
        if err:
            return self._send(409, json.dumps({'error': err}))
        self._send(200, json.dumps({'ok': True, 'n': len(cuts), 'path': out}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8790)
    ap.add_argument('--bind', default='0.0.0.0')
    a = ap.parse_args()
    t = tapes()
    print(f'cutter on http://{a.bind}:{a.port}/  ({len(t)} tapes)')
    for wd, v in t.items():
        done = sum(1 for h in v['hymns'] if h['t0'] is not None)
        print(f'  {wd:16s} {len(v["hymns"]):3d} hymns, {done:3d} already cut')
    ThreadingHTTPServer((a.bind, a.port), H).serve_forever()


if __name__ == '__main__':
    main()
