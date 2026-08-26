#!/usr/bin/env python3
"""propose_cuts.py -- DRAFT tape cuts from the tape_lane classifier.

Turns cutting a new tape into verification: the lane classifier stream is
smoothed and decoded into (lane, t0, t1) segments, edges are snapped to energy
dips, and the book's hymn order (workdir hymns.json) names the segments in
sequence -- parallagi-then-melos, the measured 23/23 prior.

Writes texts/draftcuts_<wd>.json, schema mirroring cuts_<wd>.json plus per-row
provenance.  NEVER writes cuts_*.json; chanter cuts are ground truth and drafts
are never auto-adopted.

Usage:
  propose_cuts.py --workdir mode2-orthros              # write drafts
  propose_cuts.py --workdir mode1 --model .../tape_lane_heldout_mode1.pt \
                  --eval --no-write                    # honest fold scoring
"""
import argparse, json, os, sys
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'neural'))
import tape_lane as TL

TEXTS = TL.TEXTS
STRIDE = 11                                   # frames between windows, ~0.26 s
STEP = STRIDE / TL.FPS


def prob_stream(net, M, dev, cache_key=None):
    if cache_key:
        fn = f'{TL.CACHE}/probs_{cache_key}.npz'
        if os.path.exists(fn):
            z = np.load(fn)
            return z['t'], z['P']
    starts = list(range(0, M.shape[1] - TL.WIN, STRIDE))
    P = np.zeros((len(starts), 3), dtype=np.float32)
    net.eval()
    with torch.no_grad():
        for i in range(0, len(starts), 256):
            xs = TL.cmvn(np.stack([M[:, s:s + TL.WIN]
                                for s in starts[i:i + 256]]))
            p = torch.softmax(net(torch.from_numpy(xs).to(dev)), -1)
            P[i:i + 256] = p.cpu().numpy()
    t = (np.array(starts) + TL.WIN / 2) / TL.FPS      # window-centre seconds
    if cache_key:
        np.savez(f'{TL.CACHE}/probs_{cache_key}.npz', t=t, P=P)
    return t, P


def smooth(P, w=13):
    k = np.ones(w) / w
    return np.stack([np.convolve(P[:, i], k, 'same') for i in range(3)], 1)


def runs_of(states):
    out, s0 = [], 0
    for i in range(1, len(states) + 1):
        if i == len(states) or states[i] != states[s0]:
            out.append([int(states[s0]), s0, i])
            s0 = i
    return out


LAM_SING = 8.0     # switch cost speech <-> singing
LAM_LANE = 22.0     # switch cost parallagi <-> melos


def decode(t, P):
    """prob stream -> [(lane_idx, i0, i1)] sing segments (indices into t).

    Penalised Viterbi over {speech, par, mel}: the MAP state path under a
    per-switch cost.  This is the change-point detector -- a 60%%-correct
    parallagi stream still yields the right single change-point, where
    run-length heuristics merged or fragmented it.
    """
    L = np.log(np.maximum(smooth(P, 5), 1e-9))
    lam = np.array([[0, LAM_SING, LAM_SING],
                    [LAM_SING, 0, LAM_LANE],
                    [LAM_SING, LAM_LANE, 0]], dtype=np.float32)
    T = len(L)
    D = L[0].copy()
    B = np.zeros((T, 3), dtype=np.int8)
    for i in range(1, T):
        cand = D[:, None] - lam
        B[i] = cand.argmax(0)
        D = cand.max(0) + L[i]
    st = np.zeros(T, dtype=np.int8)
    st[-1] = D.argmax()
    for i in range(T - 1, 0, -1):
        st[i - 1] = B[i, st[i]]
    R = runs_of(st)
    # absorb residual too-short runs (speech < 4 s, lane < 10 s)
    def dur(r): return (r[2] - r[1]) * STEP
    changed = True
    while changed and len(R) > 1:
        changed = False
        for i, r in enumerate(R):
            if dur(r) >= (4.0 if r[0] == 0 else 10.0):
                continue
            nb = [R[j] for j in (i - 1, i + 1) if 0 <= j < len(R)]
            tgt = max(nb, key=dur)
            if tgt[0] != r[0]:
                r[0] = tgt[0]
                changed = True
        M2 = []
        for r in R:
            if M2 and M2[-1][0] == r[0]:
                M2[-1][2] = r[2]
            else:
                M2.append(r)
        R = M2
    return [r for r in R if r[0] != 0]


