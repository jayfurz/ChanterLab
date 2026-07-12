#!/usr/bin/env python3
"""Review-workflow seed for the layer-3 consensus QA's interior-gap
``missing_block`` candidates (ChanterLab issue #86).

WHAT THIS IS
------------
``lyric_qa.py`` layer 3 clusters every accepted piece into translation FAMILIES
by hymn type and flags, per family, passages that are shared by >=70% of the
family but sit BETWEEN passages a given setting DOES have -- an *interior gap*,
i.e. a probable dropped line that no single-piece pass could ever see (absence
has no token to flag). Those flags are recorded in ``out/lyric_qa_report.json``
as ``kind == "missing_block"`` with ``verdict == "uncertain"`` and a reason
ending "... needs a PDF check". This tool turns each one into a REVIEW BUNDLE so
a human (or an instrumented agent) can adjudicate it against the printed score:

  CONFIRMED DROP  -- the missing line IS printed in the PDF but never reached the
                     extracted stream (an extractor bug -> seeds iteration 5).
  legit variation -- this setting genuinely omits / rewords the passage.
  consensus art<t> -- the family clustering grouped unlike settings (a QA bug).

Each bundle carries, for one candidate:
  * piece id, hymn type, family size (= confidence), and (for a sliced
    complete-liturgy book) the section title;
  * the setting's OWN extracted rep-voice lyric stream WITH measure numbers, so
    the reviewer sees exactly what the extractor produced around the gap;
  * the family-consensus text for the missing span (the sibling that HAS it,
    plus the specific missing n-gram the report keyed on);
  * the rendered PDF region for the gap's measure range. Measures are mapped to
    PDF pages via each piece's ``<measure>``/``<print new-system>`` markers plus
    the systems-per-page counts recorded in the piece's ``.report.json`` ``info``
    lines (no MusicXML ``new-page`` markers exist in this corpus, so page breaks
    are reconstructed from those counts). Complete-liturgy books are narrowed to
    the flagged SECTION's page range; short single pieces render in full.

OUTPUTS (all under ``out/review/`` -- gitignored via ``omr/out/``)
------------------------------------------------------------------
    out/review/index.html              ranked table (highest family size first)
    out/review/candidates/NNN_<pid>.html   one bundle per candidate
    out/review/img/<pid>_pNN.png       rendered PDF pages (shared by bundles)
    out/review/candidates.json         machine-readable bundle index
    out/review/verdicts.seed.json      empty verdict skeleton to fill in

RE-RUNNABLE
-----------
    cd omr && .venv/bin/python review_bundles.py            # reads out/lyric_qa_report.json
    cd omr && .venv/bin/python review_bundles.py --limit 30 # only the top N by confidence
    cd omr && .venv/bin/python review_bundles.py --report <path> --out <dir> --dpi 120

Re-run ``lyric_qa.py`` FIRST after any re-ingest so the report reflects current
reality; this tool is a pure consumer of the report + the ingest artifacts and
never mutates them. It does NOT edit vector_extract.py / ingest_catalog.py /
lyric_qa.py -- it only imports lyric_qa's tokenizers so the streams it shows
match the report byte-for-byte.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

import fitz  # PyMuPDF -- the same PDF library vector_extract.py uses

# Reuse the EXACT layer-3 tokenizers (READ-ONLY import) so the stream this tool
# renders is identical to the one the report clustered on. Since issue #89 the
# streams are verse-split (measure, text, syllabic) triples and the report's
# missing_passage is a WORD n-gram matched on a letters-only blob, so the
# anchoring below works on letters-only _l3_blobstream views of the streams.
from lyric_qa import _l3_blobstream, _l3_voice_measure_streams, _l3_wordkey

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPORT = os.path.join(HERE, "out", "lyric_qa_report.json")
DEFAULT_OUT = os.path.join(HERE, "out", "review")
INGEST = os.path.join(HERE, "out", "ingest")
PDFDIR = os.path.join(HERE, "pdfs", "ingest")

_INFO_SYS = re.compile(r"p(\d+): grouped \d+ staves into (\d+) systems")


# --------------------------------------------------------------- ingest lookup
def find_pdf(pid):
    p = os.path.join(PDFDIR, pid + ".pdf")
    if os.path.exists(p):
        return p
    for pat in (pid + "*.pdf", "*" + pid + "*.pdf"):
        g = sorted(glob.glob(os.path.join(PDFDIR, pat)))
        if g:
            return g[0]
    return None


def report_json_path(pid):
    return os.path.join(INGEST, pid + ".report.json")


def xml_path(pid):
    return os.path.join(INGEST, pid + ".musicxml")


def load_report_json(pid):
    p = report_json_path(pid)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ------------------------------------------------------ measure -> PDF page map
def measure_page_map(pid):
    """{measure_number -> 1-based PDF page} reconstructed from the MusicXML's
    per-measure ``<print new-system>`` markers and the piece's ``.report.json``
    ``info`` "pN: grouped .. into K systems" counts. Returns ({}, note) if the
    inputs are missing. When the MusicXML system count and the report system
    count disagree (large books drift by a few), systems are sampled into the
    report's page list with endpoint scaling so first/last pages stay aligned
    and interior drift is bounded to a page or two."""
    xp = xml_path(pid)
    if not os.path.exists(xp):
        return {}, "no musicxml"
    try:
        root = ET.parse(xp).getroot()
    except ET.ParseError:
        return {}, "musicxml parse error"
    part = root.find("part")
    if part is None:
        return {}, "no part"
    measures = []                       # (num, new_system)
    for mm in part.findall("measure"):
        try:
            num = int(mm.get("number"))
        except (TypeError, ValueError):
            continue
        pr = mm.find("print")
        ns = pr is not None and pr.get("new-system") == "yes"
        measures.append((num, ns))
    if not measures:
        return {}, "no measures"
    si = -1
    sys_of_measure = {}
    for num, ns in measures:
        if si == -1 or ns:              # measure 1 opens system 0
            si += 1
        sys_of_measure[num] = si
    n_xml = si + 1

    rep = load_report_json(pid)
    persys = [(int(m.group(1)), int(m.group(2)))
              for line in rep.get("info", []) for m in [_INFO_SYS.match(line)]
              if m]
    if not persys:
        return {}, "no systems-per-page in report.json"
    sys_page = []                       # report system index -> page
    for page, cnt in persys:
        sys_page.extend([page] * cnt)
    n_rep = len(sys_page)

    def page_for_sys(s):
        if n_rep == 0:
            return None
        if n_xml == n_rep:
            j = s
        else:                           # scale endpoints together, bound drift
            j = round(s * (n_rep - 1) / max(1, n_xml - 1))
        return sys_page[min(max(0, j), n_rep - 1)]

    m2p = {num: page_for_sys(sys_of_measure[num]) for num, _ in measures}
    note = "exact" if n_xml == n_rep else f"scaled ({n_xml} xml sys vs {n_rep} report sys)"
    return m2p, note


def section_ranges(pid):
    """[(title, start_measure, end_measure_exclusive)] from report.json sections."""
    rep = load_report_json(pid)
    secs = rep.get("sections") or []
    out = []
    for i, s in enumerate(secs):
        lo = s.get("measure", 1)
        hi = secs[i + 1].get("measure", 10 ** 9) if i + 1 < len(secs) else 10 ** 9
        out.append((s.get("title", ""), lo, hi))
    return out


# --------------------------------------------------------------- stream slicing
def rep_voice_slice(pid, lo=1, hi=10 ** 9):
    """(voice_label, [(measure, token, syllabic)...]) for the LONGEST
    (voice, verse) stream whose tokens fall in [lo, hi) -- the same
    'rep = longest stream' choice layer 3 makes."""
    xp = xml_path(pid)
    if not os.path.exists(xp):
        return None, []
    try:
        vms = _l3_voice_measure_streams(xp)
    except ET.ParseError:
        return None, []
    best_label, best = None, []
    for label, seq in vms.items():
        sl = [(mn, t, syl) for (mn, t, syl) in seq if lo <= mn < hi]
        if len(sl) > len(best):
            best_label, best = label, sl
    return best_label, best


# --------------------------------------------------------- best-effort gap loc.
def locate_gap_measures(flagged_rep, haver_pid, missing_passage, sec_lo, sec_hi):
    """Estimate the measure range of the gap in the FLAGGED setting.

    The gap has no tokens in the flagged piece (that is what makes it missing),
    so we anchor on the text the flagged piece DOES share with the family on
    either side. We find the missing WORD n-gram in the HAVER's re-joined word
    stream, read the content words just before/after it, then locate the last
    such 'pre' word and the first such 'post' word in the flagged setting's
    letters-only blob (so a differently syllabified flagged stream still
    anchors) -> the gap sits between their measures. Best-effort: returns
    (lo, hi) or None."""
    _, haver_rep = rep_voice_slice(haver_pid, sec_lo, sec_hi)
    if not haver_rep:
        return None
    hblob, _htoks = _l3_blobstream(haver_rep)
    cat = "".join(w for w in (_l3_wordkey(x)
                              for x in missing_passage.split()) if w)
    if not cat:
        return None
    p = hblob.find(cat)
    if p == -1:
        return None
    pre_str = hblob[max(0, p - 30):p]
    post_str = hblob[p + len(cat):p + len(cat) + 30]
    blob, toks = _l3_blobstream(flagged_rep)
    if not toks:
        return None

    def measure_at(q):
        j = 0
        while j + 1 < len(toks) and toks[j + 1][2] <= q:
            j += 1
        return toks[j][1]

    # A few characters at the anchor boundary may themselves be part of the
    # dropped text (or contaminated), so allow trimming up to 6 chars off the
    # gap-facing end of each anchor before demanding an 8+ char match.
    pre_end = None                       # end of the longest pre-anchor match
    for trim in range(0, 7):
        seg = pre_str[:len(pre_str) - trim]
        for L in range(len(seg), 7, -1):
            q = blob.rfind(seg[-L:])
            if q != -1:
                pre_end = q + L
                break
        if pre_end is not None:
            break
    if pre_end is None:
        return None
    post_start = None
    for trim in range(0, 7):
        seg = post_str[trim:]
        for L in range(len(seg), 7, -1):
            q = blob.find(seg[:L], pre_end)
            if q != -1:
                post_start = q
                break
        if post_start is not None:
            break
    if post_start is None:
        return None
    return (measure_at(max(0, pre_end - 1)), measure_at(post_start))


# --------------------------------------------------------------- PDF rendering
def render_pages(pid, pages, dpi, img_dir):
    """Render the given 1-based PDF page numbers to PNGs (idempotent) and return
    [(page_no, rel_path)]. Shared across candidates of the same piece."""
    pdf = find_pdf(pid)
    if not pdf:
        return [], "no pdf"
    try:
        doc = fitz.open(pdf)
    except Exception as e:                       # noqa: BLE001 - corrupt PDF
        return [], f"pdf open error: {e}"
    out = []
    for pno in pages:
        if pno is None or pno < 1 or pno > doc.page_count:
            continue
        rel = os.path.join("img", f"{pid}_p{pno:02d}.png")
        dst = os.path.join(img_dir, os.path.pardir, rel)
        dst = os.path.normpath(dst)
        if not os.path.exists(dst):
            pix = doc[pno - 1].get_pixmap(dpi=dpi)
            pix.save(dst)
        out.append((pno, rel))
    doc.close()
    return out, "ok"


# ----------------------------------------------------------------- HTML helpers
def esc(s):
    return html.escape(str(s), quote=True)


def stream_html(rep_label, rep_stream, target_lo, target_hi):
    """Render the flagged setting's rep-voice stream, grouping by measure and
    marking the measures the gap is estimated to sit between."""
    if not rep_stream:
        return "<p class='muted'>(no extracted lyric stream for this section)</p>"
    by_m = defaultdict(list)
    for mn, t, _syl in rep_stream:
        by_m[mn].append(t)
    cells = []
    for mn in sorted(by_m):
        hot = target_lo is not None and target_lo <= mn <= target_hi
        cls = "m hot" if hot else "m"
        toks = " ".join(esc(t) for t in by_m[mn])
        cells.append(f"<span class='{cls}'><b>m{mn}</b> {toks}</span>")
    head = f"<div class='muted'>rep voice: {esc(rep_label or '?')} &middot; " \
           f"{len(rep_stream)} tokens</div>"
    return head + "<div class='stream'>" + " ".join(cells) + "</div>"


CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;
  background:#fafafa;color:#1a1a1a}
@media(prefers-color-scheme:dark){body{background:#161616;color:#e6e6e6}
  a{color:#7db3ff}.card{background:#1f1f1f;border-color:#333}
  .stream{background:#111}.m.hot{background:#4a3a00}
  th{background:#222}tr:nth-child(even) td{background:#1c1c1c}}
a{color:#0a58ca}
.wrap{max-width:1100px;margin:0 auto;padding:20px}
h1{font-size:20px}h2{font-size:15px;margin:18px 0 6px}
.card{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:14px 16px;
  margin:14px 0}
.muted{color:#888;font-size:12px}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
  background:#eef;border:1px solid #ccd;margin-right:6px}
.stream{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#f3f3f3;
  padding:10px;border-radius:6px;overflow-x:auto}
.m{display:inline-block;margin:2px 6px 2px 0;white-space:nowrap}
.m.hot{background:#fff3bf;border-radius:4px;padding:0 3px}
.consensus{background:#eaffea;border-left:3px solid #3c3;padding:8px 12px;border-radius:4px}
@media(prefers-color-scheme:dark){.consensus{background:#12240f}}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #ddd;padding:5px 8px;text-align:left}
@media(prefers-color-scheme:dark){th,td{border-color:#333}}
th{background:#f0f0f0}
img.page{max-width:100%;border:1px solid #ccc;margin:8px 0;border-radius:4px}
.imgs{overflow-x:auto}
code{background:#0001;padding:1px 4px;border-radius:3px}
"""


