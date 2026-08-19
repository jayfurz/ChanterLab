#!/usr/bin/env python3
"""Wire the best available parallagi anchor into each hymn of a mode workdir.

Pairing: a hymn whose melos piece is NNN_<kind>.wav anchors to the nearest
preceding parallagi piece (NNN-3 <= M < NNN). Among candidate dataset dirs
(whisper- or CNN-labeled), the highest match_agreement >= --min wins;
an existing parallagi_dir is kept unless beaten.

Usage: wire_anchors.py <workdir> --prefixes p1 p2 ... [--min 0.55]
"""
import glob, json, os, re, sys

def main():
    wd = sys.argv[1]
    prefixes = sys.argv[sys.argv.index('--prefixes') + 1:]
    if '--min' in prefixes:
        i = prefixes.index('--min')
        mn = float(prefixes[i + 1])
        prefixes = prefixes[:i]
    else:
        mn = 0.55
    cands = {}                       # piece number -> [(agreement, dir)]
    for pref in prefixes:
        for d in glob.glob(f'/mnt/data/chant-corpus/parallagi/{pref}*'):
            sf = os.path.join(d, 'summary_full.json')
            if not os.path.exists(sf):
                continue
            m = re.search(r'(\d{3})_parallagi', d)
            if not m:
                continue
            agr = json.load(open(sf)).get('match_agreement', 0)
            cands.setdefault(int(m.group(1)), []).append((agr, d))
    hymns = json.load(open(os.path.join(wd, 'hymns.json')))
    wired = 0
    for h in hymns:
        m = re.search(r'(\d{3})_[a-z]+\.wav', h.get('melos_audio', ''))
        if not m:
            continue
        nn = int(m.group(1))
        pool = [c for num in range(max(nn - 3, 0), nn) for c in cands.get(num, [])]
        if not pool:
            continue
        agr, d = max(pool)
        cur = h.get('parallagi_dir')
        cur_agr = 0
        if cur and os.path.exists(os.path.join(cur, 'summary_full.json')):
            cur_agr = json.load(open(os.path.join(cur, 'summary_full.json'))).get('match_agreement', 0)
        if agr >= mn and agr > cur_agr:
            h['parallagi_dir'] = d
            wired += 1
            print(f"  {h['name']:26s} <- {os.path.basename(d)} (agree {agr:.2f}"
                  f"{', replaced ' + str(round(cur_agr, 2)) if cur else ''})")
    json.dump(hymns, open(os.path.join(wd, 'hymns.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f"{wired} anchors wired in {wd}")

if __name__ == '__main__':
    main()
