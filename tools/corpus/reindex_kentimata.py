#!/usr/bin/env python3
"""reindex_kentimata.py — migrate hand-made unit indices across the split.

Chanter, 2026-08-19: "yes oligon kentimata are two notes". hymn_align.py now
emits that figure as TWO units, which moved every unit index after the first
split in a page: load_units returns 113732 units corpus-wide where it returned
109040 (4692 figures split). Every index a human wrote down BEFORE that change
— the 47 hand-marked score ranges in scorecuts_*.json, the g0/g1 hymn trims in
hymns.json, and the chanter's per-unit pins/notes in datasets/*-gold — now
names the wrong glyph.

The migration is exact, not a guess: each unit load_units returns carries
u['fig'], its index in the PRE-SPLIT stream. So for one stream,

  a RANGE START old index k -> the FIRST new index with fig == k
  a RANGE END   old index k -> the LAST  new index with fig == k
  a bare PIN    old index k -> the FIRST new index with fig == k
      (a pin marks the onset of the figure, and the sub-note that sounds
       first is the first one — bottom-to-top reading order)

Three index spaces are involved and they are NOT interchangeable:
  scorecuts g0/g1   -> load_units(page, 0, page, 1e6), page-scoped: g0 against
                       p0's page stream, g1 against p1's.
  hymns.json g0/g1  -> load_units(p0, l0, p1, l1), the hymn's line slice.
  gold pins/notes   -> load_units_h(row), i.e. that same slice TRIMMED by the
                       row's own g0/g1.
The last one is circular — load_units_h slices with the very indices being
migrated — so the mapping is computed on the UNTRIMMED slice: a trimmed old
index is lifted by the old g0, mapped through fig, then lowered by the migrated
g0. When the row has no g0 both offsets are 0 and the lift is a no-op.

Usage:
  reindex_kentimata.py --dry-run          # default: report, touch nothing
  reindex_kentimata.py --write            # apply, after <file>.prekentimata.bak
  reindex_kentimata.py --verify           # re-read and assert against the .bak
"""
import argparse
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units

TEXTS = '/mnt/data/chant-corpus/texts'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
DATASETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'datasets')
BAK = '.prekentimata.bak'

_cache = {}


def stream(p0, l0, p1, l1):
    k = (p0, l0, p1, l1)
    if k not in _cache:
        units, _ = load_units(p0, l0, p1, l1)
        first, last = {}, {}
        for i, u in enumerate(units):
            f = u['fig']
            if f not in first:
                first[f] = i
            last[f] = i
        _cache[k] = (units, first, last)
    return _cache[k]


def page_stream(p):
    return stream(p, 0, p, 10 ** 6)


class Tally:
    def __init__(self):
        self.moved = 0
        self.same = 0
        self.miss = 0
        self.nudged = 0
        self.deltas = []

    def map(self, val, first, last, end=False):
        """old index -> new index, counting the outcome."""
        table = last if end else first
        if val not in table:
            # Two different failures, and only one is a data error.
            #
            # (a) the slot EXISTED but no longer emits a unit — it was a chiasma,
            #     which used to be read as a phantom note and is now silenced.
            #     A range START moves forward to the next surviving unit and an
            #     END back to the previous one, because the boundary he drew is
            #     still where he drew it; only the glyph he happened to land on
            #     has stopped being a note. hymns.json t01_ g0=18 is exactly this.
            # (b) the slot is beyond the stream altogether — scorecuts t01_#3
            #     g1=205 on a 159-figure page. That was wrong before the split
            #     too, so it is left alone and reported for the chanter.
            if table and val <= max(table):
                nxt = ([k for k in sorted(table) if k > val] if not end
                       else [k for k in sorted(table, reverse=True) if k < val])
                if nxt:
                    new = table[nxt[0]]
                    self.moved += 1
                    self.deltas.append(new - val)
                    self.nudged += 1
                    return new
            self.miss += 1
            return None
        new = table[val]
        if new == val:
            self.same += 1
        else:
            self.moved += 1
            self.deltas.append(new - val)
        return new

    def line(self):
        d = self.deltas
        return (f"moved {self.moved}, unchanged {self.same}, unmappable "
                f"{self.miss}"
                + (f", nudged past a silenced glyph {self.nudged}" if self.nudged else "")
                + (f", shift +{min(d)}..+{max(d)}" if d else ""))


