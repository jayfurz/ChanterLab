#!/usr/bin/env python3
"""v5: pitch-aware alignment.
- compound kentimata glyphs expand to two ascending slots (user primer rule)
- DTW assignment per anchor span: time prior + expected-vs-sung interval cost
- EM: relearn per-(cp,subslot) intervals from alignment, iterate
-> slots.json, note-level dataset fields, ornaments.json, timing.json"""
import json, math
import numpy as np

GORGON = {0xf053, 0xf048}   # plain + red dotted gorgon (0xf022 = antikenoma: quality only, no time)
DURATION_CP = {0xf061: 2.0, 0xf041: 2.0, 0xf027: 2.0, 0xf06b: 3.0}   # 0xf03a reverted: two-dot apli is phrase-final only (chanter); its identity is unresolved
WEIGHT_OVR = {53: 2.0, 59: 0.5, 82: 1.0}   # chanter: post-tion apostrofos carries apli; Savior halves; 'might' Ke=1
SUBW_OVR = {(58, 1): 0.5}             # Savior run: second note of the 0xf050 pair is a half too
YPORRHOE, SYNELAF = 0xf05f, 0xf050
KENTIMATA_COMPOUNDS = {0xf0d7, 0xf06f, 0xf077, 0xf04f}   # oligon/petasti + kentimata above: 2 notes up
MANUAL = [(49, 54.0), (52, 58.0), (56, 61.0), (62, 65.0), (76, 76.0), (77, 77.5),
          (118, 119.0), (150, 154.0), (157, 157.0), (218, 220.97), (249, 253.0)]   # user-ear ground truth: the ONLY hard tier ('Wherefore' at 1:59)
DROP = {21,22,23,24,25, 92,93,94,95, 99,100, 70,71,72,73}   # + scrambled 'feed My, feed My sheep' ASR cluster
MPS = 10.3   # avg moria per diatonic step

sn = json.load(open('score_notes.json'))
notes, anchors_raw = sn['notes'], sn['anchors']
mods = json.load(open('modifiers.json'))
wt = json.load(open('word_times.json'))
vn = json.load(open('voice_notes3.json'))
# clean the note stream for alignment: phantom fragments and ison-bleed notes
# (a jump to the current ison level for <0.5s) merge into their predecessor
_ison_ev = json.load(open('ison_timeline.json'))
def _ison_at(t):
    lv = _ison_ev[0][1]
    for et, el in _ison_ev:
        if et <= t + 0.5: lv = el
        else: break
    return lv
import numpy as _np
_mor0 = _np.load('moria_track.npy')
_rms0 = _np.load('rms_track.npy')
def _level(v):
    seg = _rms0[int(v[0]*100):max(int(v[0]*100)+2, int(v[1]*100))]
    return float(_np.mean(seg)) if len(seg) else 0.0
def _pitch(v):
    seg = _mor0[int((v[0]+0.03)*100):max(int((v[0]+0.03)*100)+2, int((v[1]-0.02)*100))]
    seg = seg[~_np.isnan(seg)]
    return float(_np.median(seg)) if len(seg) else None
_clean = []
for v in vn:
    dur = v[1] - v[0]
    p = _pitch(v)
    prevp = _pitch(_clean[-1]) if _clean else None
    lv = _ison_at(v[0])
    quiet = _clean and _level(v) < 0.45 * max(_level(_clean[-1]), 1e-6)
    bleed = (quiet and lv != 'M' and p is not None and abs(p - lv) < 4.5
             and prevp is not None and abs(p - prevp) > 15 and dur < 0.5)
    if _clean and (dur < 0.16 or bleed):
        _clean[-1][1] = v[1]          # absorb into predecessor
    else:
        _clean.append(list(v))
print(f"note stream cleaned: {len(vn)} -> {len(_clean)}")
vn = _clean
bars_j = json.load(open('barlines.json'))
mor = np.load('moria_track.npy')
EXPECTED = json.load(open('expected_degrees.json'))    # absolute degree per slot (martyria-closed)
STEP_POS = [-18,-8,0,12,22,30,42,54,64,72,84]
STEP_DEG = [-2,-1,0,1,2,3,4,5,6,7,8]
def sung_degree(m, t):
    if m is None: return None
    if t < 19.8: m -= 3.5
    elif t < 21.8: m -= 3.5*(21.8-t)/2.0
    k = min(range(len(STEP_POS)), key=lambda i: abs(STEP_POS[i]-m))
    return STEP_DEG[k]
