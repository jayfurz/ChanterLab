#!/usr/bin/env python3
"""lane_eval.py -- score the parallagi/melos detector against known labels.

The detector is presplit_map.py's rule: decode a span with the Greek CTC model
and count how many degree names come out per second. A parallagi sings νη πα βου
γα δι κε ζω aloud; a melos sings text. Threshold 0.43 deg/s.

It is not a network anyone here trained -- the network is the off-the-shelf
wav2vec2 Greek model, and the classifier is one number on top of its output.
Its documented figure is 96%, not 99% (PARALLAGI-PAIRING.md: "misreads no melos
span as parallagi and misses 2 of 23 parallagi").

TWO SETS, AND ONLY ONE OF THEM IS A TEST:

  grave orthros   47 chanter-cut spans, 23 parallagi / 23 melos / 1 unset.
                  This is the tape the 0.43 threshold was MEASURED on, so it is
                  the tuning set. A good score here is not evidence.
  mode 2 vespers  33 files the chanter named (ΠΑΡΑΛΛΑΓΗ) or (ΜΕΛΟΣ) by hand.
                  Held out, different mode, different recording. This is the
                  test.

Plagal 1st cannot be used at all: its files are named by clock time and carry no
lane, and presplit_map ASSIGNED their lanes with this same rule. Scoring against
those labels would be scoring the rule against itself.

Usage:
  lane_eval.py --set grave --set mode2
"""
import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

THRESH = 0.43
LIMIT = 25.0
TAPE = ('/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/'
        'Mode Grave Anastasimatarion 2 Orthros.m4a')
M2 = '/mnt/data/chant-corpus/raw/vasilikos/Mode 2 Anastasimatarion 1 Vespers'

_M = {}


def rate(path, t0=None, t1=None, dev='cuda'):
    import torch
    from degree_tokens import degrees_in, MODEL, SR
    if 'm' not in _M:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        _M['p'] = Wav2Vec2Processor.from_pretrained(MODEL)
        _M['m'] = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    cmd = ['ffmpeg', '-v', 'quiet']
    if t0 is not None:
        cmd += ['-ss', str(t0)]
    dur = LIMIT if t1 is None else min(LIMIT, t1 - t0)
    cmd += ['-t', str(dur), '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-']
    x = np.frombuffer(subprocess.run(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL).stdout, dtype=np.float32)
    if x.size < SR:
        return None
    with torch.inference_mode():
        lg = _M['m'](torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits
    d = _M['p'].batch_decode(torch.argmax(lg, dim=-1))[0]
    return len(degrees_in(d)) / max(dur, 0.1)


def report(name, rows, note=''):
    """rows: (label, predicted_rate)"""
    rows = [(l, r) for l, r in rows if r is not None]
    ok = sum(1 for l, r in rows if (r > THRESH) == (l == 'parallagi'))
    cm = collections.Counter((l, 'parallagi' if r > THRESH else 'melos') for l, r in rows)
    print('\n%s  (%d spans)%s' % (name, len(rows), note))
    print('  accuracy %.1f%%  (%d of %d)' % (100 * ok / max(len(rows), 1), ok, len(rows)))
    print('  %-12s -> parallagi  melos' % 'truth')
    for t in ('parallagi', 'melos'):
        print('  %-12s      %5d  %5d'
              % (t, cm[(t, 'parallagi')], cm[(t, 'melos')]))
    for t in ('parallagi', 'melos'):
        rs = [r for l, r in rows if l == t]
        if rs:
            print('  %-9s deg/s  median %.2f   range %.2f - %.2f'
                  % (t, float(np.median(rs)), min(rs), max(rs)))
    bad = [(l, r) for l, r in rows if (r > THRESH) != (l == 'parallagi')]
    for l, r in bad:
        print('    MISSED  labelled %-9s  %.2f deg/s' % (l, r))
    return ok, len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--set', action='append', choices=['grave', 'mode2'], required=True)
    ap.add_argument('--device', default='cuda')
    a = ap.parse_args()
    if 'grave' in a.set:
        sp = json.load(open('/mnt/data/chant-corpus/texts/'
                            'span_names_grave-orthros.json'))['spans']
        rows = [(s['lane'], rate(TAPE, s['t0'], s['t1'], a.device))
                for s in sp if s['lane'] in ('parallagi', 'melos')]
        report('grave orthros', rows,
               '   TUNING SET -- the 0.43 threshold was measured here')
    if 'mode2' in a.set:
        rows = []
        for f in sorted(glob.glob(os.path.join(M2, '*'))):
            b = os.path.basename(f)
            lab = ('parallagi' if 'ΠΑΡΑΛΛΑΓΗ' in b
                   else 'melos' if 'ΜΕΛΟΣ' in b else None)
            if lab:
                rows.append((lab, rate(f, None, None, a.device)))
        report('mode 2 vespers', rows, '   HELD OUT -- chanter-named filenames')
    return 0


if __name__ == '__main__':
    sys.exit(main())
