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
import numpy as np
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import GLYPHS, LADDERS, beats_seq
from score_degrees import leading_anchor, units_for
from prep_hymn_annotator import (PITCH_DT, CPM, BAND_UP, BAND_DN, DUR_NAME, LINE_BAND, ZOOM,
                                 attach_words, build_strip, deg_label, deg_name,
                                 find_pdf, load_gold_seed, update_manifest, hymn_x_clip)

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


def pitch_track(wav):
    """cents rel 55 Hz at 10 ms, NaN where unvoiced — the same FFT
    autocorrelation segment_tracks.py uses, so a span's curve is comparable to a
    hymn's."""
    import wave as _w
    with _w.open(wav) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()),
                          dtype=np.int16).astype(float) / 32768.
    hop, win = int(sr * 0.01), 2048
    lo, hi = int(sr / 370), int(sr / 90)
    n = max(0, (len(x) - win) // hop)
    out = np.full(n, np.nan)
    for i in range(n):
        fr = x[i * hop:i * hop + win]
        if np.sqrt((fr ** 2).mean()) < 0.008:
            continue
        fr = fr - fr.mean()
        sp = np.fft.rfft(fr, 4096)
        ac = np.fft.irfft(sp * np.conj(sp))[:win]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        pk = int(np.argmax(ac[lo:hi])) + lo
        if not (1 <= pk < len(ac) - 1 and ac[pk] > 0.45):
            continue
        a, b, c = ac[pk - 1], ac[pk], ac[pk + 1]
        out[i] = 1200 * np.log2(
            max(sr / (pk + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)), 1) / 55.)
    return out


def sung_onset(wav, t_in):
    """Where the SUNG material starts, past a held apichima.

    t_in is the chanter's mark for the end of the apichima and the seed used to
    start there, which put s04's first note 2.06 s early. The audio is continuous
    and at full level across the gap, so nothing energy-based can see it. What
    separates them is that an APICHIMA IS HELD and the chant MOVES: on s04 the
    intonation sits flat around 1250 cents to 15.3, then the parallagi enters at
    2213; on s34 it is held at 2010 for eight seconds and the parallagi enters at
    2500. Chanter: "there are probably only two low grave mode apichimas to zo
    like that", and the two are exactly s04 and s34.

    Octave errors are folded first. The tracker halves s34's held note partway
    through — 2010 cents becomes 840 — and an earlier version of this took that
    at face value, read the region as 'low', and then declined the span because
    the median over the whole stretch came out at the sung register.

    Returns None when there is no held opening to leave, so a span without an
    apichima keeps its t_in.
    """
    import wave as _w
    with _w.open(wav) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()),
                          dtype=np.int16).astype(float) / 32768.
    hop, win = int(sr * 0.01), 2048
    lo, hi = int(sr / 370), int(sr / 90)
    n = min(len(x) // hop, 6000)
    ps = np.full(n, np.nan)
    for i in range(n):
        fr = x[i * hop:i * hop + win]
        if len(fr) < win or np.sqrt((fr ** 2).mean()) < 0.008:
            continue
        fr = fr - fr.mean()
        sp = np.fft.rfft(fr, 4096)
        ac = np.fft.irfft(sp * np.conj(sp))[:win]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        pk = int(np.argmax(ac[lo:hi])) + lo
        if not (1 <= pk < len(ac) - 1 and ac[pk] > 0.45):
            continue
        a, b, c = ac[pk - 1], ac[pk], ac[pk + 1]
        ps[i] = 1200 * np.log2(
            max(sr / (pk + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)), 1) / 55.)
    if not t_in or np.count_nonzero(~np.isnan(ps)) < 50:
        return None
    # the apichima's own pitch: the flattest second inside the marked opening
    lim = int(t_in / 0.01)
    best, held, at = None, None, None
    for a in range(50, max(51, lim - 100), 10):
        seg = ps[a:a + 100]
        seg = seg[~np.isnan(seg)]
        if len(seg) < 60:
            continue
        sd = float(np.std(seg))
        if best is None or sd < best:
            best, held, at = sd, float(np.median(seg)), a
    if held is None or best > 120:
        return None                       # nothing held: no apichima to leave
    ref = np.where(np.isnan(ps), np.nan, ps)
    ref = ref + 1200 * np.round((held - ref) / 1200.0)   # fold octave errors
    # Scan forward from the END of the held window, never from the top of the
    # clip: the opening second is the attack settling onto the intonation, and
    # scanning from zero reported that as the sung onset on all six spans.
    run = 0
    for i in range(at + 100, len(ref)):
        c = ref[i]
        if np.isnan(c):
            continue
        if abs(c - held) > 250:
            run += 1
            if run >= 25:                 # 0.25 s held away from the intonation
                return round((i - run + 1) * 0.01, 2)
        else:
            run = 0
    return None


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


