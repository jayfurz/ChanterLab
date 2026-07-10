#!/usr/bin/env python3
"""release_descriptor.py — CAT-01: build and validate an immutable catalog
release descriptor from the CURRENT local ingest state, without promoting or
moving anything.

Read-only over ``out/ingest/`` (manifest.json, ingest_state.json, per-piece
``*.report.json``), ``overrides/`` (gitignored *.musicxml + the tracked
``RETIRED`` tombstone list), and ``pdfs/survey/catalog.json``. This module
deliberately does NOT change where ``ingest_catalog.py`` writes — that is
CAT-02's job (atomic build/promote/rollback). CAT-01 only defines and
describes the contract; see RELEASE_SCHEMA.md for the full field reference.

Usage::

    .venv/bin/python release_descriptor.py                    # print to stdout
    .venv/bin/python release_descriptor.py --out descriptor.json
    .venv/bin/python release_descriptor.py --strict            # nonzero exit
                                                                # on any
                                                                # validation
                                                                # problem

On a fresh checkout (no local catalog — the common case, since ``out/`` and
``pdfs/`` are gitignored copyrighted-derived material) this still produces a
valid descriptor with zero-count sections, honestly reported, rather than
failing or fabricating data — the same "report absence, don't hide it"
principle BASE-02 already established for the OMR private-corpus CI job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MIN_READER_SCHEMA_VERSION = 1

STATUS_VALUES = (
    "accepted", "review", "no_music", "type3", "download_error", "extract_error",
)

# ---------------------------------------------------------------------------
# Hashing helpers — sha256 throughout, matching the existing regression-test
# convention (tests/test_regression.py's _sha256_of).
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    return _sha256_bytes(p.read_bytes())


def _sha256_json_canonical(obj) -> str:
    """Hash a JSON-serializable value independent of key order/whitespace."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(blob)


# ---------------------------------------------------------------------------
# Loaders — all tolerant of absence (fresh checkout has no local catalog).
# ---------------------------------------------------------------------------


def _load_json(path) -> object | None:
    p = Path(path)
    if not p.is_file():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_retired(override_dir) -> list[str]:
    """Parse overrides/RETIRED: one stem per line, #-comments/blanks ignored."""
    retired_path = Path(override_dir) / "RETIRED"
    if not retired_path.is_file():
        return []
    stems = []
    for line in retired_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        stems.append(line)
    return sorted(stems)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def build_input_section(catalog_path, state, *, omr_dir) -> dict:
    catalog = _load_json(catalog_path)
    catalog_input_hash = _sha256_json_canonical(catalog) if catalog is not None else None

    # Source inventory: PUBLIC-safe fields only. `url` in a state record is
    # the external Antiochian blob URL (already public — see manifest.json's
    # pdfUrl, which is the same field). `pdf_sha256` proves WHICH source bytes
    # were used without revealing WHERE they live on this machine — the local
    # `pdf` relative path (under gitignored pdfs/ingest/) and any `detail`
    # text are deliberately never copied into the descriptor itself.
    omr_dir = Path(omr_dir)
    inventory = []
    for item_id in sorted(state.keys()):
        rec = state[item_id]
        pdf_rel = rec.get("pdf")  # e.g. "pdfs/ingest/<file>.pdf", relative to omr_dir
        inventory.append({
            "id": item_id,
            "source_url": rec.get("url"),
            "pdf_sha256": _sha256_file(omr_dir / pdf_rel) if pdf_rel else None,
        })

    return {
        "catalog_present": catalog is not None,
        "catalog_input_hash": catalog_input_hash,
        "source_inventory_count": len(inventory),
        "source_inventory_hash": _sha256_json_canonical(inventory),
        "source_inventory": inventory,
    }


def build_manifest_section(manifest) -> dict:
    if manifest is None:
        return {"present": False, "entry_count": 0, "hash": None}
    return {
        "present": True,
        "entry_count": len(manifest),
        "hash": _sha256_json_canonical(manifest),
    }


def build_musicxml_section(out_dir, manifest) -> dict:
    per_entry: dict[str, str | None] = {}
    if manifest:
        for entry in manifest:
            rel = entry.get("musicxml")
            per_entry[entry["id"]] = _sha256_file(Path(out_dir) / rel) if rel else None
    return {
        "count": len(per_entry),
        "hash": _sha256_json_canonical(per_entry),
        "per_entry": per_entry,
    }


def build_reports_section(out_dir, manifest) -> dict:
    per_entry: dict[str, str | None] = {}
    if manifest:
        for entry in manifest:
            report_path = Path(out_dir) / f"{entry['id']}.report.json"
            per_entry[entry["id"]] = _sha256_file(report_path)
    return {
        "count": len(per_entry),
        "hash": _sha256_json_canonical(per_entry),
        "per_entry": per_entry,
    }


