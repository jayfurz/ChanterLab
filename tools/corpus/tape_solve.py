#!/usr/bin/env python3
"""tape_solve.py — RESEP-01 step 3: solve the assignment, with use-once.

tape_assign.py caches every segment's CTC score against every candidate text, so
the assignment itself is a cheap CPU problem. This solves it, and adds the
constraint that was still missing: a canonical text may be assigned to at most
ONE hymn.

Use-once is NOT text-index monotonicity. That was tried and is wrong — the
candidate pool is GLT document order, which interleaves the Horologion ordinary
with the mode-proper hymns and does not follow the recording; imposing it took
grave-orthros from 25/25 assigned to 19/25 and shifted every hymn by two.
Segments and hymns share an order because both ARE the recording; GLT entries do
not.

Instead: solve, find any text used twice, keep it for whichever hymn matched it
better, ban it for the other, and re-solve. Repeat until no text repeats. Each
solve is milliseconds against the cache.

Usage:  tape_solve.py --workdir DIR [--max-iter 25]
"""
import argparse
import json
import os


# Editorial prose in the Horologion appendices — rubrics that EXPLAIN the
# chant rather than being chanted ("Οἱ Καταβασίες εἶναι οἱ Εἱρμοὶ τοῦ πρώτου
# κανόνος...", "Πῶς νὰ εὕρῃς τὰ λόγια τῶν Καταβασιῶν..."). It is written in
# modern Greek, which liturgical text is not, so the function words give it
# away. This is what the weak workdirs were matching: mode3 had 8 of 10 hymns
# assigned to prose, pl4-orthros 14 of 25.
PROSE = ('εἶναι', 'Πῶς νὰ', 'Ἔτσι ', 'δηλαδή', 'παρόλο', 'σελ.', 'ἐκδ.',
         'βλ. ', 'πρβλ', 'λέγεται', 'ὀνομάζ', 'συνήθως', 'ΜΑΔ', 'Μηναῖον,')


def is_prose(t):
    return any(m in t for m in PROSE)


def solve(segs_n, hymns, scores, banned, max_seg_run, skip_pen=1.0):
    """monotonic assignment of hymns to segment runs; returns [(hymn_i, key, opt)]"""
    H, S = len(hymns), segs_n
    NEG = -1e9
    D = [[NEG] * (S + 1) for _ in range(H + 1)]
    P = [[None] * (S + 1) for _ in range(H + 1)]
    CH = [[None] * (S + 1) for _ in range(H + 1)]
    for j in range(S + 1):
        D[0][j] = 0.0
        P[0][j] = (0, j - 1, None) if j else None
    for i in range(1, H + 1):
        for j in range(1, S + 1):
            best_v, best_p, best_ch = D[i][j - 1], (i, j - 1, None), None
            if D[i - 1][j] - skip_pen > best_v:          # hymn not on this tape
                best_v, best_p, best_ch = D[i - 1][j] - skip_pen, (i - 1, j, None), None
            for n in range(1, max_seg_run + 1):
                if j - n < 0 or D[i - 1][j - n] <= NEG / 2:
                    continue
                b = scores.get((j - n, n))
                if not b:
                    continue
                for o in b['opts']:
                    if o['gi'] in banned or is_prose(o['text']):
                        continue
                    v = D[i - 1][j - n] + max(0.0, 8.0 - o['lpt'])
                    if v > best_v:
                        best_v, best_p, best_ch = v, (i - 1, j - n, (j - n, n)), o
            D[i][j], P[i][j], CH[i][j] = best_v, best_p, best_ch
    reach = [x for x in range(S + 1) if P[H][x] is not None and D[H][x] > NEG / 2]
    if not reach:
        return []
    j = max(reach, key=lambda x: D[H][x])
    i, out = H, []
    while i > 0:
        if P[i][j] is None:
            break
        pi, pj, span = P[i][j]
        if span:
            out.append((i - 1, span, CH[i][j]))
        i, j = pi, pj
    out.reverse()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--max-seg-run', type=int, default=2)
    ap.add_argument('--max-iter', type=int, default=25)
    a = ap.parse_args()
    name = os.path.basename(a.workdir.rstrip('/'))
    cf = f'/mnt/data/chant-corpus/texts/segscores_{name}.json'
    if not os.path.exists(cf):
        raise SystemExit(f'no score cache at {cf} — run tape_assign.py first')
    raw = json.load(open(cf))
    scores = {tuple(int(x) for x in k.split(',')): v for k, v in raw.items()}
    segs_n = max(k[0] + k[1] for k in scores) if scores else 0
    hymns = json.load(open(os.path.join(a.workdir, 'hymns.json')))

    banned, res = set(), []
    for it in range(a.max_iter):
        res = solve(segs_n, hymns, scores, banned, a.max_seg_run)
        seen = {}
        dup = None
        for hi, key, o in res:
            if o is None:
                continue
            if o['gi'] in seen:
                prev = seen[o['gi']]
                worse = prev if prev[2]['lpt'] > o['lpt'] else (hi, key, o)
                dup = worse
                break
            seen[o['gi']] = (hi, key, o)
        if dup is None:
            break
        banned.add(dup[2]['gi'])
    out = []
    for hi, key, o in res:
        if o is None:
            continue
        b = scores[key]
        out.append({'hymn': hymns[hi]['name'], 'seg': list(key),
                    't0': b['t0'], 't1': b['t1'],
                    'dur': round(b['t1'] - b['t0'], 1),
                    'lpt': round(o['lpt'], 3), 'gi': o['gi'],
                    'text': o['text'], 'heading': o['head']})
    jf = f'/mnt/data/chant-corpus/texts/tapeassign_{name}.json'
    json.dump({'workdir': name, 'iterations': it + 1, 'banned': sorted(banned),
               'assigned': out}, open(jf, 'w'), ensure_ascii=False, indent=1)
    lp = sorted(r['lpt'] for r in out)
    gis = [r['gi'] for r in out]
    print('%-18s %2d/%-2d assigned  median %5.2f/tok  <=4.5: %2d  dup texts: %d  '
          '(%d iters, %d banned)'
          % (name, len(out), len(hymns), lp[len(lp) // 2] if lp else 0,
             sum(1 for x in lp if x <= 4.5), len(gis) - len(set(gis)),
             it + 1, len(banned)))
    return out


if __name__ == '__main__':
    main()
