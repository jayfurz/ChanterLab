#!/usr/bin/env python3
"""dropcap_check.py — drop caps as a hymn-boundary check, labelled by GLT.

The chanter's first rule for finding a hymn in the book: "easy way to tell the
start of a hymn is the drop cap (big red letters) as well as the martyria symbol
that usually comes before". The drop cap is the first letter of the hymn — and
now that glt_match.py knows which canonical hymn each corpus slice is, GLT
supplies that letter as a LABEL. So the two check each other:

  * agreement validates the drop-cap alphabet (the ANNA2000 initials layer uses
    lookalike codepoints: INCREMENT for Delta, OHM SIGN for Omega, Latin N)
  * disagreement means the slice does not start where the book says the hymn
    starts, or the GLT match is wrong — which is exactly the t01 bug, found by
    hand at the start of this work

Drop caps come from `scores/book_map.json` (extract_book's ANNA2000 initials,
font size > 18); no visual classifier is needed to read them, only this map.

Usage:  dropcap_check.py [--min-cov 0.55]
"""
import argparse
import json
import os
import unicodedata

BOOK = '/mnt/data/chant-corpus/scores/book_map.json'
MATCH = '/mnt/data/chant-corpus/texts/glt_hymn_match.json'
# the initials layer substitutes lookalikes for three Greek capitals
LOOKALIKE = {'∆': 'Δ',   # INCREMENT      -> Delta
             'Ω': 'Ω',   # OHM SIGN       -> Omega
             'N': 'Ν'}   # LATIN N        -> Nu


def fold(ch):
    """drop cap glyph -> plain Greek capital"""
    ch = LOOKALIKE.get(ch, ch)
    d = unicodedata.normalize('NFD', ch)
    d = ''.join(c for c in d if not unicodedata.combining(c))
    return d.upper()


def initial_of(text):
    """first Greek capital of a canonical GLT hymn text"""
    for ch in text:
        f = fold(ch)
        if 'Α' <= f <= 'Ω':
            return f
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--min-cov', type=float, default=0.55)
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/dropcap_check.json')
    a = ap.parse_args()

    caps = {}
    for p in json.load(open(BOOK))['pages']:
        s = set()
        for t in p.get('initials', []):
            for ch in t:
                f = fold(ch)
                if 'Α' <= f <= 'Ω':
                    s.add(f)
        if s:
            caps[p['page']] = s

    hymns = {}
    for wd in os.listdir('/mnt/data/chant-corpus/workdirs'):
        hy = f'/mnt/data/chant-corpus/workdirs/{wd}/hymns.json'
        if os.path.exists(hy):
            for h in json.load(open(hy)):
                hymns[(wd, h['name'])] = h

    rows, agree, checked = [], 0, 0
    for m in json.load(open(MATCH)):
        h = hymns.get((m['workdir'], m['hymn']))
        if not h:
            continue
        want = initial_of(m['glt_text'])
        page = h['p0']
        on_page = caps.get(page, set())
        ok = bool(want and want in on_page)
        row = {**{k: m[k] for k in ('workdir', 'hymn', 'coverage')},
               'page': page, 'expected_initial': want,
               'drop_caps_on_page': ''.join(sorted(on_page)), 'agrees': ok}
        rows.append(row)
        if m['coverage'] >= a.min_cov and want:
            checked += 1
            agree += ok
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=1)

    print(f'drop caps: {sum(len(v) for v in caps.values())} distinct-per-page '
          f'over {len(caps)} pages')
    print(f'hymns checked (GLT coverage >= {a.min_cov}): {checked}')
    print(f'drop cap on the start page matches the canonical initial: '
          f'{agree}/{checked} ({100*agree/max(checked,1):.0f}%)')
    bad = [r for r in rows if r['coverage'] >= a.min_cov and r['expected_initial']
           and not r['agrees']]
    if bad:
        print(f'\n{len(bad)} disagreements — boundary or match to review:')
        for r in bad[:20]:
            print(f"  {r['workdir']:16s} {r['hymn'][:20]:20s} p{r['page']} "
                  f"want {r['expected_initial']}  page has [{r['drop_caps_on_page']}]"
                  f"  cov {r['coverage']}")
    print(f'\n-> {a.out}')


if __name__ == '__main__':
    main()
