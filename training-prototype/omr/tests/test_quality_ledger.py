"""TRUST-01 private quality ledger tests using the rights-safe fixture only."""
from __future__ import annotations

import copy
import json
import fcntl
import multiprocessing
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
OMR_DIR = TESTS_DIR.parent
FIXTURE = TESTS_DIR / "fixtures" / "release_descriptor"
sys.path.insert(0, str(OMR_DIR))

import ingest_catalog as ingest  # noqa: E402
import quality_ledger as ql  # noqa: E402
import release_descriptor as rd  # noqa: E402

SHA = "a" * 40
NOW = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_descriptor_git(monkeypatch):
    monkeypatch.setattr(rd, "git_sha", lambda _cwd: SHA)
    monkeypatch.setattr(rd, "git_dirty", lambda _cwd: False)


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "omr"
    shutil.copytree(FIXTURE, root)
    return root


def _descriptor(root: Path, quality_ledger=None):
    return rd.build_release_descriptor(
        omr_dir=root,
        parser_git_sha=SHA,
        app_git_sha=SHA,
        verified_passed=10,
        verified_skipped=0,
        verified_failed=0,
        now=NOW,
        bundled_content={},
        quality_ledger=quality_ledger,
    )


def _body(root: Path, *, parent=None):
    return ql.build_ledger_body(candidate=root, descriptor=_descriptor(root), parent_snapshot=parent)


def _snapshot(root: Path, *, parent=None):
    body, summary = _body(root, parent=parent)
    descriptor = _descriptor(root, quality_ledger=summary)
    return ql.snapshot_for_descriptor(body, descriptor), descriptor


def _event(record: dict, *, to_status="human-verified", role="reviewer", ref="reviewer-1"):
    unsigned = {
        "catalog_id": record["catalog_id"],
        "score_id": record["score_id"],
        "source_id": record["source_id"],
        "from_status": record["status"],
        "to_status": to_status,
        "recorded_at": "2026-07-10T20:00:00+00:00",
        "actor": {"role": role, "ref": ref},
        "evidence": [{"kind": "fixture-review", "ref": "evidence-1"}],
    }
    return {"event_id": "evt-" + rd._sha256_json_canonical(unsigned)[:32], **unsigned}


def _write_journal(root: Path, events: list[dict]) -> None:
    path = root / ql.JOURNAL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "events": events}), encoding="utf-8")


def _append_transition_worker(journal_path, snapshot_path, started, done):
    started.set()
    ql.append_transition(
        journal_path=Path(journal_path),
        snapshot_path=Path(snapshot_path),
        catalog_id="fixture_piece_a",
        to_status="human-verified",
        actor_role="reviewer",
        actor_ref="reviewer-1",
        evidence_kind="source-review",
        evidence_ref="evidence-1",
        recorded_at="2026-07-10T20:00:00+00:00",
    )
    done.set()


def test_initial_migration_is_deterministic_and_does_not_promote_accepted_to_human_verified(tmp_path):
    root = _copy_fixture(tmp_path)
    body_one, summary_one = _body(root)
    body_two, summary_two = _body(root)

    assert body_one == body_two
    assert summary_one == summary_two
    assert summary_one["active_count"] == 1
    assert summary_one["status_counts"] == {
        "auto-imported": 1,
        "human-verified": 0,
        "known-issue": 0,
        "review-required": 0,
        "manual-override": 0,
        "retired": 0,
    }
    record = body_one["records"][0]
    assert record["catalog_id"] == "fixture_piece_a"
    assert record["status"] == "auto-imported"
    assert record["source_id"].startswith("source-")
    assert record["score_id"].startswith("score-")
    assert record["provenance"]["pdf_sha256"] is not None
    assert "pdfs/ingest" not in json.dumps(record)


def test_only_manifest_active_scores_are_migrated(tmp_path):
    body, summary = _body(_copy_fixture(tmp_path))
    assert [record["catalog_id"] for record in body["records"]] == ["fixture_piece_a"]
    assert summary["record_count"] == 1


