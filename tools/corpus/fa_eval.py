#!/usr/bin/env python3
"""fa_eval.py -- what the forced aligner is actually worth as a note-onset source.

REPRO-01 (docs/plans/NEURAL-CHANT.md section 0.4). forced_align.py, FA-ONSETS.md
and ONSET-MODEL.md all cite "median |err| 0.028 s, 91% within 0.15 s" against the
76 t03 pins. The stored result holds 32 WORD onsets, the pins are per GLYPH, and
no word->glyph mapping was ever written down. This script produces the mapping,
states its rule, shows the evidence that it is right, counts what it cannot
place, and hands every variant to onset_eval.py.

The inherited number turned out to be REAL BUT MISLABELLED, which is worse than
wrong -- see the bottom of this docstring. Both halves matter: the per-glyph
score below is what a model must beat, and the relabelling is what stops 0.028 s
being quoted as "forced alignment has nearly solved this".

The mapping. Each annotator slot carries the syllable sung on that glyph. Those
labels, concatenated in glyph order and normalised the way the CTC target stream
is normalised, are a near-copy of the canonical text: 172 characters against 179,
168 of them identical under a Needleman-Wunsch alignment. So the rule is

    glyph -> its label's FIRST character -> that character's CTC onset

with no timing used to choose anything. The mapping is monotone in glyph order,
and for 53 of the 56 glyphs it places, the canonical text at the mapped position
spells the glyph's own label; the 3 exceptions (4, 19, 66) differ only by the
capital iota that uppercasing an iota subscript inserts.

18 of 76 glyphs carry no label at all -- notes re-articulated on a vowel already
sounding -- and 2 more (7, 71) carry a label character the canonical text does
not contain, a written-out repeat of the preceding vowel. Those 20 glyphs are
UNPLACEABLE: 0 5 7 12 20 21 24 32 33 38 43 44 46 50 55 56 65 67 68 71. They are
counted as misses in the denominator of 76, never dropped. Glyph 0 is one of the
18 -- its syllable Κα is a drop cap and was never labelled -- which is why a
naive sequential match walks off, and why the alignment is done over characters
rather than by counting syllables.

Measured 2026-08-20, every number from tools/corpus/onset_eval.py:

    variant                     <=150ms  <=100ms  <=50ms  slips  median|dt|  placed
    char_first (the mapping)      55.3%    52.6%   32.9%     1     0.061 s    56/76
    word_first_recovered          26.3%    23.7%   13.2%     0     0.063 s    23/76
    word_all_recovered            26.3%    23.7%   13.2%     3     0.479 s    56/76
    word_all_stored               23.7%    22.4%   14.5%     3     0.511 s    55/76
    ORACLE nearest char           88.2%    81.6%   60.5%     1     0.039 s    76/76

(Slip counts are from the corrected onset_eval.slips(), 2026-08-20: only a
maximal out-of-gate run LONGER than 3 notes counts, which is what its docstring
always said. The earlier 6/3/5 counted isolated jitter as lost sync. Note the
oracle still shows 1 -- glyphs 72-75, the closing cadence, where no character
candidate exists at any tolerance, so even reading the gold cannot place them.)

Rates are over all 76 pins; median|dt| is over the notes each variant places, so
char_first's 0.061 s excludes the 20 hardest and must not be compared with the
oracle's 0.039 s over 76. onset_eval.py prints that caveat itself now.

Read char_first as the forced-alignment baseline on t03 and the oracle as an
upper bound no FA-only rule can beat: it picks the candidate nearest the gold
time it is then scored against. It is not an achievable score. Its 60.5% and
81.6% are 46/76 and 62/76, which is fa_char_coverage.py's coverage count arrived
at independently -- the one cross-check available on the character path.

t03 is TRAINING data and a burnt benchmark. Every row is a comparison number and
none of them is evidence of generalisation.

STALE TIMEBASE, and why this script now refuses one. An earlier run scored
word_all_stored at 1.3% and blamed the NFC/NFD normalisation difference. That
was wrong. The stored artefact for t03 was written 19 Aug 00:14; melos_t03_/
audio.wav was recut 19 Aug 20:14. Every stored word onset is shifted a median
+0.239 s against the audio it claims to describe, and its whole apparent error
IS that shift (median |err| to nearest pin: 0.2395 s, i.e. the shift). Re-run on
the current audio it scores 23.7%, so the two normalisations differ by 2.6
points, not by 22. The stored word LIST still reproduces from the text, so a
string check passes -- nothing in the artefact reveals the staleness. This is
exactly the hazard NEURAL-CHANT.md section 9 names under "timebase manifests",
and it had already reached the plan as "the stored word output is nearly
useless, 4%". main() now compares mtimes and exits unless --allow-stale-fa.

WHAT 0.028 s ACTUALLY WAS. Measure each of the 32 word onsets against whichever
of the 76 pins is NEAREST, on the current audio:

    median |err| 0.0345 s    96.9% <=0.15 s    100% <=0.35 s    max 0.205 s

against the citation's 0.028 s / 91% / 100%. Same statistic, 6 ms apart -- it
reproduces. And it is not an artefact of how densely pins are packed: shifting
the same onsets 0.3-2.0 s off the music still lands 45% within 150 ms, and
uniformly random times land 47%, against the real 96.9%.

So the denominator is the error, not the number. 0.028 s is a word-to-nearest-
pin distance over 32 WORDS. It says forced alignment is accurate WHERE IT
FIRES; it says nothing about the 24 of 76 notes that get no word onset at all,
and a word onset times the first note of its word and is silent about the rest.
Quote it as "FA word onsets sit a median 0.034 s from a real note onset". Never
quote it as an onset accuracy, and never as "FA solves 80% of the notes".

Caching. The CTC pass is re-run in-process (like fa_char_coverage.py) and the
179 character onsets are cached with the audio sha256, the model id and the text
hash. --verify-cache re-runs the model and asserts the cache still matches, which
is how the numbers above were checked to be run-invariant.

Usage:
  fa_eval.py --cache /tmp/repro01_char_onsets.json --out /tmp/repro01_fa_eval.json
  fa_eval.py --cache ... --out ... --verify-cache
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ONSET_EVAL = os.path.join(HERE, 'onset_eval.py')

MODEL = 'jonatasgrosman/wav2vec2-large-xlsr-53-greek'
# Set by reseed_batch.py before the first call; 'cpu' keeps single-piece runs
# reproducible with the numbers in this docstring (GPU output is bit-identical,
# verified 2026-08-20: max word-onset difference 0.000 s over 32 words).
DEVICE = 'cpu'
FA_JSON = '/mnt/data/chant-corpus/texts/forced_align/grave-orthros__t03_.json'
ANNOT = os.path.join(ROOT, 'tools/chant-reel/annotator/data/grave-orthros-t03/annotator_data.json')
PINS = os.path.join(ROOT, 'datasets/grave-orthros-t03-gold/pins.json')
SR = 16000


def norm_text(s):
    """The CTC target normalisation: NFD, uppercase, drop combining marks.

    Uppercasing AFTER the decomposition is load-bearing: str.upper() maps the
    combining ypogegrammeni to a capital iota, which is why the aligner's own
    output reads ΤΩΙ for τῷ. Reproduce it, do not tidy it.
    """
    t = unicodedata.normalize('NFD', s).upper()
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return t.replace('ς', 'Σ')


def norm_text_nfc(s):
    """forced_align.to_vocab()'s normalisation, reproduced exactly.

    NFC instead of NFD, so a precomposed accented vowel survives only if the
    model's vocabulary happens to hold it and is dropped otherwise: ΤῸΝ becomes
    ΤΝ, and the article ὁ vanishes altogether. That is why the stored output has
    32 words where the character path has 33, and it is the reason a stored word
    index cannot be used as a text word index.
    """
    t = unicodedata.normalize('NFC', s).upper()
    return t.replace('\u03aa', '\u0399').replace('\u03ab', '\u03a5').replace('\u03c2', '\u03a3')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ctc_char_path(fa):
    """Re-run the wav2vec2 Greek CTC forced alignment; keep the CHARACTER grid.

    forced_align.py computes exactly this and then aggregates it into words at
    write time. Everything below the word level is recovered here.
    """
    import numpy as np
    import torch
    import torchaudio.functional as F
    # Load once per process. This is called per piece by reseed_batch.py, and
    # reloading 424 weights each time dominated the batch.
    from forced_align import _load
    proc, model = _load(DEVICE)
    vocab = proc.tokenizer.get_vocab()
    blank = vocab.get('<pad>', 0)

    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', fa['audio'],
                          '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
                         capture_output=True, timeout=1800).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype('float32') / 32768.0
    wav = torch.from_numpy(a.copy()).unsqueeze(0).to(DEVICE)
    with torch.inference_mode():
        logp = torch.log_softmax(model(wav).logits, dim=-1).cpu()

    src = re.split(r'\s+', fa['glt_text'].strip())
    nfd = [''.join(c for c in norm_text(w) if c in vocab) for w in src]
    nfc = [''.join(c for c in norm_text_nfc(w) if c in vocab) for w in src]
    words = [w for w in nfd if w]
    # source-word index of each recovered word, and of each stored word
    rec_src = [i for i, w in enumerate(nfd) if w]
    sto_src = [i for i, w in enumerate(nfc) if w]
    sep = vocab.get('|')
    ids, charpos = [], []
    for wi, w in enumerate(words):
        for ci, c in enumerate(w):
            charpos.append((wi, ci, c))
            ids.append(vocab[c])
        if sep is not None and wi + 1 < len(words):
            charpos.append(None)          # a separator is not a sung character
            ids.append(sep)
    path, _ = F.forced_align(logp, torch.tensor([ids], dtype=torch.int32), blank=blank)
    path = path[0].tolist()
    ratio = wav.shape[1] / logp.shape[1] / SR

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

    chars = []
    for i, cp in enumerate(charpos):
        if cp is None:
            continue
        wi, ci, c = cp
        chars.append({'i': len(chars), 'w': wi, 'ci': ci, 'c': c,
                      't0': round(first[i] * ratio, 3),
                      't1': round((last[i] + 1) * ratio, 3)})
    return {'model': MODEL, 'audio': fa['audio'], 'audio_sha256': sha256(fa['audio']),
            'text_sha256': hashlib.sha256(fa['glt_text'].encode()).hexdigest(),
            'n_frames': int(logp.shape[1]), 'sec_per_frame': ratio,
            'words': words, 'stored_words': [w for w in nfc if w],
            'rec_src': rec_src, 'sto_src': sto_src, 'chars': chars}


def load_chars(fa, cache_path, verify):
    """Cached CTC recovery. --verify-cache re-runs the model and diffs."""
    if cache_path and os.path.exists(cache_path) and not verify:
        c = json.load(open(cache_path))
        if (c.get('audio_sha256') == sha256(fa['audio'])
                and c.get('text_sha256') == hashlib.sha256(fa['glt_text'].encode()).hexdigest()
                and c.get('model') == MODEL):
            return c, 'cache'
    fresh = ctc_char_path(fa)
    if verify and cache_path and os.path.exists(cache_path):
        old = json.load(open(cache_path))
        if json.dumps(old, sort_keys=True) != json.dumps(fresh, sort_keys=True):
            sys.exit('CACHE MISMATCH: a fresh CTC run differs from %s' % cache_path)
        print('cache verified against a fresh CTC run: identical')
    if cache_path:
        json.dump(fresh, open(cache_path, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
    return fresh, ('fresh+verified' if verify else 'fresh')


def nw_align(a, b, match=2, mismatch=-1, gap=-1):
    """Needleman-Wunsch over two character strings -> list of (i, j) pairs.

    Deterministic: ties resolve diagonal, then up, then left. Small enough
    (~180x180) that the quadratic table costs nothing.
    """
    n, m = len(a), len(b)
    sc = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        sc[i][0] = i * gap
        bt[i][0] = 1
    for j in range(1, m + 1):
        sc[0][j] = j * gap
        bt[0][j] = 2
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            d = sc[i - 1][j - 1] + (match if ai == b[j - 1] else mismatch)
            u = sc[i - 1][j] + gap
            l = sc[i][j - 1] + gap
            best = d if d >= u and d >= l else (u if u >= l else l)
            sc[i][j] = best
            bt[i][j] = 0 if best == d else (1 if best == u else 2)
    i, j, out = n, m, []
    while i > 0 or j > 0:
        b_ = bt[i][j]
        if i > 0 and j > 0 and b_ == 0:
            out.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and b_ == 1:
            i -= 1
        else:
            j -= 1
    out.reverse()
    return out


def build_mapping(chars, slots):
    """glyph -> canonical character index, from the syllable labels alone.

    No timing enters this function. That is the point: the mapping has to be
    checkable independently of the numbers it is about to produce.
    """
    canon = ''.join(c['c'] for c in chars)
    lab, owner = [], []
    for gi, label in zip(slots['gi'], slots['label']):
        for c in norm_text(label):
            if c.isspace():
                continue
            lab.append(c)
            owner.append(gi)
    L = ''.join(lab)
    pairs = nw_align(L, canon)
    exact = [(x, y) for x, y in pairs if L[x] == canon[y]]
    lab2canon = dict(exact)

    g2c = {}
    for k, gi in enumerate(owner):
        if gi in g2c:
            continue
        if k in lab2canon:
            g2c[gi] = lab2canon[k]

    all_gi = list(slots['gi'])
    no_label = [gi for gi, s in zip(slots['gi'], slots['label']) if not norm_text(s).strip()]
    unplaced = [gi for gi in all_gi if gi not in g2c]
    seq = [g2c[gi] for gi in sorted(g2c)]
    nonmono = sum(1 for i in range(1, len(seq)) if seq[i] < seq[i - 1])

    # independent evidence: does the canonical text at the mapped position spell
    # the glyph's own label?
    agree = 0
    disagree = []
    for gi in sorted(g2c):
        want = ''.join(ch for ch in norm_text(slots['label'][all_gi.index(gi)]) if not ch.isspace())
        got = canon[g2c[gi]:g2c[gi] + len(want)]
        if got == want:
            agree += 1
        else:
            disagree.append({'gi': gi, 'label': want, 'canon_at_mapped': got})

    ev = {
        'rule': 'glyph -> first character of its annotator syllable label -> that '
                'character CTC onset; label stream aligned to the canonical CTC '
                'target stream by Needleman-Wunsch, exact-character matches only',
        'n_glyphs': len(all_gi),
        'n_label_chars': len(L), 'n_canon_chars': len(canon),
        'nw_pairs': len(pairs), 'nw_exact_matches': len(exact),
        'label_chars_unaligned': len(L) - len(exact),
        'canon_chars_unaligned': len(canon) - len(exact),
        'glyphs_placed': len(g2c), 'glyphs_unplaceable': len(unplaced),
        'unplaceable_gi': unplaced,
        'unplaceable_no_label_gi': no_label,
        'unplaceable_label_not_in_text_gi': [g for g in unplaced if g not in no_label],
        'nonmonotone_steps': nonmono,
        'label_agrees_with_canonical_text': agree,
        'label_disagreements': disagree,
        'label_stream': L, 'canonical_stream': canon,
    }
    return g2c, ev


def word_onsets(chars, n_words):
    """First character of each word -- exactly what forced_align.py stores."""
    out = {}
    for c in chars:
        out.setdefault(c['w'], c['t0'])
    return [out.get(w) for w in range(n_words)]


def map_stored_words(C):
    """recovered word index -> stored word index, via the source word index.

    Both paths split the SAME text on the same whitespace, so the source word
    index is the shared key and no sequence alignment is needed or wanted here.
    """
    inv = {s: i for i, s in enumerate(C['sto_src'])}
    return {r: inv[s] for r, s in enumerate(C['rec_src']) if s in inv}


def score(pred, label, pins_path, tmpdir, results):
    """Every number goes through onset_eval.py, as a subprocess, by contract."""
    pf = os.path.join(tmpdir, 'repro01_pred_%s.json' % label)
    jf = os.path.join(tmpdir, 'repro01_score_%s.json' % label)
    json.dump({str(k): round(v, 6) for k, v in sorted(pred.items())},
              open(pf, 'w'), indent=1, sort_keys=True)
    p = subprocess.run([sys.executable, ONSET_EVAL, '--pred', pf, '--pins', pins_path,
                        '--label', label, '--json', jf],
                       capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        sys.exit('onset_eval failed for %s:\n%s' % (label, p.stderr))
    print(p.stdout.rstrip())
    r = json.load(open(jf))
    r.pop('pred_source', None)          # absolute tmp path; not a result
    results[label] = r
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--fa', default=FA_JSON, help='stored forced_align.py output')
    ap.add_argument('--allow-stale-fa', action='store_true',
                    help='score a stored FA artefact older than its audio, as a '
                         'warning rather than an error (it measures the recut '
                         'offset, not the aligner)')
    ap.add_argument('--annot', default=ANNOT, help='annotator_data.json (syllable labels)')
    ap.add_argument('--pins', default=PINS)
    ap.add_argument('--cache', help='character-onset cache (written if absent)')
    ap.add_argument('--verify-cache', action='store_true',
                    help='re-run the CTC pass and assert the cache still matches')
    ap.add_argument('--out', required=True, help='result JSON')
    a = ap.parse_args()

    fa = json.load(open(a.fa))
    tmpdir = os.path.dirname(os.path.abspath(a.out))
    C, how = load_chars(fa, a.cache, a.verify_cache)
    chars = C['chars']
    print('CTC character path: %d words, %d character onsets  (%s)'
          % (len(C['words']), len(chars), how))

    slots = json.load(open(a.annot))['slots']
    pins = {int(g): float(t) for g, t in json.load(open(a.pins))}
    g2c, ev = build_mapping(chars, slots)

    print('\nmapping: %d/%d glyphs placed, %d unplaceable (%d carry no syllable '
          'label, %d carry a label the text does not contain)'
          % (ev['glyphs_placed'], ev['n_glyphs'], ev['glyphs_unplaceable'],
             len(ev['unplaceable_no_label_gi']),
             len(ev['unplaceable_label_not_in_text_gi'])))
    print('  label stream %d chars vs canonical %d; %d exact NW matches'
          % (ev['n_label_chars'], ev['n_canon_chars'], ev['nw_exact_matches']))
    print('  monotonicity violations %d; label agrees with the canonical text at '
          'the mapped position for %d/%d placed glyphs'
          % (ev['nonmonotone_steps'], ev['label_agrees_with_canonical_text'],
             ev['glyphs_placed']))
    print('  unplaceable: %s' % ' '.join(str(g) for g in ev['unplaceable_gi']))

    wrec = word_onsets(chars, len(C['words']))
    r2s = map_stored_words(C)
    if C['stored_words'] != [w['word'] for w in fa['words']]:
        sys.exit('the stored word list does not reproduce from the text; the '
                 'normalisation in forced_align.to_vocab() has changed')
    # TIMEBASE GUARD (section 9, "timebase manifests, fixed before scoring").
    # The word-string check above passes on a RECUT audio file, because the text
    # is unchanged -- so it caught nothing. The stored artefact for t03 was
    # written 2026-08-19 00:14 and the audio was recut at 20:14 the same day,
    # which shifted every one of its 32 word onsets by a median +0.239 s and
    # dropped the word rows from 23.7% to 1.3% at 150 ms. That is the entire
    # gap the plan's section 0.2 recorded as "4%, nearly useless": a stale time
    # base, not a property of forced alignment. Never score a stored artefact
    # older than the audio it claims to describe.
    a_mtime, f_mtime = os.path.getmtime(fa['audio']), os.path.getmtime(a.fa)
    ev['stored_fa_mtime'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(f_mtime))
    ev['audio_mtime'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(a_mtime))
    ev['stored_fa_predates_audio'] = a_mtime > f_mtime
    if a_mtime > f_mtime:
        msg = ('STALE TIMEBASE: %s was written %s but its audio %s was recut %s.\n'
               '  Its word onsets describe an audio file that no longer exists.\n'
               '  Re-run:  forced_align.py --audio %s --text-file <glt_text> --json %s\n'
               '  The word_*_stored rows below are NOT a measurement of forced\n'
               '  alignment; they measure the offset between two audio cuts.'
               % (a.fa, ev['stored_fa_mtime'], fa['audio'], ev['audio_mtime'],
                  fa['audio'], a.fa))
        if a.allow_stale_fa:
            print('WARNING ' + msg, file=sys.stderr)
        else:
            sys.exit(msg + '\n  Pass --allow-stale-fa to score it anyway.')
    stored_t0 = {r: fa['words'][s]['t0'] for r, s in r2s.items()}
    dw = [abs(stored_t0[w] - wrec[w]) for w in stored_t0 if wrec[w] is not None]
    ev['stored_words'] = len(fa['words'])
    ev['recovered_words'] = len(C['words'])
    ev['stored_word_list_reproduced'] = True
    ev['recovered_words_with_a_stored_counterpart'] = len(r2s)
    ev['recovered_words_without_one'] = [C['words'][r] for r in range(len(C['words'])) if r not in r2s]
    ev['max_stored_vs_recovered_word_t0_s'] = round(max(dw), 3) if dw else None

    g2w = {gi: chars[ci]['w'] for gi, ci in g2c.items()}
    results = {}
    print()

    # 1. the mapping, character level. Every glyph the rule can place.
    score({gi: chars[ci]['t0'] for gi, ci in g2c.items()}, 'char_first', a.pins, tmpdir, results)

    # 2. word level, word-initial glyphs only -- the honest anchor set.
    wf = {gi: wrec[g2w[gi]] for gi, ci in g2c.items()
          if chars[ci]['ci'] == 0 and wrec[g2w[gi]] is not None}
    score(wf, 'word_first_recovered', a.pins, tmpdir, results)

    # 3. word level as-is: every glyph inherits its word's onset. This is what
    #    "score the stored word output against the pins" can only mean, and it
    #    is the 4% of section 0.2 made into an actual score.
    score({gi: wrec[w] for gi, w in g2w.items() if wrec[w] is not None},
          'word_all_recovered', a.pins, tmpdir, results)
    score({gi: stored_t0[w] for gi, w in g2w.items() if w in stored_t0},
          'word_all_stored', a.pins, tmpdir, results)

    # 4. ORACLE. Nearest character candidate to each gold pin -- it reads the
    #    answer to choose. Upper bound only; never an achieved score.
    t0s = [c['t0'] for c in chars]
    score({gi: min(t0s, key=lambda t: abs(t - pins[gi])) for gi in pins},
          'ORACLE_nearest_char', a.pins, tmpdir, results)

    out = {'piece': 'grave-orthros-t03', 'lane': 'REPRO-01',
           'note': 't03 is TRAINING data and a burnt benchmark; these are '
                   'comparison numbers, not evidence of generalisation',
           'oracle_variants': ['ORACLE_nearest_char'],
           'ctc': {k: C[k] for k in ('model', 'audio', 'audio_sha256', 'text_sha256',
                                     'n_frames', 'sec_per_frame')},
           'n_char_onsets': len(chars), 'mapping': ev, 'scores': results}
    json.dump(out, open(a.out, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
    print('\n->', a.out)


if __name__ == '__main__':
    sys.exit(main())
