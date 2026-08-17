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
GORGON_NAME = {0xF053: "gorgon", 0xF073: "gorgon", 0xF048: "gorgon(dotted)"}
DURATION_CP = {0xF061: 2.0, 0xF041: 2.0, 0xF027: 2.0, 0xF06B: 3.0}
DURATION_NAME = {0xF061: "klasma", 0xF041: "klasma", 0xF027: "apli", 0xF06B: "diple"}
# quality marks documented for this font (psifiston cp not yet confirmed for
# EZ-Psaltic — add it here once identified; unclassified attached marks are
# still surfaced in each record's other_marks so nothing is hidden)
QUALITY_NAME = {0xF022: "antikenoma", 0xF05B: "omalon"}
PSIFISTON_CPS: set = set()                  # fill in when the cp is confirmed
YPORRHOE, SYNELAF = 0xF05F, 0xF050
KENTIMATA_COMPOUNDS = {0xF0D7, 0xF06F, 0xF077, 0xF04F}
ATTACH_MAX_D = 30                           # px: modifier-to-glyph attach radius
# piece-specific weight overrides (glyph index -> beats); Eothinon XI values:
WEIGHT_OVR = {53: 2.0, 59: 0.5, 82: 1.0}
SUBW_OVR = {(58, 1): 0.5}

GLYPH_NAME = {
    0xF021: "apostrofos",
    0xF030: "ison",
    0xF031: "oligon",
    0xF05F: "yporrhoe",
    0xF050: "ison+kentimata",
    0xF060: "kentimata",
    0xF0D7: "kentimata-compound",
    0xF06F: "kentimata-compound",
    0xF077: "kentimata-compound",
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
    dur = [1.0] * n
    dur_mark = ["none"] * n
    quality = [[] for _ in range(n)]
    other = [[] for _ in range(n)]
    for m in mods or []:
        cp = m["cp"]
        if cp == 0x20:
            continue
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
        elif cp in DURATION_CP:
            if DURATION_CP[cp] > dur[best]:
                dur[best] = DURATION_CP[cp]
                dur_mark[best] = DURATION_NAME[cp]
            elif dur_mark[best] == "none":
                dur_mark[best] = DURATION_NAME[cp]
        elif cp in QUALITY_NAME:
            quality[best].append(QUALITY_NAME[cp])
        elif cp in PSIFISTON_CPS:
            quality[best].append("psifiston")
        else:
            other[best].append(hex(cp))
    return gor, dur, dur_mark, quality, other


def expand_slots(notes, gor, dur):
    """Replicates note_align5.py's slot expansion (incl. gorgon/synelaf beat
    steals and WEIGHT_OVR/SUBW_OVR) -> (slot_gi, slot_w, slot_sub)."""
    slot_gi, slot_w, slot_sub = [], [], []
    for j, g in enumerate(notes):
        w = dur[j]
        if g["cp"] == YPORRHOE or g["cp"] in KENTIMATA_COMPOUNDS:
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
        if gor[j]:
            pieces[0] = 0.5
            if slot_w:
                slot_w[-1] = max(0.5, slot_w[-1] - 0.5)
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
    args = ap.parse_args()

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
    gor, dur, dur_mark, quality, other = attach_modifiers(notes, mods)
    e_gi, e_w, e_sub = expand_slots(notes, gor, dur)
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
            "gorgon": gor[j],
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

    data = {
        "meta": {
            "piece_id": piece_id,
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
    }

    with open(out / "annotator_data.json", "w") as f:
        json.dump(data, f)
    with open(out / "mcr_interpretation.json", "w") as f:
        json.dump(mcr, f, indent=1)

    print(f"piece '{piece_id}': {len(notes)} glyphs, {n_slots} slots, "
          f"{len(words)} words, pitch={'yes' if pitch else 'no'}, "
          f"slot structure {'VERIFIED against slots.json' if struct_ok else 'MISMATCH (see warning)'}")
    print(f"wrote {out}/annotator_data.json, mcr_interpretation.json, strip.png, audio.wav")


if __name__ == "__main__":
    main()
