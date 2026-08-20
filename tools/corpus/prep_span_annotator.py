#!/usr/bin/env python3
"""prep_span_annotator.py — build annotator pieces from the chanter's CUT SPANS
instead of hymns.json rows.

The chanter: "but the spans are entire pieces though!" — a span IS a piece, so
each row of texts/cuts_<wd>.json becomes a data/<piece-id>/ directory the main
annotator can open, named from the score's lyric layer (span_names_<wd>.json,
47/47 correct; identification from audio does not work and is not attempted).

Everything about the score strip is shared with prep_hymn_annotator: same
renderer, same ZOOM/LINE_BAND geometry, same notes[] shape, so the annotator
needs no per-kind branch. What differs:

  * audio is CUT from the tape here, not symlinked — no per-span wav exists.
    'skips' (Vasilikos talking mid-span) are excluded, and t_in (where the
    apichima, the held νε, ends) is kept as meta.t_in_rel rather than dropped.
  * the score range belongs to the SPAN, not the hymn: units come from
    score_degrees.units_for(p0,l0,g0,p1,l1,g1). The doxology pair is the
    standing proof these can differ between the two halves of one pair.
  * there is no aligner output for a span, so slot times are seeded by beat
    weight (hymn_align.beats_seq) across the sung part of the cut. Recorded in
    meta.seed_method and on every MCR row; nothing here is a measurement.
  * meta.parallagi_anchor is score_degrees.leading_anchor(p0, g0) — load_units
    hangs a martyria on the unit BEFORE it, which is right at a cadence and
    wrong at an opening, where the martyria naming the first note falls outside
    the range.

Usage:
  prep_span_annotator.py --workdir grave-orthros --span t01_#4
  prep_span_annotator.py --workdir grave-orthros --all
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import GLYPHS, LADDERS, beats_seq
from score_degrees import leading_anchor, units_for
from prep_hymn_annotator import (BAND_UP, BAND_DN, DUR_NAME, LINE_BAND, ZOOM,
                                 attach_words, build_strip, deg_label, deg_name,
                                 find_pdf, load_gold_seed, update_manifest)

CORPUS = '/mnt/data/chant-corpus'
TEXTS = f'{CORPUS}/texts'
CANON = f'{CORPUS}/scores/legend_canon.json'   # the chanter's atlas; never legend_merged
SR = 16000                                     # the annotator decodes in-browser
GENUS = 'diatonic'                             # grave/1st/4th; hymns.json agrees, 25/25


def lines_for_units(units):
    """ordered [(page, line), ...] the units actually occupy.

    hymn_lines() enumerates every line of a (p0,l0)-(p1,l1) box, which a span
    cannot use: a span is delimited by unit index, and adjacent spans share the
    line they meet on.
    """
    return sorted({tuple(u['pl']) for u in units})


def lyrics_for_units(units):
    """lyric words overlapping the units' extent (attach_words' input).

    Same clipping rule as load_units_h: keep whole lines in the middle, clip
    the first and last line to the units' own x range, since a shared line
    carries the neighbouring span's words too.
    """
    if not units:
        return []
    pl0, kx0 = tuple(units[0]['pl']), units[0]['x0']
    pl1, kx1 = tuple(units[-1]['pl']), units[-1]['x1']
    out = []
    for p in range(pl0[0], pl1[0] + 1):
        f = os.path.join(GLYPHS, f'page{p:03d}.json')
        if not os.path.exists(f):
            continue
        for w in json.load(open(f)).get('lyrics', []):
            pl = (w['page'], w.get('line', 0))
            if pl < pl0 or pl > pl1:
                continue
            if pl == pl0 and w['x1'] < kx0 - 2:
                continue
            if pl == pl1 and w['x0'] > kx1 + 2:
                continue
            out.append(w)
    return out


def keep_segments(t0, t1, skips):
    """[t0,t1] minus the skip intervals, as (start, end) pairs."""
    segs, cur = [], t0
    for s in sorted(skips or [], key=lambda s: s[0]):
        a, b = float(s[0]), float(s[1])
        if b <= cur or a >= t1:
            continue
        if a > cur:
            segs.append((cur, min(a, t1)))
        cur = max(cur, b)
    if cur < t1:
        segs.append((cur, t1))
    return segs


def cut_audio(tape, segs, out_wav):
    """Decode each kept segment to 16k mono s16 and concatenate them."""
    pcm = bytearray()
    for a, b in segs:
        p = subprocess.run(
            ['ffmpeg', '-v', 'error', '-ss', f'{a:.3f}', '-to', f'{b:.3f}',
             '-i', tape, '-f', 's16le', '-ac', '1', '-ar', str(SR), '-'],
            stdout=subprocess.PIPE, check=True)
        pcm += p.stdout
    with wave.open(out_wav, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(pcm))
    return len(pcm) / 2 / SR


def rel_time(t, t0, skips):
    """A tape time expressed inside the cut, with earlier skips removed."""
    if t is None:
        return None
    r = t - t0
    for s in skips or []:
        a, b = float(s[0]), float(s[1])
        # a t inside a skip lands at that skip's start, which is where the cut
        # jumps over it
        r -= max(0.0, min(b, t) - max(a, t0))
    return round(max(0.0, r), 3)


def unit_degrees(units, keys, start):
    """Per-unit absolute degree, index-aligned with units (rests are None).

    Same rules as score_degrees.degree_stream — a martyria's note TAKES the
    stated degree, the opening anchor is taken not moved from — but keeping one
    entry per unit, because the annotator overlays by index.
    """
    deg, opening, out = start, start is not None, []
    for u in units:
        if u.get('rest'):
            out.append(None)
            continue
        if u.get('mart_deg') is not None:
            deg = u['mart_deg']
        elif opening:
            pass
        elif deg is not None:
            iv = keys.get(u.get('key'), keys.get(f"{u.get('base')}|"))
            deg = deg + iv if iv is not None else None
        opening = False
        out.append(deg)
    return out


def beat_times(beats, t_start, t_end):
    """Slot onsets spread over [t_start, t_end) in proportion to beats.

    A seed, not a measurement: no aligner has run on a span.
    """
    total = sum(beats) or 1.0
    span = max(0.1, t_end - t_start)
    t, acc = [], 0.0
    for b in beats:
        t.append(round(t_start + span * acc / total, 3))
        acc += b
    return t


def prep_span(wd, span, cuts, score, names, pair_of, tape, pdf,
              ann_data_dir, cache_dir):
    """Prep one span; returns the data/index.json record."""
    nm, cut, sc = names[span], cuts[span], score[span]
    piece = nm['piece_id']
    lane = nm.get('lane') if nm.get('lane') != 'unset' else None
    rec = {'id': piece, 'kind': 'span', 'workdir': wd, 'span': span,
           'lane': lane, 'ordinal': nm.get('ordinal'),
           'pair_id': pair_of.get(span), 'incipit': nm.get('incipit'),
           'prepped_at': time.strftime('%Y-%m-%d %H:%M')}

    units = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
    if not units:
        rec['status'] = 'skipped: no units in score range'
        return rec
    lyrics = lyrics_for_units(units)
    out = os.path.join(ann_data_dir, piece)
    os.makedirs(out, exist_ok=True)

    # ---- audio: cut the tape, honouring skips ----
    t0, t1 = float(cut['t0']), float(cut['t1'])
    skips = cut.get('skips') or []
    duration = cut_audio(tape, keep_segments(t0, t1, skips),
                         os.path.join(out, 'audio.wav'))
    t_in_rel = rel_time(cut.get('t_in'), t0, skips)

    # ---- strip + note geometry (identical to prep_hymn_annotator) ----
    lines = lines_for_units(units)
    line_ix = {pl: i for i, pl in enumerate(lines)}
    strip_w, strip_h, centers, tops = build_strip(
        pdf, lines, cache_dir, os.path.join(out, 'strip.png'))
    notes = []
    for u in units:
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

    # ---- machine interpretation ----
    keys = json.load(open(CANON))['keys']
    anchor = leading_anchor(sc['p0'], sc['g0'])
    expected = unit_degrees(units, keys, anchor)
    beats = beats_seq(units)
    # the apichima is sung before the first notated unit, so the notes start at
    # t_in where the chanter marked one
    times = beat_times(beats, t_in_rel or 0.0, duration)
    word, wstart = attach_words(units, lyrics)
    seed_method = ('beat-weighted seed over [%.2f, %.2f]s — no aligner output '
                   'exists for a span' % (t_in_rel or 0.0, duration))
    mcr = []
    for j, u in enumerate(units):
        interval = keys.get(u['key'], keys.get(f"{u['base']}|"))
        mcr.append({
            'gi': j, 'cp': u['key'], 'name': u['key'], 'line': notes[j]['line'],
            'sub_notes': 1, 'beats': [beats[j]],
            'gorgon': bool(u['gorgon']),
            'duration_mark': '+'.join(
                (['klasma'] if u['klasma'] else [])
                + ([DUR_NAME.get(u.get('dots', 0), f"{u['dots']} dots")]
                   if u.get('dots') else [])) or 'none',
            'quality_marks': [], 'other_marks':
                ([] if interval is None else
                 [f'interval {interval:+d}' if isinstance(interval, int)
                  else f'interval {interval:+.1f}'])
                + (['martyria: %s' % deg_label(u['mart_deg'])]
                   if u.get('mart_deg') is not None else [])
                + (['tempo: %s' % u['tempo']] if u.get('tempo') else [])
                + ['SEEDED TIME (' + seed_method + ')'],
            'expected_degrees': [expected[j]] if expected[j] is not None else None,
            'ison_at_start': None,
            'slot_ids': [j], 'word': word[j], 'word_start': bool(wstart[j]),
        })

    # ---- degree grid, from the score-implied degrees (no observed pitch) ----
    pos = LADDERS[GENUS]
    seen = [d for d in expected if d is not None] or [0, 7]
    step_deg = list(range(int(min(seen)) - 2, int(max(seen)) + 3))
    step_pos = [round(pos(d), 1) for d in step_deg]

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
            'step_pos': step_pos, 'step_deg': step_deg,
            'step_name': [deg_name(d) for d in step_deg],
            'mor_min': min(step_pos) - 10, 'mor_max': max(step_pos) + 10,
            'parallagi_anchor': anchor,
            't_in_rel': t_in_rel,
            'seed_method': seed_method,
            'source': {
                'kind': 'span', 'workdir': wd, 'span': span, 'lane': lane,
                'ordinal': nm.get('ordinal'), 'incipit': nm.get('incipit'),
                'pair_id': pair_of.get(span),
                'score_range': {k: sc[k] for k in
                                ('p0', 'l0', 'g0', 'p1', 'l1', 'g1')},
                'tape': tape, 't0': t0, 't1': t1,
                't_in': cut.get('t_in'), 'skips': skips,
            },
        },
        'notes': notes,
        'anchors': [{'gi': j, 'text': word[j]} for j in gis if wstart[j]],
        'slots': {'t': times, 'gi': gis, 'sub': [0] * len(units), 'w': beats,
                  'label': [word[j] if wstart[j] else '' for j in gis]},
        'words': [], 'pitch': None, 'ison': [], 'barlines': [], 'analytical': [],
    }
    seed = load_gold_seed(piece, len(units))
    if seed:
        data['seed'] = seed
    with open(os.path.join(out, 'annotator_data.json'), 'w') as f:
        json.dump(data, f)
    with open(os.path.join(out, 'mcr_interpretation.json'), 'w') as f:
        json.dump(mcr, f, indent=1)

    rec.update({'status': 'ready', 'data_rev': data_rev, 'n_units': len(units),
                'duration': round(duration, 1), 'n_lines': len(lines),
                'parallagi_anchor': anchor})
    return rec


def pair_map(names):
    """span -> the other half's piece_id.

    Every melos is immediately preceded by its own parallagi on a continuous
    tape (23/23 here), and the two halves share an incipit, so the parallagi id
    is the melos id with '-parallagi' appended. Both checks must hold: adjacency
    alone would pair across a hymn boundary.
    """
    def base(p):
        return p[:-len('-parallagi')] if p.endswith('-parallagi') else p
    order = sorted(names.values(), key=lambda n: n['ordinal'])
    out = {}
    for i, n in enumerate(order):
        if n.get('lane') != 'melos' or i == 0:
            continue
        prev = order[i - 1]
        if prev.get('lane') == 'parallagi' and base(prev['piece_id']) == base(n['piece_id']):
            out[n['span']] = prev['piece_id']
            out[prev['span']] = n['piece_id']
    return out


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_ann = os.path.normpath(os.path.join(here, '..', 'chant-reel', 'annotator'))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', default='grave-orthros',
                    help='workdir NAME, i.e. the texts/*_<wd>.json suffix')
    ap.add_argument('--span', help='one span id, e.g. t01_#4')
    ap.add_argument('--all', action='store_true', help='every span in the workdir')
    ap.add_argument('--annotator-dir', default=default_ann)
    ap.add_argument('--render-cache', default=f'{CORPUS}/scores/page_renders')
    args = ap.parse_args()

    wd = args.workdir
    cuts = {c['hymn']: c for c in
            json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts']}
    score = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    names = {n['span']: n for n in
             json.load(open(f'{TEXTS}/span_names_{wd}.json'))['spans']}
    tape = json.load(open(f'{TEXTS}/recut_{wd}.json'))[0]['tape']

    spans = sorted(set(cuts) & set(score) & set(names),
                   key=lambda s: names[s]['ordinal'])
    if args.span:
        if args.span not in spans:
            sys.exit(f'span {args.span!r} has no cut/scorecut/name triple in {wd}')
        spans = [args.span]
    elif not args.all:
        sys.exit('refusing to prep a whole workdir without --all (or give --span)')

    pdf = find_pdf()
    ann_data = os.path.join(args.annotator_dir, 'data')
    os.makedirs(ann_data, exist_ok=True)
    pair_of = pair_map(names)

    recs, n_ok = [], 0
    for s in spans:
        try:
            r = prep_span(wd, s, cuts, score, names, pair_of, tape, pdf,
                          ann_data, args.render_cache)
        except Exception as e:
            r = {'id': names[s]['piece_id'], 'kind': 'span', 'workdir': wd,
                 'span': s, 'status': f'ERROR: {e}',
                 'prepped_at': time.strftime('%Y-%m-%d %H:%M')}
        recs.append(r)
        n_ok += r['status'] == 'ready'
        print(f"{r['span']} {r['id']}: {r['status']}"
              + (f" — {r['n_units']} units, {r['n_lines']} lines, "
                 f"{r['duration']}s, anchor {r['parallagi_anchor']}, "
                 f"pair {r.get('pair_id')}" if r['status'] == 'ready' else ''),
              flush=True)
    path = update_manifest(ann_data, recs)
    print(f"\n{n_ok}/{len(recs)} span pieces ready; manifest: {path}")


if __name__ == '__main__':
    main()
