#!/usr/bin/env python3
"""v6: movement-space DTW aligner (tools/chant-reel/DESIGN-V2-ALIGNER.md).

Score side reuses v1's chanter-verified slot expansion (gorgon steal w/ 0.5
floor, duration marks, compounds, weight overrides). Alignment is new:
- movements, not positions: cost compares sung pitch deltas (moria/10.3) with
  scored movements (expected_degrees deltas, martyria-closed; learned_intervals
  used as a consistency cross-check). NO absolute-pitch term.
- piecewise tempo: local sec/beat = moving average over the last ~4 claimed
  slots, RESET at breaths (gap_before >= 0.14) and barline boundary slots.
- generic anchor interface: ANCHORS is a list of (slot_index, time, kind);
  'hard' anchors partition the alignment into independently-aligned spans,
  'soft' anchors add a weak time prior on a slot's claim inside the DP.
  No word-level / whisper-bias assumptions — dense syllable-acoustic anchors
  (design addendum 2026-08-17) plug into the same list.
- no metronomic fallback: unclaimed slots interpolate between their claimed
  neighbors' PERFORMANCE times (beat-proportional within the bracket only).

-> slots.json {'t','gi','sub'}, slot_claims.json, ornaments.json, timing.json
   (v1 formats; ladder_build.py / render.py unchanged).
"""
import json, math, os
from collections import deque
import numpy as np

# ---- constants (score side: chanter-verified, from v1) ----
GORGON = {0xf053, 0xf073, 0xf048}   # gorgon (S+s case pair) + red dotted
DURATION_CP = {0xf061: 2.0, 0xf041: 2.0, 0xf027: 2.0, 0xf06b: 3.0}
WEIGHT_OVR = {53: 2.0, 59: 0.5, 82: 1.0}
SUBW_OVR = {(58, 1): 0.5}
YPORRHOE, SYNELAF = 0xf05f, 0xf050
KENTIMATA_COMPOUNDS = {0xf0d7, 0xf06f, 0xf077, 0xf04f}
MANUAL = [(49, 54.0), (52, 58.0), (56, 61.0), (62, 65.0), (76, 76.0), (77, 77.5),
          (118, 119.0), (150, 154.0), (157, 157.0), (218, 220.97), (249, 253.0)]
MPS = 10.3          # avg moria per diatonic step

# ---- v2 aligner parameters ----
W_MV = 0.7          # movement-cost weight (per step of |sung - expected|)
MV_CAP = 2.5        # movement cost cap (steps)
MV_NOPITCH = 0.6    # movement cost when either pitch is unknown
DUR_DEFICIT = 2.2   # per-beat penalty: claimed IOI shorter than 0.75x scored
DUR_SURPLUS = 0.5   # per-beat penalty: claimed IOI longer than 1.8x scored
CLAIM_BONUS = 0.55  # max reward for a claim whose IOI fits the scored beats
                    # (graded: fades to 0 by |impl - B| = 0.6*B + 0.25 beats)
SKIP_NOTE = 0.45    # per skipped voice note (ornament absorption)
SKIP_NOTE_TAIL = 0.35
SKIP_SLOT_STATIC = 0.25   # skipped slot whose expected movement is 0 (legato merge)
SKIP_SLOT_MOVE = 0.8      # skipped slot that should have moved (missed onset)
W_PIN = 0.32        # hard-anchor claim window (s)
PIN_TIE = 0.3       # weak |onset - anchor| tiebreak for hard-anchor claims
# soft-anchor time priors, per anchor class (slope per s, cap) x (late, early).
# 'soft' = unbiased evidence (ison-change events today; syllable-acoustic
# anchors later): symmetric. 'soft_biased' = melisma-LATE-biased evidence
# (whisper word onsets): claiming later than the anchor is suspicious,
# earlier is normal. All capped so one bad anchor can't veto local evidence.
# per kind: (dead zone s, (late slope, late cap), (early slope, early cap))
SOFT_SHAPE = {
    'soft':        (0.45, (1.20, 2.5), (1.20, 2.5)),
    'soft_biased': (0.35, (0.25, 1.0), (0.15, 0.5)),
}
# flat fee for NOT claiming a soft-anchored slot, so a path can't dodge a
# soft prior by leaving the slot unclaimed (per anchor kind)
SOFT_SKIP = {'soft': 0.7, 'soft_biased': 0.2}
BREATH_GAP = 0.14   # gap_before >= this = breath (tempo reset)
TEMPO_WIN = 4       # moving-average window (claimed-slot intervals)
MAX_SKIP_S = 6      # max consecutive skipped slots in one DP transition
MAX_SKIP_N = 8      # max consecutive skipped notes in one DP transition
SPB_CLAMP = (0.2, 3.0)
ITERS = 3
# ASR word anchors known-bad on this piece (scrambled feed-cluster, v1 DROP)
DROP_WI = {21, 22, 23, 24, 25, 92, 93, 94, 95, 99, 100, 70, 71, 72, 73}

