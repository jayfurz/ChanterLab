#!/usr/bin/env python3
"""onset_match.py -- place note onsets from peaks, beats and pitch together.

Chanter's brief, 2026-08-21: "peak finding as the fine tuning vernier of onset,
and beat length as a fuzzy cue, and the pitch as a verifier of the note (for
instance rather than an off by one .. if it is supposed to be down two and it
goes up one in that vicinity of offset we have an issue)."

Three signals, three different jobs, and the distinction is the whole design:

  PEAKS are the vernier. A spectral-flux maximum locates an articulation to a
  few milliseconds, but says nothing about WHICH note it is -- there are more
  peaks than notes, and melisma manufactures them freely.
  BEATS are a fuzzy cue. beats_seq() gives the written duration of every unit,
  so it predicts roughly where the next onset falls. It is a prior, never a
  measurement: the chanter's departure from the grid is the music.
  PITCH is the verifier, not a placer. A parallagi sings the degree names, so
  the sung pitch at a correctly placed note must sit near the degree the score
  says. Score says down two, audio goes up one -- that is a placement error, and
  it is exactly the off-by-one the other two signals cannot see.

The alignment is a Viterbi over (note, candidate) with those three as additive
costs, so a bad peak can be overruled by the beat prior and a plausible-looking
placement can be overruled by the pitch.

MEASURED on s06 (parallagi Ως της ημων, 97 notes, 82 chanter pins), through
tools/corpus/onset_eval.py, the only scorer:

    seed                       <=150ms  <=100ms  <=50ms  median|dt|
    annotator's current seed      2.4%     1.2%    0.0%    3.587 s
    this                         95.1%    93.9%   90.2%    0.018 s

    within 20 ms  45/82        within 50 ms  74/82

INPUT IS TWO PINS: the first note and the last. Nothing else is read from the
gold. The tempo comes from the audio and the placement from the audio, but the
span cannot be found automatically on this material -- see tempo_from_audio()
for why, and note that neither reason is a bad cut.

WHAT IT STILL GETS WRONG: notes 92-95, the closing ritardando, by +0.37 to
+1.85 s. Everything else in the piece is inside 120 ms. Anchoring the last note
forces the Viterbi to span the ritardando, which fixed the direction of the
error (they were -0.44 to -2.13 s early before) but not its size.

THE PITCH VERIFIER EARNS ITS PLACE, and the way it fails is the point. It flags
8 of 96 transitions, and they split cleanly in two:

  * 92, 93, 94 -- flagged AND badly placed (+0.68 to +1.85 s). The verifier
    caught the ritardando failure on its own, from pitch alone, with no access
    to the pins. That is the job.
  * 9/10, 59/60, 91 -- flagged while placed to within 33 ms. These are not
    timing errors. gi 59/60 is the clearest: the score reads ison then elaphron,
    stay-then-drop-22, and the singer drops 22 and then stays. The movement is
    real and it happens one note EARLIER than written -- precisely the off-by-one
    the chanter described. Not resolved here; it is a notation question.

Usage:
  onset_match.py --piece <annotator piece id> --pins <pins.json> --out seed.json
  onset_match.py --piece ... --report          # per-note pitch verdicts
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

CUTS = '/mnt/data/chant-corpus/texts/scorecuts_grave-orthros.json'
LEGEND = '/mnt/data/chant-corpus/scores/legend_canon.json'
SR = 22050
HOP = 128                    # 5.8 ms -- the vernier resolution
CPM = 1200.0 / 72.0          # cents per moria


def load_audio(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def onset_envelope(y):
    """Half-wave-rectified spectral flux on a mel basis, per-piece normalised."""
    import librosa
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, aggregate=np.median)
    env = env - np.percentile(env, 10)
    env[env < 0] = 0
    m = np.percentile(env, 99)
    return env / m if m > 0 else env


def tempo_from_audio(env, lo=0.25, hi=2.5):
    """Seconds per beat from the onset envelope alone -- no pins, no span.

    Both ends of a span estimate were wrong on s06 and neither was a bad cut:
    the head carries an INTONATION (the mode established before the notated
    hymn) and the tail is the final note being HELD, its onset at 70.6 s but
    sounding to 75.8. Voiced extent therefore opened the tempo at 0.718 s/beat
    against a true 0.529 and the alignment slid to 0.0% within 150 ms.

    Autocorrelating the onset envelope sidesteps both: on s06 it returns
    0.517 s against a true median inter-onset interval of 0.529, 2% out,
    without needing to know where the hymn starts.
    """
    import librosa
    ac = librosa.autocorrelate(env, max_size=int(hi * SR / HOP))
    ac[:int(lo * SR / HOP)] = 0
    return float(np.argmax(ac)) * HOP / SR


def peaks(env, t0=0.0):
    """Local maxima with their strength; times in seconds."""
    idx = np.where((env[1:-1] >= env[:-2]) & (env[1:-1] > env[2:]))[0] + 1
    idx = idx[env[idx] > 0.06]
    return t0 + idx * HOP / SR, env[idx]


def moria_at(pitch, t0, t1):
    """Median moria over the stable middle of a note's span, or None."""
    dt = pitch['dt']
    a, b = int(round(t0 / dt)), int(round(t1 / dt))
    if b - a < 3:
        b = a + 3
    seg = [v for v in pitch['moria'][a:b] if v is not None]
    if len(seg) < 3:
        return None
    seg = sorted(seg)
    lo, hi = int(len(seg) * .2), max(int(len(seg) * .8), int(len(seg) * .2) + 1)
    return float(np.median(seg[lo:hi]))


