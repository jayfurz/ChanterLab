#!/usr/bin/env python3
"""audio_cut_fa.py — cut each track exactly, using where the words actually land.

The RMS re-cut (audio_recut.py) took corpus clipping from 126/145 to 54/145, but
it is guessing at a gap: on a tape that runs on with little silence, "walk until
quiet" has nothing to find, and a fixed fallback tail just appends more sounding
audio. Whisper cannot help either — it misses 55% of the sung audio here.

Forced alignment can, because it knows the words. Align the hymn's canonical
text (chosen acoustically by forced_align_batch.py) against a WINDOW of the
source tape that extends past the current cut, and the last word's offset is the
end of the hymn — not an estimate of a pause, but the moment the final syllable
stops. The first word's onset gives the true start the same way.

This is the chanter's own strategy applied to cutting rather than to alignment:
feed the audio and the known text, and read the timestamps off.

Usage:  audio_cut_fa.py --workdir DIR [--apply] [--pad-end 0.45] [--pad-start 0.25]

STATUS 2026-08-19: DOES NOT WORK YET. Do not run with --apply.

  The starts are good — forced alignment places a first onset reliably, and
  d_start lands in +/-2 s across the board. The ENDS do not converge:

    * the aligned end is unusable outright. CTC spreads the final token across
      whatever audio follows, so with a padded search window the last word lands
      at the window edge every time (d_end = +18.45 s = exactly --look).
    * taking the last WORD'S ONSET and letting the RMS envelope find the decay
      is better in principle and still fails: several tracks still stop at the
      window edge and t57 came out 44 s SHORT.

  The reason is upstream, not in the search. This assumes the identified text is
  exactly what the window contains, and neither side is guaranteed: an
  identification at 4.5/tok may be only part of what is sung, and an 18 s look
  window routinely contains the start of the NEXT hymn. Forced alignment cannot
  say "the text ran out here" — it must place every token somewhere.

  What would fix it: identify and align CONSECUTIVE hymns jointly over the tape,
  so each hymn's end is pinned by the next hymn's start rather than by a window
  edge. That is the same monotonic structure boundary_fit.py uses on the score
  side, applied to the tape.

  Until then audio_recut.py (RMS + whisper bounds) is the shipped cutter:
  126/145 clipped -> 54/145.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
FA = '/mnt/data/chant-corpus/texts/forced_align'
CORPUS = '/mnt/data/chant-corpus'
SR = 16000


def tape_window(tape, t0, t1):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(max(0.0, t0)),
                          '-to', str(t1), '-i', tape, '-ac', '1',
                          '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, timeout=900).stdout
    return np.frombuffer(raw, dtype=np.int16).astype('float32') / 32768.0


def main():
    import numpy as np
    import torch
    import torchaudio.functional as AF
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    from forced_align_batch import words_of, ids_of

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--pad-start', type=float, default=0.25)
    ap.add_argument('--pad-end', type=float, default=0.45)
    ap.add_argument('--look', type=float, default=18.0,
                    help='how far past the current cut to search for the end')
    ap.add_argument('--max-loss', type=float, default=4.5)
    ap.add_argument('--device', default='cuda')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    rf = os.path.join(CORPUS, 'texts', f'recut_{name}.json')
    if not os.path.exists(rf):
        raise SystemExit(f'run audio_recut.py --workdir {a.workdir} first '
                         '(it locates each piece inside the tape)')
    loc = {r['hymn']: r for r in json.load(open(rf))}

    dev = a.device if (a.device == 'cpu' or torch.cuda.is_available()) else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    vocab = proc.tokenizer.get_vocab()
    blank = vocab.get('<pad>', 0)
    sep = vocab.get('|')

    out, skipped = [], 0
    print('%-20s %8s %8s %8s %8s' % ('hymn', 'cur_len', 'new_len', 'd_start', 'd_end'))
    for h in json.load(open(os.path.join(a.workdir, 'hymns.json'))):
        fp = os.path.join(FA, f'{name}__{h["name"]}.json')
        r = loc.get(h['name'])
        if not r or not os.path.exists(fp):
            continue
        fa = json.load(open(fp))
        if (fa.get('loss_per_token') or 99) > a.max_loss:
            skipped += 1
            continue
        cs, ce = r['cur']
        w0, w1 = max(0.0, cs - 2.0), ce + a.look
        x = tape_window(r['tape'], w0, w1)
        if x.size < SR:
            continue
        words = words_of(fa['glt_text'], vocab)
        ids = ids_of(words, vocab, sep)
        with torch.inference_mode():
            logp = torch.log_softmax(
                model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits, dim=-1)
        T = logp.shape[1]
        rep = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
        if not ids or len(ids) + rep >= T:
            continue
        with torch.inference_mode():
            p, _ = AF.forced_align(
                logp, torch.tensor([ids], dtype=torch.int32, device=dev), blank=blank)
        path = p[0].tolist()
        nb = [i for i, t in enumerate(path) if t != blank]
        if len(nb) < 2:
            continue
        ratio = x.size / T / SR
        t_first = w0 + nb[0] * ratio
        # The forced-aligned END is NOT usable: CTC spreads the final token
        # across whatever audio follows, so a padded window puts the last word
        # at the window edge every time (+18.45 s = exactly --look). Use the
        # last WORD'S ONSET, which forced alignment does place reliably, then
        # let the envelope find where that final note actually decays.
        k, last_onset_tok = 0, None
        for wi, word in enumerate(words):
            last_onset_tok = k
            k += len(word) + (1 if sep is not None and wi + 1 < len(words) else 0)
        ti, prev, first_of = -1, blank, {}
        for fi, tok in enumerate(path):
            if tok == blank:
                prev = tok
                continue
            if tok != prev:
                ti += 1
            first_of.setdefault(ti, fi)
            prev = tok
        f_on = first_of.get(last_onset_tok, nb[-1])
        t_lastword = w0 + f_on * ratio
        hop = int(0.02 * SR)
        env = np.sqrt(np.maximum(
            (x[:x.size // hop * hop].reshape(-1, hop) ** 2).mean(axis=1), 0))
        fl = float(np.percentile(env, 20))
        lo = float(np.percentile(env, 90))
        thr = fl + 0.18 * max(lo - fl, 1e-9)
        i0 = int((t_lastword - w0) / 0.02)
        i = i0
        quiet = int(0.30 / 0.02)
        while i < env.size - quiet:
            if (env[i:i + quiet] <= thr).all():
                break
            i += 1
        t_last = w0 + i * 0.02
        ns, ne = max(0.0, t_first - a.pad_start), t_last + a.pad_end
        out.append({'workdir': name, 'hymn': h['name'], 'tape': r['tape'],
                    'piece': r['piece'], 'cur': [cs, ce], 'new': [round(ns, 3), round(ne, 3)],
                    'd_start': round(ns - cs, 2), 'd_end': round(ne - ce, 2),
                    'loss_per_token': fa.get('loss_per_token')})
        print('%-20s %8.1f %8.1f %+8.2f %+8.2f'
              % (h['name'][:20], ce - cs, ne - ns, ns - cs, ne - ce), flush=True)
    jf = os.path.join(CORPUS, 'texts', f'cutfa_{name}.json')
    json.dump(out, open(jf, 'w'), indent=1)
    print(f'\n{len(out)} cuts derived from sung text; {skipped} skipped '
          f'(identification weaker than {a.max_loss}/tok)')
    if a.apply:
        for r in out:
            dst = r['piece'].replace('.wav', '.recut.wav')
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(r['new'][0]), '-to', str(r['new'][1]),
                            '-ac', '1', '-ar', '44100', dst], check=True)
        print(f'wrote {len(out)} re-cut files')
    print('->', jf)


if __name__ == '__main__':
    main()
