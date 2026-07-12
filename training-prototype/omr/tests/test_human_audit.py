"""TRUST-04 sampling, private review, aggregation, and clustering tests."""
from __future__ import annotations

import json
import hashlib
from collections import Counter
import subprocess
import sys
from pathlib import Path

import pytest
import fitz

from conftest import OMR_DIR

sys.path.insert(0, str(OMR_DIR))
import human_audit as ha


def _report(i, *, warning=True, confidence=True):
    warnings = {"pitch.unmatched_accidental": i + 1} if warning else {}
    value = .85 if i % 3 == 0 else (.95 if i % 3 == 1 else 1.0)
    report = {
        "voices": ["S"] if i % 2 else ["S", "A", "T", "B"],
        "stats": {"measures": 8 + i, "staves_per_system_mode": 1 if i % 2 else 4},
        "warning_counts": warnings,
    }
    if confidence:
        report["confidence"] = {
            "reference": "omr-confidence-vector-v1",
            "signals": {
                "measure_consistency": {"ratio": value, "evidence": {}},
                "glyph_coverage": {"ratio": value, "evidence": {}},
                "lyrics": {"ratio": value, "evidence": {}},
                "override_status": {"ratio": None,
                                    "evidence": {"override_applied": i == 5}},
            },
        }
    return report


def _release(tmp_path, count=8, *, confidence=True):
    root = tmp_path / "release"
    ingest = root / "out" / "ingest"
    ingest.mkdir(parents=True)
    (root / "release-descriptor.json").write_text(json.dumps({"release_id": "rel-test"}))
    state = {}
    manifest = []
    for i in range(count):
        piece_id = f"piece-{i:02d}"
        status = "review" if i in {1, 3, 5} else "accepted"
        state[piece_id] = {"status": status,
                           "category": "choral" if i % 2 == 0 else "chant",
                           "arrangementType": "Choral" if i % 2 == 0 else "Chant"}
        (ingest / f"{piece_id}.report.json").write_text(
            json.dumps(_report(i, warning=i % 2 == 1, confidence=confidence)))
        if status == "accepted":
            manifest.append({"id": piece_id})
    (ingest / "ingest_state.json").write_text(json.dumps(state))
    (ingest / "manifest.json").write_text(json.dumps(manifest))
    return root


def test_plan_is_reproducible_and_release_bound(tmp_path):
    release = _release(tmp_path)
    first = ha.create_plan(release, None, 6, 3, "fixed-seed", None)
    second = ha.create_plan(release, None, 6, 3, "fixed-seed", None)
    assert first == second
    assert first["release_id"] == "rel-test"
    assert first["population_size"] == 8 and first["sample_size"] == 6
    assert first["auditable_population_size"] == 8
    assert first["zero_measure_exclusions"] == 0
    assert first["status_targets"] == {"accepted": 4, "review": 2}
    assert all(1 <= len(row["measure_numbers"]) <= 3 for row in first["sample"])
    assert set(first["rubric"]) == set(ha.CATEGORIES)


def test_sample_covers_accepted_review_layout_voice_genre_and_confidence(tmp_path):
    plan = ha.create_plan(_release(tmp_path), None, 8, 2, "coverage", None)
    for dimension in ("status", "layout", "voice_count", "genre",
                      "measure_confidence", "warning_profile", "override_history"):
        expected = set(plan["strata_counts"][dimension])
        got = {row["strata"][dimension] for row in plan["sample"]}
        assert got == expected


def test_plan_refuses_release_without_confidence_vectors(tmp_path):
    with pytest.raises(ha.AuditError, match="confidence vector unavailable"):
        ha.create_plan(_release(tmp_path, confidence=False), None, 2, 1, "seed", None)


