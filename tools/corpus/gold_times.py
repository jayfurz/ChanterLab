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

THERE IS NO MACHINE-READABLE "DONE" MARKER, and the obvious candidate is a
trap. `edited` in slots_corrected.json is written as
`corrected.map(c => c != null)` (annotator index.html:1331), so it is true for
every slot REFIT has touched -- and refit writes every unpinned marker in the
piece. It therefore reads all-true on any hymn refit has run over, whether or
not anyone has looked at it. An earlier version of this file treated all-true as
"complete" and pulled t03, s03 and s05 into a training set on that basis; the
chanter had only ever vouched for s02, s04 and s06.

So COMPLETE is a list, and it grows only when he says a hymn is done:

    s02  76     s04  85     s06  97        declared complete 2026-08-21
    s01  99     SEALED test fold -- never train on it

Everything else is partial: its unpinned slots are refit output, which is a
machine guess and not a label. For those, pins.json remains the only gold, and
it is the dragged subset -- fewer labels, and biased toward the notes the seed
got wrong.

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


# Declared complete by the chanter. Add a hymn here ONLY when he says so.
COMPLETE = ('s02-parallagi', 's04-parallagi', 's06-parallagi',
            's03-melos',    # 2026-08-23: re-pinned from the mel-transfer seed, "mark this export all gold"
            's05-melos')    # 2026-08-23: re-pinned from his own draft after the seed was reverted -- "this is now the golden one"

# MELOS PINS ARE NOT TRUSTED. Chanter, 2026-08-23: "we cant really trust s03
# or s05 because i might not have perfectly done the onsets when i did it
# manually. s02 s04 s06 are actually pretty close to perfect because i used the
# peakiness of the waveform rendering as a guide ... i think i might have made
# a lot of the onsets too early." So s03/s05 pins are a biased-early draft:
# never tune, lock, or gate a melos onset model against them. They may be used
# to notice a slip (seconds), not to judge precision (150 ms). The trusted
# labels are the three parallagi above, which were pinned against the peaks.
UNTRUSTED = ()                      # s03 and s05 were both re-pinned and declared gold 2026-08-23


def is_done(piece_name):
    """Complete means the chanter said so. See the docstring for why `edited`
    cannot be used for this."""
    return any(k in piece_name for k in COMPLETE)


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
    if not is_done(b):
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
                     'done': is_done(os.path.basename(d)),
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
            if r['done'] and not r['sealed']:
                tot += r['n']; trainable += r['n']
        print('\n  %d gold note events in hymns the chanter has declared complete'
              % tot)
        print('  (a "partial" hymn has only its pins; its other slots are refit '
              'output, not labels)')
        return 0
    if a.piece:
        g = load(a.piece)
        if g is None:
            sys.exit('not declared complete by the chanter -- see COMPLETE in this file')
        print('%d gold note events' % len(g))
        if a.out:
            json.dump([[k, round(v, 4)] for k, v in sorted(g.items())],
                      open(a.out, 'w'), indent=1)
            print('->', a.out)
        return 0
    ap.error('give --list or --piece')


if __name__ == '__main__':
    sys.exit(main())