# soft breath evidence: onset time -> strength from gap duration (never a hard pin)
BREATH = {round(v[0],2): min(1.0, 2.5*v[3]) for v in vn if v[3] >= 0.12 and v[0] > 3}
def breath_bonus(t):
    for bt, s in BREATH.items():
        if abs(t - bt) < 0.06: return s
    return 0.0
N = len(notes)
END_T = max(v[1] for v in vn)

def note_pitch(t0, t1):
    seg = mor[int((t0+0.03)*100):max(int((t0+0.03)*100)+2, int((t1-0.02)*100))]
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if len(seg) else None
VP = [note_pitch(v[0], v[1]) for v in vn]      # per voice-note sung moria
VDEG = [sung_degree(VP[k], vn[k][0]) for k in range(len(vn))]

# ---- modifiers ----
gor = [False]*N; dur = [1.0]*N
for m in mods:
    if m['cp'] in GORGON or m['cp'] in DURATION_CP:
        best, bd = None, 30
        for j, g in enumerate(notes):
            if g['line'] != m['line']: continue
            # interval distance: a mark's origin may sit at either edge of its glyph
            d = max(g['x0'] - m['x'], m['x'] - g['x1'], 0)
            if d < bd: best, bd = j, d
        if best is not None:
            if m['cp'] in GORGON: gor[best] = True
            else: dur[best] = max(dur[best], DURATION_CP[m['cp']])

# ---- slots with sub-note expansion ----
slot_gi, slot_w, slot_sub = [], [], []
for j, g in enumerate(notes):
    w = dur[j]
    if g['cp'] == YPORRHOE or g['cp'] in KENTIMATA_COMPOUNDS:
        pieces = [w*0.5, w*0.5]
    elif g['cp'] == SYNELAF:
        # syndesmos elaphron = two apostrophoi; the gorgon-on-first is usually
        # WRITTEN in the score (handled by normal gorgon attachment below) —
        # only bake it in when no explicit gorgon is attached to this glyph
        if gor[j]:
            pieces = [1.0, w]
        else:
            pieces = [0.5, w]
            if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)
    else:
        pieces = [w]
    if gor[j]:
        pieces[0] = 0.5
        if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)
    for si, p in enumerate(pieces):
        p = SUBW_OVR.get((j, si), WEIGHT_OVR.get(j, p) if len(pieces) == 1 else p)
        slot_gi.append(j); slot_w.append(p); slot_sub.append(si)
S = len(slot_gi)
first_slot = {}
for s in range(S): first_slot.setdefault(slot_gi[s], s)
def beats(s0, s1): return sum(slot_w[s0:s1]) or 0.001
TOTB = beats(0, S)
onsets = [v[0] for v in vn]

# ---- anchors (same as v4) ----
def build_anchors(pins, drop_wi=()):
    A = []; PIN = []
    for wi, (a, b) in enumerate(zip(anchors_raw, wt)):
        if wi in drop_wi: continue
        t, s = b['t0'], first_slot[a['gi']]
        if A and (t <= A[-1][0] + 0.05 or s <= A[-1][1]): continue
        A.append([t, s, b['w']]); PIN.append(False)
    for s, t in pins:
        A.append([t, s, 'pin']); PIN.append(True)
    order = sorted(range(len(A)), key=lambda i: (A[i][1], A[i][0]))
    A = [A[i] for i in order]; PIN = [PIN[i] for i in order]
    keep = []
    for i in range(len(A)):
        while keep and (A[i][0] <= A[keep[-1]][0] + 0.05 or A[i][1] <= A[keep[-1]][1]):
            if PIN[i] and not PIN[keep[-1]]: keep.pop()
            else: break
        if keep and (A[i][0] <= A[keep[-1]][0] + 0.05 or A[i][1] <= A[keep[-1]][1]):
            if not PIN[i]: continue
            else: break
        keep.append(i)
    A = [A[i] for i in keep]; PIN = [PIN[i] for i in keep]
    A.append([min(END_T, 271.5), S, '<end>']); PIN.append(True)
    return A, PIN

def jump_bonus(slot_idx, h, table):
    e = exp_interval(slot_idx, table)
    if e is None or abs(e) < 2: return 0.0
    k = next((i for i, v in enumerate(vn) if abs(v[0] - h) < 0.06), None)
    if k is None or k == 0: return 0.0
    p1, p0 = VP[k], VP[k-1]
    if p1 is None or p0 is None: return 0.0
    obs = (p1 - p0) / MPS
    return 0.8 if abs(obs - e) <= 0.7 else 0.0