def envelope(M, w=9):
    e = M.mean(0)                                  # mean log-mel, per frame
    k = np.ones(w) / w
    return np.convolve(e, k, 'same')


def snap(sec, env, half=2.0):
    """Move a boundary to the CENTRE of the longest quiet run within +/- half s.

    argmin(env) lands on the FIRST of the near-tied floor frames -- the left
    edge of the pause -- so every boundary clipped the closing fade off the
    ending hymn (verified visually across all 45 mode2-orthros drafts).  The
    real pause is a run of floor-level frames; its midpoint leaves the fade
    on the correct side.  Longest run (not deepest frame) because inter-hymn
    pauses reach tape floor for seconds, breath dips for fractions of one.
    """
    a = max(0, int((sec - half) * TL.FPS))
    b = min(len(env), int((sec + half) * TL.FPS))
    if b - a < 3:
        return sec
    w = env[a:b]
    floor = float(w.min())
    thr = floor + 0.15 * max(float(np.median(w)) - floor, 1e-6)
    quiet = w <= thr
    best, i, n = None, 0, len(quiet)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if best is None or j - i > best[1] - best[0]:
                best = (i, j)
            i = j
        else:
            i += 1
    if best is None:
        return (a + int(np.argmin(w))) / TL.FPS
    return (a + (best[0] + best[1]) / 2) / TL.FPS


def segments(net, M, dev, cache_key=None):
    t, P = prob_stream(net, M, dev, cache_key)
    env = envelope(M)
    R = decode(t, P)
    segs = []
    for k, (lane, i0, i1) in enumerate(R):
        if segs and segs[-1].get('_i1') == i0:
            t0 = segs[-1]['t1']          # shared lane-change boundary
        else:
            t0 = snap(t[i0] - 2.0, env, half=1.5)
        if k + 1 < len(R) and R[k + 1][1] == i1:
            # contiguous singing, lane change: ONE boundary, snapped once.
            # Wide window: the Viterbi change-point can sit a full phrase
            # before the actual pause (t03 end was 8 s early, t19 end 10 s);
            # the longest-quiet-run rule keeps a wide search honest.
            t1 = snap(t[i1 - 1], env, half=8.0)
        else:
            t1 = snap(t[i1 - 1] + 2.0, env, half=1.5)
        if t1 <= t0:
            t1 = t[i1 - 1] + 2.0
        segs.append(dict(lane=TL.CLS[lane], t0=round(t0, 2),
                         t1=round(t1, 2), _i1=i1))
    segs = [s for s in segs if s['t1'] - s['t0'] >= 8]
    for a, b in zip(segs, segs[1:]):
        if a['t1'] > b['t0']:
            mid = round((a['t1'] + b['t0']) / 2, 2)
            a['t1'] = b['t0'] = mid
    for s in segs:
        s.pop('_i1', None)
    return segs


def book_order(wd):
    fn = f'/mnt/data/chant-corpus/workdirs/{wd}/hymns.json'
    if not os.path.exists(fn):
        return []          # extra tape without a workdir: all spans unnamed
    return [r['name'] for r in json.load(open(fn))]


def tape_of(wd):
    try:
        return TL.tape_for(wd)
    except FileNotFoundError:
        return json.load(open(f'{TEXTS}/extra_tapes.json'))[wd]


# ---------------- LLM boundary audit ----------------
# The local vLLM judges each drafted boundary from a digit sparkline of the
# loudness envelope -- measured 30/31 against a chanter-verified visual review
# (mode2-orthros, 2026-08-25), catching 11/11 mid-audio boundaries with zero
# false passes. Second opinion only: verdicts land in labels, never move cuts.
QWEN_URL = os.environ.get('QWEN_URL',
                          'http://10.43.106.252:8000/v1/chat/completions')
