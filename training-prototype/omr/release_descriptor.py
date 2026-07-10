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

IMPORTANT scope note: ``musicxml``/``reports`` below cover MANIFEST-PUBLISHED
(``accepted``) entries only. ``ingest_state.json`` tracks a larger private
working set (``review``/``no_music``/``type3``/etc. items also have MusicXML
and report files on disk) that this descriptor does not enumerate — it
describes the published catalog, not a complete private working-state
inventory. See ``state`` for the full record count.

Usage::

    .venv/bin/python release_descriptor.py                    # print to stdout
    .venv/bin/python release_descriptor.py --out descriptor.json
    .venv/bin/python release_descriptor.py --strict            # nonzero exit
                                                                # on any
                                                                # validation
                                                                # problem
    .venv/bin/python release_descriptor.py \\
        --parser-sha <sha> --app-sha <sha>                     # explicit
                                                                # provenance —
                                                                # see "code"
                                                                # below

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

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised only if the dep is missing
    jsonschema = None

SCHEMA_VERSION = 1
MIN_READER_SCHEMA_VERSION = 1
SCHEMA_FILE = Path(__file__).resolve().parent / "schema" / "release_descriptor.schema.json"

STATUS_VALUES = (
    "accepted", "review", "no_music", "type3", "download_error", "extract_error",
)

_SIMPLE_ID_RE = re.compile(r"^[^/\\]+$")


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
# Safe path resolution — reject traversal, absolute paths, and anything that
# escapes the directory it's supposed to live in. Every manifest/state path
# field is untrusted input as far as this module is concerned.
# ---------------------------------------------------------------------------


def _is_simple_id(item_id) -> bool:
    """An id used to construct a filename (``<id>.report.json``) must be a
    single path segment — no separators, no '.'/'..' , non-empty."""
    return (
        isinstance(item_id, str)
        and item_id not in ("", ".", "..")
        and bool(_SIMPLE_ID_RE.match(item_id))
    )


def _resolve_contained(root: Path, rel: str, must_be_within: Path) -> tuple[Path | None, str | None]:
    """Resolve `rel` against `root` and require the result to stay within
    `must_be_within`. Returns (absolute_path, None) on success, or
    (None, problem) on any absolute path, empty value, or traversal that
    escapes the required directory."""
    if not rel or not isinstance(rel, str):
        return None, "path is empty or not a string"
    if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):  # posix + win drive letters
        return None, f"absolute path not allowed: {rel!r}"
    candidate = (root / rel).resolve()
    boundary = must_be_within.resolve()
    try:
        candidate.relative_to(boundary)
    except ValueError:
        return None, f"path escapes {boundary}: {rel!r}"
    return candidate, None


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def build_input_section(catalog_path, state, *, omr_dir, integrity_problems: list[str]) -> dict:
    catalog = _load_json(catalog_path)
    # The real upstream catalog.json is the RAW API response body written
    # verbatim by fetch_catalog() — a flat JSON array of item objects, not
    # wrapped in an envelope. This hash covers whatever is actually there,
    # shape-agnostic, so it stays correct even if the upstream shape changes.
    catalog_input_hash = _sha256_json_canonical(catalog) if catalog is not None else None

    # Source inventory: PUBLIC-safe fields only. `url` in a state record is
    # the external Antiochian blob URL (already public — see manifest.json's
    # pdfUrl, which is the same field). `pdf_sha256` proves WHICH source bytes
    # were used without revealing WHERE they live on this machine — the local
    # `pdf` relative path (under gitignored pdfs/ingest/) and any `detail`
    # text are deliberately never copied into the descriptor itself.
    omr_dir = Path(omr_dir)
    pdf_root = omr_dir / "pdfs" / "ingest"
    inventory = []
    seen_ids = set()
    for item_id in sorted(state.keys()):
        if item_id in seen_ids:
            integrity_problems.append(f"duplicate state id: {item_id!r}")
        seen_ids.add(item_id)
        if not _is_simple_id(item_id):
            integrity_problems.append(f"non-simple state id: {item_id!r}")

        rec = state[item_id]
        pdf_rel = rec.get("pdf")
        pdf_hash = None
        if pdf_rel:
            pdf_abs, problem = _resolve_contained(omr_dir, pdf_rel, pdf_root)
            if problem:
                integrity_problems.append(f"{item_id}: pdf path rejected — {problem}")
            else:
                pdf_hash = _sha256_file(pdf_abs)
        inventory.append({
            "id": item_id,
            "source_url": rec.get("url"),
            "pdf_sha256": pdf_hash,
        })

    return {
        "catalog_present": catalog is not None,
        "catalog_input_hash": catalog_input_hash,
        "source_inventory_count": len(inventory),
        "source_inventory_hash": _sha256_json_canonical(inventory),
        "source_inventory": inventory,
    }


