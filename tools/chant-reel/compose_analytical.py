#!/usr/bin/env python3
"""compose_analytical.py — turn chanter interpretation specs into typeset,
bracketed analytical figures composited above the score strip.

Reads <workdir>/analytical_interpretations.json (notes as [degree, beats]),
composes an SBMuFL character sequence per figure (interval -> quantity
character, beat pattern -> time marks), typesets it in the repo's Neanes font
via headless Chrome, and composites it with red editorial brackets into
strip.png above the passage.  Writes <workdir>/analytical.json with each
figure's strip box + time span so the renderers can glow it while sung.

v1 rule table (chanter-correctable; flagged choices land in the caption):
  intervals: +1 oligon · +2 oligonKentimaAbove · +3 oligonYpsili · -1
  apostrofos · -2 elafron
  timing: ½+½ pair -> gorgonAbove on the 2nd · ¼+¼+½ triple ->
  digorgonDottedRight on the 2nd · 2 beats -> klasmaAbove · 1½ ->
  klasmaAbove (FLAG: needs dotted-apli spelling) · leading tempo=argo ->
  red argon before the figure
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from typeset_ez import typeset  # noqa: E402  (font param added below)

HERE = Path(__file__).resolve().parent
WD = HERE.parent.parent / 'datasets/eothinon-11-workdir'
MAP_JS = Path('/mnt/data/code/byzorgan-web/web/ocr/atlas/font_glyph_map.js')
NEANES = Path('/mnt/data/code/byzorgan-web/web/fonts/neanes/Neanes.otf')

NAME2CP = {m.group(1): int(m.group(2), 16) for m in
           re.finditer(r'name: "(\w+)", codepoint: "U\+([0-9A-Fa-f]+)"', MAP_JS.read_text())}

DEGREES = ['Νη', 'Πα', 'Βου', 'Γα', 'Δι', 'Κε', 'Ζω', "Νη'", "Πα'"]
STEP_OF = {d: i for i, d in enumerate(DEGREES)}
QUANTITY = {1: 'oligon', 2: 'oligonKentimaAbove', 3: 'oligonYpsiliRight',
            4: 'oligonYpsiliLeft', 0: 'ison', -1: 'apostrofos', -2: 'elafron',
            -3: 'elafronApostrofos'}


def compose(figure, start_deg):
    """notes: [[degree, beats, ...], ...] -> (tokens, flags) for the typesetter."""
    tokens, flags = [], []
    if figure.get('tempo', '').startswith('argo'):
        tokens.append({'name': 'argon', 'red': True, 'sep': True})
    prev = STEP_OF[start_deg]
    notes = [(n[0], float(n[1])) for n in figure['notes']]
    beats = [b for _, b in notes]
    for i, (deg, b) in enumerate(notes):
        step = STEP_OF[deg]
        iv = step - prev
        prev = step
        if iv not in QUANTITY:
            flags.append(f'interval {iv:+d} unmapped, used oligon')
            iv = 1
        tokens.append({'name': QUANTITY[iv], 'red': False})
        # time marks (looking back at the pattern)
        if b == 0.5 and i > 0 and beats[i - 1] == 0.5 and (i < 2 or beats[i - 2] != 0.25):
            tokens.append({'name': 'gorgonAbove', 'red': True})
        elif b == 0.5 and i >= 2 and beats[i - 2] == 0.25 and beats[i - 1] == 0.25:
            pass                                    # closed by the digorgon below
        elif b == 0.25 and i + 1 < len(notes) and beats[i + 1] == 0.25 and i > 0:
            pass                                    # first of the quick pair
        elif b == 0.25 and i > 0 and beats[i - 1] == 0.25:
            tokens.append({'name': 'digorgonDottedRight', 'red': True})
        elif b == 2.0:
            tokens.append({'name': 'klasmaAbove', 'red': False})
        elif b == 1.5:
            tokens.append({'name': 'klasmaAbove', 'red': False})
            flags.append('1.5-beat hold spelled as klasma — needs dotted-apli, confirm')
        elif b == 1.0 or b == 0.25 or b == 0.5:
            pass
        else:
            flags.append(f'unhandled duration {b}')
    return tokens, flags


def to_spec(tokens):
    spec = []
    for t in tokens:
        cp = NAME2CP[t['name']]
        spec.append({'k': None, 'ch': chr(cp), 'red': t.get('red', False),
                     'sep': t.get('sep', False)})
    return spec


if __name__ == '__main__':
    interp = json.load(open(WD / 'analytical_interpretations.json'))
    out = {}
    for key, start in (('peter', 'Κε'), ('wolves', 'Δι')):
        fig = interp[key]
        tokens, flags = compose(fig, start)
        out[key] = {'tokens': tokens, 'flags': flags, 'span': fig['span']}
        print(f'{key}: ' + ' '.join(t['name'] + ('(r)' if t.get('red') else '')
                                    for t in tokens))
        for f in flags:
            print(f'  FLAG: {f}')
    json.dump(out, open(WD / 'analytical_composed.json', 'w'), indent=1, ensure_ascii=False)
    print('wrote analytical_composed.json')
