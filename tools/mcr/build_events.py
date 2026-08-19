#!/usr/bin/env python3
"""Build the per-voice-event MCR training table from an aligned-piece workdir.

Input (workdir, chanter-verified pipeline state):
  voice_notes3.json  [t0, t1, _, gap_before] per segmented note event (audio-only)
  moria_track.npy    pitch in moria @10 ms (NaN = unvoiced)
  rms_track.npy      level @10 ms
  ison_timeline.json app-ison level events (needed to replicate stream cleaning)
  slots.json         {'t','gi','sub'} score slots
  slot_claims.json   slot -> claimed event index INTO THE CLEANED STREAM
  mcr_interpretation.json  glyph-level ground truth (name, beats, marks, line)
  expected_degrees.json    absolute degree per slot (martyria-closed)
  ornaments.json     sung-but-unwritten quick notes  [t0, t1, gi]
  pitch_ghosts_classified.json  chanter-marked tracker-artifact regions

The raw event stream is first cleaned EXACTLY as note_align6.py does (short-note
merge + ison-bleed merge) — slot_claims indexes the cleaned stream.

Output: events.jsonl — one row per cleaned voice event. Features are AUDIO-ONLY;
labels come from the alignment. Claimed events carry glyph/movement/beat labels;
unclaimed events carry event_kind = ornament | ghost | unlabeled.
"""
import json, sys, os
import numpy as np

HOP = 0.01
SEQ_N = 48          # contour samples per event (with edge context)
SEQ_PAD = 0.10      # context s either side of the event in the sequence window
BREATH_GAP = 0.14
LONG_DUR = 0.30     # "previous long event" reference for melisma-robust deltas

wd = sys.argv[1] if len(sys.argv) > 1 else '.'
out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(wd, 'events.jsonl')
j = lambda f: json.load(open(os.path.join(wd, f)))

def jopt(f):
    p = os.path.join(wd, f)
    return json.load(open(p)) if os.path.exists(p) else None

vn_raw = j('voice_notes3.json')
sl = jopt('slots.json')
claims = jopt('slot_claims.json')
interp = jopt('mcr_interpretation.json')
E = jopt('expected_degrees.json')
orn = jopt('ornaments.json') or []
ghosts = (jopt('pitch_ghosts_classified.json') or {'regions': []})['regions']
ison_ev = jopt('ison_timeline.json')
LABELED = all(x is not None for x in (sl, claims, interp, E))
if not LABELED:
    print('label files missing -> features-only mode (event_kind=unknown)')
mcr_dir = os.path.join(wd, '..', 'mcr')
MPS = 10.3
if os.path.isdir(mcr_dir):
    for cand in os.listdir(mcr_dir):
        if cand.endswith('.meta.json'):
            MPS = json.load(open(os.path.join(mcr_dir, cand)))['moria_per_step_avg']

mor = np.load(os.path.join(wd, 'moria_track.npy'))
rms = np.load(os.path.join(wd, 'rms_track.npy'))
rms_med = float(np.median(rms[rms > 0])) if (rms > 0).any() else 1.0

# ---- stream cleaning: byte-for-byte the note_align6.py rules ----
def _ison_at(t):
    if ison_ev is None:
        return 'M'          # no ison timeline: bleed merging disabled
    lv = ison_ev[0][1]
    for et, el in ison_ev:
        if et <= t + 0.5: lv = el
        else: break
    return lv

def _level(v):
    s = rms[int(v[0] * 100):max(int(v[0] * 100) + 2, int(v[1] * 100))]
    return float(np.mean(s)) if len(s) else 0.0

def med_pitch(t0, t1):
    s = mor[int((t0 + 0.03) * 100):max(int((t0 + 0.03) * 100) + 2, int((t1 - 0.02) * 100))]
    s = s[~np.isnan(s)]
    return float(np.median(s)) if len(s) else None

