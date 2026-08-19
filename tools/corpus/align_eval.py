#!/usr/bin/env python3
"""Corpus alignment scoreboard: aggregates every hymn workdir's melos/parallagi
alignment into per-mode and overall movement-agreement + coverage numbers.

Accuracy = matched-pair movement agreement (does the sung interval match the
notation's expected interval), weighted by matched pairs. Coverage = matched
units / score units. Both reported — accuracy without coverage is gaming.

Usage: align_eval.py /mnt/data/chant-corpus/workdirs/*
"""
import json, os, sys, glob

def main():
    rows = []
    for wd in sys.argv[1:]:
        mode = os.path.basename(os.path.normpath(wd))
        for sf in glob.glob(os.path.join(wd, 'melos_*', 'summary.json')):
            s = json.load(open(sf))
            rows.append({'mode': mode, 'hymn': s['hymn'], 'kind': 'melos',
                         'genus': s.get('genus', '?'),
                         'agree': s['movement_agreement'],
                         'agree_c': s.get('movement_agreement_cents'),
                         'n': s['n_matched'],
                         'cov': s['coverage_units_pct']})
    if not rows:
        print('no aligned hymns found')
        return
    by_mode = {}
    for r in rows:
        by_mode.setdefault(r['mode'], []).append(r)
    print(f"{'mode':10s} {'hymns':>5s} {'pairs':>6s} {'strict':>9s} {'cents55':>9s} {'coverage':>8s}")
    tot_n = tot_ok = 0
    cov_w = cov_n = 0
    for mode, rs in sorted(by_mode.items()):
        n = sum(r['n'] for r in rs)
        ok = sum(r['agree'] * r['n'] for r in rs)
        okc = sum((r['agree_c'] or r['agree']) * r['n'] for r in rs)
        cov = sum(r['cov'] * r['n'] for r in rs) / max(n, 1)
        tot_n += n
        tot_ok += ok
        globals().setdefault('_tot_okc', [0]); globals()['_tot_okc'][0] += okc
        cov_w += sum(r['cov'] * r['n'] for r in rs)
        cov_n += n
        print(f"{mode:10s} {len(rs):5d} {n:6d} {ok / max(n, 1):9.3f} {okc / max(n, 1):9.3f} {cov:7.1f}%")
    print('-' * 42)
    print(f"{'OVERALL':10s} {len(rows):5d} {tot_n:6d} {tot_ok / max(tot_n, 1):9.3f} "
          f"{globals().get('_tot_okc', [0])[0] / max(tot_n, 1):9.3f} "
          f"{cov_w / max(cov_n, 1):7.1f}%")
    for r in sorted(rows, key=lambda r: r['agree']):
        print(f"  {r['mode']:8s} {r['hymn']:26s} {r['genus'][:4]:4s} "
              f"agree {r['agree']:.2f} cov {r['cov']:5.1f}% (n={r['n']})")

if __name__ == '__main__':
    main()
