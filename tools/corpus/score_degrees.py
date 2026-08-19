#!/usr/bin/env python3
"""score_degrees.py — the degree stream a score range implies, and matching it.

Chanter: "since its a monotonically progressing set of audio and scores in
liturgical order cant you just decode each score to get the parallagi streams
then check if the candidate hymn contains those since it works better if we ask
it to align against text we give it".

That is the right shape, and it avoids the component that failed. Text
identification cannot work when half the audio is sung degrees; but a parallagi
recording IS the score read aloud as degree names, so score and audio can be
compared in the same alphabet without any hymn text.

Forced alignment against a string WE supply is also far more reliable than free
decoding -- free decode gives ΠΑΨ ΠΑΒΟΎ-ΚΑΡΒΉ, usable as a rate but not as a
sequence (see PARALLAGI-PAIRING.md).

Degrees come from the score: the unit-key legend gives each unit's interval,
and a martyria gives the absolute anchor. Caveat recorded honestly -- the
legend was itself learned from parallagi alignments, so it is not fully
independent of the thing being tested. The intervals it learned do agree with
the canonical values (oligon +1, ison 0, apostrofos -1), so the contour is
canon; a legend built from canon alone would make this airtight.

Usage:
  score_degrees.py --workdir grave-orthros --show t01_#4
  score_degrees.py --workdir grave-orthros --evaluate
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hymn_align import load_units, MARTYRIA_DEG

TEXTS = '/mnt/data/chant-corpus/texts'
DEG = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']


def leading_anchor(p0, g0):
    """The degree stated by the martyria that OPENS a range.

    load_units attaches a martyria to the unit BEFORE it, because at a cadence
    the martyria names the note just sung. At the start of a hymn that puts the
    opening martyria one unit outside the range -- so a range beginning on a
    drop cap never saw the martyria that names its first note, and every stream
    started from whatever anchor it met later.

    Chanter: "grave mode starts with the ga martyria so it should start on ga as
    the beginning pitch". On gold t03's parallagi the range starts at unit 67
    and unit 66 carries mart_deg=3, which is Ga.
    """
    def look(page, before=None):
        """martyria in the 3 units ending at `before` (default: end of page)."""
        try:
            us, _ = load_units(page, 0, page, 10 ** 6)
        except Exception:
            return None
        hi = len(us) if before is None else min(before, len(us))
        # The window follows the LINE, not a fixed unit count. An opening
        # martyria is printed either at the end of the previous line (flung to
        # the right margin) or at the left of the range's own line, before its
        # first note — so the units that can carry it are "everything earlier on
        # this line, plus the tail of the line before". A flat 3-unit lookback
        # missed t01_#22/#23, whose g0 sits 3 units into its line while the Γα
        # sits on the last unit of the line before: 4 back, one too far.
        window = []
        if hi and hi <= len(us):
            line = us[hi - 1]['pl'][1] if before is None else (
                us[hi]['pl'][1] if hi < len(us) else us[hi - 1]['pl'][1])
            i = hi - 1
            while i >= 0 and us[i]['pl'][1] == line:      # earlier on this line
                window.append(i); i -= 1
            prev = us[i]['pl'][1] if i >= 0 else None     # tail of the line before
            while i >= 0 and us[i]['pl'][1] == prev and len(window) < hi:
                window.append(i); i -= 1
                if prev is not None and len(
                        [j for j in window if us[j]['pl'][1] == prev]) >= 3:
                    break
        # The OPENING martyria is the one wanted here — the right-aligned sign
        # that announces the next hymn's starting pitch. Chanter: "sometimes the
        # right aligned martyria are just a sign for the opening of the next
        # hymn and dont act as a checksum". Preferring it over a cadence
        # martyria in the same window makes that explicit rather than relying on
        # load_units' last-one-wins overwrite to happen to leave the right value
        # in mart_deg.
        for key in ('mart_open', 'mart_deg'):
            for i in window:
                if us[i].get(key) is not None:
                    return us[i][key]
        return None

    if g0 > 0:
        d = look(p0, g0)
        if d is not None:
            return d
    # A range that opens at the very TOP of a page has its martyria printed at
    # the end of the PREVIOUS page — it is right-aligned to the close of the
    # previous hymn, which is the whole reason this function exists, and that
    # position can fall across the page break. Looking only within p0 lost the
    # anchor for every hymn that starts a page: 4 of the 47 chanter-cut spans
    # (πασαπνο-ηαι-νε at g0=1, χριστουου-την-α at g0=0, and their parallagi).
    # The window is the same three units, measured back from the previous page's
    # end rather than from g0.
    if g0 <= 3 and p0 > 0:
        return look(p0 - 1)
    return None


def units_for(p0, l0, g0, p1, l1, g1):
    """Units inside a picked score range, in reading order."""
    out = []
    for p in range(p0, p1 + 1):
        try:
            us, _ = load_units(p, 0, p, 10 ** 6)
        except Exception:
            continue
        for i, u in enumerate(us):
            if p == p0 and i < g0:
                continue
            if p == p1 and i > g1:
                continue
            out.append(u)
    return out


def degree_stream(units, legend, start=None):
    """Absolute degrees implied by the neumes.

    The first martyria in range fixes the anchor; before one appears the
    contour is still correct, only its offset is unknown.
    """
    keys = legend['keys']
    deg = start
    # A martyria printed before a hymn is right-aligned to the END of the
    # previous hymn's last line, but it announces the NEW hymn's opening pitch
    # rather than closing the old one. Chanter: "grave mode starts with the ga
    # martyria so it should start on ga as the beginning pitch"; "the opening
    # one is right aligned to the end of the last hymn". So the first unit
    # TAKES that degree instead of moving from it.
    opening = start is not None
    out = []
    for u in units:
        if u.get('rest'):
            continue
        # A martyria states the degree OF THE NOTE IT ACCOMPANIES, so that note
        # takes the anchor value directly. An interval moves from the previous
        # note to this one, so it must be applied BEFORE emitting -- but only
        # when this note is not itself anchored. Applying it to the anchored
        # note too displaced the whole stream by one degree, which showed up as
        # a best-rotation of -1 against the sung parallagi (cosine 0.889
        # rotated against 0.742 unrotated on gold t03's pair).
        if u.get('mart_deg') is not None:
            deg = u['mart_deg']
        elif opening:
            pass                       # first note of the hymn: it IS the anchor
        elif deg is not None:
            # u['iv'] is an explicit reading the chanter gave for a figure
            # whose interval the KEY cannot express — the ypsili's left/right
            # position is horizontal, the key only records ab/be. It wins.
            iv = u.get('iv')
            if iv is None:
                iv = keys.get(u.get('key'), keys.get(f"{u.get('base')}|"))
            if iv is not None:
                deg += iv
        opening = False
        out.append(deg)
    return [d for d in out if d is not None]


def as_text(degs):
    return ' '.join(DEG[d % 7] for d in degs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--legend', help='interval legend; default is the LEARNED one. Pass scores/legend_canon.json for the chanter atlas.')
    ap.add_argument('--show')
    ap.add_argument('--evaluate', action='store_true')
    ap.add_argument('--limit', type=int, default=0,
                    help='cap degrees per candidate (0 = no cap)')
    a = ap.parse_args()

    wd = a.workdir
    legend = json.load(open(a.legend)) if a.legend else json.load(
        open(f'/mnt/data/chant-corpus/workdirs/{wd}/legend_global.json'))
    spans = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/cuts_{wd}.json'))['cuts']}
    score = {c['hymn']: c for c in
             json.load(open(f'{TEXTS}/scorecuts_{wd}.json'))['cuts']}

    def stream(h):
        sc = score[h]
        us = units_for(sc['p0'], sc['l0'], sc['g0'],
                       sc['p1'], sc['l1'], sc['g1'])
        d = degree_stream(us, legend, start=leading_anchor(sc['p0'], sc['g0']))
        return (d[:a.limit] if a.limit else d), len(us)

    if a.show:
        d, n = stream(a.show)
        print(f'{a.show}: {n} units -> {len(d)} anchored degrees')
        print(as_text(d)[:400])
        return

    if not a.evaluate:
        for h in list(score)[:5]:
            d, n = stream(h)
            print('  %-10s %3d units -> %3d degrees  %s'
                  % (h, n, len(d), as_text(d)[:60]))
        return

    # ---- does the score's own degree stream identify its audio? ----------
    import numpy as np
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    from forced_align_batch import words_of, ids_of
    MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
    SR = 16000
    tape = json.load(open(f'{TEXTS}/recut_{wd}.json'))[0]['tape']
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    vocab = proc.tokenizer.get_vocab()
    blank, sep = vocab.get('<pad>', 0), vocab.get('|')

    par = sorted((h for h, c in spans.items() if c.get('lane') == 'parallagi'),
                 key=lambda h: spans[h]['t0'])
    logp_cache = {}

    def logp_of(h):
        if h not in logp_cache:
            c = spans[h]
            p = subprocess.run(
                ['ffmpeg', '-v', 'quiet', '-ss', str(c['t0']), '-to',
                 str(c['t1']), '-i', tape, '-f', 'f32le', '-ac', '1',
                 '-ar', str(SR), '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            x = np.frombuffer(p.stdout, dtype=np.float32)
            with torch.inference_mode():
                logp_cache[h] = torch.log_softmax(
                    model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits,
                    dim=-1)
        return logp_cache[h]

    def cost(audio_h, text):
        w = words_of(text, vocab)
        if not w:
            return None
        ids = ids_of(w, vocab, sep)
        lp = logp_of(audio_h)
        T = lp.shape[1]
        rep = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
        if len(ids) + rep >= T:
            return None
        with torch.inference_mode(), torch.backends.cudnn.flags(enabled=False):
            L = torch.nn.functional.ctc_loss(
                lp.transpose(0, 1),
                torch.tensor(ids, dtype=torch.int32, device=dev).unsqueeze(0),
                torch.tensor([T], dtype=torch.int32, device=dev),
                torch.tensor([len(ids)], dtype=torch.int32, device=dev),
                blank=blank, reduction='none', zero_infinity=True)
        v = L.item()
        return None if v <= 0 or v != v else v / len(ids)

    texts = {}
    for h in par:
        d, n = stream(h)
        texts[h] = as_text(d)
    hit = 0
    checked = 0
    print(f'{len(par)} parallagi spans; scoring each against every '
          f'score-derived degree stream\n')
    for h in par:
        scores = []
        for g in par:
            if not texts[g]:
                continue
            c = cost(h, texts[g])
            if c is not None:
                scores.append((c, g))
        if not scores:
            continue
        scores.sort()
        checked += 1
        best = scores[0][1]
        rank = [g for _, g in scores].index(h) + 1 if h in [g for _, g in scores] else -1
        hit += best == h
        print('  %-10s best=%-10s %s  own rank %s of %d'
              % (h, best, 'OK ' if best == h else '   ', rank, len(scores)),
              flush=True)
    print(f'\nscore-derived degrees pick their own audio: {hit}/{checked}')


if __name__ == '__main__':
    main()
