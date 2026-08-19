#!/usr/bin/env python3
"""Re-match one track transcript against a constrained book-page window
(same normalization/matching as locate_tracks.py). Prints the found range.

Usage: relocate_track.py <transcript.json> <p0> <p1>
"""
import json, os, re, sys, unicodedata
from difflib import SequenceMatcher

GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'

def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^α-ω]', '', s.replace('ς', 'σ'))

def collapse(s):
    return re.sub(r'(.)\1+', r'\1', s)

def main():
    tf, p0, p1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
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
    d = json.load(open(tf))
    words = [w['word'].strip() for s in d.get('segments', [])
             for w in s.get('words', [])]
    needle = collapse(norm(' '.join(words)))[:400]
    sm = SequenceMatcher(None, hay, needle, autojunk=False)
    m = sm.find_longest_match(0, len(hay), 0, len(needle))
    ratio = m.size / max(len(needle), 1)
    start_i = max(m.a - m.b, 0)
    end_i = min(m.a + (len(needle) - m.b), len(hay) - 1)
    pa, la = anchors[start_i]
    pb, lb = anchors[end_i]
    print(json.dumps({'p0': pa, 'l0': la, 'p1': pb, 'l1': lb + 1,
                      'match_frac': round(ratio, 2), 'block': m.size,
                      'needle_len': len(needle)}))

if __name__ == '__main__':
    main()