def build_manifest_section(manifest, *, integrity_problems: list[str]) -> dict:
    if manifest is None:
        return {"present": False, "entry_count": 0, "hash": None}
    ids = [e.get("id") for e in manifest]
    dupes = {i for i in ids if ids.count(i) > 1}
    for d in sorted(x for x in dupes if x is not None):
        integrity_problems.append(f"duplicate manifest id: {d!r}")
    for e in manifest:
        eid = e.get("id")
        if not _is_simple_id(eid):
            integrity_problems.append(f"non-simple manifest id: {eid!r}")
    return {
        "present": True,
        "entry_count": len(manifest),
        "hash": _sha256_json_canonical(manifest),
    }


def build_musicxml_section(manifest, *, omr_dir, integrity_problems: list[str]) -> dict:
    """Covers manifest-published entries only (see module docstring)."""
    omr_dir = Path(omr_dir)
    xml_root = omr_dir / "out" / "ingest"
    per_entry: dict[str, str | None] = {}
    for entry in manifest or []:
        eid = entry.get("id")
        if not eid:
            continue
        rel = entry.get("musicxml")  # e.g. "out/ingest/<id>.musicxml", relative to omr_dir
        xml_hash = None
        if rel:
            xml_abs, problem = _resolve_contained(omr_dir, rel, xml_root)
            if problem:
                integrity_problems.append(f"{eid}: musicxml path rejected — {problem}")
            else:
                xml_hash = _sha256_file(xml_abs)
        per_entry[eid] = xml_hash
    return {
        "count": len(per_entry),
        "hash": _sha256_json_canonical(per_entry),
        "per_entry": per_entry,
    }


def build_reports_section(manifest, *, omr_dir, integrity_problems: list[str]) -> dict:
    """Covers manifest-published entries only (see module docstring). Report
    files are always named ``<id>.report.json`` directly under out/ingest/ —
    there is no stored path field to trust, but the id itself must still be
    a simple, single-segment token (checked in build_manifest_section /
    build_input_section) before it's safe to interpolate into a filename."""
    omr_dir = Path(omr_dir)
    reports_root = omr_dir / "out" / "ingest"
    per_entry: dict[str, str | None] = {}
    for entry in manifest or []:
        eid = entry.get("id")
        if not eid:
            continue
        if not _is_simple_id(eid):
            per_entry[eid] = None
            continue  # already recorded as an integrity problem elsewhere
        report_path = reports_root / f"{eid}.report.json"
        per_entry[eid] = _sha256_file(report_path)
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


