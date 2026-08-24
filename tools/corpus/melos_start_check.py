#!/usr/bin/env python3
"""melos_start_check.py — guard against hymn heads clipped by the piece slicers.

The piece slicers cut the continuous tapes on silence/speech boundaries, and
they have repeatedly cut INTO a hymn's opening: mode1 kyrie-ekekraxa began mid
"eisakouson", katefthynthito at "to i prosefchi mou", and the mode1 Kyklosate
sticheron began mid-word at "la-oi" — a few seconds of every head lost, and
nothing in the pipeline noticed, because every downstream stage happily aligns
whatever audio it is handed.

This is the guard. Each hymn row already SAYS how it must begin: the printed
lyrics at its own (p0, l0) in the glyph store. So for every row with melos
audio, forced-align the row's first ~10 printed lyric words against the HEAD of
that audio (first --window seconds) and demand that the first word lands near
the start. A healthy piece opens with at most a breath and maybe a spoken
stichos, so a first-word onset deep into the head — or an alignment that
places under half the words — means the head is not the hymn's opening: either
the slicer clipped it or the row's audio/page attribution is wrong. Either way
a human must look, which is all a guard has to achieve.

Two honest limits, so this is not over-trusted:
  * forced alignment ALWAYS aligns (CTC-loss-is-not-correctness): a clipped
    head squeezes the missing words into the first frames rather than failing,
    so a FLAG here is evidence, but an OK is only "the opening plausibly
    lands"; pair it with the chanter's ear for final say.
  * rows whose (p0, l0) lyrics are font-garbled (the early pages whose text
    layer never decoded to Greek) cannot be checked at all — they are flagged
    as `garbled` and listed for a canonical-text (GLT) fallback.

Usage:
  melos_start_check.py --workdir mode1-orthros [--window 60] [--json OUT]
  melos_start_check.py --all --json /mnt/data/chant-corpus/texts/melos_start_check.json
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forced_align import align

WORKDIRS = '/mnt/data/chant-corpus/workdirs'
GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
N_WORDS = 10        # ~10 printed lyric words is enough to pin an opening
ONSET_MAX_S = 8.0   # first word must land within this many seconds of the head
MIN_ALIGNED = 0.5   # ... and at least half the words must align at all


def greek_frac(s):
    """fraction of letters that are Greek — the garbled-font detector"""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    n = sum(1 for c in letters
            if 0x370 <= ord(c) <= 0x3FF or 0x1F00 <= ord(c) <= 0x1FFF)
    return n / len(letters)


def opening_text(p0, l0):
    """First ~N_WORDS whitespace-separated lyric tokens of the row's own
    opening, read from the glyph store at (p0, l0..). Tokens are printed
    syllable groups, not dictionary words — forced_align treats each as a
    word, which is fine for an onset check. Returns None if the page is
    missing."""
    f = os.path.join(GLYPHS, 'page%03d.json' % p0)
    if not os.path.exists(f):
        return None
    ly = [w for w in json.load(open(f)).get('lyrics', []) if w['line'] >= l0]
    ly.sort(key=lambda w: (w['line'], w['x0']))
    toks = []
    for w in ly:
        toks += w['text'].split()
        if len(toks) >= N_WORDS:
            break
    return ' '.join(toks[:N_WORDS])


def check_row(r, window, tmpdir):
    """One row -> report dict. status: ok | flag | garbled | no-audio | no-text."""
    out = {'name': r.get('name'), 'p0': r.get('p0'), 'l0': r.get('l0'),
           'melos_audio': r.get('melos_audio')}
    audio = r.get('melos_audio')
    if not audio or not os.path.exists(audio):
        out.update(status='no-audio', why='melos_audio missing on disk')
        return out
    if r.get('p0') is None or r.get('l0') is None:
        out.update(status='no-text', why='row has no (p0,l0)')
        return out
    text = opening_text(r['p0'], r['l0'])
    if not text:
        out.update(status='no-text', why='no lyrics at (p0,l0)')
        return out
    out['text'] = text
    gf = greek_frac(text)
    out['greek_frac'] = round(gf, 2)
    if gf < 0.5:
        out.update(status='garbled',
                   why='lyric layer is not Greek at this page — needs a '
                       'canonical-text fallback')
        return out
    # forced-align the opening against the first `window` seconds of the audio
    head = os.path.join(tmpdir, 'head.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-t', str(window),
                    '-i', audio, '-ac', '1', '-ar', '16000', head],
                   check=True, timeout=600)
    try:
        words = align(head, text)
    except Exception as e:                       # e.g. no alignable characters
        out.update(status='flag', why='forced_align failed: %s' % e)
        return out
    n_given = len(text.split())
    out['n_given'], out['n_aligned'] = n_given, len(words)
    if not words:
        out.update(status='flag', why='no words aligned in the head')
        return out
    out['first_onset_s'] = words[0]['t0']
    out['mean_score'] = round(sum(w['score'] for w in words) / len(words), 2)
    if words[0]['t0'] > ONSET_MAX_S:
        out.update(status='flag',
                   why='first word lands at %.1fs — head is not the opening'
                       % words[0]['t0'])
    elif len(words) < MIN_ALIGNED * n_given:
        out.update(status='flag',
                   why='only %d/%d opening words aligned'
                       % (len(words), n_given))
    else:
        out['status'] = 'ok'
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', action='append', default=[],
                    help='workdir basename under %s (repeatable)' % WORKDIRS)
    ap.add_argument('--all', action='store_true',
                    help='every workdir that has a hymns.json')
    ap.add_argument('--window', type=float, default=60.0,
                    help='seconds of audio head to scan (default 60)')
    ap.add_argument('--json', help='write the full report here')
    a = ap.parse_args()

    wds = a.workdir
    if a.all:
        wds = sorted(d for d in os.listdir(WORKDIRS)
                     if os.path.exists(os.path.join(WORKDIRS, d, 'hymns.json')))
    if not wds:
        ap.error('give --workdir NAME (or --all)')

    report = []
    n_flag = 0
    with tempfile.TemporaryDirectory(prefix='melos_start_check.') as tmpdir:
        for wd in wds:
            hj = os.path.join(WORKDIRS, wd, 'hymns.json')
            if not os.path.exists(hj):
                print('%-16s -- no hymns.json, skipped' % wd)
                continue
            rows = json.load(open(hj))
            rows = rows if isinstance(rows, list) else rows.get('hymns', [])
            for r in rows:
                res = check_row(r, a.window, tmpdir)
                res['workdir'] = wd
                report.append(res)
                tag = res['status']
                if tag == 'ok':
                    line = 'OK   t=%.2fs (%d/%d words)' % (
                        res['first_onset_s'], res['n_aligned'], res['n_given'])
                else:
                    if tag == 'flag':
                        n_flag += 1
                    line = '%s %s' % (tag.upper(), res.get('why', ''))
                print('%-16s %-20s %s' % (wd, res.get('name'), line))
                sys.stdout.flush()
    n_ok = sum(1 for r in report if r['status'] == 'ok')
    n_garb = sum(1 for r in report if r['status'] == 'garbled')
    print('\n%d rows: %d ok, %d flagged, %d garbled, %d unchecked'
          % (len(report), n_ok, n_flag, n_garb,
             len(report) - n_ok - n_flag - n_garb))
    if a.json:
        json.dump(report, open(a.json, 'w'), ensure_ascii=False, indent=1)
        print('->', a.json)


if __name__ == '__main__':
    main()
