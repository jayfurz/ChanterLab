#!/usr/bin/env python3
"""slip_check.py -- the closed loop: does the audio at each onset sing the note
the score says, and where does it stop doing so?

Owner, 2026-08-23: "what would be interesting is a closed loop feedback system
to make sure things are correct. for example if we have slip we would be able
to find it and compare."

The loop closes because the check is INDEPENDENT of the alignment being
checked. An alignment (transfer, model, annotator seed) claims "note i starts
at time t_i". The score says note i is degree d_i. The pitch tracker -- which
never saw the alignment -- says what degree is actually sounding at t_i. When
the alignment is right they agree at the per-note rate measured on gold
(s03 91 %, s05 87 %, with the chanter's own onsets). When the alignment slips,
every note after the slip point is compared against the wrong score degree,
and agreement collapses to the chance rate (~1/3 for stepwise chant) FROM THE
SLIP POINT ON. A sliding window over the agreement vector therefore both
DETECTS a slip and LOCATES it.

What this cannot do: distinguish a slipped alignment from a wrong score or a
wrong genus in the same window -- any of the three breaks agreement. That is
the right behaviour for a review queue: all three deserve the chanter's ear.

Usage:
  slip_check.py --piece <annotator dir> --onsets pred.json [--window 8] [--json out]
  (score range and genus come from the piece's own meta)
"""
import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from degree_pitch import SR, degrees_cents, estimate_base, f0_track   # noqa: E402
from score_degrees import degree_stream, leading_anchor, units_for    # noqa: E402

TEXTS = '/mnt/data/chant-corpus/texts'
HOP = 160
GOLD_RATE = 0.89        # per-note agreement with CORRECT onsets (s03/s05 gold)
CHANCE = 0.35           # agreement of a desynchronised index, measured on gold


def load_onsets(f):
    raw = json.load(open(f))
    if isinstance(raw, dict) and 'onsets' in raw:
        raw = raw['onsets']
    if isinstance(raw, dict):
        return {int(k): float(v) for k, v in raw.items()}
    if isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
        return {int(k): float(v) for k, v in raw}
    return {i: float(t) for i, t in enumerate(raw)}