def test_status_allocation_is_explicit_and_validated(tmp_path):
    release = _release(tmp_path)
    plan = ha.create_plan(release, None, 4, 1, "quota", None, review_share=.5)
    assert plan["status_targets"] == {"accepted": 2, "review": 2}
    assert Counter(row["strata"]["status"] for row in plan["sample"]) == \
        Counter({"accepted": 2, "review": 2})
    with pytest.raises(ha.AuditError, match="review share"):
        ha.create_plan(release, None, 4, 1, "quota", None, review_share=2)


def test_zero_measure_reports_remain_clusterable_but_are_not_sampled(tmp_path):
    release = _release(tmp_path)
    report_path = release / "out/ingest/piece-01.report.json"
    report = json.loads(report_path.read_text())
    report["stats"]["measures"] = 0
    report_path.write_text(json.dumps(report))
    plan = ha.create_plan(release, None, 4, 1, "zero", None, review_share=.5)
    assert plan["zero_measure_exclusions"] == 1
    assert "piece-01" not in {row["piece_id"] for row in plan["sample"]}
    assert any("piece-01" in cluster["piece_ids"]
               for cluster in ha.cluster_review(ha.load_population(release)))


def test_font_index_is_validated_and_applied(tmp_path):
    release = _release(tmp_path)
    index = tmp_path / "fonts.json"
    index.write_text(json.dumps({"piece-00": "smufl", "piece-01": "legacy"}))
    rows = ha.load_population(release, index)
    assert rows[0]["strata"]["font"] == "smufl"
    assert rows[1]["strata"]["font"] == "legacy"
    index.write_text(json.dumps({"piece-00": "guessed"}))
    with pytest.raises(ha.AuditError, match="invalid font stratum"):
        ha.load_population(release, index)


@pytest.mark.parametrize("names, expected", [
    (["Bravura", "Academico"], "smufl"),
    (["Maestro", "Times New Roman"], "legacy"),
    (["Bravura", "Maestro"], "mixed"),
    (["Times New Roman"], "unknown"),
])
def test_font_name_classification_is_coarse_and_nonidentifying(names, expected):
    assert ha.classify_font_names(names) == expected


