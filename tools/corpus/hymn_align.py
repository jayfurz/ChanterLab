#!/usr/bin/env python3
"""Align a hymn's audio (parallagi and/or melos) against its BOOK score slice.

Score side: global glyph records (extract_book output, 94-cluster ids) sliced
by (page, line) hymn range -> units (x-overlap groups: base + marks; red
gorgon-family attach as time marks, other red = martyria/fthora, silent).
Legend (unit-key -> interval) is LEARNED: parallagi recordings carry absolute
degree labels (parallagi_align output), so a DTW match units<->labeled events
turns each key's interval into a supervised estimate. Melos then aligns
against the same units under the learned legend.

Usage:
  hymn_align.py legend  <workdir> --hymns hymns.json     (joint legend EM)
  hymn_align.py melos   <workdir> --hymn NAME            (align one melos)
hymns.json rows: {name, p0, l0, p1, l1, parallagi_dir, melos_audio, melos_whisper}
  optional g0/g1: inclusive unit-index trim of the sliced stream (annotator
  glyph #s) for hymns that start/end mid-line between adjacent hymns.
Legend persists at <workdir>/legend_global.json and is updated by 'legend'.
"""
import json, os, sys
from collections import Counter, defaultdict
import numpy as np

GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
# ---- global cluster roles (94-cluster atlas read; intervals are LEARNED) ----
# RED_TIME was {11, 23, 22, 9} "gorgon + klasma-family hooks". Checked against
# the chanter's cluster export (datasets/exports/clusters/classifications.json,
# 2026-08-18) and the corpus: 9 and 22 are ALWAYS BLACK (110 / 2155 instances),
# so they never reached this red-only test at all, and 23 is ALWAYS RED (759) —
# meaning the sole producer of a "red klasma" was cluster 23, which the chanter
# classifies as "martyria-letter, Letter gamma for ga". Every beat it added was
# phantom. The klasma-family hook set is therefore empty; klasma is cluster 8,
# detected colour-blind below.
RED_TIME = set()
# martyria LETTER clusters -> absolute degree (chanter classifier pass
# 2026-08-18): 14=Πα 23=Γα 34=Δι 52=Κε 67=Βου. 24 REMOVED — it is the nana
# SCALE SIGN (≈Ga context), not the Νη letter; anchoring it to Νη=0 was a -3
# anchor error at Ga cadences. 26=Ζω kept but UNREVIEWED by the chanter.
MARTYRIA_DEG = {34: 4, 14: 1, 26: 6, 23: 3, 52: 5, 67: 2}
SILENT_BLACK = {12, 61, 55}      # bareia, stavros, lone slash
MARK_ONLY = {36, 13, 27, 10, 16, 9}  # dots/kentima slabs: never a base alone
# cluster 9 (chanter export): "Antikenoma that has a apli right underneath.
# Orthographical but the apli still applies. Apli adds the extra beat" — a mark
# compound, never a note, and it carries exactly one apli beat. Always black
# (110 instances), so the old red-only klasma test lost every one of them.
# Cluster 36 is the OMALON, not an apli (chanter, 2026-08-18, t03 gi6): it ties
# two notes and is qualitative/orthographic only, carrying no beat. It was
# adding a spurious beat to ~261 units corpus-wide.
# The real duration dots are cluster 10, and they are COUNTED, not flagged
# (chanter, 2026-08-18): "apli is one beat, dipli is two beats, tripli is 3".
# Corpus: 980 units carry one dot, 1092 two, 7 three — 2079 units that
# contributed no duration at all until this was wired.
DOTS = {10}
APLI_COMPOUND = {9}         # antikenoma+apli: one apli beat, never a note
# Gorgon family -> order k. Table-of-Byzantine-Notation-Symbols.pdf, "Rhythmic
# Symbols": a gorgon of order k takes k/(k+1) of a beat off a window of k+1
# symbols starting one BEFORE the sign. gorgon "takes half a beat off the
# symbol and the symbol before it (eighth notes)" -> ½ ½; digorgon "two-thirds
# off the symbol, and the symbols before and after it (triplets)" -> ⅓ ⅓ ⅓;
# trigorgon "¾ off the symbol, the symbol before it, and the two after it
# (sixteenth notes)" -> ¼ ¼ ¼ ¼. The PDF's second illustration of each is the
# klasma case (2 - ½ = 1½, 2 - ⅔ = 1⅓, 2 - ¾ = 1¼), which is exactly the
# chanter's t03 gi12 reading: "it steals a 1/2 beat from the previous note with
# the klasma which makes the previous note 1-1/2 beats".
GORGON_ORDER = {11: 1, 25: 2, 30: 3}
# Klasma "adds a beat to the symbol" (PDF). The atlas calls cluster 8 the BLACK
# klasma, and klasma detection used to look at RED glyphs only — so 2100 units
# carrying an 8ab/8be klasma added nothing, against 25 caught by the red path.
# Detection is now colour-blind.
KLASMA = {8}
# argon "adds a beat to the symbol and removes half a beat from the two
# symbols before it"
ARGON = {58, 90}
MIN_BEAT = 0.125            # floor: stacked deductions must not go negative
W_MV, MV_CAP = 1.0, 2.6
SKIP_U, SKIP_E = 1.2, 0.25
MAX_DU, MAX_DE = 4, 10
W_DUR, DUR_CAP = 0.5, 1.2
ITERS = 3