# ---- inputs ----
sn = json.load(open('score_notes.json'))
notes, anchors_raw = sn['notes'], sn['anchors']
mods = json.load(open('modifiers.json'))
wt = json.load(open('word_times.json'))       # used ONLY for the piece-start anchor
vn_raw = json.load(open('voice_notes3.json'))
bars_j = json.load(open('barlines.json'))
mor = np.load('moria_track.npy')
rms = np.load('rms_track.npy')
EXPECTED = json.load(open('expected_degrees.json'))   # absolute degree per slot (martyria-closed)
# learned per-glyph intervals: second movement hypothesis (meta ground truth
# preferred — datasets/mcr/*.meta.json learned_ez_intervals — else v1's table)
LEARNED = json.load(open('learned_intervals_meta.json'
                         if os.path.exists('learned_intervals_meta.json')
                         else 'learned_intervals.json'))
_ison_ev = json.load(open('ison_timeline.json'))
N = len(notes)

# ---- voice-note cleaning (v1, chanter-verified) ----
def _ison_at(t):
    lv = _ison_ev[0][1]
    for et, el in _ison_ev:
        if et <= t + 0.5: lv = el
        else: break
    return lv
def _level(v):
    seg = rms[int(v[0]*100):max(int(v[0]*100)+2, int(v[1]*100))]
    return float(np.mean(seg)) if len(seg) else 0.0
def note_pitch(t0, t1):
    seg = mor[int((t0+0.03)*100):max(int((t0+0.03)*100)+2, int((t1-0.02)*100))]
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if len(seg) else None
def _pitch(v): return note_pitch(v[0], v[1])
vn = []
for v in vn_raw:
    dur = v[1] - v[0]
    p = _pitch(v)
    prevp = _pitch(vn[-1]) if vn else None
    lv = _ison_at(v[0])
    quiet = vn and _level(v) < 0.45 * max(_level(vn[-1]), 1e-6)
    bleed = (quiet and lv != 'M' and p is not None and abs(p - lv) < 4.5
             and prevp is not None and abs(p - prevp) > 15 and dur < 0.5)
    if vn and (dur < 0.16 or bleed):
        vn[-1][1] = v[1]
    else:
        vn.append(list(v))
print(f"note stream cleaned: {len(vn_raw)} -> {len(vn)}")
VP = [_pitch(v) for v in vn]
END_T = max(v[1] for v in vn)

# ---- slots with sub-note expansion (v1, chanter-verified) ----
gor = [False]*N; dur = [1.0]*N
for m in mods:
    if m['cp'] in GORGON or m['cp'] in DURATION_CP:
        best, bd = None, 30
        for j, g in enumerate(notes):
            if g['line'] != m['line']: continue
            d = max(g['x0'] - m['x'], m['x'] - g['x1'], 0)
            if d < bd: best, bd = j, d
        if best is not None:
            if m['cp'] in GORGON: gor[best] = True
            else: dur[best] = max(dur[best], DURATION_CP[m['cp']])
