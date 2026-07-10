"""Tests for release_descriptor.py (CAT-01: docs/plans/10-catalog-releases/
11-release-contract.md). All fixtures are synthetic/hand-made — see
fixtures/release_descriptor/README.md — so these tests always run, never
skip, on any machine including a fresh CI checkout with no real local
catalog. That absence itself is also directly tested (see
test_empty_omr_dir_produces_honest_zero_descriptor).

The fixture's path conventions (manifest/state `musicxml` fields carrying the
`out/ingest/` prefix, `pdf` carrying `pdfs/ingest/`, the raw upstream
catalog.json being a flat array) are deliberately identical to the real
local catalog at /mnt/data/code/byzorgan-web/training-prototype/omr,
confirmed by direct inspection — this suite would have caught the original
path-doubling bug this file's history fixed.
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


def _copy_fixture(tmp_path) -> Path:
    dest = tmp_path / "omr"
    shutil.copytree(FIXTURE_DIR, dest)
    return dest


# ---------------------------------------------------------------------------
# Content correctness against the fixture (real production path shape)
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


def test_musicxml_and_report_hashes_actually_resolve_real_bytes():
    # This is the regression test for the original path-doubling bug: the
    # fixture's manifest.musicxml is "out/ingest/fixture_piece_a.musicxml"
    # (relative to omr_dir, matching real production data exactly), and the
    # builder must resolve it correctly — not silently hash nothing.
    d = _build()
    assert d["musicxml"]["per_entry"]["fixture_piece_a"] is not None
    assert d["reports"]["per_entry"]["fixture_piece_a"] is not None
    expected_xml_hash = rd._sha256_file(FIXTURE_DIR / "out" / "ingest" / "fixture_piece_a.musicxml")
    assert d["musicxml"]["per_entry"]["fixture_piece_a"] == expected_xml_hash


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
    assert d["trust"]["confidence"]["mean_integrity_pct"] == 95.0


def test_manifest_validation_clean_on_healthy_fixture():
    d = _build()
    assert d["manifest_validation"]["checked"] == 1
    assert d["manifest_validation"]["problems"] == []


def test_integrity_clean_on_healthy_fixture():
    assert _build()["integrity"]["problems"] == []


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
# Provenance: builder vs parser vs app SHA must never be conflated
# ---------------------------------------------------------------------------


def test_builder_sha_is_populated_but_parser_and_app_sha_default_to_unknown():
    d = _build()
    # This repo IS a git checkout, so builder_git_sha should resolve.
    assert d["code"]["builder_git_sha"] is not None
    assert isinstance(d["code"]["builder_dirty"], bool)
    # Never fabricated as equal to builder_git_sha — explicit-or-null only.
    assert d["code"]["parser_git_sha"] is None
    assert d["code"]["app_git_sha"] is None


def test_explicit_parser_and_app_sha_are_recorded_verbatim():
    d = _build(parser_git_sha="parsersha123", app_git_sha="appsha456")
    assert d["code"]["parser_git_sha"] == "parsersha123"
    assert d["code"]["app_git_sha"] == "appsha456"
    # And still independent from builder_git_sha (not silently overwritten).
    assert d["code"]["builder_git_sha"] != "parsersha123"


# ---------------------------------------------------------------------------
# Acceptance: "the same inputs produce the same content hashes"
# ---------------------------------------------------------------------------


def test_determinism_full_equality_with_pinned_clock():
    d1 = _build()
    d2 = _build()
    assert d1 == d2


def test_determinism_content_hashes_and_fingerprint_independent_of_time():
    d1 = rd.build_release_descriptor(omr_dir=FIXTURE_DIR, now=FIXED_NOW)
    d2 = rd.build_release_descriptor(omr_dir=FIXTURE_DIR, now=FIXED_NOW + timedelta(days=30))
    # release_id/generated_at are TIME-based by contract and must differ...
    assert d1["release_id"] != d2["release_id"]
    assert d1["generated_at"] != d2["generated_at"]
    # ...but the content fingerprint and every section hash are identical
    # regardless of when it ran.
    assert d1["content_fingerprint"] == d2["content_fingerprint"]
    assert d1["input"]["catalog_input_hash"] == d2["input"]["catalog_input_hash"]
    assert d1["input"]["source_inventory_hash"] == d2["input"]["source_inventory_hash"]
    assert d1["manifest"]["hash"] == d2["manifest"]["hash"]
    assert d1["musicxml"]["hash"] == d2["musicxml"]["hash"]
    assert d1["reports"]["hash"] == d2["reports"]["hash"]
    assert d1["state"]["hash"] == d2["state"]["hash"]
    assert d1["overrides"]["hash"] == d2["overrides"]["hash"]
    assert d1["trust"] == d2["trust"]


def test_fingerprint_differs_when_content_differs(tmp_path):
    changed = _copy_fixture(tmp_path)
    xml = changed / "out" / "ingest" / "fixture_piece_a.musicxml"
    xml.write_text(xml.read_text(encoding="utf-8").replace("C</step>", "D</step>"), encoding="utf-8")

    d1 = _build()
    d2 = _build(omr_dir=changed)
    assert d1["content_fingerprint"] != d2["content_fingerprint"]
    assert d1["release_id"] != d2["release_id"]


def test_fingerprint_includes_parser_provenance():
    # Same on-disk content, different explicit parser SHA -> different
    # fingerprint. Proves provenance is actually part of the content
    # identity, not just decoration (CAT-01 correction #4).
    d1 = _build(parser_git_sha="aaaaaaa")
    d2 = _build(parser_git_sha="bbbbbbb")
    assert d1["content_fingerprint"] != d2["content_fingerprint"]


def test_fingerprint_is_a_real_sha256_hex_digest():
    fp = _build()["content_fingerprint"]
    assert len(fp) == 64
    int(fp, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# Validation — fails closed, jsonschema-enforced structure + semantic checks
# ---------------------------------------------------------------------------


def test_validate_descriptor_passes_on_healthy_fixture():
    assert rd.validate_descriptor(_build()) == []


@pytest.mark.parametrize("missing_key", [
    "schema_version", "release_id", "content_fingerprint", "code", "manifest",
    "trust", "waivers", "integrity", "readiness",
])
def test_validate_descriptor_fails_closed_on_missing_required_field(missing_key):
    d = _build()
    del d[missing_key]
    problems = rd.validate_descriptor(d)
    assert problems  # jsonschema will flag the missing required property


def test_validate_descriptor_fails_closed_on_wrong_schema_version():
    d = _build()
    d["schema_version"] = 99
    assert rd.validate_descriptor(d)


def test_validate_descriptor_fails_closed_on_malformed_release_id():
    d = _build()
    d["release_id"] = "not-a-real-release-id"
    problems = rd.validate_descriptor(d)
    assert any("release_id" in p for p in problems)


def test_validate_descriptor_fails_closed_on_malformed_fingerprint():
    d = _build()
    d["content_fingerprint"] = "not-hex"
    problems = rd.validate_descriptor(d)
    assert any("content_fingerprint" in p for p in problems)


def test_validate_descriptor_fails_closed_on_fingerprint_release_id_mismatch():
    d = _build()
    d["content_fingerprint"] = "0" * 64
    problems = rd.validate_descriptor(d)
    assert any("does not match content_fingerprint" in p for p in problems)


def test_validate_descriptor_fails_closed_on_reported_manifest_problems():
    d = _build()
    d["manifest_validation"]["problems"] = ["fixture_piece_a: musicxml file missing: out/ingest/fixture_piece_a.musicxml"]
    problems = rd.validate_descriptor(d)
    assert any("manifest_validation" in p for p in problems)


def test_validate_descriptor_fails_closed_on_reported_integrity_problems():
    d = _build()
    d["integrity"]["problems"] = ["duplicate manifest id: 'x'"]
    problems = rd.validate_descriptor(d)
    assert any("integrity reported" in p for p in problems)


@pytest.mark.parametrize("leak", [
    "/mnt/data/code/byzorgan-web/training-prototype/omr/pdfs/ingest/foo.pdf",
    "pdfs/ingest/foo.pdf",
    "pdfs/survey/catalog.json",
    "/home/justin/.venv/bin/python",
])
def test_validate_descriptor_catches_private_path_leak(leak):
    d = _build()
    d["input"]["source_inventory"][0]["source_url"] = leak
    problems = rd.validate_descriptor(d)
    assert any("private local path" in p for p in problems)


def test_release_descriptor_module_itself_never_embeds_a_leak():
    assert rd.validate_descriptor(_build()) == []


# ---------------------------------------------------------------------------
# manifest_validation catches a real missing/corrupt backing file
# ---------------------------------------------------------------------------


def test_manifest_validation_catches_missing_musicxml(tmp_path):
    broken = _copy_fixture(tmp_path)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    d = _build(omr_dir=broken)
    assert d["manifest_validation"]["checked"] == 1
    assert any("musicxml file missing" in p for p in d["manifest_validation"]["problems"])
    problems = rd.validate_descriptor(d)
    assert any("manifest_validation" in p for p in problems)


def test_manifest_validation_catches_corrupt_musicxml(tmp_path):
    broken = _copy_fixture(tmp_path)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").write_text("not xml at all <<<", encoding="utf-8")

    d = _build(omr_dir=broken)
    assert any("does not parse" in p for p in d["manifest_validation"]["problems"])


def test_manifest_validation_catches_missing_report(tmp_path):
    broken = _copy_fixture(tmp_path)
    (broken / "out" / "ingest" / "fixture_piece_a.report.json").unlink()

    d = _build(omr_dir=broken)
    assert any("report.json missing" in p for p in d["manifest_validation"]["problems"])


# ---------------------------------------------------------------------------
# Path safety: traversal, absolute paths, duplicate/non-simple ids,
# tombstone/active-override conflicts (correction #2)
# ---------------------------------------------------------------------------


def test_rejects_musicxml_path_traversal_outside_out_ingest(tmp_path):
    broken = _copy_fixture(tmp_path)
    manifest_path = broken / "out" / "ingest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[0]["musicxml"] = "out/ingest/../../pdfs/ingest/fixture_piece_a.pdf"
    manifest_path.write_text(json.dumps(manifest))

    d = _build(omr_dir=broken)
    assert d["musicxml"]["per_entry"]["fixture_piece_a"] is None
    assert any("path rejected" in p for p in d["integrity"]["problems"])
    assert any("path rejected" in p for p in d["manifest_validation"]["problems"])


def test_rejects_absolute_musicxml_path(tmp_path):
    broken = _copy_fixture(tmp_path)
    manifest_path = broken / "out" / "ingest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[0]["musicxml"] = "/etc/passwd"
    manifest_path.write_text(json.dumps(manifest))

    d = _build(omr_dir=broken)
    assert d["musicxml"]["per_entry"]["fixture_piece_a"] is None
    assert any("absolute path" in p for p in d["integrity"]["problems"])


def test_rejects_absolute_pdf_path(tmp_path):
    broken = _copy_fixture(tmp_path)
    state_path = broken / "out" / "ingest" / "ingest_state.json"
    state = json.loads(state_path.read_text())
    state["fixture_piece_a"]["pdf"] = "/etc/passwd"
    state_path.write_text(json.dumps(state))

    d = _build(omr_dir=broken)
    inv = {e["id"]: e for e in d["input"]["source_inventory"]}
    assert inv["fixture_piece_a"]["pdf_sha256"] is None
    assert any("pdf path rejected" in p and "absolute" in p for p in d["integrity"]["problems"])


def test_rejects_duplicate_manifest_ids(tmp_path):
    broken = _copy_fixture(tmp_path)
    manifest_path = broken / "out" / "ingest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    dup = dict(manifest[0])
    manifest.append(dup)
    manifest_path.write_text(json.dumps(manifest))

    d = _build(omr_dir=broken)
    assert any("duplicate manifest id" in p for p in d["integrity"]["problems"])


def test_rejects_non_simple_manifest_id(tmp_path):
    broken = _copy_fixture(tmp_path)
    manifest_path = broken / "out" / "ingest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[0]["id"] = "../escape"
    manifest_path.write_text(json.dumps(manifest))

    d = _build(omr_dir=broken)
    assert any("non-simple manifest id" in p for p in d["integrity"]["problems"])


def test_tombstone_active_override_conflict_detected(tmp_path):
    broken = _copy_fixture(tmp_path)
    # fixture_retired_example is already tombstoned in RETIRED; add an
    # active override file with that exact stem -> conflict.
    conflicting = broken / "overrides" / "fixture_retired_example.musicxml"
    conflicting.write_text((broken / "overrides" / "fixture_override_example.musicxml").read_text())

    d = _build(omr_dir=broken)
    assert any("tombstone/active-override conflict" in p for p in d["integrity"]["problems"])


# ---------------------------------------------------------------------------
# Readiness / promotability (correction #7)
# ---------------------------------------------------------------------------


def _fully_promotable_descriptor() -> dict:
    """A hand-built descriptor satisfying every promotability condition,
    independent of real git state (which may be dirty mid-development)."""
    d = _build(parser_git_sha="parsersha", app_git_sha="appsha",
                verified_passed=48, verified_skipped=19, verified_failed=0)
    d["code"]["builder_dirty"] = False
    d["readiness"] = rd.compute_readiness(d)
    return d


def test_promotable_true_when_everything_is_clean():
    d = _fully_promotable_descriptor()
    assert d["readiness"] == {"promotable": True, "reasons": []}


@pytest.mark.parametrize("mutate,expected_phrase", [
    (lambda d: d["input"].__setitem__("catalog_present", False), "no local catalog"),
    (lambda d: d["manifest"].__setitem__("entry_count", 0), "manifest is empty"),
    (lambda d: d["code"].__setitem__("parser_git_sha", None), "parser provenance is unknown"),
    (lambda d: d["code"].__setitem__("app_git_sha", None), "app provenance is unknown"),
    (lambda d: d["code"].__setitem__("builder_dirty", True), "not confirmed clean"),
    (lambda d: d["code"].__setitem__("builder_dirty", None), "not confirmed clean"),
    (lambda d: d["verification"]["regression_suite"].__setitem__("recorded", False), "not recorded"),
    (lambda d: d["verification"]["regression_suite"].update({"failed": 2, "recorded": True}), "failing test"),
    (lambda d: d["manifest_validation"].__setitem__("problems", ["x"]), "manifest_validation problem"),
    (lambda d: d["integrity"].__setitem__("problems", ["x"]), "integrity problem"),
])
def test_promotable_false_with_reason(mutate, expected_phrase):
    d = _fully_promotable_descriptor()
    mutate(d)
    readiness = rd.compute_readiness(d)
    assert readiness["promotable"] is False
    assert any(expected_phrase in r for r in readiness["reasons"])


def test_default_fixture_build_is_not_promotable_unknown_provenance():
    # The default _build() never supplies parser/app SHA, so it must never
    # claim promotable — this is the honest default, not a special case.
    d = _build()
    assert d["readiness"]["promotable"] is False
    assert any("provenance is unknown" in r for r in d["readiness"]["reasons"])


def test_empty_omr_dir_is_not_promotable(tmp_path):
    empty = tmp_path / "empty_omr"
    empty.mkdir()
    d = rd.build_release_descriptor(omr_dir=empty, now=FIXED_NOW)
    assert d["readiness"]["promotable"] is False
    assert any("no local catalog" in r for r in d["readiness"]["reasons"])


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
    assert d["integrity"] == {"problems": []}
    # Still a fully schema-valid descriptor — absence is honestly reported,
    # not an invalid document (only readiness reflects "don't promote this").
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


def test_cli_accepts_explicit_provenance(tmp_path):
    out = tmp_path / "descriptor.json"
    rd.main(["--omr-dir", str(FIXTURE_DIR), "--out", str(out),
             "--parser-sha", "psha", "--app-sha", "asha"])
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["code"]["parser_git_sha"] == "psha"
    assert written["code"]["app_git_sha"] == "asha"


def test_cli_strict_exits_nonzero_on_broken_fixture(tmp_path):
    broken = _copy_fixture(tmp_path)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    out = tmp_path / "descriptor.json"
    rc = rd.main(["--omr-dir", str(broken), "--out", str(out), "--strict"])
    assert rc == 1


def test_cli_non_strict_exits_zero_on_broken_fixture_but_reports_it(tmp_path):
    broken = _copy_fixture(tmp_path)
    (broken / "out" / "ingest" / "fixture_piece_a.musicxml").unlink()

    out = tmp_path / "descriptor.json"
    rc = rd.main(["--omr-dir", str(broken), "--out", str(out)])
    assert rc == 0  # doesn't fail the run...
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["manifest_validation"]["problems"]  # ...but the problem IS in the artifact