def expected_moria(hymn, n):
    """Absolute moria the score implies for each unit, or None if unavailable.

    A parallagi sings the degree names, so this is a direct prediction of the
    sung pitch. For a melos it is still the melodic line, just sung to text.
    """
    try:
        from score_degrees import units_for, degree_stream, leading_anchor
        from hymn_align import LADDERS
    except Exception:
        return None
    cuts = json.load(open(CUTS))['cuts']
    c = next((x for x in cuts if x['hymn'] == hymn), None)
    if not c:
        return None
    u = units_for(c['p0'], c['l0'], c['g0'], c['p1'], c['l1'], c['g1'])
    leg = json.load(open(LEGEND))
    degs = degree_stream(u, leg, start=leading_anchor(c['p0'], c['g0']))
    if len(degs) != n:
        return None
    dia = LADDERS['diatonic']
    return np.array([dia(int(d)) for d in degs], dtype=float)


def pitch_emission(pitch, cand_t, exp_m, win=0.22):
    """Cost of reading each candidate as each note, from pitch alone.

    THE VERIFIER, and it is deliberately weak-but-wide. Chanter: "if it is
    supposed to be down two and it goes up one in that vicinity of offset we
    have an issue." A misplacement by one note lands the reader on a pitch the
    score does not predict, which neither the peak nor the beat prior can see --
    they are both blind to what is actually being sung.

    Measured over a fixed window after the candidate rather than the note's true
    span, because the span depends on the next placement and would make the
    Viterbi second-order. 220 ms is under the shortest inter-onset interval in
    the gold pins, so the window cannot spill into the following note at normal
    tempo.

    The score's Ni is an arbitrary origin against the tracker's, so the two are
    aligned on their medians before comparison -- only INTERVALS are claimed.
    """
    if pitch is None or exp_m is None:
        return None
    dt = pitch['dt']; mo = pitch['moria']
    obs = np.full(len(cand_t), np.nan)
    for k, t in enumerate(cand_t):
        a = int(round(t / dt)); b = int(round((t + win) / dt))
        seg = [v for v in mo[a:b] if v is not None]
        if len(seg) >= 4:
            obs[k] = float(np.median(seg))
    good = ~np.isnan(obs)
    if good.sum() < 8:
        return None
    off = np.median(obs[good]) - np.median(exp_m)
    obs -= off
    # |observed - expected| in moria, saturating: a 6-moria miss is already a
    # different note, and beyond that the size of the error carries no more
    # information than its existence.
    d = np.abs(obs[:, None] - exp_m[None, :])
    d = np.minimum(d, 14.0) / 14.0
    d[np.isnan(obs)] = 0.5                    # unvoiced: no opinion, not a veto
    return d.T                                # [note, candidate]


