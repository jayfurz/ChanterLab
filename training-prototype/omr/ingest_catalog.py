#!/usr/bin/env python3
"""ingest_catalog.py — batch-ingest the Antiochian Sacred Music Library into
SATB MusicXML for the choir-training app.

Flow:  catalog  ->  filter  ->  polite download  ->  pipeline.py  ->  gate  ->
manifest.

  1. Catalog. Reuse the cached ``pdfs/survey/catalog.json`` (fetched by
     survey_catalog.py); if absent, fetch it via the documented API
     (SOURCES.md) and cache it there.  Filter to a request set of categories:
       * "choral" = arrangementType contains "Choral".
       * "chant"  = everything else that still has a blob PDF URL.
     Only items whose ``descriptionHtml`` contains a blob PDF URL are eligible.
  2. Download. PDFs land in ``pdfs/ingest/`` (inside gitignored ``pdfs/``).
     RESUMABLE: a PDF already on disk is not re-fetched; on HTTP error the item
     is recorded ``download_error`` and the run continues.  1.5 s between real
     downloads only (polite; descriptive User-Agent).
  3. Extract. Each PDF is run through ``pipeline.py`` (subprocess, the repo
     venv, default ``--pages auto``) with a 180 s timeout; stdout/stderr are
     parsed for the exit code, measure-integrity %, warning count and the
     auto-selected pages.
  4. State. ``out/ingest/ingest_state.json`` keeps one record per catalog item
     (id, name, composer, arrangementType, url, pdf, status, integrity_pct,
     warnings, selected pages).  Statuses:
       accepted | review | no_music | type3 | download_error | extract_error
     Re-runs are idempotent: items already in a terminal status are skipped
     unless ``--redo`` is given (``download_error`` always retries).  No
     timestamps are written — the state is deterministic.
  5. Manifest. ``out/ingest/manifest.json`` — ONLY accepted items, the shape
     the training app consumes: {id, title, composer, arrangementType,
     musicxml, integrity_pct}, sorted by title.
  6. Summary. Printed at the end: counts by status, mean/median integrity of
     accepted items, and the top-10 review queue (lowest integrity first).

Usage:
  .venv/bin/python ingest_catalog.py --limit 20               # small test run
  .venv/bin/python ingest_catalog.py --categories choral       # default
  .venv/bin/python ingest_catalog.py --categories choral,chant --limit 100
  .venv/bin/python ingest_catalog.py --report-only             # no network

Only stdlib + PyMuPDF (fitz), matching survey_catalog.py (urllib, no requests).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SURVEY_DIR = os.path.join(HERE, "pdfs", "survey")
CATALOG = os.path.join(SURVEY_DIR, "catalog.json")          # shared with survey
INGEST_PDF_DIR = os.path.join(HERE, "pdfs", "ingest")       # gitignored
OUT_DIR = os.path.join(HERE, "out", "ingest")
STATE = os.path.join(OUT_DIR, "ingest_state.json")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")
PYTHON = os.path.join(HERE, ".venv", "bin", "python")
PIPELINE = os.path.join(HERE, "pipeline.py")

UA = "byzorgan-research (justinpeter0815theotokos@gmail.com)"
TOKEN_URL = "https://www.antiochian.org/connect/token"
LIST_URL = "https://www.antiochian.org/api/antiochian/MusicLibraryListItems"
# public SPA credentials (shipped in main-*.js; see SOURCES.md)
CLIENT = {"grant_type": "client_credentials", "client_id": "antiochian_api",
          "client_secret": "TAxhx@9tH(l^MgQ9FWE8}T@NWUT9U)"}

DOWNLOAD_SLEEP = 1.5     # s between actual downloads (polite)
EXTRACT_TIMEOUT = 180    # s per piece
# Statuses we don't recompute on a plain re-run.  download_error is *not*
# terminal — a re-run retries the fetch.
TERMINAL = {"accepted", "review", "no_music", "type3", "extract_error"}

_PDF_RE = re.compile(
    r'https://[a-z0-9.]*blob\.core\.windows\.net/[^"\'<> ]+\.pdf')


# --------------------------------------------------------------- catalog access
def http(url, data=None, headers=None):
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_catalog():
    body = urllib.parse.urlencode(CLIENT).encode()
    tok = json.loads(http(TOKEN_URL, data=body))["access_token"]
    raw = http(LIST_URL, headers={"Authorization": f"Bearer {tok}"})
    os.makedirs(SURVEY_DIR, exist_ok=True)
    with open(CATALOG, "wb") as f:
        f.write(raw)
    return json.loads(raw)


def load_catalog(offline):
    if os.path.exists(CATALOG):
        with open(CATALOG) as f:
            return json.load(f)
    if offline:
        raise SystemExit(f"no cached catalog at {CATALOG} and --report-only "
                         f"forbids network — run a normal ingest first.")
    return fetch_catalog()


def pdf_url_of(item):
    m = _PDF_RE.search(item.get("descriptionHtml") or "")
    return m.group(0) if m else None


def sanitize(url):
    """Blob filename -> safe local filename (matches survey_catalog.py)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1])


