#!/usr/bin/env python3
"""pipeline.py — ChanterLab SATB score-extraction pipeline (bake-off winner).

PDF in -> 4-voice MusicXML out + confidence report.

The engine is vector extraction (`vector_extract.py`), which won the
2026-07-02 OMR bake-off against oemer and Audiveris on the Antiochian Sacred
Music Library corpus (see docs/choir-training-roadmap.md, "OMR bake-off").
It only works on born-digital engraving PDFs (music placed as SMuFL font
glyphs + vector paths). Scanned/photographed scores need a raster OMR
fallback — detected and refused here rather than guessed at.

Usage:
  .venv/bin/python pipeline.py pdfs/01_trisagion_lozowchuk_satb.pdf \
      -o out/trisagion.musicxml
  # options
  #   --report PATH     write the JSON confidence report (default: alongside -o)
  #   --pages 2,3       restrict to 1-based page numbers
  #   --min-integrity N fail (exit 2) if <N% of measures have consistent
  #                     voice beat sums (default 90)

Exit codes: 0 ok · 2 low confidence · 3 not a born-digital music PDF
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import fitz

import vector_extract


def is_born_digital_music(pdf_path, pages=None):
    """The engine needs music-font glyphs. Scans have none (just one big
    image per page); text-only PDFs have no music fonts."""
    doc = fitz.open(pdf_path)
    music_fonts = 0
    for pno in range(len(doc)):
        if pages and (pno + 1) not in pages:
            continue
        for f in doc[pno].get_fonts():
            name = f[3] or ""
            if any(k in name for k in ("Bravura", "Opus", "Maestro",
                                       "Leland", "Emmentaler")):
                music_fonts += 1
    return music_fonts > 0


def main():
    ap = argparse.ArgumentParser(
        description="PDF -> 4-voice SATB MusicXML + confidence report")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True, help="output MusicXML path")
    ap.add_argument("--report", help="JSON confidence report path "
                                     "(default: <out>.report.json)")
    ap.add_argument("--pages", help="1-based page list, e.g. 2,3,4")
    ap.add_argument("--min-integrity", type=float, default=90.0)
    args = ap.parse_args()

    pages = [int(p) for p in args.pages.split(",")] if args.pages else None
    report_path = args.report or os.path.splitext(args.out)[0] + ".report.json"

    if not is_born_digital_music(args.pdf, pages):
        print(f"ERROR: {args.pdf} has no music-font glyphs — not a "
              f"born-digital engraving. This pipeline does not do raster "
              f"OMR; see the roadmap for the (unsolved) scan path.",
              file=sys.stderr)
        sys.exit(3)

    result, rep, _xml = vector_extract.run(
        args.pdf, args.out, report_path, pages)

    integrity = rep["stats"].get("measure_integrity_pct", 0.0)
    print(f"\n[pipeline] wrote {args.out}")
    print(f"[pipeline] confidence report: {report_path}")
    print(f"[pipeline] measure integrity {integrity}% "
          f"(threshold {args.min_integrity}%) — "
          f"{len(rep['warnings'])} warnings")
    if integrity < args.min_integrity:
        print("[pipeline] LOW CONFIDENCE — review the report before using "
              "this score for practice.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