def viterbi(n_notes, cand_t, cand_s, beats, spb, w_time, w_peak, w_pitch,
            sigma_fast, sigma_slow, pitch_cost, anchor=None):
    """Place every note on a candidate. spb may be a per-note array."""
    N, C = n_notes, len(cand_t)
    spb = np.broadcast_to(np.asarray(spb, dtype=float), (N,))
    emit = -w_peak * np.log(cand_s + 1e-3)
    emit = np.tile(emit, (N, 1))
    if pitch_cost is not None:
        emit = emit + w_pitch * pitch_cost
    INF = 1e9
    dp = np.full((N, C), INF); bp = np.zeros((N, C), dtype=np.int32)
    dp[0] = emit[0]
    # ANCHOR THE ENDS. The two pins already define the span, so pin the first
    # and last note to them rather than only using them for a tempo estimate.
    # Without this the closing ritardando cannot be recovered: placing it needs
    # the slow tempo, and measuring the slow tempo needs the placement, so the
    # feedback settles into the early reading and stays there -- the last four
    # notes sat -0.44 to -2.13 s out. Fixing the last note forces the Viterbi to
    # span the ritardando, and the tempo then follows from having to.
    if anchor is not None:
        a0, a1 = anchor
        if a0 is not None:
            dp[0] = np.where(np.arange(C) == a0, dp[0], INF)
    for i in range(1, N):
        want = beats[i - 1] * spb[i - 1]
        prev = dp[i - 1]
        best = np.full(C, INF); arg = np.zeros(C, dtype=np.int32)
        for q in range(1, C):
            # RATIO, not difference, and ASYMMETRIC. A ritardando only ever
            # slows, and it slows a lot: on s06 the last five inter-onset
            # intervals run about 3x the body tempo. An absolute cost with a
            # 130 ms sigma prices that at ((1.5-0.55)/0.13)^2 = 53, so the
            # Viterbi refuses it, places the ending early, and the tempo
            # feedback then locks the error in -- which is exactly what the
            # first version did. In log-ratio terms the same stretch is
            # log(3) = 1.1, and slowing is given the looser sigma of the two
            # because nobody suddenly sings three times faster.
            dt = cand_t[q] - cand_t[:q]
            r = np.log(np.maximum(dt, 1e-3) / max(want, 1e-3))
            sg = np.where(r > 0, sigma_slow, sigma_fast)
            c = prev[:q] + w_time * (r / sg) ** 2
            k = int(np.argmin(c))
            best[q] = c[k]; arg[q] = k
        dp[i] = best + emit[i]; bp[i] = arg
    last = dp[-1].copy()
    if anchor is not None and anchor[1] is not None:
        last = np.where(np.arange(C) == anchor[1], last, INF)
    path = [int(np.argmin(last))]
    for i in range(N - 1, 0, -1):
        path.append(int(bp[i][path[-1]]))
    return path[::-1]


