#!/usr/bin/env python3
"""Adapter: run slice_transcript.py on a dict-format pieces.json
(top-level {"segments": [...]} with per-segment "wav" names, 1-indexed)
by staging the list-format layout slice_transcript expects, then copying
the per-piece transcripts back next to the real wavs.

Usage: slice_adapter.py <tape_transcript.json> <pieces_dir> <staging_dir>
"""
import json, os, shutil, subprocess, sys

def main():
    tj, pdir, stage = sys.argv[1], sys.argv[2], sys.argv[3]
    tools = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(os.path.join(pdir, 'pieces.json')))
    segs = d['segments'] if isinstance(d, dict) else d
    os.makedirs(stage, exist_ok=True)
    mapping = []                       # (staged stem, real stem)
    for i, s in enumerate(segs):
        wav = s.get('wav')
        if not wav:
            continue
        real = os.path.join(pdir, wav)
        stem = f"{i:03d}_{s['kind']}"
        link = os.path.join(stage, stem + '.wav')
        if os.path.lexists(link):
            os.unlink(link)
        if os.path.exists(real):
            os.symlink(real, link)
            mapping.append((stem, os.path.splitext(wav)[0]))
    json.dump(segs, open(os.path.join(stage, 'pieces.json'), 'w'),
              ensure_ascii=False)
    r = subprocess.run([sys.executable,
                        os.path.join(tools, 'slice_transcript.py'), tj, stage])
    if r.returncode != 0:
        sys.exit(r.returncode)
    n = 0
    for stem, real_stem in mapping:
        src = os.path.join(stage, stem + '.json')
        if os.path.exists(src):
            shutil.copy(src, os.path.join(pdir, real_stem + '.json'))
            n += 1
    print(f"copied {n} transcripts -> {pdir}")

if __name__ == '__main__':
    main()
