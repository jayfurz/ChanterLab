"""CAT-02 release-store tests. All content is synthetic and rights-safe."""
from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
OMR_DIR = TESTS_DIR.parent
FIXTURE = TESTS_DIR / "fixtures" / "release_descriptor"
sys.path.insert(0, str(OMR_DIR))

import catalog_release as cr  # noqa: E402
import ingest_catalog as ingest  # noqa: E402
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
    return candidate


def _seal(store: Path, candidate: Path, now=FIXED_NOW) -> Path:
    return cr.seal_candidate(
        store=store,
        candidate=candidate,
        source_omr_dir=FIXTURE,
        verified_passed=88,
        verified_skipped=19,
        verified_failed=0,
        now=now,
    )


def test_seal_creates_immutable_valid_release_with_public_marker(tmp_path):
    store = tmp_path / "store"
    sealed = _seal(store, _candidate(store, name=".staging-a"))
    descriptor = cr.validate_release(sealed)

    assert sealed.parent == store / "releases"
    assert descriptor["readiness"] == {"promotable": True, "reasons": []}
    assert descriptor["bundled_content"]["count"] == 4
    marker = json.loads((sealed / "out" / "ingest" / "release.json").read_text())
    assert marker["release_id"] == descriptor["release_id"]
    assert not (sealed.stat().st_mode & stat.S_IWUSR)


def test_incomplete_or_interrupted_staging_is_never_active(tmp_path):
    store = tmp_path / "store"
    candidate = _candidate(store, name=".staging-interrupted")
    # Simulate extraction dying halfway through: no seal and no pointer write.
    (candidate / "out" / "ingest" / "manifest.json").unlink()
    assert cr._pointer_release_id(store, "current") is None
    assert not (store / "current").exists()


def test_legacy_import_copies_only_published_artifacts_with_explicit_provenance(tmp_path):
    store = tmp_path / "store"
    content = tmp_path / "content"
    content.mkdir()
    source = FIXTURE / "overrides" / "fixture_override_example.musicxml"
    for name in cr.APPROVED_BUILTINS:
        shutil.copy2(source, content / name)

    candidate = cr.import_existing(
        store=store, source_omr_dir=FIXTURE, content_dir=content,
        parser_git_sha="b" * 40, app_git_sha=SHA, now=FIXED_NOW,
    )
    assert json.loads((candidate / "build-metadata.json").read_text())["parser_git_sha"] == "b" * 40
    assert (candidate / "out" / "ingest" / "fixture_piece_a.musicxml").is_file()
    assert not (candidate / "out" / "ingest" / "fixture_piece_b.musicxml").exists()
    sealed = _seal(store, candidate)
    descriptor = json.loads((sealed / "release-descriptor.json").read_text())
    assert descriptor["code"]["parser_git_sha"] == "b" * 40


def test_promotion_requires_exact_explicit_approval(tmp_path):
    store = tmp_path / "store"
    sealed = _seal(store, _candidate(store, name=".staging-a"))
    release_id = sealed.name
    with pytest.raises(cr.ReleaseError, match="approval boundary"):
        cr.promote(store=store, release_id=release_id, approval="yes")
    assert cr._pointer_release_id(store, "current") is None


def test_verification_evidence_is_candidate_bound_and_complete(tmp_path, monkeypatch):
    store = tmp_path / "store"
    candidate = _candidate(store, name=".staging-a")
    monkeypatch.setattr(
        cr.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="99 passed, 19 skipped in 1.00s\n", stderr="", returncode=0,
        ),
    )
    result = cr.verify_candidate(candidate, Path("/venv/bin/python"))
    assert result["candidate_parser_git_sha"] == SHA
    assert result["verifier_git_sha"] == SHA
    assert (result["passed"], result["skipped"], result["failed"]) == (99, 19, 0)


def test_failure_before_atomic_current_replace_preserves_active_hashes(tmp_path):
    store = tmp_path / "store"
    first = _seal(store, _candidate(store, name=".staging-a"))
    cr.promote(store=store, release_id=first.name, approval=first.name)
    before_target = (store / "current").resolve()
    before_hash = cr._sha256_file(before_target / "out" / "ingest" / "manifest.json")

    second = _seal(
        store, _candidate(store, name=".staging-b", change_xml=True),
        now=FIXED_NOW + timedelta(seconds=1),
    )
    with pytest.raises(cr.ReleaseError, match="injected failure"):
        cr.promote(
            store=store, release_id=second.name, approval=second.name,
            inject_failure="before_current_replace",
        )

    assert (store / "current").resolve() == before_target
    assert cr._sha256_file(before_target / "out" / "ingest" / "manifest.json") == before_hash


