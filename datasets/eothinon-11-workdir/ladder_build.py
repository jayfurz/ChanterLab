#!/usr/bin/env python3
"""Build per-frame parallagi ladder track from the moria track.
- octave-glitch folding vs running median
- intonation drift correction (opening +3.5 moria)
- attractions (diatonic only): Zo-flat/Ke-raised at ~58 by arsis/thesis; Vou-raised at ~26.5
- soft-chromatic chroa spans"""
import json, numpy as np

mor_raw = np.load('moria_track.npy')
rms = np.load('rms_track.npy')
INTON = json.load(open('intonation_curve.json'))
_slots = json.load(open('slots.json'))
_exp = json.load(open('expected_degrees.json'))
_EXP_T = _slots['t']
import bisect as _bisect
def expected_deg_at(t):
    j = _bisect.bisect_right(_EXP_T, t) - 1
    return _exp[max(0, j)]
DEG_POS = {-2:-18,-1:-8,0:0,1:12,2:22,3:30,4:42,5:54,6:64,7:72,8:84}
DEG_VARIANTS = {2:[('Βου',22),('Βου↑',26.5)], 3:[('Γα',30),('Γα↑',35.5)],
                5:[('Κε',54),('Κε↑',58)], 6:[('Ζω',64),('Ζω♭',58)]}
ISON_EV = json.load(open('ison_timeline.json'))   # [[t, level_moria | 'M'], ...] from score red letters
def ison_at(t):
    lv = ISON_EV[0][1]
    for et, el in ISON_EV:
        if et <= t + 0.5: lv = el
        else: break
    return lv
tj = json.load(open('timing.json'))
t_to = tj['line_times'][1]

def root_offset(t):
    i = min(int(t), len(INTON)-1)
    return INTON[i]

# ---- octave folding vs running median of valid values ----
mor = mor_raw.copy()
runmed = np.nan; rvoiced = np.nan
alpha = 0.02
for i in range(len(mor)):
    m = mor[i]
    if np.isnan(m): continue
    if not np.isnan(runmed):
        if abs(m - runmed) > 45:
            if abs(m + 72 - runmed) < 25: m += 72
            elif abs(m - 72 - runmed) < 25: m -= 72
            else:
                mor[i] = np.nan; continue     # unexplainable outlier: drop frame
        # ison-drone bleed: reading at a known ison level, arrived from well above,
        # at breath-level energy -> the drone surfaced during a breath: fade the dot
        quiet = (not np.isnan(rvoiced)) and rms[i] < 0.45 * rvoiced
        lv = ison_at(i/100.0)
        if quiet and lv != 'M' and abs(runmed - m) > 10 and abs(m - lv) < 4.5:
            mor[i] = np.nan; continue
        mor[i] = m
    runmed = m if np.isnan(runmed) else (1-alpha)*runmed + alpha*m
    if np.isnan(rvoiced): rvoiced = rms[i]
    elif rms[i] > 0.3 * rvoiced: rvoiced = 0.99*rvoiced + 0.01*rms[i]

# flicker cleanup: voiced islands < 130ms bordered by gaps are transition/bleed frames
isn = np.isnan(mor)
i = 0
while i < len(mor):
    if not isn[i]:
        j = i
        while j < len(mor) and not isn[j]: j += 1
        left_gap = i == 0 or isn[i-1]
        right_gap = j >= len(mor) or (j < len(mor) and isn[j])
        if (j - i) < 13 and left_gap and right_gap:
            mor[i:j] = np.nan
        i = j
    else:
        i += 1

wtimes = {}
for cap in tj['captions']:
    for wd in cap['words']:
        wtimes.setdefault(wd['w'].lower().strip('.,:'), []).append(wd['t0'])
sp1 = (wtimes['by'][0]-0.3, wtimes['preserve'][0]); sp2 = (wtimes['from'][-1]-0.3, wtimes['that'][-1])

