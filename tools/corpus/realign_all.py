#!/usr/bin/env python3
"""realign_all.py — re-run the melos aligner over every hymn.

aligned.json holds the aligner's output indexed by UNIT, so any change to how
the score is segmented invalidates it: the times stop landing on the glyphs they
were computed for. The 2026-08-19 rulings (the kentimata split, the silenced
tempo signs and antikenoma, the psifiston/omalon separation) moved 109040 units
to 115038, so every stored alignment had to be recomputed rather than migrated —
an index can be moved, a time cannot.

Each hymn is a separate process because cmd_melos is a script-style entry point
and one bad hymn should not take the batch with it.

Usage:
  realign_all.py [--workdir NAME] [--force] [--jobs N]

--force also drops voice_notes.json / cents_track.npy so the pitch tracking is
redone; without it those are reused, which is much faster and is correct as long
as audio.wav has not changed.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
DERIVED = ('voice_notes.json', 'cents_track.npy', 'rms_track.npy')


def jobs_for(only):
    out = []
    for hp in sorted(glob.glob(os.path.join(WORKDIRS, '*', 'hymns.json'))):
        wd = os.path.dirname(hp)
        if only and os.path.basename(wd) != only:
            continue
        for h in json.load(open(hp)):
            mdir = os.path.join(wd, 'melos_' + h['name'])
            if os.path.isdir(mdir) and os.path.exists(os.path.join(mdir, 'audio.wav')):
                out.append((wd, hp, h['name'], mdir))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--jobs', type=int, default=1)
    a = ap.parse_args()

    todo = jobs_for(a.workdir)
    print(f'{len(todo)} hymns to realign', flush=True)
    ok = fail = 0
    t0 = time.time()
    running = []

    def reap(block):
        nonlocal ok, fail
        while running and (block or any(p.poll() is not None for _, p in running)):
            for i, (name, p) in enumerate(running):
                if p.poll() is None:
                    continue
                out = p.communicate()[0].decode(errors='replace').strip().splitlines()
                if p.returncode == 0:
                    ok += 1
                    print(f'  OK   {name}: {out[-1][:120] if out else ""}', flush=True)
                else:
                    fail += 1
                    tail = out[-1][:160] if out else 'no output'
                    print(f'  FAIL {name}: {tail}', flush=True)
                running.pop(i)
                break
            else:
                if block:
                    time.sleep(0.5)

    for wd, hp, name, mdir in todo:
        if a.force:
            for f in DERIVED:
                p = os.path.join(mdir, f)
                if os.path.exists(p):
                    os.remove(p)
        while len(running) >= max(1, a.jobs):
            reap(block=True)
        running.append((f'{os.path.basename(wd)}/{name}', subprocess.Popen(
            [sys.executable, os.path.join(HERE, 'hymn_align.py'), 'melos', wd,
             '--hymns', hp, '--hymn', name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)))
        reap(block=False)
    while running:
        reap(block=True)
    print(f'\n{ok} realigned, {fail} failed, {(time.time()-t0)/60:.1f} min', flush=True)


if __name__ == '__main__':
    main()
