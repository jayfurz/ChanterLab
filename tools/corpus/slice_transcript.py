#!/usr/bin/env python3
"""Slice a whole-tape whisper JSON into per-piece transcripts matching the
cut wavs from separate_pieces.py (times shifted to piece-local).

Usage: slice_transcript.py <tape_transcript.json> <pieces_dir>
  pieces_dir holds pieces.json + NNN_<kind>.wav; writes NNN_<kind>.json
"""
import json, os, sys

def main():
    tj, pdir = sys.argv[1], sys.argv[2]
    d = json.load(open(tj))
    words = [w for s in d.get('segments', []) for w in s.get('words', [])]
    pj = json.load(open(os.path.join(pdir, 'pieces.json')))
    pieces = pj['segments'] if isinstance(pj, dict) else pj
    pad = 0.35                          # separate_pieces cut padding
    n = 0
    for i, p in enumerate(pieces):
        stem = f"{i + 1:03d}_{p['kind']}"
        if not os.path.exists(os.path.join(pdir, stem + '.wav')):
            continue
        ws = [dict(w, start=round(w['start'] - p['t0'] + pad, 2),
                   end=round(w['end'] - p['t0'] + pad, 2))
              for w in words if p['t0'] <= w['start'] < p['t1']]
        json.dump({'text': ' '.join(w['word'] for w in ws),
                   'segments': [{'start': ws[0]['start'] if ws else 0,
                                 'end': ws[-1]['end'] if ws else 0,
                                 'text': ' '.join(w['word'] for w in ws),
                                 'words': ws}] if ws else []},
                  open(os.path.join(pdir, stem + '.json'), 'w'),
                  ensure_ascii=False)
        n += 1
    print(f"{n} piece transcripts -> {pdir}")

if __name__ == '__main__':
    main()