def beats_written(u):
    """Duration a unit carries on its own, BEFORE gorgon-family deductions.

    Chanter, 2026-08-18: the duration dots are counted, not flagged — "apli is
    one beat, dipli is two beats, tripli is 3". The PDF agrees: klasma "adds a
    beat", aplē "same as klasma", diplē "adds two beats", triplē "adds three".
    A rest is worth its dots.
    """
    if u.get('rest'):
        return float(u.get('dots', 0)) or 1.0
    return 1.0 + (1.0 if u['klasma'] else 0.0) + u.get('dots', 0)


def beats_seq(units):
    """Per-unit beats for a whole unit stream — the single source of truth.

    Must be a sequence pass, not a per-unit function: the gorgon family and the
    argon reach into their NEIGHBOURS, so a note's duration is not a property of
    that note alone. This is why callers take a list rather than mapping over
    units.
    """
    b = [beats_written(u) for u in units]
    n = len(b)
    for j, u in enumerate(units):
        k = u.get('timing', 0)
        if k:                       # gorgon k=1, digorgon k=2, trigorgon k=3
            ded = k / (k + 1.0)     # ½, ⅔, ¾
            for i in range(j - 1, j + k):        # k+1 symbols, starting one before
                if 0 <= i < n:
                    b[i] -= ded
        if u.get('argon'):
            b[j] += 1.0
            for i in (j - 1, j - 2):
                if i >= 0:
                    b[i] -= 0.5
    return [max(x, MIN_BEAT) for x in b]


def beats_of(u):
    """Deprecated single-unit view — no neighbour effects. Use beats_seq()."""
    return max(beats_written(u) - (0.5 if u.get('timing') else 0.0), MIN_BEAT)


def _xov(a, b):
    """x-overlap wide enough to call two glyphs part of one figure"""
    return (min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
            > 0.35 * min(a['x1'] - a['x0'], b['x1'] - b['x0']))


def _note_subgroups(cands):
    """Split base candidates that a wide SPAN mark merged transitively.

    Candidates that DIRECTLY x-overlap are one compound note (ison printed over
    a petasti, petasti+oligon). Candidates that never touch each other are
    separate notes which a connector merely ties together, and used to be fused
    into a single unit. Chanter, t03 gi6: "it should be split into an oligon and
    ison (two neumes)… the omalon is qualitative/orthographic", and "another
    glyph that is sometimes two wide is the eteron".

    The span marks this rescues, by how often they bridge two notes:
      31  red,   w~39  bridges 324/325 occurrences  — ETERON (chanter-confirmed)
      36  black, w~35  bridges 225/261              — OMALON (chanter-confirmed)
      25  red,   w~18  digorgon (thirds across 3 notes)
      74  red,   w~44  bridges 10/10                — wide eteron variant, unconfirmed
      85  red,   w~38  tie/syndesmos
      30  red,   w~25  trigorgon
    The rule is generic, so a span mark does not need to be classified for its
    notes to come apart correctly.
    """
    subs, used = [], [False] * len(cands)
    for i in range(len(cands)):
        if used[i]:
            continue
        cur = [cands[i]]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(cands)):
                if used[j]:
                    continue
                if any(_xov(x, cands[j]) for x in cur):
                    cur.append(cands[j])
                    used[j] = True
                    changed = True
        subs.append(cur)
    subs.sort(key=lambda s: min(x['x0'] for x in s))
    return subs


