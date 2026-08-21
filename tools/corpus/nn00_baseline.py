#!/usr/bin/env python3
"""nn00_baseline.py — the arithmetic floor: beats_seq + one constant tempo.

NN-00 in docs/plans/NEURAL-CHANT.md section 10. Every later onset number is
measured against this. If a 4 M-parameter encoder-decoder cannot beat
"cumulative written beats times one number", the plan has a problem, so the
baseline is fitted as well as an honest constant-tempo model can be, not as a
strawman.

    onset_i = t0 + (beats written before unit i) * seconds_per_beat

Per-unit beats come from hymn_align.beats_seq(), never beats_of(): the
gorgon family and the argon reach into their neighbours, so a note's duration
is not a property of that note alone.

Measured on grave-orthros-t03, 2026-08-20. t03 is TRAINING data and a BURNT
benchmark (section 6.1): these are comparison numbers against the annotator on
the same 76 pins, never evidence of generalisation. Scored end to end by
tools/corpus/onset_eval.py, the only scorer.

  variant                kind            <=150ms <=100ms <=50ms  bias   jitter
  lad_oracle             oracle           43.4 %  34.2 % 15.8 % -0.121  0.472
  ols_oracle             oracle           38.2 %  30.3 % 14.5 % +0.000  0.438
  theilsen_oracle        oracle           38.2 %  25.0 % 13.2 % -0.087  0.459
  prefix16_ols           inference-only   23.7 %  13.2 %  5.3 % -0.803  0.895
  prefix12_ols           inference-only   17.1 %  15.8 % 11.8 % -1.493  1.315
  prefix8_ols            inference-only   13.2 %  10.5 %  7.9 % -2.167  1.726
  anchor_audio_duration  inference-only    2.6 %   1.3 %  1.3 % +2.609  1.251
  (annotator today)                        32.9 %  32.9 % 30.3 % +0.566  2.333

THE ORACLE VARIANTS FIT 2 PARAMETERS ON THE 76 POINTS THEY ARE THEN SCORED ON.
They bound what constant-tempo arithmetic can do on this piece; they are not a
system. The inference-only variants are what something could actually emit at
run time, and they are far worse. A model that beats prefix16_ols has beaten a
usable arithmetic baseline; a model that beats lad_oracle has beaten the class.

What the numbers show, and what they do not:

  * The best oracle fit, 43.4 % at 150 ms, is ABOVE the annotator's 32.9 %:
    the aligner is currently worse than a ruler. It is far BELOW the annotator
    at 50 ms (15.8 % vs 30.3 %). Arithmetic is never exactly right and never
    badly wrong; the annotator is exact where it holds sync and seconds out
    where it does not. The two are wrong in different shapes, and only the
    150 ms column compares them fairly.
  * Shape. lad_oracle's signed error stays inside +/-0.50 s for glyphs 0-71
    and then runs -1.16, -1.44, -2.01, -2.57 on glyphs 72-75. That is the
    final cadence: the singer slows, a constant tempo cannot, so the whole
    error is a terminal ritardando, plus a slow +/-0.3 s breathing swell over
    the body. Compare section 0.1's annotator: +4.6 s, back through zero,
    -3.1 s, recover. Bounded rubato error versus lost sync — different
    failures, and 2.57 s of it lives in 4 notes.
  * SLIPS ARE NOT COMPARABLE ACROSS THESE TWO CLASSES, in either direction.
    onset_eval's slip counter reads the signed error curve; it knows nothing
    about mechanism. A constant-tempo model has no sync to lose -- it never
    decides it is on a different note -- so its 5 "slips" are 5 stretches
    where accumulated rubato left the 150 ms band, most of them self-
    correcting. The annotator's 2 are excursions to a different note
    entirely. Worse, the counter degenerates the other way: prefix8_ols is
    outside the gate almost everywhere and therefore reports ONE slip, its
    best-looking slip number in the table and its worst prediction. Read
    slips only next to the gate rate, and never across system classes.
  * Evidence-class split (diagnostic, not a denominator): 18 of 76 glyphs
    carry no fresh syllable -- the count section 0.1 predicts, confirmed here
    from the chanter's own labels. Arithmetic scores the two classes within
    1.3 points of each other (lad_oracle: 43.1 % fresh, 44.4 % continuing
    vowel) because it never listens to the audio. That is why the split is
    worth printing: the class that breaks acoustic systems is free for this
    one, so an acoustic system that scores WORSE on continuing-vowel notes
    than 44 % has been beaten there by arithmetic.
  * anchor_audio_duration fails for a reason worth keeping: 87 written beats
    over the voiced span implies 0.581 s/beat, 9 % faster than the 0.528 the
    piece is actually sung at. The written beats do not account for the held
    ending, so total duration is a biased tempo estimator. Do not fix this by
    fitting the span against the pins -- that would make it another oracle.

Score-side reconciliation, checked by this script on every run:
  * score_degrees.units_for(520, 6, 70, 520, 11, 145) reproduces the 76 stored
    units of datasets/grave-orthros-t03-gold/score_units.json exactly (key,
    page/line, x-extent), and equals hymn_align.load_units_h() on the t03
    hymns.json row. units_for's l0/l1 are ignored by load_units; the g-bounds
    are page-glyph indices, and 70 is where line 6 starts on page 520.
  * A fresh beats_seq() over those units agrees with the stored 'beats' field
    on all 76 units, and slicing the units out of the full page first does not
    change any of them — no neighbour effect crosses the hymn boundary.

Usage:
  nn00_baseline.py --outdir <dir>          # writes nn00_*.json, prints the table
"""
import argparse, json, os, statistics as st, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import beats_seq, load_units_h
from score_degrees import units_for

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONSET_EVAL = os.path.join(REPO, 'tools', 'corpus', 'onset_eval.py')
GOLD = os.path.join(REPO, 'datasets', 'grave-orthros-t03-gold')
PINS = os.path.join(GOLD, 'pins.json')
UNITS = os.path.join(GOLD, 'score_units.json')
ANNOT = os.path.join(REPO, 'tools', 'chant-reel', 'annotator', 'data',
                     'grave-orthros-t03', 'annotator_data.json')
