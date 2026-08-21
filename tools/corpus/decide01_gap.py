#!/usr/bin/env python3
"""decide01_gap.py -- DECIDE-01: what the model has to own, note by note.

NEURAL-CHANT.md section 10 asks for "a sized brief naming which notes the model
must own". This is the arithmetic behind docs/plans/DECIDE-01-BRIEF.md. It joins
one row per t03 glyph out of the other lanes' outputs -- it computes no onset of
its own and scores nothing itself, so the brief cannot drift away from the
scores it quotes.

Sources, all read, none recomputed:
  datasets/grave-orthros-t03-gold/pins.json         76 chanter pins (the gold)
  datasets/grave-orthros-t03-gold/score_units.json  unit key, beats per glyph
  tools/chant-reel/annotator/data/.../annotator_data.json   syllable labels
  repro01_char_onsets.json   REPRO-01's 179 CTC character onsets (candidates)
  repro01_fa_eval.json       REPRO-01's signed errors: char_first, ORACLE
  nn00_eval_lad_oracle.json / nn00_eval_prefix16_ols.json   NN-00's signed errors
The annotator's own signed errors come from onset_eval.py --piece, shelled out
here like every other lane does it. onset_eval.py stays the only scorer.

Classes partition the 76 on the CURRENT SHIPPING SYSTEM (the annotator, section
0.1), crossed with whether REPRO-01's character path holds a candidate:

  OWNED                annotator already within 150 ms       nobody must own it
  SELECTION_CLEAN      annotator outside, exactly one uncontested candidate
                       inside 150 ms
  SELECTION_AMBIGUOUS  annotator outside, a candidate inside 150 ms but more
                       than one, or the nearest is also nearest to another pin
  SUPPLY_TEXT          annotator outside, no candidate inside 150 ms, the glyph
                       carries a fresh syllable
  SUPPLY_VOWEL         the same with no syllable -- a continuing vowel
RESYNC is an overlay, not a class: the glyphs inside the annotator's slip runs.
Slip runs are extracted with a walker asserted, on every run, to return exactly
onset_eval.slips()'s count on the same vector.

Measured 2026-08-20 on grave-orthros-t03. t03 IS TRAINING DATA AND A BURNT
BENCHMARK: every number here is a fit diagnostic, never evidence of
generalisation.

  OWNED                25 / 76  32.9 %      SUPPLY_TEXT     6 / 76   7.9 %
  SELECTION_CLEAN      10 / 76  13.2 %      SUPPLY_VOWEL    1 / 76   1.3 %
  SELECTION_AMBIGUOUS  34 / 76  44.7 %

  51 notes fail today and ALL 51 sit inside the annotator's two slip runs
  (glyphs 3-47 and 70-75). There is no scattered-error class on this piece.
  To reach 90 % (69 of 76) the model must newly own 44 of those 51.

  Candidate ceiling, from REPRO-01's oracle (reads the gold pin to choose, so an
  upper bound and not an achieved score): 67 of 76 have a character candidate
  within 150 ms, 62 within 100 ms, 46 within 50 ms. Nine glyphs -- 7, 22, 46,
  58, 61, 72, 73, 74, 75 -- have none at any tolerance and must be generated.

  The oracle is less informative than it looks. Shifting every gold pin off the
  music by 0.5-2.0 s and re-asking leaves a MEDIAN 69.7 % still "covered" at
  150 ms (58.6 % at 100 ms, 37.5 % at 50 ms): with 179 candidates over the sung
  span, most of that coverage is density, not evidence. The oracle beats its own
  density null by 18.4 points at 150 ms and 23.0 at 50 ms.

  A best-of-three combiner over annotator, fa_char_first and nn00_prefix16_ols,
  choosing per glyph by reading the gold answer, reaches 77.6 % at 150 ms. No
  arbitration among today's systems reaches the 90 % gate.

What this does not show: nothing here says a selector can reach any ceiling, and
every ceiling quoted was computed with the gold answer in hand. It sizes the
problem; it does not predict a score.

Usage:
  decide01_gap.py --tmp <lane tmp dir> [--out <json>]
"""
import argparse, json, os, statistics as st, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onset_eval

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONSET_EVAL = os.path.join(REPO, 'tools', 'corpus', 'onset_eval.py')
GOLD = os.path.join(REPO, 'datasets', 'grave-orthros-t03-gold')
PINS = os.path.join(GOLD, 'pins.json')
UNITS = os.path.join(GOLD, 'score_units.json')
PIECE = 'grave-orthros-t03'
ANNOT = os.path.join(REPO, 'tools', 'chant-reel', 'annotator', 'data',
                     PIECE, 'annotator_data.json')

