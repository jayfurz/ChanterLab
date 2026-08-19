#!/usr/bin/env python3
"""Automatic mode onboarding: match each track of an album against the book's
lyric stream to produce hymns.json for hymn_align.py.

For every transcript of the album's tracks:
  - classify parallagi vs melos by degree-lexicon word fraction,
  - melos: fuzzy-locate the sung text in the mode section's lyric stream
    (normalized, melisma-collapsed, drop-cap tolerant) -> (page, line) range,
  - parallagi: inherit the page range of the nearest following melos track
    (Vasilikos chants parallagi immediately before the melos of the same hymn).

Usage: locate_tracks.py --pages A B --audio-dir DIR --out hymns.json
       [--transcripts /mnt/data/chant-corpus/transcripts]
"""
import json, os, re, sys, unicodedata
from difflib import SequenceMatcher

GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
LEX = {'πα', 'βου', 'γα', 'δι', 'κε', 'ζω', 'νη', 'νε', 'νι', 'μπου', 'γκα',
       'ντι', 'και', 'ζο', 'βι', 'πω', 'μη', 'νυ'}

def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^α-ω]', '', s.replace('ς', 'σ'))

def collapse(s):
    return re.sub(r'(.)\1+', r'\1', s)

def main():
    a = sys.argv
    p0, p1 = int(a[a.index('--pages') + 1]), int(a[a.index('--pages') + 2])
    audio_dir = a[a.index('--audio-dir') + 1]
    out = a[a.index('--out') + 1]
    tdir = a[a.index('--transcripts') + 1] if '--transcripts' in a \
        else '/mnt/data/chant-corpus/transcripts'
    # book stream
    hay, anchors = [], []
    for p in range(p0, p1 + 1):
        f = os.path.join(GLYPHS, f'page{p:03d}.json')
        if not os.path.exists(f):
            continue
        d = json.load(open(f))
        for w in d.get('lyrics', []):
            t = norm(w['text'])
            for ch in t:
                if hay and ch == hay[-1]:
                    continue
                hay.append(ch)
                anchors.append((p, w.get('line', 0)))
    hay = ''.join(hay)
    tracks = sorted(fn for fn in os.listdir(audio_dir)
                    if fn.lower().endswith(('.mp3', '.m4a', '.wav')))
    rows = []
    for fn in tracks:
        stem = os.path.splitext(fn)[0]
        tf = os.path.join(tdir, stem + '.json')
        if not os.path.exists(tf):
            rows.append({'track': fn, 'kind': 'pending'})
            continue
        d = json.load(open(tf))
        words = [w['word'].strip() for s in d.get('segments', [])
                 for w in s.get('words', [])]
        if len(words) < 6:
            rows.append({'track': fn, 'kind': 'too-few-words'})
            continue
        lexfrac = sum(1 for w in words if norm(w) in LEX or
                      collapse(norm(w)) in LEX) / len(words)
        if lexfrac > 0.5:
            rows.append({'track': fn, 'kind': 'parallagi'})
            continue
        needle = collapse(norm(' '.join(words)))[:400]
        if len(needle) < 25:
            rows.append({'track': fn, 'kind': 'too-short'})
            continue
        sm = SequenceMatcher(None, hay, needle, autojunk=False)
        m = sm.find_longest_match(0, len(hay), 0, len(needle))
        ratio = m.size / len(needle)
        if m.size < 20:
            rows.append({'track': fn, 'kind': 'unmatched'})
            continue
        # start anchor: walk back from the matched block by its needle offset
        start_i = max(m.a - m.b, 0)
        end_i = min(m.a + (len(needle) - m.b), len(hay) - 1)
        pa, la = anchors[start_i]
        pb, lb = anchors[end_i]
        rows.append({'track': fn, 'kind': 'melos', 'p0': pa, 'l0': la,
                     'p1': pb, 'l1': lb + 1, 'match_frac': round(ratio, 2),
                     'melos_audio': os.path.join(audio_dir, fn)})
    # parallagi inherit next melos range
    for i, r in enumerate(rows):
        if r['kind'] != 'parallagi':
            continue
        nxt = next((x for x in rows[i + 1:i + 3] if x['kind'] == 'melos'), None)
        if nxt:
            r.update({k: nxt[k] for k in ('p0', 'l0', 'p1', 'l1')})
            r['pairs_with'] = nxt['track']
    hymns = []
    for i, r in enumerate(rows):
        if r['kind'] != 'melos':
            continue
        par = next((x for x in rows[max(0, i - 2):i]
                    if x.get('kind') == 'parallagi' and x.get('p0') == r['p0']), None)
        hymns.append({'name': f"t{i:02d}_{norm(r['track'])[:18]}",
                      'p0': r['p0'], 'l0': r['l0'], 'p1': r['p1'], 'l1': r['l1'],
                      'melos_audio': r['melos_audio'],
                      'parallagi_track': par['track'] if par else None,
                      'parallagi_dir': None,
                      'match_frac': r['match_frac']})
    json.dump(hymns, open(out, 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    print(Counter(r['kind'] for r in rows))
    for h in hymns:
        print(f"  {h['name']:24s} p{h['p0']}.{h['l0']}-p{h['p1']}.{h['l1']} "
              f"match {h['match_frac']} par={bool(h['parallagi_track'])}")
    print(f"{len(hymns)} hymns -> {out}")

if __name__ == '__main__':
    main()
