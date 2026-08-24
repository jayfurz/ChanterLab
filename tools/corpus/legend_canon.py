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

2026-08-20, CHECK-01. Two composition rules were wrong, both found by the
single-key sweep in martyria_check.py --contingency and both then justified
from the atlas rather than from the sweep:

  * the kentima (cluster 16) was composing one step too high, because the
    atlas states the COMPOUND total and the code added it on top of the base.
  * a QUALITATIVE base was never promoted to the melodic neume among its marks,
    so the psifiston figures were being written out by hand in FIGURES -- and
    two of those hand entries had dropped their kentima.

    108 keys -> 124.  44 changed: 16 gained an interval, 28 changed value.
    2,715 of 113,832 note units in the book change interval (2.4%).
    martyria gaps satisfied  17/57 -> 32/58.
    Agreement with the chanter's own per-glyph rulings on gold t03 is 9/9
    before and 9/9 after (score_units.interval_chanter and
    chanter_notes.chanter_interval_applied).

    Still short of the CHECK-01 gate (violated < 8; 26 remain). What is left is
    not one-sided any more -- 15 low against 11 high, where it was 33 against 7
    -- and 23 of the 26 sit inside the ison/oligon ambiguity budget, so there is
    no evidence here for a third rule.

Usage:  legend_canon.py --compare --workdir grave-orthros
"""
import argparse
import json
import os
import re

ATLAS = '/mnt/data/chant-corpus/scores/atlas_chanter.json'
OUT = '/mnt/data/chant-corpus/scores/legend_canon.json'
# Bump on every rule change. Stamped into OUT so a legend written by an older
# checkout is identifiable rather than silently authoritative.
RULES_REV = 2          # 2 = CHECK-01 kentima + qualitative-base rules, 2026-08-20

# Marks that carry no melodic quantity. They may still carry duration
# (klasma, dots) or tie notes (omalon, eteron), but they never move the pitch.
QUALITATIVE = {7, 8, 10, 12, 19, 21, 31, 36, 61, 74, 75, 85, 91, 33, 42, 43,
               57, 32, 11, 25, 30, 58, 90, 9, 27}
# Marks that carry a JUMP rather than a note of their own (atlas): kentima,
# ypsili, and the ypsili+kentima compound.
JUMP_MARKS = {16, 28, 83}
# Explicit figures from the atlas, which override any composition rule.
FIGURES = {
    '3|13ab': 2,          # petasti + oligon
    # Ypsili on the RIGHT half of an oligon, psifiston underneath. Chanter,
    # 2026-08-23, on s42 glyph 71: "this should be +4 (ypseli over oligon
    # where ypseli is on the right half of the oligon. it has a psifiston
    # underneath that is qualitative orthography only." The qualitative-base
    # rule would compose oligon(+1)+ypsili(+4)=+5, which is the ypsili-LEFT
    # figure -- and that one keys differently (oligon base: '6|28ab' = 5), so
    # the extraction already separates the two forms. Geometry confirms one
    # figure here: all 5 instances in pp505-569 measure w 36.8-38.4 x
    # h 25.5-26.3 (p517, 521, 536, 549=s42 gi71, 565). Without this entry the
    # key derived to None and the piece's degree stream ran one step high
    # from gi71 on -- the chanter's "ends on ga not dhi".
    '7|28ab+6ab': 4,
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
    # Psifiston qualitative, the oligon above is the note. Kept as an assertion
    # only: the qualitative-base rule below composes both of these to +1 on its
    # own. The sibling entries '7|16ab+6ab' and '7|16ab+6ab+8ab' were ALSO
    # locked at +1 here, and that was wrong -- they were copies of this ruling
    # that silently dropped the kentima, which the atlas calls a quantitative
    # marker that is never zero. Composed they are +3 (oligon +1, kentima
    # top-middle +2), which is what the chanter's own uncompiled note on gold
    # t03 gi=63 says this very figure is. Removing the two locks, on top of the
    # other two rules, moved 11 martyria gaps (21 -> 32 satisfied). An earlier
    # comment said 8; that was the contingency sweep's headroom (25 minus the
    # 17 baseline), a different quantity.
    '7|6ab': 1,
    '7|6ab+8ab': 1,
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


def corpus_keys():
    """Every unit key the book actually produces."""
    import glob
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hymn_align import load_units
    out = set()
    for f in sorted(glob.glob('/mnt/data/chant-corpus/scores/glyphs/page*.json')):
        p = int(re.search(r'(\d+)', os.path.basename(f)).group(1))
        try:
            us, _ = load_units(p, 0, p, 10 ** 6)
        except Exception:
            continue
        out.update(u['key'] for u in us if not u.get('rest'))
    return out


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
        # An ISON printed over a PETASTI: the ison is the melodic content and the
        # petasti drops to qualitative, so the figure does not move. Chanter,
        # 2026-08-19: "3|22ab+8be this is +0 (ison over petasti the petasti
        # becomes qualitative only) and it has a klasma which you do pick up".
        # 972 units in the book were reading +1.
        #
        # Deliberately narrow: only when nothing ELSE in the figure carries
        # melodic quantity. 3|13ab is petasti+oligon and the atlas locks it at
        # +2, so this is not a general "the thing above wins" rule, and
        # 3|22ab+4be+7be+8be (1 unit, three quantities) is left to compose.
        if b == 3:
            isons = [x for x in marks if re.match(r'^(22|5)(ab|be)$', x)]
            others = [x for x in marks
                      if re.match(r'^(\d+)', x)
                      and int(re.match(r'^(\d+)', x).group(1)) not in QUALITATIVE
                      and not re.match(r'^(22|5)(ab|be)$', x)]
            if isons and not others:
                return 0, 'ison over petasti'
        # A jump MARK cannot be the melodic base. When the extraction makes one
        # the base — 28|6be is the ypsili with its oligon below, 302 units — the
        # note is the ordinary neume among the marks and the jump applies to it.
        # Chanter on the first neume of s04, 2026-08-19: "a ypseli on the left
        # side on top of an oligon … that's a +5 jump", i.e. oligon +1 plus
        # ypsili +4. Without this the key derived to nothing and contributed 0.
        if iv is None and b in JUMP_MARKS:
            notes = [m2 for m2 in (re.match(r'^(\d+)(ab|be)$', x) for x in marks)
                     if m2 and base.get(int(m2.group(1))) is not None]
            if notes:
                iv = base[int(notes[0].group(1))]
                marks = [x for x in marks if x != notes[0].group(0)] + [f'{b}ab']
                b = int(notes[0].group(1))
            else:
                return None, f'jump mark {b} with no note to attach to'
        # A QUALITATIVE mark cannot be the melodic base either. The extraction
        # makes the psifiston the base of 7|6ab, 7|28ab+6ab and 22 other keys,
        # and the atlas rules that case directly: "in 7|6ab figures the bar
        # above (cluster 6, oligon) is the melodic note (+1)". That is the same
        # promotion the jump-mark branch above does, so do it the same way
        # instead of listing each psifiston figure in FIGURES by hand -- which
        # is how '7|16ab+6ab' came to be locked at +1 with its kentima dropped.
        # Composition is additive, so which melodic mark is promoted does not
        # change the sum. Checks out against hymn_align.CHANTER_LOCK
        # '7|17ab+21ab+22ab' = 1: kentimata +1 promoted, carrier oligon
        # qualitative, ison +0. 16 keys gain an interval they had none for.
        if iv is None and b in QUALITATIVE:
            notes = [m2 for m2 in (re.match(r'^(\d+)(ab|be)$', x) for x in marks)
                     if m2 and base.get(int(m2.group(1))) is not None]
            if notes:
                iv = base[int(notes[0].group(1))]
                marks = [x for x in marks if x != notes[0].group(0)]
                b = int(notes[0].group(1))
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
            if c == 16:
                # The kentima's OWN quantity, not the compound total. The atlas
                # states the totals -- "below or to the RIGHT of an oligon ->
                # compound = +2 jump. On top in the MIDDLE of an oligon or
                # petasti -> +3 jump" -- and hymn_align.CHANTER_LOCK writes the
                # same three figures down as 6|16be +2, 6|16ab +3, 3|16ab +3.
                # Those are the figure's value with the carrier's own +1 already
                # inside, so composing on top of the base has to add one less.
                # Adding 2/3 made 6|16ab +4 and 6|16be +3, contradicting the
                # atlas twice, and it is why '3|16ab' needed a FIGURES lock at
                # all: composition gave +4 where the atlas says +3. With 1/2 the
                # lock becomes redundant rather than corrective, and the
                # chanter's own t03 note on 3|16ab+8be -- "a petasti compound
                # with a kentima meaning go up three" -- composes to +3.
                add += 1 if pos == 'be' else 2
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
    # The learned legend is 35 keys from ONE workdir, but the book holds far
    # more, and a key it never saw used to fall back to the bare base glyph —
    # silently dropping every jump a mark carries. 2002 units corpus-wide had no
    # interval at all under that scheme. Derive over what the corpus actually
    # contains instead; the atlas can compose most of it.
    for k in corpus_keys():
        keys.setdefault(k, None)

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
        # RULES_REV is stamped into the artefact so a stale writer is detectable.
        # OUT is shared and lives outside any checkout, and at least one other
        # checkout of this repo still holds the pre-CHECK-01 rules and writes to
        # the same path -- running its legend_canon.py --write would silently
        # revert 2,715 note units with nothing to show for it. Bump RULES_REV
        # with every rule change, and check it before trusting a degree stream.
        json.dump({'keys': canon, 'source': 'atlas_chanter.json',
                   'rules_rev': RULES_REV,
                   'note': 'derived from chanter-verified cluster identities, '
                           'NOT fitted to audio'},
                  open(OUT, 'w'), indent=1, ensure_ascii=False)
        print(f'\n-> {OUT}  ({len(canon)} keys, rules_rev {RULES_REV})')
        print('   rollback point: %s.pre-check01-108key.bak (108 keys)' % OUT)


if __name__ == '__main__':
    main()
