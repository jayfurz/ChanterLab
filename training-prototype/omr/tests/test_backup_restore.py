"""CAT-03 backup-set / restore-verification tests. All content is synthetic
and rights-safe (same fixtures as CAT-02's tests)."""
from __future__ import annotations

import json
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
OMR_DIR = TESTS_DIR.parent
FIXTURE = TESTS_DIR / "fixtures" / "release_descriptor"
sys.path.insert(0, str(OMR_DIR))

import backup_restore as br  # noqa: E402
import catalog_release as cr  # noqa: E402
import release_descriptor as rd  # noqa: E402

SHA = "a" * 40
FIXED_NOW = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_git(monkeypatch):
    monkeypatch.setattr(cr, "_git_state", lambda _cwd: (SHA, False))
    monkeypatch.setattr(rd, "git_sha", lambda _cwd: SHA)
    monkeypatch.setattr(rd, "git_dirty", lambda _cwd: False)


def _candidate(store: Path, *, name: str, change_xml=False) -> Path:
    candidate = store / "staging" / name
    shutil.copytree(FIXTURE / "out", candidate / "out")
    shutil.copytree(FIXTURE / "overrides", candidate / "overrides")
    (candidate / "content").mkdir(parents=True)
    builtin_source = FIXTURE / "overrides" / "fixture_override_example.musicxml"
    for builtin in cr.APPROVED_BUILTINS:
        shutil.copy2(builtin_source, candidate / "content" / builtin)
    if change_xml:
        xml = candidate / "out" / "ingest" / "fixture_piece_a.musicxml"
        xml.write_text(xml.read_text().replace("C</step>", "D</step>"), encoding="utf-8")
    (candidate / "build-metadata.json").write_text(json.dumps({
        "format_version": 1,
        "parser_git_sha": SHA,
        "app_git_sha": SHA,
        "source_catalog_hash": rd._sha256_file(FIXTURE / "pdfs" / "survey" / "catalog.json"),
        "created_at": FIXED_NOW.isoformat(),
    }), encoding="utf-8")
    cr._stamp_missing_candidate_source_hashes(candidate, FIXTURE)
    return candidate


def _seal(store: Path, candidate: Path, now=FIXED_NOW) -> Path:
    return cr.seal_candidate(
        store=store, candidate=candidate, source_omr_dir=FIXTURE,
        verified_passed=88, verified_skipped=19, verified_failed=0, now=now,
    )


def _make_writable(path: Path) -> None:
    """seal_candidate() locks releases read-only; a real corruption or a
    forced cleanup both require deliberately defeating that first, same as
    a test simulating either must."""
    for p in sorted(path.rglob("*"), reverse=True):
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _write_private_ledger(root: Path) -> Path:
    path = root / "quality-ledger" / "ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "events": [],
    }), encoding="utf-8")
    return path


def _build_omr_root_with_two_releases(tmp_path: Path) -> Path:
    """A realistic <omr>/out/release-store/{releases,current,previous} tree,
    plus the non-release backup sets, so it looks like a real source_omr_dir."""
    omr_root = tmp_path / "omr"
    shutil.copytree(FIXTURE / "pdfs", omr_root / "pdfs")
    shutil.copytree(FIXTURE / "overrides", omr_root / "overrides")
    shutil.copytree(FIXTURE / "out" / "ingest", omr_root / "out" / "ingest")
    _write_private_ledger(omr_root)
    store = omr_root / "out" / "release-store"
    first = _seal(store, _candidate(store, name=".staging-a"))
    cr.promote(store=store, release_id=first.name, approval=first.name)
    second = _seal(store, _candidate(store, name=".staging-b", change_xml=True),
                    now=FIXED_NOW.replace(minute=5))
    cr.promote(store=store, release_id=second.name, approval=second.name)
    br.write_release_snapshot(
        store / br.RELEASE_SNAPSHOT_REL.name,
        current_release_id=second.name,
        previous_release_id=first.name,
    )
    return omr_root


def _build_omr_root_with_one_release(tmp_path: Path) -> Path:
    omr_root = tmp_path / "omr"
    shutil.copytree(FIXTURE / "pdfs", omr_root / "pdfs")
    shutil.copytree(FIXTURE / "overrides", omr_root / "overrides")
    shutil.copytree(FIXTURE / "out" / "ingest", omr_root / "out" / "ingest")
    _write_private_ledger(omr_root)
    store = omr_root / "out" / "release-store"
    first = _seal(store, _candidate(store, name=".staging-a"))
    cr.promote(store=store, release_id=first.name, approval=first.name)
    br.write_release_snapshot(
        store / br.RELEASE_SNAPSHOT_REL.name,
        current_release_id=first.name,
        previous_release_id=None,
    )
    return omr_root


# --- hash manifest -----------------------------------------------------