def test_human_review_transition_is_bound_to_exact_score_identity(tmp_path):
    root = _copy_fixture(tmp_path)
    original, _ = _body(root)
    event = _event(original["records"][0])
    _write_journal(root, [event])

    body, summary = _body(root)
    record = body["records"][0]
    assert record["status"] == "human-verified"
    assert record["history"] == [event]
    assert summary["status_counts"]["human-verified"] == 1


@pytest.mark.parametrize(
    ("to_status", "role", "message"),
    [
        ("manual-override", "owner", "invalid status transition"),
        ("human-verified", "system", "requires reviewer or owner authority"),
        ("retired", "reviewer", "only an owner can retire"),
    ],
)
def test_invalid_transition_authority_or_status_is_rejected(tmp_path, to_status, role, message):
    root = _copy_fixture(tmp_path)
    body, _ = _body(root)
    _write_journal(root, [_event(body["records"][0], to_status=to_status, role=role, ref="actor-1")])
    with pytest.raises(ql.LedgerError, match=message):
        _body(root)


def test_active_score_cannot_be_marked_review_required(tmp_path):
    root = _copy_fixture(tmp_path)
    body, _ = _body(root)
    _write_journal(root, [_event(body["records"][0], to_status="review-required", role="reviewer")])
    with pytest.raises(ql.LedgerError, match="active score cannot be"):
        _body(root)


def test_changed_musicxml_rejects_stale_review_event(tmp_path):
    root = _copy_fixture(tmp_path)
    body, _ = _body(root)
    _write_journal(root, [_event(body["records"][0])])
    xml = root / "out" / "ingest" / "fixture_piece_a.musicxml"
    xml.write_text(xml.read_text(encoding="utf-8").replace("C</step>", "D</step>"), encoding="utf-8")

    with pytest.raises(ql.LedgerError, match="unknown or stale score_id"):
        _body(root)


def test_active_override_is_manual_but_tombstone_does_not_retire_score(tmp_path):
    root = _copy_fixture(tmp_path)
    override = root / "overrides" / "fixture_piece_a.musicxml"
    shutil.copy2(root / "overrides" / "fixture_override_example.musicxml", override)

    body, summary = _body(root)
    record = body["records"][0]
    assert record["status"] == "manual-override"
    assert record["override_history"]["tombstoned"] is False
    assert summary["status_counts"]["manual-override"] == 1

    retired = root / "overrides" / "RETIRED"
    retired.write_text(retired.read_text(encoding="utf-8") + "fixture_piece_a # parser fixed\n", encoding="utf-8")
    with pytest.raises(ql.LedgerError, match="conflicts with retired-override tombstone"):
        _body(root)


def test_shared_tombstone_parser_honors_inline_comments(tmp_path, monkeypatch):
    root = _copy_fixture(tmp_path)
    retired = root / "overrides" / "RETIRED"
    retired.write_text("fixture_piece_a # inline note\n", encoding="utf-8")
    assert rd.load_retired(root / "overrides") == ["fixture_piece_a"]
    monkeypatch.setattr(ingest, "OVERRIDE_DIR", str(root / "overrides"))
    assert ingest._load_retired_overrides() == {"fixture_piece_a"}


def test_new_score_references_parent_identity_and_resets_trust_status(tmp_path):
    root = _copy_fixture(tmp_path)
    parent_snapshot, _parent_descriptor = _snapshot(root)
    xml = root / "out" / "ingest" / "fixture_piece_a.musicxml"
    xml.write_text(xml.read_text(encoding="utf-8").replace("C</step>", "D</step>"), encoding="utf-8")

    body, _ = _body(root, parent=parent_snapshot)
    record = body["records"][0]
    assert record["previous_score_id"] == parent_snapshot["records"][0]["score_id"]
    assert record["score_id"] != record["previous_score_id"]
    assert record["status"] == "auto-imported"
    assert record["history"] == []


