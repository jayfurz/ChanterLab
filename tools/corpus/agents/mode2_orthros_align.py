#!/usr/bin/env python3
"""Mode 2 orthros alignment driver: joint legend EM, then THREE melos --em
rounds per hymn (each round re-aligns every hymn and lets matched pairs vote
legend keys), then align_eval on the workdir.

Usage: python3 tools/corpus/agents/mode2_orthros_align.py
"""
import json, os, subprocess, sys

CORPUS = '/mnt/data/chant-corpus'
WD = f'{CORPUS}/workdirs/mode2-orthros'
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HY = os.path.join(WD, 'hymns.json')

os.environ['CUDA_VISIBLE_DEVICES'] = ''

hymns = json.load(open(HY))
print('== legend ==', flush=True)
subprocess.run([sys.executable, os.path.join(TOOLS, 'hymn_align.py'),
                'legend', WD, '--hymns', HY], check=True)
for rnd in range(1, 4):
    print(f'== melos round {rnd} ==', flush=True)
    for h in hymns:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'hymn_align.py'),
                            'melos', WD, '--hymns', HY, '--hymn', h['name'], '--em'])
        if r.returncode != 0:
            print(f"  CRASH {h['name']} rc={r.returncode}", flush=True)
print('== eval ==', flush=True)
subprocess.run([sys.executable, os.path.join(TOOLS, 'align_eval.py'), WD])
