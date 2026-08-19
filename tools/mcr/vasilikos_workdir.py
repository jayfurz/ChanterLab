#!/usr/bin/env python3
"""Adapt a Vasilikos EM workdir (extract_vector_glyphs + em_legend outputs)
into the file layout train_aligner.build_piece expects, so the gold-trained
arc scorer can decode it and mint silver training arcs.

Builds: moria_track.npy (cents -> Ni-anchored moria, reference fitted so the
claimed events sit on the diatonic ladder), voice_notes3.json (mcrlib-cleaned
stream), slots.json / mcr_interpretation.json / expected_degrees.json /
barlines.json, and slot_claims_em.json (EM claims remapped to the cleaned
stream — diagnostic silver, not gold).

Usage: vasilikos_workdir.py <workdir>
"""
import json, sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcrlib import clean_stream, med_pitch

wd = sys.argv[1] if len(sys.argv) > 1 else '.'
j = lambda f: json.load(open(os.path.join(wd, f)))
units = j('units.json')
legend = j('legend.json')
claims_raw = j('em_claims.json')          # [unit_idx, sub, event_idx] (raw stream)
vn_raw = j('voice_notes.json')
cents = np.load(os.path.join(wd, 'cents_track.npy'))
rms = np.load(os.path.join(wd, 'rms_track.npy'))
MORIA_PER_CENT = 72.0 / 1200.0
STEP = 10.3

# ---- slots from units ----
iv = {k: v['interval'] for k, v in legend['keys'].items()}
two_sub = {int(c): v for c, v in legend.get('two_sub', {}).items()}
note_units = [i for i, u in enumerate(units) if u['kind'] == 'note']
gi_of_unit = {ui: g for g, ui in enumerate(note_units)}
slots_gi, slots_sub, E = [], [], []
deg = 0
interp = []
for g, ui in enumerate(note_units):
    u = units[ui]
    subs = u['subs']
    ivs = (two_sub[u['base']] if u['base'] in two_sub else [iv[u['key']]] * subs)
    beats = [((0.5 if u['gorgon'] else 1.0) + (1.0 if u['apli'] else 0.0)) / subs] * subs
    slot_ids = []
    for sb in range(subs):
        deg += ivs[sb]
        slot_ids.append(len(slots_gi))
        slots_gi.append(g); slots_sub.append(sb); E.append(deg)
    interp.append({'gi': g, 'cp': u['key'], 'name': u['key'], 'line': u['line'],
                   'sub_notes': subs, 'beats': beats, 'gorgon': bool(u['gorgon']),
                   'duration_mark': 'apli' if u['apli'] else 'none',
                   'quality_marks': [], 'other_marks': [],
                   'expected_degrees': E[-subs:], 'ison_at_start': 0,
                   'slot_ids': slot_ids, 'word': None, 'word_start': False})
S = len(slots_gi)

# ---- Ni reference: fit so claimed events sit on the diatonic ladder ----
LS = [12, 10, 8, 12, 12, 10, 8]
lad = {0: 0.0}
for d in range(0, max(E) + 1):
    lad[d + 1] = lad[d] + LS[d % 7]
for d in range(0, min(E) - 1, -1):
    lad[d - 1] = lad[d] - LS[(d - 1) % 7]
slot_of = {}
for (ui, sb, k) in claims_raw:
    if ui in gi_of_unit:
        g = gi_of_unit[ui]
        cand = [s for s in interp[g]['slot_ids'] if slots_sub[s] == sb]
        if cand:
            slot_of[k] = cand[0]
ev_cents = np.array([v[2] for v in vn_raw])
resid = [ev_cents[k] - lad[E[s]] / MORIA_PER_CENT for k, s in slot_of.items()]
cents_ni = float(np.median(resid))
mor = (cents - cents_ni) * MORIA_PER_CENT
np.save(os.path.join(wd, 'moria_track.npy'), mor)
check = np.median([abs((ev_cents[k] - cents_ni) * MORIA_PER_CENT - lad[E[s]])
                   for k, s in slot_of.items()])
print(f"Ni ref: {cents_ni:.0f} cents rel 55Hz "
      f"(~{55 * 2 ** (cents_ni / 1200):.1f} Hz); "
      f"median |moria - ladder(E)| over EM claims: {check:.1f} moria")

# ---- cleaned stream + claim remap ----
vn_in = [[v[0], v[1], v[2], v[3]] for v in vn_raw]
cleaned = clean_stream(vn_in, mor, rms, None)
c_t0 = [v[0] for v in cleaned]
remap = {}
ci = 0
for k, v in enumerate(vn_in):
    while ci + 1 < len(cleaned) and c_t0[ci + 1] <= v[0] + 1e-9:
        ci += 1
    remap[k] = ci
json.dump(cleaned, open(os.path.join(wd, 'voice_notes3.json'), 'w'))
claims = [None] * S
for k, s in slot_of.items():
    ck = remap[k]
    if claims[s] is None:
        claims[s] = ck
# one cleaned event can absorb several raw events; keep first claim per event
seen = {}
for s in range(S):
    if claims[s] is not None:
        if claims[s] in seen:
            claims[s] = None
        else:
            seen[claims[s]] = s
json.dump(claims, open(os.path.join(wd, 'slot_claims_em.json'), 'w'))

json.dump({'t': [0.0] * S, 'gi': slots_gi, 'sub': slots_sub},
          open(os.path.join(wd, 'slots.json'), 'w'))
json.dump(interp, open(os.path.join(wd, 'mcr_interpretation.json'), 'w'))
json.dump(E, open(os.path.join(wd, 'expected_degrees.json'), 'w'))
json.dump([], open(os.path.join(wd, 'barlines.json'), 'w'))
n_cl = sum(c is not None for c in claims)
print(f"{S} slots ({len(note_units)} glyph units), cleaned stream "
      f"{len(vn_in)} -> {len(cleaned)} events, EM silver claims {n_cl}/{S}")