def category_of(item):
    return "choral" if "Choral" in (item.get("arrangementType") or "") \
        else "chant"


# ------------------------------------------------------ liturgical taxonomy
# A pure, deterministic classifier that maps a catalog item to a
# {group, sub, rank} for the sectioned library UI.  Data-driven: it keys off
# bookName first, then the liturgicalDate order-prefix / calendarMonth / name
# keywords.  See app.js LIB_GROUP_ORDER for the matching UI section order.

# Canonical UI section order (Prototype is pinned separately, in the UI).
LIB_GROUP_ORDER = [
    "Divine Liturgy", "Presanctified Liturgy", "Anastasimatarion",
    "Vespers", "Orthros", "Triodion", "Pentecostarion",
    "Menaion", "Theotokia", "Other services & misc",
]

_MONTHS = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May",
           6: "June", 7: "July", 8: "August", 9: "September", 10: "October",
           11: "November", 12: "December"}
_MONTH_NAME_NUM = {v.lower(): k for k, v in _MONTHS.items()}

# Divine Liturgy fallback keyword -> rank (order of service).  Only used when a
# DL item's liturgicalDate carries no numeric order-prefix; the prefix (e.g.
# "14-Cherubic Hymn") is authoritative and already encodes this same order.
_DL_KEYWORDS = [
    ("great litany", 100), ("first antiphon", 200), ("little litany", 300),
    ("second antiphon", 400), ("antiphon", 400), ("entrance", 500),
    ("kontakion", 550), ("trisagion", 600), ("as many of you", 800),
    ("before thy cross", 1000), ("epistle", 1300), ("gospel", 1300),
    ("cherubic", 1400), ("litany of supplication", 1500), ("anaphora", 1600),
    ("mercy of peace", 1600), ("holy, holy", 1600), ("we praise thee", 1600),
    ("it is truly meet", 1700), ("hymn to the theotokos", 1700),
    ("axion estin", 1700), ("megalynarion", 1700), ("all creation", 1800),
    ("in thee rejoices", 1800), ("lord's prayer", 1900),
    ("communion hymn", 2200), ("koinonikon", 2200), ("communion", 2200),
    ("we have seen the true light", 3100), ("let our mouths", 3200),
    ("blessed be the name", 3400), ("dismissal", 3500), ("many years", 3800),
]

# Other-services sub-header ordering (bookName -> priority); unknown books
# fall after these, keyed by bookName.
_OTHER_ORDER = ["Funeral", "Wedding", "Baptism", "Ordinations", "Paraklesis",
                "Akathist to the Theotokos", "Psalter", "Horologion",
                "Euchologion", "Responses", "Paraliturgical",
                "Musical Instruction", "Rubrics"]


def tone_clean(tone):
    """Normalise a raw tone value to an int 1-8, or None.  Junk ('Russian',
    'Znamenny', 'Various', ...) and multi-tone lists ('2,6') -> None."""
    t = (tone or "").strip()
    return int(t) if t in {"1", "2", "3", "4", "5", "6", "7", "8"} else None


