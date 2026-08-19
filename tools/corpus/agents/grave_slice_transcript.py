#!/usr/bin/env python3
"""Slice a whole-tape whisper JSON into per-piece transcripts for the
dict-format pieces.json (separate_pieces.py 'segments' layout with 'wav'
fields), mirroring tools/corpus/slice_transcript.py.

Usage: grave_slice_transcript.py <tape_transcript.json> <pieces_dir>
"""
import json, os, sys

def main():
    tj, pdir = sys.argv[1], sys.argv[2]
    d = json.load(open(tj))
    words = [w for s in d.get('segments', []) for w in s.get('words', [])]
    pj = json.load(open(os.path.join(pdir, 'pieces.json')))
    segs = pj['segments'] if isinstance(pj, dict) else pj
    pad = float(pj.get('params', {}).get('pad', 0.35)) if isinstance(pj, dict) else 0.35
    n = 0
    for p in segs:
        wav = p.get('wav')
        if not wav or not os.path.exists(os.path.join(pdir, wav)):
            continue
        stem = os.path.splitext(wav)[0]
        off = max(0.0, p['t0'] - pad)   # cut_pieces clamps the padded start at 0
        ws = [dict(w, start=round(w['start'] - off, 2),
                   end=round(w['end'] - off, 2))
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
