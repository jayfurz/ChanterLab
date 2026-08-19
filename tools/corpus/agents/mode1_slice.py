#!/usr/bin/env python3
"""slice_transcript.py adapter for dict-form pieces.json ({'segments': [...]}).

Same semantics as tools/corpus/slice_transcript.py (pad 0.35, piece-local
times, same output schema) but reads the separate_pieces.py dict format and
names outputs from each segment's own 'wav' field.

Usage: mode1_slice.py <tape_transcript.json> <pieces_dir>
"""
import json, os, sys

def main():
    tj, pdir = sys.argv[1], sys.argv[2]
    d = json.load(open(tj))
    words = [w for s in d.get('segments', []) for w in s.get('words', [])]
    pieces = json.load(open(os.path.join(pdir, 'pieces.json')))
    segs = pieces['segments'] if isinstance(pieces, dict) else pieces
    pad = 0.35                          # separate_pieces cut padding
    n = 0
    for i, p in enumerate(segs):
        stem = os.path.splitext(p.get('wav') or f"{i:03d}_{p['kind']}.wav")[0]
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
