"""CAT-03 generated-stats tests. All content is synthetic and rights-safe."""
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

import catalog_release as cr  # noqa: E402
import release_descriptor as rd  # noqa: E402
import release_stats as rs  # noqa: E402

SHA = "a" * 40
FIXED_NOW = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_git(monkeypatch):
    monkeypatch.setattr(cr, "_git_state", lambda _cwd: (SHA, False))
    monkeypatch.setattr(rd, "git_sha", lambda _cwd: SHA)
    monkeypatch.setattr(rd, "git_dirty", lambda _cwd: False)


def _sealed_release(store: Path) -> Path:
    candidate = store / "staging" / ".staging-a"
    shutil.copytree(FIXTURE / "out", candidate / "out")
    shutil.copytree(FIXTURE / "overrides", candidate / "overrides")
    (candidate / "content").mkdir(parents=True)
    builtin_source = FIXTURE / "overrides" / "fixture_override_example.musicxml"
    for builtin in cr.APPROVED_BUILTINS:
        shutil.copy2(builtin_source, candidate / "content" / builtin)
    (candidate / "build-metadata.json").write_text(json.dumps({
        "format_version": 1,
        "parser_git_sha": SHA,
        "app_git_sha": SHA,
        "source_catalog_hash": rd._sha256_file(FIXTURE / "pdfs" / "survey" / "catalog.json"),
        "created_at": FIXED_NOW.isoformat(),
    }), encoding="utf-8")
    cr._stamp_missing_candidate_source_hashes(candidate, FIXTURE)
    return cr.seal_candidate(
        store=store, candidate=candidate, source_omr_dir=FIXTURE,
        verified_passed=88, verified_skipped=19, verified_failed=0, now=FIXED_NOW,
    )


def test_summarize_exposes_only_nonprivate_counts_and_trust(tmp_path):
    store = tmp_path / "store"
    sealed = _sealed_release(store)
    descriptor = cr.validate_release(sealed)

    summary = rs.summarize(descriptor)

    assert summary["release_id"] == descriptor["release_id"]
    assert summary["counts"]["manifest_entries"] == descriptor["manifest"]["entry_count"]
    assert summary["counts"]["musicxml"] == descriptor["musicxml"]["count"]
    assert summary["counts"]["bundled_content"] == 4
    assert summary["trust"]["status_counts"] == descriptor["trust"]["status_counts"]
    assert summary["quality_ledger"] == descriptor["quality_ledger"]
    assert summary["readiness"]["promotable"] is True
    # Never leak the private per-entry path/hash map or local filesystem paths.
    dumped = json.dumps(summary)
    assert "per_entry" not in dumped
    assert "history" not in dumped
    assert str(tmp_path) not in dumped


def test_format_markdown_is_a_single_line_with_release_id_and_counts(tmp_path):
    store = tmp_path / "store"
    sealed = _sealed_release(store)
    summary = rs.summarize(cr.validate_release(sealed))

    line = rs.format_markdown(summary)

    assert "\n" not in line
    assert summary["release_id"] in line
    assert str(summary["counts"]["manifest_entries"]) in line


def test_cli_defaults_to_current_pointer(tmp_path, capsys):
    store = tmp_path / "store"
    sealed = _sealed_release(store)
    cr.promote(store=store, release_id=sealed.name, approval=sealed.name)

    assert rs.main(["--store", str(store)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["release_id"] == sealed.name


def test_cli_errors_cleanly_with_no_current_pointer(tmp_path, capsys):
    store = tmp_path / "store"
    store.mkdir()
    assert rs.main(["--store", str(store)]) == 1
    assert "no current pointer" in capsys.readouterr().err


def test_cli_refuses_a_corrupted_descriptor(tmp_path, capsys):
    store = tmp_path / "store"
    sealed = _sealed_release(store)
    cr.promote(store=store, release_id=sealed.name, approval=sealed.name)
    descriptor_path = sealed / "release-descriptor.json"
    descriptor_path.chmod(descriptor_path.stat().st_mode | stat.S_IWUSR)
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["manifest"]["entry_count"] += 1
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    assert rs.main(["--store", str(store)]) == 1
    assert "cannot validate" in capsys.readouterr().err
