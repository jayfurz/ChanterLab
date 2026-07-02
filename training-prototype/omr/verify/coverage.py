#!/usr/bin/env python3
"""coverage.py — machine audit: every notehead/rest glyph printed in the PDF
must appear in the final extracted score (or be explicitly accounted for).

For each piece:
  * collect all main-size notehead glyphs + rest glyphs from the PDF pages,
  * run the extractor, walk the FINAL per-measure score events, and mark
    which glyph objects they carry,
  * anything unmarked is a dropped symbol -> listed with page/x/y and the
    measure it should have landed in.

Exit code 1 if any unaccounted drop is found.
"""
from __future__ import annotations

import os
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
OMR = os.path.dirname(HERE)
sys.path.insert(0, OMR)
import vector_extract as vx  # noqa: E402

PIECES = {
    "trisagion": "pdfs/01_trisagion_lozowchuk_satb.pdf",
    "cherubic": "pdfs/02_cherubichymn_lozowchuk_adapted_satb.pdf",
    "anaphora": "pdfs/03_anaphora_lozowchuk_satb.pdf",
}


def audit(name):
    pdf = os.path.join(OMR, PIECES[name])
    report = vx.Report()
    result = vx.build_score(pdf, report=report)

    def gkey(g, page):
        return (page, g.cp, round(g.x, 1), round(g.y, 1))

    used_heads = set()          # glyph identity keys in final score events
    used_rest_x = []            # (page, x) of rest events kept
    for v in result["voices"]:
        for mev in result["score"][v]:
            for e in mev:
                if e.kind == "note":
                    for h in e.heads:
                        used_heads.add(gkey(h.g, h.staff.page))
                else:
                    used_rest_x.append((e.staff.page, round(e.x, 1)))

    doc = fitz.open(pdf)
    total_heads = 0
    missing = []
    rest_glyphs = 0
    missing_rests = []
    for pno in range(len(doc)):
        music, _ = vx._page_glyphs(doc[pno])
        sizes = {}
        for g in music:
            if g.cp in vx.NOTEHEADS:
                sizes[round(g.size)] = sizes.get(round(g.size), 0) + 1
        if not sizes:
            continue
        main = max(sizes, key=sizes.get)
        for g in music:
            if g.cp in vx.NOTEHEADS and g.size >= 0.75 * main:
                total_heads += 1
                if gkey(g, pno + 1) not in used_heads:
                    missing.append((pno + 1, g))
            elif g.cp in vx.RESTS:
                rest_glyphs += 1
                if not any(p == pno + 1 and abs(x - g.x0) < 1.0
                           for (p, x) in used_rest_x):
                    missing_rests.append((pno + 1, g))

    stats = report.stats
    accounted = (stats.get("parenthesized_optional_notes_skipped", 0)
                 + stats.get("divisi_events_dropped", 0)
                 + stats.get("grace_or_cue_heads_skipped", 0))
    print(f"[{name}] noteheads in PDF: {total_heads}  "
          f"in score: {len(used_heads)}  "
          f"missing: {len(missing)} (accounted drops reported: {accounted})")
    for pno, g in missing:
        print(f"    MISSING head p{pno} ({g.x:.0f},{g.y:.0f}) "
              f"U+{g.cp:04X} size {g.size:.1f}")
    print(f"    rest glyphs: {rest_glyphs}  missing rests: "
          f"{len(missing_rests)}")
    for pno, g in missing_rests:
        print(f"    MISSING rest p{pno} ({g.x0:.0f},{g.y:.0f}) U+{g.cp:04X}")
    # note: divisi drops happen at event level; a divisi-dropped head is
    # expected to appear in `missing` — cross-check counts here.
    return len(missing) - stats.get("divisi_events_dropped", 0) \
        - stats.get("parenthesized_optional_notes_skipped", 0), missing_rests


if __name__ == "__main__":
    bad = 0
    for n in (sys.argv[1:] or list(PIECES)):
        unacc, mr = audit(n)
        bad += max(0, unacc) + len(mr)
    sys.exit(1 if bad else 0)
