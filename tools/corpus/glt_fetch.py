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
from html.parser import HTMLParser

BASE = 'https://glt.goarch.org/texts/Och/'
SITE = 'https://glt.goarch.org/texts/'
CACHE = '/mnt/data/chant-corpus/texts/glt'
OUT = '/mnt/data/chant-corpus/texts/glt_oktoechos.json'
# GLT tone number -> the mode name this corpus uses
TONE_MODE = {1: 'mode1', 2: 'mode2', 3: 'mode3', 4: 'mode4',
             5: 'pl1', 6: 'pl2', 7: 'grave', 8: 'pl4'}
PAGES = ([f'Tone{n}Sun.html' for n in range(1, 9)]
         + [f'Eothina{n}.html' for n in range(1, 12)])
# The ORDINARY. Chanter: the psalm verses "all repeat in every single mode" —
# Lord I Have Cried, Let My Prayer, God Is The Lord, the 22 short verses up to
# ἐκ βαθέων ἐκέκραξά σοι and γενηθήτω τὰ ὦτά σου, and the verse before the
# stichera, ἐξάγαγε ἐκ φυλακῆς τὴν ψυχήν μου. None of them are in the Oktoechos
# pages, which carry only the mode-proper hymns — they live in the Horologion.
# Without these, ~22 recorded segments per mode have no canonical text at all,
# which is why so much of the book had nothing to match against.
ORDINARY = ['Oro/Esperinos.html', 'Oro/Esperinos%20Sunday.html',
            'Synek/orthrosegkolpion.html']
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


