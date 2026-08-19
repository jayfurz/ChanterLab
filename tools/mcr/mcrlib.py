"""Shared MCR pipeline pieces: the note_align6-identical stream cleaning and
pitch helpers. slot_claims.json indexes the CLEANED stream — every consumer
must clean identically or labels silently shift."""
import numpy as np

HOP = 0.01
BREATH_GAP = 0.14

def med_pitch(mor, t0, t1):
    s = mor[int((t0 + 0.03) * 100):max(int((t0 + 0.03) * 100) + 2, int((t1 - 0.02) * 100))]
    s = s[~np.isnan(s)]
    return float(np.median(s)) if len(s) else None

def segment_from_tracks(cents, db, hop_s=0.01):
    """voice_segment_ref boundary rules over precomputed cents/level tracks:
    sustained pitch change (>=80c for 70ms), unvoiced gaps (>=140ms), energy
    re-articulation dips (>=7dB); octave-glitch guard; merge pass.
    Returns [[t0, t1, median_cents, gap_before_s], ...]"""
    import numpy as np
    nfr = len(cents)
    notes = []
    cur = None
    dev = 0
    last_end = -999
    def close(endfr):
        nonlocal cur
        if cur and (endfr - cur['s']) >= 10:
            notes.append([cur['s'] * hop_s, endfr * hop_s,
                          float(np.median(cur['v'])), cur['gap']])
            return endfr
    for i in range(nfr):
        c = cents[i]
        if np.isnan(c):
            if cur:
                cur['sil'] += 1
                if cur['sil'] >= 14:
                    e = close(i - cur['sil'])
                    if e: last_end = e
                    cur = None
            continue
        if cur is None:
            gap = (i - last_end) * hop_s if last_end > 0 else 9.9
            cur = {'s': i, 'v': [c], 'sil': 0, 'gap': round(min(gap, 9.9), 2), 'dip': False}
            dev = 0
            continue
        cur['sil'] = 0
        med = np.median(cur['v'][-40:])
        d = c - med
        if abs(abs(d) - 1200) < 150 and dev < 3:
            continue
        if abs(d) > 80:
            dev += 1
            if dev >= 7:
                e = close(i - dev + 1)
                if e is not None: last_end = e
                cur = {'s': i - dev + 1, 'v': [c], 'sil': 0, 'gap': 0.0, 'dip': False}
                dev = 0
            continue
        dev = 0
        if len(cur['v']) > 12:
            pk = np.max(db[max(0, i - 30):i + 1])
            if db[i] < pk - 7.0:
                cur['dip'] = True
            elif cur['dip'] and db[i] > pk - 2.5:
                e = close(i)
                if e is not None: last_end = e
                cur = {'s': i, 'v': [c], 'sil': 0, 'gap': 0.0, 'dip': False}
                continue
        cur['v'].append(c)
    close(nfr)
    if not notes:
        return []
    merged = [notes[0]]
    for n in notes[1:]:
        p = merged[-1]
        if n[0] - p[1] < 0.06 and abs(n[2] - p[2]) < 60 and n[3] < 0.14:
            p[1] = n[1]
        else:
            merged.append(n)
    return [[round(a, 3), round(b, 3), round(c, 1), g] for a, b, c, g in merged]

def clean_stream(vn_raw, mor, rms, ison_ev):
    """short-note + ison-bleed merge, byte-for-byte the note_align6.py rules"""
    def _ison_at(t):
        if ison_ev is None:
            return 'M'
        lv = ison_ev[0][1]
        for et, el in ison_ev:
            if et <= t + 0.5: lv = el
            else: break
        return lv
    def _level(v):
        s = rms[int(v[0] * 100):max(int(v[0] * 100) + 2, int(v[1] * 100))]
        return float(np.mean(s)) if len(s) else 0.0
    vn = []
    for v in vn_raw:
        dur = v[1] - v[0]
        p = med_pitch(mor, v[0], v[1])
        prevp = med_pitch(mor, vn[-1][0], vn[-1][1]) if vn else None
        lv = _ison_at(v[0])
        quiet = vn and _level(v) < 0.45 * max(_level(vn[-1]), 1e-6)
        bleed = (quiet and lv != 'M' and p is not None and abs(p - lv) < 4.5
                 and prevp is not None and abs(p - prevp) > 15 and dur < 0.5)
        if vn and (dur < 0.16 or bleed):
            vn[-1][1] = v[1]
        else:
            vn.append(list(v))
    return vn
