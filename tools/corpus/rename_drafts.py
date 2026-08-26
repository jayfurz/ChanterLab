#!/usr/bin/env python3
"""Re-name draftcuts spans using the old resep 'cur' spans (independent
track-pairing evidence with hymn identity). Both are machine; the combination
is still a DRAFT. Backup + rewrite draftcuts_<wd>.json in place."""
import json, shutil, time, sys
wd = sys.argv[1] if len(sys.argv) > 1 else 'mode2-orthros'
DF = f'/mnt/data/chant-corpus/texts/draftcuts_{wd}.json'
d = json.load(open(DF))
cuts = d['cuts']
rows = json.load(open(f'/mnt/data/chant-corpus/texts/recut_{wd}.json'))
mel_idx = [i for i, c in enumerate(cuts) if c['lane'] == 'melos']
owners = {}   # mel cut index -> [hymn names]
for r in rows:
    c0, c1 = r['cur']
    best, bov = None, 0.0
    for i in mel_idx:
        c = cuts[i]
        ov = max(0.0, min(c1, c['t1']) - max(c0, c['t0']))
        if ov > bov: best, bov = i, ov
    if best is not None and bov / (c1 - c0) >= 0.2:
        owners.setdefault(best, []).append(r['hymn'])
new = []
for i, c in enumerate(cuts):
    c = dict(c)
    if c['lane'] == 'melos':
        names = owners.get(i, [])
        if len(names) == 1:
            c['hymn'] = names[0]
            c['label'] = 'renamed from old track pairing'
        elif len(names) > 1:
            c['hymn'] = names[0]
            c['label'] = f'MERGED? old pairing says {"+".join(names)} — check for missed boundary'
        else:
            c['hymn'] = None
            c['label'] = 'no old-pairing evidence — identify by ear'
        # the par span immediately before this melos follows its name
        if i > 0 and cuts[i-1]['lane'] == 'parallagi' and new and new[-1]['lane'] == 'parallagi':
            new[-1]['hymn'] = (c['hymn'] + '#par') if c['hymn'] else None
            new[-1]['label'] = c['label']
    new.append(c)
# unnamed pairs get stable placeholder identities: uNN_#par / uNN_ in tape
# order, so the cutter and any downstream tool can address them before the
# chanter identifies the hymn.
un = 0
for i, c in enumerate(new):
    if c['hymn'] is None and c['lane'] == 'melos':
        un += 1
        c['hymn'] = f'u{un:02d}_'
        if i > 0 and new[i-1]['lane'] == 'parallagi' and new[i-1]['hymn'] is None:
            new[i-1]['hymn'] = f'u{un:02d}_#par'
un2 = 0
for c in new:
    if c['hymn'] is None:            # stray unnamed parallagi (no melos after)
        un2 += 1
        c['hymn'] = f'ux{un2:02d}_#par'
d['cuts'] = new
d['naming_source'] = 'cur-overlap rename (rename_drafts.py) over greedy book order'
shutil.copy2(DF, DF + '.bak-greedy-' + time.strftime('%Y%m%d%H%M%S'))
json.dump(d, open(DF + '.tmp', 'w'), ensure_ascii=False, indent=1)
import os; os.replace(DF + '.tmp', DF)
for c in new:
    print(f"{str(c['hymn']):10} {c['t0']:8.1f}-{c['t1']:8.1f} {c['lane'][:3]}  {c.get('label') or ''}")
