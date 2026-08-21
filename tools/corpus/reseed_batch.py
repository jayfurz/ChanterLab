#!/usr/bin/env python3
"""reseed_batch.py -- reseed every piece's annotator slots from forced alignment.

WHY THIS EXISTS. 16 hours of tape have to be pinned by hand, and the annotator
seeds each note from the DTW aligner. On gold t03 that seed lands 32.9% of
markers within 150 ms, so two notes in three get dragged manually. Seeding from
the CTC CHARACTER path instead, with written beats filling between anchors,
lands 75.0% -- 51 notes needing a manual move becomes 19 (tools/corpus/
reseed_onsets.py, scored through onset_eval.py).

This applies that across the corpus. Per piece:

    1. recover the CTC character grid on the CURRENT audio  (fa_eval.ctc_char_path)
    2. map glyph -> its syllable's first character -> that character's onset
       (fa_eval.build_mapping; uses no timing, so it is checkable on its own)
    3. fill the unmapped glyphs by cumulative beats_seq()   (reseed_onsets.fill)

WHAT IT REFUSES. Records fa_sanity.py calls impossible or suspect are skipped by
default: their assigned text does not fit their audio, so an alignment from them
is confidently wrong and seeding it would cost more chanter time than the old
seed did. --include-suspect overrides, and says so per piece.

COVERAGE IS THE NUMBER TO READ, not a score. There are no pins on these pieces,
so nothing here is measured against truth -- only t03 is, and t03 is a burnt
benchmark. What CAN be reported per piece is how many glyphs got a real anchor
rather than an interpolation. On t03 that was 56 of 76 (74%) and gave 75%
within 150 ms. A piece anchoring 20% of its glyphs is mostly arithmetic and
should not be trusted just because this script wrote it.

Usage:
  reseed_batch.py --device cuda --out-dir <dir>
  reseed_batch.py --device cuda --out-dir <dir> --apply    # write into annotator data
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import fa_eval                                   # noqa: E402
from reseed_onsets import fill, verify_tempo      # noqa: E402
from hymn_align import load_units_h, beats_seq    # noqa: E402

FA_DIR = '/mnt/data/chant-corpus/texts/forced_align'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
ANN = os.path.join(ROOT, 'tools/chant-reel/annotator/data')


def piece_id(workdir, hymn):
    return '%s-%s' % (workdir, hymn.strip('_'))


def hymn_record(workdir, hymn):
    hf = os.path.join(WORKDIRS, workdir, 'hymns.json')
    if not os.path.exists(hf):
        return None
    for h in json.load(open(hf)):
        if h.get('name') == hymn:
            return h
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--apply', action='store_true',
                    help="overwrite slots.t in each piece's annotator_data.json")
    ap.add_argument('--include-suspect', action='store_true')
    ap.add_argument('--verify-tempo', action='store_true')
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    fa_eval.DEVICE = a.device
    import fa_sanity
    verdict = {r['record']: r['verdict'] for r in fa_sanity.audit()}

    rows, skipped = [], []
    files = sorted(f for f in os.listdir(FA_DIR) if f.endswith('.json'))
    if a.limit:
        files = files[:a.limit]
    for i, fn in enumerate(files, 1):
        d = json.load(open(os.path.join(FA_DIR, fn)))
        wd, hy = d.get('workdir'), d.get('hymn')
        v = verdict.get(fn, 'unknown')
        if v != 'ok' and not a.include_suspect:
            skipped.append((fn, 'fa_sanity: %s' % v))
            continue
        if not d.get('words'):
            skipped.append((fn, 'no alignment')); continue
        pid = piece_id(wd, hy)
        ann_path = os.path.join(ANN, pid, 'annotator_data.json')
        if not os.path.exists(ann_path):
            skipped.append((fn, 'no annotator data (%s)' % pid)); continue
        ad = json.load(open(ann_path))
        h = hymn_record(wd, hy)
        if not h:
            skipped.append((fn, 'no hymns.json record')); continue
        try:
            units, _ = load_units_h(h)
            beats = beats_seq(units)
            if len(beats) != len(ad['slots']['gi']):
                skipped.append((fn, 'unit/slot mismatch %d vs %d'
                                % (len(beats), len(ad['slots']['gi'])))); continue
            # ONE CTC pass per piece. Calling ctc_char_path twice (once to test
            # the shape, once for the value) doubles the whole batch.
            C = fa_eval.ctc_char_path(d)
            g2c, ev = fa_eval.build_mapping(C['chars'], ad['slots'])
            anchors = {gi: C['chars'][ci]['t0'] for gi, ci in g2c.items()}
            if a.verify_tempo and len(anchors) >= 3:
                anchors = verify_tempo(anchors, beats)
            if len(anchors) < 2:
                skipped.append((fn, 'only %d anchors' % len(anchors))); continue
            seed = fill(anchors, beats)
        except Exception as e:
            skipped.append((fn, '%s: %s' % (type(e).__name__, e))); continue

        cov = len(anchors) / len(beats)
        json.dump({'piece_id': pid, 'n_glyphs': len(beats),
                   'n_anchors': len(anchors), 'anchor_coverage': round(cov, 3),
                   'anchor_gi': sorted(anchors),
                   'seed': {str(g): seed[g] for g in sorted(seed)}},
                  open(os.path.join(a.out_dir, pid + '.json'), 'w'), indent=1)
        if a.apply:
            ad['slots']['t'] = [seed[g] for g in range(len(beats))]
            ad.setdefault('meta', {})['seed_source'] = 'reseed_batch: FA char anchors + beats fill'
            ad['meta']['seed_anchor_coverage'] = round(cov, 3)
            tmp = ann_path + '.tmp'
            json.dump(ad, open(tmp, 'w'), ensure_ascii=False, indent=1)
            os.replace(tmp, ann_path)
        rows.append({'record': fn, 'piece_id': pid, 'n_glyphs': len(beats),
                     'n_anchors': len(anchors), 'coverage': round(cov, 3)})
        print('[%3d/%d] %-30s %3d glyphs  %3d anchors  %4.0f%% coverage'
              % (i, len(files), pid, len(beats), len(anchors), 100 * cov))

    rows.sort(key=lambda r: r['coverage'])
    print('\nreseeded %d, skipped %d' % (len(rows), len(skipped)))
    if rows:
        import statistics as st
        cs = [r['coverage'] for r in rows]
        print('  anchor coverage: median %.0f%%  min %.0f%%  max %.0f%%'
              % (100 * st.median(cs), 100 * min(cs), 100 * max(cs)))
        print('  t03 reference: 74%% coverage gave 75%% within 150 ms')
        print('\n  LOWEST coverage -- treat these seeds as arithmetic, not alignment:')
        for r in rows[:8]:
            print('    %-30s %3d/%-3d %4.0f%%'
                  % (r['piece_id'], r['n_anchors'], r['n_glyphs'], 100 * r['coverage']))
    json.dump({'pieces': rows, 'skipped': skipped},
              open(os.path.join(a.out_dir, '_summary.json'), 'w'), indent=1)
    for f, why in skipped[:12]:
        print('   skip %-34s %s' % (f, why))
    return 0


if __name__ == '__main__':
    sys.exit(main())