def refine(A, PIN, T0, table=None, passes=3):
    for _ in range(passes):
        changed = 0
        for i in range(1, len(A)-1):
            if PIN[i]: continue
            tp, sp = A[i-1][0], A[i-1][1]
            t, s = A[i][0], A[i][1]
            tn, sn_ = A[i+1][0], A[i+1][1]
            bl, br = beats(sp, s), beats(s, sn_)
            def cost(h):
                TL, TR = (h-tp)/bl, (tn-h)/br
                if TL <= 0.05 or TR <= 0.05: return 99
                return abs(math.log(TL/T0)) + abs(math.log(TR/T0)) + 0.12*abs(h-t)
            jb0 = jump_bonus(s, t, table) if table else 0.0
            best, bc = t, cost(t) - breath_bonus(t) - jb0
            for h in onsets:
                if not (tp + 0.15 < h < tn - 0.15): continue
                jb = jump_bonus(s, h, table) if table else 0.0
                reach = 3.5 if (breath_bonus(h) > 0.3 or jb > 0) else 1.3
                if abs(h-t) > reach: continue
                c = cost(h) - breath_bonus(h) - jb
                if c < bc - 1e-6: best, bc = h, c
            if best != t: A[i][0] = best; changed += 1
        if not changed: break
    return A

def exp_interval(j, table):
    key = (notes[slot_gi[j]]['cp'], slot_sub[j])
    return table.get(key)

def dtw_assign(A, table):
    """per span: monotone DP matching slots to voice notes with time+pitch costs"""
    t_slot = [None]*S; claim = [None]*S
    for (ta, sa, _), (tb, sb, _) in zip(A, A[1:]):
        span = list(range(sa, sb))
        if not span: continue
        V = [k for k, v in enumerate(vn) if ta - 0.03 <= v[0] < tb - 0.03]
        B = beats(sa, sb); cum = 0.0; targ = []
        for s in span: targ.append(ta + (cum/B)*(tb-ta)); cum += slot_w[s]
        spb = (tb - ta) / B                      # local seconds per beat
        J, K = len(span), len(V)
        if K == 0:
            for s, tg in zip(span, targ): t_slot[s] = tg
            continue
        BIG = 1e9
        # D[j][k]: min cost with slot j claiming note k; also D_un[j]: slot j unclaimed
        D = [[BIG]*K for _ in range(J)]
        Bk = [[None]*K for _ in range(J)]
        edeg0 = EXPECTED[span[0]]
        for k in range(K):
            pc0 = 1.3*min(abs(VDEG[V[k]] - edeg0), 3) if VDEG[V[k]] is not None else 0.6
            D[0][k] = 0.65*abs(vn[V[k]][0] - targ[0]) + pc0 + 0.3*k
        for j in range(1, J):
            e = exp_interval(span[j], table)
            edeg = EXPECTED[span[j]]
            for k in range(K):
                base_t = 0.65*abs(vn[V[k]][0] - targ[j])          # time demoted to weak prior
                pc = 1.3*min(abs(VDEG[V[k]] - edeg), 3) if VDEG[V[k]] is not None else 0.6
                bb = breath_bonus(vn[V[k]][0]) if span[j] in BOUNDARY else 0.0
                for kp in range(k):
                    if D[j-1][kp] >= BIG: continue
                    # duration guard: previous slot must live ~60% of its beats
                    impl = (vn[V[k]][0] - vn[V[kp]][0]) / spb
                    deficit = max(0.0, 0.75*slot_w[span[j-1]] - impl)
                    surplus = max(0.0, impl - 1.8*slot_w[span[j-1]])
                    c = D[j-1][kp] + base_t + pc + 0.3*(k-kp-1) - 1.4*bb + 2.2*deficit + 0.5*surplus
                    if e is not None and VP[V[k]] is not None and VP[V[kp]] is not None:
                        obs = (VP[V[k]] - VP[V[kp]]) / MPS
                        c += 0.3 * min(abs(obs - e), 3.0)
                    if c < D[j][k]: D[j][k] = c; Bk[j][k] = kp
        k_end = int(np.argmin(D[J-1]))
        if D[J-1][k_end] >= BIG:
            for s, tg in zip(span, targ): t_slot[s] = tg
            continue
        path = [k_end]
        for j in range(J-1, 0, -1):
            path.append(Bk[j][path[-1]])
        path.reverse()
        for j, k in enumerate(path):
            if k is None:
                t_slot[span[j]] = targ[j]
            else:
                t_slot[span[j]] = vn[V[k]][0]; claim[span[j]] = V[k]
    last = 0.0
    for s in range(S):
        if t_slot[s] is None: t_slot[s] = last + 0.2
        t_slot[s] = max(t_slot[s], last + 0.02); last = t_slot[s]
    return t_slot, claim