QWEN_MODEL = os.environ.get('QWEN_MODEL', 'qwen3.8-27b-uncensored')

AUDIT_PROMPT = """\
You are inspecting the loudness envelope of a cassette tape of Byzantine chant.
Below is a string of digits. Each digit is the average loudness of 0.25 seconds
of audio, 0 = silence (tape floor), 9 = loudest chanting. The string covers 40
seconds. A proposed cut boundary between two hymns sits exactly at the position
marked '|'.

A CORRECT boundary sits inside a silence gap: a run of several consecutive
0s/1s (at least ~1 second, i.e. 4+ low digits) separating two loud blocks.
Quiet SPEECH (a sustained murmur of 1-3 digits) adjacent to the mark also
counts as a valid neighbour -- the tape has spoken introductions between hymns.
An INCORRECT boundary sits in the middle of ongoing chanting (surrounded by
mid/high digits), even if there is a real silence gap somewhere else in the
string.

Envelope:
%s

Judge ONLY the marked position. Reply with a single JSON object, no other text:
{"verdict": "IN_GAP" or "MID_AUDIO", "reason": "<one short sentence>"}"""


def sparkline(env, sec, half=20.0, bin_s=0.25):
    a = max(0, int((sec - half) * TL.FPS))
    b = min(len(env), int((sec + half) * TL.FPS))
    n = max(1, int(bin_s * TL.FPS))
    w = env[a:b]
    v = np.array([w[i:i + n].mean() for i in range(0, len(w) - n, n)])
    lo, hi = v.min(), v.max()
    d = np.clip(((v - lo) / (hi - lo + 1e-9) * 9).round(), 0, 9).astype(int)
    mid = int((sec - a / TL.FPS) / bin_s)
    s = ''.join(str(x) for x in d)
    return s[:mid] + '|' + s[mid:]


def audit_boundary(env, sec):
    import urllib.request
    body = json.dumps(dict(
        model=QWEN_MODEL,
        messages=[dict(role='user', content=AUDIT_PROMPT % sparkline(env, sec))],
        temperature=0, max_tokens=3000,
        chat_template_kwargs=dict(enable_thinking=False))).encode()
    req = urllib.request.Request(QWEN_URL, body,
                                 {'Content-Type': 'application/json'})
    for _ in range(2):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            txt = r['choices'][0]['message']['content'] or ''
            j = json.loads(txt[txt.index('{'):txt.rindex('}') + 1])
            if j.get('verdict') in ('IN_GAP', 'MID_AUDIO'):
                return j
        except Exception as e:
            err = str(e)
    return dict(verdict='ERROR', reason=err[:80])


def rule_verdict(env, sec, near=1.5, ctx=20.0, frac=0.15, min_run=1.2):
    """IN_GAP iff a quiet run >= min_run s overlaps [sec-near, sec+near].

    Quiet = below floor + frac*(context median - floor), the same definition
    snap() uses. Tuned on the 31 chanter-verified boundaries (2026-08-25):
    28/31 with ZERO false passes -- it catches every mid-audio boundary and
    over-flags ~2 good ones, which the tiered LLM pass then clears.
    """
    a = max(0, int((sec - ctx) * TL.FPS))
    b = min(len(env), int((sec + ctx) * TL.FPS))
    w = env[a:b]
    floor = float(w.min())
    thr = floor + frac * max(float(np.median(w)) - floor, 1e-6)
    quiet = w <= thr
    lo = int((sec - near) * TL.FPS) - a
    hi = int((sec + near) * TL.FPS) - a
    i, n = 0, len(quiet)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) / TL.FPS >= min_run and j > lo and i < hi:
                return dict(verdict='IN_GAP', reason='quiet run at boundary')
            i = j
        else:
            i += 1
    return dict(verdict='MID_AUDIO', reason='no quiet run within +/-%.1fs' % near)


