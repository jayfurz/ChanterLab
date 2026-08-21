#!/usr/bin/env python3
"""onset_eval.py -- the one scorer for note-onset accuracy.

NEURAL-CHANT.md claims every number names the script that produced it. Several
did not: the 50/100 ms rates, bias, jitter, the bias-offset result and the slip
count all lived in prose. This is that script. It emits a per-note signed error
vector so any later run can be diffed against it, not just re-asserted.

Sign convention: dt = prediction - gold. NEGATIVE IS EARLY.

Metrics, per docs/plans/NEURAL-CHANT.md section 9:
  * primary gate      frac(round(|dt|,3) <= 0.150)
  * quality tier      frac(<= 0.100)          diagnostic  frac(<= 0.050)
  * asymmetric        frac(-0.200 <= dt <= +0.100)   early beats late
  * bias / jitter     signed mean / signed stdev
  * slips             maximal out-of-gate runs LONGER than SLIP_RETURN notes,
                      i.e. drift that leaves the gate and does not return. See
                      slips() for the two wrong readings this replaced, and why
                      the "does not return" clause is the whole point. t03's
                      published count is unchanged at 2 (runs of 45 and 6).

Do NOT subtract bias before slips are controlled. Measured on t03, removing the
signed mean takes the 50 ms rate from 30% to 7%: the +0.566 s "bias" is not a
lead, it is the mean of a distribution carrying 2.333 s of slip-driven jitter,
and subtracting it wrecks the notes that were already right. The script reports
the bias-corrected rate only so that trap stays visible.

Every system reports through this one script (NEURAL-CHANT.md section 9), so it
takes predictions from either source:

  --piece  the annotator's own slot times (the baseline)
  --pred   any {glyph_index: seconds} file -- NN-00's arithmetic baseline,
           fa_eval.py's forced-alignment onsets, later the model's decode.
           Accepted shapes: {"0": 1.97, ...} | [[0, 1.97], ...] |
           {"onsets": <either of those>}. A --label names it in the output.

Usage:
  onset_eval.py --piece grave-orthros-t03 --pins datasets/grave-orthros-t03-gold/pins.json
  onset_eval.py --pred nn00_t03.json --pins ... --label nn00 --json out.json
"""
import argparse, json, os, statistics as st, sys

GATE, TIER, DIAG = 0.150, 0.100, 0.050
ASYM_EARLY, ASYM_LATE = -0.200, 0.100
SLIP_RETURN = 3

ANNOT = 'tools/chant-reel/annotator/data'


def _pairs(raw):
    """{gi: t} | [[gi, t], ...] | {'onsets'|'pins': either} -> {int: float}."""
    if isinstance(raw, dict):
        for k in ('onsets', 'pins', 'pred'):
            if k in raw:
                return _pairs(raw[k])
        return {int(k): float(v) for k, v in raw.items()}
    return {int(g): float(t) for g, t in raw}


def load_pins(pins_path):
    return _pairs(json.load(open(pins_path)))


def load_annotator(piece):
    """The annotator's slot times -- the baseline prediction source.

    Regenerate a missing piece with:
      prep_hymn_annotator.py --workdir <corpus workdir> --hymn <name>
    The directory is a build artefact, not checked in; the reproduction of
    baseline_errors.json is bit-exact after a regen (verified 2026-08-20).
    """
    path = os.path.join(ANNOT, piece, 'annotator_data.json')
    if not os.path.exists(path):
        sys.exit('no annotator data at %s\n  regenerate: prep_hymn_annotator.py '
                 '--workdir <workdir> --hymn <hymn>' % path)
    a = json.load(open(path))
    return {int(g): float(t) for g, t in zip(a['slots']['gi'], a['slots']['t'])}


def load(piece, pins_path):
    return load_annotator(piece), load_pins(pins_path)


def slips(sig, gate=GATE, back=SLIP_RETURN):
    """Maximal runs outside the gate that do not return within `back` notes.

    Read the sentence literally, because two earlier readings were wrong. Drift
    leaves the gate at note i. If any of the next `back` notes is back inside the
    gate, it RETURNED, and that is jitter. If none of them is, it did not return,
    and that is a slip. So a maximal out-of-gate run counts once, and only if it
    is longer than `back` notes.

    Two rejected readings, kept because each looked right:

    * count every excursion (the original). Then one scattered miss is a slip and
      `0 slips` means `100% within the gate`, which makes NEURAL-CHANT section
      10's NN-06 gate -- ">=90% <=150ms AND 0 slips" -- unsatisfiable at 90% by
      construction.
    * end an excursion at the first `back` CONSECUTIVE in-gate notes and count it
      if the SPAN exceeds `back`. That span includes the in-gate notes it swallowed,
      so `out,in,in,out` scores a slip while `out,out,out` scores none: strictly
      worse signal, fewer slips. Non-monotonic, and it fires on pure jitter about
      half the time at 90% in-gate, which matters because NN-06 is evaluated once
      on the sealed fold and a false slip is a one-shot false failure.

    This reading is monotone in run length, ignores oscillation that touches the
    gate every couple of notes (that is jitter, which bias/jitter already report),
    and still catches a genuine loss of sync, which is always many notes long.
    t03's two runs are 45 notes (glyphs 3-47) and 6 notes (glyphs 70-75); the
    published count of 2 is unchanged under all three readings.

    Adjacency note: `sig` is the compacted vector of MATCHED notes, so a
    prediction that places only a scattered subset has had its gaps closed and
    cannot accumulate a meaningful run. Slip count is only readable next to
    n_matched -- see 'stats_over' in report().
    """
    n, i, out = len(sig), 0, 0
    while i < n:
        if abs(sig[i]) <= gate:
            i += 1
            continue
        j = i
        while j < n and abs(sig[j]) > gate:      # the maximal out-of-gate run
            j += 1
        if j - i > back:                          # never returned within `back`
            out += 1
        i = j
    return out