def build_state_section(state_path, state) -> dict:
    return {
        "present": state is not None,
        "record_count": len(state) if state else 0,
        "hash": _sha256_file(state_path),
    }


def build_overrides_section(override_dir) -> dict:
    override_dir = Path(override_dir)
    per_stem: dict[str, str] = {}
    if override_dir.is_dir():
        for f in sorted(override_dir.glob("*.musicxml")):
            per_stem[f.stem] = _sha256_file(f)
    return {
        "count": len(per_stem),
        "hash": _sha256_json_canonical(per_stem),
        "per_stem": per_stem,
        "tombstones": load_retired(override_dir),
    }


def build_trust_section(state) -> dict:
    counts = {s: 0 for s in STATUS_VALUES}
    integrities = []
    for rec in (state or {}).values():
        status = rec.get("status")
        if status in counts:
            counts[status] += 1
        if status == "accepted" and isinstance(rec.get("integrity_pct"), (int, float)):
            integrities.append(rec["integrity_pct"])
    confidence = {
        "mean_integrity_pct": round(statistics.mean(integrities), 2) if integrities else None,
        "median_integrity_pct": round(statistics.median(integrities), 2) if integrities else None,
        "min_integrity_pct": min(integrities) if integrities else None,
        "max_integrity_pct": max(integrities) if integrities else None,
    }
    return {"status_counts": counts, "confidence": confidence}


def build_manifest_validation(manifest, out_dir) -> dict:
    """Acceptance: 'all manifest entries resolve to parseable MusicXML and
    reports'. Checks every listed entry's backing files actually exist and
    parse; does NOT touch anything not referenced by the manifest."""
    problems = []
    checked = 0
    for entry in manifest or []:
        checked += 1
        eid = entry.get("id", "<no id>")
        rel = entry.get("musicxml")
        if not rel:
            problems.append(f"{eid}: manifest entry has no 'musicxml' field")
            continue
        xml_path = Path(out_dir) / rel
        if not xml_path.is_file():
            problems.append(f"{eid}: musicxml file missing: {rel}")
        else:
            try:
                ET.parse(xml_path)
            except ET.ParseError as e:
                problems.append(f"{eid}: musicxml does not parse: {e}")
        report_path = Path(out_dir) / f"{eid}.report.json"
        if not report_path.is_file():
            problems.append(f"{eid}: report.json missing")
        else:
            try:
                json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                problems.append(f"{eid}: report.json does not parse: {e}")
    return {"checked": checked, "problems": problems}


def git_sha(cwd) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=10, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def release_id_for(now: datetime, catalog_input_hash: str | None) -> str:
    # Time plus code/input identity, not a mutable label (CAT-01 contract).
    # The time component makes release_id itself non-deterministic run to
    # run by design — determinism is a property of the CONTENT hashes below,
    # tested independently of release_id (see tests/test_release_descriptor.py).
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # The suffix must always be a hex hash prefix (see validate_descriptor's
    # release_id pattern) — even the "no catalog present" case hashes a fixed
    # sentinel rather than using a literal non-hex marker string, so a
    # catalog-absent release_id is still schema-valid, not a special case.
    content = _sha256_bytes((catalog_input_hash or "no-catalog-present").encode("utf-8"))[:12]
    return f"rel-{stamp}-{content}"


def build_release_descriptor(
    *,
    omr_dir,
    parent_release_id: str | None = None,
    now: datetime | None = None,
    verified_passed: int | None = None,
    verified_skipped: int | None = None,
    verified_failed: int | None = None,
) -> dict:
    omr_dir = Path(omr_dir)
    out_dir = omr_dir / "out" / "ingest"
    state_path = out_dir / "ingest_state.json"
    manifest_path = out_dir / "manifest.json"
    catalog_path = omr_dir / "pdfs" / "survey" / "catalog.json"
    override_dir = omr_dir / "overrides"

    state = _load_json(state_path) or {}
    manifest = _load_json(manifest_path)

    now = now or datetime.now(timezone.utc)
    input_section = build_input_section(catalog_path, state, omr_dir=omr_dir)
    sha = git_sha(omr_dir)

    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id_for(now, input_section["catalog_input_hash"]),
        "parent_release_id": parent_release_id,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "code": {
            # parser_git_sha/app_git_sha are recorded as distinct contract
            # fields even though they're always equal today (one monorepo,
            # one commit) — forward-compatible if the OMR pipeline ever ships
            # as a separately-versioned package.
            "repo_git_sha": sha,
            "parser_git_sha": sha,
            "app_git_sha": sha,
        },
        "input": input_section,
        "manifest": build_manifest_section(manifest),
        "musicxml": build_musicxml_section(out_dir, manifest),
        "reports": build_reports_section(out_dir, manifest),
        "state": build_state_section(state_path, state if state else None),
        "overrides": build_overrides_section(override_dir),
        "trust": build_trust_section(state),
        # No approved-waiver mechanism exists yet anywhere in the codebase
        # (confirmed: no matching field in ingest_state.json/manifest.json).
        # Always empty until TRUST-01/RIGHTS-01 populate real waivers; the
        # field exists now so descriptors never need a breaking schema bump
        # to add it later.
        "waivers": [],
        "verification": {
            "regression_suite": {
                "passed": verified_passed,
                "skipped": verified_skipped,
                "failed": verified_failed,
                "recorded": verified_passed is not None or verified_skipped is not None or verified_failed is not None,
            },
        },
        "manifest_validation": build_manifest_validation(manifest, out_dir),
        "compatibility": {"min_reader_schema_version": MIN_READER_SCHEMA_VERSION},
    }