HYMNS = '/mnt/data/chant-corpus/workdirs/grave-orthros/hymns.json'
AUDIO = '/mnt/data/chant-corpus/workdirs/grave-orthros/melos_t03_/audio.wav'
RMS = '/mnt/data/chant-corpus/workdirs/grave-orthros/melos_t03_/rms_track.npy'

# page-glyph bounds of the t03 slice inside page 520; see the docstring.
UF_ARGS = (520, 6, 70, 520, 11, 145)
PREFIXES = (8, 12, 16)
VOICED_FRAC = 0.10        # of peak RMS, the voiced-frame threshold


def _fingerprint(u):
    return [u['key'], list(u['pl']), round(u['x0'], 1), round(u['x1'], 1)]


def score_units():
    """The 76-unit t03 stream, plus the reconciliation against the frozen copy."""
    stored = json.load(open(UNITS))
    hymn = [r for r in json.load(open(HYMNS)) if r['name'] == 't03_'][0]
    via_hymn, _ = load_units_h(hymn)
    page = units_for(UF_ARGS[0], UF_ARGS[1], 0, UF_ARGS[3], UF_ARGS[4], 10 ** 9)
    via_uf = units_for(*UF_ARGS)

    fresh = beats_seq(via_uf)
    whole_page = beats_seq(page)[UF_ARGS[2]:UF_ARGS[2] + len(via_uf)]
    recon = {
        'n_stored': len(stored),
        'n_units_for': len(via_uf),
        'n_load_units_h': len(via_hymn),
        'units_for_matches_load_units_h':
            [_fingerprint(u) for u in via_uf] == [_fingerprint(u) for u in via_hymn],
        'units_for_matches_stored':
            [_fingerprint(u) for u in via_uf]
            == [[s['key'], [s['page'], s['line']], round(s['x0'], 1), round(s['x1'], 1)]
                for s in stored],
        'fresh_beats_match_stored': fresh == [s['beats'] for s in stored],
        'beats_stable_under_slicing': fresh == whole_page,
        'total_beats': sum(fresh),
    }
    return via_uf, fresh, recon


def cumulative(beats):
    """Beats written BEFORE unit i. Unit 0 sits at 0."""
    out, run = [], 0.0
    for b in beats:
        out.append(run)
        run += b
    return out


def load_pins():
    return {int(g): float(t) for g, t in json.load(open(PINS))}


def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return my - slope * mx, slope


def theil_sen(xs, ys):
    slopes = sorted((ys[j] - ys[i]) / (xs[j] - xs[i])
                    for i in range(len(xs)) for j in range(i + 1, len(xs))
                    if xs[j] != xs[i])
    s = st.median(slopes)
    return st.median(y - s * x for x, y in zip(xs, ys)), s


