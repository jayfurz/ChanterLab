#!/usr/bin/env python3
"""glt_fetch.py — fetch and parse the Oktoechos (Παρακλητική) from glt.goarch.org.

The score's own text layer is unaccented and melisma-fragmented ('τω','σταυ',
'ρω','ω'), which is enough to align but NOT enough to syllabify: Greek
syllabification needs the word, and word reconstruction needs to know which word
it is. glt.goarch.org publishes the same hymns as fully accented polytonic
Greek, which gives three things at once:

  1. correct words and inflections, for SYL-01
  2. canonical incipits, for verifying hymn boundaries (p0/l0..p1/l1 and g0/g1)
  3. a lexicon that is actually liturgical rather than scraped from fragments

Sunday Vespers + Orthros for all 8 modes live at texts/Och/Tone{1..8}Sun.html;
the eleven Eothina at texts/Och/Eothina{1..11}.html. Tone7 = βαρύς (grave),
Tone5/6/8 = plagal 1/2/4.

Usage:  glt_fetch.py [--refresh]      writes texts/glt_oktoechos.json
"""
import argparse
import json
import os
import re
import html
import subprocess
import unicodedata

BASE = 'https://glt.goarch.org/texts/Och/'
CACHE = '/mnt/data/chant-corpus/texts/glt'
OUT = '/mnt/data/chant-corpus/texts/glt_oktoechos.json'
# GLT tone number -> the mode name this corpus uses
TONE_MODE = {1: 'mode1', 2: 'mode2', 3: 'mode3', 4: 'mode4',
             5: 'pl1', 6: 'pl2', 7: 'grave', 8: 'pl4'}
PAGES = ([f'Tone{n}Sun.html' for n in range(1, 9)]
         + [f'Eothina{n}.html' for n in range(1, 12)])
SERVICE = [
    (r'ΜΙΚΡ\w*\s+ΕΣΠΕΡΙΝ', 'small_vespers'),
    (r'ΜΕΓΑΛ\w*\s+ΕΣΠΕΡΙΝ', 'great_vespers'),
    (r'ΕΣΠΕΡΙΝ', 'vespers'),
    (r'ΟΡΘΡ', 'orthros'),
]
# a heading line, not sung text: rubrics, mode marks, psalm verses
HEADING = re.compile(r'^(Ἦχος|Ήχος|Στίχ|Δόξα|Καὶ νῦν|Και νυν|Θεοτοκίον|Δογματικόν|'
                     r'Ἀπολυτίκιον|Απολυτικιον|Κοντάκιον|Οἶκος|Ὁ Οἶκος|Καθίσματα|'
                     r'Κάθισμα|ᾨδὴ|Ωδη|Εἱρμός|Ὁ Εἱρμός|Καταβασία|Ἐξαποστειλάριον|'
                     r'Πρὸς τό|Αὐτόμελον|Άυτόμελον|Στιχηρὰ|Στιχηρά|Εἰς τὸν Στίχον|'
                     r'Ἀναβαθμοί|Προκείμενον|Εὐλογητάρια|Ὑπακοή|Αἶνοι|ΑΙΝΟΙ|Τάξις|'
                     r'Μετὰ τὴν|Ἕτερον|Ἄλλο|Τὸ Α|ΤΟ ΑΚΟΥΤΕ)', re.I)
# the rubric phrase itself: the heading word plus the article/mode tail
# that follows it, so it is removed from the sung text as well
RUBRIC_TAIL = re.compile(
    r"^\S+(\s+(τοῦ|τῆς|τὸ|ὁ|ἡ|Ὀ|Ἡ|Τὸ|ἦχου|ήχου|ῆχου|ἦχος|Ήχος|"
    r"[αβγδ]'|πλ\.|βαρύς|βαρὺς|αὐτόμελον|Αὐτόμελον)){1,4}", re.I)


