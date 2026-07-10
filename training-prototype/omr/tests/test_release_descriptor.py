"""Tests for release_descriptor.py (CAT-01: docs/plans/10-catalog-releases/
11-release-contract.md). All fixtures are synthetic/hand-made — see
fixtures/release_descriptor/README.md — so these tests always run, never
skip, on any machine including a fresh CI checkout with no real local
catalog. That absence itself is also directly tested (see
test_empty_omr_dir_produces_honest_zero_descriptor).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
OMR_DIR = TESTS_DIR.parent
FIXTURE_DIR = TESTS_DIR / "fixtures" / "release_descriptor"

sys.path.insert(0, str(OMR_DIR))
import release_descriptor as rd  # noqa: E402


FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _build(omr_dir=FIXTURE_DIR, **kwargs):
    return rd.build_release_descriptor(omr_dir=omr_dir, now=FIXED_NOW, **kwargs)


# ---------------------------------------------------------------------------
# Content correctness against the fixture
# ---------------------------------------------------------------------------


def test_build_against_fixture_reports_correct_counts():
    d = _build()
    assert d["schema_version"] == rd.SCHEMA_VERSION
    assert d["manifest"]["present"] is True
    assert d["manifest"]["entry_count"] == 1
    assert d["musicxml"]["count"] == 1
    assert d["reports"]["count"] == 1
    assert d["state"]["present"] is True
    assert d["state"]["record_count"] == 2  # accepted + review
    assert d["overrides"]["count"] == 1
    assert d["overrides"]["tombstones"] == ["fixture_retired_example"]
    assert d["input"]["catalog_present"] is True
    assert d["input"]["source_inventory_count"] == 2  # both state records


def test_source_inventory_never_leaks_local_pdf_path_but_hashes_present_pdf():
    d = _build()
    inv = {e["id"]: e for e in d["input"]["source_inventory"]}
    assert inv["fixture_piece_a"]["source_url"] == "https://example.invalid/fixture_piece_a.pdf"
    assert inv["fixture_piece_a"]["pdf_sha256"] is not None
    # fixture_piece_b has no local PDF file in the fixture -> null, not an error.
    assert inv["fixture_piece_b"]["pdf_sha256"] is None
    for entry in d["input"]["source_inventory"]:
        assert "pdf" not in entry  # the local relative path field is never copied in


def test_trust_status_counts_and_confidence():
    d = _build()
    assert d["trust"]["status_counts"]["accepted"] == 1
    assert d["trust"]["status_counts"]["review"] == 1
    assert d["trust"]["status_counts"]["no_music"] == 0
    # confidence is over ACCEPTED items only
    assert d["trust"]["confidence"]["mean_integrity_pct"] == 95.0


def test_manifest_validation_clean_on_healthy_fixture():
    d = _build()
    assert d["manifest_validation"]["checked"] == 1
    assert d["manifest_validation"]["problems"] == []


def test_waivers_always_empty_today():
    assert _build()["waivers"] == []


def test_verification_not_recorded_by_default():
    d = _build()
    v = d["verification"]["regression_suite"]
    assert v["recorded"] is False
    assert v["passed"] is None and v["skipped"] is None and v["failed"] is None


def test_verification_recorded_when_supplied():
    d = _build(verified_passed=17, verified_skipped=19, verified_failed=0)
    v = d["verification"]["regression_suite"]
    assert v == {"passed": 17, "skipped": 19, "failed": 0, "recorded": True}


# ---------------------------------------------------------------------------
# Acceptance: "the same inputs produce the same content hashes"
# ---------------------------------------------------------------------------


def test_determinism_full_equality_with_pinned_clock():
    d1 = _build()
    d2 = _build()
    assert d1 == d2


def test_determinism_content_hashes_independent_of_time():
    d1 = rd.build_release_descriptor(omr_dir=FIXTURE_DIR, now=FIXED_NOW)
    d2 = rd.build_release_descriptor(omr_dir=FIXTURE_DIR, now=FIXED_NOW + timedelta(days=30))
    # release_id/generated_at are TIME-based by contract and must differ...
    assert d1["release_id"] != d2["release_id"]
    assert d1["generated_at"] != d2["generated_at"]
    # ...but every CONTENT hash must be identical regardless of when it ran.
    assert d1["input"]["catalog_input_hash"] == d2["input"]["catalog_input_hash"]
    assert d1["input"]["source_inventory_hash"] == d2["input"]["source_inventory_hash"]
    assert d1["manifest"]["hash"] == d2["manifest"]["hash"]
    assert d1["musicxml"]["hash"] == d2["musicxml"]["hash"]
    assert d1["reports"]["hash"] == d2["reports"]["hash"]
    assert d1["state"]["hash"] == d2["state"]["hash"]
    assert d1["overrides"]["hash"] == d2["overrides"]["hash"]
    assert d1["trust"] == d2["trust"]


# ---------------------------------------------------------------------------
# Validation — fails closed
# ---------------------------------------------------------------------------


def test_validate_descriptor_passes_on_healthy_fixture():
    assert rd.validate_descriptor(_build()) == []


@pytest.mark.parametrize("missing_key", [
    "schema_version", "release_id", "code", "manifest", "trust", "waivers",
])
def test_validate_descriptor_fails_closed_on_missing_required_field(missing_key):
    d = _build()
    del d[missing_key]
    problems = rd.validate_descriptor(d)
    assert any(missing_key in p for p in problems)


def test_validate_descriptor_fails_closed_on_wrong_schema_version():
    d = _build()
    d["schema_version"] = 99
    problems = rd.validate_descriptor(d)
    assert any("schema_version" in p for p in problems)


def test_validate_descriptor_fails_closed_on_malformed_release_id():
    d = _build()
    d["release_id"] = "not-a-real-release-id"
    problems = rd.validate_descriptor(d)
    assert any("release_id" in p for p in problems)


def test_validate_descriptor_fails_closed_on_reported_manifest_problems():
    d = _build()
    d["manifest_validation"]["problems"] = ["fixture_piece_a: musicxml file missing: fixture_piece_a.musicxml"]
    problems = rd.validate_descriptor(d)
    assert any("manifest_validation" in p for p in problems)


@pytest.mark.parametrize("leak", [
    "/mnt/data/code/byzorgan-web/training-prototype/omr/pdfs/ingest/foo.pdf",
    "pdfs/ingest/foo.pdf",
    "pdfs/survey/catalog.json",
    "/home/justin/.venv/bin/python",
])
def test_validate_descriptor_catches_private_path_leak(leak):
    d = _build()
    # Inject a leak somewhere deep in the tree, exactly like a real bug would
    # (e.g. someone accidentally copying a raw state record field forward).
    d["input"]["source_inventory"][0]["source_url"] = leak
    problems = rd.validate_descriptor(d)
    assert any("private local path" in p for p in problems)


def test_release_descriptor_module_itself_never_embeds_a_leak():
    # Positive control: the REAL builder output, unmodified, must never trip
    # the leak scanner — proves the scanner isn't just trivially strict.
    assert rd.validate_descriptor(_build()) == []


# ---------------------------------------------------------------------------
# manifest_validation catches a real missing/corrupt backing file
# ---------------------------------------------------------------------------


def test_manifest_validation_catches_missing_musicxml(tmp_path):
    broken = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, broken)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    d = rd.build_release_descriptor(omr_dir=broken, now=FIXED_NOW)
    assert d["manifest_validation"]["checked"] == 1
    assert any("musicxml file missing" in p for p in d["manifest_validation"]["problems"])
    # Generation itself still succeeds (reports the problem, doesn't crash) —
    # only VALIDATION fails closed, per CAT-01's acceptance wording.
    problems = rd.validate_descriptor(d)
    assert any("manifest_validation" in p for p in problems)


def test_manifest_validation_catches_corrupt_musicxml(tmp_path):
    broken = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, broken)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").write_text("not xml at all <<<", encoding="utf-8")

    d = rd.build_release_descriptor(omr_dir=broken, now=FIXED_NOW)
    assert any("does not parse" in p for p in d["manifest_validation"]["problems"])


def test_manifest_validation_catches_missing_report(tmp_path):
    broken = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, broken)
    (broken / "out" / "ingest" / "fixture_piece_a.report.json").unlink()

    d = rd.build_release_descriptor(omr_dir=broken, now=FIXED_NOW)
    assert any("report.json missing" in p for p in d["manifest_validation"]["problems"])


# ---------------------------------------------------------------------------
# The fresh-checkout case: no local catalog at all
# ---------------------------------------------------------------------------


def test_empty_omr_dir_produces_honest_zero_descriptor(tmp_path):
    empty = tmp_path / "empty_omr"
    empty.mkdir()
    d = rd.build_release_descriptor(omr_dir=empty, now=FIXED_NOW)

    assert d["input"]["catalog_present"] is False
    assert d["input"]["catalog_input_hash"] is None
    assert d["manifest"]["present"] is False
    assert d["manifest"]["entry_count"] == 0
    assert d["state"]["present"] is False
    assert d["musicxml"]["count"] == 0
    assert d["reports"]["count"] == 0
    assert d["overrides"]["count"] == 0
    assert all(v == 0 for v in d["trust"]["status_counts"].values())
    assert d["manifest_validation"] == {"checked": 0, "problems": []}
    # Still a fully schema-valid descriptor — absence is honestly reported,
    # not an invalid document.
    assert rd.validate_descriptor(d) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_valid_descriptor(tmp_path):
    out = tmp_path / "descriptor.json"
    rc = rd.main(["--omr-dir", str(FIXTURE_DIR), "--out", str(out)])
    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["manifest"]["entry_count"] == 1
    assert rd.validate_descriptor(written) == []


def test_cli_strict_exits_nonzero_on_broken_fixture(tmp_path):
    broken = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, broken)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    out = tmp_path / "descriptor.json"
    rc = rd.main(["--omr-dir", str(broken), "--out", str(out), "--strict"])
    assert rc == 1


def test_cli_non_strict_exits_zero_on_broken_fixture_but_reports_it(tmp_path):
    broken = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, broken)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    out = tmp_path / "descriptor.json"
    rc = rd.main(["--omr-dir", str(broken), "--out", str(out)])
    assert rc == 0  # doesn't fail the run...
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["manifest_validation"]["problems"]  # ...but the problem IS in the artifact
