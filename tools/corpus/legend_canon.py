#!/usr/bin/env python3
"""legend_canon.py — build the interval legend from the chanter's atlas.

The legend in use was LEARNED from parallagi alignments, which made it circular
for any test involving parallagi, and it is also wrong. Checked against the 25
per-glyph notes the chanter wrote on gold t03:

    6|            +1   legend +1   ok
    3|            +1   legend +1   ok
    4|            -1   legend -1   ok
    5|             0   legend  0   ok
    4|8ab         -1   legend -1   ok
    7|6ab         +1   legend  0   WRONG
    3|16ab+8be    +3   legend +1   WRONG
    6|36be        +1   legend  -   missing

His atlas explains both errors independently of the notes: cluster 7 psifiston
is qualitative and "in 7|6ab figures the bar above (cluster 6, oligon) is the
melodic note (+1)"; the petasti_kentima figure is "+3 (chanter, t03 gi13)".

So the intervals are derivable from the atlas, which is chanter-verified shape
identity rather than anything fitted to audio. That is what this builds.

(`legend_merged.json` must not be used: it is the ROTATED original seed --
6|->0, 4|->+1, 5|->-1 -- which the atlas provenance explicitly overrides.)

Usage:  legend_canon.py --compare --workdir grave-orthros
"""
import argparse
import json
import re

ATLAS = '/mnt/data/chant-corpus/scores/atlas_chanter.json'
OUT = '/mnt/data/chant-corpus/scores/legend_canon.json'

# Marks that carry no melodic quantity. They may still carry duration
# (klasma, dots) or tie notes (omalon, eteron), but they never move the pitch.
QUALITATIVE = {7, 8, 10, 12, 19, 21, 31, 36, 61, 74, 75, 85, 91, 33, 42, 43,
               57, 32, 11, 25, 30, 58, 90, 9, 27}
# Explicit figures from the atlas, which override any composition rule.
FIGURES = {
    '3|13ab': 2,          # petasti + oligon
    '3|13ab+8be': 2,
    '3|16ab': 3,          # petasti + kentima on top-middle
    '3|16ab+8be': 3,
    '20|41be': -3,        # elaphron + apostrofos
    '20|41be+8ab': -3,
    '47|17be+21be': -1,   # elafron + kentimata over carrier oligon
    # The elaphron combination variant carries no interval in the atlas, but the
    # atlas LOCKS the figure above at -1 and the chanter reads that figure as
    # "elafron kentimata (-2 +1)". Subtracting the kentimata's own +1 leaves the
    # elaphron at -2, which is just the plain elaphron value (cluster 20). Needed
    # as a standalone key because _split_kentimata now emits it as its own note.
    '47|': -2,   # elaphron + kentimata over carrier oligon
    '7|6ab': 1,           # psifiston qualitative, oligon above is the note
    '7|16ab+6ab': 1,
    '7|6ab+8ab': 1,
    '7|16ab+6ab+8ab': 1,
}


# Keys the legend must carry whether or not the learned inventory happens to
# hold them. The learned legend_global.json is 36 keys from one workdir, so a
# key can be load-bearing corpus-wide and still be missing there. '6|' and '17|'
# are the two halves of every split oligon+kentimata figure -- 4692 figures
# corpus-wide, 9384 sub-units -- and if either were absent the split would
# silently lose its interval. The rest are the 17-bearing compounds that survive
# the split (measured over all 673 glyph pages) and are derivable from the atlas.
#
# '4|17be+6be' is deliberately NOT seeded, though it occurs 660 times. Composing
# it gives apostrofos -1 + kentimata +1 + oligon +1 = +1, where today it falls
# back to the bare '4|' = -1 -- a +2 swing on 660 units, which moved the closing
# degree of 10 of the 47 chanter-marked ranges. Both values are guesses. The
# figure carries THREE melodic quantities, and the lesson of the oligon+kentimata
# ruling is that such a stack is usually several NOTES rather than one net
# displacement, so composing a net for it is probably the wrong question. Left
# unseeded, i.e. on the behaviour the chanter's gold work was verified against,
# until he rules on it.
SEED = ['6|', '17|', '4|', '5|', '20|', '22|', '41|', '47|', '3|',
        '22|17be+21be',        # 1009 occurrences, carrier oligon
        '47|17be+21be',        #  188
        '22|17be+21be+36be',   #    2
        '4|17ab+33ab+4be+6ab'] #    1