def audit(rows, env, mode='tiered'):
    """Verdict per unique boundary; MID_AUDIO flags append to row labels.

    mode 'rule': envelope rule only (instant, zero deps).
    mode 'qwen': LLM on every boundary.
    mode 'tiered': rule first; the LLM is consulted only on rule flags, to
    confirm or clear them (measured: rule has 0 false passes, so a rule
    IN_GAP needs no second opinion). LLM errors fall back to the rule.
    """
    bounds = []
    for r in rows:
        for x in (r['t0'], r['t1']):
            if not bounds or all(abs(x - b) > 0.5 for b in bounds):
                bounds.append(x)
    verdicts = {}
    for x in sorted(bounds):
        v = rule_verdict(env, x)
        via = 'rule'
        if mode == 'qwen' or (mode == 'tiered'
                              and v['verdict'] == 'MID_AUDIO'):
            lv = audit_boundary(env, x)
            if lv['verdict'] != 'ERROR':
                v, via = lv, 'qwen'
        verdicts[x] = v
        print(f'   audit {x:8.1f}  {v["verdict"]:9s} [{via}] {v["reason"][:60]}')
    for r in rows:
        flags = []
        for name, x in (('t0', r['t0']), ('t1', r['t1'])):
            key = min(verdicts, key=lambda b: abs(b - x))
            v = verdicts[key]
            if v['verdict'] == 'MID_AUDIO':
                flags.append(f'AUDIT: {name} mid-audio — check')
            elif v['verdict'] == 'ERROR':
                flags.append(f'AUDIT: {name} unavailable')
        if flags:
            r['label'] = ' | '.join(([r['label']] if r['label'] else []) + flags)
    return rows


def assemble(segs, hymns):
    """Greedy hymn naming: parallagi opens a hymn, melos closes it (23/23)."""
    out, hi, open_par = [], 0, False
    for s in segs:
        row = dict(hymn=None, t0=s['t0'], t1=s['t1'], t_in=None, skips=[],
                   label=None, lane=s['lane'], draft=True)
        if s['lane'] == 'parallagi':
            if open_par:
                hi += 1                       # par after par: hymn had no melos
            if hi < len(hymns):
                row['hymn'] = hymns[hi] + '#par'
            open_par = True
        else:
            if hi < len(hymns):
                row['hymn'] = hymns[hi]
            hi += 1
            open_par = False
        if row['hymn'] is None:
            row['label'] = 'EXTRA: past end of book order'
        out.append(row)
    return out


# ---------------- evaluation against chanter cuts ----------------

def gold_spans(wd):
    d = json.load(open(f'{TEXTS}/cuts_{wd}.json'))
    return sorted([dict(hymn=c['hymn'], t0=c['t0'], t1=c['t1'],
                        lane=TL.lane_of(c)) for c in d['cuts']],
                  key=lambda c: c['t0'])


def uniq_bounds(spans, eps=1.0):
    b = sorted([s['t0'] for s in spans] + [s['t1'] for s in spans])
    out = []
    for x in b:
        if not out or x - out[-1] > eps:
            out.append(x)
    return out


def match_bounds(pred, gold, tol):
    used, hit = set(), 0
    for g in gold:
        best, bd = None, tol
        for i, p in enumerate(pred):
            if i in used or abs(p - g) > bd:
                continue
            best, bd = i, abs(p - g)
        if best is not None:
            used.add(best); hit += 1
    return hit


