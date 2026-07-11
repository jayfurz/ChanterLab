#!/usr/bin/env python3
"""CAT-03: backup-set definition, restore, and post-restore integrity proof
for the private OMR corpus and catalog release store.

This module is the single source of truth for *what* belongs in the backup
(``BACKUP_SETS``/``EXCLUDED``) so a mirror script and this restore verifier
can never drift from each other, plus the restore-side proof: given a copy
of the backup set placed at some root, verify every sealed release's own
content fingerprint, that ``current``/``previous`` resolve to valid releases,
and a plain sha256 manifest for the non-release-scoped paths (which have no
built-in fingerprint of their own).

It does not perform off-machine transport itself — that is infra's existing
SSH/tar mirror (see RELEASE_RUNBOOK.md "Backup and restore").
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import catalog_release as cr

# Every path is relative to an OMR source dir (e.g. training-prototype/omr).
# Grouped to match CAT-03/TRUST-01's scope (sources, releases, state,
# overrides/tombstones, private review journal, pointers, verification evidence).
BACKUP_SETS: dict[str, dict[str, object]] = {
    "sources": {
        "paths": ["pdfs", "SOURCES.md"],
        "why": (
            "raw source PDFs plus the cached upstream catalog and "
            "rights/provenance notes; irreplaceable if the publisher removes "
            "content"
        ),
    },
    "state": {
        "paths": ["out/ingest"],
        "why": (
            "the full private mutable working set, all ingest statuses, not "
            "just published: manifest.json, ingest_state.json, and every "
            "item's MusicXML/report"
        ),
    },
    "overrides": {
        "paths": ["overrides"],
        "why": (
            "live hand-authored corrections plus RETIRED tombstones — the "
            "working copy each new release candidate snapshots from"
        ),
    },
    "quality_ledger": {
        "paths": ["quality-ledger/ledger.json"],
        "why": (
            "private append-only reviewer/evidence journal; each sealed "
            "release contains its own immutable trust/quality-ledger.json "
            "snapshot, while this source journal drives future candidates"
        ),
    },
    "releases": {
        "paths": ["out/release-store/releases"],
        "why": (
            "every sealed, immutable release: its own out/ingest snapshot, "
            "release-scoped overrides/content, build-metadata.json, "
            "verification-results.json, and release-descriptor.json "
            "(self-validating via content_fingerprint)"
        ),
    },
    "pointers": {
        "paths": ["out/release-store/current", "out/release-store/previous"],
        "why": (
            "which release is active and which is the rollback target; "
            "relative symlinks into releases/, preserved as-is by an "
            "archive operation that does not dereference symlinks"
        ),
    },
    "verification": {
        "paths": [
            "out/release-store/backup-hash-manifest.json",
            "out/release-store/release-snapshot.json",
        ],
        "why": (
            "timestamped sha256 inventory for mutable sources/state/overrides/quality ledger "
            "and the production current/previous pointer snapshot, captured "
            "with each archive so an off-machine restore can prove both "
            "content and rollback selection"
        ),
    },
}

# Deliberately not backed up, and why.
EXCLUDED: dict[str, str] = {
    "out/release-store/staging": (
        "unserved, interrupted candidates — never authoritative "
        "(RELEASE_RUNBOOK.md); a crash here cannot affect current"
    ),
    "out/release-store/.promotion.lock": (
        "transient concurrency marker, meaningless once copied"
    ),
    "out/review": "OMR pipeline scratch/QA artifacts, reproducible from pdfs + code",
    "out/audiveris": "OMR pipeline scratch, reproducible from pdfs + code",
    "out/vector": "OMR pipeline scratch, reproducible from pdfs + code",
}

# The off-machine archive carries this alongside the release store.  It is
# intentionally outside the hashed sets: it describes those sets, so including
# it would make the manifest self-referential.
BACKUP_HASH_MANIFEST_REL = Path("out/release-store/backup-hash-manifest.json")
RELEASE_SNAPSHOT_REL = Path("out/release-store/release-snapshot.json")
HASH_MANIFEST_SCHEMA_VERSION = 1
RELEASE_SNAPSHOT_SCHEMA_VERSION = 1
_RELEASE_ID_RE = re.compile(r"^rel-\d{8}T\d{6}Z-[0-9a-f]{12}$")

# No credentials are embedded anywhere in this backup set. Transport uses
# the existing SSH host-key auth infra already relies on for the truenas
# mirror; if at-rest encryption is added later, its key belongs in infra's
# existing SOPS/age store (infra/secrets/), never duplicated here.
SECRETS_NOTE = (
    "no secrets are contained in this backup set; transport and any future "
    "at-rest key both belong to infra's existing secrets store, referenced "
    "not duplicated"
)

# Sets with no built-in content fingerprint of their own (unlike "releases",
# which is self-validating via each release-descriptor.json).
_HASHED_SETS = ("sources", "state", "overrides", "quality_ledger")


def _iter_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _safe_relative_path(value: object) -> Path | None:
    """Return a safe, non-empty relative path from a JSON manifest.

    The manifest can come from an off-machine archive, so never let it choose
    an absolute or parent-traversing destination during restore.
    """
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def build_hash_manifest(source_omr_dir: Path) -> dict[str, str]:
    """sha256 every file in the non-self-validating backup sets, keyed by
    a path relative to ``source_omr_dir`` so the manifest is host-agnostic."""
    source_omr_dir = source_omr_dir.resolve()
    manifest: dict[str, str] = {}
    for set_name in _HASHED_SETS:
        for rel in BACKUP_SETS[set_name]["paths"]:
            base = source_omr_dir / rel
            if not base.exists():
                continue
            if base.is_file():
                manifest[rel] = cr._sha256_file(base)
                continue
            for path in _iter_files(base):
                manifest[str(path.relative_to(source_omr_dir))] = cr._sha256_file(path)
    return manifest


def build_hash_manifest_evidence(source_omr_dir: Path) -> dict:
    """Build the timestamped archive evidence for mutable backup sets."""
    return {
        "schema_version": HASH_MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": build_hash_manifest(source_omr_dir),
    }


def write_hash_manifest(source_omr_dir: Path, output: Path) -> dict:
    evidence = build_hash_manifest_evidence(source_omr_dir)
    cr._write_json_atomic(output, evidence)
    return evidence


def load_hash_manifest(path: Path) -> dict[str, str]:
    """Load only the file map from a versioned archive evidence file."""
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ValueError("backup hash manifest is not a JSON object")
    if evidence.get("schema_version") != HASH_MANIFEST_SCHEMA_VERSION:
        raise ValueError("backup hash manifest schema version is unsupported")
    if not isinstance(evidence.get("generated_at"), str):
        raise ValueError("backup hash manifest is missing generated_at")
    files = evidence.get("files")
    if not isinstance(files, dict):
        raise ValueError("backup hash manifest is missing files")
    return files


def build_release_snapshot(current_release_id: str,
                           previous_release_id: str | None,
                           release_ids: list[str] | None = None) -> dict:
    if not _RELEASE_ID_RE.fullmatch(current_release_id or ""):
        raise ValueError(f"invalid current release id: {current_release_id!r}")
    if previous_release_id is not None and not _RELEASE_ID_RE.fullmatch(previous_release_id):
        raise ValueError(f"invalid previous release id: {previous_release_id!r}")
    if release_ids is None:
        release_ids = [current_release_id]
        if previous_release_id is not None:
            release_ids.append(previous_release_id)
    if not isinstance(release_ids, list) or any(
        not isinstance(release_id, str) for release_id in release_ids
    ):
        raise ValueError("release snapshot has an invalid release inventory")
    release_ids = sorted(set(release_ids))
    if any(not _RELEASE_ID_RE.fullmatch(release_id or "") for release_id in release_ids):
        raise ValueError("release snapshot has an invalid release inventory")
    if current_release_id not in release_ids or (
        previous_release_id is not None and previous_release_id not in release_ids
    ):
        raise ValueError("release snapshot inventory omits a pointer target")
    return {
        "schema_version": RELEASE_SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_release_id": current_release_id,
        "previous_release_id": previous_release_id,
        "release_ids": release_ids,
    }


def write_release_snapshot(output: Path, current_release_id: str,
                           previous_release_id: str | None,
                           release_ids: list[str] | None = None) -> dict:
    snapshot = build_release_snapshot(
        current_release_id, previous_release_id, release_ids,
    )
    cr._write_json_atomic(output, snapshot)
    return snapshot


def load_release_snapshot(path: Path) -> dict:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("release snapshot is not a JSON object")
    if snapshot.get("schema_version") != RELEASE_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("release snapshot schema version is unsupported")
    if not isinstance(snapshot.get("generated_at"), str):
        raise ValueError("release snapshot is missing generated_at")
    current = snapshot.get("current_release_id")
    previous = snapshot.get("previous_release_id")
    release_ids = snapshot.get("release_ids")
    if not _RELEASE_ID_RE.fullmatch(current or ""):
        raise ValueError("release snapshot has an invalid current_release_id")
    if previous is not None and not _RELEASE_ID_RE.fullmatch(previous):
        raise ValueError("release snapshot has an invalid previous_release_id")
    if not isinstance(release_ids, list) or any(
        not isinstance(release_id, str) or not _RELEASE_ID_RE.fullmatch(release_id)
        for release_id in release_ids
    ):
        raise ValueError("release snapshot has an invalid release_ids inventory")
    if release_ids != sorted(set(release_ids)):
        raise ValueError("release snapshot has an invalid release_ids inventory")
    if current not in release_ids or (previous is not None and previous not in release_ids):
        raise ValueError("release snapshot inventory omits a pointer target")
    return snapshot


def verify_hash_manifest(root: Path, manifest: dict[str, str]) -> list[str]:
    """Compare a restored tree at ``root`` against a manifest built by
    ``build_hash_manifest`` (against the original). Returns problem strings;
    empty means the restored mutable sets are an exact, matching inventory.

    Checking unexpected files matters because the remote mirror intentionally
    retains deleted history.  In particular, a retired override left behind by
    an older backup must not be silently copied into a recovery tree.
    """
    root = root.resolve()
    problems: list[str] = []
    expected_paths: dict[str, str] = {}
    for rel, expected in manifest.items():
        if _safe_relative_path(rel) is None or not isinstance(expected, str):
            problems.append(f"invalid manifest entry: {rel!r}")
        else:
            expected_paths[rel] = expected

    actual = build_hash_manifest(root)
    for rel in sorted(set(expected_paths) - set(actual)):
        problems.append(f"missing: {rel}")
    for rel in sorted(set(actual) - set(expected_paths)):
        problems.append(f"unexpected: {rel}")
    for rel in sorted(set(expected_paths) & set(actual)):
        expected = expected_paths[rel]
        actual_hash = actual[rel]
        if actual_hash != expected:
            problems.append(f"hash mismatch: {rel}")
    return problems


def _copy_manifest_file(source: Path, destination: Path, expected: str) -> None:
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"archive is missing a regular file: {source}")
    actual = cr._sha256_file(source)
    if actual != expected:
        raise ValueError(f"archive hash mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def materialize_restore(*, archive_root: Path, destination: Path,
                        hash_manifest: dict[str, str]) -> dict:
    """Build an exact recovery tree from the additive off-machine mirror.

    The mirror deliberately retains deleted files forever.  This routine copies
    only the manifest-listed mutable files, all sealed releases, and the two
    release pointers into an empty destination before validating it.  That
    makes a stale archived override incapable of reappearing in the restored
    working tree.
    """
    archive_root = archive_root.resolve()
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    for rel, expected in sorted(hash_manifest.items()):
        safe_rel = _safe_relative_path(rel)
        if safe_rel is None or not isinstance(expected, str):
            raise ValueError(f"invalid manifest entry: {rel!r}")
        _copy_manifest_file(archive_root / safe_rel, destination / safe_rel, expected)

    archive_store = archive_root / "out" / "release-store"
    archive_releases = archive_store / "releases"
    if not archive_releases.is_dir():
        raise ValueError(f"archive has no sealed release store: {archive_releases}")
    restored_store = destination / "out" / "release-store"
    shutil.copytree(archive_releases, restored_store / "releases", symlinks=True)

    archived_manifest = archive_root / BACKUP_HASH_MANIFEST_REL
    if not archived_manifest.is_file():
        raise ValueError(f"archive is missing bound hash evidence: {archived_manifest}")
    archived_files = load_hash_manifest(archived_manifest)
    if archived_files != hash_manifest:
        raise ValueError("archive backup hash manifest differs from the supplied manifest")
    shutil.copy2(archived_manifest, restored_store / BACKUP_HASH_MANIFEST_REL.name)

    archived_snapshot = archive_root / RELEASE_SNAPSHOT_REL
    if not archived_snapshot.is_file():
        raise ValueError(f"archive is missing bound release snapshot: {archived_snapshot}")
    snapshot = load_release_snapshot(archived_snapshot)

    # The additive archive may retain a retired pointer after a first-release
    # snapshot has no `previous`.  Materialize only the exact pair recorded in
    # the bound snapshot, never whichever old symlink happens to be present.
    for name, expected_id in (
        ("current", snapshot["current_release_id"]),
        ("previous", snapshot["previous_release_id"]),
    ):
        source = archive_store / name
        if expected_id is None:
            continue
        expected_target = f"releases/{expected_id}"
        if not source.is_symlink() or os.readlink(source) != expected_target:
            raise ValueError(f"archive {name} pointer differs from its release snapshot")
        os.symlink(expected_target, restored_store / name)
    shutil.copy2(archived_snapshot, restored_store / RELEASE_SNAPSHOT_REL.name)

    result = verify_store(destination, hash_manifest=hash_manifest)
    if not result["ok"]:
        raise ValueError(f"materialized restore did not validate: {result}")
    return result


def find_releases(root: Path) -> list[Path]:
    releases_dir = root / "out" / "release-store" / "releases"
    if not releases_dir.is_dir():
        return []
    return sorted(p for p in releases_dir.iterdir() if p.is_dir())


def _pointer_info(root: Path, name: str) -> dict:
    """Distinguish "no pointer written" (fine for `previous` before the
    first promotion) from "pointer written but dangling" (always bad) —
    conflating the two would let a corrupted `previous` symlink read as
    healthy just because the corruption also erased its release id."""
    link = root / "out" / "release-store" / name
    present = link.is_symlink()
    release_id = None
    resolves = False
    inside_releases = False
    relative_target = False
    target_text = None
    if present:
        target_text = os.readlink(link)
        target = link.resolve()
        resolves = target.is_dir()
        releases = root / "out" / "release-store" / "releases"
        try:
            target.relative_to(releases.resolve())
            inside_releases = target.parent == releases.resolve()
        except ValueError:
            pass
        release_id = target.name if resolves and inside_releases else None
        relative_target = (
            release_id is not None and target_text == f"releases/{release_id}"
        )
    return {
        "present": present,
        "release_id": release_id,
        "resolves": resolves,
        "inside_releases": inside_releases,
        "relative_target": relative_target,
        "target": target_text,
    }


def verify_store(root: Path, *, hash_manifest: dict[str, str] | None = None) -> dict:
    """The restore-side proof for scope item 3 ("restore into a clean
    location and validate hashes"). Re-derives every release's content
    fingerprint via catalog_release.validate_release (never trusts a
    recorded hash without recomputing it) and checks that current/previous
    resolve to releases that are themselves valid.
    """
    root = root.resolve()
    started = time.monotonic()
    releases: dict[str, dict] = {}
    for release_dir in find_releases(root):
        release_id = release_dir.name
        try:
            descriptor = cr.validate_release(release_dir)
            if descriptor["release_id"] != release_id:
                raise cr.ReleaseError(
                    "release directory name differs from descriptor release_id: "
                    f"{release_id!r} vs {descriptor['release_id']!r}"
                )
            releases[release_id] = {"ok": True, "problems": []}
        except cr.ReleaseError as e:
            releases[release_id] = {"ok": False, "problems": [str(e)]}

    pointers = {}
    for name in ("current", "previous"):
        info = _pointer_info(root, name)
        if name == "previous" and not info["present"]:
            valid = len(releases) <= 1  # legitimately absent before promotion
        else:
            valid = (
                info["present"] and info["resolves"] and info["inside_releases"]
                and info["relative_target"]
                and releases.get(info["release_id"], {}).get("ok", False)
            )
        pointers[name] = {**info, "valid": valid}

    pointer_problems = []
    if len(releases) > 1 and not pointers["previous"]["present"]:
        pointer_problems.append("previous pointer is missing despite multiple sealed releases")
    if (
        pointers["current"]["valid"] and pointers["previous"]["valid"]
        and pointers["current"]["release_id"] == pointers["previous"]["release_id"]
    ):
        pointer_problems.append("current and previous point at the same release")

    result: dict = {
        "releases": releases,
        "pointers": pointers,
        "release_count": len(releases),
        "invalid_release_count": sum(1 for r in releases.values() if not r["ok"]),
        "pointer_problems": pointer_problems,
        "elapsed_seconds": None,  # filled in below
    }
    if hash_manifest is None:
        result["hash_manifest_problems"] = ["missing required backup hash manifest"]
    else:
        result["hash_manifest_problems"] = verify_hash_manifest(root, hash_manifest)

    snapshot_path = root / RELEASE_SNAPSHOT_REL
    try:
        snapshot = load_release_snapshot(snapshot_path)
        if pointers["current"]["release_id"] != snapshot["current_release_id"]:
            result["release_snapshot_problems"] = [
                "current pointer differs from the archived release snapshot"
            ]
        elif pointers["previous"]["release_id"] != snapshot["previous_release_id"]:
            result["release_snapshot_problems"] = [
                "previous pointer differs from the archived release snapshot"
            ]
        elif missing := sorted(set(snapshot["release_ids"]) - set(releases)):
            result["release_snapshot_problems"] = [
                f"release snapshot inventory is missing restored releases: {missing}"
            ]
        else:
            result["release_snapshot_problems"] = []
    except (OSError, json.JSONDecodeError, ValueError) as e:
        result["release_snapshot_problems"] = [f"invalid required release snapshot: {e}"]
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["ok"] = (
        result["invalid_release_count"] == 0
        and pointers["current"]["valid"]
        and pointers["previous"]["valid"]
        and not pointer_problems
        and not result.get("hash_manifest_problems")
        and not result.get("release_snapshot_problems")
    )
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("sets", help="print the backup-set definition as JSON")

    p = sub.add_parser("hash-manifest", help="write a sha256 manifest for the non-release backup sets")
    p.add_argument("--source-omr-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)

    p = sub.add_parser("verify-store", help="validate a restored (or live) omr tree")
    p.add_argument("--root", required=True, type=Path, help="an omr source dir, e.g. training-prototype/omr")
    p.add_argument("--hash-manifest", required=True, type=Path)

    p = sub.add_parser("materialize", help="make an exact restore from an additive archive")
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--destination", required=True, type=Path)
    p.add_argument("--hash-manifest", required=True, type=Path)

    args = ap.parse_args(argv)
    if args.command == "sets":
        print(json.dumps({"sets": BACKUP_SETS, "excluded": EXCLUDED, "secrets": SECRETS_NOTE}, indent=2, sort_keys=True))
        return 0
    if args.command == "hash-manifest":
        evidence = write_hash_manifest(args.source_omr_dir, args.out)
        print(f"{len(evidence['files'])} files hashed -> {args.out}")
        return 0
    if args.command == "verify-store":
        hash_manifest = load_hash_manifest(args.hash_manifest)
        result = verify_store(args.root, hash_manifest=hash_manifest)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.command == "materialize":
        hash_manifest = load_hash_manifest(args.hash_manifest)
        result = materialize_restore(
            archive_root=args.archive_root,
            destination=args.destination,
            hash_manifest=hash_manifest,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