def lad(xs, ys):
    """Least absolute deviations, slope on a fixed 0.5 ms/beat grid.

    Deterministic by construction: an integer sweep, no solver, no seed. LAD
    rather than OLS because the gate counts notes inside 150 ms and squared
    error spends its budget on the two worst cadence stretches instead.
    """
    best = None
    for k in range(601):                     # 0.400 .. 0.700 s/beat
        s = 0.400 + k * 0.0005
        t = st.median(y - s * x for x, y in zip(xs, ys))
        cost = sum(abs(t + s * x - y) for x, y in zip(xs, ys))
        if best is None or cost < best[0]:
            best = (cost, t, s)
    return best[1], best[2]


def voiced_span():
    """First/last frame above 10 % of peak RMS — available at inference."""
    import numpy as np
    import soundfile as sf
    rms = np.load(RMS)
    dur = sf.info(AUDIO).duration
    hop = dur / len(rms)
    idx = np.where(rms > VOICED_FRAC * rms.max())[0]
    return float(idx[0] * hop), float(idx[-1] * hop), float(dur)


def variants(cum, pins, total_beats):
    """(name, kind, note, t0, seconds_per_beat) for every fit."""
    n = len(cum)
    xs = cum
    ys = [pins[i] for i in range(n)]
    out = []
    for name, fn in (('lad_oracle', lad), ('ols_oracle', ols),
                     ('theilsen_oracle', theil_sen)):
        t0, spb = fn(xs, ys)
        out.append((name, 'oracle', 'fitted on all %d pins it is then scored on' % n,
                    t0, spb))
    # 'pin-frugal', NOT 'inference-only': these fit on a PREFIX of the gold
    # pins and extrapolate, so they still consume chanter labels from the very
    # piece they score -- fewer of them, and none from the stretch being
    # predicted, but not none. Calling them inference-only would claim a system
    # could emit these numbers cold, which is false. The direction is
    # conservative (a pin-fed ruler sets a HARDER bar for the model than a
    # pin-free one would), so they stand as a floor; only the label was wrong.
    for N in sorted(PREFIXES, reverse=True):
        t0, spb = ols(xs[:N], ys[:N])
        out.append(('prefix%d_ols' % N, 'pin-frugal',
                    'fitted on the first %d gold pins, extrapolated to %d' % (N, n),
                    t0, spb))
    v0, v1, _ = voiced_span()
    # This one takes its ORIGIN from pins[0] and only its tempo from the audio.
    # The variant that uses no pin at all is below it.
    out.append(('anchor_audio_duration', 'pin-frugal',
                't0 = first gold pin; tempo = voiced audio span %.3f-%.3f s over '
                '%g written beats' % (v0, v1, total_beats),
                ys[0], (v1 - ys[0]) / total_beats))
    # Genuinely pin-free: origin AND tempo from the audio alone. This is the
    # only row a deployed system could actually emit on an unseen recording,
    # and it is the honest floor the model has to clear.
    out.append(('audio_only', 'pin-free',
                't0 = voiced onset %.3f s; tempo = voiced span over %g written '
                'beats -- no gold pin used' % (v0, total_beats),
                v0, (v1 - v0) / total_beats))
    return out


def evidence_class():
    """{glyph: has_fresh_syllable}. An EMPTY label is a continuing-vowel note.

    Section 0.1: that marks a note sung on a vowel already sounding, NOT a
    lesser note. Glyph 0's label is empty for a different reason — it lost its
    first syllable (section 0.4) — and is left in the label-less class rather
    than special-cased, because this script has no way to tell the two apart
    and inventing one would hide the count.
    """
    a = json.load(open(ANNOT))
    s = a['slots']
    return {int(g): bool(l.strip())
            for g, sub, l in zip(s['gi'], s['sub'], s['label']) if sub == 0}