def report(pred, pins):
    gs = sorted(g for g in pins if g in pred)
    missing = [g for g in pins if g not in pred]
    sig = [pred[g] - pins[g] for g in gs]          # prediction - gold
    n = len(pins)                                   # unmatched counts as a miss
    if not sig:
        # No glyph index in the prediction matches any pin -- usually a different
        # indexing convention, not a system that got everything wrong. Say so
        # rather than dividing by zero.
        return {'n_gold': n, 'n_matched': 0, 'n_unmatched': n,
                'gate_150ms': 0.0, 'tier_100ms': 0.0, 'diag_50ms': 0.0,
                'asym_200e_100l': 0.0, 'bias_s': None, 'jitter_s': None,
                'median_abs_s': None, 'slips': None,
                'gate_150ms_if_bias_removed': 0.0, 'diag_50ms_if_bias_removed': 0.0,
                'stats_over': {'rates': 'n_gold', 'bias_jitter_median_slips': 'n_matched'},
                'error': 'no predicted glyph index matches any pin; check the '
                         'glyph-indexing convention of the prediction file',
                'signed_errors': {}}
    def frac(f): return sum(1 for x in sig if f(x)) / n
    bias = sum(sig) / len(sig)
    corr = [x - bias for x in sig]
    return {
        'n_gold': n, 'n_matched': len(gs), 'n_unmatched': len(missing),
        'gate_150ms': frac(lambda x: round(abs(x), 3) <= GATE),
        'tier_100ms': frac(lambda x: round(abs(x), 3) <= TIER),
        'diag_50ms':  frac(lambda x: round(abs(x), 3) <= DIAG),
        'asym_200e_100l': frac(lambda x: ASYM_EARLY <= x <= ASYM_LATE),
        # Rates are over n_gold: an unplaceable note is a miss, not an excused
        # absence. The signed statistics can only be computed where a prediction
        # exists, so they are over n_matched -- a system that places only its
        # easy notes will show a flattering bias and jitter. 'stats_over' says
        # which denominator each side used so the two are never read as one.
        'stats_over': {'rates': 'n_gold', 'bias_jitter_median_slips': 'n_matched'},
        'bias_s': bias, 'jitter_s': st.pstdev(sig),
        'median_abs_s': st.median(abs(x) for x in sig),
        'slips': slips(sig),
        'gate_150ms_if_bias_removed': sum(1 for x in corr if round(abs(x), 3) <= GATE) / n,
        'diag_50ms_if_bias_removed': sum(1 for x in corr if round(abs(x), 3) <= DIAG) / n,
        'signed_errors': {str(g): round(v, 6) for g, v in zip(gs, sig)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--piece', help="score the annotator's slot times")
    ap.add_argument('--pred', help='score a {glyph: seconds} prediction file')
    ap.add_argument('--pins', required=True)
    ap.add_argument('--label', help='name for this prediction source in the output')
    ap.add_argument('--json')
    a = ap.parse_args()
    if bool(a.piece) == bool(a.pred):
        ap.error('give exactly one of --piece or --pred')
    pred = load_annotator(a.piece) if a.piece else _pairs(json.load(open(a.pred)))
    r = report(pred, load_pins(a.pins))
    r['label'] = a.label or a.piece or os.path.basename(a.pred)
    r['pred_source'] = ('annotator:' + a.piece) if a.piece else a.pred
    r['pins_source'] = a.pins
    print('%s  (n=%d gold, %d matched, %d unmatched)'
          % (r['label'], r['n_gold'], r['n_matched'], r['n_unmatched']))
    print('  GATE  <=150 ms   %5.1f %%      slips %d' % (100 * r['gate_150ms'], r['slips']))
    print('  tier  <=100 ms   %5.1f %%' % (100 * r['tier_100ms']))
    print('  diag  <= 50 ms   %5.1f %%' % (100 * r['diag_50ms']))
    print('  asym -200/+100   %5.1f %%' % (100 * r['asym_200e_100l']))
    print('  bias %+.3f s     jitter %.3f s     median |dt| %.3f s'
          % (r['bias_s'], r['jitter_s'], r['median_abs_s']))
    if r['n_unmatched']:
        print('  NOTE rates are over all %d gold notes; bias/jitter/median/slips'
              ' over the %d placed. Do not compare the signed statistics of a'
              ' system that places %d notes against one that places all of them.'
              % (r['n_gold'], r['n_matched'], r['n_matched']))
    print('  if bias were subtracted:  <=150 ms %.1f %%   <=50 ms %.1f %%   <- do not do this'
          % (100 * r['gate_150ms_if_bias_removed'], 100 * r['diag_50ms_if_bias_removed']))
    if a.json:
        json.dump(r, open(a.json, 'w'), indent=1)
        print('->', a.json)


if __name__ == '__main__':
    sys.exit(main())
