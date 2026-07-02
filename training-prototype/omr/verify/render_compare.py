#!/usr/bin/env python3
"""render_compare.py — side-by-side verification of extracted MusicXML vs
the original PDF engraving, one image per system.

For every system of every piece:
  top    = crop of the original PDF (pymupdf, using the extractor's own
           staff/measure coordinates, generous margins for lyrics/ledger)
  bottom = the SAME measure range rendered from the extracted MusicXML with
           verovio (breaks off, single system)

Output: verify/out/<piece>_sys<NN>_m<a>-<b>.png  — walk these by eye.

Usage:  .venv/bin/python verify/render_compare.py [piece ...]
        pieces default to: trisagion cherubic anaphora
"""
from __future__ import annotations

import io
import os
import re
import sys

import fitz
import verovio
import cairosvg
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OMR = os.path.dirname(HERE)
sys.path.insert(0, OMR)
import vector_extract  # noqa: E402

PIECES = {
    "trisagion": ("pdfs/01_trisagion_lozowchuk_satb.pdf", None),
    "cherubic": ("pdfs/02_cherubichymn_lozowchuk_adapted_satb.pdf", None),
    "anaphora": ("pdfs/03_anaphora_lozowchuk_satb.pdf", None),
}

ZOOM = 3.0


def crop_pdf_system(doc, sy, sp):
    page = doc[sy.page - 1]
    x0 = min(s.x0 for s in sy.staves) - 14
    x1 = max(s.x1 for s in sy.staves) + 6
    top = sy.staves[0].top - 6 * sp
    bot = sy.staves[-1].bot + 7 * sp
    clip = fitz.Rect(max(0, x0), max(0, top),
                     min(page.rect.x1, x1), min(page.rect.y1, bot))
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip)
    return Image.open(io.BytesIO(pix.tobytes("png")))


# ---------------------------------------------------------------- xml slicing

MEASURE_RE = re.compile(r'(    <measure number="(\d+)"[^>]*>.*?</measure>)',
                        re.S)


def slice_measures(xml, m_from, m_to):
    """Return a standalone MusicXML with only PRINTED measures m_from..m_to
    (matching the measure `number` attribute — split segments share their
    printed number), carrying forward divisions/key/time/clef state."""
    head, tail = xml.split("  <part id=", 1)
    parts = ("  <part id=" + tail).split("  </part>\n")
    out_parts = []
    for ptxt in parts:
        if "<measure" not in ptxt:
            continue
        pid = ptxt.split('"', 2)[1]
        measures = MEASURE_RE.findall(ptxt)
        state = {"divisions": None, "key": None, "time": None, "clef": None}
        kept = []
        for m, num in measures:
            i = int(num)
            if i < m_from:
                for tag in ("divisions", "key", "time", "clef"):
                    mm = re.findall(rf"<{tag}[^>]*>.*?</{tag}>", m, re.S)
                    if mm:
                        state[tag] = mm[-1]
            elif i <= m_to:
                if not kept:  # first kept measure: inject carried state
                    inject = "".join(state[t] for t in
                                     ("divisions", "key", "time", "clef")
                                     if state[t]
                                     and f"<{t.split()[0]}" not in m)
                    if inject:
                        if "<attributes>" in m:
                            m = m.replace("<attributes>",
                                          "<attributes>" + inject, 1)
                        else:
                            m = m.replace(">", ">\n      <attributes>" +
                                          inject + "</attributes>", 1)
                kept.append(m)
        out_parts.append(f'  <part id="{pid}">\n' + "\n".join(kept) +
                         "\n  </part>\n")
    return head + "".join(out_parts) + "</score-partwise>"


def render_verovio(xml_snippet, px_width):
    tk = verovio.toolkit()
    tk.setOptions({
        "breaks": "none",
        "scale": 40,
        "pageWidth": 3000,
        "adjustPageHeight": True,
        "adjustPageWidth": True,
        "header": "none",
        "footer": "none",
        "spacingLinear": 0.25,
        "spacingNonLinear": 0.6,
    })
    if not tk.loadData(xml_snippet):
        return None
    svg = tk.renderToSVG(1)
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=px_width,
                           background_color="white")
    img = Image.open(io.BytesIO(png))
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[3])
        img = bg
    return img


def label(img, text):
    out = Image.new("RGB", (img.width, img.height + 22), "white")
    out.paste(img, (0, 22))
    ImageDraw.Draw(out).text((6, 4), text, fill="black")
    return out


def run_piece(name):
    pdf_rel, _ = PIECES[name]
    pdf = os.path.join(OMR, pdf_rel)
    report = vector_extract.Report()
    result = vector_extract.build_score(pdf, report=report)
    xml = vector_extract.emit_musicxml(result)
    doc = fitz.open(pdf)
    meta = result["meta"]
    systems = result["systems"]

    # group measure indices by system
    by_sys = {}
    for mi, m in enumerate(meta):
        by_sys.setdefault(m["system_index"], []).append(mi)

    outdir = os.path.join(HERE, "out")
    os.makedirs(outdir, exist_ok=True)
    for si, mis in sorted(by_sys.items()):
        sy = systems[si]
        sp = meta[mis[0]]["sp"]
        m_from, m_to = mis[0] + 1, mis[-1] + 1
        pdf_img = crop_pdf_system(doc, sy, sp)
        snippet = slice_measures(xml, m_from, m_to)
        our_img = render_verovio(snippet, pdf_img.width)
        if our_img is None:
            print(f"  !! verovio failed on {name} sys{si} m{m_from}-{m_to}")
            continue
        a = label(pdf_img.convert("RGB"),
                  f"PDF  {name}  p{sy.page} system {si + 1}  "
                  f"measures {m_from}-{m_to}")
        b = label(our_img.convert("RGB"),
                  f"OURS (verovio render of extracted MusicXML)  "
                  f"measures {m_from}-{m_to}")
        combo = Image.new("RGB", (max(a.width, b.width),
                                  a.height + b.height + 8), "white")
        combo.paste(a, (0, 0))
        ImageDraw.Draw(combo).rectangle(
            [0, a.height + 2, combo.width, a.height + 5], fill="#888")
        combo.paste(b, (0, a.height + 8))
        fn = os.path.join(outdir, f"{name}_sys{si + 1:02d}_m{m_from}-{m_to}.png")
        combo.save(fn)
        print(f"  wrote {os.path.relpath(fn, OMR)}")


if __name__ == "__main__":
    names = sys.argv[1:] or list(PIECES)
    for n in names:
        print(f"[{n}]")
        run_piece(n)