# ---------------------------------------------------------------------------
# Validation — hand-rolled (no new pip dependency), fails closed: any
# structural problem is reported, never silently ignored.
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL = (
    "schema_version", "release_id", "parent_release_id", "generated_at",
    "code", "input", "manifest", "musicxml", "reports", "state", "overrides",
    "trust", "waivers", "verification", "manifest_validation", "compatibility",
)

# Values that must never appear in a descriptor — local filesystem paths
# under the gitignored, copyrighted-derived directories. A descriptor is a
# description of PUBLIC-safe facts (hashes, counts, public URLs); it must
# never leak where private source material lives on this machine.
_LEAK_PATTERNS = (
    re.compile(r"pdfs[/\\]ingest[/\\]"),
    re.compile(r"pdfs[/\\]survey[/\\]"),
    re.compile(r"\.venv[/\\]"),
    re.compile(r"^/(home|Users|mnt)[/\\]"),
)


def _scan_for_leaks(value, path="$") -> list[str]:
    problems = []
    if isinstance(value, str):
        for pat in _LEAK_PATTERNS:
            if pat.search(value):
                problems.append(f"{path}: value looks like a private local path: {value!r}")
    elif isinstance(value, dict):
        for k, v in value.items():
            problems.extend(_scan_for_leaks(v, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            problems.extend(_scan_for_leaks(v, f"{path}[{i}]"))
    return problems


def validate_descriptor(descriptor: dict) -> list[str]:
    """Return a list of problems (empty == valid). Never raises on a
    malformed descriptor — a caller decides whether to treat problems as
    fatal (see main()'s --strict)."""
    problems = []
    if not isinstance(descriptor, dict):
        return ["descriptor is not a JSON object"]

    for key in _REQUIRED_TOP_LEVEL:
        if key not in descriptor:
            problems.append(f"missing required top-level field: {key}")

    sv = descriptor.get("schema_version")
    if sv != SCHEMA_VERSION:
        problems.append(f"schema_version {sv!r} != known version {SCHEMA_VERSION}")

    rid = descriptor.get("release_id")
    if not isinstance(rid, str) or not re.match(r"^rel-\d{8}T\d{6}Z-[0-9a-f]+$", rid):
        problems.append(f"release_id does not match the expected 'rel-<UTC stamp>-<hash prefix>' shape: {rid!r}")

    for section in ("manifest", "musicxml", "reports", "state", "overrides", "trust", "input"):
        if not isinstance(descriptor.get(section), dict):
            problems.append(f"{section} must be an object")

    mv = descriptor.get("manifest_validation") or {}
    if mv.get("problems"):
        problems.append(f"manifest_validation reported {len(mv['problems'])} problem(s): {mv['problems'][:3]}")

    problems.extend(_scan_for_leaks(descriptor))
    return problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omr-dir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--parent", default=None, help="parent release_id, for semantic diff/rollback")
    parser.add_argument("--out", default=None, help="write descriptor JSON here (default: stdout)")
    parser.add_argument("--strict", action="store_true", help="nonzero exit on any validation problem")
    parser.add_argument("--verified-passed", type=int, default=None)
    parser.add_argument("--verified-skipped", type=int, default=None)
    parser.add_argument("--verified-failed", type=int, default=None)
    args = parser.parse_args(argv)

    descriptor = build_release_descriptor(
        omr_dir=args.omr_dir,
        parent_release_id=args.parent,
        verified_passed=args.verified_passed,
        verified_skipped=args.verified_skipped,
        verified_failed=args.verified_failed,
    )
    problems = validate_descriptor(descriptor)

    text = json.dumps(descriptor, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    if problems:
        print(f"\n[release_descriptor] {len(problems)} validation problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if args.strict:
            return 1
    else:
        print("\n[release_descriptor] valid.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
