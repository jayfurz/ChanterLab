#!/usr/bin/env python3
"""tape_assign.py — RESEP-01 step 2: assign hymn texts to silence-bounded segments.

Step 1 (tape_segments.py) cuts the tape at real pauses: 56 segments on the grave
orthros tape against 59 known pieces, median 48 s. Those edges are FACTS about
the recording, not estimates, which is exactly what every previous end-finder
lacked — a hymn's end is the segment's end, bounded by the next segment by
construction.

This step decides which segment is which hymn. Each segment is scored by CTC
likelihood against every candidate text (runs of consecutive over-split GLT
entries), and the hymns are assigned to segments by a MONOTONIC path, because
the book and the tape run in the same liturgical order. Segments that match no
text well are left unassigned — those are the parallagi (which sing solfege
syllables, not the text) and the spoken announcements.

Output per hymn: the segment span, hence exact cut points, plus the identifying
text and its per-token loss.

Usage:  tape_assign.py --workdir DIR [--device cuda]

STATUS 2026-08-19: WORKS, NOT YET CLEAN. grave-orthros, best of four runs:

    25/25 hymns assigned, monotonic across the tape
    identification median 3.78/tok, 72% at <=4.5   (per-file was 4.48, 52%)
    t03 -> 160.2-210.1 s against its known cut of 158.5-211.9 s
    median inter-hymn gap 3.4 s

  The premise holds: one hymn per silence-bounded segment identifies better than
  one hymn per pre-cut file, because the segment actually contains one hymn.
  52% -> 72% matters because 4.5/tok is the gate on editing a score boundary.

  Remaining fault: Κατέλυσας is still assigned to two hymns (t03 and t05). A
  use-once constraint is needed and is NOT simply text-order monotonicity —
  that was tried and is wrong. The candidate pool is GLT DOCUMENT order, which
  interleaves the Horologion ordinary with the mode-proper hymns and does not
  follow the recording; imposing it dropped 25/25 to 19/25, shifted every hymn
  by two, and pushed the tail to 5-6/tok. Segments and hymns share an ordering
  because both are the recording; GLT entries do not.

  A real use-once rule needs the used-set in the DP state (or an iterative
  ban-and-resolve pass), not an ordering proxy.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glt_match import WD_MODE, services_for

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
SPLIT = '/mnt/data/chant-corpus/texts/glt_oktoechos_split.json'
SEGS = '/mnt/data/chant-corpus/texts/tape_segments.json'
SR = 16000


def clip(tape, t0, t1):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t0), '-to', str(t1),
                          '-i', tape, '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, timeout=600).stdout
    return np.frombuffer(raw, dtype=np.int16).astype('float32') / 32768.0


def main():
    import numpy as np
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    from forced_align_batch import words_of, ids_of, runs

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--max-run', type=int, default=5)
    ap.add_argument('--rescore', action='store_true',
                    help='recompute segment scores instead of using the cache')
    ap.add_argument('--ban', default='',
                    help='comma-separated text indices the DP may not use; the '
                         'use-once pass fills this in automatically')
    ap.add_argument('--max-seg-run', type=int, default=2,
                    help='most consecutive tape segments one hymn may span')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    rf = f'/mnt/data/chant-corpus/texts/recut_{name}.json'
    if not os.path.exists(rf):
        raise SystemExit(f'need {rf} for the tape path')
    loc = json.load(open(rf))
    tape = loc[0]['tape']
    allsegs = json.load(open(SEGS))
    if tape not in allsegs:
        raise SystemExit(f'no segments for {tape}; run tape_segments.py')
    segs = allsegs[tape]
    hy = json.load(open(os.path.join(a.workdir, 'hymns.json')))
    print(f'{name}: {len(segs)} tape segments, {len(hy)} hymns')

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
    mode, svc = WD_MODE.get(name), services_for(name)
    pool = [g for g in glt if g['_w'] and (
        g['mode'] == 'ordinary'
        or ((not mode or g['mode'] == mode) and g['service'] in svc))]
    pos_of = {id(g): k for k, g in enumerate(pool)}
    cands = []
    for grp in runs(pool, a.max_run):
        w = [x for g in grp for x in g['_w']]
        ids = ids_of(w, vocab, sep)
        rep = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
        cands.append((grp, w, ids, len(ids) + rep, pos_of[id(grp[0])]))
    print(f'  {len(pool)} entries -> {len(cands)} candidate texts')

    # Score every segment (and short run of segments) against every candidate.
    # This is the only expensive part and it does not depend on the DP, so it is
    # CACHED: the assignment can then be re-solved on CPU as many times as the
    # constraints need, instead of re-running the model for every experiment.
    cache = f'/mnt/data/chant-corpus/texts/segscores_{name}.json'
    if os.path.exists(cache) and not a.rescore:
        best_for = {tuple(int(x) for x in k.split(',')): v
                    for k, v in json.load(open(cache)).items()}
        print(f'  loaded cached scores for {len(best_for)} segment runs')
    else:
        best_for = {}
    for i in (range(len(segs)) if not best_for else []):
        for n in range(1, a.max_seg_run + 1):
            if i + n > len(segs):
                break
            t0, t1 = segs[i][0], segs[i + n - 1][1]
            if t1 - t0 > 400:
                continue
            x = clip(tape, t0, t1)
            if x.size < SR:
                continue
            with torch.inference_mode():
                logp = torch.log_softmax(
                    model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits, dim=-1)
            T = logp.shape[1]
            lpt = logp.transpose(0, 1)
            dur = x.size / SR
            Lmax, Lmin = max(64, int(T * 0.45)), max(24, int(1.2 * dur))
            feas = [(g, w, ids, gi) for g, w, ids, need, gi in cands
                    if need < T and Lmin <= len(ids) <= Lmax]
            feas.sort(key=lambda z: len(z[2]))
            top = []
            s0 = 0
            while s0 < len(feas):
                Lc = len(feas[min(s0 + 31, len(feas) - 1)][2])
                B = max(1, min(32, int(2.0e8 / max(T * 2 * Lc, 1))))
                ch = feas[s0:s0 + B]
                s0 += B
                flat, lens = [], []
                for _, _, ids, _gi in ch:
                    flat.extend(ids); lens.append(len(ids))
                with torch.inference_mode(), torch.backends.cudnn.flags(enabled=False):
                    L = torch.nn.functional.ctc_loss(
                        lpt.expand(T, len(ch), lpt.shape[-1]).contiguous(),
                        torch.tensor(flat, dtype=torch.int32, device=dev),
                        torch.full((len(ch),), T, dtype=torch.int32, device=dev),
                        torch.tensor(lens, dtype=torch.int32, device=dev),
                        blank=blank, reduction='none', zero_infinity=True)
                for (g, w, ids, gi), v in zip(ch, L.tolist()):
                    if v <= 0.0 or v != v:
                        continue
                    top.append((v / len(ids), gi, g))
            # keep the best few per segment, not just the best: the DP needs
            # alternatives to satisfy the text-order constraint below
            top.sort(key=lambda z: z[0])
            keep, seen_gi = [], set()
            for pt, gi, g in top:
                if gi in seen_gi:
                    continue
                seen_gi.add(gi)
                keep.append({'lpt': pt, 'gi': gi,
                             'text': ' '.join(x_['text'] for x_ in g),
                             'head': g[0]['heading']})
                if len(keep) >= 8:
                    break
            if keep:
                best_for[(i, n)] = {'t0': t0, 't1': t1, 'opts': keep}
        if (i + 1) % 10 == 0:
            print(f'   scored {i+1}/{len(segs)} segments', flush=True)

    # monotonic assignment of hymns to segment runs
    H, S = len(hy), len(segs)
    NEG = -1e9
    D = [[NEG] * (S + 1) for _ in range(H + 1)]
    P = [[None] * (S + 1) for _ in range(H + 1)]
    for j in range(S + 1):
        D[0][j] = 0.0
        P[0][j] = (0, j - 1, None) if j else None
    if not os.path.exists(cache) or a.rescore:
        json.dump({f'{k[0]},{k[1]}': v for k, v in best_for.items()},
                  open(cache, 'w'), ensure_ascii=False)
        print(f'  cached scores -> {cache}')

    # LAST[i][j] = index in the text pool of the text used most recently on the
    # best path to (i, j). Carrying it makes the texts monotonically ordered,
    # which is the constraint that was missing: the book and the tape run in the
    # same liturgical order, so a text may not be reused and may not go
    # backwards. Without it Κατέλυσας was assigned to two different hymns and
    # the middle of the tape was skipped wholesale.
    banned = {int(x) for x in a.ban.split(',') if x.strip().isdigit()}
    LAST = [[-1] * (S + 1) for _ in range(H + 1)]
    CH = [[None] * (S + 1) for _ in range(H + 1)]
    for i in range(1, H + 1):
        for j in range(1, S + 1):
            best_v, best_p, best_last, best_ch = D[i][j - 1], (i, j - 1, None), \
                LAST[i][j - 1], None
            # a hymn may simply not be on this tape (the chanter: "not all the
            # tapes are the same in that not all of them have every hymn")
            if D[i - 1][j] - 1.0 > best_v:
                best_v, best_p = D[i - 1][j] - 1.0, (i - 1, j, None)
                best_last, best_ch = LAST[i - 1][j], None
            for n in range(1, a.max_seg_run + 1):
                if j - n < 0:
                    continue
                b = best_for.get((j - n, n))
                if not b or D[i - 1][j - n] <= NEG / 2:
                    continue
                prev_last = LAST[i - 1][j - n]
                for o in b['opts']:
                    if o['gi'] in banned:
                        continue
                    # NOT o['gi'] > prev_last. Text-index monotonicity looks
                    # right — book and tape both run in liturgical order — but
                    # the pool is GLT DOCUMENT order, which interleaves the
                    # ordinary with the mode-proper hymns and does NOT follow
                    # the recording. Imposing it dropped 25/25 assigned to
                    # 19/25, shifted every hymn by two, and pushed the tail to
                    # 5-6/tok. Use-once needs a different mechanism than order.
                    if o['gi'] == prev_last:
                        continue                  # never the same text twice running
                    v = D[i - 1][j - n] + max(0.0, 8.0 - o['lpt'])
                    if v > best_v:
                        best_v, best_p = v, (i - 1, j - n, (j - n, n))
                        best_last, best_ch = o['gi'], o
            D[i][j], P[i][j], LAST[i][j], CH[i][j] = best_v, best_p, best_last, best_ch
    reach = [x for x in range(S + 1) if D[H][x] > NEG / 2 and P[H][x] is not None]
    if not reach:
        raise SystemExit('no monotonic assignment found — loosen --max-seg-run')
    j = max(reach, key=lambda x: D[H][x])
    i, out = H, []
    while i > 0:
        if P[i][j] is None:          # unreachable state: stop, do not invent one
            break
        pi, pj, span = P[i][j]
        if span:
            b = best_for[(span[0], span[1])]
            o = CH[i][j] or b['opts'][0]
            out.append({'hymn': hy[i - 1]['name'], 'seg': span, 'lpt': round(o['lpt'], 3),
                        't0': b['t0'], 't1': b['t1'], 'dur': round(b['t1'] - b['t0'], 1),
                        'text': o['text'][:70], 'heading': o['head']})
        i, j = pi, pj
    out.reverse()
    jf = f'/mnt/data/chant-corpus/texts/tapeassign_{name}.json'
    json.dump({'tape': tape, 'workdir': name, 'assigned': out}, open(jf, 'w'),
              ensure_ascii=False, indent=1)
    print(f'\n{len(out)}/{H} hymns assigned to silence-bounded segments')
    for r in out[:30]:
        print('  %-20s %7.1f-%7.1f (%5.1fs) /tok %5.2f  %s'
              % (r['hymn'][:20], r['t0'], r['t1'], r['dur'], r['lpt'], r['text'][:38]))
    print('->', jf)


if __name__ == '__main__':
    main()