def backup(path, write):
    if not write:
        return
    b = path + BAK
    if not os.path.exists(b):
        shutil.copy2(path, b)
        print(f"    backup -> {b}")
    else:
        print(f"    backup exists, kept: {b}")


def source(path):
    """The indices to migrate FROM — always the pre-split originals.

    This tool is not naturally idempotent: it maps an index through u['fig'],
    which only means anything for an index that has never been migrated. Running
    it twice on the same file therefore double-shifts the chanter's hand-made
    marks, and --verify cannot tell (it compares against the .bak, so it just
    reports failures after the damage). Reading the source values from the .bak
    whenever one exists makes it idempotent by construction: a second run
    recomputes the same answer, and a run after the segmentation rules CHANGE
    re-derives from the originals instead of compounding the last migration.

    This is not hypothetical. Extending the split to the carrier figures
    (chanter, 2026-08-19) moved the indices a second time, and the only correct
    source for that pass was the pre-split values, not the first migration's.
    """
    b = path + BAK
    return json.load(open(b if os.path.exists(b) else path))


def save(path, obj, write):
    if write:
        json.dump(obj, open(path, 'w'), ensure_ascii=False, indent=1)


# ---- a) scorecuts_*.json -------------------------------------------------
def do_scorecuts(write, report):
    for path in sorted(glob.glob(os.path.join(TEXTS, 'scorecuts_*.json'))):
        d = json.load(open(path))          # written back in place
        rows = d['cuts']
        for r, src in zip(rows, source(path)['cuts']):
            r.update({k: src[k] for k in ('g0', 'g1') if k in src})
        t = Tally()
        changes = []
        for r in rows:
            g0, g1 = r.get('g0'), r.get('g1')
            n0 = None if g0 is None else t.map(g0, *page_stream(r['p0'])[1:])
            n1 = None if g1 is None else t.map(g1, *page_stream(r['p1'])[1:], end=True)
            if n0 is not None and n0 != g0:
                changes.append((r['hymn'], 'g0', g0, n0))
                r['g0'] = n0
            if n1 is not None and n1 != g1:
                changes.append((r['hymn'], 'g1', g1, n1))
                r['g1'] = n1
        print(f"  {path}: {len(rows)} rows — {t.line()}")
        for c in changes[:6]:
            print(f"    {c[0]} {c[1]}: {c[2]} -> {c[3]}")
        if len(changes) > 6:
            print(f"    ... {len(changes) - 6} more")
        backup(path, write)
        save(path, d, write)
        report.append(t)


# ---- b) workdirs/*/hymns.json --------------------------------------------
def do_hymns(write, report):
    for path in sorted(glob.glob(os.path.join(WORKDIRS, '*', 'hymns.json'))):
        rows = json.load(open(path))
        src = {r['name']: r for r in source(path)}      # pre-split originals
        for r in rows:
            o = src.get(r['name'], {})
            for k in ('g0', 'g1'):
                if k in o:
                    r[k] = o[k]
        hit = [r for r in rows if r.get('g0') is not None or r.get('g1') is not None]
        if not hit:
            continue
        t = Tally()
        changes = []
        for r in hit:
            _, first, last = stream(r['p0'], r['l0'], r['p1'], r['l1'])
            for k, end in (('g0', False), ('g1', True)):
                v = r.get(k)
                if v is None:
                    continue
                new = t.map(v, first, last, end=end)
                if new is not None and new != v:
                    changes.append((r['name'], k, v, new))
                    r[k] = new
        print(f"  {path}: {len(hit)} rows with g0/g1 — {t.line()}")
        for c in changes:
            print(f"    {c[0]} {c[1]}: {c[2]} -> {c[3]}")
        backup(path, write)
        save(path, rows, write)
        report.append(t)