slot_gi, slot_w, slot_sub = [], [], []
for j, g in enumerate(notes):
    w = dur[j]
    if g['cp'] == YPORRHOE or g['cp'] in KENTIMATA_COMPOUNDS:
        pieces = [w*0.5, w*0.5]
    elif g['cp'] == SYNELAF:
        if gor[j]:
            pieces = [1.0, w]
        else:
            pieces = [0.5, w]
            if slot_w: slot_w[-1] = max(0.5, slot_w[-1] - 0.5)
    else:
        pieces = [w]
    if gor[j]:
        pieces[0] = 0.5
        if slot_w: slot_w[-1] = max(0.5, slot_w[-1] - 0.5)
    for si, p in enumerate(pieces):
        p = SUBW_OVR.get((j, si), WEIGHT_OVR.get(j, p) if len(pieces) == 1 else p)
        slot_gi.append(j); slot_w.append(p); slot_sub.append(si)
S = len(slot_gi)
assert len(EXPECTED) == S, f"expected_degrees ({len(EXPECTED)}) != slots ({S})"
first_slot = {}
for s in range(S): first_slot.setdefault(slot_gi[s], s)
CW = [0.0]*(S+1)
for s in range(S): CW[s+1] = CW[s] + slot_w[s]
def beats(a, b): return CW[b] - CW[a]
dmov = [0] + [EXPECTED[s] - EXPECTED[s-1] for s in range(1, S)]   # expected movement into slot s
SLOT_SKIP = [SKIP_SLOT_STATIC if dmov[s] == 0 else SKIP_SLOT_MOVE for s in range(S)]
# second hypothesis: per-glyph learned movement (falls back to the degree delta)
lmov = [0] + [LEARNED.get(f"{hex(notes[slot_gi[s]]['cp'])}.{slot_sub[s]}", dmov[s])
              for s in range(1, S)]
LS = [0.0]*(S+1)
for s in range(S): LS[s+1] = LS[s] + lmov[s]
def mv_cost(obs, s_from, s_to):
    """movement cost: sung delta vs the better of (degree-delta, learned) readings"""
    e1 = EXPECTED[s_to] - EXPECTED[s_from]
    e2 = LS[s_to+1] - LS[s_from+1]
    return W_MV * min(min(abs(obs - e1), abs(obs - e2)), MV_CAP)
BOUNDARY = {first_slot[b['next_glyph']] for b in bars_j if b['next_glyph'] is not None}

# learned-interval consistency cross-check (expected movement source is dmov)
agree = tot = 0
for s in range(1, S):
    key = f"{hex(notes[slot_gi[s]]['cp'])}.{slot_sub[s]}"
    if key in LEARNED:
        tot += 1; agree += (LEARNED[key] == dmov[s])
print(f"movement source: expected_degrees deltas; learned_intervals agree on "
      f"{agree}/{tot} covered slots")

# ---- anchors: generic (slot_index, time, kind) list ----
# hard anchors partition the alignment; soft anchors are weak, capped in-DP
# time priors. Today: MANUAL pins (+ piece start/end) are hard; the soft tier
# is whisper word onsets (this piece's only dense timing source, ASR-biased so
# weight is low and capped). Dense syllable-acoustic anchors (design addendum
# 2026-08-17) land in this same list without interface changes.
_start_guess = wt[0]['t0']
_start = min((v[0] for v in vn if abs(v[0] - _start_guess) < 0.6),
             key=lambda t: abs(t - _start_guess), default=_start_guess)
ANCHORS = [(0, _start, 'hard')]
ANCHORS += [(first_slot[g], t, 'hard') for g, t in MANUAL]
ANCHORS += [(S, min(END_T, 271.5), 'hard')]
_hard_slots = {s for s, t, k in ANCHORS}
HARD = sorted((s, t) for s, t, k in ANCHORS)
def _hard_span(s):
    for (sa, ta), (sb, tb) in zip(HARD, HARD[1:]):
        if sa <= s < sb: return ta, tb
    return HARD[0][1], HARD[-1][1]
