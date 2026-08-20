#!/usr/bin/env python3
"""span_names.py — name each span by the first words of its melos.

Chanter: "can we name them by the first few words of the melos (and the
corresponding parallagi also named)".

The name comes from the SCORE, not the audio. Every span has a chanter-marked
score range, and the book carries a lyric layer, so the incipit is readable
without any of the identification that has been failing. A parallagi and its
melos share a score range, so they get the same name with the lane appended.

Two details the lyric layer forces:

  - It is syllabified with no word boundaries ("Κα τε λυ σας τωσταυ ρω ω σου"),
    so words are rebuilt from the x-gaps between syllables rather than from
    spacing in the text.
  - The opening drop cap is a separate large glyph and is absent from the lyric
    layer, so "ατελυσας" needs its Κ restored from dropcaps.json.

Usage:  span_names.py --workdir grave-orthros [--write]
"""
import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units

SCORES = '/mnt/data/chant-corpus/scores'
TEXTS = '/mnt/data/chant-corpus/texts'


def strip_accents(t):
    t = unicodedata.normalize('NFD', t)
    return ''.join(c for c in t if not unicodedata.combining(c))


def slug(t, n=48):
    t = strip_accents(t).lower()
    t = re.sub(r'[^a-zα-ω0-9]+', '-', t).strip('-')
    return t[:n].rstrip('-')


class Book:
    def __init__(self):
        self.u, self.g = {}, {}
        self.caps = json.load(open(f'{SCORES}/dropcaps.json'))

    def units(self, p):
        if p not in self.u:
            try:
                self.u[p] = load_units(p, 0, p, 10 ** 6)[0]
            except Exception:
                self.u[p] = []
        return self.u[p]

    def lyrics(self, p):
        if p not in self.g:
            f = f'{SCORES}/glyphs/page{p}.json'
            self.g[p] = (json.load(open(f)).get('lyrics', [])
                         if os.path.exists(f) else [])
        return self.g[p]

    def incipit(self, c, nwords=4):
        us = self.units(c['p0'])
        if c['g0'] >= len(us):
            return ''
        x0, ln = us[c['g0']]['x0'], c['l0']
        ly = sorted((w for w in self.lyrics(c['p0'])
                     if w.get('line') == ln and w['x1'] >= x0 - 8),
                    key=lambda w: w['x0'])
        if not ly:
            return ''
        # rebuild words: a gap wider than the typical inter-syllable space
        # starts a new word
        gaps = [ly[i + 1]['x0'] - ly[i]['x1'] for i in range(len(ly) - 1)]
        thr = (sorted(gaps)[len(gaps) // 2] + 3.0) if gaps else 3.0
        words, cur = [], [ly[0].get('text', '')]
        for i in range(1, len(ly)):
            if ly[i]['x0'] - ly[i - 1]['x1'] > thr:
                words.append(''.join(cur))
                cur = []
            cur.append(ly[i].get('text', ''))
        words.append(''.join(cur))
        # restore the drop cap the lyric layer omits
        cap = [q for q in self.caps
               if q['page'] == c['p0'] and q['line'] == ln
               and abs(q['x0'] - x0) < 80 and q.get('size', 0) >= 18]
        if cap and words:
            words[0] = cap[0]['letter'] + words[0]
        # collapse held vowels: "ρωω" -> "ρω"
        words = [re.sub(r'(.)\1{1,}', r'\1', w) for w in words]
        return ' '.join(w for w in words[:nwords] if w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--words', type=int, default=4)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    wd = a.workdir
    cuts = sorted(json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts'],
                  key=lambda c: c['t0'])
    sc = {c['hymn']: c for c in
          json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}
    book = Book()

    out = []
    for i, c in enumerate(cuts, 1):
        s = sc.get(c['hymn'])
        text = book.incipit(s, a.words) if s else ''
        lane = c.get('lane') or 'unset'
        # the id wants to be short and stable; the full incipit stays in
        # 'incipit' for display
        name = slug(' '.join(text.split()[:3]), 30) or c['hymn']
        pid = f'{wd}-{name}' + ('-parallagi' if lane == 'parallagi' else '')
        if any(o['piece_id'] == pid for o in out):      # keep ids unique
            pid = f'{pid}-{i:02d}'
        out.append({'span': c['hymn'], 'ordinal': i, 'lane': lane,
                    'incipit': text, 'piece_id': pid,
                    't0': c['t0'], 't1': c['t1']})
        print('  #%02d %-9s %-34s %s' % (i, lane, text[:34], pid[:46]))

    # a parallagi and its melos must agree, since they share a score range
    bad = 0
    for i in range(1, len(out)):
        if out[i]['lane'] == 'melos' and out[i - 1]['lane'] == 'parallagi':
            if out[i]['incipit'] != out[i - 1]['incipit']:
                bad += 1
                print('    ! pair #%02d/#%02d disagree: %r vs %r'
                      % (i, i + 1, out[i - 1]['incipit'][:24],
                         out[i]['incipit'][:24]))
    named = sum(1 for o in out if o['incipit'])
    print(f'\n{named}/{len(out)} named from the score; {bad} pair mismatch(es)')
    if a.write:
        p = f'{TEXTS}/span_names_{wd}.json'
        json.dump({'workdir': wd, 'spans': out}, open(p, 'w'),
                  indent=1, ensure_ascii=False)
        print(f'-> {p}')


if __name__ == '__main__':
    main()