vn = []
for v in vn_raw:
    dur = v[1] - v[0]
    p = med_pitch(v[0], v[1])
    prevp = med_pitch(vn[-1][0], vn[-1][1]) if vn else None
    lv = _ison_at(v[0])
    quiet = vn and _level(v) < 0.45 * max(_level(vn[-1]), 1e-6)
    bleed = (quiet and lv != 'M' and p is not None and abs(p - lv) < 4.5
             and prevp is not None and abs(p - prevp) > 15 and dur < 0.5)
    if vn and (dur < 0.16 or bleed):
        vn[-1][1] = v[1]
    else:
        vn.append(list(v))
print(f"stream cleaned: {len(vn_raw)} -> {len(vn)} events")

ev2slot = {}
for s, c in enumerate(claims or []):
    if c is not None:
        assert c not in ev2slot, f"event {c} claimed twice"
        assert c < len(vn), f"claim {c} beyond cleaned stream ({len(vn)})"
        ev2slot[c] = s

def seg(track, t0, t1):
    a, b = int(t0 / HOP), int(t1 / HOP)
    return track[max(a, 0):max(b, a + 1)]

def resample(track, t0, t1, n):
    ts = np.linspace(t0, t1, n)
    idx = np.clip((ts / HOP).astype(int), 0, len(track) - 1)
    return track[idx]

def olap(a, b, c, d):
    return max(0.0, min(b, d) - max(a, c))

meds = [med_pitch(v[0], v[1]) for v in vn]
durs = np.array([v[1] - v[0] for v in vn])

def delta(a, b):
    return None if (a is None or b is None) else (b - a) / MPS

# ---- diatonic ladder quantization (audio-only: offset + drift estimated
# from the piece itself; moria are Ni-anchored by construction) ----
LADDER_STEPS = [12, 10, 8, 12, 12, 10, 8]     # Ni-Pa-Vou-Ga-Di-Ke-Zo-Ni'
LAD_LO, LAD_HI = -8, 16
lad_pos = {0: 0.0}
for d in range(0, LAD_HI):
    lad_pos[d + 1] = lad_pos[d] + LADDER_STEPS[d % 7]
for d in range(0, LAD_LO, -1):
    lad_pos[d - 1] = lad_pos[d] - LADDER_STEPS[(d - 1) % 7]
LAD_D = np.array(sorted(lad_pos))
LAD_M = np.array([lad_pos[d] for d in sorted(lad_pos)])

def nearest_deg(m):
    i = int(np.argmin(np.abs(LAD_M - m)))
    return int(LAD_D[i]), float(m - LAD_M[i])

mm = np.array([m for m in meds if m is not None])
cand = np.arange(-6.0, 6.01, 0.25)
off_global = float(cand[np.argmin([np.median(np.min(np.abs(mm[:, None] - (LAD_M + o)[None, :]), axis=1)) for o in cand])])
ev_t = np.array([(v[0] + v[1]) / 2 for v in vn])
devs = np.array([nearest_deg(m - off_global)[1] if m is not None else np.nan for m in meds])
off_local = np.full(len(vn), off_global)
for k in range(len(vn)):
    w = np.abs(ev_t - ev_t[k]) <= 12.0
    dv = devs[w]
    dv = dv[~np.isnan(dv)]
    if len(dv) >= 5:
        off_local[k] = off_global + float(np.median(dv))
degs = [None if meds[k] is None else nearest_deg(meds[k] - off_local[k])
        for k in range(len(vn))]
print(f"ladder offset: global {off_global:+.2f} moria, "
      f"local range [{off_local.min():+.2f}, {off_local.max():+.2f}]")

def ddeg(i, k):
    if i is None or degs[i] is None or degs[k] is None:
        return None
    return degs[k][0] - degs[i][0]