def load_units(p0, l0, p1, l1):
    """units for the hymn slice [(p0,l0) .. (p1,l1))"""
    recs, lyr = [], []
    for p in range(p0, p1 + 1):
        f = os.path.join(GLYPHS, f'page{p:03d}.json')
        d = json.load(open(f))
        for g in d['glyphs']:
            key = (p, g['line'])
            if (p == p0 and g['line'] < l0) or (p == p1 and g['line'] >= l1) \
               or p > p1:
                continue
            recs.append(g)
        for w in d.get('lyrics', []):
            if (p == p0 and w.get('line', 0) < l0) or (p == p1 and w.get('line', 0) >= l1):
                continue
            lyr.append(w)
    units = []
    by_line = defaultdict(list)
    for g in recs:
        by_line[(g['page'], g['line'])].append(g)
    for pl in sorted(by_line):
        gl = sorted(by_line[pl], key=lambda g: g['x0'])
        used = [False] * len(gl)
        for i, g in enumerate(gl):
            if used[i]:
                continue
            grp = [g]; used[i] = True
            changed = True
            while changed:
                changed = False
                for j, h in enumerate(gl):
                    if used[j]:
                        continue
                    if any(min(x['x1'], h['x1']) - max(x['x0'], h['x0'])
                           > 0.35 * min(x['x1'] - x['x0'], h['x1'] - h['x0'])
                           for x in grp):
                        grp.append(h); used[j] = True; changed = True
            cands = [x for x in grp if not x['red']
                     and x['cluster'] not in SILENT_BLACK
                     and x['cluster'] not in MARK_ONLY]
            if not cands:
                n_dots = sum(1 for x in grp if x['cluster'] in DOTS)
                if n_dots:
                    # vareia + aplē/diplē/triplē and no note = a REST worth that
                    # many beats. Chanter, 2026-08-18: "rests should be units,
                    # they take up time … even if the chanter skips them … it is
                    # still what the music notation is saying one should do".
                    # 81 of these corpus-wide, every one exactly (10, 12), and
                    # all were being dropped for having no base candidate.
                    units.append({'pl': pl, 'x0': min(x['x0'] for x in grp),
                                  'x1': max(x['x1'] for x in grp),
                                  'y0': min(x['y0'] for x in grp),
                                  'y1': max(x['y1'] for x in grp),
                                  'key': 'rest', 'base': None, 'rest': True,
                                  'gorgon': False, 'klasma': False,
                                  'timing': 0, 'argon': False, 'dots': n_dots,
                                  'apli': True})
                    continue
                # martyria letters state the ABSOLUTE degree of the melody at
                # this cadence — recorded as an anchor on the previous unit
                degs = [MARTYRIA_DEG[x['cluster']] for x in grp
                        if x['red'] and x['cluster'] in MARTYRIA_DEG]
                if degs and units:
                    units[-1]['mart_deg'] = degs[0]
                continue                      # martyria/silent group: no slot
            # one unit per NOTE, not per x-overlap group: a span mark that ties
            # two notes must not fuse them (see _note_subgroups)
            subs = _note_subgroups(cands)
            spans = [(min(x['x0'] for x in s), max(x['x1'] for x in s)) for s in subs]
            cand_ids = {id(c) for c in cands}
            extra = [[] for _ in subs]
            for x in grp:                     # marks/reds go to the note they cover most
                if id(x) in cand_ids:
                    continue
                k = max(range(len(subs)),
                        key=lambda i: min(x['x1'], spans[i][1]) - max(x['x0'], spans[i][0]))
                extra[k].append(x)
            for s, ex in zip(subs, extra):
                mine = s + ex
                base = max(s, key=lambda x: (x['x1'] - x['x0']) * (x['y1'] - x['y0']))
                black = [x for x in mine if not x['red']
                         and x['cluster'] not in SILENT_BLACK]
                red = [x for x in mine if x['red']]
                marks = []
                for x in black:
                    if x is base:
                        continue
                    pos = ('ab' if (x['y0'] + x['y1']) / 2
                           < (base['y0'] + base['y1']) / 2 - 1 else 'be')
                    marks.append(f"{x['cluster']}{pos}")
                timing = max((GORGON_ORDER[x['cluster']] for x in mine
                              if x['cluster'] in GORGON_ORDER), default=0)
                gorgon = timing >= 1
                klasma = any(x['cluster'] in KLASMA for x in mine)
                units.append({'pl': pl, 'x0': min(x['x0'] for x in mine),
                              'x1': max(x['x1'] for x in mine),
                              'y0': min(x['y0'] for x in mine),
                              'y1': max(x['y1'] for x in mine),
                              'key': f"{base['cluster']}|{'+'.join(sorted(marks))}",
                              'base': base['cluster'],
                              'gorgon': gorgon, 'klasma': klasma,
                              'timing': timing, 'rest': False,
                              'argon': any(x['cluster'] in ARGON for x in mine),
                              'dots': (sum(1 for x in black if x['cluster'] in DOTS)
                                       + sum(1 for x in black
                                             if x['cluster'] in APLI_COMPOUND)),
                              'apli': any(x['cluster'] in DOTS
                                          or x['cluster'] in APLI_COMPOUND
                                          for x in black)})
    units.sort(key=lambda u: (u['pl'], u['x0']))
    return units, lyr

def load_units_h(h):
    """units + lyrics for a hymns.json row. Optional g0/g1 (annotator glyph
    #s, inclusive) trim the unit stream when a hymn starts or ends mid-line —
    adjacent hymns share lines, so (page,line) ranges alone over-slice.
    unitdeg_*/iv_ovr_* indices are relative to THIS trimmed stream."""
    units, lyr = load_units(h['p0'], h['l0'], h['p1'], h['l1'])
    g0, g1 = h.get('g0'), h.get('g1')
    if g0 is None and g1 is None:
        return units, lyr
    lo = 0 if g0 is None else int(g0)
    hi = len(units) - 1 if g1 is None else int(g1)
    kept = units[lo:hi + 1]
    if kept:
        pl0, kx0 = kept[0]['pl'], kept[0]['x0']
        pl1, kx1 = kept[-1]['pl'], kept[-1]['x1']
        def _keep(w):
            pl = (w['page'], w.get('line', 0))
            if pl < pl0 or pl > pl1:
                return False
            if pl == pl0 and w['x1'] < kx0 - 2:
                return False
            if pl == pl1 and w['x0'] > kx1 + 2:
                return False
            return True
        lyr = [w for w in lyr if _keep(w)]
    return kept, lyr

