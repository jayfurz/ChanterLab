#!/usr/bin/env python3
"""forced_align_batch.py — force-align every hymn; CTC likelihood picks the text.

Chanter's strategy: feed the audio and the KNOWN text and read off timestamps,
rather than asking a model to guess what is being sung. Validated on gold #2 at
0.028 s median error against 76 chanter pins — 17x better than the DTW aligner.

The same machinery also answers WHICH hymn a recording is. Score every candidate
text by CTC likelihood, -log P(text | audio), and take the best. Measured on
t03, whose text is independently known:

    Κατέλυσας (correct)   197 tok   loss  692    <- lowest
    Ἐν τῷ Σταυρῷ          302 tok   loss 1506
    Νεύσει σοῦ            119 tok   loss  882
    Κέκριται              131 tok   loss  880
    Στόμα δικαίου          61 tok   loss  812

Two earlier scorings failed and are worth recording so they are not retried:
  * mean best-path score rewards SHORT texts — a six-word rubric hides in a 53 s
    track as mostly blank and wins;
  * adding a coverage term does not help either, because CTC will happily
    stretch fourteen words across the whole recording, which is indistinguishable
    from melisma.
Only the full likelihood separates them.

Candidates are RUNS of consecutive over-split GLT entries
(glt_oktoechos_split.json), because a recorded hymn spans a Στίχ. plus its
sticheron, a Δόξα plus its theotokion, and so on. Combining is a liturgical
judgement; this lets the acoustics make it instead.

Usage:  forced_align_batch.py [--workdir DIR] [--device cuda] [--max-run 5]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glt_match import WD_MODE, services_for

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
SPLIT = '/mnt/data/chant-corpus/texts/glt_oktoechos_split.json'
OUT = '/mnt/data/chant-corpus/texts/forced_align'
SR = 16000


def read_audio(path):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1',
                          '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, timeout=1800).stdout
    return np.frombuffer(raw, dtype=np.int16).astype('float32') / 32768.0


def words_of(text, vocab):
    t = unicodedata.normalize('NFC', text).upper().replace('ς', 'Σ')
    out = []
    for w in re.split(r'\s+', t):
        w2 = ''.join(c for c in w if c in vocab)
        if w2:
            out.append(w2)
    return out


def ids_of(words, vocab, sep):
    ids = []
    for i, w in enumerate(words):
        ids += [vocab[c] for c in w]
        if sep is not None and i + 1 < len(words):
            ids.append(sep)
    return ids


def runs(entries, max_run):
    """candidate texts: 1..max_run consecutive entries from the same page+service"""
    out = []
    for i in range(len(entries)):
        for n in range(1, max_run + 1):
            if i + n > len(entries):
                break
            grp = entries[i:i + n]
            if len({(g['page'], g['service']) for g in grp}) > 1:
                break
            out.append(grp)
    return out


def main():
    import torch
    import torchaudio.functional as AF
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--max-run', type=int, default=5)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    dev = a.device if (a.device == 'cpu' or torch.cuda.is_available()) else 'cpu'
    proc = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()
    vocab = proc.tokenizer.get_vocab()
    blank = vocab.get('<pad>', 0)
    sep = vocab.get('|')

    glt = [g for g in json.load(open(SPLIT))
           if 'Ζήτει' not in g['text'][:40] and not g['text'].lstrip().startswith('(')]
    for g in glt:
        g['_w'] = words_of(g['text'], vocab)
    glt = [g for g in glt if g['_w']]

    wds = ([a.workdir] if a.workdir
           else sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/')))
    done = 0
    for wd in wds:
        hp = os.path.join(wd, 'hymns.json')
        if not os.path.exists(hp):
            continue
        name = os.path.basename(wd.rstrip('/'))
        mode, svc = WD_MODE.get(name), services_for(name)
        pool = [g for g in glt
                if g['mode'] == 'ordinary'
                or ((not mode or g['mode'] == mode) and g['service'] in svc)]
        cands = runs(pool, a.max_run)
        if not cands:
            continue
        prepared = []
        for grp in cands:
            w = [x for g in grp for x in g['_w']]
            ids = ids_of(w, vocab, sep)
            # CTC needs one frame per token plus one more for every consecutive
            # repeat. Without this check an unalignable candidate comes back
            # from ctc_loss as 0.0 (zero_infinity) and wins the minimum, then
            # blows up in forced_align.
            rep = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
            prepared.append((grp, w, ids, len(ids) + rep))
        print(f'\n=== {name}  ({len(pool)} entries -> {len(prepared)} candidate runs)',
              flush=True)
        for h in json.load(open(hp)):
            wav = os.path.join(wd, 'melos_' + h['name'], 'audio.wav')
            if not os.path.exists(wav):
                continue
            x = read_audio(wav)
            if x.size < SR:
                continue
            with torch.inference_mode():
                t = torch.from_numpy(x.copy()).unsqueeze(0).to(dev)
                logp = torch.log_softmax(model(t).logits, dim=-1)
            T = logp.shape[1]
            ratio = x.size / T / SR
            lpt = logp.transpose(0, 1)
            Tl = torch.tensor([T], device=dev)
            # Batch the candidates: one ctc_loss call per BATCH, not per
            # candidate. 3580 runs x 173 tracks is ~600k separate calls and
            # Python overhead dominates (the unbatched version pinned a 3090 at
            # 86% and still crawled). Expanding log_probs across the batch
            # dimension is a view, so only the targets cost memory.
            # Native CTC needs O(B x T x L) working memory, so cap both. A
            # plausible hymn runs ~3.7 tokens per second of audio (t03: 197
            # tokens over 53 s), so anything past ~45% of the frame count cannot
            # be what is being sung and is dropped before it costs memory.
            # A plausible hymn runs ~3.7 tokens per second of audio (t03: 197
            # tokens over 53 s). Bound the candidates on BOTH sides: too long
            # cannot be sung in the time and costs O(BxTxL) memory, too short
            # cannot fill it. The floor matters — without it a 61-token psalm
            # verse wins a 53 s track on raw loss.
            dur_s = x.size / SR
            Lmax = max(64, int(T * 0.45))
            Lmin = max(24, int(1.2 * dur_s))
            feasible = [(g_, w_, i_) for g_, w_, i_, nd in prepared
                        if i_ and nd < T and Lmin <= len(i_) <= Lmax]
            best = None
            # Native CTC allocates roughly B x T x 2L floats. T scales with the
            # track (a 160 s hymn is ~8000 frames) and L with the candidate, so a
            # FIXED batch size OOMs on the long ones — the first corpus run died
            # asking for 35.76 GiB. Size each batch from its own longest
            # candidate against a fixed element budget instead.
            feasible.sort(key=lambda z: len(z[2]))
            BUDGET = 2.0e8
            s0 = 0
            while s0 < len(feasible):
                Lc = len(feasible[min(s0 + 31, len(feasible) - 1)][2])
                B = max(1, min(32, int(BUDGET / max(T * 2 * Lc, 1))))
                chunk = feasible[s0:s0 + B]
                s0 += B
                n = len(chunk)
                flat, lens = [], []
                for _, _, i_ in chunk:
                    flat.extend(i_); lens.append(len(i_))
                tg = torch.tensor(flat, dtype=torch.int32, device=dev)
                tl = torch.tensor(lens, dtype=torch.int32, device=dev)
                il = torch.full((n,), T, dtype=torch.int32, device=dev)
                # cuDNN's CTC kernel rejects the expanded (non-contiguous)
                # batch and caps target length; force the native implementation.
                with torch.inference_mode(), torch.backends.cudnn.flags(enabled=False):
                    losses = torch.nn.functional.ctc_loss(
                        lpt.expand(T, n, lpt.shape[-1]).contiguous(), tg, il, tl,
                        blank=blank, reduction='none', zero_infinity=True)
                for (g_, w_, i_), v in zip(chunk, losses.tolist()):
                    if v <= 0.0 or v != v:      # zeroed infinity, or NaN
                        continue
                    # Rank by loss PER TOKEN, not raw loss. Raw loss rewards
                    # short texts — it picked six-word rubrics and instructional
                    # prose ("Οἱ Καταβασίες εἶναι οἱ Εἱρμοὶ ...") over the hymn.
                    # On t03 per-token separates cleanly: correct 3.51, wrong
                    # candidates 4.99 / 6.72 / 7.41 / 13.32.
                    pt = v / len(i_)
                    if best is None or pt < best[0]:
                        best = (pt, g_, w_, i_, v)
                continue
            per_tok, grp, w, ids, loss = best
            with torch.inference_mode():
                p, sc = AF.forced_align(
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
            out_w, k = [], 0
            for wi, word in enumerate(w):
                idx = [i for i in range(k, k + len(word)) if i in first]
                k += len(word) + (1 if sep is not None and wi + 1 < len(w) else 0)
                if idx:
                    out_w.append({'word': word,
                                  't0': round(first[idx[0]] * ratio, 3),
                                  't1': round((last[idx[-1]] + 1) * ratio, 3)})
            text = ' '.join(g['text'] for g in grp)
            json.dump({'workdir': name, 'hymn': h['name'], 'audio': wav,
                       'ctc_loss': round(loss, 2),
                       'loss_per_token': round(loss / max(len(ids), 1), 4),
                       'n_entries': len(grp), 'glt_service': grp[0]['service'],
                       'glt_page': grp[0]['page'], 'glt_heading': grp[0]['heading'],
                       'glt_text': text, 'words': out_w},
                      open(os.path.join(OUT, f'{name}__{h["name"]}.json'), 'w'),
                      ensure_ascii=False, indent=1)
            done += 1
            print('  %-20s /tok %5.2f loss %7.1f  %dx %3dtok %2dw  %s'
                  % (h['name'][:20], per_tok, loss, len(grp), len(ids),
                     len(out_w), text[:38]), flush=True)
    print(f'\n{done} tracks aligned -> {OUT}')


if __name__ == '__main__':
    main()
