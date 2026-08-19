#!/usr/bin/env python3
"""Learn the cluster->interval legend of a vector-extracted classic score by
EM against a note-precise recording (the Vasilikos parallagi/melos tapes).

Units = connected groups of x-overlapping black glyphs on a line (base note
glyph + attached marks). Each unit-key (base cluster + positioned marks) emits
one sung note with a learnable interval. Red glyphs (martyries/fthores) and
configured silent clusters emit nothing. EM: movement-DTW align events<->units
-> re-estimate each key's interval from the observed movement distribution ->
repeat. The red martyria letters are held out as absolute-degree checkpoints.

Usage: em_legend.py <workdir> (needs score_vec.json, voice_notes.json)
   ->  legend.json (unit keys, intervals, support), units.json, em_claims.json
"""
import json, sys, os
from collections import Counter, defaultdict
import numpy as np

wd = sys.argv[1] if len(sys.argv) > 1 else '.'
sv = json.load(open(os.path.join(wd, 'score_vec.json')))
vn = json.load(open(os.path.join(wd, 'voice_notes.json')))

# ---- config: role priors (from reading p643 + EM round 1; EM refines) ----
# 4=ison 1=apostrofos 8=oligon 0=petasti 9=kentimata 6/26=elafron(+apostr above
# =-2) 21=yporrhoe(TWO descending) 14=bareia 12=RED gorgon 27=apli
INIT_IV = {4: 0, 8: 1, 1: -1, 0: 1, 9: 1, 18: -1, 24: 1, 6: -2, 26: -2,
           10: 0, 20: 0, 29: -2, 19: 1, 11: 0}
SILENT = {14}                  # bareia: standalone accent, no note
MARK_ONLY = {27, 13, 5}        # apli / dots / apoderma: never a base
TWO_SUB = {21: (-1, -1)}       # yporrhoe: two descending sub-notes (frozen)
TIME_RED = {12, 13}            # red gorgon (+companion dot): time, attach to note
GORGON_CL, APLI_CL = 12, 27
STEP_C = 165.0                 # cents per diatonic step (refit in round 1)
W_MV, MV_CAP = 1.0, 2.6
W_ABS, ABS_CAP = 0.3, 2.0      # absolute-pitch anchor (kills cumulative-
                               # degree drift; Ni from the final cadence)
SKIP_U, SKIP_E = 0.9, 0.55
MAX_DU, MAX_DE = 4, 4
BANDF = 0.22
ITERS = 4

# ---- build units ----
G = sv['glyphs']
by_line = defaultdict(list)
for g in G:
    by_line[g['line']].append(g)
units = []
for li in sorted(by_line):
    gl = sorted(by_line[li], key=lambda g: g['x0'])
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
                       > 0.35 * min(x['x1'] - x['x0'], h['x1'] - h['x0']) for x in grp):
                    grp.append(h); used[j] = True; changed = True
        black = [x for x in grp if not x['red']]
        red = [x for x in grp if x['red']]
        if not black:
            units.append({'line': li, 'x0': min(x['x0'] for x in grp),
                          'kind': 'red', 'red_cl': sorted(x['cluster'] for x in red)})
            continue
        base = max((x for x in black if x['cluster'] not in MARK_ONLY),
                   key=lambda x: (x['x1'] - x['x0']) * (x['y1'] - x['y0']), default=None)
        if base is None:
            units.append({'line': li, 'x0': min(x['x0'] for x in grp), 'kind': 'silent',
                          'key': 'marks:' + ','.join(str(x['cluster']) for x in black)})
            continue
        marks = []
        for x in black:
            if x is base:
                continue
            pos = 'ab' if (x['y0'] + x['y1']) / 2 < (base['y0'] + base['y1']) / 2 - 1 else 'be'
            marks.append(f"{x['cluster']}{pos}")
        key = f"{base['cluster']}|{'+'.join(sorted(marks))}"
        kind = 'silent' if base['cluster'] in SILENT else 'note'
        units.append({'line': li, 'x0': min(x['x0'] for x in grp),
                      'xc': (base['x0'] + base['x1']) / 2, 'kind': kind,
                      'key': key, 'base': base['cluster'],
                      'subs': len(TWO_SUB.get(base['cluster'], (0,))),
                      'gorgon': any(x['cluster'] == GORGON_CL for x in grp),
                      'apli': any(x['cluster'] == APLI_CL for x in black),
                      'red_cl': sorted(x['cluster'] for x in red)})