def _prefix_num(litdate):
    """Leading 'NN[.N][a|b]' order token of a liturgicalDate -> float, or None.
    Handles Divine Liturgy ('05.1-Kontakion', '14-Cherubic') and Presanctified
    ('1.11a-...', '1.11b-...')."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)([a-z])?", litdate or "")
    if not m:
        return None
    val = float(m.group(1)) * 1000.0
    if m.group(2):
        val += (ord(m.group(2)) - ord("a") + 1)
    return val


def _first_int(s):
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else 0


def _dl_rank(item):
    r = _prefix_num(item.get("liturgicalDate"))
    if r is not None:
        return int(r)
    name = (item.get("name") or "").lower()
    for kw, rank in _DL_KEYWORDS:
        if kw in name:
            return rank
    return 99000  # unrankable -> trails, UI falls back to title sort


def _month_of(item):
    cm = (item.get("calendarMonth") or "").strip()
    if cm.isdigit() and 1 <= int(cm) <= 12:
        return int(cm)
    m = re.match(r"\s*([A-Za-z]+)", item.get("liturgicalDate") or "")
    if m:
        return _MONTH_NAME_NUM.get(m.group(1).lower())
    return None


def _is_resurrectional(item):
    blob = ((item.get("name") or "") + " "
            + (item.get("liturgicalDate") or "")).lower()
    return "resurrect" in blob


def _alpha_rank(item):
    """'J1-Palm Sunday' -> letter(A=0)*1000 + number, so the season sorts."""
    m = re.match(r"\s*([A-Z])(\d+)", item.get("liturgicalDate") or "")
    if m:
        return (ord(m.group(1)) - ord("A")) * 1000 + int(m.group(2))
    return 99000


def _service_sub(item):
    """Strip the 'NN-' order prefix off a Vespers/Orthros liturgicalDate to get
    a readable service-moment sub-header."""
    litd = (item.get("liturgicalDate") or "").strip()
    m = re.match(r"\s*[0-9a-z.]+-\s*(.+)", litd)
    label = (m.group(1) if m else litd).strip()
    return label or "Other"


def _service_rank(item):
    r = _prefix_num(item.get("liturgicalDate"))
    return int(r) if r is not None else 99000


def liturgical_group(item):
    """Pure classifier: catalog item -> {group, sub, rank}.  Deterministic.

    `rank` orders items WITHIN a group; where a group has sub-headers the rank
    is sub-major (sub_order*1000 + within-sub order) so that sorting a group's
    items by (rank, title) yields contiguous, correctly ordered sub sections.
    """
    book = (item.get("bookName") or "").strip()
    tclean = tone_clean(item.get("tone"))

    # 1. Divine Liturgy / Presanctified — ordered by service (litDate prefix).
    if book == "Divine Liturgy":
        return {"group": "Divine Liturgy", "sub": None, "rank": _dl_rank(item)}
    if book == "Presanctified Liturgy":
        r = _prefix_num(item.get("liturgicalDate"))
        return {"group": "Presanctified Liturgy", "sub": None,
                "rank": int(r) if r is not None else 99000}

    # 2. Anastasimatarion = Octoechos (+ Eothina) + clearly-resurrectional
    #    Vespers/Orthros items that carry a clean tone.  Subdivided by the eight
    #    tones; junk / multi-tone -> a trailing "Mixed / other tones" bucket.
    resurrectional_move = (
        book in ("Vespers", "Vespers-Litia", "Orthros")
        and _is_resurrectional(item) and tclean is not None)
    if book in ("Octoechos", "Octoechos Eothina") or resurrectional_move:
        tone_order = tclean if tclean else 9   # 9 = mixed bucket, sorts last
        sub = f"Tone {tclean}" if tclean else "Mixed / other tones"
        within = min(_first_int(item.get("liturgicalDate")), 999)
        return {"group": "Anastasimatarion", "sub": sub,
                "rank": tone_order * 1000 + within}

    # 3. Menaion (fixed calendar) — collapsed, church-year month buckets.
    if book in ("Menaion", "Kazan Menaion"):
        mon = _month_of(item)
        if mon:
            church = (mon - 9) % 12   # Sep=0 .. Aug=11
            day = _first_int(item.get("calendarDay")) \
                or _first_int(item.get("liturgicalDate"))
            return {"group": "Menaion", "sub": _MONTHS[mon],
                    "rank": church * 1000 + min(day, 99)}
        return {"group": "Menaion", "sub": "Unknown date", "rank": 12000}

    # Theotokia / Stavrotheotokia — collapsed; Theotokia then Stavro (Cross).
    if book == "Theotokia-Stavrotheotokia":
        litd = (item.get("liturgicalDate") or "").lower()
        if "stavro" in litd or "cross" in litd:
            return {"group": "Theotokia",
                    "sub": "Stavro-Theotokia (of the Cross)",
                    "rank": 2000 + (tclean or 9)}
        return {"group": "Theotokia", "sub": "Theotokia",
                "rank": 1000 + (tclean or 9)}

    # 4. Triodion / Pentecostarion — one season group each, ordered by the
    #    alpha-numeric liturgicalDate prefix (A1-Pascha, B1-Thomas, ...).
    if book == "Lenten Triodion":
        return {"group": "Triodion", "sub": None, "rank": _alpha_rank(item)}
    if book == "Pentecostarion":
        return {"group": "Pentecostarion", "sub": None, "rank": _alpha_rank(item)}

    # 5. Vespers / Orthros — the non-resurrectional remainder, grouped by
    #    service moment (cleaned litDate label), ordered by its numeric prefix.
    if book in ("Vespers", "Vespers-Litia"):
        return {"group": "Vespers", "sub": _service_sub(item),
                "rank": _service_rank(item)}
    if book == "Orthros":
        return {"group": "Orthros", "sub": _service_sub(item),
                "rank": _service_rank(item)}

    # 6. Everything else -> Other services & misc, sub-headed by bookName.
    pr = _OTHER_ORDER.index(book) if book in _OTHER_ORDER else len(_OTHER_ORDER)
    return {"group": "Other services & misc", "sub": book or "Uncategorised",
            "rank": pr * 1000}


# --------------------------------------------------------------- state / manifest
def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def write_manifest(state, catalog=None):
    # join back to the catalog by id (blob filename stem) for the browse/filter
    # fields the state records don't carry (tone, liturgical date)
    extra = {}
    if catalog:
        for item in catalog:
            url = pdf_url_of(item)
            if url:
                fname = sanitize(url)
                stem = fname[:-4] if fname.lower().endswith(".pdf") else fname
                extra[stem] = item
    accepted = []
    guarded = 0
    for r in state.values():
        if r["status"] != "accepted":
            continue
        # re-check the tripwire here too: state may hold accepts from before
        # the guard existed (or before an engine fix) — keep them out of the
        # app until they are re-extracted (--redo).
        if voice_guard(r["id"], r["arrangementType"]):
            guarded += 1
            continue
        cat = extra.get(r["id"], {})
        cls = liturgical_group(cat)
        accepted.append(
            {"id": r["id"], "title": r["name"], "composer": r["composer"],
             "arrangementType": r["arrangementType"], "musicxml": r["musicxml"],
             "integrity_pct": r["integrity_pct"],
             "tone": (cat.get("tone") or "").strip() or None,
             "toneClean": tone_clean(cat.get("tone")),
             "liturgicalDate": (cat.get("liturgicalDate") or "").strip() or None,
             "bookName": (cat.get("bookName") or "").strip() or None,
             "group": cls["group"], "sub": cls["sub"], "rank": cls["rank"],
             "pdfUrl": r.get("url")})
    if guarded:
        print(f"[manifest] {guarded} accepted item(s) held back by the "
              f"voice-collapse guard (re-extract with --redo)")
    accepted.sort(key=lambda r: (r["title"] or "").lower())
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump(accepted, f, indent=1)
    return accepted


# --------------------------------------------------------------------- pipeline
def fmt_pages(pages):
    """Compress a '2,3,4,...,44' selection string to '2-44' for tidy console
    output (the full list is kept verbatim in the state record)."""
    if not pages:
        return "-"
    nums = sorted(int(n) for n in pages.split(",") if n)
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(parts)


def parse_pipeline(stdout, stderr):
    """Pull integrity %, warning count and selected pages out of pipeline.py's
    stdout (see pipeline.py for the exact lines)."""
    text = stdout or ""
    m = re.search(r"measure integrity ([0-9.]+)%", text)
    integrity = float(m.group(1)) if m else None
    m = re.search(r"([0-9]+) warnings", text)
    warnings = int(m.group(1)) if m else None
    m = re.search(r"(?:selected pages|pages \(explicit\)): ([0-9,]+)", text)
    pages = m.group(1) if m else None
    return integrity, warnings, pages


def voice_guard(item_id, arrangement):
    """Voice-collapse tripwire. A choral-marked piece whose extraction emitted
    a single voice is almost always a staff-grouping failure (every staff
    became its own 'system', so all voices concatenated into Soprano at a
    vacuous 100% integrity) — not genuine unison. Same for extractions where
    most systems came out single-staff (stat added by the engine). Returns a
    review reason, or None when the structure looks plausible."""
    if not any(k in (arrangement or "") for k in ("Choral", "4-part", "Full choir")):
        return None
    try:
        with open(os.path.join(OUT_DIR, item_id + ".report.json")) as f:
            rep = json.load(f)
    except Exception:
        return None
    voices = rep.get("voices") or []
    if len(voices) < 2:
        return f"choral-marked but only {len(voices)} voice(s) extracted"
    stats = rep.get("stats") or {}
    single, total = stats.get("single_staff_systems", 0), stats.get("systems", 0)
    if total and single > total * 0.5:
        return f"{single}/{total} systems detected as single-staff"
    return None


def run_pipeline(pdf_path, xml_path):
    """Run pipeline.py on one PDF. Returns a partial record dict with status,
    integrity_pct, warnings, selected_pages."""
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    try:
        p = subprocess.run(
            [PYTHON, PIPELINE, pdf_path, "-o", xml_path],
            capture_output=True, text=True, timeout=EXTRACT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "extract_error", "integrity_pct": None,
                "warnings": None, "selected_pages": None,
                "detail": f"timeout after {EXTRACT_TIMEOUT}s"}

    integrity, warnings, pages = parse_pipeline(p.stdout, p.stderr)
    blob = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        status = "accepted"
    elif p.returncode == 2:
        status = "review"
    elif p.returncode == 3:
        status = "type3" if "Type3" in blob else "no_music"
    else:
        status = "extract_error"
    return {"status": status, "integrity_pct": integrity, "warnings": warnings,
            "selected_pages": pages,
            "detail": (p.stderr or "").strip().splitlines()[-1]
            if status == "extract_error" and p.stderr else None}


# ------------------------------------------------------------------------- main
def build_pool(catalog, categories):
    """Eligible (item, category) pairs, sorted deterministically: choral first,
    then by filename (so partial --limit runs are a stable prefix)."""
    pool = []
    for item in catalog:
        url = pdf_url_of(item)
        if not url:
            continue
        cat = category_of(item)
        if cat in categories:
            pool.append((item, cat, url, sanitize(url)))
    pool.sort(key=lambda t: (0 if t[1] == "choral" else 1, t[3]))
    return pool


def summarize(state):
    records = list(state.values())
    print("\n=== ingest summary ===")
    print(f"items in state: {len(records)}")
    by_status = Counter(r["status"] for r in records)
    for st in ("accepted", "review", "no_music", "type3",
               "download_error", "extract_error"):
        if by_status.get(st):
            print(f"  {st:14s} {by_status[st]}")
    for st, n in by_status.items():   # any status not in the fixed list
        if st not in ("accepted", "review", "no_music", "type3",
                      "download_error", "extract_error"):
            print(f"  {st:14s} {n}")

    acc = [r["integrity_pct"] for r in records
           if r["status"] == "accepted" and r["integrity_pct"] is not None]
    if acc:
        print(f"\naccepted integrity: mean {statistics.mean(acc):.1f}%  "
              f"median {statistics.median(acc):.1f}%  (n={len(acc)})")

    review = sorted(
        (r for r in records if r["status"] == "review"),
        key=lambda r: (r["integrity_pct"] if r["integrity_pct"] is not None
                       else -1.0))
    if review:
        print(f"\ntop {min(10, len(review))} review-queue items "
              f"(lowest integrity first):")
        for r in review[:10]:
            ip = r["integrity_pct"]
            ip_s = f"{ip:5.1f}%" if ip is not None else "  n/a"
            w = r["warnings"] if r["warnings"] is not None else "?"
            print(f"  {ip_s}  {str(w):>3} warn  {(r['name'] or '')[:52]}")


def classify_report():
    """Read-only sanity report: run liturgical_group() over the full cached
    catalog and print the group/sub distribution + key assertions."""
    from collections import defaultdict
    cat = load_catalog(offline=True)
    bygroup = Counter()
    subs = defaultdict(Counter)
    submin = defaultdict(lambda: defaultdict(lambda: 10 ** 9))
    unranked_dl = []
    men_total = men_month = 0
    for it in cat:
        g = liturgical_group(it)
        bygroup[g["group"]] += 1
        subs[g["group"]][g["sub"]] += 1
        submin[g["group"]][g["sub"]] = min(submin[g["group"]][g["sub"]], g["rank"])
        if g["group"] == "Divine Liturgy" and g["rank"] >= 99000:
            unranked_dl.append(it.get("name"))
        if g["group"] == "Menaion":
            men_total += 1
            men_month += (g["sub"] != "Unknown date")

    print("=== group distribution (UI section order) ===")
    for grp in LIB_GROUP_ORDER:
        print(f"{bygroup.get(grp, 0):5d}  {grp}")
    for grp in set(bygroup) - set(LIB_GROUP_ORDER):
        print(f"{bygroup[grp]:5d}  !! UNORDERED {grp!r}")
    print(f"total classified: {sum(bygroup.values())}/{len(cat)}")

    print("\n=== sub-headers per group (in UI order) ===")
    for grp in LIB_GROUP_ORDER:
        if not subs[grp]:
            continue
        print(f"[{grp}]  {bygroup[grp]} items, {len(subs[grp])} sub(s)")
        for s in sorted(subs[grp], key=lambda s: submin[grp][s]):
            print(f"     {subs[grp][s]:4d}  {s}")

    print("\n=== assertions ===")
    pct = 100 * men_month // max(1, men_total)
    print(f"Menaion month coverage: {men_month}/{men_total} = {pct}% "
          f"({'OK' if pct >= 90 else 'FAIL <90%'})")
    print(f"Divine Liturgy unrankable: {len(unranked_dl)} "
          f"({'OK' if not unranked_dl else 'FAIL'})")
    for n in unranked_dl:
        print("   -", n)
    # spot-check a few DL service-order slots landed in order
    dl = sorted((liturgical_group(it)["rank"],
                 (it.get("name") or "").lower()) for it in cat
                if (it.get("bookName") == "Divine Liturgy"))
    def rank_of(kw):
        for r, n in dl:
            if kw in n:
                return r
        return None
    order = [("great litany", rank_of("great litany")),
             ("trisagion", rank_of("trisagion")),
             ("cherubic", rank_of("cherubic")),
             ("anaphora", rank_of("anaphora")),
             ("communion", rank_of("communion hymn")),
             ("dismissal", rank_of("dismissal"))]
    ranks = [r for _, r in order if r is not None]
    ok = all(ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1))
    print("DL service order (litany<trisagion<cherubic<anaphora<communion"
          f"<dismissal): {'OK' if ok else 'FAIL'}  {order}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--categories", default="choral",
                    help="comma list of {choral,chant} (default: choral)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of items processed (stable prefix)")
    ap.add_argument("--redo", action="store_true",
                    help="reprocess items already in a terminal status")
    ap.add_argument("--report-only", action="store_true",
                    help="summarize existing state + rewrite manifest; no network")
    ap.add_argument("--classify-report", action="store_true",
                    help="print the liturgical_group() distribution over the "
                         "full cached catalog and exit; read-only, no network")
    args = ap.parse_args()

    if args.classify_report:
        classify_report()
        return

    state = load_state()

    if args.report_only:
        catalog = load_catalog(offline=True) if os.path.exists(CATALOG) else None
        accepted = write_manifest(state, catalog)
        summarize(state)
        print(f"\nmanifest: {MANIFEST}  ({len(accepted)} accepted)")
        print(f"state:    {STATE}")
        return

    categories = {c.strip() for c in args.categories.split(",") if c.strip()}
    unknown = categories - {"choral", "chant"}
    if unknown:
        raise SystemExit(f"unknown categories: {sorted(unknown)} "
                         f"(choose from choral, chant)")

    catalog = load_catalog(offline=False)
    print(f"catalog: {len(catalog)} items")
    pool = build_pool(catalog, categories)
    print(f"eligible ({'/'.join(sorted(categories))}) with PDF: {len(pool)}")
    if args.limit is not None:
        pool = pool[:args.limit]
    print(f"processing {len(pool)} items\n")

    os.makedirs(INGEST_PDF_DIR, exist_ok=True)

    for i, (item, cat, url, fname) in enumerate(pool, 1):
        stem = fname[:-4] if fname.lower().endswith(".pdf") else fname
        item_id = stem
        prior = state.get(item_id)
        if prior and prior["status"] in TERMINAL and not args.redo:
            print(f"[{i}/{len(pool)}] skip (already {prior['status']}): "
                  f"{(item.get('name') or '')[:48]}")
            continue

        pdf_path = os.path.join(INGEST_PDF_DIR, fname)
        rel_pdf = os.path.relpath(pdf_path, HERE)
        xml_path = os.path.join(OUT_DIR, stem + ".musicxml")
        rel_xml = os.path.relpath(xml_path, HERE)

        record = {
            "id": item_id, "name": item.get("name"),
            "composer": item.get("composer"),
            "arrangementType": item.get("arrangementType"),
            "category": cat, "url": url, "pdf": rel_pdf, "musicxml": rel_xml,
            "status": None, "integrity_pct": None, "warnings": None,
            "selected_pages": None, "detail": None,
        }

        # --- download (resumable) ---
        if not os.path.exists(pdf_path):
            try:
                data = http(url)
                with open(pdf_path, "wb") as f:
                    f.write(data)
                time.sleep(DOWNLOAD_SLEEP)   # polite, real downloads only
            except Exception as e:           # noqa: BLE001 - record & continue
                record["status"] = "download_error"
                record["detail"] = str(e)[:120]
                state[item_id] = record
                save_state(state)
                print(f"[{i}/{len(pool)}] DOWNLOAD ERROR "
                      f"{(item.get('name') or '')[:40]}: {str(e)[:60]}")
                continue

        # --- extract ---
        res = run_pipeline(pdf_path, xml_path)
        record.update(res)
        if record["status"] == "accepted":
            reason = voice_guard(item_id, record["arrangementType"])
            if reason:
                record["status"] = "review"
                record["detail"] = reason
        state[item_id] = record
        save_state(state)

        ip = record["integrity_pct"]
        ip_s = f"{ip:.0f}%" if ip is not None else "  -"
        print(f"[{i}/{len(pool)}] {record['status']:14s} {ip_s:>5} "
              f"pages={fmt_pages(record['selected_pages']):8s} "
              f"{(item.get('name') or '')[:44]}")

    accepted = write_manifest(state, catalog)
    summarize(state)
    print(f"\nmanifest: {MANIFEST}  ({len(accepted)} accepted)")
    print(f"state:    {STATE}")


if __name__ == "__main__":
    main()