n_bad = 0
def add_soft(s, t, kind):
    global n_bad
    if s in _hard_slots: return
    ta, tb = _hard_span(s)
    if not (ta - 1.0 <= t <= tb + 1.0):
        n_bad += 1; return        # soft anchor contradicts the hard partition
    ANCHORS.append((s, t, kind))
# whisper word onsets: dense but melisma-late-biased
for wi, (a, b) in enumerate(zip(anchors_raw, wt)):
    if wi in DROP_WI: continue
    add_soft(first_slot[a['gi']], b['t0'], 'soft_biased')
# ison-change events (meta ground truth): score red letters give the glyph,
# the timeline gives the performance time — unbiased soft anchors
ISON_CP = {0xf043: 0, 0xf063: 0, 0xf056: 12, 0xf076: 12, 0xf042: 22,
           0xf04e: 30, 0xf06e: 30, 0xf06d: 42, 0xf04d: 42, 0xf03f: 'M', 0xf02f: 'M'}
if os.path.exists('ison_events_meta.json') and os.path.exists('red_special.json'):
    ev_meta = json.load(open('ison_events_meta.json'))
    letters = []
    for m in json.load(open('red_special.json')):
        cp = int(m['cp'], 16)
        if cp not in ISON_CP: continue
        gj = min((j for j, g in enumerate(notes) if g['line'] == m['line']),
                 key=lambda j: abs((notes[j]['x0']+notes[j]['x1'])/2 - m['x']))
        letters.append((ISON_CP[cp], gj))
    li, cur, n_ison = 0, None, 0
    for t, lvl in ev_meta:
        while li < len(letters) and letters[li][0] == cur and letters[li][0] != lvl:
            li += 1               # redundant restatement of the current level
        if li >= len(letters) or letters[li][0] != lvl: break
        add_soft(first_slot[letters[li][1]], t, 'soft')
        cur = lvl; li += 1; n_ison += 1
else:
    n_ison = 0
ANCHORS.sort(key=lambda a: a[0])
SOFT = {}                          # slot -> [(time, kind), ...]
for s, t, k in ANCHORS:
    if k != 'hard': SOFT.setdefault(s, []).append((t, k))
print(f"anchors: {len(HARD)} hard (partition), "
      f"{sum(len(v) for v in SOFT.values())} soft "
      f"({n_ison} ison-matched, {n_bad} dropped as span-inconsistent)")

def virtual_pitch(t):
    seg = mor[int((t+0.03)*100):int((t+0.30)*100)]
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if len(seg) else None

# ---- piecewise tempo ----
def build_curve(events):
    """events: [(t, slot, note_k or None)] chronological, claimed/pinned only.
    Returns step curve [(t, spb or None)]; None = reset (fall back to span default)."""
    curve, win, prev = [], deque(maxlen=TEMPO_WIN), None
    for (t, s, k) in events:
        if prev is not None:
            t0, s0, _ = prev
            db = beats(s0, s)
            breath = (k is not None and vn[k][3] >= BREATH_GAP)
            if breath or s in BOUNDARY:
                win.clear(); curve.append((t, None))
            elif db > 1e-6 and t > t0 + 1e-6:
                win.append(min(max((t - t0)/db, SPB_CLAMP[0]), SPB_CLAMP[1]))
                curve.append((t, sum(win)/len(win)))
        prev = (t, s, k)
    return curve
def spb_lookup(t, curve, default):
    v = default
    for ct, cv in curve:
        if ct <= t: v = cv if cv is not None else default
        else: break
    return v

