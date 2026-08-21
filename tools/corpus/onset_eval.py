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
  * slips             maximal runs where signed drift leaves the gate and does
                      not return within SLIP_RETURN notes

Do NOT subtract bias before slips are controlled. Measured on t03, removing the
signed mean takes the 50 ms rate from 30% to 7%: the +0.566 s "bias" is not a
lead, it is the mean of a distribution carrying 2.333 s of slip-driven jitter,
and subtracting it wrecks the notes that were already right. The script reports
the bias-corrected rate only so that trap stays visible.

Usage:
  onset_eval.py --piece grave-orthros-t03 --pins datasets/grave-orthros-t03-gold/pins.json
  onset_eval.py --piece ... --pins ... --json out.json
"""
import argparse, json, os, statistics as st, sys

GATE, TIER, DIAG = 0.150, 0.100, 0.050
ASYM_EARLY, ASYM_LATE = -0.200, 0.100
SLIP_RETURN = 3

ANNOT = 'tools/chant-reel/annotator/data'


def load(piece, pins_path):
    a = json.load(open(os.path.join(ANNOT, piece, 'annotator_data.json')))
    pred = {g: t for g, t in zip(a['slots']['gi'], a['slots']['t'])}
    raw = json.load(open(pins_path))
    pins = dict(raw['pins'] if isinstance(raw, dict) and 'pins' in raw else raw)
    return pred, pins


def slips(sig, gate=GATE, back=SLIP_RETURN):
    """Maximal runs outside the gate that do not return within `back` notes."""
    n, i, out = len(sig), 0, 0
    while i < n:
        if abs(sig[i]) <= gate:
            i += 1
            continue
        j = i
        while j < n:
            look = [k for k in range(j, min(j + back, n)) if abs(sig[k]) <= gate]
            if len(look) == min(back, n - j):
                break
            j += 1
        out += 1
        i = max(j, i + 1)
    return out


def report(pred, pins):
    gs = sorted(g for g in pins if g in pred)
    missing = [g for g in pins if g not in pred]
    sig = [pred[g] - pins[g] for g in gs]          # prediction - gold
    n = len(pins)                                   # unmatched counts as a miss
    def frac(f): return sum(1 for x in sig if f(x)) / n
    bias = sum(sig) / len(sig)
    corr = [x - bias for x in sig]
    return {
        'n_gold': n, 'n_matched': len(gs), 'n_unmatched': len(missing),
        'gate_150ms': frac(lambda x: round(abs(x), 3) <= GATE),
        'tier_100ms': frac(lambda x: round(abs(x), 3) <= TIER),
        'diag_50ms':  frac(lambda x: round(abs(x), 3) <= DIAG),
        'asym_200e_100l': frac(lambda x: ASYM_EARLY <= x <= ASYM_LATE),
        'bias_s': bias, 'jitter_s': st.pstdev(sig),
        'median_abs_s': st.median(abs(x) for x in sig),
        'slips': slips(sig),
        'gate_150ms_if_bias_removed': sum(1 for x in corr if round(abs(x), 3) <= GATE) / n,
        'diag_50ms_if_bias_removed': sum(1 for x in corr if round(abs(x), 3) <= DIAG) / n,
        'signed_errors': {str(g): round(v, 6) for g, v in zip(gs, sig)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--piece', required=True)
    ap.add_argument('--pins', required=True)
    ap.add_argument('--json')
    a = ap.parse_args()
    r = report(*load(a.piece, a.pins))
    print('%s  (n=%d gold, %d matched, %d unmatched)'
          % (a.piece, r['n_gold'], r['n_matched'], r['n_unmatched']))
    print('  GATE  <=150 ms   %5.1f %%      slips %d' % (100 * r['gate_150ms'], r['slips']))
    print('  tier  <=100 ms   %5.1f %%' % (100 * r['tier_100ms']))
    print('  diag  <= 50 ms   %5.1f %%' % (100 * r['diag_50ms']))
    print('  asym -200/+100   %5.1f %%' % (100 * r['asym_200e_100l']))
    print('  bias %+.3f s     jitter %.3f s     median |dt| %.3f s'
          % (r['bias_s'], r['jitter_s'], r['median_abs_s']))
    print('  if bias were subtracted:  <=150 ms %.1f %%   <=50 ms %.1f %%   <- do not do this'
          % (100 * r['gate_150ms_if_bias_removed'], 100 * r['diag_50ms_if_bias_removed']))
    if a.json:
        json.dump(r, open(a.json, 'w'), indent=1)
        print('->', a.json)


if __name__ == '__main__':
    sys.exit(main())