# ---- c) datasets/*-gold pins.json + chanter_notes.json --------------------
def gold_row(dsdir):
    """(hymns.json path, row) for a gold dataset directory."""
    idx = os.path.join(DATASETS, 'gold_index.json')
    name = os.path.basename(dsdir)
    wd = hymn = None
    if os.path.exists(idx):
        for e in json.load(open(idx))['datasets']:
            if name.startswith(e['id'].replace('/', '-')) and e.get('hymn'):
                wd, hymn = e['workdir'], e['hymn']
    if wd is None:                     # grave-orthros-t03-gold -> grave-orthros, t03_
        parts = name[:-len('-gold')].rsplit('-', 1)
        if len(parts) != 2:
            return None, None
        wd, hymn = os.path.join(WORKDIRS, parts[0]), parts[1] + '_'
    if not os.path.isabs(wd):
        wd = os.path.join(os.path.dirname(DATASETS), wd)
    hp = os.path.join(wd, 'hymns.json')
    if not os.path.exists(hp):
        return None, None
    for r in json.load(open(hp)):
        if r['name'] == hymn:
            return hp, r
    return None, None


def do_gold(write, report):
    for dsdir in sorted(glob.glob(os.path.join(DATASETS, '*-gold'))):
        pins = os.path.join(dsdir, 'pins.json')
        notes = os.path.join(dsdir, 'chanter_notes.json')
        if not os.path.exists(pins) and not os.path.exists(notes):
            continue
        hp, row = gold_row(dsdir)
        if row is None:
            print(f"  {dsdir}: SKIPPED — could not resolve its hymns.json row")
            continue
        units, first, last = stream(row['p0'], row['l0'], row['p1'], row['l1'])
        # the trim offsets: OLD g0 from the .bak if this run already migrated
        # hymns.json, else the value still on disk (see the docstring on why the
        # mapping is computed untrimmed).
        bak = hp + BAK
        old_row = row
        if os.path.exists(bak):
            for r in json.load(open(bak)):
                if r['name'] == row['name']:
                    old_row = r
        old_g0 = int(old_row.get('g0') or 0)
        new_g0 = first.get(old_g0, old_g0) if old_row.get('g0') is not None else 0
        t = Tally()

        def remap(gi):
            new = t.map(int(gi) + old_g0, first, last)
            return None if new is None else new - new_g0

        for path, key in ((pins, None), (notes, 'gi')):
            if not os.path.exists(path):
                continue
            d = json.load(open(path))
            changes = []
            for item in d:
                old = item[0] if key is None else item[key]
                new = remap(old)
                if new is None or new == old:
                    continue
                changes.append((old, new))
                if key is None:
                    item[0] = new
                else:
                    item[key] = new
            print(f"  {path}: {len(d)} entries, {len(changes)} moved")
            for c in changes[:6]:
                print(f"    {c[0]} -> {c[1]}")
            if len(changes) > 6:
                print(f"    ... {len(changes) - 6} more")
            backup(path, write)
            save(path, d, write)
        print(f"  {dsdir}: {t.line()} (stream {len(units)} units, "
              f"{len(first)} figures, trim g0 {old_g0} -> {new_g0})")
        if t.moved:
            print(f"  {dsdir}: NOTE score_units.json is the frozen PRE-split "
                  f"stream and is NOT migrated here — regenerate it before "
                  f"reading pins against it.")
        report.append(t)


