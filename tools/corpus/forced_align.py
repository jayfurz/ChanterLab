#!/usr/bin/env python3
"""forced_align.py — align KNOWN text to chant audio (CTC forced alignment).

Chanter's strategy, and it is the right one:

  "Because liturgical Greek chants are almost always singing pre-existing text
   from historical service books ... you should not ask an AI to guess the text.
   Instead, you feed the AI both the Audio File and the Known Greek Text, and
   let it precisely map the timestamps."

Free-running ASR is hopeless here — measured on the grave orthros tape, whisper
misses 55% of the sung audio and emits 463 s of segments over silence, because
it was never trained on ecclesiastical Greek or on melismatic chant. Forced
alignment skips generation entirely: the text is GIVEN (glt_fetch.py already
pulls it from the GOA digital chant stand), and only the phoneme/character
acoustic layer is used, to decide WHEN each letter is sung. Holding one syllable
for five seconds is fine — CTC simply repeats that token.

Uses torchaudio.functional.forced_align (the same CTC layer WhisperX wraps) over
a Greek wav2vec2 CTC model, so no whisperx dependency is needed. Byzantine chant
is sung with modern Greek pronunciation, so a modern Greek model is appropriate.

Usage:
  forced_align.py --audio a.wav --text "ΚΑΤΕΛΥΣΑΣ ..."   [--json out.json]
  forced_align.py --workdir DIR --hymn NAME --text-from-glt

MEASURED against gold #2 (t03), and READ THE DENOMINATOR (re-measured
2026-08-20 by tools/corpus/fa_eval.py on the current audio):

    each of the 32 WORD onsets to its NEAREST of the 76 pins
                       median |err| 0.0345 s  96.9% within 0.15 s  100% within 0.35 s

This is the figure earlier drafts quoted as "0.028 s median against the 76 t03
pins". It reproduces. What does not survive is the label: the denominator is 32
words, not 76 notes, and "nearest pin" is chosen after the fact. It says that
WHEN forced alignment fires it fires accurately. It does not say how many notes
it times, and it must never be quoted as an onset accuracy.

Scored properly -- every word onset carried to the glyphs it implies, over all
76 pins, through tools/corpus/onset_eval.py:

    FA word path  -> glyphs   26.3% within 0.15 s   13.2% within 0.05 s
    FA char path  -> glyphs   55.3% within 0.15 s   32.9% within 0.05 s
    ORACLE, nearest char      88.2% within 0.15 s   60.5% within 0.05 s
    DTW aligner (annotator)   32.9% within 0.15 s   30.3% within 0.05 s

t03 is TRAINING data and a burnt benchmark (NEURAL-CHANT.md 6.1). Every row is a
comparison number against prior work, never evidence of generalisation.

So forced alignment beats the DTW aligner on the character path and is WORSE
than it on the word path -- a real improvement, but not the 17x one, and only
via the characters. Only 23 of the 76 glyphs are word-initial, so the word path
has nothing of its own to say about the other 53. See NEURAL-CHANT.md 0.4.

Denominators, because mixing them is the error this whole correction is about:
every rate above is over all 76 pins, from onset_eval.py. The DTW aligner's
often-quoted "0.485 s median" is over the 52 units it matched; over all 76 its
median is 0.714 s.

TIMEBASE WARNING. The stored artefacts under texts/forced_align/ carry no audio
checksum, and t03's predated a recut of its own audio by 20 hours -- every word
onset was shifted a median +0.239 s, which scored as 1.3% and was recorded in
the plan as "forced alignment is nearly useless, 4%". Nothing in the artefact
said so; the text still matched. Re-run this script whenever the audio moves,
and see fa_eval.py's --allow-stale-fa guard.

What still holds, and is the reason this approach is right:
  * word onsets ARE accurate where they exist, so they are hard anchors for the
    note-level DTW -- what ALIGN-02 wanted the chanter's manual pins for.
  * the same alignment gives syllable timing for SYL-01 and training labels for
    the onset model, without the chanter pinning anything.
  * CTC score identifies WHICH hymn a recording is -- but score it with
    name_check.py, never with the loss (see CTC-loss-is-not-correctness).
"""
import argparse
import json
import os
import re
import sys
import unicodedata

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'


