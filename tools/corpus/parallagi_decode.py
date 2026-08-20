#!/usr/bin/env python3
"""parallagi_decode.py — decide parallagi vs melos by what the audio SAYS.

parallagi_probe.py compares two forced-alignment losses, which is weak: if the
Greek ASR model transcribes sung solfege badly, both hypotheses score poorly and
the comparison is between two bad options with an arbitrary threshold.

This asks the audio directly. A parallagi rendition has a closed vocabulary --
the chanter sings only νη πα βου γα δι κε ζω, over and over. So greedy-decode
the track and measure what fraction of the decoded letters belong to those
seven syllables. Melos text ranges over all of Greek and cannot score high on
that measure by chance; a parallagi track has almost nowhere else to go.

No forced alignment, no candidate pool, no assumption about which hymn it is.

Usage:  parallagi_decode.py [--workdir NAME]
"""
import argparse
import glob
import json
import os
import subprocess
import re
import unicodedata

import numpy as np
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
SR = 16000
DEG = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']
# Letters the seven degree names are built from. A decode of sung degrees stays
# almost entirely inside this set; running Greek text does not.
DEG_LETTERS = set('νηπαβουγδικεζω')


def read_audio(path):
    """Decode to 16 kHz mono float32 via ffmpeg.

    soundfile refuses some of the corpus m4a files ("Format not recognised"),
    which killed a full-corpus run 123 tracks in. ffmpeg reads everything the
    recordings are actually in, so the probe is not limited by the container.
    """
    p = subprocess.run(
        ['ffmpeg', '-v', 'quiet', '-i', path, '-f', 'f32le',
         '-ac', '1', '-ar', str(SR), '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if p.returncode != 0 or not p.stdout:
        return None
    return np.frombuffer(p.stdout, dtype=np.float32)


def strip(s):
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def decode(model, proc, dev, wav):
    x = read_audio(wav)
    if x is None or x.size < SR:
        return None
    with torch.inference_mode():
        lg = model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits
    return proc.batch_decode(torch.argmax(lg, dim=-1))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir')
    ap.add_argument('--thresh', type=float, default=0.80)
    a = ap.parse_args()

    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()

    out, par = [], 0
    for f in sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/hymns.json')):
        w = f.split('/')[-2]
        if a.workdir and w != a.workdir:
            continue
        for h in json.load(open(f)):
            for lane in ('melos_audio', 'parallagi_track'):
                wav = h.get(lane)
                if not wav:
                    continue
                # parallagi_track is stored as a bare filename, relative to the
                # same pieces directory the melos piece came from.
                if not os.path.isabs(wav):
                    wav = os.path.join(os.path.dirname(h.get('melos_audio', '')),
                                       wav)
                if not os.path.exists(wav):
                    continue
                d = decode(model, proc, dev, wav)
                if not d:
                    continue
                letters = re.sub(r'[^α-ωa-z]', '', strip(d))
                if len(letters) < 20:
                    continue
                frac = sum(c in DEG_LETTERS for c in letters) / len(letters)
                is_par = frac >= a.thresh
                par += is_par and lane == 'melos_audio'
                out.append({'workdir': w, 'hymn': h['name'], 'lane': lane,
                            'deg_frac': round(frac, 3), 'parallagi': is_par,
                            'decode_head': d[:60]})
                print('  %-16s %-22s %-16s %.3f %s'
                      % (w, h['name'][:22], lane, frac,
                         'PARALLAGI' if is_par else ''))
    json.dump(out, open('/mnt/data/chant-corpus/texts/parallagi_decode.json', 'w'),
              indent=1, ensure_ascii=False)
    ml = [r for r in out if r['lane'] == 'melos_audio']
    pl = [r for r in out if r['lane'] == 'parallagi_track']
    if ml:
        print('\nmelos lane:     %d/%d (%.0f%%) decode as sung degrees'
              % (par, len(ml), 100.0 * par / len(ml)))
    if pl:
        k = sum(r['parallagi'] for r in pl)
        print('parallagi lane: %d/%d (%.0f%%) decode as sung degrees  '
              '<- control, should be high' % (k, len(pl), 100.0 * k / len(pl)))


if __name__ == '__main__':
    main()