W_ABS, ABS_CAP = 0.55, 2.0
W_MART = 1.6

def iv_of(iv, u):
    """unknown mark-combos fall back to the bare base glyph's interval
    (marks are mostly quality/time; better than a silent 0 default)"""
    k = u['key']
    if k in iv:
        return iv[k]
    return iv.get(f"{u['base']}|", 0)

def dtw(units, deg_obs, iv, start=None, times=None, spb=None, drone_c=None,
        exp_abs=None, beats=None):
    """monotonic DTW: units claim labeled events; movement cost on degree
    deltas under the current legend + ABSOLUTE degree anchor (score-side
    cumulative degree from a fitted hymn start-degree — prevents the path
    sliding off-by-one through repeated-glyph stretches).
    start=None searches the best start degree; returns (path, start, cost).

    REST units never reach the DP: they are notated silence, so they can never
    claim a sung event, but the time they occupy still has to separate the notes
    on either side. They are filtered out here and their beats folded into the
    PRECEDING note. Chanter, 2026-08-18: "on a rest, the chanter STOPS singing …
    it should be folded into the duration of the PREVIOUS note, otherwise the
    next note will go on for too long instead of being delayed the duration of
    the rest as it should." Since the duration prior measures onset-to-onset,
    charging the rest to the note before it is what delays the next onset;
    charging it forward would have stretched the wrong note.
    Returned path indices are always against the ORIGINAL unit stream."""
    if any(u.get('rest') for u in units):
        keep = [j for j, u in enumerate(units) if not u.get('rest')]
        if not keep:
            return None
        allb = beats if beats is not None else beats_seq(units)
        cb = np.concatenate([[0.0], np.cumsum(allb)])
        # each kept note carries its own beats plus any rest that FOLLOWS it,
        # up to the next kept note
        kb = []
        for m, j in enumerate(keep):
            nxt = keep[m + 1] if m + 1 < len(keep) else len(allb)
            kb.append(float(cb[nxt] - cb[j]))
        got = dtw([units[j] for j in keep], deg_obs, iv, start=start, times=times,
                  spb=spb, drone_c=drone_c,
                  exp_abs=([exp_abs[j] for j in keep]
                           if exp_abs is not None else None),
                  beats=kb)
        if got is None:
            return None
        path, st, cost = got
        return [(keep[j], k) for j, k in path], st, cost
    N, K = len(units), len(deg_obs)
    exp = np.zeros(N + 1)
    for j, u in enumerate(units):
        exp[j + 1] = exp[j] + iv_of(iv, u)
    if exp_abs is not None:
        # parallagi-anchored ABSOLUTE degree per unit overrides the
        # legend-cumulative expectation (kills tail-key error accumulation)
        exp[1:] = np.asarray(exp_abs, dtype=float)
        exp[0] = exp[1]
        start = 0
    if start is None:
        # start and the caller's Ni/degree hypothesis are coupled through the
        # absolute term — a narrow search around the observed opening suffices
        est = int(round(float(np.median(deg_obs[:6]))) - round(exp[1]))
        best = None
        for s in range(est - 2, est + 3):
            got = dtw(units, deg_obs, iv, start=s, times=times, spb=spb,
                      drone_c=drone_c, exp_abs=exp_abs, beats=beats)
            if got and (best is None or got[2] < best[2]):
                best = got
        return best
    BIG = 1e18
    deg = np.asarray(deg_obs, dtype=float)
    abs_c = W_ABS * np.minimum(np.abs(deg[None, :] - (start + exp[1:])[:, None]),
                               ABS_CAP)                       # [j, k]
    mart_c = np.zeros((N, K))
    for j, u in enumerate(units):
        md = u.get('mart_deg')
        if md is not None:
            mart_c[j] = W_MART * np.min(np.abs(
                deg[None, :] - (md + 7 * np.arange(-1, 2))[:, None]), axis=0)
    dd = {o: deg[o:] - deg[:-o] for o in range(1, MAX_DE + 1)}   # deg[k]-deg[k-o]
    fee = np.full(K, SKIP_E)
    if drone_c is not None:
        fee = np.where(np.abs(np.asarray(drone_c[1]) - drone_c[0]) <= 45.0,
                       0.05, SKIP_E)          # ison-singer captures skip cheap
    FEE = np.concatenate([[0.0], np.cumsum(fee)])
    use_dur = times is not None and spb is not None
    if use_dur:
        t = np.asarray(times, dtype=float)
        dt = {o: np.maximum(t[o:] - t[:-o], 0.02) for o in range(1, MAX_DE + 1)}
        bs = np.array(beats if beats is not None else beats_seq(units))
        CB = np.concatenate([[0.0], np.cumsum(bs)])
    D = np.full((N, K), BIG)
    Pj = np.full((N, K), -1, dtype=np.int32)
    Pk = np.full((N, K), -1, dtype=np.int32)
    k0 = min(8, K)
    D[0, :k0] = 0.3 * np.arange(k0) + abs_c[0, :k0] + mart_c[0, :k0]
    for j in range(1, N):
        best = np.full(K, BIG)
        bj = np.full(K, -1, dtype=np.int32)
        bk = np.full(K, -1, dtype=np.int32)
        for j2 in range(max(0, j - MAX_DU), j):
            ce = exp[j + 1] - exp[j2 + 1]
            base_pen = SKIP_U * (j - j2 - 1)
            row = D[j2]
            if use_dur:
                # elapsed beats from the ONSET of j2 to the ONSET of j, i.e. the
                # durations of units j2 .. j-1. This used to read
                # CB[j+1] - CB[j2+1] (units j2+1 .. j) — off by one unit, which
                # was invisible while every beat was 1.0 or 2.0 and became real
                # the moment the duration model gave units 0.125 .. 4.0 beats.
                B = max(CB[j] - CB[j2], 0.25)
            for o in range(1, MAX_DE + 1):
                if o >= K:
                    break
                skip_fees = FEE[o:K] - FEE[1:K - o + 1] if o > 1 else 0.0
                cand = (row[:-o] + W_MV * np.minimum(np.abs(dd[o] - ce), MV_CAP)
                        + base_pen + skip_fees)
                if use_dur:
                    cand = cand + W_DUR * np.minimum(
                        np.abs(np.log(dt[o] / (B * spb))), DUR_CAP)
                upd = cand < best[o:]
                if upd.any():
                    idx = np.nonzero(upd)[0] + o
                    best[idx] = cand[idx - o]
                    bj[idx] = j2
                    bk[idx] = idx - o
        D[j] = best + abs_c[j] + mart_c[j]
        Pj[j], Pk[j] = bj, bk
    endc = D[N - 1] + 0.3 * (K - 1 - np.arange(K))
    if float(endc.min()) >= BIG * 0.5:
        return None
    k = int(np.argmin(endc))
    cost = float(endc[k])
    path, j = [], N - 1
    while j >= 0 and k >= 0:
        path.append((j, k))
        j, k = int(Pj[j, k]), int(Pk[j, k])
    path.reverse()
    return path, start, cost