def test_promote_then_rollback_restores_exact_prior_release(tmp_path):
    store = tmp_path / "store"
    first = _seal(store, _candidate(store, name=".staging-a"))
    cr.promote(store=store, release_id=first.name, approval=first.name)
    first_xml_hash = cr._sha256_file(first / "out" / "ingest" / "fixture_piece_a.musicxml")

    second = _seal(
        store, _candidate(store, name=".staging-b", change_xml=True),
        now=FIXED_NOW + timedelta(seconds=1),
    )
    cr.promote(store=store, release_id=second.name, approval=second.name)
    assert cr._pointer_release_id(store, "current") == second.name
    assert cr._pointer_release_id(store, "previous") == first.name

    cr.rollback(store=store, approval=first.name)
    assert cr._pointer_release_id(store, "current") == first.name
    assert cr._pointer_release_id(store, "previous") == second.name
    assert cr._sha256_file((store / "current" / "out" / "ingest" / "fixture_piece_a.musicxml")) == first_xml_hash


def test_semantic_diff_reports_changed_piece_and_counts(tmp_path):
    store = tmp_path / "store"
    first = _seal(store, _candidate(store, name=".staging-a"))
    second = _seal(
        store, _candidate(store, name=".staging-b", change_xml=True),
        now=FIXED_NOW + timedelta(seconds=1),
    )
    diff = cr.release_diff(
        json.loads((first / "release-descriptor.json").read_text()),
        json.loads((second / "release-descriptor.json").read_text()),
    )
    assert diff["pieces"]["changed"] == ["fixture_piece_a"]
    assert diff["manifest_entries"]["delta"] == 0


def test_tampered_sealed_file_is_refused_before_promotion(tmp_path):
    store = tmp_path / "store"
    sealed = _seal(store, _candidate(store, name=".staging-a"))
    xml = sealed / "out" / "ingest" / "fixture_piece_a.musicxml"
    xml.chmod(0o644)
    xml.write_text(xml.read_text().replace("C</step>", "D</step>"), encoding="utf-8")
    with pytest.raises(cr.ReleaseError, match="musicxml hash mismatch"):
        cr.promote(store=store, release_id=sealed.name, approval=sealed.name)


def test_candidate_configuration_redirects_every_generated_path(tmp_path, monkeypatch):
    candidate = tmp_path / ".staging-test"
    (candidate / "out" / "ingest").mkdir(parents=True)
    (candidate / "overrides").mkdir()
    (candidate / "build-metadata.json").write_text(
        json.dumps({"parser_git_sha": SHA}), encoding="utf-8",
    )
    monkeypatch.setattr(
        ingest.subprocess, "run",
        lambda cmd, **_kwargs: SimpleNamespace(stdout=SHA + "\n" if "rev-parse" in cmd else ""),
    )
    ingest.configure_candidate(candidate)
    assert Path(ingest.OUT_DIR) == candidate.resolve() / "out" / "ingest"
    assert Path(ingest.STATE) == candidate.resolve() / "out" / "ingest" / "ingest_state.json"
    assert Path(ingest.MANIFEST) == candidate.resolve() / "out" / "ingest" / "manifest.json"
    assert Path(ingest.OVERRIDE_DIR) == candidate.resolve() / "overrides"


def test_server_allowlist_exposes_marker_but_not_descriptor():
    server_path = OMR_DIR.parents[1] / "server" / "byzorgan-web-server.py"
    spec = importlib.util.spec_from_file_location("chanterlab_server", server_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._omr_allowed("out/ingest/release.json") is True
    assert module._omr_allowed("release-descriptor.json") is False


def test_entrypoint_can_bind_disposable_pod_to_candidate_release(tmp_path):
    entrypoint_path = OMR_DIR.parents[1] / "server" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("chanterlab_entrypoint", entrypoint_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.DATA_ROOT = tmp_path / "data"
    module.TRAINING_ROOT = tmp_path / "training"
    release_id = "rel-20260710T200000Z-" + "a" * 12
    release = module.DATA_ROOT / "releases" / release_id
    (release / "out" / "ingest").mkdir(parents=True)
    (release / "content").mkdir()
    (module.TRAINING_ROOT / "omr").mkdir(parents=True)
    (module.TRAINING_ROOT / "content").mkdir()
    (release / "out" / "ingest" / "manifest.json").write_text("[]")
    (release / "out" / "ingest" / "release.json").write_text("{}")
    for name in module.BUILTINS:
        (release / "content" / name).write_text("<score-partwise/>")

    module.configure_catalog(f"releases/{release_id}")
    assert (module.TRAINING_ROOT / "omr" / "out").resolve() == release / "out"
    for name in module.BUILTINS:
        assert (module.TRAINING_ROOT / "content" / name).resolve() == release / "content" / name

    with pytest.raises(RuntimeError, match="invalid CATALOG_POINTER"):
        module.configure_catalog("../../etc")