def to_vocab(text, vocab):
    """uppercase Greek, keep only characters the model knows, '|' between words"""
    t = unicodedata.normalize('NFC', text).upper()
    t = t.replace('Ϊ', 'Ι').replace('Ϋ', 'Υ').replace('ς', 'Σ').replace('Σ', 'Σ')
    out, words = [], []
    for w in re.split(r'\s+', t):
        w2 = ''.join(c for c in w if c in vocab)
        if w2:
            words.append(w2)
    return words


_MODEL_CACHE = {}


def _load(device):
    """Processor and model for a device, loaded once per process.

    align() used to load both on every call. That is invisible for one track and
    costs 424 weight loads over a 160-track batch (realign_fa.py), so it is
    cached here rather than at each call site.
    """
    if device not in _MODEL_CACHE:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        proc = Wav2Vec2Processor.from_pretrained(MODEL)
        model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(device).eval()
        _MODEL_CACHE[device] = (proc, model)
    return _MODEL_CACHE[device]


def align(audio_path, text, device='cpu'):
    import torch
    import torchaudio
    import torchaudio.functional as F

    proc, model = _load(device)
    vocab = proc.tokenizer.get_vocab()

    # read via ffmpeg: torchaudio 2.11 routes load() through torchcodec, which
    # is not installed, and ffmpeg is already a hard dependency of this pipeline
    import subprocess
    import numpy as np
    sr = 16000
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', audio_path,
                          '-ac', '1', '-ar', str(sr), '-f', 's16le', '-'],
                         capture_output=True, timeout=1800).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype('float32') / 32768.0
    wav = torch.from_numpy(a.copy()).unsqueeze(0)
    with torch.inference_mode():
        logits = model(wav.to(device)).logits
        logp = torch.log_softmax(logits, dim=-1).cpu()

    words = to_vocab(text, vocab)
    if not words:
        raise SystemExit('no alignable characters in the text')
    sep = vocab.get('|')
    ids = []
    spans = []                       # (word_index, start_tok, end_tok)
    for wi, w in enumerate(words):
        st = len(ids)
        ids += [vocab[c] for c in w]
        spans.append((wi, st, len(ids)))
        if sep is not None and wi + 1 < len(words):
            ids.append(sep)
    targets = torch.tensor([ids], dtype=torch.int32)
    blank = vocab.get('<pad>', 0)
    path, scores = F.forced_align(logp, targets, blank=blank)
    path = path[0].tolist()
    scores = scores[0].tolist()

    ratio = wav.shape[1] / logp.shape[1] / sr        # seconds per frame
    # first and last frame each target index occupies
    first, last = {}, {}
    ti = -1
    prev = blank
    for fi, tok in enumerate(path):
        if tok == blank:
            prev = tok
            continue
        if tok != prev:
            ti += 1
        first.setdefault(ti, fi)
        last[ti] = fi
        prev = tok
    out = []
    for wi, st, en in spans:
        idx = [i for i in range(st, en) if i in first]
        if not idx:
            continue
        out.append({'word': words[wi],
                    't0': round(first[idx[0]] * ratio, 3),
                    't1': round((last[idx[-1]] + 1) * ratio, 3),
                    'score': round(sum(scores[first[i]] for i in idx) / len(idx), 3)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--audio', required=True)
    ap.add_argument('--text')
    ap.add_argument('--text-file')
    ap.add_argument('--json')
    ap.add_argument('--device', default='cpu')
    a = ap.parse_args()
    text = a.text or open(a.text_file, encoding='utf-8').read()
    res = align(a.audio, text, a.device)
    for r in res[:200]:
        print('%8.3f %8.3f  %6.2f  %s' % (r['t0'], r['t1'], r['score'], r['word']))
    print('\n%d words aligned' % len(res))
    if a.json:
        json.dump(res, open(a.json, 'w'), ensure_ascii=False, indent=1)
        print('->', a.json)


if __name__ == '__main__':
    main()