def dtw_time(units, times):
    """bootstrap matching: beat-position vs time-position (parallagi is
    note-precise, ~1:1) — no interval knowledge needed"""
    beats = np.array(beats_seq(units))
    cb = np.concatenate([[0], np.cumsum(beats)])
    pos_u = cb[:-1] / max(cb[-1], 1e-9)
    t = np.array(times)
    pos_e = (t - t[0]) / max(t[-1] - t[0], 1e-9)
    N, K = len(units), len(t)
    BIG = 1e18
    D = np.full((N, K), BIG)
    P = np.full((N, K, 2), -1, dtype=int)
    D[0, :min(8, K)] = 0.3 * np.arange(min(8, K))
    for j in range(1, N):
        for k in range(1, K):
            b, ba = BIG, (-1, -1)
            for j2 in range(max(0, j - MAX_DU), j):
                for k2 in range(max(0, k - MAX_DE), k):
                    if D[j2, k2] >= BIG:
                        continue
                    c = (D[j2, k2] + 6.0 * abs(pos_u[j] - pos_e[k])
                         + SKIP_U * (j - j2 - 1) + SKIP_E * (k - k2 - 1))
                    if c < b:
                        b, ba = c, (j2, k2)
            D[j, k] = b
            P[j, k] = ba
    ends = [(D[N - 1, k] + 0.3 * (K - 1 - k), k) for k in range(K) if D[N - 1, k] < BIG]
    if not ends:
        return None
    _, k = min(ends)
    path, j = [], N - 1
    while j >= 0 and k >= 0:
        path.append((j, k))
        j, k = P[j, k]
    path.reverse()
    return path

# chanter-verified cluster identities (scores/atlas_chanter.json, 2026-08-18):
# these keys are GROUND TRUTH — seeded into every legend and LOCKED against EM
# vote overwrites, because the previous rotated seed (4=oligon 5=apostrofos
# 6=ison) was "confirmed" by EM through circular unitdeg pairing. Kentima
# composites: 16be (below/right of base) = +2, 16ab (top-middle) = +3.
CHANTER_LOCK = {'6|': 1, '5|': 0, '4|': -1, '3|': 1, '17|': 1, '20|': -2,
                '6|16be': 2, '6|16ab': 3, '3|16ab': 3,
                # classifier pass 2026-08-18 (marks: 8=klasma, 17=kentimata,
                # 21=carrier oligon, 22=ison-variant, 41=apostrofos-variant,
                # 13=oligon-variant, 10=apli/dipli dots):
                '22|': 0, '48|': -4, '41|': -1,
                '3|13ab': 2, '3|13ab+8be': 2,        # petasti+oligon = +2
                '20|41be': -3, '20|41be+8ab': -3,    # apostrofos in elafron
                '3|22ab': 0, '3|22ab+8be': 0,        # ison over petasti
                '22|17be+21be': 1,                   # ison+kentimata/carrier
                '7|17ab+21ab+22ab': 1,               # same over psifiston
                '47|17be+21be': -1,                  # elafron+kentimata/carrier
                '20|10be+10be': -2}                  # elafron + dipli dots


