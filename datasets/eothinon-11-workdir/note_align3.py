#!/usr/bin/env python3
"""v3: beat-weighted note matching.
- gorgon (0xf053): halves its note and the note before
- klasma (0xf061/0xf041): doubles its note
- yporrhoe (0xf05f): 2 quick slots in one glyph
- syneches elaphron (0xf050): 2 slots, gorgon-on-first semantics
- bidirectional anchor refinement vs beat-tempo consistency
-> slots.json {'t', 'gi'}, ornaments.json"""
import json, math

GORGON, KLASMA = {0xf053}, {0xf061, 0xf041}
YPORRHOE, SYNELAF = 0xf05f, 0xf050

sn = json.load(open('score_notes.json'))
notes, anchors_raw = sn['notes'], sn['anchors']
mods = json.load(open('modifiers.json'))
wt = json.load(open('word_times.json'))
vn = json.load(open('voice_notes3.json'))
N = len(notes)
END_T = max(v[1] for v in vn)

# ---- attach modifiers to notes ----
gor = [False]*N; kla = [False]*N
for m in mods:
    if m['cp'] in GORGON | KLASMA:
        best, bd = None, 30
        for j, g in enumerate(notes):
            if g['line'] != m['line']: continue
            d = abs(g['x1'] - m['x'])
            if d < bd: best, bd = j, d
        if best is not None:
            if m['cp'] in GORGON: gor[best] = True
            else: kla[best] = True
print(f"gorgon on {sum(gor)} notes, klasma on {sum(kla)} notes")

# ---- build slots ----
slot_gi, slot_w = [], []
for j, g in enumerate(notes):
    w = 2.0 if kla[j] else 1.0
    if g['cp'] == YPORRHOE:
        pieces = [w*0.5, w*0.5]
    elif g['cp'] == SYNELAF:
        pieces = [0.5, w]
        if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)   # gorgon steals, not halves
    else:
        pieces = [w]
    if gor[j]:
        pieces[0] = 0.5
        if slot_w: slot_w[-1] = max(0.25, slot_w[-1] - 0.5)   # steal 0.5 from previous
    for p in pieces:
        slot_gi.append(j); slot_w.append(p)
S = len(slot_gi)
first_slot = {}
for s in range(S):
    first_slot.setdefault(slot_gi[s], s)
print(f"{N} glyphs -> {S} slots, total beats {sum(slot_w):.1f}")

# ---- anchors in slot space ----
DROP_WI = {21, 22, 23, 24, 25}      # after/Thy/Resurrection/O/Savior: whisper unreliable here
MANUAL = [(49, 54.0), (52, 58.0)]   # ground truth: 'rec-' melisma 54-58, '-tion' at 58
A = []; PIN = []
for wi, (a, b) in enumerate(zip(anchors_raw, wt)):
    if wi in DROP_WI: continue
    t, s = b['t0'], first_slot[a['gi']]
    if A and (t <= A[-1][0] + 0.05 or s <= A[-1][1]): continue
    A.append([t, s, b['w']]); PIN.append(False)
for gi, t in MANUAL:
    A.append([t, first_slot[gi], f'manual@{gi}']); PIN.append(True)
order = sorted(range(len(A)), key=lambda i: A[i][1])
A = [A[i] for i in order]; PIN = [PIN[i] for i in order]
keep = []
for i in range(len(A)):
    while keep and (A[i][0] <= A[keep[-1]][0] + 0.05 or A[i][1] <= A[keep[-1]][1]):
        if PIN[i] and not PIN[keep[-1]]: keep.pop()
        else: break
    if keep and (A[i][0] <= A[keep[-1]][0] + 0.05 or A[i][1] <= A[keep[-1]][1]): continue
    keep.append(i)
A = [A[i] for i in keep]; PIN = [PIN[i] for i in keep]
A.append([min(END_T, 271.5), S, '<end>']); PIN.append(True)