def run_eval(pred_path, label, out_path):
    subprocess.run([sys.executable, ONSET_EVAL, '--pred', pred_path,
                    '--pins', PINS, '--label', label, '--json', out_path],
                   check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    return json.load(open(out_path))


def drift_shape(sig, step=8):
    return [round(sig[i], 3) for i in range(0, len(sig), step)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='.')
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    units, beats, recon = score_units()
    bad = [k for k, v in recon.items() if v is False]
    if bad:
        sys.exit('score-side reconciliation FAILED: %s\n%s'
                 % (', '.join(bad), json.dumps(recon, indent=1)))
    cum = cumulative(beats)
    pins = load_pins()
    if sorted(pins) != list(range(len(units))):
        sys.exit('pins do not cover units 0-%d exactly' % (len(units) - 1))

    fresh = evidence_class()
    n_fresh = sum(1 for v in fresh.values() if v)
    result = {
        'piece': 'grave-orthros-t03',
        'fold': 'gold train — BURNT BENCHMARK, comparison only, never generalisation',
        'pins': os.path.relpath(PINS, REPO),
        'n_units': len(units),
        'total_beats': sum(beats),
        'reconciliation': recon,
        'evidence_class': {
            'n_fresh_syllable': n_fresh,
            'n_continuing_vowel': len(fresh) - n_fresh,
            'continuing_vowel_glyphs': sorted(g for g, v in fresh.items() if not v),
            'source': os.path.relpath(ANNOT, REPO),
        },
        'variants': [],
    }

    rows = []
    for name, kind, note, t0, spb in variants(cum, pins, sum(beats)):
        pred = {str(i): round(t0 + spb * cum[i], 6) for i in range(len(cum))}
        pred_path = os.path.join(a.outdir, 'nn00_pred_%s.json' % name)
        json.dump(pred, open(pred_path, 'w'), indent=1)
        ev = run_eval(pred_path, 'nn00:' + name,
                      os.path.join(a.outdir, 'nn00_eval_%s.json' % name))
        sig = [ev['signed_errors'][str(i)] for i in range(len(cum))]
        by = {}
        for want, key in ((True, 'fresh_syllable'), (False, 'continuing_vowel')):
            idx = [i for i in range(len(cum)) if fresh[i] is want]
            by[key] = {
                'n': len(idx),
                'gate_150ms': sum(1 for i in idx if round(abs(sig[i]), 3) <= 0.150) / len(idx),
                'median_abs_s': st.median(abs(sig[i]) for i in idx),
            }
        result['variants'].append({
            'name': name, 'kind': kind, 'fit': note,
            't0_s': round(t0, 6), 'seconds_per_beat': round(spb, 6),
            'onset_eval': ev,
            'drift_every_8th_glyph': drift_shape(sig),
            'max_abs_drift_s': round(max(abs(x) for x in sig), 3),
            'by_evidence_class': by,
        })
        rows.append((name, kind, ev, by))

    out = os.path.join(a.outdir, 'nn00_t03.json')
    json.dump(result, open(out, 'w'), indent=1, sort_keys=True)

    print('NN-00 arithmetic baseline — grave-orthros-t03 (BURNT benchmark, %d pins)'
          % len(pins))
    print('  units_for%s == load_units_h == frozen score_units.json; beats agree 76/76'
          % (UF_ARGS,))
    print('  %g written beats; %d of %d glyphs carry no fresh syllable'
          % (sum(beats), len(fresh) - n_fresh, len(fresh)))
    print()
    print('  %-22s %-14s %7s %7s %7s %6s %8s %8s'
          % ('variant', 'kind', '<=150ms', '<=100ms', '<=50ms', 'slips', 'bias', 'jitter'))
    for name, kind, ev, _ in rows:
        print('  %-22s %-14s %6.1f%% %6.1f%% %6.1f%% %6d %+8.3f %8.3f'
              % (name, kind, 100 * ev['gate_150ms'], 100 * ev['tier_100ms'],
                 100 * ev['diag_50ms'], ev['slips'], ev['bias_s'], ev['jitter_s']))
    print()
    for name, kind, ev, by in rows:
        print('  %-22s fresh %2d: %5.1f%%   continuing-vowel %2d: %5.1f%%'
              % (name, by['fresh_syllable']['n'],
                 100 * by['fresh_syllable']['gate_150ms'],
                 by['continuing_vowel']['n'],
                 100 * by['continuing_vowel']['gate_150ms']))
    print()
    best = max(rows, key=lambda r: r[2]['gate_150ms'])
    print('  drift every 8th glyph, %s: %s'
          % (best[0], '  '.join('%+.1f' % x for x in
                                drift_shape([best[2]['signed_errors'][str(i)]
                                             for i in range(len(cum))]))))
    print('  a constant-tempo model has no sync to lose; its slip count measures')
    print('  accumulated rubato, not desync, and is not comparable to the annotator\'s.')
    print('->', out)


if __name__ == '__main__':
    sys.exit(main())