def cmd_legend(wd, hymns):
    os.makedirs(wd, exist_ok=True)
    lg_path = os.path.join(wd, 'legend_global.json')
    if os.path.exists(lg_path):
        iv = dict(json.load(open(lg_path))['keys'])
    else:
        iv = {}
    iv.update(CHANTER_LOCK)
    data = []
    for h in hymns:
        if not h.get('parallagi_dir'):
            continue
        evf = os.path.join(h['parallagi_dir'], 'events_full.jsonl')
        if not os.path.exists(evf):
            continue
        ev = [json.loads(l) for l in open(evf)]
        deg = [r['degree_abs'] for r in ev]
        times = [r['t0'] for r in ev]
        units, _ = load_units_h(h)
        data.append((h['name'], units, deg, times))
        n_mart = sum('mart_deg' in u for u in units)
        print(f"{h['name'][:44]:44s} units {len(units):4d} labeled-events "
              f"{len(deg)} martyries {n_mart}")
    for it in range(ITERS):
        votes = defaultdict(list)
        agree = tot = 0
        for name, units, deg, times in data:
            got = dtw(units, deg, iv)
            path = got[0] if got else None
            if not path:
                continue
            for (j2, k2), (j, k) in zip(path, path[1:]):
                if j - j2 == 1:
                    votes[units[j]['key']].append(deg[k] - deg[k2])
                exp = sum(iv.get(units[x]['key'], 0) for x in range(j2 + 1, j + 1))
                tot += 1
                agree += (deg[k] - deg[k2] == exp)
        changed = 0
        for key, obs in votes.items():
            if key in CHANTER_LOCK:
                continue               # ground truth never yields to votes
            if len(obs) >= 2:
                new = int(np.clip(round(float(np.median(obs))), -4, 4))
                if iv.get(key) != new:
                    iv[key] = new
                    changed += 1
        print(f"legend iter {it}: agreement {agree / max(tot, 1):.2f} "
              f"({tot} pairs), {changed} keys changed, {len(iv)} keys known")
    support = Counter()
    for name, units, deg, times in data:
        got = dtw(units, deg, iv)
        path = got[0] if got else []
        for j, _ in path:
            support[units[j]['key']] += 1
        # persist unit -> absolute degree (parallagi-anchored); unmatched
        # units fill by cumulating legend intervals from the nearest match
        ud = {j: int(deg[k]) for j, k in path}
        filled = {}
        last = None
        for j in range(len(units)):
            if j in ud:
                filled[j] = ud[j]
                last = j
            elif last is not None:
                filled[j] = filled[j - 1] + iv_of(iv, units[j])
        for j in range(len(units) - 1, -1, -1):
            if j not in filled and j + 1 in filled:
                filled[j] = filled[j + 1] - iv_of(iv, units[j + 1])
        json.dump({str(j): filled[j] for j in sorted(filled)},
                  open(os.path.join(wd, f'unitdeg_{name}.json'), 'w'))
    json.dump({'keys': iv, 'support': dict(support)}, open(lg_path, 'w'), indent=1)
    print(f"saved {len(iv)} keys -> {lg_path}")
    for k, n in support.most_common(12):
        print(f"  {k:14s} -> {iv.get(k, 0):+d}  (matched {n})")

SOFT_CYCLE = [8, 14, 8, 12]
HARD_STEPS = [4, 6, 20, 4, 12, 6, 20]     # octave-cyclic, hard chromatic from Πα
CPM = 1200.0 / 72.0

def trochos(d):
    """soft-chromatic absolute ladder position (moria), fifth-periodic"""
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += SOFT_CYCLE[i % 4]
    else:
        for i in range(-1, d - 1, -1):
            m -= SOFT_CYCLE[i % 4]
    return m

def hard_pos(d):
    """hard-chromatic absolute ladder position (moria), octave-cyclic"""
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += HARD_STEPS[i % 7]
    else:
        for i in range(-1, d - 1, -1):
            m -= HARD_STEPS[i % 7]
    return m

DIA_STEPS = [12, 10, 8, 12, 12, 10, 8]

def dia_pos(d):
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += DIA_STEPS[i % 7]
    else:
        for i in range(-1, d - 1, -1):
            m -= DIA_STEPS[i % 7]
    return m

