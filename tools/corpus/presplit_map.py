#!/usr/bin/env python3
"""presplit_map.py — turn an already-split folder into labelled spans.

Three of the sixteen target recordings were never single tapes: Mode 2 Vespers,
Plagal 1st Vespers and Plagal 1st Orthros arrive as folders of per-hymn files.
Chanter: "i had the plagal one ones in a folder and there were a bunch of
smaller cuts rather than one long vespers and one long orthros cut." They need
mapping, not cutting, and cutting them by hand would redo work already done.

Two sources of lane, in order of trust:

  1. the filename, when the chanter wrote it there -- Mode 2 Vespers files are
     named "(ΜΕΛΟΣ)" and "(ΠΑΡΑΛΛΑΓΗ)", which is authoritative
  2. the degree-token rate, otherwise -- Plagal 1st files are named by
     timestamp and carry no label, so the lane is recovered acoustically at
     0.43 deg/s (96% on the gold tape, see PARALLAGI-PAIRING.md)

Then the pairing prior checks the result: parallagi should alternate with melos.
A folder that does not alternate has a mislabelled file, and this says so rather
than writing a clean-looking answer.

Usage:  presplit_map.py --dir DIR --key mode2 [--limit-sec 25]
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEXTS = '/mnt/data/chant-corpus/texts'
AUDIO_EXT = ('.mp3', '.m4a', '.wav', '.flac')
THRESH = 0.43           # deg/s, the split measured on the gold tape


TS_RX = re.compile(r'(\d{1,2})\.(\d{2})\s*([AP])M(?:\s+(\d+))?', re.I)


def order_key(name):
    """Recording order for the Plagal 1st folders.

    Their names carry a clock time and an optional index: "... 4.58 AM 0.m4a",
    "... 5.02 AM.m4a", "... 5.02 AM 1.m4a". Plain sorting breaks this twice --
    a space sorts before a dot, so "5.02 AM 1" lands ahead of "5.02 AM", and
    "5.09" would follow "5.10". File mtimes cannot rescue it either: every file
    in the folder carries the same stamp. So parse the clock out of the name.
    """
    m = TS_RX.search(name)
    if not m:
        return (1, name)
    h, mi, ap, idx = int(m.group(1)), int(m.group(2)), m.group(3).upper(), m.group(4)
    if h == 12:
        h = 0
    if ap == 'P':
        h += 12
    return (0, h, mi, -1 if idx is None else int(idx), name)


def dur_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration', '-of',
                        'default=nw=1:nk=1', path],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return 0.0


def lane_from_name(n):
    if 'ΠΑΡΑΛΛΑΓΗ' in n or 'ΠΑΡΑΛΛΑΓΉ' in n:
        return 'parallagi'
    if 'ΜΕΛΟΣ' in n or 'ΜΈΛΟΣ' in n:
        return 'melos'
    return None


def clean_label(n):
    t = os.path.splitext(n)[0]
    t = re.sub(r'^\d+\.*\s*', '', t)                  # leading track number
    t = re.sub(r'\((?:ΜΕΛΟΣ|ΠΑΡΑΛΛΑΓΗ)\)', '', t)      # the lane marker
    return re.sub(r'\s+', ' ', t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--limit-sec', type=float, default=25.0)
    a = ap.parse_args()

    files = sorted((f for f in os.listdir(a.dir)
                    if f.lower().endswith(AUDIO_EXT)), key=order_key)
    if not files:
        raise SystemExit(f'no audio in {a.dir}')
    named = [lane_from_name(f) for f in files]
    need_audio = any(x is None for x in named)

    detect = None
    if need_audio:
        import numpy as np
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        from degree_tokens import degrees_in, MODEL, SR
        dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        proc = Wav2Vec2Processor.from_pretrained(MODEL)
        model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(dev).eval()

        def detect(path, dur):
            end = min(a.limit_sec, dur) if a.limit_sec else dur
            p = subprocess.run(
                ['ffmpeg', '-v', 'quiet', '-t', str(end), '-i', path,
                 '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            x = np.frombuffer(p.stdout, dtype=np.float32)
            if x.size < SR:
                return 0.0
            with torch.inference_mode():
                lg = model(torch.from_numpy(x.copy()).unsqueeze(0).to(dev)).logits
            d = proc.batch_decode(torch.argmax(lg, dim=-1))[0]
            return len(degrees_in(d)) / max(end, 0.1)

    out = []
    for f, lane in zip(files, named):
        path = os.path.join(a.dir, f)
        dur = dur_of(path)
        rate = None
        src = 'filename'
        if lane is None and detect:
            rate = round(detect(path, dur), 3)
            lane = 'parallagi' if rate > THRESH else 'melos'
            src = 'degree-rate'
        out.append({'file': path, 'name': f, 'dur': dur, 'lane': lane,
                    'lane_from': src, 'deg_per_s': rate,
                    'label': clean_label(f)})
        print('  %-52s %6.1fs %-9s %s'
              % (f[:52], dur, lane or '?',
                 ('%.2f deg/s' % rate) if rate is not None else ''), flush=True)

    # pairing check
    bad = []
    for i, r in enumerate(out):
        if r['lane'] == 'melos':
            if i == 0 or out[i - 1]['lane'] != 'parallagi':
                bad.append((i, r['name'], 'melos not preceded by parallagi'))
    npar = sum(1 for r in out if r['lane'] == 'parallagi')
    nmel = sum(1 for r in out if r['lane'] == 'melos')
    print(f'\n{len(out)} files: {npar} parallagi, {nmel} melos')
    if bad:
        print(f'{len(bad)} pairing exception(s) — inspect before trusting:')
        for i, n, why in bad[:12]:
            print(f'    #{i+1:02d} {n[:48]}  {why}')
    else:
        print('pairing holds: every melos follows a parallagi')

    p = f'{TEXTS}/presplit_{a.key}.json'
    json.dump({'key': a.key, 'dir': a.dir, 'threshold_deg_s': THRESH,
               'files': out, 'pairing_exceptions': bad},
              open(p, 'w'), indent=1, ensure_ascii=False)
    print(f'-> {p}')


if __name__ == '__main__':
    main()