def test_removed_parent_score_is_retained_only_with_explicit_owner_retirement(tmp_path):
    root = _copy_fixture(tmp_path)
    parent_snapshot, _parent_descriptor = _snapshot(root)
    parent_record = parent_snapshot["records"][0]
    event = _event(parent_record, to_status="retired", role="owner", ref="owner-1")
    _write_journal(root, [event])
    (root / "out" / "ingest" / "manifest.json").write_text("[]", encoding="utf-8")

    body, summary = _body(root, parent=parent_snapshot)
    assert summary["active_count"] == 0
    assert summary["status_counts"]["retired"] == 1
    assert body["records"][0]["active"] is False
    assert body["records"][0]["status"] == "retired"
    assert body["records"][0]["history"][-1] == event


@pytest.mark.parametrize(
    ("to_status", "role"),
    [("retired", "owner"), ("review-required", "reviewer")],
)
def test_historical_manual_override_preserves_last_hash_after_withholding(tmp_path, to_status, role):
    root = _copy_fixture(tmp_path)
    shutil.copy2(
        root / "overrides" / "fixture_override_example.musicxml",
        root / "overrides" / "fixture_piece_a.musicxml",
    )
    parent_snapshot, _parent_descriptor = _snapshot(root)
    parent_record = parent_snapshot["records"][0]
    override_hash = parent_record["override_history"]["active_override_sha256"]
    assert parent_record["status"] == "manual-override"
    event = _event(parent_record, to_status=to_status, role=role, ref=f"{role}-1")
    _write_journal(root, [event])
    (root / "out" / "ingest" / "manifest.json").write_text("[]", encoding="utf-8")

    body, _summary = _body(root, parent=parent_snapshot)
    record = body["records"][0]
    assert record["active"] is False
    assert record["status"] == to_status
    assert record["override_history"]["active_override_sha256"] is None
    assert record["override_history"]["last_override_sha256"] == override_hash


def test_rewritten_sealed_event_is_rejected_even_when_score_is_no_longer_active(tmp_path):
    root = _copy_fixture(tmp_path)
    initial, _ = _body(root)
    event = _event(initial["records"][0])
    _write_journal(root, [event])
    parent_snapshot, _parent_descriptor = _snapshot(root)

    rewritten = copy.deepcopy(event)
    rewritten["evidence"][0]["ref"] = "different-evidence"
    _write_journal(root, [rewritten])
    (root / "out" / "ingest" / "manifest.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ql.LedgerError, match="was changed after it was sealed"):
        _body(root, parent=parent_snapshot)


def test_review_required_withholds_reimport_and_can_be_reapproved(tmp_path, monkeypatch):
    root = _copy_fixture(tmp_path)
    state_path = root / "out" / "ingest" / "ingest_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["fixture_piece_a"]["source_pdf_sha256"] = rd._sha256_file(
        root / "pdfs" / "ingest" / "fixture_piece_a.pdf"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    parent_snapshot, _parent_descriptor = _snapshot(root)
    event = _event(parent_snapshot["records"][0], to_status="review-required", role="reviewer")
    _write_journal(root, [event])

    monkeypatch.setattr(ingest, "CANDIDATE_METADATA", str(root / "build-metadata.json"))
    monkeypatch.setattr(ingest, "OUT_DIR", str(root / "out" / "ingest"))
    monkeypatch.setattr(ingest, "MANIFEST", str(root / "out" / "ingest" / "manifest.json"))
    monkeypatch.setattr(ingest, "voice_guard", lambda *_args: None)
    withheld = ingest._review_required_stems(state)
    assert withheld == {"fixture_piece_a"}
    assert ingest.write_manifest(state, catalog=[], withheld=withheld) == []

    withheld_snapshot, _descriptor = _snapshot(root, parent=parent_snapshot)
    snapshot_path = root / ql.SNAPSHOT_REL
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(withheld_snapshot), encoding="utf-8")
    ql.append_transition(
        journal_path=root / ql.JOURNAL_REL,
        snapshot_path=snapshot_path,
        catalog_id="fixture_piece_a",
        to_status="human-verified",
        actor_role="reviewer",
        actor_ref="reviewer-1",
        evidence_kind="source-review",
        evidence_ref="evidence-2",
        recorded_at="2026-07-10T21:00:00+00:00",
    )

    assert ingest._review_required_stems(state) == set()
    assert [entry["id"] for entry in ingest.write_manifest(state, catalog=[], withheld=set())] == ["fixture_piece_a"]
    reapproved, _summary = _body(root, parent=withheld_snapshot)
    assert reapproved["records"][0]["active"] is True
    assert reapproved["records"][0]["status"] == "human-verified"