def heard_degrees(piece_dir, ts, genus='diatonic'):
    """Sounding degree (mod 7) at each onset, from pitch alone."""
    raw = subprocess.run(['ffmpeg', '-v', 'quiet', '-i',
                          os.path.join(piece_dir, 'audio.wav'),
                          '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
                         stdout=subprocess.PIPE).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    f0, ok = f0_track(x)
    if ok.sum() < 50:
        return [None] * len(ts)
    med = np.median(f0[ok])
    dc = degrees_cents(genus)
    off, _ = estimate_base(1200 * np.log2(f0[ok] / med), dc)
    full = np.full(len(f0), np.nan)
    full[ok] = 1200 * np.log2(f0[ok] / med)
    out = []
    for k, t0 in enumerate(ts):
        t1 = ts[k + 1] if k + 1 < len(ts) else t0 + 0.4
        seg = full[int(t0 * SR / HOP):int(t1 * SR / HOP)]
        seg = seg[~np.isnan(seg)]
        if len(seg) < 3:
            out.append(None)
            continue
        rel = (np.median(seg) - off) % 1200
        d = np.abs(rel - np.array(dc))
        out.append(int(np.argmin(np.minimum(d, 1200 - d))))
    return out


def score_degrees_for(piece_dir):
    D = json.load(open(os.path.join(piece_dir, 'annotator_data.json')))
    src = D['meta']['source']
    leg = json.load(open('/mnt/data/chant-corpus/scores/legend_canon.json'))
    if 'span' in src:                      # grave tape span piece
        sc = {c['hymn']: c for c in
              json.load(open(f'{TEXTS}/scorecuts_grave-orthros.json'))['cuts']}[src['span']]
        u = units_for(sc['p0'], sc['l0'], sc['g0'], sc['p1'], sc['l1'], sc['g1'])
        return [int(v) % 7 for v in degree_stream(u, leg, start=leading_anchor(sc['p0'], sc['g0']))], 'diatonic'
    # mode-workdir hymn piece: the row IS the range (g0/g1 annotator-relative)
    wd = src['workdir']
    rows = json.load(open(os.path.join(wd, 'hymns.json')))
    rows = rows if isinstance(rows, list) else rows['hymns']
    r = [x for x in rows if x['name'] == src['hymn']][0]
    from hymn_align import load_units_h
    u, _ = load_units_h(r)
    genus = r.get('genus') or src.get('genus') or 'diatonic'
    return [int(v) % 7 for v in degree_stream(u, leg, start=leading_anchor(r['p0'], r.get('g0') or 0))], genus


def check(piece_dir, onsets_file, window=8):
    on = load_onsets(onsets_file)
    exp, genus = score_degrees_for(piece_dir)
    gs = sorted(on)
    ts = [on[g] for g in gs]
    heard = heard_degrees(piece_dir, ts, genus=genus)
    n = min(len(exp), len(gs))
    # Base estimation has near-symmetric optima (degree_match.py: offsets for
    # the SAME span swing 560-710 cents between runs), so the heard degrees
    # can come out rotated by a constant. A rotation is global; a slip is
    # local. Score agreement under the best global rotation -- measured
    # without it, 11 correctly-aligned pieces scored ~0.01, BELOW chance,
    # which is exactly what a constant shift looks like.
    def agree_at(r):
        out = [None] * n
        for i in range(n):
            if heard[i] is not None:
                e = exp[gs[i]] if gs[i] < len(exp) else exp[i]
                out[i] = int((heard[i] + r) % 7 == e)
        return out
    best = max(range(7), key=lambda r: sum(x for x in agree_at(r) if x))
    agree = agree_at(best)
    # sliding window rate over placed notes
    flags, rates = [], []
    for i in range(n):
        w = [a for a in agree[max(0, i - window // 2):i + window // 2 + 1] if a is not None]
        r = sum(w) / len(w) if w else None
        rates.append(r)
    # a suspected slip: a maximal run of windows at or below the midpoint
    # between the gold rate and chance
    thr = (GOLD_RATE + CHANCE) / 2
    runs, cur = [], None
    for i, r in enumerate(rates):
        bad = r is not None and r < thr
        if bad and cur is None:
            cur = i
        if not bad and cur is not None:
            runs.append((cur, i - 1)); cur = None
    if cur is not None:
        runs.append((cur, n - 1))
    runs = [(a, b) for a, b in runs if b - a + 1 >= 3]
    placed = [a for a in agree if a is not None]
    overall = sum(placed) / max(len(placed), 1)
    return {'n': n, 'rotation': best, 'overall_agreement': round(overall, 3),
            'expected_when_correct': GOLD_RATE,
            'suspected_slips': [{'gi0': int(a), 'gi1': int(b),
                                 't0': round(ts[a], 1), 't1': round(ts[b], 1)}
                                for a, b in runs],
            'rates': [round(r, 2) if r is not None else None for r in rates]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--piece', required=True)
    ap.add_argument('--onsets', required=True)
    ap.add_argument('--window', type=int, default=8)
    ap.add_argument('--json')
    a = ap.parse_args()
    r = check(a.piece.rstrip('/'), a.onsets, a.window)
    nm = os.path.basename(a.piece.rstrip('/'))[13:18]
    verdict = 'CLEAN' if not r['suspected_slips'] and r['overall_agreement'] > 0.75 else \
              'SLIP?' if r['suspected_slips'] else 'LOW AGREEMENT'
    print('%-6s %3d notes  agreement %.2f (gold-onset rate %.2f)  %s %s'
          % (nm, r['n'], r['overall_agreement'], GOLD_RATE, verdict,
             ' '.join('gi %d-%d (%.0f-%.0fs)' % (s['gi0'], s['gi1'], s['t0'], s['t1'])
                      for s in r['suspected_slips'])))
    if a.json:
        json.dump(r, open(a.json, 'w'), indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
