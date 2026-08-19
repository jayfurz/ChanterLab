#!/usr/bin/env python3
"""ingest_pins.py — pull chanter-verified pins out of the annotator's exports
and score them against the machine alignment; maintain the verification ledger.

For every <exports>/<piece>/pins.json (written by the annotator's Export via
serve.py) whose piece is in the annotator manifest (data/index.json):

  1. timing check    pinned onset vs the machine's aligned t0 per unit
                     (median / p90 |dt|; confirm <= TOL, contradict > TOL)
  2. degree check    sung degree at each pin (median cents just after onset,
                     quantized on the hymn's genus ladder + fitted Νη) —
                     consecutive pinned deltas vs the notation's expected
                     deltas = STRICT-ON-PINS, the ground-truth analogue of
                     align_eval's strict column
  3. staging         pins + mcr_flags are copied into the hymn's melos dir
                     (melos_<name>/chanter_pins.json / chanter_flags.json) so
                     the aligner can consume them as hard anchors
  4. record          per-piece row in the verification ledger
                     (/mnt/data/chant-corpus/verification_ledger.json)

Usage:
  ingest_pins.py                  # ingest everything exported, print scoreboard
  ingest_pins.py --piece mode1-t04
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import LADDERS

CORPUS = '/mnt/data/chant-corpus'
LEDGER = os.path.join(CORPUS, 'verification_ledger.json')
CPM = 1200.0 / 72.0
TOL = 0.35          # s: pin agrees with machine onset
PIN_WIN = (0.03, 0.35)   # onset transient skipped / fallback span cap (s)


def empirical_ladder(aligned, ni_c, pos):
    """theory ladder overridden per degree by the median cents the aligner's
    own matched events sang at that degree — Vasilikos sits 30-70c off
    Chrysanthine theory, so nearest-THEORY quantization mislabels borderline
    notes (same reason cmd_melos refits empirical centers)."""
    import numpy as np
    lad = {d: ni_c + pos(d) * CPM for d in range(-15, 26)}
    by = {}
    for a in aligned:
        by.setdefault(a['degree_obs'], []).append(a['cents'])
    for d, cs in by.items():
        if d in lad and len(cs) >= 2:
            lad[d] = float(np.clip(np.median(cs), lad[d] - 80, lad[d] + 80))
    return lad


def sung_degree(cents, t0, t1, lad, dt=0.01):
    """degree over the note span [t0, t1]: median finite cents (skipping the
    onset transient), quantized on the (empirical) ladder. None if the span
    is unvoiced. Calibrated on machine pairs: with true event spans this
    matches the aligner's degree_obs 61/62."""
    import numpy as np
    i0, i1 = int((t0 + PIN_WIN[0]) / dt), int(t1 / dt)
    win = cents[max(0, i0):max(i0 + 1, i1)]
    win = win[np.isfinite(win)]
    if len(win) < 3:
        return None
    m = float(np.median(win))
    return min(lad, key=lambda d: abs(lad[d] - m))


