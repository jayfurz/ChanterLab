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
BAND_UP, BAND_DN = 144, 144    # strip band split around each line center (px)
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
        return None
    pins = [p for p in json.load(open(pf)) if isinstance(p, (list, tuple))]
    keep = [p for p in pins if 0 <= p[0] < n_units]
    if len(keep) != len(pins):
        print(f'  WARNING {piece}: {len(pins) - len(keep)} gold pins fall outside '
              f'the current {n_units}-unit stream — re-index the gold')
    seed = {'pins': keep, 'source': os.path.relpath(gdir, REPO)}
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
        # -cropbox: glyph JSON coords are CropBox-relative (fitz page space)
        subprocess.run(['pdftoppm', '-png', '-cropbox', '-r', str(72 * ZOOM),
                        '-f', str(page), '-l', str(page),
                        '-singlefile', pdf, out[:-4]], check=True)
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


def build_strip(pdf, lines, cache_dir, out_png):
    """Stack one LINE_BAND-tall band per hymn line; content centered.
    Returns (strip_w, strip_h, line_centers, {(page,line): band_top_pt})."""
    from PIL import Image
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
        tops[(p, li)] = max(0, top_px) / ZOOM     # band top in pt
        centers.append(i * LINE_BAND + BAND_UP)
    strip.save(out_png)
    return strip_w, strip.height, centers, tops


def machine_times(units, aligned, beats, duration):
    """Per-unit machine onset: aligned t0 where matched, beat-weighted
    interpolation elsewhere; strictly increasing, clamped to [0, duration]."""
    t = [None] * len(units)
    for a in aligned:
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
    genus = summ['genus']
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    units, lyrics = load_units_h(h)
    if not units:
        rec['status'] = 'skipped: no units in slice'
        return rec

    out = os.path.join(ann_data_dir, piece)
    os.makedirs(out, exist_ok=True)

    # ---- strip + note geometry ----
    lines = hymn_lines(h)
    if h.get('g0') is not None or h.get('g1') is not None:
        # g0/g1-trimmed hymn: only strip the lines its units actually occupy
        occ = {tuple(u['pl']) for u in units}
        lines = [pl for pl in lines if pl in occ]
    line_ix = {pl: i for i, pl in enumerate(lines)}
    strip_w, strip_h, centers, tops = build_strip(
        pdf, lines, cache_dir, os.path.join(out, 'strip.png'))
    notes = []
    for j, u in enumerate(units):
        pl = tuple(u['pl'])
        li = line_ix[pl]
        ty = tops[pl]
        notes.append({
            'cp': u['base'], 'key': u['key'], 'line': li,
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
        interval = iv.get(u['key'], iv.get(f"{u['base']}|", 0))
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
                + ([] if j in matched_units else ['UNMATCHED (interpolated time)']),
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
