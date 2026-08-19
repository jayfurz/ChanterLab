#!/usr/bin/env python3
"""snap_analytical.py — derive analytical melisma note boundaries from pitch.

Monotone DP over the ghost-smoothed moria track: every 10ms frame is assigned
to the interpretation's note sequence IN ORDER; cost = |pitch − target degree|
(clamped 25), NaN frames neutral (6), plus a WEAK beat-duration prior
(w_beat=0.15).  Chanter-validated 2026-08-17 on the eothinon-11 melismas:
mean error vs hand-pinned boundaries 50–66 ms (proportional beats: up to
600 ms).  The residual miss lives where pitch is ambiguous (attraction band)
— the chanter's ear remains the tiebreaker there; future features: spectral
flux for consonant onsets, RMS for breaths, tempo moving-average prior.

Usage: snap(span, degrees, beats, mor) -> internal boundary times.
"""
import numpy as np

TARGET = {'Νη': -8, 'Πα': 0, 'Βου': 22, 'Γα': 30, 'Δι': 42, 'Κε': 54,
          'Ζω': 64, "Νη'": 72, "Πα'": 84}
MIN_FR = 8


def snap(span, degrees, beats, mor, w_beat=0.15):
    i0, i1 = int(span[0]*100), int(span[1]*100)
    seg = mor[i0:i1]
    F, N = len(seg), len(degrees)
    tgt = [TARGET[d] for d in degrees]
    exp_len = [b/sum(beats)*F for b in beats]
    C = np.zeros((N, F))
    for n in range(N):
        for f in range(F):
            v = seg[f]
            C[n, f] = min(abs(v - tgt[n]), 25.0) if np.isfinite(v) else 6.0
    cum = np.zeros((N, F+1))
    cum[:, 1:] = np.cumsum(C, axis=1)
    D = np.full((N, F+1), 1e18)
    B = np.zeros((N, F+1), dtype=int)
    for f in range(MIN_FR, F+1):
        D[0, f] = cum[0, f] + w_beat*abs(f - exp_len[0])
    for n in range(1, N):
        for f in range((n+1)*MIN_FR, F+1):
            gs = np.arange(n*MIN_FR, f - MIN_FR + 1)
            cost = D[n-1, gs] + (cum[n, f] - cum[n, gs]) + w_beat*np.abs((f-gs) - exp_len[n])
            k = int(np.argmin(cost))
            D[n, f], B[n, f] = cost[k], gs[k]
    bounds = []
    f = F
    for n in range(N-1, 0, -1):
        f = B[n, f]
        bounds.append(f)
    bounds.reverse()
    return [round(span[0] + b/100, 3) for b in bounds]
