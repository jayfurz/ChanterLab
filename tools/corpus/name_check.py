#!/usr/bin/env python3
"""name_check.py — score identification against the hymn names themselves.

56 of the 173 hymns are named with a transliterated incipit rather than a
sequence number: mode2, mode3, mode3-orthros, pl1-compunction and pl1-vespers
use names like `kyrie-ekekraxa`, `ean-anomias`, `ek-vatheon-doxazo`. Those names
came from the chanter's own foldering, so they are independent of anything the
CTC solver does — which makes them a free 56-hymn accuracy check on the whole
identification pipeline, with no new labelling.

The test: transliterate the assigned text's opening words to Latin and ask
whether the hymn's name appears in it. It cannot prove an assignment right (a
name only covers the incipit), but a name that does NOT appear is strong
evidence the text is wrong.

Usage:  name_check.py [--workdir NAME]
"""
import argparse
import difflib
import glob
import json
import os
import re
import unicodedata

# A hymn's own incipit should open its span. Allow a little slack for a
# leading rubric or an initial the OCR split off, but not a whole verse.
EARLY_CHARS = 25

# The chanter's own romanisation, longest digraphs first.
MAP = [('ευ', 'ef'), ('αυ', 'af'), ('ου', 'ou'), ('αι', 'e'), ('ει', 'i'),
       ('οι', 'i'), ('υι', 'i'), ('γγ', 'ng'), ('μπ', 'b'), ('ντ', 'd'),
       ('θ', 'th'), ('χ', 'ch'), ('ψ', 'ps'), ('ξ', 'x'), ('φ', 'f'),
       ('β', 'v'), ('γ', 'g'), ('δ', 'd'), ('ζ', 'z'), ('η', 'i'),
       ('υ', 'y'), ('ω', 'o'), ('ς', 's'), ('σ', 's'), ('α', 'a'),
       ('ε', 'e'), ('ι', 'i'), ('κ', 'k'), ('λ', 'l'), ('μ', 'm'),
       ('ν', 'n'), ('ο', 'o'), ('π', 'p'), ('ρ', 'r'), ('τ', 't')]


def translit(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for a, b in MAP:
        s = s.replace(a, b)
    return re.sub(r'[^a-z]+', '', s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir')
    ap.add_argument('--show-all', action='store_true')
    a = ap.parse_args()

    hit = miss = late = 0
    for f in sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/hymns.json')):
        w = f.split('/')[-2]
        if a.workdir and w != a.workdir:
            continue
        af = f'/mnt/data/chant-corpus/texts/tapeassign_{w}.json'
        if not os.path.exists(af):
            continue
        A = {x['hymn']: x for x in json.load(open(af))['assigned']}
        for h in json.load(open(f)):
            n = h['name']
            key = re.sub(r'[^a-z]+', '', n.lower())
            # Sequence names (t01_, t04_005) carry no text. They reduce to a
            # bare 't', which then fuzzy-matches nearly any opening and scores
            # a spurious 1.00 — so require a real incipit, not a stub.
            if len(key) < 6:
                continue
            r = A.get(n)
            if not r:
                continue
            # Names are often truncated ("ina-to-genos-frag"), so slide the
            # name over the text and keep the best-scoring window. WHERE it
            # lands matters as much as whether it lands: a name is an incipit,
            # so a match at offset 0 means the span starts on the hymn, and a
            # match deep into the text means the span opens on the material
            # BEFORE it — the chanter's "starts an entire line too early",
            # measured in the audio instead of the score.
            full = translit(r['text'])
            best, at = 0.0, 0
            for i in range(max(len(full) - len(key), 0) + 1):
                v = difflib.SequenceMatcher(
                    None, key, full[i:i + len(key)]).ratio()
                if v > best:
                    best, at = v, i
            found = best >= 0.62
            early = found and at > EARLY_CHARS
            if found and not early:
                hit += 1
            else:
                miss += 1
            if found and early:
                late += 1
            tag = 'ok' if (found and not early) else (
                'STARTS-EARLY' if early else 'WRONG-TEXT')
            if a.show_all or not (found and not early):
                print('  %-16s %-22s %.2f @%-5d %5.2f/tok %-12s %s'
                      % (w, n[:22], best, at, r['lpt'], tag, r['text'][:32]))
    tot = hit + miss
    if tot:
        print('\n%d/%d (%.0f%%) start on their own incipit'
              % (hit, tot, 100.0 * hit / tot))
        print('%d/%d (%.0f%%) contain it but start EARLY — right hymn, '
              'wrong boundary' % (late, tot, 100.0 * late / tot))
        print('%d/%d (%.0f%%) do not contain it — wrong text'
              % (tot - hit - late, tot, 100.0 * (tot - hit - late) / tot))


if __name__ == '__main__':
    main()
