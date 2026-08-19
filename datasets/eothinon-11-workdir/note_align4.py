#!/usr/bin/env python3
"""v4: two-stage beat-weighted matching with breath<->barline phrase skeleton.
Stage 1: whisper anchors + manual pins -> provisional times.
Stage 2: DP-match voice breath gaps to score barlines -> phrase pins;
         drop whisper anchors deviating >1.8s from the pin skeleton; refit.
-> slots.json, ornaments.json, timing.json rewritten"""
import json, math

GORGON = {0xf053}
DURATION_CP = {0xf061: 2.0, 0xf041: 2.0,   # klasma above/below
               0xf027: 2.0,                # apli (')
               0xf022: 3.0,                # dipli (")
               0xf06b: 3.0}                # cadence dipli-class hold
YPORRHOE, SYNELAF = 0xf05f, 0xf050
MANUAL = [(49, 54.0), (52, 58.0)]     # user ground truth: 'rec-' 54, '-tion' 58
BREATH_PINS = [(164, 167.22), (215, 212.55), (222, 220.97)]  # curated breath<->barline
DROP = {21,22,23,24,25, 92,93,94,95}   # whisper junk: Resurrection region + Thy,/preserve/Thy/flock cluster

sn = json.load(open('score_notes.json'))
notes, anchors_raw = sn['notes'], sn['anchors']
mods = json.load(open('modifiers.json'))
wt = json.load(open('word_times.json'))
vn = json.load(open('voice_notes3.json'))
bars = json.load(open('barlines.json'))
N = len(notes)
END_T = max(v[1] for v in vn)

# ---- modifiers ----
gor = [False]*N; dur = [1.0]*N
for m in mods:
    if m['cp'] in GORGON or m['cp'] in DURATION_CP:
        best, bd = None, 30
        for j, g in enumerate(notes):
            if g['line'] != m['line']: continue
            d = abs(g['x1'] - m['x'])
            if d < bd: best, bd = j, d
        if best is not None:
            if m['cp'] in GORGON: gor[best] = True
            else: dur[best] = max(dur[best], DURATION_CP[m['cp']])

# ---- slots ----
slot_gi, slot_w = [], []
for j, g in enumerate(notes):
    w = dur[j]
    if g['cp'] == YPORRHOE: pieces = [w*0.5, w*0.5]
    elif g['cp'] == SYNELAF:
        pieces = [0.5, w]
        if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)
    else: pieces = [w]
    if gor[j]:
        pieces[0] = 0.5
        if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)
    for p in pieces:
        slot_gi.append(j); slot_w.append(p)
S = len(slot_gi)
first_slot = {}
for s in range(S): first_slot.setdefault(slot_gi[s], s)
def beats(s0, s1): return sum(slot_w[s0:s1]) or 0.001
TOTB = beats(0, S)
onsets = [v[0] for v in vn]

def build_anchors(pins, drop_wi=(), skeleton=None):
    """pins: [(slot, time)] hard; whisper words filtered vs skeleton if given"""
    A = []; PIN = []
    for wi, (a, b) in enumerate(zip(anchors_raw, wt)):
        if wi in drop_wi: continue
        t, s = b['t0'], first_slot[a['gi']]
        if skeleton is not None:
            pred = skeleton(s)
            if abs(t - pred) > 1.8: continue
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

def refine(A, PIN, T0, passes=3):
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
            best, bc = t, cost(t)
            for h in onsets:
                if not (tp + 0.15 < h < tn - 0.15) or abs(h-t) > 1.3: continue
                c = cost(h)
                if c < bc - 1e-6: best, bc = h, c
            if best != t: A[i][0] = best; changed += 1
        if not changed: break
    return A

def assign(A):
    t_slot = [None]*S; claimed = [False]*len(vn)
    for (ta, sa, _), (tb, sb, _) in zip(A, A[1:]):
        span = list(range(sa, sb))
        if not span: continue
        V = [k for k, v in enumerate(vn) if ta - 0.03 <= v[0] < tb - 0.03]
        B = beats(sa, sb); cum = 0.0; fracs = []
        for s in span: fracs.append(cum/B); cum += slot_w[s]
        vp = 0
        for s, f in zip(span, fracs):
            target = ta + f*(tb-ta)
            best, bd = None, 1e9
            for k in V[vp:]:
                d = abs(vn[k][0] - target)
                if d < bd: best, bd = k, d
                if vn[k][0] > target + 1.5: break
            if best is not None and bd < 0.9:
                t_slot[s] = vn[best][0]; claimed[best] = True; vp = V.index(best)+1
            else: t_slot[s] = target
    last = 0.0
    for s in range(S):
        if t_slot[s] is None: t_slot[s] = last + 0.2
        t_slot[s] = max(t_slot[s], last + 0.02); last = t_slot[s]
    return t_slot, claimed

# ================= stage 1: whisper + manual =================
pins1 = [(first_slot[g], t) for g, t in MANUAL]
pins1 += [(first_slot[g], t) for g, t in BREATH_PINS]
A1, P1 = build_anchors(pins1, drop_wi=DROP)
T0 = (A1[-1][0] - A1[0][0]) / TOTB
A1 = refine(A1, P1, T0)
t1_result = assign(A1)

t_slot, claimed = t1_result
A2 = A1

json.dump({'t': [round(t,3) for t in t_slot], 'gi': slot_gi}, open('slots.json','w'))

# ---- ornaments ----
orn = []
start_t = A2[0][0]
for k, v in enumerate(vn):
    if claimed[k] or not (0.15 <= v[1]-v[0] <= 0.50) or v[0] < start_t: continue
    gi = 0
    for s in range(S):
        if t_slot[s] <= v[0]: gi = slot_gi[s]
        else: break
    if orn and orn[-1][2] == gi and v[0]-orn[-1][1] < 0.35: orn[-1][1] = round(v[1],2)
    else: orn.append([round(v[0],2), round(v[1],2), gi])
json.dump(orn, open('ornaments.json','w'))

# ---- rewrite timing.json from slot times ----
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

print(f"\n{len(orn)} ornament spans; line times: {lt}")
iv = sorted(t_slot[s+1]-t_slot[s] for s in range(S-1))
print(f"slot interval median {iv[S//2]:.2f} p95 {iv[int(0.95*S)]:.2f} max {iv[-1]:.2f}")