def eval_segs(segs, gold, label):
    gb = uniq_bounds(gold)
    pb = uniq_bounds([dict(t0=s['t0'], t1=s['t1']) for s in segs])
    print(f'-- {label}: {len(segs)} segments, {len(pb)} boundaries '
          f'(gold {len(gold)} spans, {len(gb)} boundaries)')
    for tol in (2, 5, 10):
        h = match_bounds(pb, gb, tol)
        print(f'   boundaries within {tol:2d}s: {h}/{len(gb)} recall '
              f'{h/len(gb):.2f}   precision {h/max(1,len(pb)):.2f}')
    if not segs or 'lane' not in segs[0]:
        return
    lane_ok = miss = 0
    matched_pred = set()
    for g in gold:
        best, bo = None, 0.0
        for i, s in enumerate(segs):
            o = min(g['t1'], s['t1']) - max(g['t0'], s['t0'])
            if o > bo:
                best, bo = i, o
        iou = 0.0
        if best is not None:
            s = segs[best]
            iou = bo / (max(g['t1'], s['t1']) - min(g['t0'], s['t0']))
        if best is None or iou < 0.3:
            miss += 1
        else:
            matched_pred.add(best)
            if segs[best]['lane'] == g['lane']:
                lane_ok += 1
    hall = len(segs) - len(matched_pred)
    print(f'   spans: matched {len(gold)-miss}/{len(gold)}, missed {miss}, '
          f'hallucinated/split-extra {hall};  lane acc on matched '
          f'{lane_ok}/{len(gold)-miss} = {lane_ok/max(1,len(gold)-miss):.2f}')


def baseline_silence(M):
    env = envelope(M, w=43)                       # ~1 s smoothing
    thr = np.percentile(env, 12)
    sil = env < thr
    segs, i, T = [], 0, len(sil)
    while i < T:
        if not sil[i]:
            j = i
            while j < T:
                if sil[j]:
                    k = j
                    while k < T and sil[k]:
                        k += 1
                    if (k - j) / TL.FPS >= 1.5:
                        break
                    j = k
                else:
                    j += 1
            segs.append(dict(t0=round(i / TL.FPS, 2), t1=round(j / TL.FPS, 2)))
            while j < T and sil[j]:
                j += 1
            i = j
        else:
            i += 1
    return [s for s in segs if s['t1'] - s['t0'] >= 5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--model', default=f'{TL.MODELS}/tape_lane_all.pt')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--eval', action='store_true')
    ap.add_argument('--audit', default='tiered',
                    choices=['tiered', 'rule', 'qwen', 'none'])
    ap.add_argument('--no-write', action='store_true')
    a = ap.parse_args()
    dev = a.device if (a.device == 'cpu' or torch.cuda.is_available()) else 'cpu'
    ck = torch.load(a.model, map_location=dev, weights_only=False)
    if ck['cfg'].get('heldout') != a.workdir and a.eval:
        print(f"WARNING: model heldout={ck['cfg'].get('heldout')} but "
              f"evaluating {a.workdir} -- scores are NOT honest", file=sys.stderr)
    net = TL.Net().to(dev)
    net.load_state_dict(ck['state'])
    tape = tape_of(a.workdir)
    print('tape', tape)
    M = TL.mel(tape)
    segs = segments(net, M, dev, cache_key=f"{a.workdir}_{os.path.basename(a.model).replace('.pt','')}")
    hymns = book_order(a.workdir)
    rows = assemble(segs, hymns)
    if a.audit != 'none':
        rows = audit(rows, envelope(M), mode=a.audit)
    if a.eval:
        gold = gold_spans(a.workdir)
        eval_segs(segs, gold, f'model ({os.path.basename(a.model)})')
        eval_segs(baseline_silence(M), gold, 'baseline silence-gap')
    if not a.no_write:
        out = f'{TEXTS}/draftcuts_{a.workdir}.json'
        assert 'draftcuts_' in os.path.basename(out)
        import datetime
        json.dump(dict(workdir=a.workdir, saved=datetime.datetime.now()
                       .isoformat(timespec='seconds'),
                       source=dict(model=a.model, tool='propose_cuts.py'),
                       draft=True, cuts=rows),
                  open(out, 'w'), indent=1, ensure_ascii=False)
        print('wrote', out)
    for r in rows:
        print(' %8.1f %8.1f %-9s %s%s' % (r['t0'], r['t1'], r['lane'],
              r['hymn'] or '??', '  [' + r['label'] + ']' if r['label'] else ''))


if __name__ == '__main__':
    main()