def candidate_html(c, imgs, page_note, loc_note):
    cons = f"<div class='consensus'><b>Family-consensus text (the sibling that " \
           f"HAS this passage):</b><br>&ldquo;{esc(c['context'])} &hellip;&rdquo;" \
           f"<br><span class='muted'>reported missing n-gram key: </span>" \
           f"<code>{esc(c['missing_passage'])}</code>" \
           f"<br><span class='muted'>sibling piece: {esc(c['sibling'])}</span></div>"
    imghtml = "".join(
        f"<div class='muted'>PDF page {p}</div><img class='page' src='../{rel}'>"
        for p, rel in imgs) or "<p class='muted'>(no PDF pages rendered)</p>"
    tlo, thi = c.get("target_lo"), c.get("target_hi")
    target = (f"measures ~{tlo}&ndash;{thi} (localized via family anchors)"
              if tlo is not None else
              (f"section measures {c['sec_lo']}&ndash;"
               f"{c['sec_hi'] if c['sec_hi'] < 10**8 else 'end'}"
               if c.get("section") else "whole piece"))
    return f"""<!doctype html><meta charset=utf-8>
<title>#{c['rank']:03d} {esc(c['pid'])}</title><style>{CSS}</style>
<div class=wrap>
<p><a href="../index.html">&larr; index</a></p>
<h1>#{c['rank']:03d} &nbsp; {esc(c['title'] or c['pid'])}</h1>
<div class=card>
  <span class=pill>type: {esc(c['type'])}</span>
  <span class=pill>family size: {c['family_size']} (confidence)</span>
  {"<span class=pill>section: "+esc(c['section'])+"</span>" if c.get('section') else ""}
  <div class=muted>piece id: {esc(c['pid'])}</div>
  <div class=muted>gap region: {target} &middot; PDF page map: {esc(page_note)}
     &middot; anchor localization: {esc(loc_note)}</div>
</div>
<h2>What the family says is missing here</h2>
<div class=card>{cons}</div>
<h2>What the extractor produced for THIS setting (rep voice, by measure)</h2>
<div class=card>{stream_html(c['rep_label'], c['rep_stream'], tlo, thi)}</div>
<h2>Printed score &mdash; read the gap region for the missing line</h2>
<div class="card imgs">{imghtml}</div>
</div>"""


