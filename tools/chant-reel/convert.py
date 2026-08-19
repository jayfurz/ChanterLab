#!/usr/bin/env python3
"""whisper json -> whisper_words.json [(word, t0, t1)] ; prefers whisper_out (small) over whisper_fast (base)"""
import json, os, sys

src = None
for d in (sys.argv[1:] or ['whisper_out', 'whisper_fast']):
    p = os.path.join(d, 'raw_mono.json')
    if os.path.exists(p):
        src = p; break
if not src:
    raise SystemExit('no whisper json yet')
j = json.load(open(src))
words = []
for seg in j['segments']:
    for w in seg.get('words', []):
        words.append((w['word'].strip(), round(w['start'], 2), round(w['end'], 2)))
json.dump(words, open('whisper_words.json', 'w'))
print(f"{src}: {len(words)} words")
print("text:", j['text'][:400])
