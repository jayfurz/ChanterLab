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
        accepted.append(
            {"id": r["id"], "title": r["name"], "composer": r["composer"],
             "arrangementType": r["arrangementType"], "musicxml": r["musicxml"],
             "integrity_pct": r["integrity_pct"],
             "tone": (cat.get("tone") or "").strip() or None,
             "liturgicalDate": (cat.get("liturgicalDate") or "").strip() or None,
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
    args = ap.parse_args()

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