def local_spb(t, beats, k=9):
    """Seconds-per-beat per note, smoothed -- the tempo the singer is keeping.

    A single global rate cannot follow a ritardando, and the ritardando is where
    every method in this project has failed: on the first pass over s06 the last
    five notes ran -0.35 to -2.79 s while the other 77 were inside 120 ms. So
    the rate is re-estimated from the previous pass and fed back.
    """
    n = len(beats)
    r = np.full(n, np.nan)
    for i in range(n - 1):
        if beats[i] > 0 and t[i + 1] > t[i]:
            r[i] = (t[i + 1] - t[i]) / beats[i]
    r[-1] = r[-2] if n > 1 else 1.0
    out = np.empty(n)
    for i in range(n):
        lo, hi = max(0, i - k // 2), min(n, i + k // 2 + 1)
        w = r[lo:hi][~np.isnan(r[lo:hi])]
        out[i] = np.median(w) if len(w) else np.nanmedian(r)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data', required=True, help='annotator_data.json')
    ap.add_argument('--pins')
    ap.add_argument('--out')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--hymn', help='scorecut hymn id, e.g. t01_#7, to enable pitch')
    ap.add_argument('--iters', type=int, default=3)
    ap.add_argument('--smooth', type=int, default=5,
                    help='notes in the tempo median. Small, because the closing '
                         'ritardando slows a lot and a wide window lags it')
    ap.add_argument('--w-time', type=float, default=1.0)
    ap.add_argument('--w-peak', type=float, default=0.35)
    ap.add_argument('--w-pitch', type=float, default=0.8)
    ap.add_argument('--sigma-fast', type=float, default=0.22,
                    help='log-ratio tolerance for RUSHING -- tight')
    ap.add_argument('--sigma-slow', type=float, default=0.45,
                    help='log-ratio tolerance for SLOWING -- loose, because the '
                         'closing ritardando slows a lot')
    a = ap.parse_args()

    D = json.load(open(a.data))
    n = len(D['slots']['gi'])
    beats = np.array(D['slots'].get('w') or [1.0] * n, dtype=float)
    audio = os.path.join(os.path.dirname(os.path.abspath(a.data)), 'audio.wav')
    y = load_audio(audio)
    env = onset_envelope(y)
    ct, cs = peaks(env)

    # THE SPAN. Two chanter pins -- the first note and the last -- and nothing
    # else. Detecting it from the audio does not work on this material and the
    # failure is informative: s06's cut is sung continuously from 1.2 s to
    # 75.8 s, while its 97 notes run 12.5 s to 70.6 s. Roughly 11 s of singing
    # before the score starts (an intonation) and 5 s after it ends. A voiced-
    # extent estimate therefore opens the tempo at 0.718 s/beat against a true
    # 0.559, and the whole alignment slides -- measured, it scored 0.0%.
    #
    # That is the chanter's own precondition showing up as a number: the score
    # sheet is not cut to the audio here. Until it is, the two anchors come from
    # him. It is a cheap ask -- pin the first note and the last, press match --
    # and it is honest about what the method needs.
    if a.pins:
        _raw = json.load(open(a.pins))
        _p = {int(g): float(v) for g, v in (_raw['pins'] if isinstance(_raw, dict) else _raw)}
        lo, hi = _p[min(_p)], _p[max(_p)]
        span_src = 'first and last chanter pin'
    else:
        rms = np.sqrt(np.convolve(y * y, np.ones(1024) / 1024, 'same'))
        voiced = np.where(rms > 0.10 * rms.max())[0]
        lo, hi = voiced[0] / SR, voiced[-1] / SR
        span_src = 'voiced extent (unreliable if the cut is not tight)'
    keep = (ct >= lo - 0.5) & (ct <= hi + 0.5)
    ct, cs = ct[keep], cs[keep]
    print('%d notes, %d candidate peaks, span %.2f-%.2f s (%s)'
          % (n, len(ct), lo, hi, span_src))

    exp_m = expected_moria(a.hymn, n) if a.hymn else None
    pc = pitch_emission(D.get('pitch'), ct, exp_m) if exp_m is not None else None
    print('pitch verifier: %s' % ('on, %d notes predicted' % len(exp_m)
                                  if pc is not None else 'off'))

    anchor = None
    if a.pins:
        anchor = (int(np.argmin(np.abs(ct - lo))), int(np.argmin(np.abs(ct - hi))))
        print('anchored: note 0 -> %.3f s, note %d -> %.3f s'
              % (ct[anchor[0]], n - 1, ct[anchor[1]]))
    spb = tempo_from_audio(env)
    print('opening tempo %.3f s/beat (onset-envelope autocorrelation, no pins)' % spb)
    path = None
    for it in range(a.iters):
        path = viterbi(n, ct, cs, beats, spb, a.w_time, a.w_peak, a.w_pitch,
                       a.sigma_fast, a.sigma_slow, pc, anchor)
        t = ct[path]
        new_spb = local_spb(t, beats, k=a.smooth)
        drift = float(np.max(new_spb) / max(np.min(new_spb), 1e-6))
        print('  pass %d: tempo %.3f-%.3f s/beat (x%.2f across the piece)'
              % (it + 1, new_spb.min(), new_spb.max(), drift))
        spb = new_spb
    onset = {i: float(ct[p]) for i, p in enumerate(path)}

    if a.pins:
        raw = json.load(open(a.pins))
        pins = {int(g): float(v) for g, v in (raw['pins'] if isinstance(raw, dict) else raw)}
        if a.report and exp_m is not None:
            verify(onset, pins, D.get('pitch'), exp_m, beats, spb)

    if a.out:
        json.dump({str(g): round(t, 4) for g, t in sorted(onset.items())},
                  open(a.out, 'w'), indent=1)
        print('->', a.out)
    return 0


def verify(onset, pins, pitch, exp_m, beats, spb):
    """Report where the SUNG pitch disagrees with the score at a placement.

    This is the check the chanter asked for and it is not a scoring metric: a
    note placed on the wrong articulation usually still lands on some peak and
    still roughly honours the beat, so neither of those notices. The pitch does.
    """
    n = len(onset)
    obs = []
    for i in range(n):
        t0 = onset[i]
        t1 = onset[i + 1] if i + 1 in onset else t0 + beats[i] * float(np.mean(spb))
        obs.append(moria_at(pitch, t0, min(t1, t0 + 0.6)))
    ok = [i for i in range(n) if obs[i] is not None]
    off = np.median([obs[i] for i in ok]) - np.median(exp_m[ok])
    bad = []
    for i in range(n - 1):
        if obs[i] is None or obs[i + 1] is None:
            continue
        want = exp_m[i + 1] - exp_m[i]
        got = obs[i + 1] - obs[i]
        if abs(got - want) >= 8.0 and (want == 0 or np.sign(got) != np.sign(want)
                                       or abs(got - want) >= 12.0):
            bad.append((i, want, got))
    print('\n  PITCH VERIFIER: %d of %d transitions disagree with the score'
          % (len(bad), n - 1))
    print('  (score movement vs sung movement, in moria; 12 moria is a tone)')
    for i, want, got in bad[:12]:
        e = onset[i] - pins[i] if i in pins else None
        print('    gi=%-3d score %+5.1f  sung %+6.1f%s'
              % (i, want, got, '   placement error %+.3f s' % e if e is not None else ''))


if __name__ == '__main__':
    sys.exit(main())
