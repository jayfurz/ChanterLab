#!/usr/bin/env python3
"""prep_melos_piece.py — build a hymn's MELOS annotator piece from its cut.

The chanter creates spans in the book faster than any batch runs: a new row
has a tape cut but no piece, so the book's "Fix onsets" sits greyed out.
This is the whole melos chain for one hymn — cut the audio from the tape at
his saved span, align, prep — callable on demand (the book's build button
runs it in a subprocess).

Usage: prep_melos_piece.py --workdir /mnt/data/chant-corpus/workdirs/mode2 --hymn NAME
"""
import argparse, json, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prep_hymn_annotator as P
import hymn_align

TEXTS = '/mnt/data/chant-corpus/texts'
BOOKCUTS = '/mnt/data/chant-corpus/pieces/bookcuts'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--hymn', required=True)
    a = ap.parse_args()
    wd = a.workdir.rstrip('/')
    wd_base = os.path.basename(wd)
    hj = os.path.join(wd, 'hymns.json')
    rows = json.load(open(hj))
    r = next((x for x in rows if x['name'] == a.hymn), None)
    if r is None:
        sys.exit(f'no row {a.hymn!r} in {wd_base}')
    cf = f'{TEXTS}/cuts_{wd_base}.json'
    cuts = {c['hymn']: c for c in json.load(open(cf))['cuts']} \
        if os.path.exists(cf) else {}
    c = cuts.get(a.hymn)
    if not c or c.get('t0') is None:
        sys.exit(f'{a.hymn}: no saved melos cut')
    rc = f'{TEXTS}/recut_{wd_base}.json'
    rr = json.load(open(rc)) if os.path.exists(rc) else []
    tape = rr[0].get('tape') if rr else None
    if not tape or not os.path.exists(tape):
        sys.exit(f'{wd_base}: no tape known')
    span = [round(float(c['t0']), 2), round(float(c['t1']), 2)]
    os.makedirs(BOOKCUTS, exist_ok=True)
    wav = f'{BOOKCUTS}/{wd_base}__{a.hymn}.wav'
    if r.get('tape_span') != span or not os.path.exists(
            r.get('melos_audio') or ''):
        subprocess.run(['ffmpeg', '-v', 'quiet', '-y', '-i', tape,
                        '-ss', str(span[0]), '-to', str(span[1]), wav],
                       check=True)
        shutil.copy2(hj, hj + '.bak-prep-' + time.strftime('%H%M%S'))
        r['melos_audio'] = wav
        r['tape_span'] = span
        tmp = hj + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(rows, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
        os.replace(tmp, hj)
    hymn_align.cmd_melos(wd, rows, a.hymn)
    pdf = P.find_pdf()
    ann_data = os.path.normpath(os.path.join(HERE, '..', 'chant-reel',
                                             'annotator', 'data'))
    rec = P.prep_hymn(wd, r, pdf, ann_data,
                      '/mnt/data/chant-corpus/scores/page_renders')
    P.update_manifest(ann_data, [rec])
    print(f"{rec['id']}: {rec['status']}")


if __name__ == '__main__':
    main()
