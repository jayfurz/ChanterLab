#!/usr/bin/env python3
"""slice_transcript.py adapted for the dict-format pieces.json
(top-level {audio, transcript, params, segments:[{t0,t1,kind,wav,...}]}).
Same slicing semantics: piece-local times, cut padding as in separate_pieces
(t0_cut = max(0, t0 - pad)).

Usage: pl2_slice_transcript.py <tape_transcript.json> <pieces_dir>
"""
import json, os, sys

def main():
    tj, pdir = sys.argv[1], sys.argv[2]
    d = json.load(open(tj))
    words = [w for s in d.get('segments', []) for w in s.get('words', [])]
    doc = json.load(open(os.path.join(pdir, 'pieces.json')))
    segs = doc['segments'] if isinstance(doc, dict) else doc
    pad = doc.get('params', {}).get('pad', 0.35) if isinstance(doc, dict) else 0.35
    n = 0
    for p in segs:
        wav = p.get('wav') or ''
        stem = os.path.splitext(wav)[0]
        if not stem or not os.path.exists(os.path.join(pdir, wav)):
            continue
        t0c = max(0.0, p['t0'] - pad)
        ws = [dict(w, start=round(w['start'] - t0c, 2),
                   end=round(w['end'] - t0c, 2))
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