# red time-marks (gorgon prints red in this book): attach standalone red
# gorgon units to the nearest note unit on the line, then drop them
notes_on = defaultdict(list)
for u in units:
    if u['kind'] == 'note':
        notes_on[u['line']].append(u)
kept = []
for u in units:
    if u['kind'] == 'red' and set(u['red_cl']) <= TIME_RED and notes_on[u['line']]:
        tgt = min(notes_on[u['line']], key=lambda n: abs(n['xc'] - u['x0']))
        if GORGON_CL in u['red_cl']:
            tgt['gorgon'] = True
        continue
    kept.append(u)
units = kept
units.sort(key=lambda u: (u['line'], u['x0']))
slots = [(i, sb) for i, u in enumerate(units) if u['kind'] == 'note'
         for sb in range(u['subs'])]
print(f"{len(units)} units -> {len(slots)} note slots "
      f"({sum(u['kind'] == 'red' for u in units)} red, "
      f"{sum(u['kind'] == 'silent' for u in units)} silent units); "
      f"{len({units[i]['key'] for i, _ in slots})} note keys; {len(vn)} events")

iv = {}
for i, _ in slots:
    u = units[i]
    if u['base'] not in TWO_SUB:
        iv.setdefault(u['key'], INIT_IV.get(u['base'], 0))

def iv_of(i, sb):
    u = units[i]
    return TWO_SUB[u['base']][sb] if u['base'] in TWO_SUB else iv[u['key']]

pitch = np.array([v[2] for v in vn])
t0 = np.array([v[0] for v in vn])
dur = np.array([v[1] - v[0] for v in vn])
step_c = STEP_C
ni_c = None                    # set by the anchor search below

def decode():
    """movement DTW: note slots claim events (monotonic, banded)"""
    N, K = len(slots), len(vn)
    deg = np.zeros(N + 1)
    for j, (i, sb) in enumerate(slots):
        deg[j + 1] = deg[j] + iv_of(i, sb)
    beats = np.array([((0.5 if units[i]['gorgon'] else 1.0)
                       + (1.0 if units[i]['apli'] else 0.0)) / units[i]['subs']
                      for i, _ in slots])
    cb = np.concatenate([[0], np.cumsum(beats)])
    spb = (t0[-1] + dur[-1] - t0[0]) / cb[-1]
    BIG = 1e18
    D = np.full((N, K), BIG); P = np.full((N, K, 2), -1, dtype=int)
    band = np.abs((t0 - t0[0]) / (t0[-1] - t0[0] + 1e-9)[None] -
                  (cb[:N] / cb[-1])[:, None]) <= BANDF
    band[:3, :6] = True; band[-3:, -6:] = True
    for k in range(min(6, K)):
        if band[0, k]:
            D[0, k] = 0.4 * k
    for j in range(1, N):
        for k in range(K):
            if not band[j, k]:
                continue
            best, barg = BIG, (-1, -1)
            for j2 in range(max(0, j - MAX_DU), j):
                for k2 in range(max(0, k - MAX_DE), k):
                    if D[j2, k2] >= BIG:
                        continue
                    obs = (pitch[k] - pitch[k2]) / step_c
                    exp = deg[j + 1] - deg[j2 + 1]
                    c = (D[j2, k2] + W_MV * min(abs(obs - exp), MV_CAP)
                         + SKIP_U * (j - j2 - 1) + SKIP_E * (k - k2 - 1))
                    c += W_ABS * min(abs((pitch[k] - ni_c) / step_c - deg[j + 1]),
                                     ABS_CAP)
                    B = cb[j + 1] - cb[j2 + 1]
                    impl = (t0[k] - t0[k2]) / spb
                    c += 0.25 * min(abs(impl - B), 3.0)
                    if c < best:
                        best, barg = c, (j2, k2)
            D[j, k] = best; P[j, k] = barg
    ends = [(D[N - 1, k] + 0.4 * (K - 1 - k), k) for k in range(K)
            if D[N - 1, k] < BIG]
    if not ends:
        raise SystemExit('decode failed: no complete path')
    _, k = min(ends)
    path, j = [], N - 1
    while j >= 0 and k >= 0:
        path.append((j, k))
        j, k = P[j, k]
    path.reverse()
    return path, deg