# Some GLT pages run a whole appendix into one paragraph with no line breaks -
# the eight-mode Theotokia are the worst case, all eight in a single <p> with
# only an inline rubric between them. Split on the rubric wherever it appears,
# otherwise one 2000-character blob swallows eight separate hymns and any
# boundary check against it is meaningless.
INLINE_SPLIT = re.compile(
    r'(?=\u0398\u03b5\u03bf\u03c4\u03bf\u03ba\u03af\u03bf\u03bd\s+\u03c4\u03bf\u1fe6\s+[\u1fc6\u03ae\u1f26]\u03c7\u03bf\u03c5)|'
    r'(?=\u1f4c\s+\u0395\u1f31\u03c1\u03bc\u1f78\u03c2)|'
    r'(?=\u1f26\u03c7\u03bf\u03c2\s+[\u03b1\u03b2\u03b3\u03b4]\')')


def norm(s):
    """fold to the form the score's lyric layer can be compared against:
    accents/breathings stripped, lowercase, final sigma folded, letters only."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('ς', 'σ')
    return re.sub(r'[^α-ω]', '', s)


def collapse(s):
    """collapse runs of one letter — the melisma reprints the vowel per note"""
    return re.sub(r'(.)\1+', r'\1', s)


def strip_html(raw):
    raw = re.sub(r'(?is)<(script|style).*?</\1>', ' ', raw)
    raw = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>', '\n', raw)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    out = [re.sub(r'\s+', ' ', l).strip() for l in html.unescape(raw).split('\n')]
    return [l for l in out if l]


def fetch(page, refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, page)
    if refresh or not os.path.exists(path):
        subprocess.run(['curl', '-sS', '-m', '40', '-o', path, BASE + page],
                       check=True)
    return open(path, encoding='utf-8', errors='replace').read()


def parse(page, lines):
    """-> [{tone, mode, service, heading, text, norm, collapsed}]"""
    m = re.match(r'Tone(\d)Sun', page)
    tone = int(m.group(1)) if m else None
    eoth = re.match(r'Eothina(\d+)', page)
    hymns, service, heading, buf = [], ('eothinon' if eoth else 'vespers'), '', []

    def flush():
        if not buf:
            return
        for text in INLINE_SPLIT.split(' '.join(buf)):
            text = text.strip()
            n = norm(text)
            if len(n) < 12:              # ignore stray fragments
                continue
            hymns.append({
                'page': page, 'tone': tone,
                'mode': TONE_MODE.get(tone) if tone else f'eothinon{eoth.group(1)}',
                'service': service, 'heading': heading,
                'text': text, 'norm': n, 'collapsed': collapse(n),
            })
        buf.clear()

    for l in lines:
        up = l.upper()
        hit = next((s for pat, s in SERVICE if re.search(pat, up)), None)
        if hit and len(l) < 60:
            flush(); service = hit; heading = ''; continue
        m = HEADING.match(l)
        if m:
            # GLT often runs the rubric and the first line of the hymn together
            # ("Theotokion tou echou a' Idou peplirotai ..."). Treating that
            # whole line as text merges several hymns into one entry, which
            # makes any boundary check meaningless - split the rubric off and
            # keep the remainder as sung text.
            flush()
            if len(l) < 90:
                heading = l
            else:
                cut = RUBRIC_TAIL.match(l)
                end = cut.end() if cut else m.end()
                heading = l[:end].strip()
                rest = l[end:].strip()
                if rest:
                    buf.append(rest)
            continue
        if l.isupper() and len(l) < 60:
            flush(); heading = l; continue
        buf.append(re.sub(r'\s*ΤΟ ΑΚΟΥΤΕ\s*', ' ', l).strip())
    flush()
    return hymns


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()
    all_h = []
    for p in PAGES:
        try:
            h = parse(p, strip_html(fetch(p, a.refresh)))
        except Exception as e:
            print(f'  {p}: FAILED {e}')
            continue
        all_h += h
        print(f'  {p:20s} {len(h):4d} hymns')
    json.dump(all_h, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'\n{len(all_h)} hymns -> {OUT}')


if __name__ == '__main__':
    main()
