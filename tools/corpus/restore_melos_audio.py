#!/usr/bin/env python3
"""restore_melos_audio.py — put audio.wav back in the melos workdirs.

132 of the 173 melos directories had summary.json and aligned.json but no
audio.wav, so prep_hymn_annotator skipped them ("no audio.wav") and only 41
hymns ever reached the annotator. Nothing was lost: audio.wav was a
byte-identical COPY of the hymns.json row's melos_audio, ~20 MB a piece, and
every one of those 132 source files is still on disk. They were almost certainly
deleted to reclaim the 1.1 GB.

Restored as a COPY. A symlink was tried first and was a mistake: hymn_align's
melos pass runs `ffmpeg -y -i <melos_audio> ... audio.wav`, which through a
symlink reads and writes the SAME FILE and truncated
pieces/.../004_melos_fixed.wav from 53.4 s to 4.8 s. That one was rebuildable
from the tape only because texts/recut_grave-orthros.json happened to record the
span it came from at corr 1.0. These recordings are irreplaceable and several
tools in this directory write to audio.wav, so the safe move is 1.1 GB of disk
rather than an audit of every writer forever. (hymn_align now also renders to a
scratch file and moves it into place, so a stray symlink cannot do this again.)

15 of the sources are .mp3 rather than .wav; those are transcoded, because
audio_duration() reads the header with the wave module and the browser is handed
the file directly.

Usage:
  restore_melos_audio.py            # report only
  restore_melos_audio.py --write
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import wave


def rows():
    """(melos dir, dest audio.wav, source) for every dir that is missing one."""
    out = []
    for hp in sorted(glob.glob('/mnt/data/chant-corpus/workdirs/*/hymns.json')):
        wd = os.path.dirname(hp)
        try:
            hymns = json.load(open(hp))
        except Exception:
            continue
        for r in hymns:
            d = os.path.join(wd, 'melos_' + r['name'])
            dst = os.path.join(d, 'audio.wav')
            src = r.get('melos_audio')
            if not os.path.isdir(d) or os.path.exists(dst):
                continue
            if not src or not os.path.exists(src):
                out.append((d, dst, None))
                continue
            out.append((d, dst, src))
    return out


def is_wav(p):
    try:
        with wave.open(p) as w:
            w.getnframes()
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    linked = converted = missing = failed = 0
    for d, dst, src in rows():
        if src is None:
            missing += 1
            print(f'  NO SOURCE  {os.path.relpath(d, "/mnt/data/chant-corpus/workdirs")}')
            continue
        if is_wav(src):
            if a.write:
                tmp = dst + '.tmp'
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
            linked += 1
        else:
            if a.write:
                tmp = dst + '.tmp.wav'
                p = subprocess.run(
                    ['ffmpeg', '-v', 'error', '-y', '-i', src,
                     '-ac', '1', '-ar', '22050', tmp],
                    capture_output=True)
                if p.returncode or not os.path.exists(tmp):
                    failed += 1
                    print(f'  FFMPEG FAILED  {src}\n    {p.stderr.decode()[:160]}')
                    continue
                os.replace(tmp, dst)
            converted += 1
    verb = 'copied' if a.write else 'would copy'
    print(f'\n  {verb}: {linked}   transcoded from mp3: {converted}   '
          f'no source: {missing}   failed: {failed}')
    if not a.write:
        print('  (report only — pass --write to apply)')


if __name__ == '__main__':
    main()
