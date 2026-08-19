#!/usr/bin/env python3
"""glt_match.py — match each corpus hymn's score text to its canonical GLT text.

The score lyric layer is unaccented and fragmented by the melisma
('τω','σταυ','ρω','ω'); glt_fetch.py gives the same hymns fully accented. Match
them and three problems get evidence at once:

  * SYL-01 gets the real word and inflection behind each lyric fragment
  * hymn BOUNDARIES get checked — a slice that runs into the next hymn shows up
    as text past the end of its GLT match, which is exactly the t01 bug that was
    fixed by hand with g0/g1
  * mis-slotted hymns (wrong mode, wrong service) surface as a poor best match

Comparison is on collapsed-normalised text: accents stripped, lowercase, letters
only, runs of one letter collapsed — because the melisma reprints the vowel once
per note, so 'ωωω' and 'ω' are the same word.

Usage:  glt_match.py [--workdir DIR] [--all-modes] [--min 0.55]

STATUS 2026-08-18: NOT YET TRUSTWORTHY. Read before using the output.

  v1 matched each hymn independently to its best-covering GLT text. That is
  degenerate — 173 corpus hymns collapsed onto 73 distinct texts, one claimed by
  17 hymns — and dropcap_check.py caught it: only 38% of hymns had their
  canonical initial among the drop caps on their own start page.

  v2 (this file) applies the chanter's correction: "the hymns are already in
  order ... lord i have cried then the verses then the stichera then the glory
  both now doxastikon theotokia ... then aposticha ... the order is the same".
  So it is a monotonic sequence alignment, not independent lookups. That
  structure is right and it does make the assignment one-to-one and ordered.

  But it does NOT yet lock on. On grave-orthros the ordered path puts
  Κατέλυσας on t01 when the fragments prove it belongs to t03, and most
  similarities sit at 0.2-0.4. Two known causes, both fixable, neither fixed:

    1. The GLT parse is too noisy to align against. Rubrics are glued to the
       first line of the hymn ("Ὁ Εἱρμὸς «Νεύσει σοῦ ...", "Στιχ. ..."), 40 of
       603 entries are still merged appendices, and the orthros section offers
       41 candidates for 25 recorded hymns.
    2. The DP is driven by aggregate similarity over a noisy field instead of
       being anchored. The rest of this project already learned that lesson —
       hymn_align anchors on parallagi degrees and martyria before trusting the
       path. This needs the same: pin the few high-confidence matches (t41 0.92,
       t44 0.82, t48 0.85) and align between them.

  v3 fixed cause (1): the parse now reads the red-font markup, so rubrics are no
  longer glued to the sung text, and the Horologion ordinary was added so the
  psalm verses exist at all. The canonical text (glt_oktoechos.json, 826 hymns)
  is now sound and independently useful.

  Cause (2) remains, and a THIRD is now the dominant one: GLT is deliberately
  over-split relative to a recorded hymn — median entry 148 chars against a hymn
  of 170-400 — but align() still assigns one hymn to exactly ONE entry. A hymn
  must be allowed to absorb a RUN of consecutive GLT entries, the same many-to-
  one shape boundary_fit.py already uses for drop-cap segments. Until that lands,
  similarities sit at 0.3-0.4 for structural reasons and mean nothing.

  Treat glt_hymn_match.json as a CANDIDATE list, not as hymn identification, and
  do not feed it to SYL-01.
"""
import argparse
import difflib
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units_h
from glt_fetch import norm, collapse, OUT as GLT_JSON

# workdir name -> GLT mode key
WD_MODE = {'mode1': 'mode1', 'mode1-orthros': 'mode1', 'mode2': 'mode2',
           'mode2-orthros': 'mode2', 'mode3': 'mode3', 'mode3-orthros': 'mode3',
           'mode4': 'mode4', 'grave': 'grave', 'grave-orthros': 'grave',
           'pl1-vespers': 'pl1', 'pl1-compunction': 'pl1', 'pl2': 'pl2',
           'pl4': 'pl4', 'pl4-orthros': 'pl4'}
# a workdir is ONE service, and GLT lists the same hymn separately under small
# vespers, great vespers and orthros. Filtering by service both sharpens the
# match and keeps the order constraint meaningful.
WD_SERVICE = {'orthros': ('orthros',),
              'vespers': ('small_vespers', 'great_vespers', 'vespers')}


def services_for(name):
    return WD_SERVICE['orthros'] if 'orthros' in name else WD_SERVICE['vespers']


def score_text(h):
    """the hymn slice's lyric stream, in reading order, collapsed-normalised"""
    _, lyr = load_units_h(h)
    lyr = sorted(lyr, key=lambda w: (w['page'], w.get('line', 0), w['x0']))
    return collapse(norm(''.join(w['text'] for w in lyr)))