GATE, TIER, DIAG = onset_eval.GATE, onset_eval.TIER, onset_eval.DIAG
NEAR = 0.500          # neighbourhood half-width, ~one median IOI (section 9.1)
COMBINE = ('annotator', 'fa_char_first', 'nn00_prefix16_ols')   # inference-only
TARGET = 0.90         # section 9 release gate


def slip_runs(sig, gate=GATE, back=onset_eval.SLIP_RETURN):
    """The index spans onset_eval.slips() counts. Same walk, spans kept.

    This mirrors onset_eval.slips() and asserts it agrees, because a brief that
    names "the notes inside the slips" while the scorer counts different ones is
    worse than no brief. The assert is not decoration: it caught this walk still
    implementing the pre-2026-08-20 rule (count every excursion) after slips()
    was corrected to count only maximal out-of-gate runs longer than `back`.
    """
    n, i, out = len(sig), 0, []
    while i < n:
        if abs(sig[i]) <= gate:
            i += 1
            continue
        j = i
        while j < n and abs(sig[j]) > gate:
            j += 1
        if j - i > back:
            out.append((i, j - 1))
        i = j
    assert len(out) == onset_eval.slips(sig, gate, back), 'slip walk diverged from onset_eval'
    return out


def run_eval(args, out_path, label):
    subprocess.run([sys.executable, ONSET_EVAL] + args
                   + ['--pins', PINS, '--label', label, '--json', out_path],
                   check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    return json.load(open(out_path))


def signed(ev, n):
    """Signed error vector, None where the source placed no onset for a glyph."""
    e = ev['signed_errors']
    return [e.get(str(i)) for i in range(n)]


def stats(vals):
    """Rates over a fixed denominator of len(vals); None counts as a miss."""
    n = len(vals)
    if not n:
        return {'n': 0}
    hit = [v for v in vals if v is not None]
    def frac(th): return sum(1 for v in hit if round(abs(v), 3) <= th) / n
    return {
        'n': n,
        'gate_150ms': frac(GATE), 'tier_100ms': frac(TIER), 'diag_50ms': frac(DIAG),
        'median_abs_s': st.median(abs(v) for v in hit) if hit else None,
        'n_placed': len(hit),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tmp', required=True, help='dir holding repro01_*/nn00_* outputs')
    ap.add_argument('--out')
    a = ap.parse_args()
    T = a.tmp
    out = a.out or os.path.join(T, 'decide01_gap.json')

    pins = dict(onset_eval.load_pins(PINS))
    units = json.load(open(UNITS))
    n = len(units)
    if sorted(pins) != list(range(n)):
        sys.exit('pins do not cover units 0-%d exactly' % (n - 1))
    labels = json.load(open(ANNOT))['slots']['label']

    cands = sorted(c['t0'] for c in json.load(open(
        os.path.join(T, 'repro01_char_onsets.json')))['chars'])
    fa = json.load(open(os.path.join(T, 'repro01_fa_eval.json')))

    annot = run_eval(['--piece', PIECE], os.path.join(T, 'decide01_annotator.json'),
                     'annotator')
    err = {
        'annotator': signed(annot, n),
        'fa_char_first': signed(fa['scores']['char_first'], n),
        'fa_oracle': signed(fa['scores']['ORACLE_nearest_char'], n),
        'nn00_lad_oracle': signed(json.load(open(
            os.path.join(T, 'nn00_eval_lad_oracle.json'))), n),
        'nn00_prefix16_ols': signed(json.load(open(
            os.path.join(T, 'nn00_eval_prefix16_ols.json'))), n),
    }

    rows = []
    for i in range(n):
        g, u = pins[i], units[i]
        best = min(cands, key=lambda c: (abs(c - g), c))
        rows.append({
            'gi': i, 'key': u['key'], 'beats': u['beats'], 'gold_s': g,
            'syllable': labels[i],
            'fresh_syllable': bool(labels[i]),
            'n_cand_within_500ms': sum(1 for c in cands if abs(c - g) <= NEAR),
            'n_cand_within_150ms': sum(1 for c in cands if round(abs(c - g), 3) <= GATE),
            'nearest_cand_s': round(best, 6),
            'nearest_cand_dt_s': round(best - g, 6),
            'cand_within_150ms': round(abs(best - g), 3) <= GATE,
            'cand_within_100ms': round(abs(best - g), 3) <= TIER,
            'cand_within_50ms': round(abs(best - g), 3) <= DIAG,
            'dt': {k: (None if v[i] is None else round(v[i], 6)) for k, v in err.items()},
        })

    # Contested candidates: one character onset is the nearest candidate to more
    # than one gold pin, so a selector cannot give both notes what they want.
    claims = {}
    for r in rows:
        claims.setdefault(r['nearest_cand_s'], []).append(r['gi'])
    for r in rows:
        r['nearest_cand_contested_by'] = [g for g in claims[r['nearest_cand_s']]
                                          if g != r['gi']]

    # An upper bound on any static combiner of today's systems: take, per glyph,
    # whichever of the three inference-only systems happens to be closest. It
    # reads the gold answer to choose, so it is a ceiling, not a system.
    for r in rows:
        have = [r['dt'][s] for s in COMBINE if r['dt'][s] is not None]
        r['best_current_dt_s'] = min(have, key=abs) if have else None

    # How much of the oracle's coverage is information and how much is candidate
    # density? Shift every gold pin by a constant and re-ask. A shifted pin is at
    # a musically wrong time, so whatever coverage survives is the density floor.
    null = {'shifts_s': [], 'gate_150ms': [], 'tier_100ms': [], 'diag_50ms': []}
    for k in range(-20, 21):
        d = round(k / 10.0, 1)
        if abs(d) < 0.5:
            continue
        nd = [min(abs(c - (pins[i] + d)) for c in cands) for i in range(n)]
        null['shifts_s'].append(d)
        for key, th in (('gate_150ms', GATE), ('tier_100ms', TIER), ('diag_50ms', DIAG)):
            null[key].append(sum(1 for x in nd if round(x, 3) <= th) / n)
    null = {'shifts_s': null['shifts_s'],
            'median_coverage': {k: st.median(null[k])
                                for k in ('gate_150ms', 'tier_100ms', 'diag_50ms')},
            'max_coverage': {k: max(null[k])
                             for k in ('gate_150ms', 'tier_100ms', 'diag_50ms')},
            'note': 'pins shifted off the music; surviving coverage is candidate '
                    'density, not evidence'}

    runs = slip_runs(err['annotator'])
    in_slip = set()
    for lo, hi in runs:
        in_slip.update(range(lo, hi + 1))
    for r in rows:
        r['in_annotator_slip'] = r['gi'] in in_slip

    for r in rows:
        ok = round(abs(r['dt']['annotator']), 3) <= GATE
        if ok:
            r['klass'] = 'OWNED'
        elif r['cand_within_150ms']:
            r['klass'] = ('SELECTION_CLEAN'
                          if r['n_cand_within_150ms'] == 1
                          and not r['nearest_cand_contested_by']
                          else 'SELECTION_AMBIGUOUS')
        elif r['fresh_syllable']:
            r['klass'] = 'SUPPLY_TEXT'
        else:
            r['klass'] = 'SUPPLY_VOWEL'

    order = ['OWNED', 'SELECTION_CLEAN', 'SELECTION_AMBIGUOUS',
             'SUPPLY_TEXT', 'SUPPLY_VOWEL']
    classes = {}
    for k in order:
        idx = [r['gi'] for r in rows if r['klass'] == k]
        ex = next((r for r in rows if r['klass'] == k), None)
        classes[k] = {
            'glyphs': idx, 'n': len(idx), 'share_of_76': len(idx) / n,
            'n_in_slip': sum(1 for r in rows if r['klass'] == k and r['in_annotator_slip']),
            'n_continuing_vowel': sum(1 for r in rows
                                      if r['klass'] == k and not r['fresh_syllable']),
            'oracle_cand_within_150ms': sum(1 for r in rows
                                            if r['klass'] == k and r['cand_within_150ms']),
            'mean_cands_within_500ms': (
                st.mean(r['n_cand_within_500ms'] for r in rows if r['klass'] == k)
                if idx else None),
            'systems': {s: stats([r['dt'][s] for r in rows if r['klass'] == k])
                        for s in err},
            'example': None if ex is None else
                {'gi': ex['gi'], 'key': ex['key'], 'beats': ex['beats'],
                 'syllable': ex['syllable'], 'gold_s': ex['gold_s'],
                 'annotator_dt_s': ex['dt']['annotator'],
                 'fa_char_first_dt_s': ex['dt']['fa_char_first'],
                 'nearest_cand_dt_s': ex['nearest_cand_dt_s'],
                 'n_cand_within_150ms': ex['n_cand_within_150ms'],
                 'n_cand_within_500ms': ex['n_cand_within_500ms'],
                 'nearest_cand_contested_by': ex['nearest_cand_contested_by']},
        }

    need = min(k for k in range(n + 1) if k / n >= TARGET)
    owned = classes['OWNED']['n']
    sizing = {
        'denominator': n,
        'release_gate': '>= 90 % within 150 ms, 0 slips (section 9)',
        'notes_needed_at_90pct': need,
        'owned_today': owned,
        'failing_today': n - owned,
        'may_remain_wrong_at_90pct': n - need,
        'must_newly_own': need - owned,
        'must_newly_own_by_class': {k: classes[k]['n'] for k in order[1:]},
        'best_current_combiner_ceiling': stats([r['best_current_dt_s'] for r in rows]),
        'contested_nearest_candidates':
            sum(1 for r in rows if r['nearest_cand_contested_by']),
        'mean_cands_within_500ms': st.mean(r['n_cand_within_500ms'] for r in rows),
        'mean_cands_within_150ms': st.mean(r['n_cand_within_150ms'] for r in rows),
        'continuing_vowel': {
            'n': sum(1 for r in rows if not r['fresh_syllable']),
            'glyphs': [r['gi'] for r in rows if not r['fresh_syllable']],
            'with_candidate_within_150ms':
                sum(1 for r in rows if not r['fresh_syllable'] and r['cand_within_150ms']),
            'whose_nearest_candidate_is_contested':
                sum(1 for r in rows if not r['fresh_syllable']
                    and r['nearest_cand_contested_by']),
            'systems': {s2: stats([r['dt'][s2] for r in rows if not r['fresh_syllable']])
                        for s2 in err},
        },
        'oracle_ceiling_candidate_within_150ms': sum(1 for r in rows if r['cand_within_150ms']),
        'oracle_ceiling_candidate_within_100ms': sum(1 for r in rows if r['cand_within_100ms']),
        'oracle_ceiling_candidate_within_50ms': sum(1 for r in rows if r['cand_within_50ms']),
        'no_candidate_at_150ms_must_be_generated':
            [r['gi'] for r in rows if not r['cand_within_150ms']],
        'annotator_slip_runs': [{'from_gi': lo, 'to_gi': hi, 'n': hi - lo + 1}
                                for lo, hi in runs],
        'n_in_slip': len(in_slip),
        'candidate_density_null': null,
    }

    result = {
        'lane': 'DECIDE-01',
        'piece': PIECE,
        'fold': 'gold train -- BURNT BENCHMARK, fit diagnostic only, never generalisation',
        'sources': {
            'pins': os.path.relpath(PINS, REPO),
            'units': os.path.relpath(UNITS, REPO),
            'labels': os.path.relpath(ANNOT, REPO),
            'candidates': 'repro01_char_onsets.json (REPRO-01, %d character onsets)'
                          % len(cands),
            'signed_errors': 'repro01_fa_eval.json, nn00_eval_*.json, onset_eval.py --piece',
        },
        'neighbourhood_half_width_s': NEAR,
        'whole_piece': {s: stats(err[s]) for s in err},
        'classes': classes,
        'sizing': sizing,
        'rows': rows,
    }
    json.dump(result, open(out, 'w'), indent=1, ensure_ascii=False)

    w = result['whole_piece']
    print('%s  n=%d   t03 is a BURNT BENCHMARK; these are fit diagnostics' % (PIECE, n))
    print('  %-18s %7s %7s %7s %9s %7s' % ('system', '<=150', '<=100', '<=50', 'med|dt|', 'placed'))
    for s in err:
        v = w[s]
        print('  %-18s %6.1f%% %6.1f%% %6.1f%% %8.3f %7d'
              % (s, 100 * v['gate_150ms'], 100 * v['tier_100ms'], 100 * v['diag_50ms'],
                 v['median_abs_s'], v['n_placed']))
    print()
    print('  %-20s %4s %7s %9s %9s %8s %6s %6s' % ('class', 'n', 'share',
          'ann med|dt|', 'fa<=150', 'orc<=150', 'slip', 'vowel'))
    for k in order:
        c = classes[k]
        v = c['systems']
        print('  %-20s %4d %6.1f%% %9.3f %8.1f%% %7.1f%% %6d %6d'
              % (k, c['n'], 100 * c['share_of_76'], v['annotator']['median_abs_s'],
                 100 * v['fa_char_first']['gate_150ms'],
                 100 * v['fa_oracle']['gate_150ms'],
                 c['n_in_slip'], c['n_continuing_vowel']))
    print()
    print('  90 %% gate needs %d of %d; owned today %d; failing %d; must newly own %d'
          % (need, n, owned, n - owned, need - owned))
    print('  failing by class: %s'
          % ', '.join('%d %s' % (classes[k]['n'], k.lower()) for k in order[1:]))
    print('  best-of-three combiner ceiling (reads the gold to choose): %.1f %% <=150 ms'
          % (100 * sizing['best_current_combiner_ceiling']['gate_150ms']))
    print('  candidate-density null (pins shifted off the music): %.1f %% <=150 ms median'
          % (100 * null['median_coverage']['gate_150ms']))
    print('  oracle ceiling: %d of %d have a character candidate within 150 ms'
          % (sizing['oracle_ceiling_candidate_within_150ms'], n))
    print('  no candidate at any tolerance -> must be generated: %s'
          % sizing['no_candidate_at_150ms_must_be_generated'])
    print('->', out)


if __name__ == '__main__':
    sys.exit(main())
