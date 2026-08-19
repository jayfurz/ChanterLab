#!/usr/bin/env python3
"""audio_recut.py — repair clipped hymn audio by re-finding it in the source tape.

Chanter: the tracks "cut off too early and the hymns end up having a long
silence in the beginning and the last note gets cut off too early", and "some
modes are already precut, like plagal 1". audio_cut_check.py confirms both:
153 of 173 tracks end while still sounding, and the two clean workdirs are
mode2 (0/15 clipped) and pl1-vespers (2/13) — those are the reference for what a
correct cut looks like, median tail ~0.4 s.

The piece files do NOT partition the tape (grave-orthros: 3015 s of pieces from a
3896 s tape), so a clipped tail is NOT the head of the next piece — it sits in a
dropped region and can only be recovered from the tape itself. The original cut
offsets were never recorded, so this re-derives them: correlate the piece's RMS
envelope against the tape's, then walk forward from the piece end until the
sound actually stops.

Re-locating rather than re-cutting from scratch is deliberate: piece numbering
stays identical, so every hymns.json melos_audio path and every chanter pin
survives.

Usage:
  audio_recut.py --workdir DIR [--apply] [--tail 0.35] [--lead 0.25]
Without --apply it only reports what it would change.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np

HOP = 0.05                      # envelope resolution (s)
SR = 16000
CORPUS = '/mnt/data/chant-corpus'
CACHE = os.path.join(CORPUS, 'texts', 'env_cache')


def envelope(path, cache_key=None):
    """coarse RMS envelope at HOP resolution, mono 16 kHz"""
    if cache_key:
        os.makedirs(CACHE, exist_ok=True)
        cp = os.path.join(CACHE, cache_key + '.npy')
        if os.path.exists(cp):
            return np.load(cp)
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                        '-ar', str(SR), '-f', 's16le', '-'],
                       capture_output=True, timeout=900)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(SR * HOP)
    if x.size < n:
        return np.zeros(0, np.float32)
    m = x[:x.size // n * n].reshape(-1, n)
    e = np.sqrt((m ** 2).mean(axis=1)).astype(np.float32)
    if cache_key:
        np.save(cp, e)
    return e


def locate(tape, piece):
    """offset in frames of `piece` inside `tape` by normalised correlation"""
    if piece.size < 4 or tape.size <= piece.size:
        return None, 0.0
    t = tape - tape.mean()
    q = piece - piece.mean()
    n = 1 << int(np.ceil(np.log2(tape.size + piece.size)))
    c = np.fft.irfft(np.fft.rfft(t, n) * np.conj(np.fft.rfft(q, n)), n)
    c = c[:tape.size - piece.size + 1]
    if c.size == 0:
        return None, 0.0
    i = int(np.argmax(c))
    # normalise the winning lag so a score is comparable across pieces
    w = tape[i:i + piece.size]
    d = np.linalg.norm(w - w.mean()) * np.linalg.norm(q)
    return i, float(np.dot(w - w.mean(), q) / d) if d else 0.0


_CORP = None


# whisper hallucinations on this corpus: subtitle credits injected into silence
JUNK = ('AUTHORWAVE', 'Υπότιτλοι', 'ΥΠΟΤΙΤΛΟΙ', 'subtitle', 'Subtitle')


def tape_segments(tape_path):
    """(start, end) of real sung segments in the TAPE-level whisper transcript.

    Chanter: "perhaps we also weigh in the whisper transcript with timestamp
    recordings as well" — for tracks where the pause is too short for the RMS
    search to find. Whisper is used ONLY as a BOUND here, never as the cut
    itself: it mutes on melisma (that is how t03 lost 21 s of parallagi in an
    earlier session), so it under-reports singing. That makes it a sound LOWER
    bound on where sound continues, and the next segment's start a sound UPPER
    bound on how far to extend, but never a reliable cut point on its own.
    """
    base = os.path.splitext(os.path.basename(tape_path))[0]
    p = os.path.join(CORPUS, 'transcripts', base + '.json')
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p))
    except Exception:
        return []
    out = []
    for sg in d.get('segments', []):
        if 'start' not in sg or 'end' not in sg:
            continue
        t = str(sg.get('text', ''))
        if any(j in t for j in JUNK) or not t.strip():
            continue
        out.append((float(sg['start']), float(sg['end'])))
    out.sort()
    return out


def find_tape(piece_path):
    """the source recording a piece dir was cut from.

    Layout: pieces live in pieces/<Album Title>/NNN_melos.wav, and the tape is
    raw/vasilikos/<Album>/<Album Title>.m4a — so the match is on the tape's
    FILENAME STEM, not on its parent directory. Modes whose raw source is many
    short recordings instead of one tape (plagal 1: 33 files) were never cut by
    this pipeline and are already clean; they return None and are skipped.
    """
    global _CORP
    if _CORP is None:
        _CORP = json.load(open(os.path.join(CORPUS, 'corpus.json')))
    d = os.path.basename(os.path.dirname(piece_path)).strip().lower()
    best = None
    for r in _CORP:
        st = os.path.splitext(os.path.basename(r['path']))[0].strip().lower()
        if st == d:
            return r['path']
        if st.startswith(d) or d.startswith(st):
            if best is None or r['dur_s'] > best['dur_s']:
                best = r
    return best['path'] if best else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--tail', type=float, default=0.35, help='silence to keep after the last note')
    ap.add_argument('--lead', type=float, default=0.25, help='silence to keep before the first note')
    ap.add_argument('--move-start', action='store_true',
                    help='also re-cut the START. Off by default: doing so shifts every chanter pin measured against this audio.')
    ap.add_argument('--floor', type=float, default=0.18,
                    help='how far above the tape noise floor still counts as sound')
    ap.add_argument('--min-gap', type=float, default=0.30, help='silence run that ends a hymn')
    ap.add_argument('--max-extend', type=float, default=5.0,
                    help='never chase the end further than this. The tape is '
                         'near-continuous chanting, so an unbounded "walk until '
                         'silence" swallows the following hymns (+480 s in the '
                         'first run). A clipped note needs seconds, not minutes.')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    hy = json.load(open(os.path.join(a.workdir, 'hymns.json')))
    tapes = {}
    tseg = {}
    out = []
    print('%-22s %8s %8s %8s %8s %s' % ('hymn', 'corr', 'cur_end', 'new_end', 'delta', 'note'))
    for h in hy:
        mp = h.get('melos_audio')
        if not mp or not os.path.exists(mp):
            continue
        tp = find_tape(mp)
        if not tp:
            print('%-22s  no source tape' % h['name'][:22]); continue
        key = os.path.basename(tp).replace('/', '_')
        if key not in tapes:
            tapes[key] = envelope(tp, key)
        tape = tapes[key]
        pe = envelope(mp)
        off, corr = locate(tape, pe)
        if off is None or corr < 0.5:
            print('%-22s %8.2f  LOCATE FAILED' % (h['name'][:22], corr)); continue
        end = off + pe.size
        # Threshold ADAPTIVE to the tape's own noise floor. A fixed fraction of
        # the signal level does not work: these are tape transfers, the floor
        # never approaches zero, so "is it silent" was never true and the search
        # always fell through to the fixed +0.6 s fallback (only 5 of 25 tracks
        # actually improved). Sit the threshold a short way above the measured
        # floor instead, so the end of a sung note is detectable against it.
        floor_lvl = float(np.percentile(tape, 20))
        loud = float(np.percentile(pe, 90))
        thr = floor_lvl + a.floor * max(loud - floor_lvl, 1e-9)
        gap = int(a.min_gap / HOP)
        lim = min(tape.size, end + int(a.max_extend / HOP))
        j = end
        while j < lim:
            if (tape[j:j + gap] <= thr).all():
                break
            j += 1
        if j >= lim:
            # No sustained silence inside the window — common where the tape
            # runs on with little gap between hymns. A fixed offset just adds
            # more sounding audio (this is why pl4-orthros barely improved:
            # 22/25 clipped -> 18/25). Cut at the QUIETEST point instead, which
            # is where the gap actually is even when it never reaches the floor.
            w = tape[end:lim]
            if w.size >= 3:
                sm = np.convolve(w, np.ones(gap) / gap, mode='same')
                j = end + int(np.argmin(sm))
            else:
                j = end + int(a.tail / HOP)
        new_end = min(tape.size, j + int(a.tail / HOP))
        # whisper bounds, in seconds
        segs = tseg.get(key)
        if segs is None:
            segs = tseg[key] = tape_segments(tp)
        if segs:
            e_s = end * HOP
            spanning = [e for st, e in segs if st <= e_s <= e]
            if spanning:                      # cut lands mid-utterance
                lo = int(max(spanning) / HOP)
                if lo > new_end:
                    new_end = min(tape.size, lo + int(a.tail / HOP))
            nxt = [st for st, e in segs if st > e_s + 0.2]
            if nxt:
                # Cap the extension at the next utterance — but only if the tape
                # actually has sound there. Measured on the grave orthros tape:
                # whisper misses 55% of the sung audio and still emits 463 s of
                # segments over silence even after the junk filter, because it
                # was never trained on ecclesiastical Greek or on chant. An
                # uncorroborated segment would cut a hymn short, so require RMS
                # to agree before letting whisper shorten anything.
                c0 = int(min(nxt) / HOP)
                win = tape[c0:c0 + int(0.5 / HOP)]
                if win.size and float(win.mean()) > thr:
                    cap = int((min(nxt) - 0.1) / HOP)
                    if cap > end:
                        new_end = min(new_end, cap)
        if a.move_start:
            k = off
            back = int(a.max_extend / HOP)
            while k > 0 and tape[k - 1] > thr and off - k < back:
                k -= 1
            new_start = max(0, k - int(a.lead / HOP))
        else:
            # The start is the ORIGIN OF THE TIME BASE. Gold #2 carries 76
            # chanter pins measured against it, and re-cutting the start would
            # have moved t03 by 0.25 s (corpus median 0.35 s), silently
            # invalidating every one of them. The chanter's complaint was the
            # clipped END; the leads were already small. Preserve the start.
            new_start = off
        d_end = (new_end - end) * HOP
        d_start = (off - new_start) * HOP
        out.append({'workdir': name, 'hymn': h['name'], 'piece': mp, 'tape': tp,
                    'corr': round(corr, 3),
                    'cur': [round(off * HOP, 2), round(end * HOP, 2)],
                    'new': [round(new_start * HOP, 2), round(new_end * HOP, 2)],
                    'add_end_s': round(d_end, 2), 'add_start_s': round(d_start, 2)})
        print('%-22s %8.2f %8.1f %8.1f %+8.2f %s'
              % (h['name'][:22], corr, end * HOP, new_end * HOP, d_end,
                 'recovers clipped note' if d_end > 0.15 else ''))
    jf = os.path.join(CORPUS, 'texts', f'recut_{name}.json')
    json.dump(out, open(jf, 'w'), indent=1)
    if out:
        adds = [r['add_end_s'] for r in out]
        print('\n%d located | median tail recovered %.2f s | max %.2f s'
              % (len(out), sorted(adds)[len(adds) // 2], max(adds)))
    print('-> %s%s' % (jf, '' if a.apply else '   (report only; pass --apply to write audio)'))

    if a.apply:
        for r in out:
            dst = r['piece'].replace('.wav', '.recut.wav')
            s, e = r['new']
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(s), '-to', str(e), '-ac', '1', '-ar', '44100',
                            dst], check=True)
        print('wrote %d re-cut files (.recut.wav alongside the originals)' % len(out))


if __name__ == '__main__':
    main()
