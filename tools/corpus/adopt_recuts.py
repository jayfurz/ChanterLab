#!/usr/bin/env python3
"""adopt_recuts.py — point the pipeline at the corrected audio, gold and all.

audio_recut.py measured every hymn's cut against the tape and wrote a corrected
<piece>.recut.wav beside each original, but nothing was ever pointed at them —
so the hymns played short. The chanter noticed: "why does the hymn cut out
abruptly and slightly early?" On grave-orthros the median hymn is missing 1.83 s
off the END, worst case 4.55 s.

The reason this needs its own tool rather than just audio_recut_apply.py is the
START. A recut usually adds lead-in as well, and every timestamp measured
against that audio then shifts by add_start_s — including the chanter's gold
pins, which are [unit, seconds] against the OLD cut. Adopting the audio without
shifting them would leave 76 hand-placed pins silently a quarter-second early on
t03 and nobody would see it until they were replayed.

So: adopt the audio, shift the gold, and verify the two moved together.

Usage:
  adopt_recuts.py                 # report
  adopt_recuts.py --apply
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import wave

TEXTS = '/mnt/data/chant-corpus/texts'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..'))
DERIVED = ('audio.wav', 'voice_notes.json', 'cents_track.npy', 'rms_track.npy')
BAK = '.prerecut.bak'


def cut_from_tape(r, out, apply):
    """Cut the corrected span straight out of the tape.

    The pre-made <piece>.recut.wav files CANNOT be trusted: 123 of the 160 on
    disk do not match the length their own record claims — t26_027's says 95 s
    and the file is 14 s. Adopting them wholesale pointed four hymns at audio
    far too short for their notes and the aligner could not find a path at all
    (210 units in 14.3 s is fifteen notes a second).

    The RECORDS are sound, though: each carries the tape and the corrected span
    at a measured correlation of 0.94-0.99. So the audio is recut here rather
    than trusted, exactly as pieces/.../004_melos_fixed.wav was rebuilt, and the
    result is length-checked before anything is pointed at it.
    """
    want = r['new'][1] - r['new'][0]
    if not apply:
        return want
    tmp = out + '.tmp.wav'
    p = subprocess.run(['ffmpeg', '-v', 'error', '-y',
                        '-ss', f"{r['new'][0]:.3f}", '-to', f"{r['new'][1]:.3f}",
                        '-i', r['tape'], '-ac', '1', '-ar', '44100', tmp],
                       capture_output=True)
    if p.returncode or not os.path.exists(tmp):
        return None
    try:
        with wave.open(tmp) as w:
            got = w.getnframes() / w.getframerate()
    except Exception:
        os.remove(tmp)
        return None
    if abs(got - want) > max(0.5, 0.02 * want):
        os.remove(tmp)
        return None
    os.replace(tmp, out)
    return got


def recuts(apply):
    """workdir -> {hymn: record}, cutting each corrected span from the tape."""
    out = {}
    for f in sorted(glob.glob(os.path.join(TEXTS, 'recut_*.json'))):
        wd = os.path.basename(f)[len('recut_'):-len('.json')]
        rows = {}
        for r in json.load(open(f)):
            if not r.get('new') or not r.get('tape') or not os.path.exists(r['tape']):
                continue
            dst = r['piece'].replace('.wav', '.fixedcut.wav')
            got = cut_from_tape(r, dst, apply)
            if got is None:
                print(f"  SKIP {wd}/{r['hymn']}: could not cut a sound "
                      f"{r['new'][1] - r['new'][0]:.1f}s span from the tape")
                continue
            rows[r['hymn']] = dict(r, recut=dst)
        if rows:
            out[wd] = rows
    return out


def gold_dirs():
    """dataset dir -> (workdir, hymn) for every frozen gold set."""
    out = {}
    for d in sorted(glob.glob(os.path.join(REPO, 'datasets', '*-gold'))):
        name = os.path.basename(d)[:-len('-gold')]
        for wd in sorted(glob.glob(os.path.join(WORKDIRS, '*'))):
            w = os.path.basename(wd)
            if not name.startswith(w + '-'):
                continue
            hy = name[len(w) + 1:]
            for cand in (hy, hy + '_'):
                if os.path.isdir(os.path.join(wd, 'melos_' + cand)):
                    out[d] = (w, cand)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()

    rc = recuts(a.apply)
    golds = gold_dirs()
    n_audio = n_pins = 0
    for wd, rows in rc.items():
        hp = os.path.join(WORKDIRS, wd, 'hymns.json')
        if not os.path.isfile(hp):
            continue
        hymns = json.load(open(hp))
        changed = []
        for h in hymns:
            r = rows.get(h['name'])
            if not r or h.get('melos_audio') == r['recut']:
                continue
            changed.append((h['name'], r['add_start_s'], r['add_end_s']))
            if a.apply:
                h['melos_audio'] = r['recut']
                md = os.path.join(WORKDIRS, wd, 'melos_' + h['name'])
                for f in DERIVED:
                    p = os.path.join(md, f)
                    if os.path.exists(p):
                        os.remove(p)
        if not changed:
            continue
        n_audio += len(changed)
        add_end = [c[2] for c in changed]
        print(f'  {wd}: {len(changed)} hymns -> recut audio '
              f'(median +{sorted(add_end)[len(add_end)//2]:.2f}s at the end)')
        if a.apply:
            if not os.path.exists(hp + BAK):
                shutil.copy2(hp, hp + BAK)
            json.dump(hymns, open(hp, 'w'), ensure_ascii=False, indent=1)

    # the gold pins move with the audio they were placed against
    for d, (wd, hy) in golds.items():
        r = rc.get(wd, {}).get(hy)
        if not r or not r['add_start_s']:
            continue
        shift = r['add_start_s']
        for fn, key in (('pins.json', None), ('chanter_notes.json', 't')):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            data = json.load(open(p))
            moved = 0
            if key is None:
                for row in data:
                    if isinstance(row, list) and len(row) > 1 \
                       and isinstance(row[1], (int, float)):
                        row[1] = round(row[1] + shift, 3)
                        moved += 1
            else:
                for row in data:
                    if isinstance(row, dict) and isinstance(row.get(key), (int, float)):
                        row[key] = round(row[key] + shift, 3)
                        moved += 1
            n_pins += moved
            print(f'  {os.path.basename(d)}/{fn}: {moved} timestamps +{shift:.2f}s')
            if a.apply and moved:
                if not os.path.exists(p + BAK):
                    shutil.copy2(p, p + BAK)
                json.dump(data, open(p, 'w'), ensure_ascii=False, indent=1)

    print(f'\n  {n_audio} hymns repointed, {n_pins} gold timestamps shifted'
          + ('' if a.apply else '   (report only — pass --apply)'))


if __name__ == '__main__':
    main()
