#!/usr/bin/env python3
"""prep_par_piece.py — a PARALLAGI annotator piece per hymn: its own score.

Chanter, 2026-08-24, pressing Par♪ on ek-pason: "it has ALL the melos notes
but it should have ONLY the glyphs that I selected from the parallagi span
score". On this tape the parallagi is an abbreviated cadence formula with its
own (shorter) score range — the row's `par_score` — so listening to it over
the melos strip is wrong. This preps a real piece per hymn:

    id       <wd>-<name>-par
    score    the row's par_score range (the chanter's own selection)
    audio    the '#par' tape cut (from the apichima mark when one is set)

The aligner runs on the pair first so prep has its summary/aligned; for an
abbreviated parallagi that alignment is a rough seed at best — tap mode is
the honest way to pin these.

Usage: prep_par_piece.py --workdir /mnt/data/chant-corpus/workdirs/mode1 [--hymn NAME | --all]
"""
import argparse, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prep_hymn_annotator as P
import hymn_align

TEXTS = '/mnt/data/chant-corpus/texts'


def par_wav(wd_base, name, cut, tape):
    out_dir = f'{TEXTS}/paudio_cache'
    os.makedirs(out_dir, exist_ok=True)
    out = f'{out_dir}/{wd_base}__{name}.wav'
    cf = f'{TEXTS}/cuts_{wd_base}.json'
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(cf):
        t0 = max(float(cut['t0']), float(cut.get('t_in') or cut['t0']))
        subprocess.run(['ffmpeg', '-v', 'quiet', '-y', '-i', tape,
                        '-ss', str(t0), '-to', str(cut['t1']), out], check=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--hymn')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    wd = args.workdir.rstrip('/')
    wd_base = os.path.basename(wd)
    rows = json.load(open(os.path.join(wd, 'hymns.json')))
    cf = f'{TEXTS}/cuts_{wd_base}.json'
    cuts = {}
    if os.path.exists(cf):
        cuts = {c['hymn']: c for c in json.load(open(cf))['cuts']}
    rc = f'{TEXTS}/recut_{wd_base}.json'
    tape = None
    if os.path.exists(rc):
        rr = json.load(open(rc))
        tape = rr[0].get('tape') if rr else None
    pdf = P.find_pdf()
    ann_data = os.path.normpath(os.path.join(HERE, '..', 'chant-reel',
                                             'annotator', 'data'))
    recs, n_ok = [], 0
    for r in rows:
        if args.hymn and r['name'] != args.hymn:
            continue
        ps, cut = r.get('par_score'), cuts.get(r['name'] + '#par')
        if not cut or cut.get('t0') is None or not tape:
            if args.hymn:
                sys.exit(f"{r['name']}: needs a saved #par cut")
            continue
        if not ps:
            # chanter: outside the abbreviated-parallagi tapes the two lanes
            # share the same exact score span — the melos range IS the
            # parallagi range unless a par_score says otherwise
            ps = {k: r.get(k) for k in ('p0', 'l0', 'g0', 'p1', 'l1', 'g1')}
        pseudo = {k: v for k, v in r.items()
                  if k not in ('segments', 'par_score', 'parallagi_track',
                               'parallagi_dir', 'tape_span', 'melos_audio')}
        pseudo['name'] = r['name'] + '-par'
        pseudo.update(ps)
        pseudo['melos_audio'] = par_wav(wd_base, r['name'], cut, tape)
        pseudo['boundary_note'] = ('parallagi piece: the chanter-selected '
                                   'par_score range over the #par tape cut')
        try:
            hymn_align.cmd_melos(wd, [pseudo], pseudo['name'])
            rec = P.prep_hymn(wd, pseudo, pdf, ann_data,
                              '/mnt/data/chant-corpus/scores/page_renders')
        except Exception as e:
            rec = {'id': f"{wd_base}-{pseudo['name'].strip('_')}",
                   'workdir': wd, 'hymn': pseudo['name'],
                   'status': f'ERROR: {e}',
                   'prepped_at': time.strftime('%Y-%m-%d %H:%M')}
        recs.append(rec)
        n_ok += rec['status'] == 'ready'
        print(f"{rec['id']}: {rec['status']}", flush=True)
    if recs:
        P.update_manifest(ann_data, recs)
    print(f'{n_ok}/{len(recs)} parallagi pieces ready')


if __name__ == '__main__':
    main()