def test_font_index_is_bound_to_release_source_hash(tmp_path):
    release = _release(tmp_path, count=1)
    source = tmp_path / "source"
    pdf = source / "pdfs" / "ingest" / "piece-00.pdf"
    pdf.parent.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "rights-safe generated fixture")
    doc.save(pdf)
    doc.close()
    state_path = release / "out" / "ingest" / "ingest_state.json"
    state = json.loads(state_path.read_text())
    state["piece-00"].update(pdf="pdfs/ingest/piece-00.pdf",
                             source_pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
    state_path.write_text(json.dumps(state))
    assert ha.build_font_index(release, source) == {"piece-00": "unknown"}
    state["piece-00"]["source_pdf_sha256"] = "0" * 64
    state_path.write_text(json.dumps(state))
    with pytest.raises(ha.AuditError, match="hash mismatch"):
        ha.build_font_index(release, source)


def test_prepare_dataset_copies_sealed_reports_and_binds_inventory(tmp_path):
    release = _release(tmp_path, count=1)
    sha = subprocess.run(["git", "-C", str(OMR_DIR), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    (release / "release-descriptor.json").write_text(json.dumps({
        "release_id": "rel-test", "code": {"parser_git_sha": sha}}))
    out = tmp_path / "audit-dataset"
    metadata = ha.prepare_dataset(release, OMR_DIR, out)
    assert metadata["release_id"] == "rel-test"
    assert metadata["sealed_reports_copied"] == 1
    assert metadata["review_reports_regenerated"] == 0
    assert metadata["report_count"] == 1
    assert (out / "out/ingest/piece-00.report.json").exists()
    with pytest.raises(ha.AuditError, match="already exists"):
        ha.prepare_dataset(release, OMR_DIR, out)


def _completed(plan):
    results = ha.results_template(plan)
    for i, row in enumerate(results["observations"]):
        row["reviewer_ref"] = "reviewer_a"
        row["evidence_ref"] = f"evidence_{i:03d}"
        row["review_date"] = "2026-07-11"
        row["grades"] = {category: "pass" for category in ha.CATEGORIES}
    results["observations"][0]["grades"]["pitch"] = "major"
    results["observations"][1]["grades"]["lyric"] = "minor"
    return results


def test_summary_reports_category_rates_intervals_and_strata(tmp_path):
    plan = ha.create_plan(_release(tmp_path), None, 4, 2, "summary", None)
    summary = ha.summarize(plan, _completed(plan))
    assert summary["release_id"] == "rel-test"
    assert summary["sampled_pieces"] == 4
    assert summary["sampled_measures"] == 8
    assert summary["reviewer_observations"] == 8
    assert summary["categories"]["pitch"]["errors"] == 1
    assert len(summary["categories"]["pitch"]["error_rate_95pct_wilson"]) == 2
    assert summary["categories"]["lyric"]["errors"] == 1
    assert summary["domains"]["semantic"]["errors"] == 2
    assert summary["domains"]["structural"]["errors"] == 0
    assert "status" in summary["strata"]


@pytest.mark.parametrize("mutation, message", [
    (lambda results: results.update(release_id="other"), "not bound"),
    (lambda results: results["observations"].pop(), "at least one"),
    (lambda results: results["observations"][0].update(reviewer_ref="Jane@example.com"),
     "opaque identifier"),
    (lambda results: results["observations"][0]["grades"].update(pitch="probably"),
     "valid grade"),
])
def test_summary_fails_closed_on_incomplete_or_private_identity_data(tmp_path,
                                                                    mutation,
                                                                    message):
    plan = ha.create_plan(_release(tmp_path), None, 3, 1, "invalid", None)
    results = _completed(plan)
    mutation(results)
    with pytest.raises(ha.AuditError, match=message):
        ha.summarize(plan, results)


def test_review_clusters_are_ordered_by_projected_impact(tmp_path):
    rows = ha.load_population(_release(tmp_path), None)
    clusters = ha.cluster_review(rows)
    assert sum(cluster["piece_count"] for cluster in clusters) == 3
    assert clusters == sorted(clusters,
                              key=lambda row: (-row["priority_score"], row["signature"]))
    assert all(cluster["piece_ids"] == sorted(cluster["piece_ids"])
               for cluster in clusters)
    assert [cluster["campaign_id"] for cluster in clusters] == [
        f"parser-campaign-{i:03d}" for i in range(1, len(clusters) + 1)]
    assert all(cluster["projected_catalog_impact"] >= cluster["piece_count"]
               for cluster in clusters)


def test_summary_records_independent_reviewer_disagreement(tmp_path):
    plan = ha.create_plan(_release(tmp_path), None, 2, 1, "disagreement", None)
    results = _completed(plan)
    second = dict(results["observations"][0])
    second["reviewer_ref"] = "reviewer_b"
    second["evidence_ref"] = "evidence_second"
    second["grades"] = dict(second["grades"], pitch="pass")
    results["observations"].append(second)
    summary = ha.summarize(plan, results)
    assert summary["reviewer_observations"] == 3
    assert summary["categories"]["pitch"]["multiply_reviewed_measures"] == 1
    assert summary["categories"]["pitch"]["disagreement_measures"] == 1


def test_cli_writes_private_template_without_claiming_results(tmp_path):
    release = _release(tmp_path)
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "results.json"
    ha.main(["plan", "--release", str(release), "--sample-size", "3",
             "--out", str(plan_path), "--results-template", str(result_path)])
    plan = json.loads(plan_path.read_text())
    results = json.loads(result_path.read_text())
    assert plan["kind"] == "chanterlab-human-audit-plan"
    assert results["kind"] == "chanterlab-human-audit-results-private"
    assert all(row["reviewer_ref"] is None for row in results["observations"])