def build_overrides_section(override_dir, *, integrity_problems: list[str]) -> dict:
    override_dir = Path(override_dir)
    per_stem: dict[str, str] = {}
    if override_dir.is_dir():
        for f in sorted(override_dir.glob("*.musicxml")):
            per_stem[f.stem] = _sha256_file(f)
    tombstones = load_retired(override_dir)
    conflicts = sorted(set(per_stem) & set(tombstones))
    for stem in conflicts:
        integrity_problems.append(
            f"tombstone/active-override conflict: {stem!r} is both an active "
            f"override file and listed in RETIRED — apply_overrides() will "
            f"skip it silently; delete the file or remove it from RETIRED"
        )
    return {
        "count": len(per_stem),
        "hash": _sha256_json_canonical(per_stem),
        "per_stem": per_stem,
        "tombstones": tombstones,
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


def build_manifest_validation(manifest, *, omr_dir) -> dict:
    """Acceptance: 'all manifest entries resolve to parseable MusicXML and
    reports'. Checks every listed entry's backing files actually exist and
    parse; does NOT touch anything not referenced by the manifest. Path
    safety itself (traversal/containment) is checked separately in
    build_musicxml_section/build_reports_section and reported under
    `integrity` — this function only re-derives the same contained path to
    check existence/parseability, never trusting an uncontained path."""
    omr_dir = Path(omr_dir)
    xml_root = omr_dir / "out" / "ingest"
    problems = []
    checked = 0
    for entry in manifest or []:
        checked += 1
        eid = entry.get("id", "<no id>")
        rel = entry.get("musicxml")
        if not rel:
            problems.append(f"{eid}: manifest entry has no 'musicxml' field")
            continue
        xml_path, path_problem = _resolve_contained(omr_dir, rel, xml_root)
        if path_problem:
            problems.append(f"{eid}: musicxml path rejected — {path_problem}")
        elif not xml_path.is_file():
            problems.append(f"{eid}: musicxml file missing: {rel}")
        else:
            try:
                ET.parse(xml_path)
            except ET.ParseError as e:
                problems.append(f"{eid}: musicxml does not parse: {e}")

        if not _is_simple_id(eid):
            problems.append(f"{eid}: id is not a simple token; report path cannot be safely derived")
            continue
        report_path = xml_root / f"{eid}.report.json"
        if not report_path.is_file():
            problems.append(f"{eid}: report.json missing")
        else:
            try:
                json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                problems.append(f"{eid}: report.json does not parse: {e}")
    return {"checked": checked, "problems": problems}


# ---------------------------------------------------------------------------
# Provenance — builder identity is always derived from the code that's
# actually running; parser/app provenance is NEVER inferred from it (they
# can genuinely diverge: ingestion may have run days ago at a different
# commit than whatever is building this descriptor right now).
# ---------------------------------------------------------------------------


def git_sha(cwd) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=10, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def git_dirty(cwd) -> bool | None:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=cwd, capture_output=True,
            text=True, timeout=10, check=True,
        )
        return bool(out.stdout.strip())
    except Exception:
        return None


def release_id_for(now: datetime, content_fingerprint: str) -> str:
    # Time plus a canonical content fingerprint, not a mutable label
    # (CAT-01 contract). The time component makes release_id itself
    # non-deterministic run to run by design — determinism is a property of
    # content_fingerprint (and the section hashes it's built from), tested
    # independently of release_id.
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"rel-{stamp}-{content_fingerprint[:12]}"


def compute_content_fingerprint(*, parser_git_sha, app_git_sha, input_section, manifest_section,
                                 musicxml_section, reports_section, state_section, overrides_section,
                                 bundled_content_section=None) -> str:
    """A single canonical hash covering everything that makes two releases
    the SAME release: parser/app provenance, raw catalog input, source
    inventory, manifest, MusicXML, reports, state, overrides, tombstones, and
    optional CAT-02 bundled content. Same content always
    produces the same fingerprint; this is a real sha256 over canonical JSON,
    so different content collides only with cryptographically negligible
    probability — never in practice."""
    payload = {
        "parser_git_sha": parser_git_sha,
        "app_git_sha": app_git_sha,
        "catalog_input_hash": input_section["catalog_input_hash"],
        "source_inventory_hash": input_section["source_inventory_hash"],
        "manifest_hash": manifest_section["hash"],
        "musicxml_hash": musicxml_section["hash"],
        "reports_hash": reports_section["hash"],
        "state_hash": state_section["hash"],
        "overrides_hash": overrides_section["hash"],
        "tombstones": overrides_section["tombstones"],
    }
    if bundled_content_section is not None:
        payload["bundled_content_hash"] = bundled_content_section["hash"]
    return _sha256_json_canonical(payload)


# ---------------------------------------------------------------------------
# Readiness / promotability — a structurally valid descriptor can still be
# non-promotable. CAT-02 is expected to refuse to promote anything this
# module marks promotable=False.
# ---------------------------------------------------------------------------