def test_retired_event_withholds_next_candidate_manifest(tmp_path, monkeypatch):
    root = _copy_fixture(tmp_path)
    state_path = root / "out" / "ingest" / "ingest_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["fixture_piece_a"]["source_pdf_sha256"] = rd._sha256_file(
        root / "pdfs" / "ingest" / "fixture_piece_a.pdf"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    parent_snapshot, _parent_descriptor = _snapshot(root)
    event = _event(parent_snapshot["records"][0], to_status="retired", role="owner", ref="owner-1")
    _write_journal(root, [event])

    monkeypatch.setattr(ingest, "CANDIDATE_METADATA", str(root / "build-metadata.json"))
    monkeypatch.setattr(ingest, "OUT_DIR", str(root / "out" / "ingest"))
    monkeypatch.setattr(ingest, "MANIFEST", str(root / "out" / "ingest" / "manifest.json"))
    monkeypatch.setattr(ingest, "voice_guard", lambda *_args: None)
    withheld = ingest._review_required_stems(state)
    assert withheld == {"fixture_piece_a"}
    assert ingest.write_manifest(state, catalog=[], withheld=withheld) == []
    retired, _summary = _body(root, parent=parent_snapshot)
    assert retired["records"][0]["active"] is False
    assert retired["records"][0]["status"] == "retired"


def test_snapshot_and_descriptor_binding_detect_tampering(tmp_path):
    root = _copy_fixture(tmp_path)
    snapshot, descriptor = _snapshot(root)
    assert ql.validate_snapshot(snapshot, descriptor=descriptor) == []

    tampered = copy.deepcopy(snapshot)
    tampered["records"][0]["status"] = "human-verified"
    problems = ql.validate_snapshot(tampered, descriptor=descriptor)
    assert any("ledger_hash" in problem or "status does not match" in problem for problem in problems)


def test_append_transition_rejects_email_actor_reference(tmp_path):
    root = _copy_fixture(tmp_path)
    snapshot, _descriptor = _snapshot(root)
    snapshot_path = root / ql.SNAPSHOT_REL
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ql.LedgerError, match="opaque token"):
        ql.append_transition(
            journal_path=root / ql.JOURNAL_REL,
            snapshot_path=snapshot_path,
            catalog_id="fixture_piece_a",
            to_status="human-verified",
            actor_role="reviewer",
            actor_ref="name@example.invalid",
            evidence_kind="fixture-review",
            evidence_ref="evidence-1",
            recorded_at="2026-07-10T20:00:00+00:00",
        )


def test_private_journal_is_owner_only_and_append_waits_for_writer_lock(tmp_path):
    root = _copy_fixture(tmp_path)
    snapshot, _descriptor = _snapshot(root)
    snapshot_path = root / ql.SNAPSHOT_REL
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    journal_path = root / ql.JOURNAL_REL
    ql.write_journal(journal_path, ql.empty_journal())

    assert (journal_path.stat().st_mode & 0o777) == 0o600
    assert (journal_path.parent.stat().st_mode & 0o777) == 0o700

    lock_path = journal_path.parent / ".ledger.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    started = multiprocessing.Event()
    done = multiprocessing.Event()
    process = multiprocessing.Process(
        target=_append_transition_worker,
        args=(str(journal_path), str(snapshot_path), started, done),
    )
    process.start()
    try:
        assert started.wait(2)
        assert not done.wait(0.2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    assert done.wait(2)
    process.join(2)
    assert process.exitcode == 0
    assert len(ql.load_journal(journal_path)["events"]) == 1
