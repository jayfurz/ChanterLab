#!/usr/bin/env python3
"""survey_catalog.py — size up how much of the Antiochian Sacred Music Library
the vector-extraction pipeline can ingest automatically.

Pulls the catalog via the documented API (SOURCES.md), samples PDFs politely
(1.5 s apart, descriptive UA), classifies each by music-font family
(SMuFL/Bravura = pipeline-ready vs legacy Finale/Sibelius fonts vs scans),
and runs pipeline.py on the pipeline-ready ones to get real integrity numbers.

Downloads land in pdfs/survey/ (gitignored — copyrighted source material).

Usage:
  .venv/bin/python survey_catalog.py --choral 30 --chant 15
  .venv/bin/python survey_catalog.py --report-only   # reuse prior downloads
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SURVEY_DIR = os.path.join(HERE, "pdfs", "survey")
CATALOG = os.path.join(SURVEY_DIR, "catalog.json")
RESULTS = os.path.join(SURVEY_DIR, "survey_results.json")
UA = "byzorgan-research (justinpeter0815theotokos@gmail.com)"
TOKEN_URL = "https://www.antiochian.org/connect/token"
LIST_URL = "https://www.antiochian.org/api/antiochian/MusicLibraryListItems"
# public SPA credentials (shipped in main-*.js; see SOURCES.md)
CLIENT = {"grant_type": "client_credentials", "client_id": "antiochian_api",
          "client_secret": "TAxhx@9tH(l^MgQ9FWE8}T@NWUT9U)"}

SMUFL_FONTS = ("Bravura", "Leland", "Petaluma", "Finale Maestro SMuFL")
LEGACY_FONTS = ("Opus", "Maestro", "Engraver", "Sonata", "Petrucci", "Jazz")


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
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


def pdf_url_of(item):
    m = re.search(r'https://[a-z0-9.]*blob\.core\.windows\.net/[^"\'<> ]+\.pdf',
                  item.get("descriptionHtml") or "")
    return m.group(0) if m else None


def classify(path):
    """Return (kind, detail): smufl | legacy_font | scan | text_only | error."""
    try:
        doc = fitz.open(path)
    except Exception as e:
        return "error", str(e)[:80]
    fonts = set()
    n_images = 0
    for page in doc:
        for f in page.get_fonts():
            fonts.add(f[3] or "")
        n_images += len(page.get_images())
    names = " | ".join(sorted(fonts))
    if any(k in n for n in fonts for k in SMUFL_FONTS):
        return "smufl", names
    if any(k in n for n in fonts for k in LEGACY_FONTS):
        return "legacy_font", names
    if n_images >= len(doc) and len(fonts) <= 2:
        return "scan", f"{n_images} images / {len(doc)} pages; fonts: {names}"
    return "text_only", names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--choral", type=int, default=30, help="sample size, Choral items")
    ap.add_argument("--chant", type=int, default=15, help="sample size, Chant items")
    ap.add_argument("--seed", type=int, default=20260702)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    if os.path.exists(CATALOG):
        catalog = json.load(open(CATALOG))
    else:
        catalog = fetch_catalog()
    print(f"catalog: {len(catalog)} items")

    is_choral = lambda x: "Choral" in (x.get("arrangementType") or "")
    choral = [x for x in catalog if is_choral(x) and pdf_url_of(x)]
    chant = [x for x in catalog if not is_choral(x) and pdf_url_of(x)]
    print(f"  choral-family items with PDFs: {len(choral)}")
    print(f"  chant/other items with PDFs:   {len(chant)}")

    rng = random.Random(args.seed)
    sample = ([("choral", x) for x in rng.sample(choral, min(args.choral, len(choral)))]
              + [("chant", x) for x in rng.sample(chant, min(args.chant, len(chant)))])

    results = []
    for group, item in sample:
        url = pdf_url_of(item)
        fname = os.path.join(SURVEY_DIR, re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]))
        if not os.path.exists(fname):
            if args.report_only:
                continue
            try:
                open(fname, "wb").write(http(url))
                time.sleep(1.5)  # polite
            except Exception as e:
                results.append({"group": group, "name": item.get("name"), "url": url,
                                "kind": "download_error", "detail": str(e)[:80]})
                continue
        kind, detail = classify(fname)
        row = {"group": group, "name": (item.get("name") or "")[:60],
               "composer": (item.get("composer") or "")[:40],
               "arrangementType": item.get("arrangementType"),
               "url": url, "file": os.path.basename(fname),
               "kind": kind, "fonts": detail[:160]}
        # run the real pipeline on pipeline-ready PDFs
        if kind == "smufl":
            out = os.path.join(SURVEY_DIR, "out", os.path.basename(fname) + ".musicxml")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            p = subprocess.run(
                [os.path.join(HERE, ".venv", "bin", "python"),
                 os.path.join(HERE, "pipeline.py"), fname, "-o", out],
                capture_output=True, text=True, timeout=120)
            m = re.search(r"measure integrity ([0-9.]+)%", p.stdout)
            row["pipeline_exit"] = p.returncode
            row["integrity_pct"] = float(m.group(1)) if m else None
        results.append(row)
        print(f"  [{row['kind']:12s}] {row['name'][:44]:44s} "
              f"{('integrity ' + str(row.get('integrity_pct')) + '%') if row.get('integrity_pct') is not None else ''}")

    json.dump(results, open(RESULTS, "w"), indent=1)
    from collections import Counter
    by = Counter((r["group"], r["kind"]) for r in results)
    print("\nsummary (group, kind -> count):")
    for k, v in sorted(by.items()):
        print(f"  {k[0]:7s} {k[1]:14s} {v}")
    ok = [r for r in results if r.get("pipeline_exit") == 0]
    lo = [r for r in results if r.get("pipeline_exit") == 2]
    print(f"\npipeline clean (exit 0): {len(ok)}   low-confidence (exit 2): {len(lo)}")
    print(f"results: {RESULTS}")


if __name__ == "__main__":
    main()
