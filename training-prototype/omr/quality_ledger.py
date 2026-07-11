#!/usr/bin/env python3
"""Private quality-ledger journal and immutable release snapshot support.

The ingest pipeline's ``accepted`` status means only that a score is
publishable by its current structural guards. It is not human verification.
This module keeps review decisions in an ignored, append-only journal and
reconciles them into a sealed, release-local ledger snapshot. The snapshot is
bound into the release descriptor but is deliberately not part of the public
catalog or web-server allowlist.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

try:
    import jsonschema
except ImportError:  # pragma: no cover - only exercised without release deps
    jsonschema = None

import release_descriptor as rd


LEDGER_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1
JOURNAL_REL = Path("quality-ledger") / "ledger.json"
SNAPSHOT_REL = Path("trust") / "quality-ledger.json"
SCHEMA_FILE = Path(__file__).resolve().parent / "schema" / "quality_ledger.schema.json"

STATUS_VALUES = (
    "auto-imported",
    "human-verified",
    "known-issue",
    "review-required",
    "manual-override",
    "retired",
)
ACTIVE_FORBIDDEN_STATUSES = {"review-required", "retired"}
INACTIVE_ALLOWED_STATUSES = {"review-required", "retired"}
ACTOR_ROLES = {"system", "reviewer", "owner"}

_SOURCE_ID_RE = re.compile(r"^source-[0-9a-f]{64}$")
_SCORE_ID_RE = re.compile(r"^score-[0-9a-f]{64}$")
_EVENT_ID_RE = re.compile(r"^evt-[0-9a-f]{16,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_EVIDENCE_KIND_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


class LedgerError(RuntimeError):
    """A malformed journal or unreconcilable ledger state."""


def _canonical_hash(value) -> str:
    return rd._sha256_json_canonical(value)


def _load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: Path, value) -> None:
    _ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        path.chmod(0o600)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise LedgerError(f"private ledger path is not a regular directory: {path}")
    path.chmod(0o700)


@contextmanager
def _journal_lock(journal_path: Path):
    _ensure_private_dir(journal_path.parent)
    lock_path = journal_path.parent / ".ledger.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _is_opaque_ref(value) -> bool:
    return isinstance(value, str) and bool(_OPAQUE_REF_RE.fullmatch(value))


def source_id_for(source_url: str | None, pdf_sha256: str | None) -> str | None:
    """A source identity never includes a local path or release identity."""
    if not isinstance(source_url, str) or not source_url or not isinstance(pdf_sha256, str):
        return None
    if not _SHA256_RE.fullmatch(pdf_sha256):
        return None
    return "source-" + _canonical_hash({
        "source_url": source_url,
        "pdf_sha256": pdf_sha256,
    })


def score_id_for(catalog_id: str, source_id: str | None, musicxml_sha256: str | None) -> str | None:
    """An immutable emitted-score identity, independent of its release."""
    if not rd._is_simple_id(catalog_id):
        return None
    if not isinstance(source_id, str) or not _SOURCE_ID_RE.fullmatch(source_id):
        return None
    if not isinstance(musicxml_sha256, str) or not _SHA256_RE.fullmatch(musicxml_sha256):
        return None
    return "score-" + _canonical_hash({
        "catalog_id": catalog_id,
        "source_id": source_id,
        "musicxml_sha256": musicxml_sha256,
    })


def empty_journal() -> dict:
    return {"schema_version": JOURNAL_SCHEMA_VERSION, "events": []}


def _event_problems(event: object) -> list[str]:
    if not isinstance(event, dict):
        return ["event is not an object"]
    problems = []
    required = {
        "event_id", "catalog_id", "score_id", "source_id", "from_status",
        "to_status", "recorded_at", "actor", "evidence",
    }
    missing = sorted(required - set(event))
    if missing:
        problems.append(f"event is missing fields: {', '.join(missing)}")
    unexpected = sorted(set(event) - required)
    if unexpected:
        problems.append(f"event has unsupported fields: {', '.join(unexpected)}")
    if not _EVENT_ID_RE.fullmatch(event.get("event_id", "")):
        problems.append("event_id must be evt- followed by 16-64 lowercase hex characters")
    if not rd._is_simple_id(event.get("catalog_id")):
        problems.append("catalog_id is not a simple score id")
    if not _SCORE_ID_RE.fullmatch(event.get("score_id", "")):
        problems.append("score_id is invalid")
    if not _SOURCE_ID_RE.fullmatch(event.get("source_id", "")):
        problems.append("source_id is invalid")
    from_status = event.get("from_status")
    to_status = event.get("to_status")
    if from_status not in STATUS_VALUES or to_status not in STATUS_VALUES:
        problems.append("event status is not in the TRUST-01 vocabulary")
    elif from_status == to_status:
        problems.append("event cannot transition to the same status")
    if _timestamp(event.get("recorded_at")) is None:
        problems.append("recorded_at must be a timezone-aware ISO 8601 timestamp")

    actor = event.get("actor")
    if not isinstance(actor, dict):
        problems.append("actor must be an object")
    else:
        if set(actor) - {"role", "ref"}:
            problems.append("actor has unsupported fields")
        role = actor.get("role")
        if role not in ACTOR_ROLES:
            problems.append("actor role is invalid")
        ref = actor.get("ref")
        if role in {"reviewer", "owner"} and not _is_opaque_ref(ref):
            problems.append("reviewer/owner actor ref must be an opaque token")
        if role == "system" and ref is not None and not _is_opaque_ref(ref):
            problems.append("system actor ref must be null or an opaque token")

    evidence = event.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append("event requires at least one opaque evidence reference")
    else:
        for index, item in enumerate(evidence):
            if not isinstance(item, dict) or set(item) != {"kind", "ref"}:
                problems.append(f"evidence[{index}] must contain exactly kind and ref")
                continue
            if not _EVIDENCE_KIND_RE.fullmatch(item.get("kind", "")):
                problems.append(f"evidence[{index}].kind is invalid")
            if not _is_opaque_ref(item.get("ref")):
                problems.append(f"evidence[{index}].ref must be an opaque token")

    if not problems and from_status in STATUS_VALUES and to_status in STATUS_VALUES:
        role = actor["role"]
        allowed = _allowed_targets(from_status)
        if to_status not in allowed:
            problems.append(f"invalid status transition: {from_status} -> {to_status}")
        elif to_status == "retired" and role != "owner":
            problems.append("only an owner can retire a score")
        elif to_status in {"human-verified", "known-issue", "review-required"} and role not in {"reviewer", "owner"}:
            problems.append(f"{to_status} requires reviewer or owner authority")
    return problems


def _allowed_targets(from_status: str) -> set[str]:
    return {
        "auto-imported": {"human-verified", "known-issue", "review-required", "retired"},
        "human-verified": {"known-issue", "review-required", "retired"},
        "known-issue": {"human-verified", "review-required", "retired"},
        "review-required": {"human-verified", "known-issue", "retired"},
        "manual-override": {"review-required", "retired"},
        "retired": set(),
    }.get(from_status, set())


def journal_problems(journal: object) -> list[str]:
    """Validate the private append-only journal independent of a catalog."""
    if not isinstance(journal, dict):
        return ["journal is not a JSON object"]
    problems = []
    if journal.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        problems.append("journal schema_version is unsupported")
    if set(journal) != {"schema_version", "events"}:
        problems.append("journal must contain exactly schema_version and events")
    events = journal.get("events")
    if not isinstance(events, list):
        return problems + ["journal events must be a list"]

    event_ids = set()
    previous_times: dict[str, datetime] = {}
    for index, event in enumerate(events):
        for problem in _event_problems(event):
            problems.append(f"events[{index}]: {problem}")
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        if event_id in event_ids:
            problems.append(f"events[{index}]: duplicate event_id {event_id!r}")
        event_ids.add(event_id)
        score_id = event.get("score_id")
        recorded_at = _timestamp(event.get("recorded_at"))
        if recorded_at and isinstance(score_id, str):
            previous = previous_times.get(score_id)
            if previous and recorded_at < previous:
                problems.append(f"events[{index}]: event time moves backward for {score_id}")
            previous_times[score_id] = recorded_at
    return problems


def load_journal(path: Path) -> dict:
    """Load a journal; an absent file is the valid zero-review migration."""
    if not path.is_file():
        return empty_journal()
    try:
        journal = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"quality ledger journal is unreadable: {exc}") from exc
    problems = journal_problems(journal)
    if problems:
        raise LedgerError("quality ledger journal is invalid:\n  - " + "\n  - ".join(problems))
    return journal


def write_journal(path: Path, journal: dict) -> None:
    problems = journal_problems(journal)
    if problems:
        raise LedgerError("refusing to write invalid journal:\n  - " + "\n  - ".join(problems))
    _write_json_atomic(path, journal)


def _warning_summary(report_path: Path, state_record: dict) -> tuple[int, dict]:
    """Return a non-textual warning summary; report prose stays out of ledger."""
    count = state_record.get("warnings")
    if not isinstance(count, int) or count < 0:
        count = 0
    if report_path.is_file():
        try:
            report = _load_json(report_path)
        except (OSError, json.JSONDecodeError):
            report = None
        warnings = report.get("warnings") if isinstance(report, dict) else None
        if isinstance(warnings, list):
            count = len(warnings)
    return count, {"count": count}


def _record_for_active(
    *,
    catalog_id: str,
    manifest_entry: dict,
    state_record: dict,
    descriptor: dict,
    candidate: Path,
    problems: list[str],
) -> dict | None:
    source = {
        item["id"]: item
        for item in descriptor.get("input", {}).get("source_inventory", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }.get(catalog_id)
    if not isinstance(source, dict):
        problems.append(f"{catalog_id}: source inventory entry is missing")
        return None
    source_url = source.get("source_url")
    pdf_sha256 = source.get("pdf_sha256")
    source_id = source_id_for(source_url, pdf_sha256)
    if source_id is None:
        problems.append(f"{catalog_id}: active score lacks URL or source PDF hash")

    musicxml_sha256 = descriptor.get("musicxml", {}).get("per_entry", {}).get(catalog_id)
    report_sha256 = descriptor.get("reports", {}).get("per_entry", {}).get(catalog_id)
    if not isinstance(musicxml_sha256, str) or not _SHA256_RE.fullmatch(musicxml_sha256):
        problems.append(f"{catalog_id}: active score lacks a resolved MusicXML hash")
    if not isinstance(report_sha256, str) or not _SHA256_RE.fullmatch(report_sha256):
        problems.append(f"{catalog_id}: active score lacks a resolved report hash")
    score_id = score_id_for(catalog_id, source_id, musicxml_sha256)
    if score_id is None:
        problems.append(f"{catalog_id}: immutable score identity cannot be derived")
        return None

    report_path = candidate / "out" / "ingest" / f"{catalog_id}.report.json"
    warning_count, warning_summary = _warning_summary(report_path, state_record)
    integrity = state_record.get("integrity_pct")
    if not isinstance(integrity, (int, float)) or isinstance(integrity, bool):
        integrity = None
    parser_sha = descriptor.get("code", {}).get("parser_git_sha")
    if not isinstance(parser_sha, str) or not _GIT_SHA_RE.fullmatch(parser_sha):
        problems.append(f"{catalog_id}: parser provenance is missing or invalid")

    return {
        "catalog_id": catalog_id,
        "source_id": source_id,
        "score_id": score_id,
        "previous_score_id": None,
        "parser_git_sha": parser_sha,
        "active": True,
        "initial_status": "auto-imported",
        "status": "auto-imported",
        "provenance": {
            "title": manifest_entry.get("title", state_record.get("name")),
            "composer": manifest_entry.get("composer", state_record.get("composer")),
            "book": manifest_entry.get("bookName"),
            "edition": None,
            "source_url": source_url,
            "pdf_sha256": pdf_sha256,
        },
        "artifacts": {
            "musicxml_sha256": musicxml_sha256,
            "report_sha256": report_sha256,
        },
        "confidence": {
            "reference": "legacy-measure-integrity-v1",
            "integrity_pct": integrity,
            "warning_count": warning_count,
            "warning_summary": warning_summary,
        },
        "override_history": {
            "active_override_sha256": None,
            "last_override_sha256": None,
            "tombstoned": False,
        },
        "history": [],
    }


def _summary_for(records: list[dict]) -> dict:
    status_counts = {status: 0 for status in STATUS_VALUES}
    for record in records:
        status = record.get("status")
        if status in status_counts:
            status_counts[status] += 1
    body = {"schema_version": LEDGER_SCHEMA_VERSION, "records": records}
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "record_count": len(records),
        "active_count": sum(1 for record in records if record.get("active") is True),
        "status_counts": status_counts,
        "hash": _canonical_hash(body),
    }


def _history_event_map(records: list[dict]) -> dict[str, dict]:
    result = {}
    for record in records:
        for event in record.get("history", []):
            if isinstance(event, dict) and isinstance(event.get("event_id"), str):
                result[event["event_id"]] = event
    return result


def _apply_event(record: dict, event: dict, problems: list[str]) -> None:
    prefix = f"{record.get('catalog_id', '<unknown>')}/{record.get('score_id', '<unknown>')}"
    if event.get("catalog_id") != record.get("catalog_id"):
        problems.append(f"{prefix}: event {event.get('event_id')!r} has a different catalog_id")
        return
    if event.get("score_id") != record.get("score_id"):
        problems.append(f"{prefix}: event {event.get('event_id')!r} has a stale score_id")
        return
    if event.get("source_id") != record.get("source_id"):
        problems.append(f"{prefix}: event {event.get('event_id')!r} has a stale source_id")
        return
    if event.get("from_status") != record.get("status"):
        problems.append(
            f"{prefix}: event {event.get('event_id')!r} expected {event.get('from_status')!r}, "
            f"current status is {record.get('status')!r}"
        )
        return
    record["history"].append(copy.deepcopy(event))
    record["status"] = event["to_status"]


def _load_parent_records(parent_snapshot: dict | None) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    if parent_snapshot is None:
        return [], {}, {}
    problems = validate_snapshot(parent_snapshot)
    if problems:
        raise LedgerError("parent quality ledger is invalid:\n  - " + "\n  - ".join(problems))
    records = copy.deepcopy(parent_snapshot["records"])
    return (
        records,
        {record["score_id"]: record for record in records},
        _history_event_map(records),
    )


def build_ledger_body(*, candidate: Path, descriptor: dict, parent_snapshot: dict | None = None) -> tuple[dict, dict]:
    """Reconcile a staged candidate and private journal into deterministic body.

    It does not write anything and it does not need a release ID, so the body
    can be hashed before descriptor construction without a hash cycle.
    """
    candidate = Path(candidate)
    try:
        manifest = _load_json(candidate / "out" / "ingest" / "manifest.json")
        state = _load_json(candidate / "out" / "ingest" / "ingest_state.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"candidate ingest data is unreadable: {exc}") from exc
    if not isinstance(manifest, list) or not isinstance(state, dict):
        raise LedgerError("candidate manifest/state have invalid shapes")
    journal = load_journal(candidate / JOURNAL_REL)
    parent_records, parent_by_score, parent_events = _load_parent_records(parent_snapshot)
    problems: list[str] = []

    # A mutable journal may retain an event that is already sealed in the
    # parent snapshot, but it may never rewrite that event under the same ID.
    # Check this before deciding whether the event targets a current or a
    # retained historical score, so removal from manifest cannot hide it.
    for event in journal["events"]:
        prior = parent_events.get(event["event_id"])
        if prior is not None and _canonical_hash(prior) != _canonical_hash(event):
            problems.append(f"event {event['event_id']!r} was changed after it was sealed")

    manifest_entries: dict[str, dict] = {}
    for entry in manifest:
        if not isinstance(entry, dict) or not rd._is_simple_id(entry.get("id")):
            problems.append("manifest contains a non-simple id")
            continue
        item_id = entry["id"]
        if item_id in manifest_entries:
            problems.append(f"manifest contains duplicate id {item_id!r}")
            continue
        manifest_entries[item_id] = entry

    events_by_score: dict[str, list[dict]] = {}
    for event in journal["events"]:
        events_by_score.setdefault(event["score_id"], []).append(event)

    records: list[dict] = []
    active_scores: set[str] = set()
    used_events: set[str] = set(parent_events)
    tombstones = set(descriptor.get("overrides", {}).get("tombstones", []))
    active_overrides = descriptor.get("overrides", {}).get("per_stem", {})

    for catalog_id in sorted(manifest_entries):
        state_record = state.get(catalog_id)
        if not isinstance(state_record, dict):
            problems.append(f"{catalog_id}: active manifest entry has no state record")
            continue
        record = _record_for_active(
            catalog_id=catalog_id,
            manifest_entry=manifest_entries[catalog_id],
            state_record=state_record,
            descriptor=descriptor,
            candidate=candidate,
            problems=problems,
        )
        if record is None:
            continue
        score_id = record["score_id"]
        active_scores.add(score_id)
        prior_same = parent_by_score.get(score_id)
        prior_catalog = [
            parent for parent in parent_records
            if parent.get("catalog_id") == catalog_id and parent.get("active") is True
        ]
        if prior_same is not None and prior_same.get("override_history", {}).get("active_override_sha256") is None:
            # Same immutable score revision: preserve an already-audited status
            # and history. A new revision intentionally starts at auto-imported.
            record["initial_status"] = prior_same["initial_status"]
            record["status"] = prior_same["status"]
            record["history"] = copy.deepcopy(prior_same["history"])
            record["previous_score_id"] = prior_same.get("previous_score_id")
        elif prior_catalog:
            record["previous_score_id"] = sorted(prior_catalog, key=lambda r: r["score_id"])[-1]["score_id"]

        override_hash = active_overrides.get(catalog_id)
        tombstoned = catalog_id in tombstones
        if override_hash is not None and tombstoned:
            problems.append(f"{catalog_id}: active override conflicts with retired-override tombstone")
        if override_hash is not None:
            record["initial_status"] = "manual-override"
            record["status"] = "manual-override"
            record["history"] = []
            record["override_history"]["active_override_sha256"] = override_hash
            record["override_history"]["last_override_sha256"] = override_hash
        record["override_history"]["tombstoned"] = tombstoned

        for event in events_by_score.get(score_id, []):
            event_id = event["event_id"]
            if event_id in parent_events:
                if _canonical_hash(parent_events[event_id]) != _canonical_hash(event):
                    problems.append(f"event {event_id!r} was changed after it was sealed")
                continue
            if override_hash is not None:
                problems.append(f"{catalog_id}: journal event {event_id!r} cannot target an active manual override")
                continue
            _apply_event(record, event, problems)
            used_events.add(event_id)
        if record["status"] in ACTIVE_FORBIDDEN_STATUSES:
            problems.append(f"{catalog_id}: active score cannot be {record['status']!r}; remove it from manifest first")
        records.append(record)

    # Retain only explicitly withheld/retired historical revisions. An event
    # that names an old score revision must be exact; it cannot silently carry
    # a review decision across changed MusicXML or source bytes.
    for score_id, events in sorted(events_by_score.items()):
        new_events = [event for event in events if event["event_id"] not in parent_events]
        if not new_events:
            continue
        if score_id in active_scores:
            continue
        parent = parent_by_score.get(score_id)
        if parent is None:
            problems.append(f"journal targets unknown or stale score_id {score_id!r}")
            continue
        record = copy.deepcopy(parent)
        record["active"] = False
        for event in new_events:
            _apply_event(record, event, problems)
            used_events.add(event["event_id"])
        active_override = record["override_history"]["active_override_sha256"]
        if active_override is not None and record["status"] != "manual-override":
            record["override_history"]["last_override_sha256"] = active_override
            record["override_history"]["active_override_sha256"] = None
        if record["status"] not in INACTIVE_ALLOWED_STATUSES:
            problems.append(
                f"{record['catalog_id']}: non-active historical score must end as review-required or retired"
            )
        records.append(record)

    # Preserve a historical record once it was deliberately withheld/retired.
    for parent in parent_records:
        if parent["score_id"] in active_scores:
            continue
        if parent["score_id"] in {record["score_id"] for record in records}:
            continue
        if parent.get("active") is False and parent.get("status") in INACTIVE_ALLOWED_STATUSES:
            records.append(copy.deepcopy(parent))

    all_event_ids = {event["event_id"] for event in journal["events"]}
    unused = sorted(all_event_ids - used_events)
    if unused:
        problems.append("journal contains event(s) that do not match this candidate: " + ", ".join(unused))

    records.sort(key=lambda record: (record["catalog_id"], record["score_id"]))
    body = {"schema_version": LEDGER_SCHEMA_VERSION, "records": records}
    summary = _summary_for(records)
    snapshot_problems = validate_ledger_body(body, descriptor=descriptor)
    problems.extend(snapshot_problems)
    if problems:
        raise LedgerError("quality ledger reconciliation failed:\n  - " + "\n  - ".join(sorted(set(problems))))
    return body, summary


def snapshot_for_descriptor(body: dict, descriptor: dict) -> dict:
    """Bind a pre-hashed ledger body to its descriptor after release ID exists."""
    summary = _summary_for(body.get("records", []))
    expected = descriptor.get("quality_ledger")
    if expected != summary:
        raise LedgerError("descriptor quality_ledger section does not match the ledger body")
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "release_id": descriptor["release_id"],
        "release_content_fingerprint": descriptor["content_fingerprint"],
        "ledger_hash": summary["hash"],
        "summary": summary,
        "records": body["records"],
    }


def write_snapshot(path: Path, body: dict, descriptor: dict) -> dict:
    snapshot = snapshot_for_descriptor(body, descriptor)
    problems = validate_snapshot(snapshot, descriptor=descriptor)
    if problems:
        raise LedgerError("refusing to write invalid quality ledger snapshot:\n  - " + "\n  - ".join(problems))
    _write_json_atomic(path, snapshot)
    return snapshot


def _load_schema() -> dict:
    with SCHEMA_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def _record_problems(record: object, *, descriptor: dict | None = None) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    problems = []
    required = {
        "catalog_id", "source_id", "score_id", "previous_score_id", "parser_git_sha",
        "active", "initial_status", "status", "provenance", "artifacts", "confidence",
        "override_history", "history",
    }
    if set(record) != required:
        problems.append("record has missing or unsupported fields")
    catalog_id = record.get("catalog_id")
    source_id = record.get("source_id")
    score_id = record.get("score_id")
    if not rd._is_simple_id(catalog_id):
        problems.append("catalog_id is not a simple id")
    if not _SOURCE_ID_RE.fullmatch(source_id or ""):
        problems.append("source_id is invalid")
    if not _SCORE_ID_RE.fullmatch(score_id or ""):
        problems.append("score_id is invalid")
    previous = record.get("previous_score_id")
    if previous is not None and not _SCORE_ID_RE.fullmatch(previous):
        problems.append("previous_score_id is invalid")
    if not _GIT_SHA_RE.fullmatch(record.get("parser_git_sha") or ""):
        problems.append("parser_git_sha is invalid")
    if not isinstance(record.get("active"), bool):
        # Integers must never be accepted as an active flag.
        problems.append("active must be a boolean")
    if record.get("initial_status") not in STATUS_VALUES or record.get("status") not in STATUS_VALUES:
        problems.append("record status is outside the TRUST-01 vocabulary")

    provenance = record.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "title", "composer", "book", "edition", "source_url", "pdf_sha256",
    }:
        problems.append("provenance has missing or unsupported fields")
    else:
        source_url = provenance.get("source_url")
        pdf_sha256 = provenance.get("pdf_sha256")
        if source_id_for(source_url, pdf_sha256) != source_id:
            problems.append("source_id does not match provenance")
        for key in ("title", "composer", "book", "edition", "source_url", "pdf_sha256"):
            if provenance.get(key) is not None and not isinstance(provenance.get(key), str):
                problems.append(f"provenance.{key} must be a string or null")
        if pdf_sha256 is not None and not _SHA256_RE.fullmatch(pdf_sha256):
            problems.append("provenance.pdf_sha256 is invalid")

    artifacts = record.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"musicxml_sha256", "report_sha256"}:
        problems.append("artifacts has missing or unsupported fields")
    else:
        xml_hash = artifacts.get("musicxml_sha256")
        report_hash = artifacts.get("report_sha256")
        if not isinstance(xml_hash, str) or not _SHA256_RE.fullmatch(xml_hash):
            problems.append("artifacts.musicxml_sha256 is invalid")
        if not isinstance(report_hash, str) or not _SHA256_RE.fullmatch(report_hash):
            problems.append("artifacts.report_sha256 is invalid")
        if score_id_for(catalog_id, source_id, xml_hash) != score_id:
            problems.append("score_id does not match catalog/source/MusicXML identity")

    confidence = record.get("confidence")
    if not isinstance(confidence, dict) or set(confidence) != {
        "reference", "integrity_pct", "warning_count", "warning_summary",
    }:
        problems.append("confidence has missing or unsupported fields")
    else:
        if confidence.get("reference") != "legacy-measure-integrity-v1":
            problems.append("confidence reference is unsupported")
        integrity = confidence.get("integrity_pct")
        if integrity is not None and (
            not isinstance(integrity, (int, float)) or isinstance(integrity, bool) or not 0 <= integrity <= 100
        ):
            problems.append("confidence.integrity_pct must be a 0..100 number or null")
        if not isinstance(confidence.get("warning_count"), int) or confidence["warning_count"] < 0:
            problems.append("confidence.warning_count must be a nonnegative integer")
        if confidence.get("warning_summary") != {"count": confidence.get("warning_count")}:
            problems.append("confidence.warning_summary must exactly summarize the warning count")

    overrides = record.get("override_history")
    if not isinstance(overrides, dict) or set(overrides) != {
        "active_override_sha256", "last_override_sha256", "tombstoned",
    }:
        problems.append("override_history has missing or unsupported fields")
    else:
        active_override = overrides.get("active_override_sha256")
        last_override = overrides.get("last_override_sha256")
        if active_override is not None and not _SHA256_RE.fullmatch(active_override):
            problems.append("override_history.active_override_sha256 is invalid")
        if last_override is not None and not _SHA256_RE.fullmatch(last_override):
            problems.append("override_history.last_override_sha256 is invalid")
        if not isinstance(overrides.get("tombstoned"), bool):
            problems.append("override_history.tombstoned must be a boolean")
        if active_override is not None and overrides.get("tombstoned"):
            problems.append("active override conflicts with a retired-override tombstone")
        if active_override is not None and record.get("status") != "manual-override":
            problems.append("active override requires manual-override status")
        if active_override is not None and record.get("active") is not True:
            problems.append("active override cannot remain on a historical record")
        if active_override is not None and last_override != active_override:
            problems.append("active override must match the last applied override hash")
        if record.get("status") == "manual-override" and active_override is None:
            problems.append("manual-override status requires an active override hash")

    history = record.get("history")
    if not isinstance(history, list):
        problems.append("history must be a list")
    else:
        current = record.get("initial_status")
        previous_time = None
        seen_events = set()
        for index, event in enumerate(history):
            for problem in _event_problems(event):
                problems.append(f"history[{index}]: {problem}")
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            if event_id in seen_events:
                problems.append(f"history[{index}]: duplicate event id")
            seen_events.add(event_id)
            if any(event.get(key) != record.get(key) for key in ("catalog_id", "score_id", "source_id")):
                problems.append(f"history[{index}]: event identity does not match record")
            if event.get("from_status") != current:
                problems.append(f"history[{index}]: transition expected {event.get('from_status')!r}, current is {current!r}")
            current = event.get("to_status")
            event_time = _timestamp(event.get("recorded_at"))
            if previous_time and event_time and event_time < previous_time:
                problems.append(f"history[{index}]: time moves backward")
            if event_time:
                previous_time = event_time
        if current != record.get("status"):
            problems.append("record status does not match audited history")

    active = record.get("active")
    status = record.get("status")
    if active is True and status in ACTIVE_FORBIDDEN_STATUSES:
        problems.append("active record cannot be review-required or retired")
    if active is False and status not in INACTIVE_ALLOWED_STATUSES:
        problems.append("non-active record must be review-required or retired")

    if descriptor is not None and not problems:
        active_xml = descriptor.get("musicxml", {}).get("per_entry", {})
        active_reports = descriptor.get("reports", {}).get("per_entry", {})
        source_inventory = {
            item.get("id"): item
            for item in descriptor.get("input", {}).get("source_inventory", [])
            if isinstance(item, dict)
        }
        if active is True:
            if artifacts["musicxml_sha256"] != active_xml.get(catalog_id):
                problems.append("active MusicXML hash differs from descriptor")
            if artifacts["report_sha256"] != active_reports.get(catalog_id):
                problems.append("active report hash differs from descriptor")
            source = source_inventory.get(catalog_id, {})
            if provenance["source_url"] != source.get("source_url") or provenance["pdf_sha256"] != source.get("pdf_sha256"):
                problems.append("active provenance differs from descriptor source inventory")
            if record["parser_git_sha"] != descriptor.get("code", {}).get("parser_git_sha"):
                problems.append("active parser SHA differs from descriptor")
            expected_override = descriptor.get("overrides", {}).get("per_stem", {}).get(catalog_id)
            if overrides["active_override_sha256"] != expected_override:
                problems.append("active override hash differs from descriptor")
            expected_tombstone = catalog_id in set(descriptor.get("overrides", {}).get("tombstones", []))
            if overrides["tombstoned"] != expected_tombstone:
                problems.append("tombstone state differs from descriptor")
    return problems


def validate_ledger_body(body: object, *, descriptor: dict | None = None) -> list[str]:
    if not isinstance(body, dict):
        return ["ledger body is not an object"]
    if set(body) != {"schema_version", "records"}:
        return ["ledger body must contain exactly schema_version and records"]
    if body.get("schema_version") != LEDGER_SCHEMA_VERSION:
        return ["ledger body schema_version is unsupported"]
    records = body.get("records")
    if not isinstance(records, list):
        return ["ledger body records must be a list"]
    problems = []
    score_ids = set()
    active_catalog_ids = set()
    history_event_ids = set()
    for index, record in enumerate(records):
        for problem in _record_problems(record, descriptor=descriptor):
            problems.append(f"records[{index}]: {problem}")
        if not isinstance(record, dict):
            continue
        score_id = record.get("score_id")
        if score_id in score_ids:
            problems.append(f"records[{index}]: duplicate score_id {score_id!r}")
        score_ids.add(score_id)
        if record.get("active") is True:
            catalog_id = record.get("catalog_id")
            if catalog_id in active_catalog_ids:
                problems.append(f"records[{index}]: duplicate active catalog_id {catalog_id!r}")
            active_catalog_ids.add(catalog_id)
        for event in record.get("history", []) if isinstance(record.get("history"), list) else []:
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            if event_id in history_event_ids:
                problems.append(f"records[{index}]: event_id is duplicated across records: {event_id!r}")
            history_event_ids.add(event_id)
    if records != sorted(records, key=lambda record: (record.get("catalog_id", ""), record.get("score_id", ""))):
        problems.append("records are not in canonical catalog_id/score_id order")

    if descriptor is not None:
        manifest_ids = set(descriptor.get("musicxml", {}).get("per_entry", {}))
        if active_catalog_ids != manifest_ids:
            problems.append("active ledger records do not exactly reconcile to descriptor manifest ids")
    return problems


def validate_snapshot(snapshot: object, *, descriptor: dict | None = None) -> list[str]:
    """Validate a release-local snapshot and optionally bind it to a descriptor."""
    if not isinstance(snapshot, dict):
        return ["quality ledger snapshot is not a JSON object"]
    problems = []
    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(
            _load_schema(), format_checker=jsonschema.FormatChecker(),
        )
        for error in sorted(validator.iter_errors(snapshot), key=lambda e: list(e.absolute_path)):
            location = "/".join(str(p) for p in error.absolute_path) or "<root>"
            problems.append(f"schema violation at {location}: {error.message}")
    else:  # pragma: no cover
        problems.append("jsonschema package is not installed")

    records = snapshot.get("records")
    body = {"schema_version": snapshot.get("schema_version"), "records": records}
    problems.extend(validate_ledger_body(body, descriptor=descriptor))
    if isinstance(records, list):
        expected_summary = _summary_for(records)
        if snapshot.get("ledger_hash") != expected_summary["hash"]:
            problems.append("ledger_hash does not match canonical records")
        if snapshot.get("summary") != expected_summary:
            problems.append("summary does not match canonical records")

    if descriptor is not None:
        if snapshot.get("release_id") != descriptor.get("release_id"):
            problems.append("snapshot release_id differs from descriptor")
        if snapshot.get("release_content_fingerprint") != descriptor.get("content_fingerprint"):
            problems.append("snapshot release content fingerprint differs from descriptor")
        if snapshot.get("summary") != descriptor.get("quality_ledger"):
            problems.append("snapshot summary differs from descriptor quality_ledger section")
    problems.extend(rd._scan_for_leaks(snapshot))
    return problems


def load_snapshot(path: Path) -> dict:
    try:
        snapshot = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"quality ledger snapshot is unreadable: {exc}") from exc
    problems = validate_snapshot(snapshot)
    if problems:
        raise LedgerError("quality ledger snapshot is invalid:\n  - " + "\n  - ".join(problems))
    return snapshot


def append_transition(
    *,
    journal_path: Path,
    snapshot_path: Path,
    catalog_id: str,
    to_status: str,
    actor_role: str,
    actor_ref: str | None,
    evidence_kind: str,
    evidence_ref: str,
    recorded_at: str | None = None,
) -> dict:
    """Append one reviewed transition using an existing sealed snapshot.

    The caller selects a logical catalog id, while the snapshot supplies the
    exact immutable score/source identities and expected prior status. This
    prevents an old review decision from being silently attached to changed
    MusicXML on the next candidate.
    """
    snapshot = load_snapshot(snapshot_path)
    active_choices = [
        record for record in snapshot["records"]
        if record["catalog_id"] == catalog_id and record["active"] is True
    ]
    choices = active_choices or [
        record for record in snapshot["records"]
        if record["catalog_id"] == catalog_id and record["status"] == "review-required"
    ]
    if len(choices) != 1:
        raise LedgerError(f"snapshot has no unique transitionable score for {catalog_id!r}")
    record = choices[0]
    timestamp = recorded_at or datetime.now(timezone.utc).isoformat()
    unsigned = {
        "catalog_id": catalog_id,
        "score_id": record["score_id"],
        "source_id": record["source_id"],
        "from_status": record["status"],
        "to_status": to_status,
        "recorded_at": timestamp,
        "actor": {"role": actor_role, "ref": actor_ref},
        "evidence": [{"kind": evidence_kind, "ref": evidence_ref}],
    }
    event = {"event_id": "evt-" + _canonical_hash(unsigned)[:32], **unsigned}
    sealed_event_ids = {
        event["event_id"]
        for snapshot_record in snapshot["records"]
        for event in snapshot_record["history"]
    }
    with _journal_lock(journal_path):
        journal = load_journal(journal_path)
        current_status = record["status"]
        for prior in journal["events"]:
            if prior["score_id"] != record["score_id"] or prior["event_id"] in sealed_event_ids:
                continue
            if prior["from_status"] != current_status:
                raise LedgerError(
                    f"journal has a concurrent or stale transition for {catalog_id!r}; "
                    "reload the latest snapshot before appending"
                )
            current_status = prior["to_status"]
        if event["from_status"] != current_status:
            raise LedgerError(
                f"journal status changed for {catalog_id!r}; reload the latest snapshot before appending"
            )
        journal["events"].append(event)
        problems = journal_problems(journal)
        if problems:
            raise LedgerError("transition is invalid:\n  - " + "\n  - ".join(problems))
        write_journal(journal_path, journal)
    return event


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create an empty private journal")
    p.add_argument("--journal", required=True, type=Path)

    p = sub.add_parser("validate-journal", help="validate private journal syntax and transition rules")
    p.add_argument("--journal", required=True, type=Path)

    p = sub.add_parser("transition", help="append one reviewed transition from a sealed snapshot")
    p.add_argument("--journal", required=True, type=Path)
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--catalog-id", required=True)
    p.add_argument("--to-status", required=True, choices=STATUS_VALUES)
    p.add_argument("--actor-role", required=True, choices=sorted(ACTOR_ROLES))
    p.add_argument("--actor-ref", default=None)
    p.add_argument("--evidence-kind", required=True)
    p.add_argument("--evidence-ref", required=True)
    p.add_argument("--recorded-at", default=None)

    args = ap.parse_args(argv)
    try:
        if args.command == "init":
            if args.journal.exists():
                raise LedgerError(f"journal already exists: {args.journal}")
            write_journal(args.journal, empty_journal())
        elif args.command == "validate-journal":
            load_journal(args.journal)
        else:
            event = append_transition(
                journal_path=args.journal,
                snapshot_path=args.snapshot,
                catalog_id=args.catalog_id,
                to_status=args.to_status,
                actor_role=args.actor_role,
                actor_ref=args.actor_ref,
                evidence_kind=args.evidence_kind,
                evidence_ref=args.evidence_ref,
                recorded_at=args.recorded_at,
            )
            print(json.dumps(event, indent=2, sort_keys=True))
    except LedgerError as exc:
        print(f"quality_ledger: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
