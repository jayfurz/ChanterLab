#!/usr/bin/env python3
"""fa_sanity.py -- which tracks cannot possibly be aligned, before anyone tries.

A forced aligner never refuses. Give it the wrong text and it will still place
every character somewhere, and the result looks like an alignment. The cheapest
guard is arithmetic: a singer emits roughly 2-6 characters of text per second of
chant, so a record whose assigned text needs 80 characters per second is not a
hard alignment, it is the wrong text or the wrong cut.

CTC makes the hard version of this check free. torchaudio's forced_align refuses
outright when len(targets) + repeats > frames, because there is no path through
the lattice. On the 2026-08-20 corpus realignment that fired once, on
pl4-orthros__t27_: 18.4 s of audio carrying the whole of Anavathmoi Antiphon A
(1,460 characters, 79.6 ch/s). It was not a bug in the aligner -- it was the
tape solve assigning a whole antiphon block to one 18-second segment, and the
crash is the only reason anyone found out.

Audited over 173 records, 2026-08-20:

    median 4.5 ch/s
    12 IMPOSSIBLE  (>12 ch/s)  -- text far too long for the audio
    12 suspicious  (8-12 ch/s)
     3 at the other extreme, 0.2-0.3 ch/s: 251 characters over 1,032 s of audio,
       which means the cut spans many hymns or the text is a fragment

Both tails cost chanter time in the same way: the alignment will be confidently
wrong, and the annotator will seed every note from it. Fix the cut or the
identification first. This script does not fix anything -- it says where to look.

Usage:
  fa_sanity.py                 # the table
  fa_sanity.py --json out.json
  fa_sanity.py --quiet         # exit 2 if any record is impossible
"""
import argparse
import contextlib
import glob
import json
import os
import statistics as st
import sys
import wave

FA_DIR = '/mnt/data/chant-corpus/texts/forced_align'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
# Chant runs 2-6 ch/s. These bounds are deliberately loose: the point is to
# catch a record that is wrong by an order of magnitude, not to grade tempo.
IMPOSSIBLE_HI, SUSPECT_HI, SUSPECT_LO = 12.0, 8.0, 1.0


def duration(path):
    try:
        with contextlib.closing(wave.open(path)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return None


def audit():
    out = []
    for f in sorted(glob.glob(os.path.join(FA_DIR, '*.json'))):
        d = json.load(open(f))
        p = d.get('audio') or os.path.join(
            WORKDIRS, d.get('workdir', ''), 'melos_%s' % d.get('hymn', ''), 'audio.wav')
        if not os.path.exists(p):
            continue
        dur = duration(p)
        if not dur:
            continue
        n = len(d.get('glt_text') or '')
        r = n / dur
        verdict = ('impossible' if r > IMPOSSIBLE_HI else
                   'suspect_high' if r > SUSPECT_HI else
                   'suspect_low' if r < SUSPECT_LO else 'ok')
        out.append({'record': os.path.basename(f), 'workdir': d.get('workdir'),
                    'hymn': d.get('hymn'), 'chars': n, 'audio_s': round(dur, 1),
                    'chars_per_s': round(r, 1), 'verdict': verdict,
                    'n_words': len(d.get('words') or []),
                    'source': d.get('source')})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--json')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    rows = audit()
    if not rows:
        print('no records found')
        return 1
    bad = [r for r in rows if r['verdict'] != 'ok']
    if not a.quiet:
        rows.sort(key=lambda r: -r['chars_per_s'])
        print('%-34s %7s %9s %7s  %s' % ('record', 'chars', 'audio s', 'ch/s', 'verdict'))
        for r in rows:
            if r['verdict'] == 'ok':
                continue
            print('%-34s %7d %9.1f %7.1f  %s'
                  % (r['record'], r['chars'], r['audio_s'], r['chars_per_s'], r['verdict']))
        print('\n%d records, median %.1f ch/s' %
              (len(rows), st.median(r['chars_per_s'] for r in rows)))
        for v in ('impossible', 'suspect_high', 'suspect_low'):
            print('  %-13s %d' % (v, sum(1 for r in rows if r['verdict'] == v)))
        print('\nThese will align confidently and wrongly. Fix the cut or the '
              'identification\nbefore seeding an annotator from them.')
    if a.json:
        json.dump(rows, open(a.json, 'w'), ensure_ascii=False, indent=1)
        print('->', a.json)
    return 2 if any(r['verdict'] == 'impossible' for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