class GLTReader(HTMLParser):
    """Reads GLT markup structurally instead of guessing from plain text.

    The site marks rubrics exactly the way the printed book does — in RED:

        <FONT COLOR="#ff0000">Ὁ Εἱρμὸς</FONT><br/>«Νεύσει σοῦ πρὸς γεώδη, ...

    so "Ὁ Εἱρμὸς", "Στίχ.", "Ἦχος βαρὺς", "ᾨδὴ α'" and the rest are red, and the
    sung text is plain. The first parser flattened the HTML and tried to spot
    rubrics with a regex on the resulting text, which glued them onto the first
    line of the hymn ("Ὁ Εἱρμὸς «Νεύσει σοῦ ...") and polluted every match. The
    colour is unambiguous and free — use it.

    Blue is the ΤΟ ΑΚΟΥΤΕ audio link; skip it entirely. </p> ends a hymn.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.runs = []            # (kind, text): kind in {red, text, break}
        self._red = 0
        self._skip = 0

    def _color(self, attrs):
        for k, v in attrs:
            if k.lower() == 'color' and v:
                return v.strip().lower().lstrip('#')
        return None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == 'font':
            c = self._color(attrs)
            if c and c.startswith('ff0000'):
                self._red += 1
                return
            if c and (c.startswith('0000ff') or c.startswith('00f')):
                self._skip += 1
                return
            self._red += 0
        elif t == 'a':
            self._skip += 1
        elif t in ('br', 'p', 'div', 'tr'):
            self.runs.append(('break', ''))
        elif t in ('script', 'style'):
            self._skip += 1

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == 'font':
            if self._skip:
                self._skip -= 1
            elif self._red:
                self._red -= 1
        elif t == 'a':
            self._skip = max(0, self._skip - 1)
        elif t in ('script', 'style'):
            self._skip = max(0, self._skip - 1)
        elif t in ('p', 'div', 'tr'):
            self.runs.append(('para', ''))

    def handle_data(self, data):
        d = re.sub(r'\s+', ' ', data)
        if not d.strip() or self._skip:
            return
        self.runs.append(('red' if self._red else 'text', d))


def read_runs(raw):
    r = GLTReader()
    r.feed(raw)
    return r.runs


def parse(page, runs):
    """-> [{tone, mode, service, heading, text, norm, collapsed}]

    A hymn is a maximal run of PLAIN text. Red text is a rubric: it closes the
    hymn in progress and becomes the next one's heading. </p> also closes.
    """
    m = re.match(r'Tone(\d)Sun', page)
    tone = int(m.group(1)) if m else None
    eoth = re.match(r'Eothina(\d+)', page)
    ordinary = page.startswith(('Oro/', 'Synek/'))
    hymns, service = [], ('orthros' if 'orthros' in page.lower()
                          else 'eothinon' if eoth else 'vespers')
    heading, pending, buf = '', [], []

    def flush():
        if not buf:
            return
        text = ' '.join(' '.join(buf).split())
        n = norm(text)
        if len(n) >= 12:
            hymns.append({
                'page': page, 'tone': tone,
                'mode': ('ordinary' if ordinary else
                         TONE_MODE.get(tone) if tone
                         else f'eothinon{eoth.group(1)}'),
                'service': service, 'heading': heading,
                'text': text, 'norm': n, 'collapsed': collapse(n),
            })
        buf.clear()

    for kind, txt in runs:
        if kind in ('break', 'para'):
            if kind == 'para':
                flush()
            continue
        if kind == 'red':
            pending.append(txt.strip())
            flush()
            continue
        if pending:
            heading = ' '.join(' '.join(pending).split())
            pending = []
            up = heading.upper()
            hit = next((sv for pat, sv in SERVICE if re.search(pat, up)), None)
            if hit:
                service = hit
        buf.append(txt.strip())
    flush()
    # a service heading can also arrive as an all-caps plain line
    for h in hymns:
        up = h['text'].upper()
        if len(h['text']) < 60:
            hit = next((sv for pat, sv in SERVICE if re.search(pat, up)), None)
            if hit:
                h['service'] = hit
    return hymns


def fetch(page, refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    url = (SITE + page) if '/' in page else (BASE + page)
    path = os.path.join(CACHE, page.replace('/', '_').replace('%20', '_'))
    if refresh or not os.path.exists(path):
        subprocess.run(['curl', '-sS', '-m', '40', '-o', path, url], check=True)
    return open(path, encoding='utf-8', errors='replace').read()


# --- combine pass -------------------------------------------------------
# Chanter: "we can over split and then combine in another pass". The red-font
# reader deliberately splits at every rubric and every </p>, which cuts a hymn
# into its stanzas; this pass glues them back into hymn-level units.
#
# Which rubrics actually START a hymn is a liturgical question, and the chanter
# gave the rules that matter:
#   * "the verse preceding the stichera might be treated as a short hymn but it
#     is actually attached to the following hymn"  -> Στίχ. merges FORWARD
#   * "the same with the glory and both now followed by the theotokia" -> Δόξα /
#     Καὶ νῦν head a unit that continues into the theotokion that follows
HYMN_START = re.compile(
    "^(Ἦχος|Ήχος|Ὁ Εἱρμ|Ο Ειρμ|ᾨδὴ|Ωδη|Δόξα|Καὶ νῦν|Και νυν|Θεοτοκίον|Θεοτοκια|"
    "Ἀπολυτίκιον|Απολυτικιον|Κάθισμα|Καθίσματα|Ἐξαποστειλ|Κοντάκιον|Οἶκος|"
    "Ὑπακοή|Προκείμ|Αἶνοι|Ἀναβαθμ|Μακαρισμ|Εὐλογητ|Στιχηρ|Αὐτόμελ|Άυτόμελ|"
    "Ἄλλο|Ἕτερο|Ἀπόστιχα|Εἰς τὸν Στίχον)")
# a psalm verse: never its own hymn, always attached to what follows
VERSE = re.compile("^(Στίχ|Στιχ|\\(Δίς\\)|Δίς)")


def combine_parts(hymns):
    """merge the over-split entries into hymn-level units"""
    out = []
    for h in hymns:
        head = (h.get('heading') or '').strip()
        new = (not out
               or out[-1]['page'] != h['page']
               or out[-1]['service'] != h['service']
               or (bool(HYMN_START.match(head)) and not VERSE.match(head)))
        if new:
            g = dict(h)
            g['parts'] = [h['text']]
            g['headings'] = [head] if head else []
            out.append(g)
        else:
            g = out[-1]
            g['parts'].append(h['text'])
            if head:
                g['headings'].append(head)
            g['text'] = (g['text'] + ' ' + h['text']).strip()
            g['norm'] = norm(g['text'])
            g['collapsed'] = collapse(g['norm'])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()
    all_h = []
    split_h = []
    for p in PAGES + ORDINARY:
        try:
            h = parse(p, read_runs(fetch(p, a.refresh)))
        except Exception as e:
            print(f'  {p}: FAILED {e}')
            continue
        split_h += h              # the over-split form, before combining
        h = combine_parts(h)
        all_h += h
        print(f'  {p:20s} {len(h):4d} hymns')
    json.dump(all_h, open(OUT, 'w'), ensure_ascii=False, indent=1)
    # The over-split form is what forced alignment wants: it scores RUNS of
    # consecutive entries against the audio, so it needs the pieces, not a
    # pre-combined guess. Combining is a liturgical judgement; CTC likelihood is
    # an acoustic measurement, and the measurement should get the raw material.
    sp = OUT.replace('.json', '_split.json')
    for g in split_h:
        g.pop('_w', None)
    json.dump(split_h, open(sp, 'w'), ensure_ascii=False, indent=1)
    print(f'\n{len(all_h)} hymns -> {OUT}')
    print(f'{len(split_h)} over-split entries -> {sp}')


if __name__ == '__main__':
    main()
