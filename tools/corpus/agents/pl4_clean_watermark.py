#!/usr/bin/env python3
"""pl4: strip Whisper watermark hallucinations ('Υπότιτλοι', 'AUTHORWAVE')
from sliced piece transcripts NNN_*.json in a pieces dir (in place).

Usage: pl4_clean_watermark.py <pieces_dir>
"""
import json, glob, os, re, sys, unicodedata

def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^α-ωa-z]', '', s.replace('ς', 'σ'))

BAD = {'υποτιτλοι', 'authorwave', 'υποτιτλοιauthorwave'}

def main():
    pdir = sys.argv[1]
    n = 0
    for f in sorted(glob.glob(os.path.join(pdir, '[0-9]*_*.json'))):
        d = json.load(open(f))
        segs = []
        for s in d.get('segments', []):
            ws = [w for w in s.get('words', []) if norm(w['word']) not in BAD]
            if not ws:
                continue
            segs.append({'start': ws[0]['start'], 'end': ws[-1]['end'],
                         'text': ' '.join(w['word'] for w in ws), 'words': ws})
        d['segments'] = segs
        d['text'] = ' '.join(w['word'] for s in segs for w in s['words'])
        json.dump(d, open(f, 'w'), ensure_ascii=False)
        n += 1
    print(f'cleaned {n} transcripts in {pdir}')

if __name__ == '__main__':
    main()
