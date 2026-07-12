#!/usr/bin/env python3
"""pipeline.py — ChanterLab SATB score-extraction pipeline (bake-off winner).

PDF in -> 4-voice MusicXML out + confidence report.

The engine is vector extraction (`vector_extract.py`), which won the
2026-07-02 OMR bake-off against oemer and Audiveris on the Antiochian Sacred
Music Library corpus (see docs/choir-training-roadmap.md, "OMR bake-off").
It only works on born-digital engraving PDFs (music placed as music-font
glyphs + vector paths). Scanned/photographed scores need a raster OMR
fallback — detected and refused here rather than guessed at.

Many catalog PDFs interleave Byzantine-neume pages and Western staff-notation
pages (often half the PDF each). `classify_pages()` labels every page by the
music-font family it carries (SMuFL, legacy Finale, Byzantine-neume, unnamed
Type3) and whether it has 5-line-staff candidates; `--pages auto` (the default)
then feeds only the Western staff pages to the engine.

Usage:
  .venv/bin/python pipeline.py pdfs/01_trisagion_lozowchuk_satb.pdf \
      -o out/trisagion.musicxml
  # options
  #   --report PATH     write the JSON confidence report (default: alongside -o)
  #   --pages auto      auto-pick Western staff pages (DEFAULT when omitted)
  #   --pages 2,3       restrict to explicit 1-based page numbers
  #   --min-integrity N fail (exit 2) if <N% of measures have consistent
  #                     voice beat sums (default 90)

Exit codes: 0 ok · 2 low confidence · 3 no extractable (Western staff) pages
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

import fitz

import confidence_signals
import vector_extract

# --- music-font families -----------------------------------------------------
# SMuFL is what the engine reads best; legacy Finale (Sonata-codepoint) support
# is being added inside vector_extract.py.  Names are matched as substrings so
# subset prefixes ("ABCDEF+Maestro") and style suffixes fall through.
SMUFL_FONTS = ("Bravura", "Leland", "Petaluma", "Emmentaler",
               "Finale Maestro SMuFL")
LEGACY_FONTS = ("Maestro", "Petrucci", "Sonata", "Opus", "Engraver")
BYZANTINE_FONTS = ("Anastasia", "ATHONITE", "Psaltica")  # + "EZ…" prefix

# A page is extractable only if it carries real Western notation *and* staves.
MUSIC_MIN_GLYPHS = 20   # Western music-font glyphs required to select a page
STAFF_MIN_LINES = 5     # long horizontal lines needed to call it a staff page
TYPE3_MIN_GLYPHS = 40   # "many" unnamed-Type3 glyphs -> treat page as type3

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


def _font_family(font_name):
    """Map a span font name to (family, label).

    family ∈ {smufl, legacy, byzantine, type3, other}.  ``label`` is the human
    font name (subset prefix stripped) used for reporting.
    """
    base = _SUBSET_RE.sub("", font_name or "")
    if base.startswith("Type3"):            # PyMuPDF names unnamed Type3 fonts
        return "type3", "Type3"             # "Type3 (NNN 0 R)"
    for k in SMUFL_FONTS:
        if k in base:
            return "smufl", k
    if "SMuFL" in base:                     # any "... SMuFL" variant is SMuFL,
        return "smufl", base                # not the legacy font it's named for
    for k in LEGACY_FONTS:
        if k in base:
            return "legacy", k
    for k in BYZANTINE_FONTS:
        if k in base:
            return "byzantine", k
    if base.startswith("EZ"):               # EZ… Byzantine font families
        return "byzantine", base
    return "other", base


def _staff_line_candidates(page):
    """Cheap 5-line-staff proxy: count long horizontal vector lines of similar
    length (mirrors the idea in vector_extract._find_staves without clustering
    into 5-line groups — a rough count is enough for page selection)."""
    widths = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p2.y - p1.y) < 0.7 and abs(p2.x - p1.x) > 80:
                    widths.append(abs(p2.x - p1.x))
    if not widths:
        return 0
    mx = max(widths)
    return sum(1 for w in widths if w >= 0.55 * mx)   # near-max-width lines


def classify_pages(pdf_path):
    """Classify every page of a PDF by the music notation it carries.

    Returns a list of per-page dicts (1-based ``page``) with glyph counts by
    family, a staff-candidate count, and a coarse ``kind`` /
    ``selectable`` verdict used by ``--pages auto``::

        {"page", "kind", "selectable", "smufl_glyphs", "legacy_glyphs",
         "western_glyphs", "byzantine_glyphs", "type3_glyphs",
         "staff_candidates", "has_staff", "font", "bucket", "reason"}

    ``kind`` ∈ {western, byzantine, type3, text}.
    """
    doc = fitz.open(pdf_path)
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        counts = defaultdict(int)
        fam_glyphs = defaultdict(int)   # label -> glyphs (for the dominant font)
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    n = len(span.get("chars", []))
                    family, label = _font_family(span["font"])
                    counts[family] += n
                    if family in ("smufl", "legacy", "byzantine"):
                        fam_glyphs[label] += n

        smufl, legacy = counts["smufl"], counts["legacy"]
        byz, t3 = counts["byzantine"], counts["type3"]
        western = smufl + legacy
        staff = _staff_line_candidates(page)
        has_staff = staff >= STAFF_MIN_LINES

        selectable = western >= MUSIC_MIN_GLYPHS and has_staff
        if western > 0 and western >= byz and western >= t3:
            kind = "western"
            # dominant Western font label
            west_labels = {k: v for k, v in fam_glyphs.items()
                           if _font_family(k)[0] in ("smufl", "legacy")}
            font = max(west_labels, key=west_labels.get) if west_labels else "?"
            notation = "SMuFL" if smufl >= legacy else "legacy Finale"
            bucket = f"Western notation ({font}, {notation})"
            if selectable:
                reason = (f"Western notation ({font}, {notation}): "
                          f"{western} music glyphs, {staff} staff lines")
            else:
                why = ("no staff lines" if not has_staff
                       else f"only {western} music glyphs")
                bucket += f" — skipped ({why})"
                reason = f"Western notation ({font}) but {why}"
        elif byz > 0 and byz >= t3:
            kind, selectable = "byzantine", False
            byz_labels = {k: v for k, v in fam_glyphs.items()
                          if _font_family(k)[0] == "byzantine"}
            font = max(byz_labels, key=byz_labels.get) if byz_labels else "?"
            bucket = f"Byzantine-neume notation ({font})"
            reason = f"Byzantine-neume notation ({font}, {byz} glyphs)"
        elif t3 >= TYPE3_MIN_GLYPHS:
            kind, selectable, font = "type3", False, "Type3"
            bucket = "music in unnamed Type3 fonts"
            reason = f"music in unnamed Type3 fonts ({t3} glyphs)"
        else:
            kind, selectable, font = "text", False, None
            bucket = "no music-font glyphs (title/text page)"
            reason = "no music-font glyphs (title/text page)"

        out.append({
            "page": pno + 1, "kind": kind, "selectable": selectable,
            "smufl_glyphs": smufl, "legacy_glyphs": legacy,
            "western_glyphs": western, "byzantine_glyphs": byz,
            "type3_glyphs": t3, "staff_candidates": staff,
            "has_staff": has_staff, "font": font,
            "bucket": bucket, "reason": reason,
        })
    doc.close()
    return out


def select_pages(page_infos):
    """1-based page numbers of the auto-selectable (Western staff) pages."""
    return [p["page"] for p in page_infos if p["selectable"]]


def _page_ranges(nums):
    """[1,2,3,5] -> '1-3,5'."""
    nums = sorted(nums)
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(parts)


def print_selection(page_infos):
    """Print which pages were selected/skipped and why, grouping consecutive
    pages that share a verdict (e.g. 'pages 3-4 selected: Western (Maestro);
    pages 1-2 skipped: Byzantine notation')."""
    runs = []   # (bucket, selectable, [pages]) merged across consecutive pages
    for p in page_infos:
        if runs and runs[-1][0] == p["bucket"]:
            runs[-1][2].append(p["page"])
        else:
            runs.append((p["bucket"], p["selectable"], [p["page"]]))
    print("[pipeline] page auto-selection:")
    for bucket, sel, pages in runs:
        tag = "selected" if sel else "skipped "
        print(f"  {tag}: pages {_page_ranges(pages)} — {bucket}")


def _refuse(pdf, message, code=3):
    print(f"ERROR: {pdf}: {message}", file=sys.stderr)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(
        description="PDF -> 4-voice SATB MusicXML + confidence report")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True, help="output MusicXML path")
    ap.add_argument("--report", help="JSON confidence report path "
                                     "(default: <out>.report.json)")
    ap.add_argument("--pages", default="auto",
                    help="'auto' (default) auto-picks Western staff pages, "
                         "or an explicit 1-based list e.g. 2,3,4")
    ap.add_argument("--min-integrity", type=float, default=90.0)
    args = ap.parse_args()

    report_path = args.report or os.path.splitext(args.out)[0] + ".report.json"
    infos = classify_pages(args.pdf)

    if args.pages == "auto":
        print_selection(infos)
        pages = select_pages(infos)
        if not pages:
            # Nothing extractable — explain *why* with a distinct message so the
            # batch ingester can bucket it (type3 vs Byzantine vs no music).
            has_western = any(p["kind"] == "western" for p in infos)
            has_type3 = any(p["kind"] == "type3" for p in infos)
            has_byz = any(p["kind"] == "byzantine" for p in infos)
            if has_type3 and not has_western:
                _refuse(args.pdf, "music in unnamed Type3 fonts — not yet "
                                  "supported (no named Western music font).")
            elif has_byz and not has_western:
                _refuse(args.pdf, "only Byzantine-neume notation found — "
                                  "outside SATB (Western staff) scope.")
            else:
                _refuse(args.pdf, "no born-digital Western staff notation "
                                  "found. This pipeline does not do raster OMR; "
                                  "see the roadmap for the (unsolved) scan path.")
        print(f"[pipeline] selected pages: {','.join(map(str, pages))}")
        selection_mode = "auto"
    else:
        pages = [int(p) for p in args.pages.split(",")]
        chosen = [p for p in infos if p["page"] in pages]
        if not any(p["western_glyphs"] > 0 for p in chosen):
            _refuse(args.pdf, f"pages {args.pages} have no Western music-font "
                              f"glyphs — not a born-digital engraving.")
        print(f"[pipeline] pages (explicit): {','.join(map(str, pages))}")
        selection_mode = "explicit"

    confidence_context = {
        "page_selection": confidence_signals.page_selection_context(
            infos, pages, selection_mode,
        ),
        "policy": {
            "reference": "legacy-measure-integrity-v1",
            "minimum_measure_consistency_ratio": round(args.min_integrity / 100, 6),
        },
    }
    result, rep, _xml = vector_extract.run(
        args.pdf, args.out, report_path, pages,
        confidence_context=confidence_context,
    )

    integrity = rep["stats"].get("measure_integrity_pct") or 0.0
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
