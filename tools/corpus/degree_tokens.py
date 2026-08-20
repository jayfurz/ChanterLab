#!/usr/bin/env python3
"""degree_tokens.py — find the degree names a parallagi calls out.

An earlier detector asked what FRACTION of decoded letters belong to the degree
names, thresholded at 0.80, and failed its control: known-parallagi scored
0.53-0.80 against known-melos 0.49-0.65. The conclusion drawn from that -- that
the model cannot hear sung solfege -- was wrong. It can. Reading the decodes:

    parallagi   ΠΑΨ ΠΑΒΟΎ-ΚΑΡΒΉ ΒΗ ΚΕΖΏ-Ο- ... ΒΟΥΚΑΔ Κ-Ε-ΘΗ ΔΗ Κ-ΕΑ-ΔΙ
    melos       ΑΤΈΛΙΣΑΣΤΌΣΤΑΦΑΏΣΟΥΣ ΤΟΝ ΘΆΡΝΑΚΤΟΝ   (Κατέλυσας τῷ Σταυρῷ...)

The degree names are plainly there; they are simply surrounded by junk letters,
which is why a letter-fraction measure could not see them. The right unit is the
TOKEN, not the letter: count occurrences of πα/βου/γα/δι/κε/ζω/νη and measure
their rate per second.

That rate is also the raw material for step 4 of the chanter's process -- match
the degrees the parallagi calls out against the degrees the score notates --
which does not depend on hymn text and so does not inherit the failure of text
identification.

Usage:  degree_tokens.py --workdir grave-orthros [--limit-sec 25]
"""
import argparse
import json
import re
import subprocess
import unicodedata

import numpy as np
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
SR = 16000
TEXTS = '/mnt/data/chant-corpus/texts'

# Degree names as the ASR tends to render them, longest first so that "βου"
# wins over a bare "ου". Ni is written both νη and νε; Vou surfaces as βου and
# often as βη.
DEG_PATTERNS = [
    (0, r'ν[ηει]'), (1, r'πα'), (2, r'β(?:ου|η|ι)'), (3, r'γα'),
    (4, r'δ[ιη]'), (5, r'κ[εαι]'), (6, r'ζ[ωο]'),
]
NAMES = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo']
RX = re.compile('|'.join(f'(?P<d{d}>{p})' for d, p in DEG_PATTERNS))


def strip(t):
    t = unicodedata.normalize('NFD', t.lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def degrees_in(text):
    """Degree tokens in decoded text, in order."""
    out = []
    for m in RX.finditer(strip(text)):
        for d, _ in DEG_PATTERNS:
            if m.group(f'd{d}'):
                out.append(d)
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='grave-orthros')
    ap.add_argument('--limit-sec', type=float, default=25.0,
                    help='seconds of each span to decode (0 = whole span)')
    ap.add_argument('--tape')
    a = ap.parse_args()

    cuts = sorted(json.load(open(f'{TEXTS}/cuts_{a.workdir}.json'))['cuts'],
                  key=lambda c: c['t0'])
    tape = a.tape or json.load(
        open(f'{TEXTS}/recut_{a.workdir}.json'))[0]['tape']

    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()

    def decode(t0, t1):
        p = subprocess.run(
            ['ffmpeg', '-v', 'quiet', '-ss', str(t0), '-to', str(t1),
             '-i', tape, '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        x = np.frombuffer(p.stdout, dtype=np.float32)
        if x.size < SR:
            return ''
        with torch.inference_mode():
            lg = model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits
        return proc.batch_decode(torch.argmax(lg, dim=-1))[0]

    rows = []
    for c in cuts:
        t1 = min(c['t0'] + a.limit_sec, c['t1']) if a.limit_sec else c['t1']
        d = decode(c['t0'], t1)
        degs = degrees_in(d)
        dur = max(t1 - c['t0'], 0.1)
        rows.append({'hymn': c['hymn'], 'lane': c.get('lane'),
                     'rate': len(degs) / dur, 'n': len(degs),
                     'degrees': degs, 'decode': d})
        print('  %-10s %-9s %5.2f deg/s  %s'
              % (c['hymn'][:10], c.get('lane') or '-', len(degs) / dur,
                 ' '.join(NAMES[x] for x in degs[:14])), flush=True)

    json.dump(rows, open(f'{TEXTS}/degree_tokens_{a.workdir}.json', 'w'),
              indent=1, ensure_ascii=False)
    for lane in ('parallagi', 'melos'):
        v = sorted(r['rate'] for r in rows if r['lane'] == lane)
        if v:
            print('\n%-9s n=%d  median %.2f deg/s  range %.2f-%.2f'
                  % (lane, len(v), v[len(v) // 2], v[0], v[-1]))
    par = [r['rate'] for r in rows if r['lane'] == 'parallagi']
    mel = [r['rate'] for r in rows if r['lane'] == 'melos']
    if par and mel:
        # the threshold that best separates the two known lanes
        best = max(((sum(p > t for p in par) + sum(m <= t for m in mel)) /
                    (len(par) + len(mel)), t)
                   for t in [i / 100 for i in range(0, 300)])
        print('\nbest split at %.2f deg/s separates the lanes %.0f%% correctly'
              % (best[1], 100 * best[0]))


if __name__ == '__main__':
    main()