def learn(t_slot, claim):
    from collections import defaultdict
    by = defaultdict(list)
    for j in range(1, S):
        if claim[j] is None or claim[j-1] is None: continue
        p1, p0 = VP[claim[j]], VP[claim[j-1]]
        if p1 is None or p0 is None or abs(p1-p0) > 55: continue
        by[(notes[slot_gi[j]]['cp'], slot_sub[j])].append((p1-p0)/MPS)
    table = {}
    for k, v in by.items():
        if len(v) >= 2: table[k] = round(float(np.median(v)))
    return table

# boundary slots: first slot after each barline (candidate breath sites, soft)
BOUNDARY = {first_slot[b['next_glyph']] for b in bars_j if b['next_glyph'] is not None}
pins = [(first_slot[g], t) for g, t in MANUAL]
A, PIN = build_anchors(pins, DROP)
T0 = (A[-1][0] - A[0][0]) / TOTB
A = refine(A, PIN, T0)

table = {}
for it in range(3):
    t_slot, claim = dtw_assign(A, table)
    table = learn(t_slot, claim)
    if it == 0:
        A = refine(A, PIN, T0, table=table)   # second refine pass with pitch evidence
    # agreement metric
    errs = []
    for j in range(1, S):
        e = exp_interval(j, table)
        if e is None or claim[j] is None or claim[j-1] is None: continue
        if VP[claim[j]] is None or VP[claim[j-1]] is None: continue
        errs.append(abs((VP[claim[j]] - VP[claim[j-1]])/MPS - e))
    print(f"iter {it}: learned {len(table)} (cp,sub) intervals, "
          f"claimed {sum(c is not None for c in claim)}/{S}, "
          f"interval MAE {np.mean(errs):.2f} steps over {len(errs)}")

json.dump({'t': [round(t,3) for t in t_slot], 'gi': slot_gi, 'sub': slot_sub},
          open('slots.json','w'))
json.dump({f"{hex(k[0])}.{k[1]}": v for k, v in sorted(table.items())},
          open('learned_intervals.json','w'))
json.dump([claim[j] for j in range(S)], open('slot_claims.json','w'))
print("\nlearned interval table:")
for k, v in sorted(table.items()):
    print(f"  {hex(k[0])} sub{k[1]}: {v:+d}")

# ---- ornaments (unclaimed quick notes) ----
claimed_set = {c for c in claim if c is not None}
orn = []
for k, v in enumerate(vn):
    if k in claimed_set or not (0.15 <= v[1]-v[0] <= 0.50) or v[0] < A[0][0]: continue
    gi = 0
    for s in range(S):
        if t_slot[s] <= v[0]: gi = slot_gi[s]
        else: break
    if orn and orn[-1][2] == gi and v[0]-orn[-1][1] < 0.35: orn[-1][1] = round(v[1],2)
    else: orn.append([round(v[0],2), round(v[1],2), gi])
json.dump(orn, open('ornaments.json','w'))

# ---- rewrite timing.json ----
tj = json.load(open('timing.json'))
starts_w = [t_slot[first_slot[anchors_raw[i]['gi']]] for i in range(len(anchors_raw))]
ptr = 0
for cap in tj['captions']:
    for wd in cap['words']:
        t0 = starts_w[ptr]
        t1 = starts_w[ptr+1] if ptr+1 < len(starts_w) else min(t0+3.0, END_T)
        wd['t0'] = round(t0,2); wd['t1'] = round(max(t1, t0+0.15),2)
        ptr += 1
    cap['t0'] = cap['words'][0]['t0']; cap['t1'] = cap['words'][-1]['t1']
lt = []
for li in range(18):
    gi = min(i for i, g in enumerate(notes) if g['line'] == li)
    lt.append(round(t_slot[first_slot[gi]],2))
for i in range(1,18):
    if lt[i] <= lt[i-1]: lt[i] = lt[i-1] + 0.5
tj['line_times'] = lt
json.dump(tj, open('timing.json','w'), indent=1)
print(f"\n{len(orn)} ornaments; slots {S}; timing.json rewritten")