# ---- per-span DP: slots claim notes; movement + duration + skip costs ----
def align_span(sa, ta, sb, tb, prev_ev, spb_fn, last_span):
    span = list(range(sa, sb)); J = len(span)
    hi = END_T + 1.0 if last_span else tb - W_PIN
    elig = [k for k in range(len(vn)) if ta - W_PIN <= vn[k][0] < hi]
    K0 = [k for k in elig if abs(vn[k][0] - ta) <= W_PIN]
    NL = []                       # (t, pitch, gap, global_k)
    if K0:
        NL = [(vn[k][0], VP[k], vn[k][3], k) for k in elig]
        k0set = {elig.index(k) for k in K0}
    else:                         # no onset near the hard anchor: virtual event
        NL = [(ta, virtual_pitch(ta), 0.0, None)]
        NL += [(vn[k][0], VP[k], vn[k][3], k) for k in elig if vn[k][0] > ta]
        k0set = {0}
    K = len(NL)
    # slot-skip prefix cost over the span (soft-anchored slots aren't free to skip)
    ss_pre = [0.0]*(J+1)
    for j in range(J):
        fee = sum(SOFT_SKIP[kind] for _, kind in SOFT.get(span[j], ()))
        ss_pre[j+1] = ss_pre[j] + SLOT_SKIP[span[j]] + fee
    BIG = 1e18
    D = [[BIG]*K for _ in range(J)]
    P = [[None]*K for _ in range(J)]
    p_prev = prev_ev[2] if prev_ev else None
    s_prev = prev_ev[1] if prev_ev else None
    for k in k0set:
        c = PIN_TIE * abs(NL[k][0] - ta)
        if p_prev is not None and NL[k][1] is not None and s_prev is not None:
            c += mv_cost((NL[k][1] - p_prev) / MPS, s_prev, sa)
        D[0][k] = c
    for j in range(1, J):
        s = span[j]
        soft = SOFT.get(s)
        for k in range(1, K):
            t_k, p_k, gap_k, _ = NL[k]
            breath = gap_k >= BREATH_GAP
            best, barg = BIG, None
            for j2 in range(max(0, j-1-MAX_SKIP_S), j):
                row = D[j2]
                B = beats(span[j2], s)
                skip_s = ss_pre[j] - ss_pre[j2+1]
                for k2 in range(max(0, k-1-MAX_SKIP_N), k):
                    base = row[k2]
                    if base >= BIG: continue
                    t_kp, p_kp = NL[k2][0], NL[k2][1]
                    spb = spb_fn(t_kp)
                    impl = (t_k - t_kp) / spb
                    c = base + skip_s + SKIP_NOTE*(k-k2-1)
                    c += DUR_DEFICIT * max(0.0, 0.75*B - impl)
                    if not breath:
                        c += DUR_SURPLUS * max(0.0, impl - 1.8*B)
                    # graded reward when the onset lands where the beats predict
                    c -= CLAIM_BONUS * max(0.0, 1.0 - abs(impl - B)/(0.6*B + 0.25))
                    if p_k is not None and p_kp is not None:
                        c += mv_cost((p_k - p_kp) / MPS, span[j2], s)
                    else:
                        c += MV_NOPITCH
                    if c < best: best, barg = c, (j2, k2)
            if soft is not None and best < BIG:
                for st, kind in soft:
                    dt = t_k - st
                    dead, late, early = SOFT_SHAPE[kind]
                    sl, cap = late if dt > 0 else early
                    best += min(sl * max(0.0, abs(dt) - dead), cap)
            D[j][k] = best; P[j][k] = barg
    # terminal: any (j,k); remaining slots skipped + tail duration to the next hard anchor
    near_pin = min(vn, key=lambda v: abs(v[0] - tb), default=None)
    breath_pin = last_span or (near_pin is not None and abs(near_pin[0]-tb) <= W_PIN
                              and near_pin[3] >= BREATH_GAP)
    best, barg = BIG, None
    for j in range(J):
        for k in range(K):
            if D[j][k] >= BIG: continue
            t_k = NL[k][0]
            B = beats(span[j], sb)
            spb = spb_fn(t_k)
            impl = (tb - t_k) / spb
            c = D[j][k] + (ss_pre[J] - ss_pre[j+1]) + SKIP_NOTE_TAIL*(K-1-k)
            c += DUR_DEFICIT * max(0.0, 0.75*B - impl)
            if not breath_pin:
                c += DUR_SURPLUS * max(0.0, impl - 1.8*B)
            if c < best: best, barg = c, (j, k)
    ev = []
    j, k = barg
    while j is not None:
        t_k, p_k, _, gk = NL[k]
        ev.append((t_k, span[j], gk, p_k))
        nxt = P[j][k]
        if j == 0 or nxt is None: break
        j, k = nxt
    ev.reverse()
    return ev