def piece_id_for(wd, nm):
    """The id the chanter sees in the picker.

    span_names.py names a span by its incipit alone, which is right for identity
    but useless for finding anything: the picker sorts by id, so the 47 spans
    scattered alphabetically by Greek incipit with no way to tell a parallagi
    from its melos. Chanter, 2026-08-19: "why dont they say
    grave-orthros-s<#>-greek-title", and "make sure the 47 have Melos/paralagi
    as well pretty clear to the user that its parallagi or melos when selecting".

    So the id leads with the span's ORDINAL on the tape, which is liturgical
    order, then the lane, then the incipit — sorting the picker into the order
    he cut them, with each parallagi immediately before its melos.
    """
    lane = nm.get('lane')
    lane = lane if lane in ('melos', 'parallagi') else 'unset'
    base = nm['piece_id']
    for suf in ('-parallagi',):
        if base.endswith(suf):
            base = base[:-len(suf)]
    if base.startswith(wd + '-'):
        base = base[len(wd) + 1:]
    return f"{wd}-s{int(nm['ordinal']):02d}-{lane}-{base}"


def prep_span(wd, span, cuts, score, names, pair_of, tape, pdf,
              ann_data_dir, cache_dir):
    """Prep one span; returns the data/index.json record."""
    nm, cut, sc = names[span], cuts[span], score[span]
    piece = piece_id_for(wd, nm)
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
        pdf, lines, cache_dir, os.path.join(out, 'strip.png'), clip=hymn_x_clip(units))
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
    sung = sung_onset(os.path.join(out, 'audio.wav'), t_in_rel)
    seed_from = t_in_rel or 0.0
    # Trust the detection only as a CORRECTION to the mark, never as a
    # replacement for it. Chanter: "there are probably only two low grave mode
    # apichimas to zo like that" — and on the six spans carrying a t_in the
    # detector proposes +1.6 to +2.4 s on three of them and +4.8 to +8.3 s on
    # the other three. A shift of that size means it locked onto a held note
    # inside the singing rather than the intonation, so it is recorded and
    # ignored. The bound is the chanter's own count, not a fitted threshold.
    SUNG_MAX_SHIFT = 3.0
    corrected = (sung is not None and t_in_rel is not None
                 and 0.75 < sung - t_in_rel <= SUNG_MAX_SHIFT)
    if corrected:
        seed_from = sung
    times = beat_times(beats, seed_from, duration)
    word, wstart = attach_words(units, lyrics)
    seed_method = ('beat-weighted seed over [%.2f, %.2f]s — no aligner output '
                   'exists for a span' % (seed_from, duration))
    if corrected:
        seed_method += ('; started from the detected SUNG onset %.2fs rather '
                        'than the marked apichima end %.2fs — the apichima is '
                        'held past the mark' % (sung, t_in_rel))
    elif sung is not None and t_in_rel is not None and sung - t_in_rel > SUNG_MAX_SHIFT:
        seed_method += ('; a sung onset was detected at %.2fs but is %.1fs past '
                        'the marked apichima end, too far to trust — kept the mark'
                        % (sung, sung - t_in_rel))
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

    # ---- degree grid, and the SUNG pitch curve against it ----
    #
    # A span had pitch: None — the curve simply was not computed, because only
    # prep_hymn_annotator had a cents_track to draw from and a span is cut fresh
    # from the tape. Chanter: "i dont even see the pitch rendering." Without it
    # there is nothing to correlate a pin against, which is most of what the
    # band is for.
    #
    # A hymn converts cents to moria against summary.json's fitted Νη. A span has
    # no summary, so Νη is fitted here the only honest way available: shift the
    # curve so its voiced MEDIAN sits on the median degree the score expects.
    # One parameter, no claim beyond it, and recorded as an estimate in meta.
    pos = LADDERS[GENUS]
    seen = [d for d in expected if d is not None] or [0, 7]
    step_deg = list(range(int(min(seen)) - 2, int(max(seen)) + 3))
    step_pos = [round(pos(d), 1) for d in step_deg]

    pitch = None
    ni_cents = None
    try:
        cents = pitch_track(os.path.join(out, 'audio.wav'))
        v = cents[~np.isnan(cents)]
        if len(v) > 50:
            want = pos(int(round(float(np.median(seen)))))   # moria the score expects
            ni_cents = float(np.median(v)) - want * CPM
            mor = (cents - ni_cents) / CPM
            step = max(1, round(PITCH_DT / 0.01))
            ds = mor[::step]
            pitch = {'dt': 0.01 * step,
                     'moria': [None if not np.isfinite(x) else round(float(x), 1)
                               for x in ds]}
    except Exception as e:
        print('  pitch track failed for %s: %s' % (piece, e))

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
            'ni_cents_rel55_est': None if ni_cents is None else round(ni_cents, 1),
            'parallagi_anchor': anchor,
            't_in_rel': t_in_rel,
            'sung_onset': sung,
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
        'words': [], 'pitch': pitch, 'ison': [], 'barlines': [], 'analytical': [],
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


def pair_map(wd, names):
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
            out[n['span']] = piece_id_for(wd, prev)
            out[prev['span']] = piece_id_for(wd, n)
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
    pair_of = pair_map(wd, names)

    recs, n_ok = [], 0
    for s in spans:
        try:
            r = prep_span(wd, s, cuts, score, names, pair_of, tape, pdf,
                          ann_data, args.render_cache)
        except Exception as e:
            r = {'id': piece_id_for(wd, names[s]), 'kind': 'span', 'workdir': wd,
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
