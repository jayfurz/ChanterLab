#!/usr/bin/env python3
"""legacy_glyph_atlas.py — visual contact sheets for legacy Finale music-font glyphs.

Most survey PDFs from the Antiochian Sacred Music Library engrave their notes with
legacy Finale fonts ("Maestro", "Petrucci"), often subset-embedded with a random
6-letter prefix (e.g. "DDKCOB+Maestro"). Each codepoint in those fonts maps to a
musical symbol (notehead, rest, clef, accidental, ...) but the mapping is private
and undocumented. This script does NOT guess the mapping — it produces the raw
material a human/model needs to classify every codepoint by LOOKING at real usage:

  * per-font-family contact sheets (one row per codepoint) with a tight crop of the
    glyph plus wider "context" crops that show the surrounding staff/notes, and
  * atlas_summary.json with counts, PDF spread, and a size ratio vs. the font's
    dominant glyph (handy for spotting grace notes / small ornaments).

Outputs land in pdfs/survey/atlas/ (sheets) and pdfs/survey/atlas/crops/ (every crop).

Usage:
  .venv/bin/python legacy_glyph_atlas.py
  .venv/bin/python legacy_glyph_atlas.py --survey-dir pdfs/survey --max-examples 6
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import unicodedata
from collections import defaultdict

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ----- tunables -------------------------------------------------------------
LEGACY_KEYS = ("maestro", "petrucci")   # case-insensitive font-name markers
ZOOM = 6                                 # get_pixmap matrix scale (spec: Matrix(6,6))
TIGHT_PAD = 0.30                         # expand char bbox by 30% each side
TIGHT_MIN_HALF_W = 0.55                  # ...but hairline glyphs (barlines) get at
                                         #    least this many span-sizes of half-width
# Context window. NB: PyMuPDF reports each char's bbox with the font's FULL line
# height (~2.3x the span size) for *every* glyph, so the raw bbox already spans the
# staff vertically but is only glyph-wide horizontally. A literal "5x w and 5x h"
# therefore yields a tall empty sliver. To meet the real goal — surrounding staff
# lines / neighbouring notes visible, glyph centred — we build a landscape window:
# wide enough for horizontal neighbours, tall enough to cover the staff.
CTX_HALF_W = 3.5                         # context half-width, in span-size units
CTX_HALF_H = 1.9                         # context half-height, in span-size units
CTX_MIN_W_GLYPH = 2.5                    # ...and at least this many glyph-widths wide
MAX_EXAMPLES = 6                         # kept per codepoint
CTX_ON_SHEET = 3                         # context crops shown per row

# ----- sheet layout ---------------------------------------------------------
ROW_H = 140                              # uniform row height (px)
PAD = 6
LABEL_W = 190
TIGHT_W = 200
CTX_W = 516                              # LABEL+TIGHT+3*CTX = 1938  (<= ~2000)
ROWS_PER_SHEET = 20                      # split families with > 20 codepoints
BG = (255, 255, 255)
GRID = (222, 222, 222)
INK = (20, 20, 20)
SUB = (110, 110, 110)


def base_family(font_name: str) -> str:
    """Strip a subset prefix ('DDKCOB+Maestro' -> 'Maestro')."""
    return font_name.split("+", 1)[1] if "+" in font_name else font_name


def is_legacy(font_name: str) -> bool:
    low = font_name.lower()
    return any(k in low for k in LEGACY_KEYS)


def uni_name(cp: int) -> str:
    try:
        return unicodedata.name(chr(cp))
    except ValueError:
        if 0xE000 <= cp <= 0xF8FF:
            return "<Private Use Area>"
        return "<unnamed>"


def is_symbolish(cp: int) -> bool:
    """A codepoint that would be odd for a *text* font but normal for a music font."""
    if 0xE000 <= cp <= 0xF8FF:
        return True
    try:
        cat = unicodedata.category(chr(cp))
    except Exception:
        return True
    return cat[0] in ("S", "C") or cp >= 0x2000


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Scalable default font (Pillow >= 10 supports size=)."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Phase 1 — scan every PDF, collect legacy-music char instances
# ---------------------------------------------------------------------------
def scan(pdf_paths):
    """Return (instances, other_fonts).

    instances: {(family, cp): [ {pdf_i, page, bbox, size}, ... ]}
    other_fonts: {family: Counter-ish dict for non-legacy fonts, used to flag
                  candidate music fonts we might be missing}
    """
    instances = defaultdict(list)
    other_total = defaultdict(int)
    other_sym = defaultdict(int)
    other_cps = defaultdict(set)
    other_pdfs = defaultdict(set)

    for pdf_i, path in enumerate(pdf_paths):
        try:
            doc = fitz.open(path)
        except Exception as e:
            print(f"  skip (open failed): {os.path.basename(path)}  [{e}]")
            continue
        with doc:
            for page in doc:
                try:
                    raw = page.get_text("rawdict")
                except Exception:
                    continue
                pno = page.number
                for block in raw.get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            font = span.get("font", "") or ""
                            size = float(span.get("size", 0.0) or 0.0)
                            fam = base_family(font)
                            legacy = is_legacy(font)
                            for ch in span.get("chars", []):
                                cp = ord(ch["c"])
                                if legacy:
                                    bb = ch["bbox"]
                                    instances[(fam, cp)].append(
                                        {"pdf_i": pdf_i, "page": pno,
                                         "bbox": (bb[0], bb[1], bb[2], bb[3]),
                                         "size": size}
                                    )
                                else:
                                    other_total[fam] += 1
                                    other_cps[fam].add(cp)
                                    other_pdfs[fam].add(pdf_i)
                                    if is_symbolish(cp):
                                        other_sym[fam] += 1
    other = {
        fam: {
            "total_chars": other_total[fam],
            "symbolish_chars": other_sym[fam],
            "sym_frac": other_sym[fam] / other_total[fam] if other_total[fam] else 0.0,
            "distinct_cps": len(other_cps[fam]),
            "n_pdfs": len(other_pdfs[fam]),
        }
        for fam in other_total
    }
    return instances, other


# ---------------------------------------------------------------------------
# Phase 2 — pick example instances (prefer different PDFs, then largest bbox)
# ---------------------------------------------------------------------------
def area(bbox):
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def pick_examples(insts, k=MAX_EXAMPLES):
    ordered = sorted(insts, key=lambda r: area(r["bbox"]), reverse=True)
    chosen, used_pdfs = [], set()
    # first pass: largest bbox from each distinct PDF
    for r in ordered:
        if r["pdf_i"] not in used_pdfs:
            chosen.append(r)
            used_pdfs.add(r["pdf_i"])
            if len(chosen) >= k:
                return chosen
    # second pass: fill remaining slots with next-largest (repeat PDFs allowed)
    for r in ordered:
        if r in chosen:
            continue
        chosen.append(r)
        if len(chosen) >= k:
            break
    return chosen


# ---------------------------------------------------------------------------
# Phase 3 — render crops
# ---------------------------------------------------------------------------
def tight_clip(bbox, size, page_rect):
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2
    half_w = max(w / 2 + TIGHT_PAD * w, TIGHT_MIN_HALF_W * size)
    r = fitz.Rect(cx - half_w, y0 - TIGHT_PAD * h, cx + half_w, y1 + TIGHT_PAD * h)
    return _sanitize(r, page_rect)


def ctx_clip(bbox, size, page_rect):
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w = max(CTX_HALF_W * size, CTX_MIN_W_GLYPH * w)
    half_h = max(CTX_HALF_H * size, 0.6 * h)
    r = fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return _sanitize(r, page_rect)


def _sanitize(rect, page_rect):
    r = rect & page_rect                      # clamp to page
    if r.is_empty or r.width < 1 or r.height < 1:
        # degenerate (e.g. space glyph): grow a hair so the pixmap is non-empty
        r = fitz.Rect(rect.x0, rect.y0, rect.x0 + 4, rect.y0 + 4) & page_rect
        if r.is_empty:
            r = fitz.Rect(page_rect.x0, page_rect.y0,
                          page_rect.x0 + 4, page_rect.y0 + 4)
    return r


def render_clip(page, clip):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=clip, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def render_all(instances, examples, pdf_paths, crops_dir):
    """Render tight+context crops for every chosen example.

    Returns thumbs: {(fam, cp): [ {"tight": Image, "ctx": Image}, ... ]}
    keeping only small thumbnails in memory; full-res crops are written to disk.
    """
    os.makedirs(crops_dir, exist_ok=True)
    # group render jobs by pdf so each file opens once
    jobs = defaultdict(list)  # pdf_i -> [(key, ex_idx, page, bbox, size)]
    for key, exs in examples.items():
        for ex_idx, r in enumerate(exs):
            jobs[r["pdf_i"]].append((key, ex_idx, r["page"], r["bbox"], r["size"]))

    thumbs = {key: [None] * len(exs) for key, exs in examples.items()}
    t_max = (TIGHT_W - 2 * PAD, ROW_H - 2 * PAD)
    c_max = (CTX_W - 2 * PAD, ROW_H - 2 * PAD)

    for pdf_i, joblist in jobs.items():
        path = pdf_paths[pdf_i]
        stem = os.path.splitext(os.path.basename(path))[0][:32]
        try:
            doc = fitz.open(path)
        except Exception as e:
            print(f"  render skip (reopen failed): {os.path.basename(path)} [{e}]")
            continue
        with doc:
            # order jobs by page to keep page loads sequential
            for key, ex_idx, pno, bbox, size in sorted(joblist, key=lambda j: j[2]):
                fam, cp = key
                page = doc[pno]
                pr = page.rect
                tag = f"{fam}_U{cp:04X}_ex{ex_idx}_{stem}_p{pno+1}"
                try:
                    t_img = render_clip(page, tight_clip(bbox, size, pr))
                    c_img = render_clip(page, ctx_clip(bbox, size, pr))
                except Exception as e:
                    print(f"  render fail {tag}: {e}")
                    continue
                t_img.save(os.path.join(crops_dir, tag + "_tight.png"))
                c_img.save(os.path.join(crops_dir, tag + "_ctx.png"))
                tt = t_img.copy(); tt.thumbnail(t_max, Image.LANCZOS)
                ct = c_img.copy(); ct.thumbnail(c_max, Image.LANCZOS)
                thumbs[key][ex_idx] = {"tight": tt, "ctx": ct}
    return thumbs


# ---------------------------------------------------------------------------
# Phase 4 — contact sheets
# ---------------------------------------------------------------------------
def paste_centered(sheet, img, col_x, col_w, row_y):
    if img is None:
        return
    x = col_x + (col_w - img.width) // 2
    y = row_y + (ROW_H - img.height) // 2
    sheet.paste(img, (x, y))


def build_sheets(family, rows, thumbs, stats, atlas_dir):
    """rows: list of cp sorted by count desc. Returns list of written sheet paths."""
    f_main = load_font(16)
    f_sub = load_font(11)
    f_hdr = load_font(15)

    sheet_w = LABEL_W + TIGHT_W + CTX_ON_SHEET * CTX_W
    header_h = 26
    written = []
    chunks = [rows[i:i + ROWS_PER_SHEET] for i in range(0, len(rows), ROWS_PER_SHEET)]
    multi = len(chunks) > 1

    tight_x = LABEL_W
    ctx_x = [LABEL_W + TIGHT_W + c * CTX_W for c in range(CTX_ON_SHEET)]
    sep_x = [LABEL_W, LABEL_W + TIGHT_W] + ctx_x[1:]  # vertical rule positions

    for si, chunk in enumerate(chunks, 1):
        sheet_h = header_h + len(chunk) * (ROW_H + PAD) + PAD
        sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
        d = ImageDraw.Draw(sheet)

        cap = f"{family}  —  {len(rows)} codepoints"
        if multi:
            cap += f"   (sheet {si}/{len(chunks)})"
        d.text((PAD, 6), cap, font=f_hdr, fill=INK)
        d.text((LABEL_W + PAD, 8), "tight", font=f_sub, fill=SUB)
        d.text((LABEL_W + TIGHT_W + PAD, 8), "context (up to 3 examples)",
               font=f_sub, fill=SUB)

        y = header_h
        for cp in chunk:
            st = stats[(family, cp)]
            # separators
            d.line([(0, y), (sheet_w, y)], fill=GRID)
            for cx in sep_x:
                d.line([(cx, y), (cx, y + ROW_H)], fill=GRID)
            # label block
            lx = PAD
            d.text((lx, y + 8), f"U+{cp:04X}", font=f_main, fill=INK)
            d.text((lx, y + 32), f"count={st['count']}", font=f_main, fill=INK)
            d.text((lx, y + 54), f"pdfs={st['n_pdfs']}", font=f_main, fill=INK)
            d.text((lx, y + 78), f"x{st['size_ratio_vs_dominant']:.2f} size",
                   font=f_sub, fill=SUB)
            name = st["unicode_name"]
            d.text((lx, y + 96), (name[:26]), font=f_sub, fill=SUB)
            if len(name) > 26:
                d.text((lx, y + 110), name[26:52], font=f_sub, fill=SUB)

            exs = thumbs.get((family, cp), [])
            # tight crop of example 1
            if exs and exs[0]:
                paste_centered(sheet, exs[0]["tight"], tight_x, TIGHT_W, y)
            # context crops of up to 3 examples
            for c in range(CTX_ON_SHEET):
                if c < len(exs) and exs[c]:
                    paste_centered(sheet, exs[c]["ctx"], ctx_x[c], CTX_W, y)
            y += ROW_H + PAD
        d.line([(0, y), (sheet_w, y)], fill=GRID)

        name = f"{family}_atlas" + (f"_{si}" if multi else "") + ".png"
        out = os.path.join(atlas_dir, name)
        sheet.save(out)
        written.append(out)
    return written


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey-dir", default=os.path.join(HERE, "pdfs", "survey"))
    ap.add_argument("--max-examples", type=int, default=MAX_EXAMPLES)
    args = ap.parse_args()

    survey_dir = os.path.abspath(args.survey_dir)
    atlas_dir = os.path.join(survey_dir, "atlas")
    crops_dir = os.path.join(atlas_dir, "crops")
    os.makedirs(atlas_dir, exist_ok=True)

    pdf_paths = sorted(glob.glob(os.path.join(survey_dir, "*.pdf")))
    print(f"scanning {len(pdf_paths)} PDFs in {survey_dir}")
    instances, other = scan(pdf_paths)
    print(f"collected {len(instances)} distinct (family, codepoint) pairs")

    # ---- stats per (family, cp) ----
    families = defaultdict(list)  # family -> [cp]
    stats = {}
    for (fam, cp), insts in instances.items():
        sizes = [r["size"] for r in insts]
        n_pdfs = len({r["pdf_i"] for r in insts})
        stats[(fam, cp)] = {
            "cp": f"0x{cp:X}",
            "unicode_name": uni_name(cp),
            "count": len(insts),
            "n_pdfs": n_pdfs,
            "median_size": round(statistics.median(sizes), 2) if sizes else 0.0,
        }
        families[fam].append(cp)

    # dominant glyph (most frequent) per family -> reference size
    dom_size = {}
    for fam, cps in families.items():
        dom_cp = max(cps, key=lambda c: stats[(fam, c)]["count"])
        dom_size[fam] = stats[(fam, dom_cp)]["median_size"] or 1.0
    for (fam, cp), st in stats.items():
        st["size_ratio_vs_dominant"] = round(st["median_size"] / dom_size[fam], 3)

    # ---- pick + render examples ----
    examples = {key: pick_examples(insts, args.max_examples)
                for key, insts in instances.items()}
    print("rendering crops ...")
    thumbs = render_all(instances, examples, pdf_paths, crops_dir)

    # ---- contact sheets ----
    sheet_paths = []
    for fam in sorted(families):
        rows = sorted(families[fam],
                      key=lambda c: stats[(fam, c)]["count"], reverse=True)
        sheet_paths += build_sheets(fam, rows, thumbs, stats, atlas_dir)

    # ---- summary json ----
    summary = []
    for (fam, cp), st in stats.items():
        summary.append({
            "family": fam,
            "cp": st["cp"],
            "unicode_name": st["unicode_name"],
            "count": st["count"],
            "n_pdfs": st["n_pdfs"],
            "median_size": st["median_size"],
            "size_ratio_vs_dominant": st["size_ratio_vs_dominant"],
            "n_examples": len(examples[(fam, cp)]),
        })
    summary.sort(key=lambda r: r["count"], reverse=True)
    summary_path = os.path.join(atlas_dir, "atlas_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=1)

    # ---- report ----
    print("\n=== SHEETS ===")
    for p in sheet_paths:
        print(" ", p)
    print(f"summary: {summary_path}")

    print("\n=== distinct codepoints per family ===")
    for fam in sorted(families):
        print(f"  {fam:10s} {len(families[fam])}")

    print("\n=== summary table (sorted by count desc) ===")
    print(f"{'family':9s} {'cp':8s} {'count':>6s} {'pdfs':>4s} {'ratio':>6s}  unicode_name")
    for r in summary:
        print(f"{r['family']:9s} U+{int(r['cp'],16):04X} {r['count']:6d} "
              f"{r['n_pdfs']:4d} {r['size_ratio_vs_dominant']:6.2f}  {r['unicode_name']}")

    # ---- flag other candidate music fonts ----
    print("\n=== candidate NON-legacy music/symbol fonts (many symbol/PUA glyphs) ===")
    STD = ("times", "arial", "helvetica", "courier", "optima", "janson",
           "bookantiqua", "book antiqua", "castellar", "cgomega", "academico",
           "edwin", "calibri", "cambria", "georgia", "verdana", "palatino",
           "garamond", "tahoma", "segoe")
    flagged = []
    for fam, info in other.items():
        low = fam.lower()
        if any(s in low for s in STD):
            continue
        if info["sym_frac"] >= 0.30 or (info["symbolish_chars"] >= 20 and
                                        info["sym_frac"] >= 0.15):
            flagged.append((fam, info))
    for fam, info in sorted(flagged, key=lambda x: x[1]["symbolish_chars"], reverse=True):
        print(f"  {fam:16s} sym_frac={info['sym_frac']:.2f} "
              f"symbolish={info['symbolish_chars']:4d} distinct_cps={info['distinct_cps']:3d} "
              f"pdfs={info['n_pdfs']} total_chars={info['total_chars']}")
    if not flagged:
        print("  (none)")

    # Byzantine / chant fonts often remap glyphs onto plain letters, so they slip
    # past the symbol heuristic. List remaining non-standard *names* for a human.
    print("\n=== other non-standard-named fonts (letter-mapped; eyeball these too) ===")
    flagged_names = {f for f, _ in flagged}
    extra = []
    for fam, info in other.items():
        low = fam.lower()
        if fam in flagged_names or any(s in low for s in STD) or low.startswith("type3"):
            continue
        if info["distinct_cps"] >= 6 and info["total_chars"] >= 10:
            extra.append((fam, info))
    for fam, info in sorted(extra, key=lambda x: x[1]["total_chars"], reverse=True):
        print(f"  {fam:16s} distinct_cps={info['distinct_cps']:3d} "
              f"pdfs={info['n_pdfs']} total_chars={info['total_chars']} "
              f"sym_frac={info['sym_frac']:.2f}")
    if not extra:
        print("  (none)")


if __name__ == "__main__":
    main()
