#!/usr/bin/env python3
"""annotate.py — audit overlay: draw every extracted event back onto the
original PDF at its own coordinates.

Per system image:
  * voice-colored dot on every captured notehead (S red / A blue / T green /
    B orange); rests get a hollow square at the rest glyph x.
  * label = pitch letter+octave + duration shorthand (+ '.' dots, '~' tie
    start, 'u' assumed unison, printed accidental).
  * dashed verticals at detected barline x positions.

Reading the output: a printed notehead with NO dot = dropped note; a dot on
empty paper = spurious; wrong color = voice-routing bug; label vs staff
position = pitch bug; label duration vs printed flags/beams = duration bug.

Usage: .venv/bin/python verify/annotate.py [trisagion cherubic anaphora]
"""
from __future__ import annotations

import io
import os
import sys

import fitz
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OMR = os.path.dirname(HERE)
sys.path.insert(0, OMR)
import vector_extract  # noqa: E402
from vector_extract import LETTERS  # noqa: E402

PIECES = {
    "trisagion": "pdfs/01_trisagion_lozowchuk_satb.pdf",
    "cherubic": "pdfs/02_cherubichymn_lozowchuk_adapted_satb.pdf",
    "anaphora": "pdfs/03_anaphora_lozowchuk_satb.pdf",
}
ZOOM = 3.0
COLORS = {"S": (220, 30, 30), "A": (30, 80, 230), "T": (20, 150, 40),
          "B": (235, 130, 0)}
ACC_TXT = {-1: "b", 0: "n", 1: "#"}

try:
    FONT = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 15)
except OSError:
    FONT = ImageFont.load_default()


def dur_txt(e):
    base = {8.0: "B", 4.0: "W", 2.0: "H", 1.0: "Q", 0.5: "E", 0.25: "S",
            0.125: "T"}.get(e.beats, f"{e.beats}")
    return base + "." * e.dots


def annotate_system(doc, sy, meta_rows, zoom=ZOOM, x_window=None):
    global ZOOM
    ZOOM = zoom
    page = doc[sy.page - 1]
    sp = sy.staves[0].sp
    x0 = min(s.x0 for s in sy.staves) - 14
    x1 = max(s.x1 for s in sy.staves) + 6
    if x_window:
        x0, x1 = x_window[0] - 3 * sp, x_window[1] + 2 * sp
    top = sy.staves[0].top - 6 * sp
    bot = sy.staves[-1].bot + 7 * sp
    clip = fitz.Rect(max(0, x0), max(0, top),
                     min(page.rect.x1, x1), min(page.rect.y1, bot))
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    d = ImageDraw.Draw(img)

    def P(x, y):
        return ((x - clip.x0) * ZOOM, (y - clip.y0) * ZOOM)

    # barlines
    for bx in sy.bar_xs:
        X, _ = P(bx, 0)
        for yy in range(0, img.height, 14):
            d.line([(X, yy), (X, yy + 7)], fill=(160, 160, 160), width=2)

    # measure numbers (global numbering from meta rows)
    for row in meta_rows:
        (lo, hi) = row["x_range"]
        X, Y = P((lo + hi) / 2, sy.staves[0].top - 4.5 * sp)
        d.text((X, Y), f"m{row['mi'] + 1}", fill=(120, 0, 120), font=FONT)

    for v, evs in sy.events.items():
        col = COLORS.get(v, (0, 0, 0))
        for idx, e in enumerate(evs):
            stag = idx % 3
            above = v in ("S", "T")
            if above:
                ly = e.staff.top - (2.1 + 0.95 * stag) * e.staff.sp
            else:
                ly = e.staff.bot + (1.3 + 0.95 * stag) * e.staff.sp
            _, LY = P(0, ly)
            if e.kind == "rest":
                X, Y = P(e.x, e.staff.mid)
                d.rectangle([X - 5, Y - 5, X + 5, Y + 5], outline=col, width=2)
                d.text((X - 8, LY), "r" + dur_txt(e), fill=col, font=FONT)
                continue
            for h in e.heads:
                X, Y = P(h.g.cx, h.g.y)
                r = 5
                d.ellipse([X - r, Y - r, X + r, Y + r], fill=col)
                lab = f"{LETTERS[h.step % 7]}{h.step // 7}"
                if h.acc is not None:
                    lab += ACC_TXT[h.acc]
                lab += dur_txt(e)
                if e.tie_start:
                    lab += "~"
                if e.unison_assumed:
                    lab += "u"
                d.text((X - 14, LY), lab, fill=col, font=FONT)
                LY += 16  # chord heads: stack labels downward
    return img


def run_piece(name, only_measure=None):
    pdf = os.path.join(OMR, PIECES[name])
    report = vector_extract.Report()
    result = vector_extract.build_score(pdf, report=report)
    doc = fitz.open(pdf)
    meta = result["meta"]
    systems = result["systems"]
    by_sys = {}
    for mi, m in enumerate(meta):
        m2 = dict(m)
        m2["mi"] = mi
        by_sys.setdefault(m["system_index"], []).append(m2)
    outdir = os.path.join(HERE, "out")
    os.makedirs(outdir, exist_ok=True)
    for si, rows in sorted(by_sys.items()):
        if only_measure is not None:
            hit = [r for r in rows if r["mi"] + 1 == only_measure]
            if not hit:
                continue
            img = annotate_system(doc, systems[si], hit, zoom=6.0,
                                  x_window=hit[0]["x_range"])
            fn = os.path.join(outdir, f"{name}_zoom_m{only_measure}.png")
            img.save(fn)
            print(f"  wrote {os.path.relpath(fn, OMR)}")
            return
        img = annotate_system(doc, systems[si], rows)
        m_from, m_to = rows[0]["mi"] + 1, rows[-1]["mi"] + 1
        fn = os.path.join(outdir,
                          f"{name}_ann{si + 1:02d}_m{m_from}-{m_to}.png")
        img.save(fn)
        print(f"  wrote {os.path.relpath(fn, OMR)}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    om = None
    if "-m" in sys.argv:
        om = int(sys.argv[sys.argv.index("-m") + 1])
        args = [args[0]]
    for n in (args or list(PIECES)):
        print(f"[{n}]")
        run_piece(n, only_measure=om)