# ---- --verify ------------------------------------------------------------
def verify():
    bad = 0
    checked = 0
    skipped = 0

    def check(what, old, new, first, last, end=False):
        nonlocal bad, checked, skipped
        table = last if end else first
        if old not in table:
            # A slot INSIDE the stream that no longer emits a unit was nudged to
            # the neighbouring surviving one on purpose (see Tally.map), so the
            # check follows the same rule rather than calling it a failure.
            if table and old <= max(table):
                nxt = ([k for k in sorted(table) if k > old] if not end
                       else [k for k in sorted(table, reverse=True) if k < old])
                if nxt:
                    checked += 1
                    if table[nxt[0]] != new:
                        print(f"  FAIL {what}: silenced slot {old} should nudge "
                              f"to {table[nxt[0]]}, file says {new}")
                        bad += 1
                    return
            # never mappable, before the split either: the migration left it
            # alone and so does the check. t01_#3 g1=205 on a 159-figure page.
            skipped += 1
            if old != new:
                print(f"  FAIL {what}: unmappable old {old} was changed to {new}")
                bad += 1
            return
        checked += 1
        if table[old] != new:
            print(f"  FAIL {what}: old {old} should map to {table[old]}, "
                  f"file says {new}")
            bad += 1

    for path in sorted(glob.glob(os.path.join(TEXTS, 'scorecuts_*.json'))):
        if not os.path.exists(path + BAK):
            continue
        new = json.load(open(path))['cuts']
        old = json.load(open(path + BAK))['cuts']
        for o, n in zip(old, new):
            if o.get('g0') is not None:
                check(f"{path} {o['hymn']} g0", o['g0'], n['g0'], *page_stream(o['p0'])[1:])
            if o.get('g1') is not None:
                check(f"{path} {o['hymn']} g1", o['g1'], n['g1'],
                      *page_stream(o['p1'])[1:], end=True)
            if n.get('g0') is not None and n.get('g1') is not None \
               and o['p0'] == o['p1'] and n['g1'] < n['g0']:
                print(f"  FAIL {path} {o['hymn']}: range inverted "
                      f"{n['g0']}..{n['g1']}")
                bad += 1
    for path in sorted(glob.glob(os.path.join(WORKDIRS, '*', 'hymns.json'))):
        if not os.path.exists(path + BAK):
            continue
        new = {r['name']: r for r in json.load(open(path))}
        for o in json.load(open(path + BAK)):
            if o.get('g0') is None and o.get('g1') is None:
                continue
            n = new[o['name']]
            _, first, last = stream(o['p0'], o['l0'], o['p1'], o['l1'])
            if o.get('g0') is not None:
                check(f"{path} {o['name']} g0", o['g0'], n['g0'], first, last)
            if o.get('g1') is not None:
                check(f"{path} {o['name']} g1", o['g1'], n['g1'], first, last, end=True)
            if n.get('g0') is not None and n.get('g1') is not None and n['g1'] < n['g0']:
                print(f"  FAIL {path} {o['name']}: range inverted")
                bad += 1
    for dsdir in sorted(glob.glob(os.path.join(DATASETS, '*-gold'))):
        hp, row = gold_row(dsdir)
        if row is None:
            continue
        _, first, last = stream(row['p0'], row['l0'], row['p1'], row['l1'])
        old_row = row
        if os.path.exists(hp + BAK):
            for r in json.load(open(hp + BAK)):
                if r['name'] == row['name']:
                    old_row = r
        old_g0 = int(old_row.get('g0') or 0)
        new_g0 = first.get(old_g0, old_g0) if old_row.get('g0') is not None else 0
        for path, key in ((os.path.join(dsdir, 'pins.json'), None),
                          (os.path.join(dsdir, 'chanter_notes.json'), 'gi')):
            if not os.path.exists(path + BAK):
                continue
            new = json.load(open(path))
            old = json.load(open(path + BAK))
            prev = None
            for o, n in zip(old, new):
                ov = o[0] if key is None else o[key]
                nv = n[0] if key is None else n[key]
                check(f"{path} #{ov}", int(ov) + old_g0, int(nv) + new_g0, first, last)
                if prev is not None and nv < prev:
                    print(f"  FAIL {path}: order inverted at {ov} -> {nv}")
                    bad += 1
                prev = nv
    print(f"\nVERIFY: {checked} migrated indices checked, {bad} failures, "
          f"{skipped} left alone as unmappable")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    if a.verify:
        return verify()
    write = a.write
    print("=== reindex_kentimata: " + ("WRITE" if write else "DRY RUN") + " ===")
    report = []
    print("\n[a] scorecuts")
    do_scorecuts(write, report)
    print("\n[b] hymns.json")
    do_hymns(write, report)
    print("\n[c] gold datasets")
    do_gold(write, report)
    moved = sum(t.moved for t in report)
    same = sum(t.same for t in report)
    miss = sum(t.miss for t in report)
    deltas = [d for t in report for d in t.deltas]
    print("\n" + "=" * 62)
    print(f"  {moved + same + miss} hand-made indices seen")
    print(f"  {moved} MOVED (a kentimata split fell before them)")
    if deltas:
        print(f"     shift min +{min(deltas)}  max +{max(deltas)}  "
              f"mean +{sum(deltas) / len(deltas):.1f}")
    print(f"  {same} already correct (no split before them)")
    print(f"  {miss} UNMAPPABLE (no unit carries that fig — inspect by hand)")
    print(f"  {'WRITTEN' if write else 'nothing written (--write to apply)'}")
    print("=" * 62)
    return 1 if miss else 0


if __name__ == '__main__':
    sys.exit(main())