# ---- iterate: DTW <-> piecewise tempo ----
curve = None
events = []
for it in range(ITERS):
    events, prev_ev = [], None
    for (sa, ta), (sb, tb) in zip(HARD, HARD[1:]):
        default = (tb - ta) / max(beats(sa, sb), 1e-6)
        if curve is None:
            spb_fn = lambda t, d=default: d
        else:
            spb_fn = lambda t, d=default, c=curve: spb_lookup(t, c, d)
        ev = align_span(sa, ta, sb, tb, prev_ev, spb_fn, last_span=(sb == S))
        events += ev
        prev_ev = (ev[-1][0], ev[-1][1], ev[-1][3]) if ev else prev_ev
    curve = build_curve([(t, s, k) for t, s, k, _ in events])
    mvda = []
    for (t0, s0, k0, p0), (t1, s1, k1, p1) in zip(events, events[1:]):
        if p0 is None or p1 is None: continue
        obs = (p1 - p0)/MPS
        mvda.append(min(abs(obs - (EXPECTED[s1] - EXPECTED[s0])),
                        abs(obs - (LS[s1+1] - LS[s0+1]))))
    claimed = sum(1 for _, _, k, _ in events if k is not None)
    print(f"iter {it}: claimed {claimed}/{S} slots "
          f"({100*claimed/S:.0f}%), movement-cost mean {np.mean(mvda):.2f} steps "
          f"over {len(mvda)} claimed pairs")

# ---- display times: performance-time interpolation only ----
claim = [None]*S
t_slot = [None]*S
for t, s, k, _ in events:
    t_slot[s] = t
    if k is not None: claim[s] = k
bracket = [(t, s) for t, s, _, _ in events] + [(HARD[-1][1], S)]
for (t0, s0), (t1, s1) in zip(bracket, bracket[1:]):
    if s1 <= s0: continue
    for s in range(s0+1, min(s1, S)):
        f = beats(s0, s) / max(beats(s0, s1), 1e-6)
        t_slot[s] = t0 + f * (t1 - t0)
last = 0.0
for s in range(S):
    if t_slot[s] is None: t_slot[s] = last + 0.2
    t_slot[s] = max(t_slot[s], last + 0.02); last = t_slot[s]

# ---- outputs (v1 formats) ----
json.dump({'t': [round(t, 3) for t in t_slot], 'gi': slot_gi, 'sub': slot_sub},
          open('slots.json', 'w'))
json.dump(claim, open('slot_claims.json', 'w'))

claimed_set = {c for c in claim if c is not None}
orn = []
for k, v in enumerate(vn):
    if k in claimed_set or not (0.15 <= v[1]-v[0] <= 0.50) or v[0] < HARD[0][1]: continue
    gi = 0
    for s in range(S):
        if t_slot[s] <= v[0]: gi = slot_gi[s]
        else: break
    if orn and orn[-1][2] == gi and v[0]-orn[-1][1] < 0.35: orn[-1][1] = round(v[1], 2)
    else: orn.append([round(v[0], 2), round(v[1], 2), gi])
json.dump(orn, open('ornaments.json', 'w'))

tj = json.load(open('timing.json'))
starts_w = [t_slot[first_slot[anchors_raw[i]['gi']]] for i in range(len(anchors_raw))]
ptr = 0
for cap in tj['captions']:
    for wd in cap['words']:
        t0 = starts_w[ptr]
        t1 = starts_w[ptr+1] if ptr+1 < len(starts_w) else min(t0+3.0, END_T)
        wd['t0'] = round(t0, 2); wd['t1'] = round(max(t1, t0+0.15), 2)
        ptr += 1
    cap['t0'] = cap['words'][0]['t0']; cap['t1'] = cap['words'][-1]['t1']