def sim(a, b):
    """how much of the SCORE text this GLT hymn accounts for, mildly damped by
    gross length mismatch.

    Pure coverage-of-score is right in spirit — a recording often covers only
    part of a hymn, so the score text is a subset and a symmetric ratio punishes
    that unfairly — but on its own it is degenerate, because a long GLT blob
    covers almost any Greek text. The damping only bites when the GLT entry is
    far longer than the score; the ORDER constraint in align() does the real
    work of stopping one text being claimed by many hymns."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    cov = sum(bl.size for bl in sm.get_matching_blocks()) / max(len(a), 1)
    return cov * min(1.0, (len(a) / max(len(b), 1)) ** 0.25)


def align(scores, cands, gap_c=0.35, max_run=8):
    """Monotonic alignment of the hymn sequence to the GLT sequence.

    Two structures, both from the chanter:

    ORDER — "the hymns are already in order ... lord i have cried then the
    verses then the stichera then the glory both now doxastikon theotokia ...
    the order is the same". So this is a sequence alignment, not independent
    nearest-neighbour lookups; a monotonic path stops one text being claimed by
    seventeen hymns and stops matches running out of order.

    MANY-TO-ONE — "we can over split and then combine in another pass". The
    red-font reader deliberately over-splits GLT (median entry 148 chars against
    a recorded hymn of 170-400), so one hymn routinely spans a RUN of consecutive
    GLT entries: a Στίχ. plus its sticheron, a Δόξα plus the theotokion that
    follows, the whole Κύριε ἐκέκραξα block of psalm verses. Matching one hymn to
    exactly one entry pinned similarity at 0.3-0.4 for purely structural reasons.

    Skips are allowed on both sides: GLT holds hymns this tape never recorded,
    and the tape holds hymns GLT does not.
    Returns [(score_index, (glt_start, glt_end) or None, similarity)].
    """
    n, m = len(scores), len(cands)
    if not n or not m:
        return []
    # prefix-concatenated GLT text so a run's text is cheap to build
    pref = ['']
    for g in cands:
        pref.append(pref[-1] + g['collapsed'])
    NEG = -1e9
    D = [[NEG] * (m + 1) for _ in range(n + 1)]
    P = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for j in range(1, m + 1):
        D[0][j] = 0.0
        P[0][j] = (0, j - 1, None)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best_v, best_p = D[i - 1][j] - gap_c, (i - 1, j, None)
            if D[i][j - 1] > best_v:
                best_v, best_p = D[i][j - 1], (i, j - 1, None)
            for r in range(1, min(max_run, j) + 1):
                prev = D[i - 1][j - r]
                if prev <= NEG / 2:
                    continue
                run = pref[j][len(pref[j - r]):]
                v = prev + sim(scores[i - 1], run)
                if v > best_v:
                    best_v, best_p = v, (i - 1, j - r, (j - r, j))
            D[i][j], P[i][j] = best_v, best_p
    jend = max(range(m + 1), key=lambda j: D[n][j])
    i, j, out = n, jend, []
    while i > 0 or j > 0:
        pi, pj, span = P[i][j]
        if span:
            run = pref[span[1]][len(pref[span[0]]):]
            out.append((pi, span, sim(scores[pi], run)))
        elif pi != i:
            out.append((pi, None, 0.0))
        i, j = pi, pj
    out.reverse()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--all-modes', action='store_true')
    ap.add_argument('--min', type=float, default=0.55)
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/glt_hymn_match.json')
    a = ap.parse_args()

    glt = json.load(open(GLT_JSON))
    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    rows = []
    for wd in wds:
        hy = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hy):
            continue
        name = os.path.basename(wd.rstrip('/'))
        mode = WD_MODE.get(name)
        svc = services_for(name)
        # the ORDINARY is available to every mode: the psalm verses, Lord I Have
        # Cried, God Is The Lord and the rest are identical in all eight modes
        # (chanter), so they are never mode-discriminative but they ARE sung and
        # they DO occupy segments in the book.
        cands = [g for g in glt
                 if (g['mode'] == 'ordinary'
                     or ((a.all_modes or not mode or g['mode'] == mode)
                         and g['service'] in svc))]
        if not cands:
            cands = [g for g in glt if not mode or g['mode'] == mode] or glt
        print(f'\n=== {name}  ({len(cands)} candidate GLT hymns)')
        # both sides in liturgical order: hymns by (page, line), GLT as parsed
        hl = sorted(json.load(open(hy)), key=lambda h: (h['p0'], h['l0']))
        texts = [score_text(h) for h in hl]
        keep = [k for k, t in enumerate(texts) if len(t) >= 12]
        for k, h in enumerate(hl):
            if k not in keep:
                print(f'  {h["name"][:24]:24s} NO LYRICS')
        path = align([texts[k] for k in keep], cands)
        for si, span, sc in path:
            h = hl[keep[si]]
            if span is None:
                print(f'  --  {h["name"][:22]:22s} unaligned')
                rows.append({'workdir': name, 'hymn': h['name'], 'coverage': 0.0,
                             'glt_page': None, 'glt_service': None,
                             'glt_heading': None, 'glt_text': '',
                             'score_chars': len(texts[keep[si]])})
                continue
            run = cands[span[0]:span[1]]
            g = run[0]
            text = ' '.join(x['text'] for x in run)
            flag = 'ok ' if sc >= a.min else 'LOW'
            rows.append({'workdir': name, 'hymn': h['name'], 'coverage': round(sc, 3),
                         'glt_page': g['page'], 'glt_service': g['service'],
                         'glt_heading': g['heading'], 'glt_text': text,
                         'glt_n_entries': len(run),
                         'score_chars': len(texts[keep[si]]),
                         'glt_chars': sum(len(x['collapsed']) for x in run)})
            print(f'  {flag} {h["name"][:22]:22s} sim {sc:.2f} x{len(run)} '
                  f'{g["service"][:12]:12s} {text[:48]}')
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=1)
    good = sum(1 for r in rows if r['coverage'] >= a.min)
    print(f'\n{good}/{len(rows)} matched at >= {a.min} coverage -> {a.out}')


if __name__ == '__main__':
    main()
