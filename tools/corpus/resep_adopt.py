#!/usr/bin/env python3
"""resep_adopt.py — point hymns.json at the segment-edge cuts.

resep_recut.py writes <piece>.recut.wav beside each original and changes nothing
else, so the improvement is inert: the pipeline still reads the old file. This
adopts the new cut as the hymn's melos audio and clears the derived tracks so
the next aligner run rebuilds from it.

Kept: chanter_pins.json and chanter_flags.json — chanter data is never deleted
by a tool. Removed: audio.wav, voice_notes.json, cents_track.npy, rms_track.npy,
all regenerable by hymn_align.py melos.

TIME BASE. A segment-edge cut starts where the singing starts, which is not
where the old file started, so every timestamp measured against the old audio
shifts. The two gold datasets are frozen separately with their own audio
checksums and are not silently affected — but a hymn carrying pins must have
them shifted by the recorded delta before its gold is re-frozen. The delta is
written to each row as recut_shift_s.

Usage:  resep_adopt.py [--workdir DIR] [--apply]
"""
import argparse
import glob
import json
import os
import shutil

DERIVED = ('audio.wav', 'voice_notes.json', 'cents_track.npy', 'rms_track.npy')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    files = ([f'/mnt/data/chant-corpus/texts/resepcut_'
              f'{os.path.basename(a.workdir.rstrip("/"))}.json'] if a.workdir
             else sorted(glob.glob('/mnt/data/chant-corpus/texts/resepcut_*.json')))
    tot_p = tot_r = 0
    for rf in files:
        if not os.path.exists(rf):
            continue
        rows = json.load(open(rf))
        if not rows:
            continue
        wd = rows[0]['workdir']
        hp = f'/mnt/data/chant-corpus/workdirs/{wd}/hymns.json'
        hy = json.load(open(hp))
        idx = {r['hymn']: r for r in rows}
        n_p = n_r = 0
        for h in hy:
            r = idx.get(h['name'])
            if not r:
                continue
            dst = r['piece'].replace('.wav', '.recut.wav')
            if not os.path.exists(dst):
                continue
            if h.get('melos_audio') != dst:
                n_p += 1
                if a.apply:
                    h.setdefault('melos_audio_orig', h.get('melos_audio'))
                    h['melos_audio'] = dst
                    h['recut_shift_s'] = round(r['new'][0] - r['old'][0], 3)
                    h['recut_source'] = 'segment_edges'
                    h['recut_lpt'] = r['lpt']
            md = f'/mnt/data/chant-corpus/workdirs/{wd}/melos_{h["name"]}'
            for f in DERIVED:
                p = os.path.join(md, f)
                if os.path.exists(p):
                    n_r += 1
                    if a.apply:
                        os.remove(p)
        if a.apply and n_p:
            shutil.copy(hp, hp + '.pre-resep')
            json.dump(hy, open(hp, 'w'), indent=1, ensure_ascii=False)
        tot_p += n_p
        tot_r += n_r
        print('%-18s %2d hymns repointed, %3d derived files %s'
              % (wd, n_p, n_r, 'removed' if a.apply else 'would be removed'))
    print(f'\n{tot_p} hymns repointed at segment-edge cuts, {tot_r} derived files'
          f'{"" if a.apply else "   (dry run; pass --apply)"}')
    if a.apply:
        print('  backups: hymns.json.pre-resep per workdir')
        print('  re-run hymn_align.py melos to rebuild the tracks')


if __name__ == '__main__':
    main()
