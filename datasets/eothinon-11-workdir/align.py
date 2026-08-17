#!/usr/bin/env python3
"""Align known score lyrics to whisper word timestamps -> timing.json"""
import json, re, difflib

DUR = 273.18

# words as sung, in order; line breaks per the 18 score systems.
# a word belongs to the line where it STARTS. Continuation lines (start
# mid-melisma of previous word) are marked with cont=True.
LINES = [
    (False, "Glory to the Father, and to the Son, and"),
    (False, "to the Holy Spirit."),
    (False, "When Thou didst show Thyself to the disciples"),
    (True,  "after Thy Resurrection, O"),          # 'disci-/ples'
    (False, "Savior, Thou gavest Simon"),
    (False, "the tending of the sheep, that he might return"),
    (True,  "Thy love, and Thou didst ask him to"), # 're-/turn'
    (False, "have care for the shepherding of"),
    (False, "the flock. Wherefore, Thou didst say to"),
    (False, "him: If thou lovest Me, O Peter, feed"),
    (False, "My lambs, feed My,"),
    (False, "feed My sheep. And he, straightway showing"),
    (False, "his affectionate love, inquired concerning"),
    (True,  "the other disciple. By their intercessions"),  # 'con-/cerning'
    (True,  "O Christ, preserve"),                  # 'in-/tercessions'
    (False, "Thy, preserve Thy flock"),
    (False, "from the wolves that ravage"),
    (True,  "it."),                                  # 'rav-/age'
]

CAPTIONS = [
    "Glory to the Father, and to the Son, and to the Holy Spirit.",
    "When Thou didst show Thyself to the disciples after Thy Resurrection, O Savior,",
    "Thou gavest Simon the tending of the sheep,",
    "that he might return Thy love,",
    "and Thou didst ask him to have care for the shepherding of the flock.",
    "Wherefore, Thou didst say to him:",
    "If thou lovest Me, O Peter, feed My lambs,",
    "feed My, feed My sheep.",
    "And he, straightway showing his affectionate love,",
    "inquired concerning the other disciple.",
    "By their intercessions, O Christ,",
    "preserve Thy, preserve Thy flock from the wolves that ravage it.",
]

def norm(w):
    return re.sub(r"[^a-z]", "", w.lower())

# ---- flatten score words ----
score_words = []           # (display_word, line_idx_of_start)
for li, (cont, text) in enumerate(LINES):
    for w in text.split():
        score_words.append((w, li))

# ---- whisper words ----
ww = json.load(open('whisper_words.json'))   # [(word, t0, t1)]

# snap word starts to nearest voice-note onset (pitch-tracker is more precise)
try:
    vn = json.load(open('voice_notes3.json'))
    onsets = [v[0] for v in vn]
    def snap(t):
        best = min(onsets, key=lambda o: abs(o - t))
        return best if abs(best - t) <= 0.45 else t
    ww = [(w, snap(t0), t1) for (w, t0, t1) in ww]
    ww = [(w, t0, max(t0 + 0.1, t1)) for (w, t0, t1) in ww]
except FileNotFoundError:
    pass
w_norm = [norm(w[0]) for w in ww]
s_norm = [norm(w[0]) for w in score_words]

# ---- sequence alignment ----
sm = difflib.SequenceMatcher(a=s_norm, b=w_norm, autojunk=False)
starts = [None]*len(score_words)
ends = [None]*len(score_words)
for bl in sm.get_matching_blocks():
    for k in range(bl.size):
        starts[bl.a+k] = ww[bl.b+k][1]
        ends[bl.a+k] = ww[bl.b+k][2]

matched = sum(1 for s in starts if s is not None)
print(f"matched {matched}/{len(score_words)} score words to whisper words")

# ---- interpolate missing times ----
n = len(score_words)
known = [i for i in range(n) if starts[i] is not None]
if not known:
    raise SystemExit("no matches at all")
for i in range(n):
    if starts[i] is None:
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is None:
            starts[i] = starts[nxt] * i / max(nxt, 1)
        elif nxt is None:
            t0 = ends[prev] if ends[prev] else starts[prev]
            starts[i] = t0 + (i - prev) * 1.5
        else:
            f = (i - prev) / (nxt - prev)
            starts[i] = starts[prev] + f * (starts[nxt] - starts[prev])
# monotonic fix + ends
for i in range(1, n):
    if starts[i] < starts[i-1]:
        starts[i] = starts[i-1]
for i in range(n):
    if ends[i] is None:
        ends[i] = starts[i+1] if i+1 < n else min(DUR, starts[i]+3.0)
    ends[i] = max(ends[i], starts[i] + 0.15)

# ---- line anchor times ----
line_times = []
for li in range(len(LINES)):
    idxs = [i for i, (_, l) in enumerate(score_words) if l == li]
    first = idxs[0]
    t = starts[first]
    if LINES[li][0] and first > 0:
        # line starts mid-melisma of previous word: 60% into prev word span
        prev_t = starts[first-1]
        t = prev_t + 0.6 * (max(t, prev_t + 0.2) - prev_t)
    line_times.append(round(t, 2))
# enforce strictly increasing
for i in range(1, 18):
    if line_times[i] <= line_times[i-1]:
        line_times[i] = line_times[i-1] + 0.5

# ---- captions with word times ----
caps = []
ptr = 0
for ctext in CAPTIONS:
    cw = ctext.split()
    cwn = [norm(w) for w in cw]
    # match caption words against score_words sequence from ptr
    words = []
    for j, w in enumerate(cw):
        si = ptr + j
        words.append({'w': w, 't0': round(starts[si], 2), 't1': round(ends[si], 2)})
    ptr += len(cw)
    caps.append({'t0': words[0]['t0'], 't1': words[-1]['t1'], 'words': words})
assert ptr == n, f"caption words {ptr} != score words {n}"

json.dump({'line_times': line_times, 'captions': caps, 'duration': DUR},
          open('timing.json', 'w'), indent=1)
json.dump([{'w': score_words[i][0], 'line': score_words[i][1],
            't0': round(starts[i], 2), 't1': round(ends[i], 2)}
           for i in range(n)], open('word_times.json', 'w'))
print("line times:", line_times)
print("caption spans:", [(c['t0'], c['t1']) for c in caps])
