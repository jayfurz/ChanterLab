#!/usr/bin/env python3
"""audio_cut_pairs.py — cut a hymn's end using the NEXT hymn's start.

audio_cut_fa.py failed because forced alignment cannot say "the text ran out
here": every token must be placed somewhere, so over a padded window the final
melisma smears to the window edge (+18.45 s = exactly the look-ahead). Adding a
larger window makes it worse, not better.

The fix is structural, and it is the same monotonic constraint the score side
already uses: align TWO consecutive hymns jointly. Concatenate hymn i's text
with hymn i+1's text and force-align the pair over a window spanning both. Now
the end of hymn i is pinned by the beginning of hymn i+1 — the model has to put
the next hymn's first words somewhere, and it cannot do that inside hymn i.
There is no free window edge for the melisma to run to.

The gap between the last token of text i and the first token of text i+1 is the
real pause between the hymns; the cut goes inside it.

Usage:  audio_cut_pairs.py --workdir DIR [--apply] [--max-loss 4.5]

STATUS 2026-08-19: CORRECT BUT LOW COVERAGE. Sound where it applies.

  With the adjacency filter the numbers are believable (+4.46, -6.57, +0.75,
  +4.51 s) — but it only fires on 1-3 tracks per workdir, because two melos
  tracks are rarely adjacent on the tape. The chanter: "the hymns always had a
  paralagi then melos right after of the same hymn and length", so what sits
  between two melos tracks is usually the NEXT hymn's parallagi, which sings
  solfege syllables rather than the text. Spanning that makes the alignment
  smear badly (t03 +57 s, t17 +75 s, t31 +52 s before the filter).

  The obvious next constraint is the chanter's other observation, that a hymn's
  parallagi and melos have the SAME LENGTH. Measured over the 55 hymns that have
  both: median ratio 1.02, which confirms the rule — but p25 0.69 and p75 1.80,
  with only 20% inside +/-15%. The rule is right and the PAIRINGS are wrong;
  re_pair.py exists for exactly that and would have to run first.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
FA = '/mnt/data/chant-corpus/texts/forced_align'
CORPUS = '/mnt/data/chant-corpus'
SR = 16000


def window(tape, t0, t1):
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
    ap.add_argument('--max-loss', type=float, default=4.5)
    ap.add_argument('--pad-start', type=float, default=0.25)
    ap.add_argument('--gap-frac', type=float, default=0.5,
                    help='where in the inter-hymn gap to cut (0.5 = midpoint)')
    ap.add_argument('--device', default='cuda')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    rf = os.path.join(CORPUS, 'texts', f'recut_{name}.json')
    if not os.path.exists(rf):
        raise SystemExit(f'run audio_recut.py --workdir {a.workdir} first')
    loc = {r['hymn']: r for r in json.load(open(rf))}
    hy = json.load(open(os.path.join(a.workdir, 'hymns.json')))

    dev = a.device if (a.device == 'cpu' or torch.cuda.is_available()) else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    vocab = proc.tokenizer.get_vocab()
    blank = vocab.get('<pad>', 0)
    sep = vocab.get('|')

    def fa_of(h):
        p = os.path.join(FA, f'{name}__{h["name"]}.json')
        if not os.path.exists(p):
            return None
        d = json.load(open(p))
        return d if (d.get('loss_per_token') or 99) <= a.max_loss else None

    seq = [h for h in hy if h['name'] in loc]
    seq.sort(key=lambda h: loc[h['name']]['cur'][0])
    out = []
    print('%-20s %8s %8s %8s  %s' % ('hymn', 'cur_len', 'new_len', 'd_end', 'gap'))
    for i in range(len(seq) - 1):
        h, nx = seq[i], seq[i + 1]
        fa1, fa2 = fa_of(h), fa_of(nx)
        if not fa1 or not fa2:
            continue
        r1, r2 = loc[h['name']], loc[nx['name']]
        # Only pair tracks that are genuinely adjacent on the tape. Chanter:
        # "the hymns always had a paralagi then melos right after of the same
        # hymn and length" — so between two melos tracks there is usually the
        # NEXT hymn's parallagi, which sings solfege syllables rather than the
        # text. Spanning that makes the alignment smear (t03 came out +57 s,
        # t17 +75 s). If the next melos is not close behind, this method has no
        # anchor to offer and the RMS cut stands.
        between = r2['cur'][0] - r1['cur'][1]
        if not (-1.0 <= between <= 15.0):
            continue
        w0 = max(0.0, r1['cur'][0] - 2.0)
        w1 = r2['cur'][0] + min(25.0, max(8.0, 0.4 * (r2['cur'][1] - r2['cur'][0])))
        if w1 - w0 > 420:
            continue
        x = window(r1['tape'], w0, w1)
        if x.size < SR:
            continue
        w_a = words_of(fa1['glt_text'], vocab)
        w_b = words_of(fa2['glt_text'], vocab)
        ids_a = ids_of(w_a, vocab, sep)
        ids = ids_of(w_a + w_b, vocab, sep)
        with torch.inference_mode():
            logp = torch.log_softmax(
                model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits, dim=-1)
        T = logp.shape[1]
        rep = sum(1 for k in range(1, len(ids)) if ids[k] == ids[k - 1])
        if not ids or len(ids) + rep >= T:
            continue
        with torch.inference_mode():
            p, _ = AF.forced_align(
                logp, torch.tensor([ids], dtype=torch.int32, device=dev), blank=blank)
        path = p[0].tolist()
        first, last, ti, prev = {}, {}, -1, blank
        for fi, tok in enumerate(path):
            if tok == blank:
                prev = tok
                continue
            if tok != prev:
                ti += 1
            first.setdefault(ti, fi)
            last[ti] = fi
            prev = tok
        ratio = x.size / T / SR
        n_a = len(ids_a)
        end_a = max((last[k] for k in last if k < n_a), default=None)
        start_b = min((first[k] for k in first if k >= n_a), default=None)
        first_a = min((first[k] for k in first if k < n_a), default=None)
        if end_a is None or start_b is None or first_a is None or start_b <= end_a:
            continue
        t_enda = w0 + (end_a + 1) * ratio
        t_startb = w0 + start_b * ratio
        gap = t_startb - t_enda
        cut = t_enda + a.gap_frac * gap
        ns = max(0.0, w0 + first_a * ratio - a.pad_start)
        out.append({'workdir': name, 'hymn': h['name'], 'tape': r1['tape'],
                    'piece': r1['piece'], 'cur': r1['cur'],
                    'new': [round(ns, 3), round(cut, 3)],
                    'gap_s': round(gap, 2),
                    'd_end': round(cut - r1['cur'][1], 2)})
        print('%-20s %8.1f %8.1f %+8.2f  %5.2f'
              % (h['name'][:20], r1['cur'][1] - r1['cur'][0], cut - ns,
                 cut - r1['cur'][1], gap), flush=True)
    jf = os.path.join(CORPUS, 'texts', f'cutpairs_{name}.json')
    json.dump(out, open(jf, 'w'), indent=1)
    if out:
        g = sorted(r['gap_s'] for r in out)
        print(f'\n{len(out)} ends pinned by the next hymn; median gap {g[len(g)//2]:.2f} s')
    if a.apply:
        for r in out:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', r['tape'],
                            '-ss', str(r['new'][0]), '-to', str(r['new'][1]),
                            '-ac', '1', '-ar', '44100',
                            r['piece'].replace('.wav', '.recut.wav')], check=True)
        print(f'wrote {len(out)} re-cut files')
    print('->', jf)


if __name__ == '__main__':
    main()
