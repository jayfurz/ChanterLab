#!/usr/bin/env python3
"""Build parallagi datasets for parallagi-marked transcripts that have audio
but no dataset dir yet. Plan-only by default; --run executes.

Usage: python3 tools/corpus/agents/build_parallagi_missing.py [--run]
"""
import os, re, sys, json, subprocess, unicodedata

CORPUS = '/mnt/data/chant-corpus'
TR = os.path.join(CORPUS, 'transcripts')
RAW = os.path.join(CORPUS, 'raw', 'vasilikos')
OUT = os.path.join(CORPUS, 'parallagi')
AEXT = {'.m4a', '.mp3', '.wav', '.flac', '.ogg', '.opus'}

def norm(s):
    return unicodedata.normalize('NFC', s)

def is_parallagi(name):
    u = norm(name).upper()
    return 'PARALLAGE' in u or 'ΠΑΡΑΛΛΑΓ' in u

# index audio by NFC-normalized stem
audio_by_stem = {}
for root, _dirs, files in os.walk(RAW):
    for f in files:
        stem, ext = os.path.splitext(f)
        if ext.lower() in AEXT:
            audio_by_stem.setdefault(norm(stem), []).append(os.path.join(root, f))

existing = {norm(d) for d in os.listdir(OUT)} if os.path.isdir(OUT) else set()

plan, no_audio, have_ds = [], [], []
for f in sorted(os.listdir(TR)):
    if not f.endswith('.json'):
        continue
    stem = norm(f[:-5])
    if not is_parallagi(stem):
        continue
    if stem in existing:
        have_ds.append(stem)
        continue
    hits = audio_by_stem.get(stem, [])
    if not hits:
        no_audio.append(stem)
        continue
    plan.append((stem, hits[0], os.path.join(TR, f)))

print(f'parallagi transcripts: existing_ds={len(have_ds)} to_build={len(plan)} no_audio={len(no_audio)}')
for s in no_audio:
    print('  NO-AUDIO:', s)
for s, a, w in plan:
    print('  BUILD:', s, '<-', a)

if '--run' not in sys.argv:
    sys.exit(0)

repo = '/mnt/data/code/byzorgan-web-worktrees/chant-annotator'
results = []
for stem, audio, whisper in plan:
    outdir = os.path.join(OUT, stem)
    print(f'=== {stem}', flush=True)
    r1 = subprocess.run(['python3', 'tools/corpus/parallagi_dataset.py',
                         '--audio', audio, '--whisper', whisper, '--outdir', outdir],
                        cwd=repo, capture_output=True, text=True)
    ok1 = r1.returncode == 0 and os.path.exists(os.path.join(outdir, 'events.jsonl'))
    if not ok1:
        print('DATASET FAIL', r1.returncode)
        print(r1.stdout[-2000:]); print(r1.stderr[-2000:])
        results.append((stem, 'dataset_fail'))
        continue
    r2 = subprocess.run(['python3', 'tools/corpus/parallagi_align.py', outdir],
                        cwd=repo, capture_output=True, text=True)
    ok2 = r2.returncode == 0 and os.path.exists(os.path.join(outdir, 'events_full.jsonl'))
    if not ok2:
        print('ALIGN FAIL', r2.returncode)
        print(r2.stdout[-2000:]); print(r2.stderr[-2000:])
        results.append((stem, 'align_fail'))
        continue
    n = sum(1 for _ in open(os.path.join(outdir, 'events.jsonl')))
    print(f'OK events={n}')
    results.append((stem, f'ok:{n}'))

print(json.dumps(results, ensure_ascii=False, indent=1))