def index_html(cands, survived, total_ref):
    rows = []
    for c in cands:
        rows.append(
            f"<tr><td>{c['rank']:03d}</td>"
            f"<td><a href='candidates/{c['rank']:03d}_{esc(c['pid'])}.html'>{esc(c['pid'])}</a></td>"
            f"<td>{esc(c['type'])}</td>"
            f"<td>{esc(c.get('section') or '')}</td>"
            f"<td style='text-align:right'>{c['family_size']}</td>"
            f"<td><code>{esc(c['missing_passage'])}</code></td>"
            f"<td>{c['n_pages']}</td></tr>")
    return f"""<!doctype html><meta charset=utf-8>
<title>Interior-gap missing_block review bundles</title><style>{CSS}</style>
<div class=wrap>
<h1>Layer-3 interior-gap <code>missing_block</code> review bundles</h1>
<p class=muted>{survived} candidate flags across {len({c['pid'] for c in cands})}
pieces survived the current re-ingest (issue #86 referenced ~{total_ref}).
Ranked by family size = consensus confidence. Each row is a probable dropped
line: a family-shared passage that sits between passages the setting DOES have.
Verdict each in <code>out/review/verdicts.json</code>.</p>
<table>
<tr><th>#</th><th>piece</th><th>type</th><th>section</th><th>family</th>
<th>missing n-gram key</th><th>pages</th></tr>
{''.join(rows)}
</table></div>"""


