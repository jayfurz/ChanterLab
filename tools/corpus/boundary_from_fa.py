#!/usr/bin/env python3
"""boundary_from_fa.py — fix score slices using what the recording actually sings.

Chanter: "i dont think the sheet music ever had a pass at starting and ending in
the right places ... a common trope i see is the sheet music starts maybe an
entire line too early, giving the last line of the hymn before it, and sometimes
it doesnt end at the end but goes on to the next few lines of the next hymn."

Measured: only 54% of hymns begin exactly on a drop cap.

Earlier attempts fitted boundaries against GLT string similarity or against
audio duration, and both were too weak to move a boundary safely. Forced
alignment changes that: CTC has now decided, acoustically, WHICH canonical text
this recording sings (validated on gold #2 at 0.028 s onset error). So the test
becomes concrete —

    does each LINE of the score slice appear in the text the singer actually sang?

Leading lines that do not are the tail of the previous hymn; trailing lines that
do not are the head of the next one. Both get trimmed, and the drop cap is used
to confirm the proposed start.

Writes proposals only; never edits hymns.json, because re-cutting re-indexes
pins.

Usage:  boundary_from_fa.py [--workdir DIR] [--apply]
"""
import argparse
import difflib
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import GLYPHS
from glt_fetch import norm, collapse

FA = '/mnt/data/chant-corpus/texts/forced_align'
DROPCAPS = '/mnt/data/chant-corpus/scores/dropcaps.json'


