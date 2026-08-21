#!/usr/bin/env python3
"""realign_fa.py -- re-run forced alignment on the CURRENT audio, keeping the
identified text.

WHY. The stored artefacts under texts/forced_align/ carry no audio checksum, so
nothing detected that RESEP recut the audio underneath them. Audited 2026-08-20:

    173 artefacts
     13  fresh, with word timings
     59  STALE -- the audio was recut after the alignment was written
    101  identification-only records (tape_solve): glt_text but no word timings

t03's stale artefact was shifted a median +0.239 s, which scored 1.3% of notes
within 150 ms and entered NEURAL-CHANT.md 0.2 as "forced alignment is nearly
useless, 4%". Re-aligned it scores 23.7%, and its character path 55.3%. So the
FA layer the whole onset pipeline rests on exists, in usable form, for 13 of 173
tracks. This fixes that.

WHAT IT DELIBERATELY DOES NOT DO. forced_align_batch.py also re-runs
IDENTIFICATION -- it scores every candidate text by CTC likelihood and picks
one. Re-running it here could silently reassign a hymn, and identification is
only ~83% right at the 4.5/tok gate (see forced_align_batch.py). This script
keeps each record's existing glt_text and replaces ONLY the timings, so a
re-alignment can never change what a track is believed to be.

PROVENANCE is written this time: audio sha256, audio mtime, the aligning device,
and when. An artefact whose producer is unidentifiable is a correctness hazard
the moment the audio moves again -- which is exactly what happened.

Usage:
  realign_fa.py --device cuda            # all stale/timing-less records
  realign_fa.py --device cuda --all      # every record, including fresh ones
  realign_fa.py --dry-run
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FA_DIR = '/mnt/data/chant-corpus/texts/forced_align'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'


def sha256(path, cap=64 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def audio_for(d):
    """The audio this record describes, preferring the stored path."""
    a = d.get('audio')
    if a and os.path.exists(a):
        return a
    p = os.path.join(WORKDIRS, d.get('workdir', ''),
                     'melos_%s' % d.get('hymn', ''), 'audio.wav')
    return p if os.path.exists(p) else None


def needs_work(d, path, audio):
    if not d.get('words'):
        return 'no word timings'
    if os.path.getmtime(audio) > os.path.getmtime(path):
        return 'audio recut after alignment'
    if d.get('audio_sha256') and d['audio_sha256'] != sha256(audio):
        return 'audio sha256 changed'
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--all', action='store_true', help='realign fresh ones too')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int)
    a = ap.parse_args()

    jobs = []
    for path in sorted(glob.glob(os.path.join(FA_DIR, '*.json'))):
        d = json.load(open(path))
        if not d.get('glt_text'):
            print('skip %s: no glt_text' % os.path.basename(path))
            continue
        audio = audio_for(d)
        if not audio:
            print('skip %s: no audio' % os.path.basename(path))
            continue
        why = needs_work(d, path, audio) or ('forced (--all)' if a.all else None)
        if why:
            jobs.append((path, d, audio, why))
    if a.limit:
        jobs = jobs[:a.limit]
    print('%d records to realign' % len(jobs))
    if a.dry_run:
        for p, _, _, w in jobs[:20]:
            print('   %-38s %s' % (os.path.basename(p), w))
        return 0

    from forced_align import align                      # noqa: E402
    ok = fail = 0
    for i, (path, d, audio, why) in enumerate(jobs, 1):
        t0 = time.time()
        try:
            words = align(audio, d['glt_text'], device=a.device)
        except Exception as e:
            fail += 1
            print('[%3d/%d] FAIL %-34s %s' % (i, len(jobs), d.get('hymn'), e))
            continue
        d['words'] = words
        d['audio'] = audio
        d['audio_sha256'] = sha256(audio)
        d['audio_mtime'] = time.strftime('%Y-%m-%d %H:%M',
                                         time.localtime(os.path.getmtime(audio)))
        d['aligned_at'] = time.strftime('%Y-%m-%d %H:%M')
        d['aligned_device'] = a.device
        d['realign_reason'] = why
        tmp = path + '.tmp'
        json.dump(d, open(tmp, 'w'), ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        ok += 1
        print('[%3d/%d] %-34s %3d words  %.1fs  (%s)'
              % (i, len(jobs), os.path.basename(path), len(words),
                 time.time() - t0, why))
    print('\nrealigned %d, failed %d' % (ok, fail))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
