#!/usr/bin/env python3
"""regen_strips.py — rebuild piece score strips with the current band split,
touching NOTHING else in annotator_data.json.

The 144px lower band cut lyrics off (chanter 2026-08-24: "hard to see the
lyrics under some of the notes"); BAND_DN is now 200. Re-running prep would
also reseed slots — destroying transfer-seeded onsets and stale-marking
chanter work — so this regenerates ONLY strip.png and the geometry meta
(strip_h, band_dn, line_centers). Note boxes and slot times are band-top
relative and stay valid; data_rev is left alone so local pins survive.

Usage: regen_strips.py --piece mode1-kyrie-ekekraxa [--piece ...] | --prefix mode1-
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prep_hymn_annotator as P

DATA = os.path.normpath(os.path.join(HERE, '..', 'chant-reel', 'annotator', 'data'))

def regen(pid, cache):
    d = os.path.join(DATA, pid)
    f = os.path.join(d, 'annotator_data.json')
    D = json.load(open(f))
    src = D['meta'].get('source') or {}
    wd, hy = src.get('workdir'), src.get('hymn')
    if not wd or not hy:
        print(f'{pid}: no workdir/hymn source — skipped'); return
    rows = json.load(open(os.path.join(wd, 'hymns.json')))
    rows = rows if isinstance(rows, list) else rows['hymns']
    r = next((x for x in rows if x['name'] == hy), None)
    if r is None:
        print(f'{pid}: row {hy} gone — skipped'); return
    pdf = json.load(open('/mnt/data/chant-corpus/scores/book_map.json'))['pdf']
    from hymn_align import load_units_h
    units, _ = load_units_h(r)
    lines = P.hymn_lines(r)
    clip = P.hymn_x_clip(units)
    w, h, centers, tops = P.build_strip(pdf, lines, cache,
                                        os.path.join(d, 'strip.png'), clip=clip)
    D['meta'].update({'strip_w': w, 'strip_h': h, 'line_centers': centers,
                      'band_up': P.BAND_UP, 'band_dn': P.BAND_DN})
    # notes carry ABSOLUTE strip y (rel + line * LINE_BAND): a band-height
    # change moves every line's offset, so recompute y0/y1 exactly as prep
    # does — first regen shipped 288-based note y under a 344 meta and the
    # neume highlights floated 56px higher per line.
    line_ix = {pl: i for i, pl in enumerate(lines)}
    if len(units) == len(D.get('notes', [])):
        for u, n in zip(units, D['notes']):
            pl = tuple(u['pl'])
            li = line_ix.get(pl)
            if li is None or pl not in tops:
                continue
            ty = tops[pl]
            n['line'] = li
            n['y0'] = round((u['y0'] - ty) * P.ZOOM + li * P.LINE_BAND, 1)
            n['y1'] = round((u['y1'] - ty) * P.ZOOM + li * P.LINE_BAND, 1)
    else:
        print(f'{pid}: WARNING notes ({len(D.get("notes", []))}) != units '
              f'({len(units)}) — note boxes NOT recomputed')
    tmp = f + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(D, fh, ensure_ascii=False)
    os.replace(tmp, f)
    print(f'{pid}: strip {w}x{h}, {len(centers)} lines, band_dn {P.BAND_DN}')

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--piece', action='append', default=[])
    ap.add_argument('--prefix')
    ap.add_argument('--render-cache', default='/mnt/data/chant-corpus/scores/page_renders')
    a = ap.parse_args()
    pids = list(a.piece)
    if a.prefix:
        pids += sorted(p for p in os.listdir(DATA)
                       if p.startswith(a.prefix) and
                       os.path.isfile(os.path.join(DATA, p, 'annotator_data.json')))
    for pid in dict.fromkeys(pids):
        try:
            regen(pid, a.render_cache)
        except Exception as e:
            print(f'{pid}: FAILED — {e}')

if __name__ == '__main__':
    main()
