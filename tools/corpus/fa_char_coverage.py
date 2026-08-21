#!/usr/bin/env python3
"""fa_char_coverage.py -- how much onset evidence is in the CTC path, really?

forced_align.py aligns every CHARACTER and only aggregates spans into words at
the end. The stored per-hymn results keep word onsets and throw the character
grid away -- which made an earlier draft of NEURAL-CHANT.md claim a "42%
structural ceiling" for forced alignment from the 32 stored words. That was an
artefact of post-processing, not a property of CTC.

Measured on t03 (2026-08-20), 33 words / 179 aligned characters:

    distinct character-level onsets in the CTC path      179
    gold pins with SOME character onset within 0.05 s   46/76  (61%)
    gold pins with SOME character onset within 0.10 s   62/76  (82%)
    gold pins with SOME word onset within 0.05 s         3/76  ( 4%)  <- STALE

(An earlier run reported 211/47/62% because it counted the 32 "|" word
separators as character onsets. They are not sung characters.)

THE WORD ROW IS A STALE TIMEBASE. WITHDRAWN 2026-08-20. The character rows are
computed here, in-process, against the current audio, and they stand. The word
row is read out of the STORED forced_align artefact (see load_stored_words
below), which for t03 was written 19 Aug 00:14 while its audio was recut at
20:14 -- every word onset in it is shifted a median +0.239 s. Re-aligned on the
current audio the same measurement gives 20/76 (26%) at 0.05 s, not 3/76 (4%).
That 4% reached NEURAL-CHANT.md 0.2 as "forced alignment is nearly useless",
which was wrong. This script now refuses to print the word row from an artefact
older than its audio. See tools/corpus/fa_eval.py for the full accounting.

Two things follow, and the second matters more.

  * The word-level output is a WEAK onset source, not a useless one, and it is
    weak for a structural reason: a word onset times the first note of its word
    and says nothing about the rest. Scored per glyph it is 26.3% within 150 ms
    against the character path's 55.3% (fa_eval.py).
  * The character path already holds evidence for 61% of notes at 50 ms.

But 179 candidates for 76 notes is ~2.4 per note, so this is an ORACLE number:
it says the information is present, not that it can be picked out. What FA
leaves is a SELECTION problem, not an availability problem. Read it as an upper
bound on what any FA-derived anchor set could give, never as an achieved score.

Usage: fa_char_coverage.py
"""
import json, sys, unicodedata, re, subprocess, os, time
import numpy as np, torch, torchaudio.functional as F
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
M='jonatasgrosman/wav2vec2-large-xlsr-53-greek'
proc=Wav2Vec2Processor.from_pretrained(M); model=Wav2Vec2ForCTC.from_pretrained(M).eval()
vocab=proc.tokenizer.get_vocab()
d=json.load(open('/mnt/data/chant-corpus/texts/forced_align/grave-orthros__t03_.json'))
text=d['glt_text']; audio=d['audio']
raw=subprocess.run(['ffmpeg','-v','error','-i',audio,'-ac','1','-ar','16000','-f','s16le','-'],
                   capture_output=True).stdout
a=np.frombuffer(raw,dtype=np.int16).astype('float32')/32768.
wav=torch.from_numpy(a.copy()).unsqueeze(0)
with torch.inference_mode():
    logp=torch.log_softmax(model(wav).logits,dim=-1)
t=unicodedata.normalize('NFD',text).upper()
t=''.join(c for c in t if unicodedata.category(c)!='Mn').replace('ς','Σ')
words=[''.join(c for c in w if c in vocab) for w in re.split(r'\s+',t)]
words=[w for w in words if w]
sep=vocab.get('|'); ids=[]; charpos=[]
for wi,w in enumerate(words):
    for ci,c in enumerate(w):
        charpos.append((wi,ci)); ids.append(vocab[c])
    if sep is not None and wi+1<len(words): charpos.append(None); ids.append(sep)
path,_=F.forced_align(logp, torch.tensor([ids],dtype=torch.int32), blank=vocab.get('<pad>',0))
path=path[0].tolist(); ratio=wav.shape[1]/logp.shape[1]/16000
first={}; ti=-1; prev=vocab.get('<pad>',0)
for fi,tok in enumerate(path):
    if tok==prev or tok==vocab.get('<pad>',0):
        prev=tok; continue
    ti+=1; first.setdefault(ti,fi); prev=tok
# charpos[i] is None for the '|' word separators appended between words. A
# separator is not a sung character and its CTC onset is not note evidence;
# counting them inflated an earlier run from 179 onsets to 211.
onsets=sorted({round(first[i]*ratio,3) for i in first
               if i < len(charpos) and charpos[i] is not None})
print('t03 canonical text: %d words, %d aligned characters'%(len(words), sum(len(w) for w in words)))
print('DISTINCT character-level CTC onsets: %d'%len(onsets))
pins=[p[1] for p in json.load(open('datasets/grave-orthros-t03-gold/pins.json'))]
tol=0.05
cov=sum(1 for p in pins if any(abs(o-p)<=tol for o in onsets))
print('\nof the 76 gold pins, how many have SOME character onset within:')
for tol in (0.05,0.10,0.15):
    c=sum(1 for p in pins if any(abs(o-p)<=tol for o in onsets))
    print('   %.2f s : %2d/76  (%3.0f%%)'%(tol,c,100*c/76))
# The word row comes from the STORED artefact, not from the pass above. If that
# artefact predates the audio it describes, its onsets are shifted and the row is
# a measurement of the recut, not of the aligner -- which is how "4%" got into
# NEURAL-CHANT.md 0.2. Refuse rather than print a misleading number.
FA_PATH='/mnt/data/chant-corpus/texts/forced_align/grave-orthros__t03_.json'
if os.path.getmtime(audio) > os.path.getmtime(FA_PATH):
    print('\n   word-level: WITHHELD. %s was written %s but its audio was recut'
          ' %s.\n   Its word onsets describe an audio file that no longer exists.'
          '\n   Re-run: forced_align.py --audio %s --text-file <glt_text> --json %s'
          % (FA_PATH,
             time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(FA_PATH))),
             time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(audio))),
             audio, FA_PATH))
else:
    w0=[w['t0'] for w in d['words']]
    for tol in (0.05,0.10,0.15):
        c=sum(1 for p in pins if any(abs(o-p)<=tol for o in w0))
        print('   word-level, %.2f s : %2d/76  (%3.0f%%)'%(tol,c,100*c/76))