# ---- Ni anchor search: histogram peak is SOME ladder degree; try which ----
wts = np.clip(dur, 0, 2.0)
hist, edges = np.histogram(pitch, bins=np.arange(pitch.min(), pitch.max() + 25, 25),
                           weights=wts)
peak_c = float(edges[np.argmax(hist)] + 12.5)
best = None
for kdeg in range(0, 8):
    ni_c = peak_c - kdeg * step_c
    path, deg = decode()
    ok = sum(round((pitch[k] - pitch[k2]) / step_c) == deg[j + 1] - deg[j2 + 1]
             for (j2, k2), (j, k) in zip(path, path[1:]))
    score = ok + 0.3 * len(path)
    if best is None or score > best[0]:
        best = (score, ni_c, kdeg)
ni_c = best[1]
print(f"Ni anchor: histogram peak {peak_c:.0f}c = degree {best[2]} -> "
      f"Ni {ni_c:.0f}c (~{55 * 2 ** (ni_c / 1200):.1f} Hz)")

for it in range(ITERS):
    path, deg = decode()
    obs_by_key = defaultdict(list)
    hits = tot = 0
    dc1 = []
    for (j2, k2), (j, k) in zip(path, path[1:]):
        obs_c = pitch[k] - pitch[k2]
        exp = deg[j + 1] - deg[j2 + 1]
        tot += 1
        hits += (round(obs_c / step_c) == exp)
        if j - j2 == 1:
            ui, sb = slots[j]
            if units[ui]['base'] not in TWO_SUB:
                obs_by_key[units[ui]['key']].append(obs_c / step_c)
            if abs(exp) == 1 and abs(obs_c / step_c - exp) < 0.6:
                dc1.append(abs(obs_c))
    if dc1:
        step_c = float(np.clip(np.median(dc1), 130, 210))
    changed = 0
    for key, obs in obs_by_key.items():
        if len(obs) >= 3:
            new = int(np.clip(round(np.median(obs)), -4, 4))
            if new != iv[key]:
                iv[key] = new; changed += 1
    print(f"iter {it}: claimed {len(path)}/{len(slots)} slots, movement "
          f"agreement {hits / max(tot, 1):.2f}, step {step_c:.0f}c, "
          f"{changed} key intervals changed")

path, deg = decode()
support = Counter(units[slots[j][0]]['key'] for j, _ in path)
json.dump({'step_cents': step_c,
           'keys': {k: {'interval': iv[k], 'claimed': support.get(k, 0)}
                    for k in sorted(iv)},
           'two_sub': {str(c): list(v) for c, v in TWO_SUB.items()}},
          open(os.path.join(wd, 'legend.json'), 'w'), indent=1)
json.dump(units, open(os.path.join(wd, 'units.json'), 'w'))
json.dump([[int(slots[j][0]), int(slots[j][1]), int(k)] for j, k in path],
          open(os.path.join(wd, 'em_claims.json'), 'w'))
print('\nlearned intervals (claimed>=3):')
for k in sorted(iv, key=lambda k: -support.get(k, 0)):
    if support.get(k, 0) >= 3:
        print(f"  {k:16s} -> {iv[k]:+d}  (claimed {support[k]})")
# absolute-degree checkpoints at red martyria units
print('\ncumulative degree at red-martyria units (letter check):')
degfull = {}
d = 0
for i, u in enumerate(units):
    if u['kind'] == 'note':
        for sb in range(u['subs']):
            d += iv_of(i, sb)
    if u['kind'] == 'red' or u.get('red_cl'):
        degfull.setdefault(tuple(u.get('red_cl', [])), []).append(d % 7)
for cl, ds in sorted(degfull.items()):
    print(f"  red {cl}: degrees(mod 7) {Counter(ds).most_common(4)}")