lt = []
for li in range(18):
    gi = min(i for i, g in enumerate(notes) if g['line'] == li)
    lt.append(round(t_slot[first_slot[gi]], 2))
for i in range(1, 18):
    if lt[i] <= lt[i-1]: lt[i] = lt[i-1] + 0.5
tj['line_times'] = lt
json.dump(tj, open('timing.json', 'w'), indent=1)
print(f"{len(orn)} ornaments; slots {S}; timing.json rewritten")

# ================= eval report =================
print("\n---- pins (hard anchors) ----")
v1 = json.load(open('slots_v1.json')) if os.path.exists('slots_v1.json') else None
for g, tp in MANUAL:
    s = first_slot[g]
    tv = t_slot[s]
    d = tv - tp
    v1t = v1['t'][s] if v1 else float('nan')
    ok = abs(d) <= 0.3 or (v1 and abs(tv - v1t) <= 0.3)
    print(f"  gi{g:>3} slot{s:>3}  pin {tp:7.2f}  v2 {tv:7.2f}  d={d:+.2f}  "
          f"v1 {v1t:7.2f}  {'claimed' if claim[s] is not None else 'virtual'}  "
          f"{'PASS' if ok else 'FAIL'}")

print("\n---- Savior run (slots 65..72; pin 61.0 -> 'ior' 65.0) ----")
sav = list(range(first_slot[56], first_slot[62]+1))
n_cl = 0
for s in sav:
    cl = claim[s] is not None
    n_cl += cl
    tenth = abs(t_slot[s]*2 - round(t_slot[s]*2)) < 1e-9
    grid_flag = tenth and not cl and s not in _hard_slots
    print(f"  slot{s} gi{slot_gi[s]}.{slot_sub[s]} w={slot_w[s]}  t={t_slot[s]:.2f}  "
          f"{'CLAIMED k='+str(claim[s]) if cl else ('pin' if s in _hard_slots else 'interp')}"
          f"{'  [exact-half GRID?]' if grid_flag else ''}")
print(f"  -> {n_cl}/{len(sav)} of the Savior slots claimed real onsets")

print("\n---- region echoes (meta caveats) ----")
def echo(label, gis):
    xs = [f"{t_slot[first_slot[g]]:.2f}" for g in gis]
    print(f"  {label}: " + " ".join(xs))
echo("rec melisma 54->58 (gi49..52)", [49, 50, 51, 52])
echo("'of'/'the' (gi76,77)", [76, 77])
echo("Wherefore (gi118)", [118])
echo("feed2/My (gi150,157)", [150, 157])
echo("preserve (gi218)", [218])
echo("that (gi249)", [249])

print("\n---- per-span tempo ----")
for (sa, ta), (sb, tb) in zip(HARD, HARD[1:]):
    samples, resets = [], 0
    prev = None
    for t, s, k, _ in events:
        if not (sa <= s < sb): continue
        if prev is not None:
            db = beats(prev[1], s)
            if (k is not None and vn[k][3] >= BREATH_GAP) or s in BOUNDARY:
                resets += 1
            elif db > 1e-6 and t > prev[0]:
                samples.append((t - prev[0]) / db)
        prev = (t, s)
    if samples:
        print(f"  span slot{sa:>3}..{sb:<3} t {ta:6.1f}-{tb:6.1f}: "
              f"spb median {np.median(samples):.2f} "
              f"range [{min(samples):.2f},{max(samples):.2f}] "
              f"n={len(samples)} resets={resets}")

if v1:
    print("\n---- 15 largest |t_v2 - t_v1| ----")
    diffs = sorted(range(S), key=lambda s: -abs(t_slot[s] - v1['t'][s]))[:15]
    for s in sorted(diffs, key=lambda s: t_slot[s]):
        print(f"  slot{s:>3} gi{slot_gi[s]:>3}.{slot_sub[s]}  "
              f"v1 {v1['t'][s]:7.2f} -> v2 {t_slot[s]:7.2f}  "
              f"d={t_slot[s]-v1['t'][s]:+.2f}  "
              f"{'claimed' if claim[s] is not None else 'interp'}")