# ----------------------------------------------------------------------- driver
def collect_candidates(report):
    out = []
    for pid, pdata in report["pieces"].items():
        for f in pdata.get("layer3", []):
            if f.get("kind") != "missing_block":
                continue
            if "interior gap" not in f.get("reason", ""):
                continue
            out.append((pid, pdata.get("title", ""), f))
    # confidence order: larger family first, then type, then pid for determinism
    out.sort(key=lambda z: (-z[2].get("family_size", 0), z[2].get("type", ""), z[0]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--limit", type=int, default=0,
                    help="only build the top-N candidates by confidence (0 = all)")
    ap.add_argument("--max-pages", type=int, default=6,
                    help="cap rendered pages per candidate")
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    cands = collect_candidates(report)
    total = len(cands)
    if args.limit:
        cands = cands[:args.limit]

    os.makedirs(os.path.join(args.out, "candidates"), exist_ok=True)
    os.makedirs(os.path.join(args.out, "img"), exist_ok=True)
    img_dir = os.path.join(args.out, "img")

    built = []
    for rank, (pid, title, f) in enumerate(cands, 1):
        section = f.get("section")
        sec_lo, sec_hi = 1, 10 ** 9
        if section:
            for st, lo, hi in section_ranges(pid):
                if st == section:
                    sec_lo, sec_hi = lo, hi
                    break
        rep_label, rep_stream = rep_voice_slice(pid, sec_lo, sec_hi)
        m2p, page_note = measure_page_map(pid)

        sibling = (f.get("siblings") or [""])[0]
        loc = locate_gap_measures(rep_stream, sibling, f.get("missing_passage", ""),
                                  sec_lo, sec_hi)
        loc_note = "family-anchored" if loc else "not localized (showing full region)"
        target_lo = target_hi = None
        if loc:
            target_lo, target_hi = loc

        # choose pages to render
        if m2p:
            if target_lo is not None:
                lo_pg = m2p.get(target_lo)
                hi_pg = m2p.get(target_hi)
                pages = _page_span(lo_pg, hi_pg)
            elif section:
                lo_pg = m2p.get(sec_lo)
                hi_pg = m2p.get(min(sec_hi - 1, max(m2p)))
                pages = _page_span(lo_pg, hi_pg)
            else:
                pages = sorted(set(v for v in m2p.values() if v))
        else:
            pages = list(range(1, args.max_pages + 1))
        pages = _cap_pages(pages, args.max_pages)

        imgs, _ = render_pages(pid, pages, args.dpi, img_dir)

        c = {"rank": rank, "pid": pid, "title": title, "type": f.get("type"),
             "section": section, "sec_lo": sec_lo, "sec_hi": sec_hi,
             "family_size": f.get("family_size", 0),
             "missing_passage": f.get("missing_passage", ""),
             "context": f.get("context", ""), "sibling": sibling,
             "rep_label": rep_label, "rep_stream": rep_stream,
             "target_lo": target_lo, "target_hi": target_hi,
             "n_pages": len(imgs)}
        with open(os.path.join(args.out, "candidates",
                               f"{rank:03d}_{pid}.html"), "w", encoding="utf-8") as fp:
            fp.write(candidate_html(c, imgs, page_note, loc_note))
        # drop the heavy stream before persisting the machine index
        built.append({k: v for k, v in c.items() if k != "rep_stream"})
        print(f"[{rank:3d}/{len(cands)}] {pid[:48]:48s} fam={c['family_size']:2d} "
              f"pages={len(imgs)} loc={'y' if loc else '-'}")

    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(index_html(built, total, 101))
    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as fp:
        json.dump({"generated_from": args.report, "survived": total,
                   "candidates": built}, fp, indent=1)
    seed = {c["pid"] + ("::" + c["section"] if c["section"] else ""): {
        "rank": c["rank"], "family_size": c["family_size"],
        "verdict": "", "mechanism": "", "note": ""} for c in built}
    seedpath = os.path.join(args.out, "verdicts.seed.json")
    if not os.path.exists(seedpath):
        with open(seedpath, "w", encoding="utf-8") as fp:
            json.dump(seed, fp, indent=1)
    print(f"\n{len(built)} bundles -> {args.out}/index.html "
          f"({total} interior-gap candidates total)")


def _page_span(lo_pg, hi_pg):
    if lo_pg and hi_pg:
        a, b = sorted((lo_pg, hi_pg))
        return list(range(max(1, a - 1), b + 2))     # +/-1 page buffer for drift
    if lo_pg:
        return [max(1, lo_pg - 1), lo_pg, lo_pg + 1]
    return []


def _cap_pages(pages, cap):
    pages = [p for p in dict.fromkeys(pages) if p]
    return pages[:cap] if len(pages) > cap else pages


if __name__ == "__main__":
    main()