DIA = [('Ζω',-8,None),('Νη',0,None),('Πα',12,None),('Βου',22,None),('Βου↑',26.5,'vou'),
       ('Γα',30,None),('Γα↑',35.5,'ga'),('Δι',42,None),('Κε',54,None),('ATTR',58,'kezo'),
       ('Ζω',64,None),("Νη'",72,None),("Πα'",84,None)]
CHR = [('Ζω',-8,None),('Νη',0,None),('Πα',12,None),('Βου',20,None),('Γα',34,None),
       ('Δι',42,None),('Κε',50,None),('Ζω',64,None),("Νη'",72,None),("Πα'",84,None)]

FPS = 30; n_frames = int(len(mor)/100*FPS)
track = []
for fi in range(n_frames):
    t = fi/FPS
    i0 = int(t*100); seg = mor[i0:i0+4]; seg = seg[~np.isnan(seg)]
    chroa = 1 if (sp1[0]<=t<=sp1[1] or sp2[0]<=t<=sp2[1]) else 0
    if len(seg)==0: track.append([None,"",0,chroa]); continue
    m = float(np.median(seg)) - root_offset(t)
    grid = CHR if chroa else DIA
    name,pos,attr = min(grid, key=lambda g: abs(g[1]-m))
    flat = 0
    def _med(a, b):
        vs = [mor[k] - root_offset(k / 100.0)
              for k in range(max(0, a), min(b, len(mor))) if not np.isnan(mor[k])]
        return float(np.median(vs)) if vs else m
    if attr == 'kezo':
        # arsis/thesis by sustained direction: forward median decides,
        # immune to transients/tails (chanter-corrected 2026-08-17)
        name, flat = ('Κε↑', 0) if _med(i0, i0 + 180) >= 56 else ('Ζω', 1)
    # attraction-band HOLD: vibrato around ~58 oscillates through Ke(54) and
    # Zo(64) frames — if the LOCAL median sits in the band, the whole hold is
    # one attracted note: raised Ke in arsis, Zo-flat in thesis (chanter:
    # "O Peter" shows only Ke-sharp).  True Ke / Zo holds are untouched.
    if not chroa and flat == 0 and name in ('Κε', 'Ζω', 'Κε↑') and 52 <= m <= 65.5:
        loc = _med(i0 - 60, i0 + 60)
        if 55.5 <= loc <= 62.5:
            name, flat = ('Κε↑', 0) if _med(i0, i0 + 180) >= 56 else ('Ζω', 1)
    # chant-aware label: within the ambiguity band, prefer the score-expected
    # degree family (dot still shows true pitch; only the LABEL consults the score)
    if not chroa and name in ('Βου','Βου↑','Γα','Γα↑','Δι'):
        ed = expected_deg_at(t)
        if ed in DEG_VARIANTS:
            fam = DEG_VARIANTS[ed]
            best = min(fam, key=lambda v: abs(v[1]-m))
            cur_fam = 2 if name.startswith('Βου') else (3 if name.startswith('Γα') else 4)
            if cur_fam != ed and abs(best[1]-m) <= 4.5:
                name = best[0]
    track.append([round(m,1), name, flat, chroa])
# label hysteresis: a new label must persist >=3 frames (100ms) to display
stable = [t[:] for t in track]
cur = None; cand = None; cnt = 0
for fi in range(len(track)):
    nm = track[fi][1]
    if not nm:
        cur = None; cand = None; cnt = 0; continue
    if nm == cur:
        cand = None; cnt = 0
    elif nm == cand:
        cnt += 1
        if cnt >= 3: cur = nm; cand = None; cnt = 0
    else:
        cand = nm; cnt = 1
    if cur is None: cur = nm
    stable[fi][1] = cur
    stable[fi][2] = track[fi][2] if cur == track[fi][1] else 0
track = stable
json.dump(track, open('ladder_track.json','w'))
from collections import Counter
lab = Counter(t[1] for t in track if t[0] is not None)
print("degrees:", dict(lab.most_common()))