def test_build_hash_manifest_covers_sources_state_overrides():
    manifest = br.build_hash_manifest(FIXTURE)
    assert "pdfs/survey/catalog.json" in manifest
    assert "pdfs/ingest/fixture_piece_a.pdf" in manifest
    assert "out/ingest/manifest.json" in manifest
    assert "out/ingest/ingest_state.json" in manifest
    assert "overrides/RETIRED" in manifest
    assert "overrides/fixture_override_example.musicxml" in manifest
    assert manifest["pdfs/survey/catalog.json"] == cr._sha256_file(FIXTURE / "pdfs" / "survey" / "catalog.json")


def test_hash_manifest_covers_private_quality_ledger_and_rejects_mutation(tmp_path):
    root = tmp_path / "omr"
    shutil.copytree(FIXTURE, root)
    ledger = _write_private_ledger(root)
    manifest = br.build_hash_manifest(root)

    assert manifest["quality-ledger/ledger.json"] == cr._sha256_file(ledger)
    restored = tmp_path / "restored"
    shutil.copytree(root, restored)
    (restored / "quality-ledger" / "ledger.json").write_text("{}", encoding="utf-8")
    assert "hash mismatch: quality-ledger/ledger.json" in br.verify_hash_manifest(restored, manifest)


def test_verify_hash_manifest_clean_restore_has_no_problems(tmp_path):
    manifest = br.build_hash_manifest(FIXTURE)
    restored = tmp_path / "restored"
    shutil.copytree(FIXTURE, restored)
    assert br.verify_hash_manifest(restored, manifest) == []


def test_verify_hash_manifest_detects_missing_file(tmp_path):
    manifest = br.build_hash_manifest(FIXTURE)
    restored = tmp_path / "restored"
    shutil.copytree(FIXTURE, restored)
    (restored / "overrides" / "RETIRED").unlink()
    problems = br.verify_hash_manifest(restored, manifest)
    assert any("missing: overrides/RETIRED" in p for p in problems)


def test_verify_hash_manifest_detects_corruption(tmp_path):
    manifest = br.build_hash_manifest(FIXTURE)
    restored = tmp_path / "restored"
    shutil.copytree(FIXTURE, restored)
    target = restored / "out" / "ingest" / "manifest.json"
    target.write_text(target.read_text() + "  ", encoding="utf-8")
    problems = br.verify_hash_manifest(restored, manifest)
    assert any("hash mismatch: out/ingest/manifest.json" in p for p in problems)


def test_verify_hash_manifest_detects_unexpected_stale_override(tmp_path):
    manifest = br.build_hash_manifest(FIXTURE)
    restored = tmp_path / "restored"
    shutil.copytree(FIXTURE, restored)
    (restored / "overrides" / "retired-piece.musicxml").write_text("stale", encoding="utf-8")

    problems = br.verify_hash_manifest(restored, manifest)

    assert "unexpected: overrides/retired-piece.musicxml" in problems


def test_hash_manifest_evidence_is_versioned_and_loadable(tmp_path):
    evidence_path = tmp_path / "backup-hash-manifest.json"
    evidence = br.write_hash_manifest(FIXTURE, evidence_path)

    assert evidence["schema_version"] == br.HASH_MANIFEST_SCHEMA_VERSION
    assert evidence["generated_at"]
    assert br.load_hash_manifest(evidence_path) == evidence["files"]


# --- store restore verification ----------------------------------------

def test_verify_store_ok_for_healthy_restore(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)

    hash_manifest = br.build_hash_manifest(omr_root)
    result = br.verify_store(restored, hash_manifest=hash_manifest)

    assert result["ok"] is True
    assert result["release_count"] == 2
    assert result["invalid_release_count"] == 0
    assert result["pointers"]["current"]["valid"] is True
    assert result["pointers"]["previous"]["valid"] is True
    assert result["hash_manifest_problems"] == []
    assert result["elapsed_seconds"] >= 0


def test_verify_store_catches_corrupted_release_after_restore(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)

    current_id = cr._pointer_release_id((restored / "out" / "release-store"), "current")
    release_dir = restored / "out" / "release-store" / "releases" / current_id
    _make_writable(release_dir)
    xml = release_dir / "out" / "ingest" / "fixture_piece_a.musicxml"
    xml.write_text(xml.read_text().replace("D</step>", "E</step>"), encoding="utf-8")

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))
    assert result["ok"] is False
    assert result["releases"][current_id]["ok"] is False
    assert result["pointers"]["current"]["valid"] is False


def test_verify_store_catches_dangling_pointer(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)

    store = restored / "out" / "release-store"
    previous_id = cr._pointer_release_id(store, "previous")
    _make_writable(store / "releases" / previous_id)
    shutil.rmtree(store / "releases" / previous_id)

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))
    assert result["ok"] is False
    assert result["pointers"]["previous"]["resolves"] is False
    assert result["pointers"]["previous"]["valid"] is False


def test_verify_store_requires_previous_with_multiple_releases(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)
    (restored / "out" / "release-store" / "previous").unlink()

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))

    assert result["ok"] is False
    assert "previous pointer is missing despite multiple sealed releases" in result["pointer_problems"]