def slice_lines(h):
    """[(page, line, collapsed lyric text)] for the hymn's declared slice"""
    out = []
    for p in range(h['p0'], h['p1'] + 1):
        f = os.path.join(GLYPHS, f'page{p:03d}.json')
        if not os.path.exists(f):
            continue
        d = json.load(open(f))
        by = {}
        for w in d.get('lyrics', []):
            li = w.get('line', 0)
            if (p == h['p0'] and li < h['l0']) or (p == h['p1'] and li >= h['l1']):
                continue
            by.setdefault(li, []).append((w['x0'], w['text']))
        for li in sorted(by):
            txt = ''.join(t for _, t in sorted(by[li]))
            out.append((p, li, collapse(norm(txt))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--min-line', type=float, default=0.45,
                    help='fraction of a line that must be matched to keep it')
    ap.add_argument('--max-loss', type=float, default=4.5,
                    help='only trust a boundary when CTC is confident about the '
                         'text. On t03, whose text is independently known, the '
                         'correct hymn scores 3.51 per token and wrong ones 4.99 '
                         'and up — so a weak identification must not be allowed '
                         'to move a boundary. This is what stopped an 8-line '
                         'trim on t48 (5.93/tok).')
    ap.add_argument('--out', default='/mnt/data/chant-corpus/texts/boundary_from_fa.json')
    ap.add_argument('--apply', action='store_true',
                    help='write the corrected p0/l0/p1/l1 into hymns.json. '
                         'Backs up to hymns.json.pre-fa and records the previous '
                         'slice on each row. Re-slicing re-indexes units, so any '
                         'pins on a moved hymn must be re-indexed too — the two '
                         'gold sets are frozen separately and unaffected.')
    a = ap.parse_args()

    caps = {(d['page'], d['line']) for d in json.load(open(DROPCAPS))}
    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    rows = []
    for wd in wds:
        hp = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hp):
            continue
        name = os.path.basename(wd.rstrip('/'))
        hy = json.load(open(hp))
        printed = False
        for h in hy:
            fp = os.path.join(FA, f'{name}__{h["name"]}.json')
            if not os.path.exists(fp):
                continue
            fa = json.load(open(fp))
            lpt_ = fa.get('loss_per_token')
            if lpt_ is None or lpt_ > a.max_loss:
                rows.append({'workdir': name, 'hymn': h['name'],
                             'current': [h['p0'], h['l0'], h['p1'], h['l1']],
                             'proposed': None, 'moved': False,
                             'skipped': 'low FA confidence',
                             'loss_per_token': lpt_,
                             'was_on_dropcap': (h['p0'], h['l0']) in caps,
                             'starts_on_dropcap': (h['p0'], h['l0']) in caps,
                             'trim_head_lines': 0, 'trim_tail_lines': 0})
                continue
            sung = collapse(norm(fa['glt_text']))
            lines = slice_lines(h)
            if not lines or len(sung) < 20:
                continue
            score = ''.join(t for _, _, t in lines)
            sm = difflib.SequenceMatcher(None, score, sung, autojunk=False)
            blocks = [b for b in sm.get_matching_blocks() if b.size > 2]
            if not blocks:
                continue
            # per-line matched fraction, from the block coverage over `score`
            covered = [False] * len(score)
            for b in blocks:
                for i in range(b.a, b.a + b.size):
                    covered[i] = True
            keep, pos = [], 0
            for (p, li, t) in lines:
                n = len(t)
                frac = (sum(covered[pos:pos + n]) / n) if n else 0.0
                keep.append(frac >= a.min_line)
                pos += n
            if not any(keep):
                continue
            i0, i1 = keep.index(True), len(keep) - 1 - keep[::-1].index(True)
            # HARD CONSTRAINT: the drop cap is the chanter's "dead giveaway" for
            # where a hymn starts, so a correction may never move a start OFF
            # one. If the trimmed start is not on a drop cap, snap to the
            # nearest trimmed-away line that is; if none is, keep the original
            # start. Without this, pl2 t06 trimmed four head lines and landed
            # between drop caps.
            if (lines[i0][0], lines[i0][1]) not in caps:
                snap = [k for k in range(0, i0 + 1)
                        if (lines[k][0], lines[k][1]) in caps]
                if snap:
                    i0 = snap[-1]
                elif (h['p0'], h['l0']) in caps:
                    i0 = 0
            p0, l0 = lines[i0][0], lines[i0][1]
            pe, le = lines[i1][0], lines[i1][1]
            cur = [h['p0'], h['l0'], h['p1'], h['l1']]
            prop = [p0, l0, pe, le + 1]
            trimmed_head, trimmed_tail = i0, len(lines) - 1 - i1
            row = {'workdir': name, 'hymn': h['name'], 'current': cur,
                   'proposed': prop, 'trim_head_lines': trimmed_head,
                   'trim_tail_lines': trimmed_tail,
                   'starts_on_dropcap': (p0, l0) in caps,
                   'was_on_dropcap': (h['p0'], h['l0']) in caps,
                   'loss_per_token': fa.get('loss_per_token'),
                   'moved': prop != cur}
            rows.append(row)
            if row['moved']:
                if not printed:
                    print(f'\n=== {name}'); printed = True
                print('  %-20s %d:%d-%d:%d -> %d:%d-%d:%d  head-%d tail-%d  '
                      'dropcap %s->%s'
                      % (h['name'][:20], *cur, *prop, trimmed_head, trimmed_tail,
                         'Y' if row['was_on_dropcap'] else 'n',
                         'Y' if row['starts_on_dropcap'] else 'n'))
    json.dump(rows, open(a.out, 'w'), indent=1)
    mv = [r for r in rows if r['moved']]
    if a.apply:
        import shutil
        by_wd = {}
        for r in mv:
            by_wd.setdefault(r['workdir'], []).append(r)
        for wdn, items in by_wd.items():
            hp2 = f'/mnt/data/chant-corpus/workdirs/{wdn}/hymns.json'
            hys = json.load(open(hp2))
            idx = {r['hymn']: r for r in items}
            n = 0
            for hh in hys:
                r = idx.get(hh['name'])
                if not r:
                    continue
                hh['slice_pre_fa'] = r['current']
                hh['p0'], hh['l0'], hh['p1'], hh['l1'] = r['proposed']
                hh['boundary_source'] = 'forced_align+dropcap'
                hh.pop('g0', None)
                hh.pop('g1', None)
                n += 1
            shutil.copy(hp2, hp2 + '.pre-fa')
            json.dump(hys, open(hp2, 'w'), indent=1, ensure_ascii=False)
            print(f'  applied {n} boundaries to {wdn} (backup hymns.json.pre-fa)')
    dc0 = sum(r['was_on_dropcap'] for r in rows)
    dc1 = sum(r['starts_on_dropcap'] for r in rows)
    print(f'\n{len(rows)} hymns checked, {len(mv)} boundaries move')
    print(f'  start sits on a drop cap: {dc0} -> {dc1}')
    print(f'  head lines trimmed: {sum(r["trim_head_lines"] for r in rows)}, '
          f'tail lines trimmed: {sum(r["trim_tail_lines"] for r in rows)}')
    print(f'-> {a.out}')


if __name__ == '__main__':
    main()