def ingest_piece(p, exports_dir):
    """Score one piece's export; returns a ledger row or None."""
    import numpy as np
    pdir = os.path.join(exports_dir, p['id'])
    pins_f = os.path.join(pdir, 'pins.json')
    if not os.path.exists(pins_f):
        return None
    pins = json.load(open(pins_f))
    flags = []
    ff = os.path.join(pdir, 'mcr_flags.json')
    if os.path.exists(ff):
        flags = json.load(open(ff))
    # chanter-consistent full timeline (corrected times for EVERY slot):
    # gives each pinned note its true end boundary for pitch sampling.
    # slots_corrected.json is the UI's column format: {t[], gi[], sub[], ...}
    slot_t = {}
    sc = os.path.join(pdir, 'slots_corrected.json')
    if os.path.exists(sc):
        d = json.load(open(sc))
        for gi, sub, t in zip(d['gi'], d['sub'], d['t']):
            if sub == 0:
                slot_t[gi] = t
    wd, name = p['workdir'], p['hymn']
    mdir = os.path.join(wd, 'melos_' + name)
    summ = json.load(open(os.path.join(mdir, 'summary.json')))
    aligned = json.load(open(os.path.join(mdir, 'aligned.json')))
    cents = np.load(os.path.join(mdir, 'cents_track.npy'))
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    pos = LADDERS[summ['genus']]
    ni_c = summ['ni_cents_rel55']
    mcr = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'chant-reel',
        'annotator', 'data', p['id'], 'mcr_interpretation.json')))

    t_mach = {a['unit']: a['t0'] for a in aligned}
    pins = sorted(pins, key=lambda x: x[1])

    # 1. timing agreement on machine-matched pinned units
    dts = sorted(abs(t - t_mach[gi]) for gi, t in pins if gi in t_mach)
    n_conf = sum(d <= TOL for d in dts)

    # 2. strict-on-pins: consecutive pinned degree deltas vs notation
    key_of = {r['gi']: r['cp'] for r in mcr}
    # chanter interval overrides win; else the aligner's iv_of fallback
    # (unknown mark-combos take the bare base glyph's interval)
    ovr = {}
    ivo = os.path.join(wd, f'iv_ovr_{name}.json')
    if os.path.exists(ivo):
        ovr = {int(k): v for k, v in json.load(open(ivo)).items()}
    iv_u = lambda j: ovr[j] if j in ovr else (
        iv[key_of[j]] if key_of.get(j) in iv
        else iv.get(key_of.get(j, '').split('|')[0] + '|', 0))
    lad = empirical_ladder(aligned, ni_c, pos)
    n_pairs = n_agree = 0
    disagreements = []   # chanter-vs-legend interval evidence (legend work items)
    prev = None          # (gi, sung_deg)
    for k, (gi, t) in enumerate(pins):
        # note span end: next slot on the chanter-consistent timeline,
        # else next pin, capped at the fallback window
        t1 = slot_t.get(gi + 1,
                        pins[k + 1][1] if k + 1 < len(pins) else t + PIN_WIN[1])
        sd = sung_degree(cents, t, min(t1, t + 1.5), lad)
        if sd is None:
            continue
        if prev is not None and gi > prev[0]:
            exp_delta = sum(iv_u(j) for j in range(prev[0] + 1, gi + 1))
            n_pairs += 1
            if (sd - prev[1]) == exp_delta:
                n_agree += 1
            elif gi - prev[0] == 1:
                # adjacent pins: the sung delta IS a supervised interval
                # estimate for this unit's key — legend correction evidence
                disagreements.append({'gi': gi, 'key': key_of.get(gi),
                                      'legend': exp_delta,
                                      'sung': sd - prev[1]})
        prev = (gi, sd)

    # 3. stage for the aligner
    with open(os.path.join(mdir, 'chanter_pins.json'), 'w') as f:
        json.dump(pins, f)
    if flags:
        with open(os.path.join(mdir, 'chanter_flags.json'), 'w') as f:
            json.dump(flags, f, indent=1)

    return {
        'piece': p['id'], 'workdir': wd, 'hymn': name,
        'n_pins': len(pins), 'n_flags': len(flags),
        'n_machine_checked': len(dts),
        'median_dt': round(dts[len(dts) // 2], 3) if dts else None,
        'p90_dt': round(dts[int(len(dts) * 0.9)], 3) if dts else None,
        'n_confirm': n_conf, 'n_contradict': len(dts) - n_conf,
        'strict_pins': round(n_agree / n_pairs, 3) if n_pairs else None,
        'n_pin_pairs': n_pairs,
        'legend_disagreements': disagreements,
        'machine_agreement': p.get('movement_agreement'),
        'machine_coverage_pct': p.get('coverage_pct'),
        'ingested_at': time.strftime('%Y-%m-%d %H:%M'),
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ann = os.path.normpath(os.path.join(here, '..', 'chant-reel', 'annotator'))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--exports-dir', default=os.path.join(ann, 'exports'))
    ap.add_argument('--piece', help='only this piece id')
    args = ap.parse_args()

    man_f = os.path.join(ann, 'data', 'index.json')
    if not os.path.exists(man_f):
        sys.exit(f'no manifest at {man_f} — run prep_hymn_annotator first')
    pieces = json.load(open(man_f))['pieces']
    if args.piece:
        pieces = [p for p in pieces if p['id'] == args.piece]
        if not pieces:
            sys.exit(f'piece {args.piece!r} not in manifest')

    ledger = {'pieces': {}}
    if os.path.exists(LEDGER):
        ledger = json.load(open(LEDGER))
    rows = []
    for p in pieces:
        if p.get('status') != 'ready':
            continue
        try:
            row = ingest_piece(p, args.exports_dir)
        except Exception as e:
            print(f"{p['id']}: ERROR {e}", file=sys.stderr)
            continue
        if row:
            rows.append(row)
            ledger['pieces'][row['piece']] = row
    if not rows:
        print('no exports found — Export from the annotator UI first '
              f'(looked in {args.exports_dir})')
        return
    ledger['updated_at'] = time.strftime('%Y-%m-%d %H:%M')
    tmp = LEDGER + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(ledger, f, indent=1)
    os.replace(tmp, LEDGER)

    hdr = f"{'piece':26} {'pins':>4} {'med dt':>7} {'confirm':>8} {'contra':>6} {'strict@pins':>11}"
    print(hdr + '\n' + '-' * len(hdr))
    for r in rows:
        print(f"{r['piece']:26} {r['n_pins']:>4} "
              f"{r['median_dt'] if r['median_dt'] is not None else '—':>7} "
              f"{r['n_confirm']:>8} {r['n_contradict']:>6} "
              f"{str(r['strict_pins']) if r['strict_pins'] is not None else '—':>11}")
    tot_pairs = sum(r['n_pin_pairs'] for r in rows)
    tot_agree = sum(round(r['strict_pins'] * r['n_pin_pairs'])
                    for r in rows if r['strict_pins'] is not None)
    if tot_pairs:
        print(f"\ncorpus strict-on-pins: {tot_agree / tot_pairs:.3f} "
              f"over {tot_pairs} ground-truth pairs from {len(rows)} hymns")
    for r in rows:
        if r['legend_disagreements']:
            print(f"\n{r['piece']}: chanter-vs-legend interval evidence "
                  f"(adjacent pins; legend work items):")
            for d in r['legend_disagreements']:
                print(f"  gi {d['gi']:>3} key {d['key']:<16} "
                      f"legend {d['legend']:+d}  sung {d['sung']:+d}")
    print(f"ledger: {LEDGER}")


if __name__ == '__main__':
    main()