def test_verify_store_rejects_pointer_outside_release_store(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)
    store = restored / "out" / "release-store"
    current_id = cr._pointer_release_id(store, "current")
    outside = tmp_path / "outside" / current_id
    shutil.copytree(store / "releases" / current_id, outside, symlinks=True)
    (store / "current").unlink()
    (store / "current").symlink_to(outside)

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))

    assert result["ok"] is False
    assert result["pointers"]["current"]["resolves"] is True
    assert result["pointers"]["current"]["inside_releases"] is False


def test_verify_store_rejects_identical_current_and_previous(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)
    store = restored / "out" / "release-store"
    current_target = (store / "current").readlink()
    (store / "previous").unlink()
    (store / "previous").symlink_to(current_target)

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))

    assert result["ok"] is False
    assert "current and previous point at the same release" in result["pointer_problems"]


def test_verify_store_requires_pointers_to_match_snapshot(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)
    store = restored / "out" / "release-store"
    previous_target = (store / "previous").readlink()
    (store / "current").unlink()
    (store / "current").symlink_to(previous_target)

    result = br.verify_store(restored, hash_manifest=br.build_hash_manifest(omr_root))

    assert result["ok"] is False
    assert "current pointer differs from the archived release snapshot" in result["release_snapshot_problems"]


def test_verify_store_requires_hash_manifest(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)

    result = br.verify_store(omr_root)

    assert result["ok"] is False
    assert result["hash_manifest_problems"] == ["missing required backup hash manifest"]


def test_materialize_restore_uses_bound_evidence_and_omits_archive_history(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    evidence_path = omr_root / br.BACKUP_HASH_MANIFEST_REL
    evidence = br.write_hash_manifest(omr_root, evidence_path)
    archive = tmp_path / "archive"
    shutil.copytree(omr_root, archive, symlinks=True)
    (archive / "overrides" / "retired-piece.musicxml").write_text("stale", encoding="utf-8")
    destination = tmp_path / "materialized"

    result = br.materialize_restore(
        archive_root=archive,
        destination=destination,
        hash_manifest=evidence["files"],
    )

    assert result["ok"] is True
    assert not (destination / "overrides" / "retired-piece.musicxml").exists()
    assert (destination / "quality-ledger" / "ledger.json").read_text(encoding="utf-8") == (
        omr_root / "quality-ledger" / "ledger.json"
    ).read_text(encoding="utf-8")
    assert (destination / br.BACKUP_HASH_MANIFEST_REL).is_file()


def test_materialize_restore_ignores_stale_previous_outside_snapshot(tmp_path):
    omr_root = _build_omr_root_with_one_release(tmp_path)
    evidence_path = omr_root / br.BACKUP_HASH_MANIFEST_REL
    evidence = br.write_hash_manifest(omr_root, evidence_path)
    archive = tmp_path / "archive"
    shutil.copytree(omr_root, archive, symlinks=True)
    store = archive / "out" / "release-store"
    current_target = (store / "current").readlink()
    (store / "previous").symlink_to(current_target)

    destination = tmp_path / "materialized"
    result = br.materialize_restore(
        archive_root=archive,
        destination=destination,
        hash_manifest=evidence["files"],
    )

    assert result["ok"] is True
    assert not (destination / "out" / "release-store" / "previous").exists()


def test_find_releases_excludes_staging(tmp_path):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    store = omr_root / "out" / "release-store"
    # A leftover interrupted candidate must never be mistaken for a release.
    (store / "staging" / ".staging-leftover").mkdir(parents=True)
    found = br.find_releases(omr_root)
    assert len(found) == 2
    assert all(p.parent.name == "releases" for p in found)


# --- CLI -----------------------------------------------------------------

def test_cli_sets_prints_backup_set_definition(capsys):
    assert br.main(["sets"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["sets"]) == {
        "sources", "state", "overrides", "quality_ledger", "releases", "pointers", "verification",
    }
    assert "out/release-store/staging" in payload["excluded"]
    assert str(br.RELEASE_SNAPSHOT_REL) in payload["sets"]["verification"]["paths"]


def test_cli_verify_store_exit_code_reflects_health(tmp_path, capsys):
    omr_root = _build_omr_root_with_two_releases(tmp_path)
    restored = tmp_path / "restored-omr"
    shutil.copytree(omr_root, restored, symlinks=True)
    evidence_path = tmp_path / "backup-hash-manifest.json"
    br.write_hash_manifest(omr_root, evidence_path)
    assert br.main([
        "verify-store", "--root", str(restored), "--hash-manifest", str(evidence_path),
    ]) == 0

    store = restored / "out" / "release-store"
    previous_id = cr._pointer_release_id(store, "previous")
    _make_writable(store / "releases" / previous_id)
    shutil.rmtree(store / "releases" / previous_id)
    assert br.main([
        "verify-store", "--root", str(restored), "--hash-manifest", str(evidence_path),
    ]) == 1
