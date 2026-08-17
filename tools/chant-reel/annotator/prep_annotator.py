#!/usr/bin/env python3
"""prep_annotator.py — convert chant-reel pipeline outputs into annotator-ready data.

Reads the per-piece working directory produced by the chant-reel pipeline
(score_notes.json, slots.json, timing.json, modifiers.json, strip.png,
line_centers.npy, moria_track.npy, ison_timeline.json, expected_degrees.json,
barlines.json, master.wav) and writes into <annotator>/data/:

  annotator_data.json      everything the UI needs (notes, slots, words, pitch, ison)
  mcr_interpretation.json  one record per glyph: the machine's reading of the score
                           (name, beats, gorgon/duration/quality marks, expected
                           degrees, ison at start) so the chanter can compare the
                           MCR extraction against the printed page
  strip.png                copy of the score strip
  audio.wav                copy of the master recording

Only score_notes.json, slots.json, strip.png, line_centers.npy and the audio are
required; every other input is optional and degrades gracefully.

Usage:
  python3 prep_annotator.py --input /path/to/piece-workdir [--out DIR]
                            [--audio master.wav] [--piece-id my-piece]
                            [--parts-tables PARTS.json] [--overrides OVERRIDES.json]

With --parts-tables (a geometry-tables JSON holding SUB_LAYOUT / MARK_INK /
MARK_INK_instances, see tables' "how_to_apply") each note in
annotator_data.json gains an optional "parts" field:

  notes[g].parts = {
    "subs":  [[x0,y0,x1,y1], ...],  # one ink box per sub-note, sung order,
                                    # same coord space as the note cell
    "marks": [[x0,y0,x1,y1], ...]   # duration-mark fill boxes in fill order;
                                    # length == added beats (klasma/apli 1,
                                    # diple 2, tripli 3)
  }

subs are emitted only for glyphs that expand to >1 sub-slot and whose cp is in
SUB_LAYOUT; marks only for glyphs carrying a duration mark whose cp is in
MARK_INK.  Without the flag no parts field is written (fully backward
compatible).  Absent/mismatched parts => the UI falls back to whole-cell
highlight.

--overrides points at a JSON {"WEIGHT_OVR": {"<gi>": beats, ...},
"SUBW_OVR": [[gi, sub, beats], ...], "ATTACH_OVR": {"<mi>": gi, ...}} that
replaces the per-piece override tables below (they are keyed by glyph index,
which shifts whenever glyph extraction changes; ATTACH_OVR is optional).

The per-piece interpretation knobs below (GORGON, DURATION_CP, WEIGHT_OVR, ...)
mirror the score-side logic of tools/chant-reel/note_align5.py and should be kept
in sync with the aligner used for the piece.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Per-piece / per-font interpretation constants (mirror note_align5.py).
# Edit these when the aligner's tables change or a new piece needs overrides.
# --------------------------------------------------------------------------
GORGON = {0xF053, 0xF073, 0xF048}          # gorgon (S+s case pair) + red dotted
DIGORGON = {0xF044}                        # digorgon: prev+carrier+next share 1 beat, 1/3 each (chanter-verified)
GORGON_INTERNAL = {0xF055}                 # gorgon over its OWN kentimata: both subs 0.5, NO steal from prev
GORGON_NAME = {0xF053: "gorgon", 0xF073: "gorgon", 0xF048: "gorgon(dotted)"}
DURATION_CP = {0xF061: 2.0, 0xF041: 2.0, 0xF027: 2.0, 0xF06B: 3.0}
DURATION_NAME = {0xF061: "klasma", 0xF041: "klasma", 0xF027: "apli", 0xF06B: "diple"}
# quality marks documented for this font (psifiston cp not yet confirmed for
# EZ-Psaltic — add it here once identified; unclassified attached marks are
# still surfaced in each record's other_marks so nothing is hidden)
QUALITY_NAME = {0xF022: "antikenoma", 0xF05B: "omalon"}
PSIFISTON_CPS: set = set()                  # fill in when the cp is confirmed
YPORRHOE = {0xF05F, 0xF029}                 # classic + stacked/narrow variant: 2 descending notes
SYNELAF = 0xF050
KENTIMATA_COMPOUNDS = {0xF0D7, 0xF06F, 0xF04F, 0xF055, 0xF059, 0xF075}  # two sung notes; 0xf077 = ONE note
ATTACH_MAX_D = 30                           # px: modifier-to-glyph attach radius
# piece-specific weight overrides (glyph index -> beats); Eothinon XI values:
WEIGHT_OVR = {54: 2.0, 60: 0.5, 84: 1.0}
SUBW_OVR = {(59, 1): 0.5}
# piece-specific attachment overrides (modifier index -> glyph index): the 9
# red gorgons of the stacked yporrhoe (0xf029) have zero-width origins ~24px
# right of the glyph origin — past its x1, at/inside the NEXT glyph — so
# nearest-interval attachment misassigns them (chanter: 0xf029 carries the
# red gorgon).  Eothinon XI values:
ATTACH_OVR = {22: 24, 70: 61, 108: 92, 145: 118, 181: 149, 223: 184,
              289: 227, 293: 231, 333: 259, 341: 266}
# mi 289 is the tenth such gorgon, written as cp 0xf044 (unique in the piece)

GLYPH_NAME = {
    0xF021: "apostrofos",
    0xF030: "ison",
    0xF031: "oligon",
    0xF05F: "running-elafron",   # apostrofos+elafron ligature (syndesmos); engine: runningElafron
    0xF029: "yporrhoe",          # steep stacked two-comma descent; engine: yporroi
    0xF050: "ison+kentimata",
    0xF059: "elafron+kentimata",       # over silent oligon table + psifiston bowl
    0xF075: "oligon+ypsili+kentimata", # note1 = oligon WITH ypsili (jump up 4), note2 = kentimata; psifiston silent
    0xF077: "petasti+oligon",          # ONE melodic note, up 2; both strokes light together
    0xF065: "petasti+kentima",         # ONE note; kentima lights WITH the petasti
    0xF070: "ison+petasti",            # ONE note; petasti qualitative here but lights WITH the ison
    0xF034: "oligon+ypsili",           # ONE note (jump); ypsili lights WITH the oligon
    0xF049: "apostrofos+klasma",       # psifiston+oligon table silent; klasma curl EMBEDDED in the char
    0xF055: "apostrofos+kentimata",    # over silent oligon; glyph-internal gorgon: both notes half a beat
    0xF060: "kentimata",
    0xF0D7: "kentimata-compound",
    0xF06F: "kentimata-compound",
    0xF04F: "kentimata-compound",
}

PITCH_DT = 0.02       # s per downsampled pitch sample written to JSON
MORIA_SRC_DT = 0.01   # s per sample in moria_track.npy


def glyph_name(cp: int) -> str:
    return GLYPH_NAME.get(cp, hex(cp))


def attach_modifiers(notes, mods):
    """Attach every non-space modifier to its nearest glyph on the same line
    using the aligner's interval-distance rule (a mark's origin may sit at
    either edge of its glyph). Returns per-glyph mark lists + gorgon/duration."""
    n = len(notes)
    gor = [False] * n
    digor = [False] * n
    dur = [1.0] * n
    dur_mark = ["none"] * n
    dur_mod = [None] * n      # the modifier record whose duration mark applied
    quality = [[] for _ in range(n)]
    other = [[] for _ in range(n)]
    for mi, m in enumerate(mods or []):
        cp = m["cp"]
        if cp == 0x20:
            continue
        if mi in ATTACH_OVR:
            best = ATTACH_OVR[mi]
        else:
            best, bd = None, ATTACH_MAX_D
            for j, g in enumerate(notes):
                if g["line"] != m["line"]:
                    continue
                d = max(g["x0"] - m["x"], m["x"] - g["x1"], 0)
                if d < bd:
                    best, bd = j, d
        if best is None:
            continue
        if cp in GORGON:
            gor[best] = True
        elif cp in DIGORGON:
            digor[best] = True
        elif cp in DURATION_CP:
            if DURATION_CP[cp] > dur[best]:
                dur[best] = DURATION_CP[cp]
                dur_mark[best] = DURATION_NAME[cp]
                dur_mod[best] = m
            elif dur_mark[best] == "none":
                dur_mark[best] = DURATION_NAME[cp]
                dur_mod[best] = m
        elif cp in QUALITY_NAME:
            quality[best].append(QUALITY_NAME[cp])
        elif cp in PSIFISTON_CPS:
            quality[best].append("psifiston")
        else:
            other[best].append(hex(cp))
    return gor, digor, dur, dur_mark, dur_mod, quality, other


def multi_sub(cp: int) -> bool:
    """True for glyphs that expand to more than one sung sub-slot."""
    return cp in YPORRHOE or cp in KENTIMATA_COMPOUNDS or cp == SYNELAF


def ink_bbox(strip_img, x0, y0, x1, y1, exclude=()):
    """Tight bbox of BLACK ink inside a strip-image cell (red ink and pixels
    inside `exclude` boxes are ignored).  Returns [x0,y0,x1,y1] or None."""
    import numpy as np
    box = (int(max(0, x0)), int(max(0, y0)),
           int(min(strip_img.width, x1)), int(min(strip_img.height, y1)))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    a = np.asarray(strip_img.crop(box).convert("RGB")).astype(int)
    dark = a.max(axis=2) < 120                      # black ink; red fails (r~0xed)
    for ex in exclude:
        ex0, ey0, ex1, ey1 = (int(ex[0] - box[0]), int(ex[1] - box[1]),
                              int(ex[2] - box[0]), int(ex[3] - box[1]))
        dark[max(0, ey0 - 2):ey1 + 2, max(0, ex0 - 2):ex1 + 2] = False
    # keep only the dominant connected ink mass (plus comparably-sized
    # companions): drops detached clutter — lyric ascender tips poking into
    # the cell, printed beat numerals, neighbours' antialiasing
    lab = np.zeros(dark.shape, dtype=int)
    sizes, nl = [0], 0
    for sy, sx in zip(*np.nonzero(dark)):
        if lab[sy, sx]:
            continue
        nl += 1
        stack, count = [(sy, sx)], 0
        lab[sy, sx] = nl
        while stack:
            y, x = stack.pop()
            count += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (0 <= ny < dark.shape[0] and 0 <= nx < dark.shape[1]
                            and dark[ny, nx] and not lab[ny, nx]):
                        lab[ny, nx] = nl
                        stack.append((ny, nx))
        sizes.append(count)
    if nl == 0:
        return None
    # keep the largest component plus same-band companions; a large stroke
    # BELOW/ABOVE the main one (psifiston / antikenoma bowl — expressive,
    # never sung) is dropped unless its rows overlap the main stroke's
    big = int(np.argmax(sizes))
    ys, _ = np.nonzero(lab == big)
    b0, b1 = ys.min(), ys.max()
    keep = {big}
    for l in range(1, nl + 1):
        if l == big or sizes[l] < 0.15 * sizes[big]:
            continue
        ly, _ = np.nonzero(lab == l)
        ov = min(b1, ly.max()) - max(b0, ly.min()) + 1
        if ov >= 0.5 * (ly.max() - ly.min() + 1):
            keep.add(l)
    dark &= np.isin(lab, list(keep))
    ys, xs = np.nonzero(dark)
    if not len(xs):
        return None
    return [box[0] + int(xs.min()) - 1.0, box[1] + int(ys.min()) - 1.0,
            box[0] + int(xs.max()) + 2.0, box[1] + int(ys.max()) + 2.0]


def build_parts(notes, dur_mark, dur_mod, tables, strip_img=None):
    """Attach an optional per-glyph 'parts' field (in place) from the geometry
    tables (--parts-tables):

      subs  : SUB_LAYOUT[cp].subs are per-sub-note ink boxes as 0..1 fractions
              of the glyph's em cell, in sung order -> scaled into the note's
              own coord space (x line-local, y strip-band).
      marks : duration-mark drawn-ink boxes in fill order, one per ADDED beat
              (klasma/apli 1, diple 2, tripli 3).  Preferred source is the
              per-instance measured ink (MARK_INK_instances, matched by
              line + origin x — this also covers non-standard font sizes);
              otherwise the MARK_INK rule: [mod.x+dx0, band_y0+dy0,
              mod.x+dx1, band_y0+dy1] with band_y0 = the glyph cell's y0.

    A duration-marked glyph with no SUB_LAYOUT entry (plain ison/oligon/…)
    gets subs=[tight black-ink bbox] measured from the strip (strip_img),
    so the melodic fill hugs the printed neume instead of the whole em cell.

    Glyphs with one sub-slot and no duration mark get no parts field; a cp
    missing from a table just omits that half.  Returns (n_subs, n_marks)."""
    sub_layout = tables.get("SUB_LAYOUT") or {}
    mark_ink = tables.get("MARK_INK") or {}
    # instance ink indexed per (cp, line) for tolerance matching on origin x
    inst_ix = {}
    for cph, recs in (tables.get("MARK_INK_instances") or {}).items():
        for r in recs:
            inst_ix.setdefault((cph.lower(), r["line"]), []).append(r)
    n_subs = n_marks = 0
    for j, g in enumerate(notes):
        parts = {}
        if True:
            lay = sub_layout.get("0x%04x" % g["cp"])
            n_expected = 2 if multi_sub(g["cp"]) else 1
            if lay and len(lay["subs"]) == n_expected:
                w, h = g["x1"] - g["x0"], g["y1"] - g["y0"]
                def _scale(f):
                    return [round(g["x0"] + f[0] * w, 1), round(g["y0"] + f[1] * h, 1),
                            round(g["x0"] + f[2] * w, 1), round(g["y0"] + f[3] * h, 1)]
                # a sub entry may be a NESTED list of boxes (all lit together,
                # e.g. oligon+ypsili as one jump) or a single flat box
                parts["subs"] = [
                    [_scale(b) for b in f] if isinstance(f[0], (list, tuple))
                    else _scale(f)
                    for f in lay["subs"]]
        emb = (tables.get("MARK_EMBED") or {}).get("0x%04x" % g["cp"])
        if dur_mark[j] != "none" and emb:
            # mark printed INSIDE the character (no modifier record needed)
            w, h = g["x1"] - g["x0"], g["y1"] - g["y0"]
            boxes = [[round(g["x0"] + b[0] * w, 1), round(g["y0"] + b[1] * h, 1),
                      round(g["x0"] + b[2] * w, 1), round(g["y0"] + b[3] * h, 1)]
                     for b in emb["boxes_norm"]]
            if len(boxes) == int(emb["added_beats"]):
                parts["marks"] = boxes
        m = dur_mod[j]
        if dur_mark[j] != "none" and "marks" not in parts and m is not None:
            cph = "0x%04x" % m["cp"]
            mk = mark_ink.get(cph)
            if mk:
                boxes = None
                for r in inst_ix.get((cph, m["line"]), []):
                    if abs(r["x"] - m["x"]) < 0.5:
                        boxes = r["ink_boxes"]
                        break
                if boxes is None:
                    boxes = [[m["x"] + d[0], g["y0"] + d[1],
                              m["x"] + d[2], g["y0"] + d[3]]
                             for d in mk["boxes_rel"]]
                if len(boxes) == int(mk["added_beats"]):
                    parts["marks"] = [[round(float(v), 1) for v in b]
                                      for b in boxes]
        # single-note glyph without a sub layout: tight-ink melodic box so the
        # fill hugs the printed neume rather than the whole em cell — for ALL
        # simple neumes, so their highlight matches the compounds' precision
        if not multi_sub(g["cp"]) and "subs" not in parts and strip_img is not None:
            tight = ink_bbox(strip_img, g["x0"], g["y0"], g["x1"], g["y1"],
                             exclude=parts.get("marks", []))
            if tight:
                parts["subs"] = [[round(v, 1) for v in tight]]
        if parts:
            g["parts"] = parts
            n_subs += "subs" in parts
            n_marks += "marks" in parts
    return n_subs, n_marks


def expand_slots(notes, gor, digor, dur):
    """Replicates note_align5.py's slot expansion (incl. gorgon/synelaf beat
    steals and WEIGHT_OVR/SUBW_OVR) -> (slot_gi, slot_w, slot_sub)."""
    slot_gi, slot_w, slot_sub = [], [], []
    for j, g in enumerate(notes):
        w = dur[j]
        if g["cp"] in YPORRHOE or g["cp"] in KENTIMATA_COMPOUNDS:
            pieces = [w * 0.5, w * 0.5]
        elif g["cp"] == SYNELAF:
            if gor[j]:
                pieces = [1.0, w]
            else:
                pieces = [0.5, w]
                if slot_w:
                    slot_w[-1] = max(0.5, slot_w[-1] - 0.5)
        else:
            pieces = [w]
        if gor[j] and g["cp"] not in GORGON_INTERNAL:
            pieces[0] = 0.5
            if slot_w:
                slot_w[-1] = max(0.5, slot_w[-1] - 0.5)
        if digor[j]:               # digorgon: prev + carrier + next share 1 beat
            pieces[0] = 1.0 / 3
            if len(pieces) >= 2:
                pieces[1] = 1.0 / 3
            if slot_w:
                slot_w[-1] = max(1.0 / 3, slot_w[-1] - 2.0 / 3)
        for si, p in enumerate(pieces):
            p = SUBW_OVR.get((j, si), WEIGHT_OVR.get(j, p) if len(pieces) == 1 else p)
            slot_gi.append(j)
            slot_w.append(p)
            slot_sub.append(si)
    return slot_gi, slot_w, slot_sub


def ison_at(ison_ev, t):
    """Ison level active at time t (aligner semantics: event applies if its
    timestamp is within +0.5s of t)."""
    if not ison_ev:
        return None
    lv = ison_ev[0][1]
    for et, el in ison_ev:
        if et <= t + 0.5:
            lv = el
        else:
            break
    return lv


def load_json(path):
    if path and path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, help="piece working directory")
    ap.add_argument("--out", default=str(here / "data"), help="output dir (default: <annotator>/data)")
    ap.add_argument("--audio", default="master.wav", help="audio filename inside --input")
    ap.add_argument("--strip", default="strip.png")
    ap.add_argument("--score-notes", default="score_notes.json")
    ap.add_argument("--slots", default="slots.json")
    ap.add_argument("--timing", default="timing.json")
    ap.add_argument("--modifiers", default="modifiers.json")
    ap.add_argument("--expected", default="expected_degrees.json")
    ap.add_argument("--ison", default="ison_timeline.json")
    ap.add_argument("--moria", default="moria_track.npy")
    ap.add_argument("--line-centers", default="line_centers.npy")
    ap.add_argument("--barlines", default="barlines.json")
    ap.add_argument("--piece-id", default=None, help="stable id for localStorage autosave (default: input dir name)")
    ap.add_argument("--parts-tables", default=None, metavar="PATH",
                    help="geometry tables JSON (SUB_LAYOUT/MARK_INK[/MARK_INK_instances]); "
                         "when given, notes gain a per-glyph 'parts' field for "
                         "sub-note / duration-mark progressive highlight")
    ap.add_argument("--overrides", default=None, metavar="PATH",
                    help='JSON {"WEIGHT_OVR":{"gi":beats},"SUBW_OVR":[[gi,sub,beats],...]'
                         ',"ATTACH_OVR":{"mi":gi}} replacing the per-piece '
                         "override tables (glyph-index keyed, so they shift "
                         "when glyph extraction changes)")
    args = ap.parse_args()

    global WEIGHT_OVR, SUBW_OVR, ATTACH_OVR
    if args.overrides:
        with open(args.overrides) as f:
            ovr = json.load(f)
        if "WEIGHT_OVR" in ovr:
            WEIGHT_OVR = {int(k): float(v) for k, v in ovr["WEIGHT_OVR"].items()}
        if "SUBW_OVR" in ovr:
            SUBW_OVR = {(int(gi), int(sub)): float(w) for gi, sub, w in ovr["SUBW_OVR"]}
        if "ATTACH_OVR" in ovr:
            ATTACH_OVR = {int(k): int(v) for k, v in ovr["ATTACH_OVR"].items()}

    parts_tables = None
    if args.parts_tables:
        with open(args.parts_tables) as f:
            parts_tables = json.load(f)

    import numpy as np  # deferred so --help works without numpy

    src = Path(args.input).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    piece_id = args.piece_id or src.name

    # ---- required inputs ----
    sn = load_json(src / args.score_notes)
    slots = load_json(src / args.slots)
    if sn is None or slots is None:
        sys.exit(f"missing required input: {args.score_notes} / {args.slots} in {src}")
    notes, anchors = sn["notes"], sn.get("anchors", [])
    line_centers = np.load(src / args.line_centers).tolist()

    # ---- optional inputs ----
    timing = load_json(src / args.timing) or {}
    mods = load_json(src / args.modifiers) or []
    expected = load_json(src / args.expected)      # per-slot absolute degrees
    ison_ev = load_json(src / args.ison) or []
    bars = load_json(src / args.barlines) or []

    # ---- copies ----
    shutil.copyfile(src / args.strip, out / "strip.png")
    shutil.copyfile(src / args.audio, out / "audio.wav")

    # ---- strip geometry ----
    try:
        from PIL import Image
        strip_w, strip_h = Image.open(src / args.strip).size
    except Exception:
        # fall back: parse PNG IHDR directly (width/height at bytes 16..24)
        raw = (src / args.strip).read_bytes()
        strip_w = int.from_bytes(raw[16:20], "big")
        strip_h = int.from_bytes(raw[20:24], "big")

    # ---- machine interpretation (score-side note_align5 replication) ----
    gor, digor, dur, dur_mark, dur_mod, quality, other = attach_modifiers(notes, mods)
    # performance insertions carry their printed marks inside the composited
    # image — no modifier records exist, so force the figure's own semantics
    for j, g in enumerate(notes):
        if g.get("inserted") and g["cp"] == 0xF055:
            gor[j] = True
    e_gi, e_w, e_sub = expand_slots(notes, gor, digor, dur)
    struct_ok = (e_gi == slots["gi"] and e_sub == slots["sub"])
    if not struct_ok:
        print("WARNING: replicated slot expansion does not match slots.json "
              f"({len(e_gi)} vs {len(slots['gi'])} slots) — slots.json wins for "
              "slot structure; per-slot beat weights may be approximate.",
              file=sys.stderr)
    n_slots = len(slots["t"])
    # per-slot weight, keyed to the authoritative slots.json structure
    wmap = {}
    for gi, sub, w in zip(e_gi, e_sub, e_w):
        wmap[(gi, sub)] = w
    slot_w = [wmap.get((slots["gi"][i], slots["sub"][i]), 1.0) for i in range(n_slots)]

    # word text per glyph via anchors (word of glyph g = last anchor with gi <= g)
    word_of_glyph = [""] * len(notes)
    for a in sorted(anchors, key=lambda a: a["gi"]):
        for g in range(a["gi"], len(notes)):
            word_of_glyph[g] = a["text"]
    anchor_gis = {a["gi"] for a in anchors}

    # slots grouped per glyph
    slots_of_glyph = [[] for _ in notes]
    for i in range(n_slots):
        slots_of_glyph[slots["gi"][i]].append(i)

    mcr = []
    for j, g in enumerate(notes):
        sids = slots_of_glyph[j]
        t0 = slots["t"][sids[0]] if sids else None
        rec = {
            "gi": j,
            "cp": hex(g["cp"]),
            "name": glyph_name(g["cp"]),
            "line": g["line"],
            "sub_notes": len(sids),
            "beats": [round(slot_w[i], 3) for i in sids],
            "gorgon": gor[j] or digor[j],
            "duration_mark": dur_mark[j],
            "quality_marks": quality[j],
            "other_marks": other[j],
            "expected_degrees": ([expected[i] for i in sids]
                                 if expected and len(expected) == n_slots else None),
            "ison_at_start": ison_at(ison_ev, t0) if t0 is not None else None,
            "slot_ids": sids,
            "word": word_of_glyph[j],
            "word_start": j in anchor_gis,
        }
        if g.get("inserted"):
            rec["inserted"] = True
        if digor[j]:
            rec["gorgon_kind"] = "digorgon"
        mcr.append(rec)

    # ---- per-slot labels (word text at word-start slots) ----
    labels = [""] * n_slots
    for i in range(n_slots):
        gi, sub = slots["gi"][i], slots["sub"][i]
        if sub == 0 and gi in anchor_gis:
            labels[i] = word_of_glyph[gi]

    # ---- flattened word list from timing.json captions ----
    words = []
    for cap in timing.get("captions", []):
        for wd in cap["words"]:
            words.append({"w": wd["w"], "t0": wd["t0"], "t1": wd["t1"]})

    # ---- downsampled pitch curve ----
    pitch = None
    mp = src / args.moria
    if mp.exists():
        mor = np.load(mp)
        step = max(1, round(PITCH_DT / MORIA_SRC_DT))
        ds = mor[::step]
        pitch = {
            "dt": MORIA_SRC_DT * step,
            "moria": [None if not np.isfinite(v) else round(float(v), 1) for v in ds],
        }

    duration = timing.get("duration")
    if duration is None:
        try:
            import wave
            with wave.open(str(src / args.audio)) as w:
                duration = w.getnframes() / w.getframerate()
        except Exception:
            duration = (slots["t"][-1] + 5) if slots["t"] else 60.0

    # ---- optional per-glyph parts (sub-note / duration-mark ink boxes) ----
    n_parts_subs = n_parts_marks = 0
    if parts_tables is not None:
        strip_img = None
        try:
            from PIL import Image
            strip_img = Image.open(src / args.strip)
        except Exception as e:
            print(f"note: no strip image for tight-ink boxes ({e})", file=sys.stderr)
        n_parts_subs, n_parts_marks = build_parts(notes, dur_mark, dur_mod,
                                                  parts_tables, strip_img)

    import hashlib
    data_rev = hashlib.md5(json.dumps(
        [slots["gi"], slots["sub"]]).encode()).hexdigest()[:10]
    analytical = load_json(src / "analytical.json")
    ana_entries = ([e for e in analytical.values() if e.get("span")]
                   if isinstance(analytical, dict) else [])

    data = {
        "meta": {
            "piece_id": piece_id,
            "data_rev": data_rev,   # slot-structure hash: stale localStorage keys off
            "duration": round(float(duration), 3),
            "strip_w": strip_w,
            "strip_h": strip_h,
            "line_centers": line_centers,
            "audio": "audio.wav",
            "strip": "strip.png",
            "slot_struct_verified": struct_ok,
        },
        "notes": notes,
        "anchors": anchors,
        "slots": {"t": slots["t"], "gi": slots["gi"], "sub": slots["sub"],
                  "w": [round(w, 3) for w in slot_w], "label": labels},
        "words": words,
        "pitch": pitch,
        "ison": ison_ev,
        "barlines": [{"line": b["line"], "x": b["x"]} for b in bars],
        "analytical": ana_entries,
    }

    with open(out / "annotator_data.json", "w") as f:
        json.dump(data, f)
    with open(out / "mcr_interpretation.json", "w") as f:
        json.dump(mcr, f, indent=1)

    print(f"piece '{piece_id}': {len(notes)} glyphs, {n_slots} slots, "
          f"{len(words)} words, pitch={'yes' if pitch else 'no'}, "
          f"slot structure {'VERIFIED against slots.json' if struct_ok else 'MISMATCH (see warning)'}")
    if parts_tables is not None:
        print(f"parts: {n_parts_subs} glyphs with sub-note boxes, "
              f"{n_parts_marks} with duration-mark boxes")
    print(f"wrote {out}/annotator_data.json, mcr_interpretation.json, strip.png, audio.wav")


if __name__ == "__main__":
    main()
