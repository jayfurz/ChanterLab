#!/usr/bin/env python3
"""audio_recut_apply.py — adopt the re-cut audio as the pipeline's melos source.

audio_recut.py writes <piece>.recut.wav beside each original and changes
nothing else, so nothing downstream sees it. This points hymns.json at the
re-cut files and clears the derived tracks so the next aligner run rebuilds
them from the corrected audio.

What it removes per hymn (all regenerable by hymn_align.py melos):
    melos_<name>/audio.wav, voice_notes.json, cents_track.npy, rms_track.npy

What it keeps: chanter_pins.json, chanter_flags.json, aligned.json,
summary.json — the aligner overwrites the last two itself, and the first two are
chanter data that must never be deleted by a tool.

CAUTION about the time base. With --move-start the re-cut also trims the lead,
which shifts every timestamp measured against that audio. The two gold datasets
are frozen separately with their own audio checksums
(datasets/grave-orthros-t03-gold, datasets/eothinon-11-workdir) so they are not
silently corrupted — but their pins refer to the OLD cut. Re-freezing gold
against the new audio means shifting each pin by that hymn's add_start_s, which
is recorded per hymn in texts/recut_<workdir>.json.

Usage:  audio_recut_apply.py --workdir DIR [--apply]
"""
import argparse
import json
import os
import shutil

CORPUS = '/mnt/data/chant-corpus'
DERIVED = ('audio.wav', 'voice_notes.json', 'cents_track.npy', 'rms_track.npy')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()

    name = os.path.basename(a.workdir.rstrip('/'))
    rf = os.path.join(CORPUS, 'texts', f'recut_{name}.json')
    if not os.path.exists(rf):
        raise SystemExit(f'no re-cut report for {name}; run audio_recut.py first')
    recut = {r['hymn']: r for r in json.load(open(rf))}
    hp = os.path.join(a.workdir, 'hymns.json')
    hy = json.load(open(hp))

    n_pt = n_rm = 0
    for h in hy:
        r = recut.get(h['name'])
        if not r:
            continue
        dst = r['piece'].replace('.wav', '.recut.wav')
        if not os.path.exists(dst):
            continue
        if h.get('melos_audio') != dst:
            n_pt += 1
            if a.apply:
                h['melos_audio_orig'] = h.get('melos_audio')
                h['melos_audio'] = dst
                h['recut'] = {'add_start_s': r['add_start_s'],
                              'add_end_s': r['add_end_s'], 'corr': r['corr']}
        md = os.path.join(a.workdir, 'melos_' + h['name'])
        for f in DERIVED:
            p = os.path.join(md, f)
            if os.path.exists(p):
                n_rm += 1
                if a.apply:
                    os.remove(p)
    if a.apply:
        shutil.copy(hp, hp + '.pre-recut')
        json.dump(hy, open(hp, 'w'), indent=1, ensure_ascii=False)
    print(f'{name}: {n_pt} hymns repointed, {n_rm} derived files '
          f'{"removed" if a.apply else "would be removed"}'
          f'{"" if a.apply else "   (dry run; pass --apply)"}')
    if a.apply:
        print(f'  hymns.json backed up to {hp}.pre-recut')
        print('  now re-run: hymn_align.py melos <wd> --hymns <wd>/hymns.json '
              '--hymn <name> --em   (audio.wav and the tracks rebuild automatically)')


if __name__ == '__main__':
    main()