def compute_readiness(descriptor: dict) -> dict:
    reasons = []
    if not descriptor["input"]["catalog_present"]:
        reasons.append("no local catalog input present")
    if descriptor["manifest"]["entry_count"] == 0:
        reasons.append("manifest is empty (no published entries)")
    if descriptor["code"]["parser_git_sha"] is None:
        reasons.append("parser provenance is unknown (not explicitly supplied)")
    if descriptor["code"]["app_git_sha"] is None:
        reasons.append("app provenance is unknown (not explicitly supplied)")
    if descriptor["code"]["builder_dirty"] is not False:
        reasons.append("builder code tree is not confirmed clean (dirty or unknown)")
    if descriptor["manifest"]["present"] and descriptor["manifest"]["hash"] is None:
        reasons.append("manifest hash missing despite manifest being present")
    v = descriptor["verification"]["regression_suite"]
    if not v["recorded"]:
        reasons.append("verification (regression suite) was not recorded for this build")
    elif any(v[name] is None for name in ("passed", "skipped", "failed")):
        reasons.append("verification record is incomplete (passed/skipped/failed are all required)")
    elif any(v[name] < 0 for name in ("passed", "skipped", "failed")):
        reasons.append("verification counts cannot be negative")
    elif v["failed"] > 0:
        reasons.append(f"verification reported {v['failed']} failing test(s)")
    mv_problems = descriptor["manifest_validation"]["problems"]
    if mv_problems:
        reasons.append(f"{len(mv_problems)} manifest_validation problem(s)")
    integrity_problems = descriptor["integrity"]["problems"]
    if integrity_problems:
        reasons.append(f"{len(integrity_problems)} integrity problem(s)")
    return {"promotable": len(reasons) == 0, "reasons": reasons}


def build_release_descriptor(
    *,
    omr_dir,
    source_omr_dir=None,
    parent_release_id: str | None = None,
    now: datetime | None = None,
    parser_git_sha: str | None = None,
    app_git_sha: str | None = None,
    verified_passed: int | None = None,
    verified_skipped: int | None = None,
    verified_failed: int | None = None,
    bundled_content: dict[str, str] | None = None,
) -> dict:
    omr_dir = Path(omr_dir)
    source_omr_dir = Path(source_omr_dir) if source_omr_dir else omr_dir
    out_dir = omr_dir / "out" / "ingest"
    state_path = out_dir / "ingest_state.json"
    manifest_path = out_dir / "manifest.json"
    catalog_path = source_omr_dir / "pdfs" / "survey" / "catalog.json"
    override_dir = omr_dir / "overrides"

    loaded_state = _load_json(state_path)
    state = loaded_state or {}
    manifest = _load_json(manifest_path)

    now = now or datetime.now(timezone.utc)
    integrity_problems: list[str] = []

    input_section = build_input_section(
        catalog_path, state, omr_dir=source_omr_dir,
        integrity_problems=integrity_problems,
    )
    manifest_section = build_manifest_section(manifest, integrity_problems=integrity_problems)
    musicxml_section = build_musicxml_section(manifest, omr_dir=omr_dir, integrity_problems=integrity_problems)
    reports_section = build_reports_section(manifest, omr_dir=omr_dir, integrity_problems=integrity_problems)
    state_section = build_state_section(state_path, loaded_state)
    overrides_section = build_overrides_section(override_dir, integrity_problems=integrity_problems)

    # Builder identity is derived from THIS module's own location — the code
    # that is actually running right now — never from --omr-dir, which is
    # just where the DATA lives and may be a different checkout entirely.
    builder_dir = Path(__file__).resolve().parent
    builder_sha = git_sha(builder_dir)
    builder_dirty = git_dirty(builder_dir)

    fingerprint = compute_content_fingerprint(
        parser_git_sha=parser_git_sha, app_git_sha=app_git_sha,
        input_section=input_section, manifest_section=manifest_section,
        musicxml_section=musicxml_section, reports_section=reports_section,
        state_section=state_section, overrides_section=overrides_section,
        bundled_content_section={
            "count": len(bundled_content),
            "hash": _sha256_json_canonical(bundled_content),
            "per_file": bundled_content,
        } if bundled_content is not None else None,
    )

    descriptor = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id_for(now, fingerprint),
        "content_fingerprint": fingerprint,
        "parent_release_id": parent_release_id,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "code": {
            "builder_git_sha": builder_sha,
            "builder_dirty": builder_dirty,
            # Never inferred from builder_git_sha — the ingestion run that
            # actually produced this data may have happened at a different
            # commit, days or weeks before this descriptor is built. Explicit
            # or unknown (null); never fabricated as equal.
            "parser_git_sha": parser_git_sha,
            "app_git_sha": app_git_sha,
        },
        "input": input_section,
        "manifest": manifest_section,
        "musicxml": musicxml_section,
        "reports": reports_section,
        "state": state_section,
        "overrides": overrides_section,
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
        "manifest_validation": build_manifest_validation(manifest, omr_dir=omr_dir),
        "integrity": {"problems": integrity_problems},
        "compatibility": {"min_reader_schema_version": MIN_READER_SCHEMA_VERSION},
    }
    if bundled_content is not None:
        descriptor["bundled_content"] = {
            "count": len(bundled_content),
            "hash": _sha256_json_canonical(bundled_content),
            "per_file": bundled_content,
        }
    descriptor["readiness"] = compute_readiness(descriptor)
    return descriptor


