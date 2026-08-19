#!/usr/bin/env python3
"""parallagi_probe.py — is this track the hymn, or the chanter singing degrees?

Chanter: "some of the hymns are parallagi only .. about half the hymns would
have ni pa vous only instead of chants."

That breaks the identification pipeline at its root. tape_assign.py forces every
segment against Greek hymn TEXT, so for a parallagi rendition there is no
correct answer in the pool at all — the audio sings "νη πα βου γα", not words.
CTC then lands on whatever is cheapest to align to anything, which is exactly
the failure name_check.py measured: generic psalm boilerplate winning by
margins of 0.03-0.48 per token, because nothing actually fits.

The test is cheap, because the score already tells us what a parallagi
rendition WOULD sing. unitdeg_<hymn>.json holds the parallagi-anchored absolute
degree of every unit, so the expected syllable stream is derivable — no
transcription needed. Score the melos audio against that stream and against the
text it was assigned, and whichever wins says what the audio actually is.

Usage:  parallagi_probe.py [--workdir NAME]
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import soundfile as sf
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forced_align_batch import words_of, ids_of

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
SR = 16000
# The seven degrees as the chanter sings them. Octave equivalents share a name,
# so the stream is degree mod 7.
DEG = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']


def degree_text(wd, hymn):
    f = os.path.join(wd, f'unitdeg_{hymn}.json')
    if not os.path.exists(f):
        return None
    d = json.load(open(f))
    seq = [d[k] for k in sorted(d, key=int)]
    return ' '.join(DEG[int(v) % 7] for v in seq if v is not None)


def ctc_per_tok(model, proc, vocab, blank, sep, dev, wav, text):
    w = words_of(text, vocab)
    if not w:
        return None
    ids = ids_of(w, vocab, sep)
    x, sr = sf.read(wav, dtype='float32')
    if x.ndim > 1:
        x = x.mean(1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    if x.size < SR:
        return None
    with torch.inference_mode():
        logp = torch.log_softmax(
            model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits, dim=-1)
    T = logp.shape[1]
    rep = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
    if len(ids) + rep >= T:
        return None       # not alignable in the available frames
    with torch.inference_mode(), torch.backends.cudnn.flags(enabled=False):
        L = torch.nn.functional.ctc_loss(
            logp.transpose(0, 1),
            torch.tensor(ids, dtype=torch.int32, device=dev).unsqueeze(0),
            torch.tensor([T], dtype=torch.int32, device=dev),
            torch.tensor([len(ids)], dtype=torch.int32, device=dev),
            blank=blank, reduction='none', zero_infinity=True)
    v = L.item()
    return None if v <= 0.0 or v != v else v / len(ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir')
    a = ap.parse_args()

    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    vocab = proc.tokenizer.get_vocab()
    blank, sep = vocab.get('<pad>', 0), vocab.get('|')

    par = txt = neither = 0
    for f in sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/hymns.json')):
        wd = os.path.dirname(f)
        w = os.path.basename(wd)
        if a.workdir and w != a.workdir:
            continue
        af = f'/mnt/data/chant-corpus/texts/tapeassign_{w}.json'
        A = ({x['hymn']: x for x in json.load(open(af))['assigned']}
             if os.path.exists(af) else {})
        for h in json.load(open(f)):
            wav = h.get('melos_audio')
            if not wav or not os.path.exists(wav):
                continue
            dt = degree_text(wd, h['name'])
            if not dt:
                continue
            pl = ctc_per_tok(model, proc, vocab, blank, sep, dev, wav, dt)
            r = A.get(h['name'])
            tl = (ctc_per_tok(model, proc, vocab, blank, sep, dev, wav, r['text'])
                  if r else None)
            if pl is None:
                continue
            if tl is None:
                verdict, _ = 'PARALLAGI (no text score)', par
                par += 1
            elif pl < tl - 0.25:
                verdict = 'PARALLAGI'
                par += 1
            elif tl < pl - 0.25:
                verdict = 'text'
                txt += 1
            else:
                verdict = 'ambiguous'
                neither += 1
            print('  %-16s %-22s degrees %5.2f  text %s  -> %s'
                  % (w, h['name'][:22], pl,
                     ('%5.2f' % tl) if tl is not None else '   --', verdict))
    tot = par + txt + neither
    if tot:
        print('\n%d/%d (%.0f%%) score better as sung DEGREES than as their '
              'assigned text' % (par, tot, 100.0 * par / tot))
        print('%d/%d (%.0f%%) better as text' % (txt, tot, 100.0 * txt / tot))
        print('%d/%d (%.0f%%) within 0.25/tok — undecided' % (neither, tot,
                                                              100.0 * neither / tot))


if __name__ == '__main__':
    main()