def build():
    at = json.load(open(ATLAS))['clusters']
    base = {int(k): v.get('interval') for k, v in at.items()}
    names = {int(k): v.get('name', '') for k, v in at.items()}

    def interval_for(key):
        if key in FIGURES:
            return FIGURES[key], 'figure'
        m = re.match(r'^(\d+)\|(.*)$', key)
        if not m:
            return None, 'unparsed'
        b = int(m.group(1))
        marks = [x for x in m.group(2).split('+') if x]
        iv = base.get(b)
        if iv is None:
            if b in QUALITATIVE:
                return None, 'qualitative base'
            return None, f'no interval for cluster {b} ({names.get(b, "?")})'
        add = 0
        for mk in marks:
            mm = re.match(r'^(\d+)(ab|be)$', mk)
            if not mm:
                continue
            c, pos = int(mm.group(1)), mm.group(2)
            if c in QUALITATIVE:
                continue
            if c == 16:            # kentima
                add += 2 if pos == 'be' else 3
            elif c == 17:
                # NOT the general oligon+kentimata figure. That figure is two
                # notes of +1 read bottom to top (chanter, 2026-08-19) and
                # hymn_align._split_kentimata now emits it as two units, '6|'
                # and '17|', so it never reaches this rule. What is left here is
                # only what the split declines: the atlas-locked carrier-oligon
                # compounds (22|17be+21be +1, 47|17be+21be -1) and the figures
                # with a third melodic quantity (4|17be+6be, 28|17be+6be,
                # 7|17ab+4ab+6ab ...). In those the kentimata really is one
                # added step on top of the base, which is what +1 means here.
                add += 1
            elif c == 28:          # ypsili
                add += 4
            elif c == 83:
                add += 7
            elif base.get(c) is not None:
                add += base[c]
        return iv + add, 'composed'

    return interval_for, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    interval_for, names = build()
    learned = json.load(open(
        f'/mnt/data/chant-corpus/workdirs/{a.workdir}/legend_global.json'))
    keys, support = learned['keys'], learned.get('support', {})
    for k in SEED:
        keys.setdefault(k, None)          # None = no learned value to compare

    canon, why = {}, {}
    for k in keys:
        v, w = interval_for(k)
        why[k] = w
        if v is not None:
            canon[k] = v

    if a.compare:
        agree = dis = unk = 0
        rows = []
        for k in sorted(keys, key=lambda k: -support.get(k, 0)):
            n = support.get(k, 0)
            if k not in canon:
                unk += n
                continue
            if keys[k] is None:
                continue                  # seeded key, nothing learned to compare
            if canon[k] == keys[k]:
                agree += n
            else:
                dis += n
                rows.append((n, k, keys[k], canon[k], why[k]))
        tot = agree + dis + unk
        print('unit occurrences in %s, weighted by support:' % a.workdir)
        print('  canon agrees with the learned legend : %d (%.0f%%)'
              % (agree, 100 * agree / max(tot, 1)))
        print('  canon DISAGREES                      : %d (%.0f%%)'
              % (dis, 100 * dis / max(tot, 1)))
        print('  canon cannot derive                  : %d (%.0f%%)'
              % (unk, 100 * unk / max(tot, 1)))
        if rows:
            print('\n  largest disagreements:')
            for n, k, l, c, w in sorted(rows, reverse=True)[:12]:
                print('    %5d  %-22s learned %+d  canon %+d  (%s)'
                      % (n, k, l, c, w))
    if a.write:
        json.dump({'keys': canon, 'source': 'atlas_chanter.json',
                   'note': 'derived from chanter-verified cluster identities, '
                           'NOT fitted to audio'},
                  open(OUT, 'w'), indent=1, ensure_ascii=False)
        print(f'\n-> {OUT}  ({len(canon)} keys)')


if __name__ == '__main__':
    main()