def beats(s0, s1): return sum(slot_w[s0:s1]) or 0.001
TOTB = beats(0, S)
T0 = (A[-1][0] - A[0][0]) / TOTB          # sec per beat
print(f"global tempo {T0:.2f} s/beat, {len(A)-1} anchors")

onsets = [v[0] for v in vn]
def refine():
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
            if not (tp + 0.15 < h < tn - 0.15): continue
            if abs(h - t) > 1.3: continue
            c = cost(h)
            if c < bc - 1e-6: best, bc = h, c
        if best != t:
            A[i][0] = best; changed += 1
    return changed
for it in range(3):
    ch = refine()
    print(f"refine pass {it}: moved {ch} anchors")
    if not ch: break

# ---- beat-proportional assignment within spans ----
t_slot = [None]*S
claimed = [False]*len(vn)
for (ta, sa, _), (tb, sb, _) in zip(A, A[1:]):
    span_slots = list(range(sa, sb))
    if not span_slots: continue
    V = [k for k, v in enumerate(vn) if ta - 0.03 <= v[0] < tb - 0.03]
    B = beats(sa, sb)
    cum = 0.0
    fracs = []
    for s in span_slots:
        fracs.append(cum / B)
        cum += slot_w[s]
    if not V:
        for s, f in zip(span_slots, fracs):
            t_slot[s] = ta + f*(tb-ta)
        continue
    vp = 0
    for s, f in zip(span_slots, fracs):
        target = ta + f*(tb-ta)
        best, bd = None, 1e9
        for k in V[vp:]:
            d = abs(vn[k][0] - target)
            if d < bd: best, bd = k, d
            if vn[k][0] > target + 1.5: break
        if best is not None and bd < 0.9:
            t_slot[s] = vn[best][0]
            claimed[best] = True
            vp = V.index(best) + 1
        else:
            t_slot[s] = target
last = 0.0
for s in range(S):
    if t_slot[s] is None: t_slot[s] = last + 0.2
    t_slot[s] = max(t_slot[s], last + 0.02)
    last = t_slot[s]

json.dump({'t': [round(t,3) for t in t_slot], 'gi': slot_gi}, open('slots.json','w'))

# ---- ornaments: unclaimed quick sung notes ----
orn = []
for k, v in enumerate(vn):
    if claimed[k] or not (0.15 <= v[1]-v[0] <= 0.50): continue
    if v[0] < A[0][0]: continue        # apichima: no ornament pulse
    gi = 0
    for s in range(S):
        if t_slot[s] <= v[0]: gi = slot_gi[s]
        else: break
    if orn and orn[-1][2] == gi and v[0]-orn[-1][1] < 0.35: orn[-1][1] = round(v[1],2)
    else: orn.append([round(v[0],2), round(v[1],2), gi])
json.dump(orn, open('ornaments.json','w'))
print(f"{len(orn)} ornament spans, {sum(o[1]-o[0] for o in orn):.1f}s")

# ---- rewrite caption word times + line times from slot times ----
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
print("timing.json rewritten from slot times")

iv = sorted(t_slot[s+1]-t_slot[s] for s in range(S-1))
print(f"slot interval median {iv[S//2]:.2f} p95 {iv[int(0.95*S)]:.2f} max {iv[-1]:.2f}")
for label, lo, hi in [('Resurrection',48,58),('of-the-flock',108,118),('feed-lambs',142,152),
                      ('affectionate',172,180),('post-Christ',203,216),('2nd-preserve',224,230)]:
    ss = [s for s in range(S) if lo <= t_slot[s] <= hi]
    if ss:
        words = [a['text'] for a,b in zip(anchors_raw, wt) if lo <= b['t0'] <= hi]
        print(f"  {label}: slots {len(ss)} t {t_slot[ss[0]]:.1f}-{t_slot[ss[-1]]:.1f} words~{words}")