# ---------------------------------------------------------------------------
# Validation — the checked-in JSON Schema (schema/release_descriptor.schema.json)
# is authoritative for structure/types; jsonschema enforces it. Semantic
# checks that JSON Schema can't express (private-path leaks, cross-field
# consistency) run on top and are never skipped even if jsonschema is
# unavailable for some reason.
# ---------------------------------------------------------------------------

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


_release_id_re = re.compile(r"^rel-\d{8}T\d{6}Z-[0-9a-f]{12}$")
_sha256_re = re.compile(r"^[0-9a-f]{64}$")


def _load_schema() -> dict:
    with SCHEMA_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def validate_descriptor(descriptor: dict) -> list[str]:
    """Return a list of problems (empty == valid). Never raises on a
    malformed descriptor — a caller decides whether to treat problems as
    fatal (see main()'s --strict)."""
    problems = []
    if not isinstance(descriptor, dict):
        return ["descriptor is not a JSON object"]

    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(
            _load_schema(), format_checker=jsonschema.FormatChecker(),
        )
        for error in sorted(validator.iter_errors(descriptor), key=lambda e: list(e.absolute_path)):
            location = "/".join(str(p) for p in error.absolute_path) or "<root>"
            problems.append(f"schema violation at {location}: {error.message}")
    else:  # pragma: no cover
        problems.append("jsonschema package is not installed — structural validation was NOT performed")

    # Semantic checks beyond JSON types/structure.
    fp = descriptor.get("content_fingerprint")
    if not (isinstance(fp, str) and _sha256_re.match(fp)):
        problems.append(f"content_fingerprint is not a valid sha256 hex digest: {fp!r}")

    rid = descriptor.get("release_id")
    if not (isinstance(rid, str) and _release_id_re.match(rid)):
        problems.append(f"release_id does not match the expected 'rel-<UTC stamp>-<12 hex chars>' shape: {rid!r}")
    elif fp and not rid.endswith(fp[:12]):
        problems.append(f"release_id suffix does not match content_fingerprint prefix: {rid!r} vs {fp[:12]!r}")

    generated_at = descriptor.get("generated_at")
    try:
        parsed_generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if parsed_generated_at.utcoffset() is None:
            raise ValueError("timezone offset is required")
    except (AttributeError, TypeError, ValueError):
        problems.append(f"generated_at is not a timezone-aware ISO 8601 timestamp: {generated_at!r}")

    # Recompute every aggregate that can be derived from the descriptor.
    # JSON Schema proves types and shapes; these checks prove that the values
    # agree with one another after serialization or transport.
    try:
        aggregate_specs = (
            ("input.source_inventory", descriptor["input"]["source_inventory"],
             descriptor["input"]["source_inventory_count"], descriptor["input"]["source_inventory_hash"]),
            ("musicxml.per_entry", descriptor["musicxml"]["per_entry"],
             descriptor["musicxml"]["count"], descriptor["musicxml"]["hash"]),
            ("reports.per_entry", descriptor["reports"]["per_entry"],
             descriptor["reports"]["count"], descriptor["reports"]["hash"]),
            ("overrides.per_stem", descriptor["overrides"]["per_stem"],
             descriptor["overrides"]["count"], descriptor["overrides"]["hash"]),
        )
        if "bundled_content" in descriptor:
            aggregate_specs += (
                ("bundled_content.per_file", descriptor["bundled_content"]["per_file"],
                 descriptor["bundled_content"]["count"], descriptor["bundled_content"]["hash"]),
            )
        for name, value, claimed_count, claimed_hash in aggregate_specs:
            if claimed_count != len(value):
                problems.append(f"{name} count mismatch: claimed {claimed_count}, actual {len(value)}")
            actual_hash = _sha256_json_canonical(value)
            if claimed_hash != actual_hash:
                problems.append(f"{name} hash mismatch: claimed {claimed_hash!r}, recomputed {actual_hash!r}")

        expected_fingerprint = compute_content_fingerprint(
            parser_git_sha=descriptor["code"]["parser_git_sha"],
            app_git_sha=descriptor["code"]["app_git_sha"],
            input_section=descriptor["input"],
            manifest_section=descriptor["manifest"],
            musicxml_section=descriptor["musicxml"],
            reports_section=descriptor["reports"],
            state_section=descriptor["state"],
            overrides_section=descriptor["overrides"],
            bundled_content_section=descriptor.get("bundled_content"),
        )
        if fp != expected_fingerprint:
            problems.append(
                "content_fingerprint does not match descriptor content: "
                f"claimed {fp!r}, recomputed {expected_fingerprint!r}"
            )

        expected_readiness = compute_readiness(descriptor)
        if descriptor["readiness"] != expected_readiness:
            problems.append(
                "readiness does not match descriptor evidence: "
                f"claimed {descriptor['readiness']!r}, recomputed {expected_readiness!r}"
            )
    except (KeyError, TypeError, ValueError) as e:
        # The structural errors above identify the malformed field. Preserve
        # fail-closed behavior without letting semantic validation raise.
        problems.append(f"cross-field validation could not run: {e}")

    mv = descriptor.get("manifest_validation") or {}
    if mv.get("problems"):
        problems.append(f"manifest_validation reported {len(mv['problems'])} problem(s): {mv['problems'][:3]}")

    integ = descriptor.get("integrity") or {}
    if integ.get("problems"):
        problems.append(f"integrity reported {len(integ['problems'])} problem(s): {integ['problems'][:3]}")

    problems.extend(_scan_for_leaks(descriptor))
    return problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omr-dir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--source-omr-dir", default=None,
                        help="catalog/PDF source root when --omr-dir is a staged release")
    parser.add_argument("--parent", default=None, help="parent release_id, for semantic diff/rollback")
    parser.add_argument("--out", default=None, help="write descriptor JSON here (default: stdout)")
    parser.add_argument("--strict", action="store_true", help="nonzero exit on any validation problem")
    parser.add_argument("--parser-sha", default=None, help="git SHA of the parser code that produced this data (explicit; never inferred)")
    parser.add_argument("--app-sha", default=None, help="git SHA of the app code this data is intended for (explicit; never inferred)")
    parser.add_argument("--verified-passed", type=int, default=None)
    parser.add_argument("--verified-skipped", type=int, default=None)
    parser.add_argument("--verified-failed", type=int, default=None)
    args = parser.parse_args(argv)

    descriptor = build_release_descriptor(
        omr_dir=args.omr_dir,
        source_omr_dir=args.source_omr_dir,
        parent_release_id=args.parent,
        parser_git_sha=args.parser_sha,
        app_git_sha=args.app_sha,
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

    readiness = descriptor["readiness"]
    print(
        f"\n[release_descriptor] promotable={readiness['promotable']}"
        + (f" reasons={readiness['reasons']}" if readiness["reasons"] else ""),
        file=sys.stderr,
    )

    if problems:
        print(f"[release_descriptor] {len(problems)} validation problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if args.strict:
            return 1
    else:
        print("[release_descriptor] valid.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