# mode 2 uses BOTH scales by genre (chanter guidance): soft chromatic for the
# sticheraric verses, hard chromatic from Πα for heirmologic pieces — the
# score marks it with different martyria/fthores. Until fthora clusters are
# decoded, cmd_melos hypothesis-tests the ladders per hymn (or honors an
# explicit hymns.json 'genus': diatonic modes pass 'diatonic').
LADDERS = {'soft_chromatic': trochos, 'hard_chromatic': hard_pos,
           'diatonic': dia_pos}

def cmd_melos(wd, hymns, name):
    import subprocess
    h = next(x for x in hymns if x['name'] == name)
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    units, lyr = load_units_h(h)
    # chanter interval overrides ({unit_index: interval}, from the annotator
    # verification lane): the Ioannou font prints some neumes shape-identically
    # (ison vs oligon are the same bar), so shape-level extraction can't
    # disambiguate — the chanter's reading wins. Implemented by giving the
    # unit a synthetic private key so every iv_of lookup resolves to the
    # override without touching the shared legend.
    ivo = os.path.join(wd, f'iv_ovr_{name}.json')
    if os.path.exists(ivo):
        iv = dict(iv)
        n_ovr = 0
        for k, v in json.load(open(ivo)).items():
            j = int(k)
            if 0 <= j < len(units):
                units[j]['key'] = f'#ovr{j}'
                iv[f'#ovr{j}'] = v
                n_ovr += 1
        print(f'  {n_ovr} chanter interval overrides from {os.path.basename(ivo)}')
    udf = os.path.join(wd, f'unitdeg_{name}.json')
    unit_deg = None
    if os.path.exists(udf):
        raw_ud = {int(k): v for k, v in json.load(open(udf)).items()}
        if len(raw_ud) >= 0.8 * len(units):
            unit_deg = [raw_ud.get(j) for j in range(len(units))]
    mdir = os.path.join(wd, 'melos_' + name)
    os.makedirs(mdir, exist_ok=True)
    wav = os.path.join(mdir, 'audio.wav')
    if not os.path.exists(os.path.join(mdir, 'voice_notes.json')):
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', h['melos_audio'],
                        '-ac', '1', '-ar', '44100', wav], check=True)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(
            os.path.abspath(__file__)), '..', 'mcr', 'segment_tracks.py'),
            wav, mdir], check=True)
    vn = json.load(open(os.path.join(mdir, 'voice_notes.json')))
    cents = np.array([v[2] for v in vn])
    dur = np.array([v[1] - v[0] for v in vn])
    # Ni search: histogram peak is SOME degree; quantize events -> degrees
    # under each hypothesis and take the best DTW fit against the score
    hist, edges = np.histogram(cents, bins=np.arange(cents.min(), cents.max() + 30, 30),
                               weights=np.clip(dur, 0, 3))
    peak = float(edges[np.argmax(hist)] + 15)
    drone_lvl = peak            # most-persistent level = ison candidate
    best = None
    # genre determines genus (chanter rule: stichera=soft, heirmologic=hard
    # chromatic in mode 2) — honor hymns.json when it says so
    lads = ({h['genus']: LADDERS[h['genus']]} if h.get('genus') in LADDERS
            else LADDERS)
    for genus, pos in lads.items():
        for kdeg in range(0, 8):
            ni = peak - pos(kdeg) * CPM
            lad = {d: ni + pos(d) * CPM for d in range(-8, 16)}
            deg_obs = [min(lad, key=lambda d: abs(lad[d] - c)) for c in cents]
            ev_t = [v[0] for v in vn]
            beats_tot = sum(beats_seq(units))
            spb = max((ev_t[-1] - ev_t[0]) / max(beats_tot, 1.0), 0.05)
            got = dtw(units, deg_obs, iv, times=ev_t, spb=spb,
                      drone_c=(drone_lvl, cents), exp_abs=unit_deg)
            if got and (best is None or got[2] < best[3]):
                best = (kdeg, ni, got[0], got[2], deg_obs, genus, got[1], lad)
    kdeg, ni, path, cost, deg_obs, genus, start_deg, lad0 = best
    # empirical per-degree center refit (Vasilikos's practice sits 30-70c off
    # theory; nearest-THEORY quantization mislabels borderline notes). Two
    # rounds: matched events vote centers (clamped +-80c of theory), events
    # requantize, re-align.
    exp_cum = {}
    deg_obs_kept = deg_obs
    for _ in range(2):
        d = start_deg
        if unit_deg is not None:
            exp_by_unit = list(unit_deg)
        else:
            exp_by_unit = []
            for u in units:
                d += iv_of(iv, u)
                exp_by_unit.append(d)
        by_deg = {}
        for j, k in path:
            by_deg.setdefault(exp_by_unit[j], []).append(cents[k])
        emp = dict(lad0)
        for dg, cs_ in by_deg.items():
            if dg in emp and len(cs_) >= 2:
                th = lad0[dg]
                emp[dg] = float(np.clip(np.median(cs_), th - 80, th + 80))
        deg_obs = [min(emp, key=lambda dd: abs(emp[dd] - c)) for c in cents]
        ev_t = [v[0] for v in vn]
        got = dtw(units, deg_obs, iv, start=None if unit_deg else start_deg,
                  exp_abs=unit_deg,
                  drone_c=(drone_lvl, cents), times=ev_t,
                  spb=max((ev_t[-1] - ev_t[0]) / max(sum(
                      beats_seq(units)), 1.0), 0.05))
        if not got:
            break
        def agree_of(pth, dobs):
            ok = n = 0
            for (j2, k2), (j, k) in zip(pth, pth[1:]):
                e = sum(iv_of(iv, units[x]) for x in range(j2 + 1, j + 1))
                n += 1
                ok += (dobs[k] - dobs[k2] == e)
            return (ok / n if n else 0.0), n
        a_old, n_old = agree_of(path, best[4] if _ == 0 else deg_obs_kept)
        a_new, n_new = agree_of(got[0], deg_obs)
        # accept only if internal consistency improves (cost is not
        # comparable across different quantizations)
        if (a_new, n_new) > (a_old, n_old):
            path, start_deg, cost = got
            deg_obs_kept = deg_obs
        else:
            deg_obs = best[4] if _ == 0 else deg_obs_kept
            break
    agree = tot = 0
    agree_c = 0
    pos_g = LADDERS[genus]
    exp_deg_cum = []
    dd_ = start_deg
    for u in units:
        dd_ += iv_of(iv, u)
        exp_deg_cum.append(dd_)
    for (j2, k2), (j, k) in zip(path, path[1:]):
        if unit_deg is not None:
            exp = unit_deg[j] - unit_deg[j2]
            e1, e2 = unit_deg[j], unit_deg[j2]
        else:
            exp = sum(iv_of(iv, units[x]) for x in range(j2 + 1, j + 1))
            e1, e2 = exp_deg_cum[j], exp_deg_cum[j2]
        tot += 1
        agree += (deg_obs[k] - deg_obs[k2] == exp)
        # attraction-tolerant: sung interval within 55c of the notated one
        # (a note under έλξεις deviates by design — performance practice,
        # not misalignment)
        obs_c = cents[k] - cents[k2]
        exp_c = (pos_g(e1) - pos_g(e2)) * CPM
        agree_c += (abs(obs_c - exp_c) <= 55.0)
    out = []
    for j, k in path:
        u = units[j]
        out.append({'unit': int(j), 'page': int(u['pl'][0]), 'line': int(u['pl'][1]),
                    'key': u['key'], 'interval': int(iv.get(u['key'], 0)),
                    't0': float(vn[k][0]), 't1': float(vn[k][1]),
                    'cents': float(cents[k]), 'degree_obs': int(deg_obs[k]),
                    'gorgon': bool(u['gorgon']), 'klasma': bool(u['klasma'])})
    json.dump(out, open(os.path.join(mdir, 'aligned.json'), 'w'), indent=1)
    if '--em' in sys.argv:
        # melos-EM: matched single-step pairs vote intervals for keys the
        # parallagi seed didn't cover (agreement ~0.83 -> votes trustworthy)
        lg = json.load(open(os.path.join(wd, 'legend_global.json')))
        votes = defaultdict(list)
        for (j2, k2), (j, k) in zip(path, path[1:]):
            if j - j2 == 1:
                votes[units[j]['key']].append(deg_obs[k] - deg_obs[k2])
        changed = 0
        for key, obs in votes.items():
            if len(obs) >= 3:
                new = int(np.clip(round(float(np.median(obs))), -4, 4))
                if lg['keys'].get(key) != new:
                    lg['keys'][key] = new
                    changed += 1
        json.dump(lg, open(os.path.join(wd, 'legend_global.json'), 'w'), indent=1)
        print(f"  em: {changed} keys updated ({len(lg['keys'])} known)")
    summ = {'hymn': name, 'genus': genus, 'start': int(start_deg),
            'ni_cents_rel55': round(float(ni), 1),
            'n_units': len(units),
            'n_events': len(vn), 'n_matched': len(path), 'coverage_units_pct':
            round(100 * len(path) / max(len(units), 1), 1),
            'movement_agreement': round(agree / max(tot, 1), 2),
            'movement_agreement_cents': round(agree_c / max(tot, 1), 2),
            'ni_hz': round(55 * 2 ** (ni / 1200), 1)}
    json.dump(summ, open(os.path.join(mdir, 'summary.json'), 'w'), indent=1)
    print(f"{name:24s} {genus[:4]:4s} units {len(units):4d} events {len(vn):4d} "
          f"matched {len(path):4d} ({summ['coverage_units_pct']}%) mv-agree "
          f"{summ['movement_agreement']} Ni {summ['ni_hz']}Hz")

if __name__ == '__main__':
    mode = sys.argv[1]
    wd = sys.argv[2]
    hymns = json.load(open(sys.argv[sys.argv.index('--hymns') + 1]))
    if mode == 'legend':
        cmd_legend(wd, hymns)
    elif mode == 'melos':
        name = sys.argv[sys.argv.index('--hymn') + 1]
        cmd_melos(wd, hymns, name)