rows = []
since_breath = 0
for k, v in enumerate(vn):
    t0, t1, _, gap = v
    dur = t1 - t0
    if gap >= BREATH_GAP:
        since_breath = 0
    # --- pitch contour (steps, relative to own median) ---
    core = seg(mor, t0, t1)
    voiced = core[~np.isnan(core)]
    med = meds[k]
    nan_frac = float(np.isnan(core).mean()) if len(core) else 1.0
    if med is not None and len(voiced) >= 4:
        c_steps = (voiced - med) / MPS
        ts = np.arange(len(voiced))
        fit = np.polyfit(ts, c_steps, 1)
        slope = float(fit[0] / HOP)
        resid = float(np.std(c_steps - np.polyval(fit, ts)))
        rng = float(c_steps.max() - c_steps.min())
        iqr = float(np.percentile(c_steps, 75) - np.percentile(c_steps, 25))
        third = max(1, len(voiced) * 2 // 5)
        within = float(np.median(c_steps[-third:]) - np.median(c_steps[:third]))
        dsm = np.diff(np.convolve(c_steps, np.ones(3) / 3, 'valid')) if len(voiced) >= 5 else np.array([0.0])
        sgn = np.sign(dsm[np.abs(dsm) > 0.08])
        turns = int(np.sum(sgn[1:] != sgn[:-1])) if len(sgn) > 1 else 0
    else:
        slope = resid = rng = iqr = within = 0.0
        turns = 0
    # --- movement vs neighbours (steps) ---
    d_prev = delta(meds[k - 1], med) if k > 0 else None
    d_prev2 = delta(meds[k - 2], med) if k > 1 else None
    d_next = delta(med, meds[k + 1]) if k + 1 < len(vn) else None
    kl = next((i for i in range(k - 1, -1, -1) if durs[i] >= LONG_DUR), None)
    d_prev_long = delta(meds[kl], med) if kl is not None else None
    # --- rms envelope ---
    r = seg(rms, t0, t1)
    if len(r) >= 2:
        peak = float(r.max())
        rmean = float(r.mean()) / rms_med
        attack = float(np.argmax(r >= 0.8 * peak) / len(r))
        tail = float(np.mean(r[-max(1, len(r) // 5):]) / peak) if peak > 0 else 0.0
    else:
        rmean, attack, tail, peak = 0.0, 0.0, 0.0, 0.0
    r_prev = seg(rms, *vn[k - 1][:2]) if k > 0 else np.array([1.0])
    rms_prev_ratio = float(peak / max(float(r_prev.max()), 1e-6)) if len(r_prev) else 1.0
    # --- tempo-relative duration ---
    lo, hi = max(0, k - 5), min(len(vn), k + 6)
    dur_rel = float(dur / max(np.median(durs[lo:hi]), 1e-6))
    gap_after = float(vn[k + 1][0] - t1) if k + 1 < len(vn) else 0.0

    feats = {
        'dur': round(dur, 4), 'log_dur': round(float(np.log(max(dur, 1e-3))), 4),
        'dur_rel': round(dur_rel, 4),
        'gap_before': round(gap, 4), 'gap_after': round(gap_after, 4),
        'breath_before': int(gap >= BREATH_GAP), 'breath_after': int(gap_after >= BREATH_GAP),
        'since_breath': since_breath,
        'd_prev': None if d_prev is None else round(d_prev, 3),
        'd_prev2': None if d_prev2 is None else round(d_prev2, 3),
        'd_prev_long': None if d_prev_long is None else round(d_prev_long, 3),
        'd_next': None if d_next is None else round(d_next, 3),
        'ddeg_prev': ddeg(k - 1 if k > 0 else None, k),
        'ddeg_prev_long': ddeg(kl, k),
        'ddeg_next': ddeg(k, k + 1) if k + 1 < len(vn) else None,
        'deg_off': None if degs[k] is None else round(degs[k][1], 2),
        # passing-tone position: where this event's pitch sits between its
        # neighbours' (ornaments/melisma transients tend to sit mid-glide)
        'mid_frac': (round(float(np.clip((med - meds[k - 1]) / (meds[k + 1] - meds[k - 1]), -1, 2)), 3)
                     if (0 < k < len(vn) - 1 and med is not None
                         and meds[k - 1] is not None and meds[k + 1] is not None
                         and abs(meds[k + 1] - meds[k - 1]) > 5.0) else None),
        'slope': round(slope, 3), 'resid': round(resid, 3),
        'range': round(rng, 3), 'iqr': round(iqr, 3),
        'within': round(within, 3), 'turns': turns, 'nan_frac': round(nan_frac, 3),
        'rms_mean': round(rmean, 3), 'attack': round(attack, 3), 'tail': round(tail, 3),
        'rms_prev_ratio': round(rms_prev_ratio, 3),
        'prev_dur': round(float(durs[k - 1]), 4) if k > 0 else 0.0,
        'next_dur': round(float(durs[k + 1]), 4) if k + 1 < len(vn) else 0.0,
    }
    # --- sequence channels for the CNN: pitch(steps rel med), voiced mask, rms ---
    w0, w1 = t0 - SEQ_PAD, t1 + SEQ_PAD
    p = resample(mor, w0, w1, SEQ_N)
    m = (~np.isnan(p)).astype(float)
    ref = med if med is not None else float(np.nanmedian(p)) if not np.all(np.isnan(p)) else 0.0
    p = np.where(np.isnan(p), ref, p)
    p = (p - ref) / MPS
    rq = resample(rms, w0, w1, SEQ_N) / rms_med

    row = {'event': k, 't0': round(t0, 3), 't1': round(t1, 3), 'features': feats,
           'seq_pitch': [round(float(x), 3) for x in p],
           'seq_mask': [int(x) for x in m],
           'seq_rms': [round(float(x), 3) for x in rq]}

    if not LABELED:
        row['event_kind'] = 'unknown'
        row['line'] = int(t0 // 15)      # pseudo-groups for any grouped use
    elif k in ev2slot:
        s = ev2slot[k]
        g = interp[sl['gi'][s]]
        sub = sl['sub'][s]
        beats = g['beats'][sub] if sub < len(g['beats']) else g['beats'][-1]
        prev_claimed = max((s2 for s2 in range(s) if claims[s2] is not None), default=None)
        row.update({
            'event_kind': 'structural',
            'glyph': f"{g['name']}.{sub}",
            'cp': g['cp'], 'sub': sub, 'n_subs': g['sub_notes'],
            'movement': (E[s] - E[s - 1]) if s > 0 else None,
            'mv_from_prev_claimed': (E[s] - E[prev_claimed]) if prev_claimed is not None else None,
            'beats': beats, 'gorgon': int(bool(g['gorgon'])),
            'duration_mark': g['duration_mark'],
            'quality_marks': g['quality_marks'],
            'line': g['line'], 'word': g.get('word'),
        })
    else:
        in_orn = any(olap(t0, t1, o0, o1) > 0.05 for o0, o1, _ in orn)
        in_ghost = any(olap(t0, t1, r['t0'], r['t1']) > 0.4 * dur for r in ghosts)
        row['event_kind'] = 'ornament' if in_orn else ('ghost' if in_ghost else 'unlabeled')
        # group unclaimed events by nearest structural line for leakage-safe CV
        near = min((abs(t0 - vn[c][0]), s) for c, s in ev2slot.items())[1]
        row['line'] = interp[sl['gi'][near]]['line']
    rows.append(row)
    since_breath += 1

with open(out_path, 'w') as f:
    for r in rows:
        f.write(json.dumps(r) + '\n')

from collections import Counter
kinds = Counter(r['event_kind'] for r in rows)
print(f"{len(rows)} events -> {out_path}")
print('kinds:', dict(kinds))
print('glyph classes:', len({r['glyph'] for r in rows if 'glyph' in r}))
mv = Counter(r['movement'] for r in rows if r.get('movement') is not None)
print('movement label distribution:', dict(sorted(mv.items())))
agree = tot = 0
for r in rows:
    if r.get('mv_from_prev_claimed') is not None and r['features']['d_prev_long'] is not None:
        tot += 1
        agree += (round(r['features']['d_prev_long']) == r['mv_from_prev_claimed'])
print(f"sanity: round(d_prev_long) == mv_from_prev_claimed on {agree}/{tot} "
      f"({100 * agree / max(tot, 1):.0f}%)")
