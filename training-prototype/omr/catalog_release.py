#!/usr/bin/env python3
"""Build, seal, promote, and roll back immutable ChanterLab catalog releases.

The release store has one mutable decision: the ``current`` symlink. Release
trees themselves are immutable after sealing::

    <store>/
      staging/.staging-<token>/   # interrupted work; never served
      releases/rel-.../           # sealed candidates
      current -> releases/rel-... # atomically replaced on promotion
      previous -> releases/rel-...# rollback target

Run ``new`` first, point ``ingest_catalog.py --candidate-dir`` at the printed
path, then ``seal``. Promotion requires the release id repeated via
``--approve`` and never copies into the served tree.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import release_descriptor as rd
import quality_ledger as ql

HERE = Path(__file__).resolve().parent
APPROVED_BUILTINS = (
    "trisagion_omr.musicxml",
    "trisagion_vector.musicxml",
    "cherubic_vector.musicxml",
    "anaphora_vector.musicxml",
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_RELEASE_ID_RE = re.compile(r"^rel-\d{8}T\d{6}Z-[0-9a-f]{12}$")


class ReleaseError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _git_state(cwd: Path) -> tuple[str, bool]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip())
    return sha, dirty


def _require_git_sha(value: str, name: str) -> None:
    if not _GIT_SHA_RE.fullmatch(value or ""):
        raise ReleaseError(f"{name} must be a real hexadecimal git SHA, got {value!r}")


def _contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as e:
        raise ReleaseError(f"path escapes release store: {path}") from e
    return resolved


def _release_path(store: Path, release_id: str) -> Path:
    if not _RELEASE_ID_RE.fullmatch(release_id or ""):
        raise ReleaseError(f"invalid release id: {release_id!r}")
    return _contained(store / "releases" / release_id, store / "releases")


def _pointer_release_id(store: Path, name: str) -> str | None:
    pointer = store / name
    if not pointer.is_symlink():
        return None
    target = pointer.resolve(strict=True)
    releases = (store / "releases").resolve()
    try:
        target.relative_to(releases)
    except ValueError as e:
        raise ReleaseError(f"{name} pointer escapes releases/: {target}") from e
    return target.name


def _copy_quality_ledger(source_omr_dir: Path, candidate: Path) -> None:
    """Snapshot the private journal with candidate inputs, if it exists.

    The journal is ignored corpus state, not a live file that a candidate may
    read later from the source checkout. Its absence is the valid initial
    migration state and produces an all-auto-imported ledger.
    """
    source = source_omr_dir / ql.JOURNAL_REL
    if not source.is_file():
        return
    ql.load_journal(source)
    target = candidate / ql.JOURNAL_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _candidate_journal_hash(candidate: Path) -> str | None:
    journal = candidate / ql.JOURNAL_REL
    if journal.is_file():
        ql.load_journal(journal)
    return rd._sha256_file(journal)


def _candidate_source_inventory_hash(candidate: Path, source_omr_dir: Path) -> str:
    """Hash the exact source PDFs named by the staged candidate state.

    A catalog.json hash alone does not prove that the source PDF bytes stayed
    fixed between extraction and seal. This derives the same inventory hash
    that the release descriptor will bind, but does so at verification time so
    a later source-PDF mutation is a sealing failure rather than new ledger
    provenance attached to old MusicXML.
    """
    try:
        state = _load_json(candidate / "out" / "ingest" / "ingest_state.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"candidate state is unreadable for source verification: {exc}") from exc
    if not isinstance(state, dict):
        raise ReleaseError("candidate state is not a JSON object for source verification")
    problems: list[str] = []
    section = rd.build_input_section(
        source_omr_dir / "pdfs" / "survey" / "catalog.json",
        state,
        omr_dir=source_omr_dir,
        integrity_problems=problems,
    )
    if problems:
        raise ReleaseError("candidate source inventory is unsafe:\n  - " + "\n  - ".join(problems))
    return section["source_inventory_hash"]


def _recorded_candidate_source_inventory_hash(candidate: Path) -> str:
    """Hash the PDF identities recorded by extraction/import, not live bytes."""
    try:
        state = _load_json(candidate / "out" / "ingest" / "ingest_state.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"candidate state is unreadable for source verification: {exc}") from exc
    if not isinstance(state, dict):
        raise ReleaseError("candidate state is not a JSON object for source verification")
    inventory = []
    for item_id in sorted(state):
        record = state[item_id]
        if not rd._is_simple_id(item_id) or not isinstance(record, dict):
            raise ReleaseError(f"candidate state has an unsafe source record: {item_id!r}")
        if "source_pdf_sha256" not in record:
            raise ReleaseError(f"{item_id}: source PDF hash was not recorded at candidate input time")
        pdf_hash = record["source_pdf_sha256"]
        if pdf_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", pdf_hash):
            raise ReleaseError(f"{item_id}: recorded source PDF hash is invalid")
        inventory.append({
            "id": item_id,
            "source_url": record.get("url"),
            "pdf_sha256": pdf_hash,
        })
    return rd._sha256_json_canonical(inventory)


def _stamp_missing_candidate_source_hashes(candidate: Path, source_omr_dir: Path) -> None:
    """Migration-only input snapshot for legacy import candidates.

    Fresh ingestion records source_pdf_sha256 while it extracts. Legacy state
    predates that field, so import-existing stamps the source bytes observed at
    candidate initialization. It still cannot prove earlier historical output
    used those bytes; it merely prevents later source drift from being silently
    attached to the imported candidate.
    """
    state_path = candidate / "out" / "ingest" / "ingest_state.json"
    try:
        state = _load_json(state_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"legacy import state is unreadable: {exc}") from exc
    if not isinstance(state, dict):
        raise ReleaseError("legacy import state is not a JSON object")
    source_root = source_omr_dir / "pdfs" / "ingest"
    changed = False
    for item_id, record in state.items():
        if not rd._is_simple_id(item_id) or not isinstance(record, dict):
            raise ReleaseError(f"legacy import state has an unsafe source record: {item_id!r}")
        if "source_pdf_sha256" in record:
            continue
        pdf_hash = None
        pdf_rel = record.get("pdf")
        if pdf_rel:
            pdf_path, problem = rd._resolve_contained(source_omr_dir, pdf_rel, source_root)
            if problem:
                raise ReleaseError(f"{item_id}: legacy source PDF path rejected: {problem}")
            pdf_hash = rd._sha256_file(pdf_path)
        record["source_pdf_sha256"] = pdf_hash
        changed = True
    if changed:
        _write_json_atomic(state_path, state)


def _candidate_artifact_inventory_hash(candidate: Path) -> str:
    """Canonical inventory of every candidate artifact that sealing publishes.

    Tests run against parser code in ``HERE`` and generate their own temporary
    output, so a green test process alone cannot prove the staged candidate
    was unchanged afterward. Bind the candidate's manifest, state, published
    artifacts, overrides, and approved built-ins into its verification result.
    Source-PDF identity and the private journal are bound separately.
    """
    out = candidate / "out" / "ingest"
    try:
        manifest = _load_json(out / "manifest.json")
        loaded_state = _load_json(out / "ingest_state.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"candidate artifact inventory is unreadable: {exc}") from exc
    if not isinstance(manifest, list) or not isinstance(loaded_state, dict):
        raise ReleaseError("candidate manifest/state have invalid shapes for verification")
    problems: list[str] = []
    manifest_section = rd.build_manifest_section(manifest, integrity_problems=problems)
    musicxml_section = rd.build_musicxml_section(
        manifest, omr_dir=candidate, integrity_problems=problems,
    )
    reports_section = rd.build_reports_section(
        manifest, omr_dir=candidate, integrity_problems=problems,
    )
    overrides_section = rd.build_overrides_section(
        candidate / "overrides", integrity_problems=problems,
    )
    manifest_validation = rd.build_manifest_validation(manifest, omr_dir=candidate)
    if problems or manifest_validation["problems"]:
        details = problems + manifest_validation["problems"]
        raise ReleaseError("candidate artifacts are not valid for verification:\n  - " + "\n  - ".join(details))
    payload = {
        "manifest": manifest_section,
        "musicxml": musicxml_section,
        "reports": reports_section,
        "state": rd.build_state_section(out / "ingest_state.json", loaded_state),
        "overrides": overrides_section,
        "bundled_content": _bundled_content(candidate),
        "build_metadata_hash": rd._sha256_file(candidate / "build-metadata.json"),
    }
    return rd._sha256_json_canonical(payload)


def new_candidate(*, store: Path, source_omr_dir: Path, content_dir: Path,
                  app_git_sha: str, now: datetime | None = None) -> Path:
    store = store.resolve()
    source_omr_dir = source_omr_dir.resolve()
    content_dir = content_dir.resolve()
    _require_git_sha(app_git_sha, "app_git_sha")
    parser_sha, dirty = _git_state(HERE)
    if dirty:
        raise ReleaseError("parser checkout is dirty; commit and pass CI before starting a candidate")

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    token = f".staging-{stamp}-{secrets.token_hex(4)}"
    staging_root = store / "staging"
    candidate = staging_root / token
    try:
        (candidate / "out" / "ingest").mkdir(parents=True, exist_ok=False)
        (candidate / "overrides").mkdir()
        (candidate / "content").mkdir()
        (store / "releases").mkdir(parents=True, exist_ok=True)

        source_overrides = source_omr_dir / "overrides"
        retired = source_overrides / "RETIRED"
        if retired.is_file():
            shutil.copy2(retired, candidate / "overrides" / "RETIRED")
        for override in sorted(source_overrides.glob("*.musicxml")):
            ET.parse(override)
            shutil.copy2(override, candidate / "overrides" / override.name)
        _copy_quality_ledger(source_omr_dir, candidate)

        for name in APPROVED_BUILTINS:
            src = content_dir / name
            if not src.is_file():
                raise ReleaseError(f"approved built-in missing: {src}")
            ET.parse(src)
            shutil.copy2(src, candidate / "content" / name)

        metadata = {
            "format_version": 1,
            "mode": "ingest",
            "parser_git_sha": parser_sha,
            "app_git_sha": app_git_sha,
            "source_catalog_hash": rd._sha256_file(
                source_omr_dir / "pdfs" / "survey" / "catalog.json"
            ),
            "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        }
        if metadata["source_catalog_hash"] is None:
            raise ReleaseError("source catalog is missing; refusing to initialize candidate")
        _write_json_atomic(candidate / "build-metadata.json", metadata)
    except Exception:
        shutil.rmtree(candidate, ignore_errors=True)
        raise
    return candidate


def import_existing(*, store: Path, source_omr_dir: Path, content_dir: Path,
                    parser_git_sha: str, app_git_sha: str,
                    now: datetime | None = None) -> Path:
    """Create an unserved candidate from a complete legacy out/ingest tree.

    This is the one-time migration path. Provenance is explicit because old
    ingest state did not record it; nothing is inferred from the importer.
    Only manifest-published MusicXML/reports plus state are copied.
    """
    _require_git_sha(parser_git_sha, "parser_git_sha")
    _require_git_sha(app_git_sha, "app_git_sha")
    store = store.resolve()
    source_omr_dir = source_omr_dir.resolve()
    content_dir = content_dir.resolve()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    candidate = store / "staging" / f".staging-import-{stamp}-{secrets.token_hex(4)}"
    source_out = source_omr_dir / "out" / "ingest"
    try:
        (candidate / "out" / "ingest").mkdir(parents=True, exist_ok=False)
        (candidate / "overrides").mkdir()
        (candidate / "content").mkdir()
        (store / "releases").mkdir(parents=True, exist_ok=True)
        manifest = _load_json(source_out / "manifest.json")
        shutil.copy2(source_out / "manifest.json", candidate / "out" / "ingest" / "manifest.json")
        shutil.copy2(source_out / "ingest_state.json", candidate / "out" / "ingest" / "ingest_state.json")
        _stamp_missing_candidate_source_hashes(candidate, source_omr_dir)
        for entry in manifest:
            item_id = entry.get("id")
            rel = entry.get("musicxml")
            if not rd._is_simple_id(item_id) or rel != f"out/ingest/{item_id}.musicxml":
                raise ReleaseError(f"unsafe or inconsistent manifest entry: {item_id!r} / {rel!r}")
            for suffix in (".musicxml", ".report.json"):
                src = source_out / f"{item_id}{suffix}"
                if not src.is_file():
                    raise ReleaseError(f"manifest artifact missing: {src}")
                shutil.copy2(src, candidate / "out" / "ingest" / src.name)

        source_overrides = source_omr_dir / "overrides"
        retired = source_overrides / "RETIRED"
        if retired.is_file():
            shutil.copy2(retired, candidate / "overrides" / "RETIRED")
        for override in sorted(source_overrides.glob("*.musicxml")):
            ET.parse(override)
            shutil.copy2(override, candidate / "overrides" / override.name)
        _copy_quality_ledger(source_omr_dir, candidate)
        for name in APPROVED_BUILTINS:
            src = content_dir / name
            if not src.is_file():
                raise ReleaseError(f"approved built-in missing: {src}")
            ET.parse(src)
            shutil.copy2(src, candidate / "content" / name)

        catalog_hash = rd._sha256_file(source_omr_dir / "pdfs" / "survey" / "catalog.json")
        if catalog_hash is None:
            raise ReleaseError("source catalog is missing; refusing legacy import")
        _write_json_atomic(candidate / "build-metadata.json", {
            "format_version": 1,
            "mode": "import",
            "parser_git_sha": parser_git_sha,
            "app_git_sha": app_git_sha,
            "source_catalog_hash": catalog_hash,
            "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        })
    except Exception:
        shutil.rmtree(candidate, ignore_errors=True)
        raise
    return candidate


def _bundled_content(candidate: Path) -> dict[str, str]:
    actual = sorted(p.name for p in (candidate / "content").glob("*.musicxml"))
    if actual != sorted(APPROVED_BUILTINS):
        raise ReleaseError(
            f"bundled content allowlist mismatch: expected {sorted(APPROVED_BUILTINS)}, got {actual}"
        )
    return {name: _sha256_file(candidate / "content" / name) for name in actual}


def _published_ingest_file_names(manifest: list, *, include_marker: bool) -> set[str]:
    names = {"manifest.json", "ingest_state.json"}
    if include_marker:
        names.add("release.json")
    for entry in manifest:
        item_id = entry.get("id") if isinstance(entry, dict) else None
        rel = entry.get("musicxml") if isinstance(entry, dict) else None
        if not rd._is_simple_id(item_id) or rel != f"out/ingest/{item_id}.musicxml":
            raise ReleaseError(f"unsafe or inconsistent manifest entry: {item_id!r} / {rel!r}")
        names.add(f"{item_id}.musicxml")
        names.add(f"{item_id}.report.json")
    return names


def _prune_candidate_to_published_artifacts(candidate: Path) -> None:
    """Remove non-manifest OMR output before an unserved candidate is sealed.

    Ingestion deliberately retains review/no_music diagnostics while building.
    A sealed release must retain only manifest-backed MusicXML/reports: the
    web server's MusicXML route is filename based, so leaving those extras
    would make a withheld score guessable despite its absence from manifest.
    """
    out = candidate / "out" / "ingest"
    try:
        manifest = _load_json(out / "manifest.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"candidate manifest is unreadable for publication pruning: {exc}") from exc
    if not isinstance(manifest, list):
        raise ReleaseError("candidate manifest is not a JSON list for publication pruning")
    allowed = _published_ingest_file_names(manifest, include_marker=True)
    for path in out.iterdir():
        if path.name in allowed:
            if path.is_symlink() or not path.is_file():
                raise ReleaseError(f"candidate published artifact is not a regular file: {path.name}")
            continue
        if path.is_symlink() or path.is_dir():
            raise ReleaseError(f"candidate ingest output has unsupported path: {path.name}")
        if path.suffix in {".musicxml", ".json"}:
            path.unlink()
        else:
            raise ReleaseError(f"candidate ingest output has unsupported file: {path.name}")


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod((mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)))
    root.chmod(root.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def verify_candidate(candidate: Path, python: Path, source_omr_dir: Path | None = None) -> dict:
    candidate = candidate.resolve()
    metadata = _load_json(candidate / "build-metadata.json")
    parser_sha, dirty = _git_state(HERE)
    if dirty or (metadata.get("mode") != "import" and metadata.get("parser_git_sha") != parser_sha):
        raise ReleaseError("verification checkout does not match clean candidate provenance")
    source_inventory_hash = None
    if source_omr_dir is not None:
        source_omr_dir = source_omr_dir.resolve()
        source_inventory_hash = _candidate_source_inventory_hash(candidate, source_omr_dir)
        if _recorded_candidate_source_inventory_hash(candidate) != source_inventory_hash:
            raise ReleaseError("source PDF inventory differs from hashes recorded at candidate input time")
    command = [str(python), "-m", "pytest", str(HERE / "tests"), "-q"]
    proc = subprocess.run(command, cwd=HERE, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    sys.stdout.write(output)

    def count(label_pattern: str) -> int:
        matches = re.findall(rf"(\d+) (?:{label_pattern})(?:[,\s]|$)", output)
        return int(matches[-1]) if matches else 0

    result = {
        "format_version": 1,
        "candidate_parser_git_sha": metadata["parser_git_sha"],
        "verifier_git_sha": parser_sha,
        "command": command,
        "passed": count("passed"),
        "skipped": count("skipped"),
        "failed": count("failed") + count("errors?"),
        "exit_code": proc.returncode,
        # The private journal is an input to ledger sealing even though it
        # does not alter parser output. Bind its exact candidate copy to
        # verification so it cannot be edited between verify and seal.
        "quality_ledger_journal_hash": _candidate_journal_hash(candidate),
        "source_inventory_hash": source_inventory_hash,
        "candidate_artifact_inventory_hash": _candidate_artifact_inventory_hash(candidate),
    }
    _write_json_atomic(candidate / "verification-results.json", result)
    if proc.returncode != 0 or result["failed"] != 0 or result["passed"] == 0:
        raise ReleaseError(f"candidate verification failed: {result}")
    return result


def _verify_actual_files(release: Path, descriptor: dict) -> list[str]:
    problems: list[str] = []
    out = release / "out" / "ingest"
    manifest_path = out / "manifest.json"
    state_path = out / "ingest_state.json"
    try:
        manifest = _load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as e:
        return [f"manifest unreadable: {e}"]

    if not isinstance(manifest, list):
        return ["manifest is not a JSON list"]
    try:
        expected_ingest = _published_ingest_file_names(manifest, include_marker=True)
    except ReleaseError as exc:
        return [str(exc)]
    actual_ingest = {path.name for path in out.iterdir()}
    if actual_ingest != expected_ingest:
        problems.append(
            "sealed ingest inventory differs from manifest-backed artifacts: "
            f"missing={sorted(expected_ingest - actual_ingest)}, "
            f"unexpected={sorted(actual_ingest - expected_ingest)}"
        )
    for path in out.iterdir():
        if path.is_symlink() or not path.is_file():
            problems.append(f"sealed ingest artifact is not a regular file: {path.name}")
    if rd._sha256_json_canonical(manifest) != descriptor["manifest"]["hash"]:
        problems.append("manifest hash differs from descriptor")
    if len(manifest) != descriptor["manifest"]["entry_count"]:
        problems.append("manifest entry count differs from descriptor")
    manifest_ids = {entry.get("id") for entry in manifest}
    if manifest_ids != set(descriptor["musicxml"]["per_entry"]):
        problems.append("manifest ids differ from descriptor MusicXML inventory")

    for section, suffix in (("musicxml", ".musicxml"), ("reports", ".report.json")):
        for item_id, expected in descriptor[section]["per_entry"].items():
            path = out / f"{item_id}{suffix}"
            actual = _sha256_file(path) if path.is_file() else None
            if actual != expected:
                problems.append(f"{section} hash mismatch: {item_id}")

    state_actual = _sha256_file(state_path) if state_path.is_file() else None
    if state_actual != descriptor["state"]["hash"]:
        problems.append("ingest state hash differs from descriptor")

    override_actual = {
        p.stem: _sha256_file(p) for p in sorted((release / "overrides").glob("*.musicxml"))
    }
    if override_actual != descriptor["overrides"]["per_stem"]:
        problems.append("override inventory differs from descriptor")

    content_actual = _bundled_content(release)
    if content_actual != descriptor.get("bundled_content", {}).get("per_file"):
        problems.append("bundled content inventory differs from descriptor")
    for name in content_actual:
        try:
            ET.parse(release / "content" / name)
        except ET.ParseError as e:
            problems.append(f"bundled content is invalid XML: {name}: {e}")
    ledger_path = release / ql.SNAPSHOT_REL
    trust_dir = ledger_path.parent
    journal_dir = release / ql.JOURNAL_REL.parent
    if journal_dir.exists() or journal_dir.is_symlink():
        problems.append("mutable quality-ledger directory must not be inside a sealed release")
    if "quality_ledger" in descriptor:
        if not trust_dir.is_dir() or trust_dir.is_symlink():
            problems.append("quality ledger trust directory is missing or unsafe")
        elif {path.name for path in trust_dir.iterdir()} != {ledger_path.name}:
            problems.append("quality ledger trust directory has unexpected content")
        elif ledger_path.is_symlink() or not ledger_path.is_file():
            problems.append("quality ledger snapshot is missing or not a regular file")
        else:
            try:
                snapshot = _load_json(ledger_path)
            except (OSError, json.JSONDecodeError) as e:
                problems.append(f"quality ledger snapshot unreadable: {e}")
            else:
                problems.extend(ql.validate_snapshot(snapshot, descriptor=descriptor))
    elif trust_dir.exists() or trust_dir.is_symlink():
        problems.append("unbound quality ledger trust directory exists in a legacy descriptor release")
    return problems


def validate_release(release: Path) -> dict:
    descriptor_path = release / "release-descriptor.json"
    marker_path = release / "out" / "ingest" / "release.json"
    try:
        descriptor = _load_json(descriptor_path)
    except (OSError, json.JSONDecodeError) as e:
        raise ReleaseError(f"descriptor unreadable: {e}") from e
    problems = rd.validate_descriptor(descriptor)
    if descriptor.get("readiness", {}).get("promotable") is not True:
        problems.append(f"descriptor is not promotable: {descriptor.get('readiness')}")
    problems.extend(_verify_actual_files(release, descriptor))
    try:
        marker = _load_json(marker_path)
    except (OSError, json.JSONDecodeError) as e:
        problems.append(f"public release marker unreadable: {e}")
    else:
        expected_marker = {
            "schema_version": descriptor["schema_version"],
            "release_id": descriptor["release_id"],
            "content_fingerprint": descriptor["content_fingerprint"],
        }
        if marker != expected_marker:
            problems.append("public release marker differs from descriptor")
    if problems:
        raise ReleaseError("release validation failed:\n  - " + "\n  - ".join(problems))
    return descriptor


def seal_candidate(*, store: Path, candidate: Path, source_omr_dir: Path,
                   verified_passed: int | None = None, verified_skipped: int | None = None,
                   verified_failed: int | None = None,
                   now: datetime | None = None) -> Path:
    store = store.resolve()
    candidate = _contained(candidate, store / "staging")
    if candidate.parent != (store / "staging").resolve() or not candidate.name.startswith(".staging-"):
        raise ReleaseError("candidate must be a direct .staging-* child of store/staging")
    metadata = _load_json(candidate / "build-metadata.json")
    parser_sha, dirty = _git_state(HERE)
    if dirty:
        raise ReleaseError("release builder checkout is dirty")
    if metadata.get("mode") != "import" and metadata.get("parser_git_sha") != parser_sha:
        raise ReleaseError(
            "parser SHA changed after candidate initialization; discard it and start a new candidate"
        )
    current_catalog_hash = rd._sha256_file(
        source_omr_dir / "pdfs" / "survey" / "catalog.json"
    )
    if metadata.get("source_catalog_hash") != current_catalog_hash:
        raise ReleaseError(
            "source catalog changed after candidate initialization; discard it and start a new candidate"
        )
    current_source_inventory_hash = _candidate_source_inventory_hash(
        candidate, source_omr_dir.resolve(),
    )
    if _recorded_candidate_source_inventory_hash(candidate) != current_source_inventory_hash:
        raise ReleaseError("source PDF inventory differs from hashes recorded at candidate input time")
    current_artifact_inventory_hash = _candidate_artifact_inventory_hash(candidate)
    current_journal_hash = _candidate_journal_hash(candidate)
    _require_git_sha(metadata.get("parser_git_sha"), "parser_git_sha")
    _require_git_sha(metadata.get("app_git_sha"), "app_git_sha")
    if verified_passed is None or verified_skipped is None or verified_failed is None:
        verification = _load_json(candidate / "verification-results.json")
        if verification.get("candidate_parser_git_sha") != metadata.get("parser_git_sha"):
            raise ReleaseError("verification evidence parser SHA does not match candidate")
        if verification.get("exit_code") != 0:
            raise ReleaseError("verification evidence records a nonzero exit")
        if verification.get("quality_ledger_journal_hash") != _candidate_journal_hash(candidate):
            raise ReleaseError("quality ledger journal changed after candidate verification")
        if verification.get("source_inventory_hash") != current_source_inventory_hash:
            raise ReleaseError("source PDF inventory changed after candidate verification")
        if verification.get("candidate_artifact_inventory_hash") != current_artifact_inventory_hash:
            raise ReleaseError("candidate artifacts changed after candidate verification")
        verified_passed = verification.get("passed")
        verified_skipped = verification.get("skipped")
        verified_failed = verification.get("failed")
    if verified_failed != 0:
        raise ReleaseError(f"cannot seal with {verified_failed} failing verification test(s)")

    _prune_candidate_to_published_artifacts(candidate)

    parent = _pointer_release_id(store, "current")
    parent_ledger = None
    if parent:
        parent_release = _release_path(store, parent)
        # A child must never inherit history from a current pointer whose
        # release is already invalid or whose ledger binding was tampered.
        validate_release(parent_release)
        parent_path = parent_release / ql.SNAPSHOT_REL
        if parent_path.is_file():
            parent_ledger = ql.load_snapshot(parent_path)

    descriptor_base = rd.build_release_descriptor(
        omr_dir=candidate,
        source_omr_dir=source_omr_dir,
        parent_release_id=parent,
        now=now,
        parser_git_sha=metadata["parser_git_sha"],
        app_git_sha=metadata["app_git_sha"],
        verified_passed=verified_passed,
        verified_skipped=verified_skipped,
        verified_failed=verified_failed,
        bundled_content=_bundled_content(candidate),
    )
    if descriptor_base["input"]["source_inventory_hash"] != current_source_inventory_hash:
        raise ReleaseError("source PDF inventory changed while building the candidate descriptor")
    ledger_body, ledger_summary = ql.build_ledger_body(
        candidate=candidate,
        descriptor=descriptor_base,
        parent_snapshot=parent_ledger,
    )
    descriptor = rd.build_release_descriptor(
        omr_dir=candidate,
        source_omr_dir=source_omr_dir,
        parent_release_id=parent,
        now=now,
        parser_git_sha=metadata["parser_git_sha"],
        app_git_sha=metadata["app_git_sha"],
        verified_passed=verified_passed,
        verified_skipped=verified_skipped,
        verified_failed=verified_failed,
        bundled_content=_bundled_content(candidate),
        quality_ledger=ledger_summary,
    )
    if descriptor["input"]["source_inventory_hash"] != current_source_inventory_hash:
        raise ReleaseError("source PDF inventory changed while finalizing the candidate descriptor")
    if rd._sha256_file(source_omr_dir / "pdfs" / "survey" / "catalog.json") != current_catalog_hash:
        raise ReleaseError("source catalog changed while finalizing the candidate")
    if _candidate_source_inventory_hash(candidate, source_omr_dir.resolve()) != current_source_inventory_hash:
        raise ReleaseError("source PDF inventory changed while finalizing the candidate")
    if _recorded_candidate_source_inventory_hash(candidate) != current_source_inventory_hash:
        raise ReleaseError("recorded source PDF inventory changed while finalizing the candidate")
    if _candidate_artifact_inventory_hash(candidate) != current_artifact_inventory_hash:
        raise ReleaseError("candidate artifacts changed while finalizing the candidate")
    if _candidate_journal_hash(candidate) != current_journal_hash:
        raise ReleaseError("quality ledger journal changed while finalizing the candidate")
    problems = rd.validate_descriptor(descriptor)
    if problems or not descriptor["readiness"]["promotable"]:
        detail = problems or descriptor["readiness"]["reasons"]
        raise ReleaseError("candidate is not sealable:\n  - " + "\n  - ".join(detail))

    _write_json_atomic(candidate / "release-descriptor.json", descriptor)
    ql.write_snapshot(candidate / ql.SNAPSHOT_REL, ledger_body, descriptor)
    _write_json_atomic(candidate / "out" / "ingest" / "release.json", {
        "schema_version": descriptor["schema_version"],
        "release_id": descriptor["release_id"],
        "content_fingerprint": descriptor["content_fingerprint"],
    })
    journal_path = candidate / ql.JOURNAL_REL
    journal_dir = journal_path.parent
    journal_bytes = None
    if journal_dir.exists() or journal_dir.is_symlink():
        if journal_dir.is_symlink() or not journal_dir.is_dir():
            raise ReleaseError("candidate quality-ledger path is unsafe")
        contents = {path.name for path in journal_dir.iterdir()}
        if contents != {journal_path.name} or not journal_path.is_file() or journal_path.is_symlink():
            raise ReleaseError("candidate quality-ledger directory has unexpected content")
        journal_bytes = journal_path.read_bytes()
    try:
        if journal_bytes is not None:
            journal_path.unlink()
            journal_dir.rmdir()
        validate_release(candidate)
    except Exception:
        if journal_bytes is not None:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            journal_path.write_bytes(journal_bytes)
        raise

    (store / "releases").mkdir(parents=True, exist_ok=True)
    destination = _release_path(store, descriptor["release_id"])
    if destination.exists():
        raise ReleaseError(f"sealed release already exists: {destination}")
    os.replace(candidate, destination)
    _fsync_dir(destination.parent)
    _make_read_only(destination)
    return destination


def release_diff(old: dict | None, new: dict) -> dict:
    old = old or {}
    old_xml = old.get("musicxml", {}).get("per_entry", {})
    new_xml = new["musicxml"]["per_entry"]
    old_ids, new_ids = set(old_xml), set(new_xml)
    changed = sorted(i for i in old_ids & new_ids if old_xml[i] != new_xml[i])
    return {
        "from_release_id": old.get("release_id"),
        "to_release_id": new["release_id"],
        "manifest_entries": {
            "before": old.get("manifest", {}).get("entry_count", 0),
            "after": new["manifest"]["entry_count"],
            "delta": new["manifest"]["entry_count"] - old.get("manifest", {}).get("entry_count", 0),
        },
        "pieces": {
            "added": sorted(new_ids - old_ids),
            "removed": sorted(old_ids - new_ids),
            "changed": changed,
        },
        "status_counts": {
            key: {
                "before": old.get("trust", {}).get("status_counts", {}).get(key, 0),
                "after": value,
                "delta": value - old.get("trust", {}).get("status_counts", {}).get(key, 0),
            }
            for key, value in new["trust"]["status_counts"].items()
        },
        "confidence": {
            "before": old.get("trust", {}).get("confidence"),
            "after": new["trust"]["confidence"],
        },
        "quality_ledger": {
            "before": old.get("quality_ledger"),
            "after": new.get("quality_ledger"),
        },
    }


def _atomic_pointer(store: Path, name: str, release_id: str, *, inject_failure=None) -> None:
    target_rel = Path("releases") / release_id
    tmp = store / f".{name}.tmp-{os.getpid()}"
    tmp.unlink(missing_ok=True)
    try:
        os.symlink(target_rel, tmp)
        if inject_failure == f"before_{name}_replace":
            raise ReleaseError(f"injected failure before {name} pointer replace")
        os.replace(tmp, store / name)
        _fsync_dir(store)
    finally:
        tmp.unlink(missing_ok=True)


def promote(*, store: Path, release_id: str, approval: str,
            inject_failure: str | None = None) -> dict:
    store = store.resolve()
    if approval != release_id:
        raise ReleaseError("approval boundary failed: --approve must exactly match --release-id")
    release = _release_path(store, release_id)
    descriptor = validate_release(release)
    store.mkdir(parents=True, exist_ok=True)
    with (store / ".promotion.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _pointer_release_id(store, "current")
        if current == release_id:
            return descriptor
        if inject_failure == "before_previous_replace":
            raise ReleaseError("injected failure before previous pointer replace")
        if current:
            _atomic_pointer(store, "previous", current, inject_failure=inject_failure)
        if inject_failure == "after_previous_replace":
            raise ReleaseError("injected failure after previous pointer replace")
        _atomic_pointer(store, "current", release_id, inject_failure=inject_failure)
    return descriptor


def rollback(*, store: Path, approval: str, inject_failure: str | None = None) -> dict:
    target = _pointer_release_id(store.resolve(), "previous")
    if not target:
        raise ReleaseError("no previous release is available for rollback")
    return promote(
        store=store, release_id=target, approval=approval,
        inject_failure=inject_failure,
    )


def smoke_http(base_url: str, expected_release_id: str) -> dict:
    base = base_url.rstrip("/") + "/"

    def get(path: str):
        request = urllib.request.Request(
            base + path,
            headers={"User-Agent": "ChanterLab-release-smoke/1.0"},
        )
        return urllib.request.urlopen(request, timeout=15)

    with get("omr/out/ingest/release.json") as r:
        marker = json.load(r)
    if marker.get("release_id") != expected_release_id:
        raise ReleaseError(
            f"served release mismatch: expected {expected_release_id}, got {marker.get('release_id')}"
        )
    with get("omr/out/ingest/manifest.json") as r:
        manifest = json.load(r)
    if not manifest:
        raise ReleaseError("served manifest is empty")
    first = manifest[0]["musicxml"]
    with get("omr/" + first) as r:
        ET.fromstring(r.read())
    return {"release_id": marker["release_id"], "manifest_entries": len(manifest), "sample": first}


def _descriptor_for(store: Path, release_id: str | None) -> dict | None:
    if not release_id:
        return None
    return _load_json(_release_path(store, release_id) / "release-descriptor.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="initialize a unique, unserved staging candidate")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--source-omr-dir", required=True, type=Path)
    p.add_argument("--content-dir", type=Path)
    p.add_argument("--app-sha", required=True)

    p = sub.add_parser("import-existing", help="stage the validated legacy catalog for first migration")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--source-omr-dir", required=True, type=Path)
    p.add_argument("--content-dir", type=Path)
    p.add_argument("--parser-sha", required=True)
    p.add_argument("--app-sha", required=True)

    p = sub.add_parser("seal", help="validate and immutably seal a completed candidate")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--source-omr-dir", required=True, type=Path)

    p = sub.add_parser("verify", help="run the required OMR suite and record candidate-bound evidence")
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--python", required=True, type=Path)
    p.add_argument("--source-omr-dir", required=True, type=Path)

    p = sub.add_parser("diff", help="print semantic differences from active to candidate")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--release-id", required=True)

    p = sub.add_parser("validate", help="validate a sealed release and its actual files")
    p.add_argument("--release-dir", required=True, type=Path)

    p = sub.add_parser("promote", help="atomically switch current to a sealed release")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--release-id", required=True)
    p.add_argument("--approve", required=True)

    p = sub.add_parser("rollback", help="atomically switch current to previous")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--approve", required=True, help="must equal the previous release id")

    p = sub.add_parser("status", help="show current/previous release ids")
    p.add_argument("--store", required=True, type=Path)

    p = sub.add_parser("smoke", help="verify the release id and a real score over HTTP")
    p.add_argument("--base-url", required=True)
    p.add_argument("--release-id", required=True)

    args = ap.parse_args(argv)
    try:
        if args.command == "new":
            content_dir = args.content_dir or args.source_omr_dir.parent / "content"
            print(new_candidate(
                store=args.store, source_omr_dir=args.source_omr_dir,
                content_dir=content_dir, app_git_sha=args.app_sha,
            ))
        elif args.command == "import-existing":
            content_dir = args.content_dir or args.source_omr_dir.parent / "content"
            print(import_existing(
                store=args.store, source_omr_dir=args.source_omr_dir,
                content_dir=content_dir, parser_git_sha=args.parser_sha,
                app_git_sha=args.app_sha,
            ))
        elif args.command == "seal":
            print(seal_candidate(
                store=args.store, candidate=args.candidate,
                source_omr_dir=args.source_omr_dir,
            ))
        elif args.command == "verify":
            print(json.dumps(verify_candidate(
                args.candidate, args.python, args.source_omr_dir,
            ), sort_keys=True))
        elif args.command == "diff":
            current = _pointer_release_id(args.store.resolve(), "current")
            print(json.dumps(release_diff(
                _descriptor_for(args.store.resolve(), current),
                _descriptor_for(args.store.resolve(), args.release_id),
            ), indent=2, sort_keys=True))
        elif args.command == "validate":
            d = validate_release(args.release_dir.resolve())
            print(d["release_id"])
        elif args.command == "promote":
            d = promote(store=args.store, release_id=args.release_id, approval=args.approve)
            print(f"promoted {d['release_id']}")
        elif args.command == "rollback":
            d = rollback(store=args.store, approval=args.approve)
            print(f"rolled back to {d['release_id']}")
        elif args.command == "status":
            print(json.dumps({
                "current": _pointer_release_id(args.store.resolve(), "current"),
                "previous": _pointer_release_id(args.store.resolve(), "previous"),
            }, sort_keys=True))
        elif args.command == "smoke":
            print(json.dumps(smoke_http(args.base_url, args.release_id), sort_keys=True))
    except (ReleaseError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"catalog_release: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
