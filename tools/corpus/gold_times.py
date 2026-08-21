#!/usr/bin/env python3
"""gold_times.py -- the chanter's true onset labels, which are NOT pins.json.

Chanter, 2026-08-21: "idk why the pins only have a portion, but i went through
s02 s04 and s06 and they are all correct. well i know why. they are the ones
that i didnt have to do anything to drag. but when i say a hymn is done that
means all the note events are now correct."

pins.json holds only the notes he had to MOVE. A note the seed already placed
correctly is never dragged, so it never becomes a pin -- and it is just as much
ground truth as the ones that were. Reading pins.json as the label set has two
consequences, and the second is worse than the first:

  * it throws away labels. Over the completed hymns, 593 note events exist and
    only 466 are pinned -- 27% discarded.
  * it biases the denominator toward the HARD notes. A pin is by construction a
    note the seed got wrong. Scoring only on pins scores only on the subset the
    previous system failed, which flatters nothing but measures the wrong
    population. s06 is the clearest: 15 of its 97 notes needed no drag, and
    every evaluation of that piece in this repo before today silently excluded
    exactly those 15.

THE "DONE" MARKER is `edited` all true in slots_corrected.json, with `pinned`
true on the dragged subset. When every slot is edited the chanter has been
through the whole hymn and all note events are correct.

Completed as of 2026-08-21 (593 events):
    s01  99   SEALED test fold -- never train on it
    s02  76     s03  76     s04  85     s05  85     s06  97
    t03  75   but see below

t03 IS AN EXCEPTION. Its export is the stale 75-unit, pre-split version and is
offset by about 0.25 s; the real gold is datasets/grave-orthros-t03-gold/
pins.json, which has all 76 and is what baseline_errors.json is built from.
load() refuses the t03 export rather than let it be used by accident.

Usage:
  gold_times.py --list
  gold_times.py --piece <export dir> --out gold.json     # onset_eval --pins
"""
import argparse
import glob
import json
import os
import sys

EXPORTS = ('/mnt/data/code/byzorgan-web-worktrees/chant-annotator/'
           'datasets/exports')
T03_GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', '..', 'datasets/grave-orthros-t03-gold/pins.json')
SEALED = ('s01',)


def is_done(sc):
    n = len(sc.get('gi', []))
    return n > 0 and sum(1 for x in sc.get('edited', [])) == n \
        and all(sc.get('edited', []))


def load(piece_dir):
    """{glyph: seconds} for a completed hymn, or None if it is not complete."""
    b = os.path.basename(piece_dir.rstrip('/'))
    if '-t03' in b:
        raise SystemExit('refusing the t03 export: it is the stale 75-unit '
                         'pre-split copy, offset ~0.25 s. Use %s' % T03_GOLD)
    f = os.path.join(piece_dir, 'slots_corrected.json')
    if not os.path.exists(f):
        return None
    sc = json.load(open(f))
    if not is_done(sc):
        return None
    return {int(g): float(t) for g, t in zip(sc['gi'], sc['t'])}


def survey():
    rows = []
    for d in sorted(glob.glob(os.path.join(EXPORTS, 'grave-orthros-*'))):
        f = os.path.join(d, 'slots_corrected.json')
        if not os.path.exists(f):
            continue
        sc = json.load(open(f))
        n = len(sc.get('gi', []))
        rows.append({'piece': os.path.basename(d), 'n': n,
                     'pinned': sum(1 for x in sc.get('pinned', []) if x),
                     'done': is_done(sc),
                     'sealed': any(s in os.path.basename(d) for s in SEALED)})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--piece')
    ap.add_argument('--out')
    a = ap.parse_args()
    if a.list:
        tot = trainable = 0
        print('  %-46s %5s %6s  %s' % ('piece', 'notes', 'pinned', 'status'))
        for r in survey():
            tag = ('SEALED' if r['sealed'] else 'done' if r['done'] else 'partial')
            print('  %-46s %5d %6d  %s' % (r['piece'][14:58], r['n'], r['pinned'], tag))
            if r['done']:
                tot += r['n']
                if not r['sealed']:
                    trainable += r['n']
        print('\n  %d gold note events in completed hymns, %d of them trainable'
              % (tot, trainable))
        return 0
    if a.piece:
        g = load(a.piece)
        if g is None:
            sys.exit('not complete -- edited is not true on every slot')
        print('%d gold note events' % len(g))
        if a.out:
            json.dump([[k, round(v, 4)] for k, v in sorted(g.items())],
                      open(a.out, 'w'), indent=1)
            print('->', a.out)
        return 0
    ap.error('give --list or --piece')


if __name__ == '__main__':
    sys.exit(main())
