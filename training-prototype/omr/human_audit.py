#!/usr/bin/env python3
"""Reproducible private human-audit sampling, aggregation, and clustering."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


SCHEMA_VERSION = 1
CATEGORIES = ("pitch", "rhythm", "voice", "lyric", "divisi", "layout", "metadata")
DOMAINS = {"semantic": ("pitch", "rhythm", "voice", "lyric", "divisi"),
           "structural": ("layout", "metadata")}
GRADES = {"pass", "minor", "major", "unreviewable"}
SEVERITY = {"pass": 0, "minor": 1, "major": 2, "unreviewable": -1}
OPAQUE_REF = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


class AuditError(ValueError):
    pass


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _hash(seed: str, *parts: object) -> str:
    text = "\0".join([seed, *(str(part) for part in parts)])
    return hashlib.sha256(text.encode()).hexdigest()


def _sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_paths(release: Path):
    ingest = release / "out" / "ingest"
    if not ingest.is_dir() and (release / "manifest.json").exists():
        ingest = release
    return ingest


def _release_id(release: Path, explicit: str | None):
    if explicit:
        return explicit
    descriptor = release / "release-descriptor.json"
    if descriptor.exists():
        return _load(descriptor).get("release_id")
    raise AuditError("release identity unavailable; pass --release-id")


def _band(value, cuts=(.9, .98)):
    if value is None:
        return "unknown"
    if value < cuts[0]:
        return "low"
    if value < cuts[1]:
        return "middle"
    return "high"


def _genre(record):
    text = " ".join(str(record.get(k) or "") for k in
                    ("category", "arrangementType", "hymnType", "group")).lower()
    if "choral" in text:
        return "choral"
    if "chant" in text or "byzantine" in text:
        return "chant"
    return "unknown"


def _warning_profile(counts):
    active = sorted(code for code, count in counts.items() if count)
    if not active:
        return "clean"
    families = sorted({code.split(".", 1)[0] for code in active})
    return "+".join(families)


def _font_value(piece_id, font_index):
    value = font_index.get(piece_id, "unknown") if font_index else "unknown"
    if value not in {"legacy", "smufl", "mixed", "unknown"}:
        raise AuditError(f"invalid font stratum for {piece_id}: {value}")
    return value


def classify_font_names(names):
    import vector_extract as ve
    families = {ve._music_font_family(name) for name in names}
    families.discard(None)
    if families == {"smufl", "finale"}:
        return "mixed"
    if families == {"smufl"}:
        return "smufl"
    if families == {"finale"}:
        return "legacy"
    return "unknown"


def build_font_index(release: Path, source_omr_dir: Path):
    import fitz
    state = _load(_release_paths(release) / "ingest_state.json")
    index = {}
    for piece_id, record in sorted(state.items()):
        if record.get("status") not in {"accepted", "review"}:
            continue
        relative = record.get("pdf")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise AuditError(f"{piece_id}: unsafe or missing source PDF reference")
        path = source_omr_dir / relative
        if not path.exists():
            raise AuditError(f"{piece_id}: source PDF unavailable for font indexing")
        expected_hash = record.get("source_pdf_sha256")
        if not expected_hash or _sha256_file(path) != expected_hash:
            raise AuditError(f"{piece_id}: source PDF hash mismatch for font indexing")
        with fitz.open(path) as doc:
            names = {font[3] for page in doc for font in page.get_fonts(full=True)}
        index[piece_id] = classify_font_names(names)
    return index


def _assert_parser_checkout(source_omr_dir: Path, parser_sha: str):
    repo = subprocess.run(["git", "-C", str(source_omr_dir), "rev-parse",
                           "--show-toplevel"], capture_output=True, text=True,
                          check=True).stdout.strip()
    relative_omr = source_omr_dir.resolve().relative_to(Path(repo).resolve())
    for name in ("pipeline.py", "vector_extract.py", "confidence_signals.py",
                 "legacy_glyph_map.json"):
        current = (source_omr_dir / name).read_bytes()
        committed = subprocess.run(
            ["git", "-C", repo, "show", f"{parser_sha}:{relative_omr / name}"],
            capture_output=True, check=True).stdout
        if current != committed:
            raise AuditError(f"parser checkout does not match release: {name}")


def prepare_dataset(release: Path, source_omr_dir: Path, out: Path):
    descriptor = _load(release / "release-descriptor.json")
    release_id = descriptor["release_id"]
    parser_sha = descriptor["code"]["parser_git_sha"]
    _assert_parser_checkout(source_omr_dir, parser_sha)
    source_ingest = _release_paths(release)
    state = _load(source_ingest / "ingest_state.json")
    target_ingest = out / "out" / "ingest"
    if out.exists():
        raise AuditError("audit dataset output already exists")
    target_ingest.mkdir(parents=True)
    shutil.copy2(source_ingest / "ingest_state.json", target_ingest)
    shutil.copy2(source_ingest / "manifest.json", target_ingest)
    shutil.copy2(release / "release-descriptor.json", out)
    extracted = copied = 0
    try:
        for piece_id, record in sorted(state.items()):
            if record.get("status") not in {"accepted", "review"}:
                continue
            target_report = target_ingest / f"{piece_id}.report.json"
            sealed_report = source_ingest / target_report.name
            if sealed_report.exists():
                shutil.copy2(sealed_report, target_report)
                copied += 1
                continue
            relative = record.get("pdf")
            pdf = source_omr_dir / relative if relative else None
            if not pdf or not pdf.exists() or _sha256_file(pdf) != record.get("source_pdf_sha256"):
                raise AuditError(f"{piece_id}: review source is missing or hash-mismatched")
            with tempfile.TemporaryDirectory(prefix="chanterlab-audit-") as temp:
                xml = Path(temp) / "discard.musicxml"
                proc = subprocess.run(
                    [sys.executable, str(source_omr_dir / "pipeline.py"), str(pdf),
                     "-o", str(xml), "--report", str(target_report)],
                    cwd=source_omr_dir, capture_output=True, text=True)
            if proc.returncode not in {0, 2} or not target_report.exists():
                raise AuditError(f"{piece_id}: review report extraction failed: {proc.stderr[-500:]}")
            report = _load(target_report)
            if report.get("confidence", {}).get("reference") != "omr-confidence-vector-v1":
                raise AuditError(f"{piece_id}: regenerated report lacks confidence vector")
            extracted += 1
        report_hashes = {path.name.removesuffix(".report.json"): _sha256_file(path)
                         for path in sorted(target_ingest.glob("*.report.json"))}
        metadata = {"schema_version": SCHEMA_VERSION,
                    "kind": "chanterlab-private-audit-dataset",
                    "release_id": release_id, "parser_git_sha": parser_sha,
                    "sealed_reports_copied": copied,
                    "review_reports_regenerated": extracted,
                    "report_count": len(report_hashes),
                    "report_inventory_hash": hashlib.sha256(
                        json.dumps(report_hashes, sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()}
        _dump(out / "audit-dataset.json", metadata)
        return metadata
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise


def _row(piece_id, state, report, font_index):
    confidence = report.get("confidence")
    if not confidence or confidence.get("reference") != "omr-confidence-vector-v1":
        raise AuditError(f"{piece_id}: confidence vector unavailable")
    warning_counts = report.get("warning_counts")
    if not isinstance(warning_counts, dict):
        raise AuditError(f"{piece_id}: stable warning counts unavailable")
    signals = confidence["signals"]
    voices = report.get("voices") or []
    trust = state.get("trust_status", "auto-imported")
    strata = {
        "status": state.get("status", "unknown"),
        "font": _font_value(piece_id, font_index),
        "layout": str(report.get("stats", {}).get("staves_per_system_mode", "unknown")),
        "voice_count": str(len(voices)),
        "genre": _genre(state),
        "warning_profile": _warning_profile(warning_counts),
        "measure_confidence": _band(signals["measure_consistency"]["ratio"]),
        "glyph_confidence": _band(signals["glyph_coverage"]["ratio"]),
        "lyric_confidence": _band(signals["lyrics"]["ratio"]),
        "override_history": "override" if signals["override_status"]["evidence"]
            .get("override_applied") else trust,
    }
    measures = int(report.get("stats", {}).get("measures") or 0)
    return {"piece_id": piece_id, "strata": strata, "measures": measures,
            "warning_counts": warning_counts,
            "confidence_reference": confidence["reference"]}


def load_population(release: Path, font_index_path: Path | None = None):
    ingest = _release_paths(release)
    state = _load(ingest / "ingest_state.json")
    font_index = _load(font_index_path) if font_index_path else {}
    rows = []
    for piece_id, record in sorted(state.items()):
        if record.get("status") not in {"accepted", "review"}:
            continue
        report_path = ingest / f"{piece_id}.report.json"
        if not report_path.exists():
            raise AuditError(f"{piece_id}: report missing")
        rows.append(_row(piece_id, record, _load(report_path), font_index))
    return rows


def _coverage_tokens(row):
    return {(key, value) for key, value in row["strata"].items()}


def select_sample(rows, sample_size: int, seed: str):
    if not 0 < sample_size <= len(rows):
        raise AuditError("sample size must be between 1 and population size")
    token_counts = Counter(token for row in rows for token in _coverage_tokens(row))
    remaining = sorted(rows, key=lambda row: _hash(seed, row["piece_id"]))
    selected, covered = [], set()
    while remaining and len(selected) < sample_size:
        def score(row):
            new = _coverage_tokens(row) - covered
            rarity = sum(1 / token_counts[token] for token in new)
            return (-len(new), -rarity, _hash(seed, row["piece_id"]))
        best = min(remaining, key=score)
        remaining.remove(best)
        selected.append(best)
        covered |= _coverage_tokens(best)
    return selected


def select_status_sample(rows, sample_size: int, seed: str, review_share: float):
    if not 0 <= review_share <= 1:
        raise AuditError("review share must be between 0 and 1")
    by_status = {status: [row for row in rows if row["strata"]["status"] == status]
                 for status in ("accepted", "review")}
    review_target = min(len(by_status["review"]), round(sample_size * review_share))
    if review_share and by_status["review"] and review_target == 0:
        review_target = 1
    accepted_target = min(len(by_status["accepted"]), sample_size - review_target)
    shortfall = sample_size - accepted_target - review_target
    if shortfall:
        review_target += min(shortfall, len(by_status["review"]) - review_target)
        shortfall = sample_size - accepted_target - review_target
    if shortfall:
        accepted_target += min(shortfall, len(by_status["accepted"]) - accepted_target)
    if accepted_target + review_target != sample_size:
        raise AuditError("sample size exceeds accepted and review population")
    selected = select_sample(by_status["accepted"], accepted_target,
                             f"{seed}:accepted") if accepted_target else []
    selected += select_sample(by_status["review"], review_target,
                              f"{seed}:review") if review_target else []
    selected.sort(key=lambda row: _hash(seed, row["piece_id"]))
    return selected, {"accepted": accepted_target, "review": review_target}


def _measure_sample(piece_id, count, per_piece, seed):
    if count <= 0:
        return []
    ranked = sorted(range(1, count + 1), key=lambda n: _hash(seed, piece_id, n))
    return sorted(ranked[:min(per_piece, count)])


def create_plan(release: Path, release_id: str | None, sample_size: int,
                measures_per_piece: int, seed: str, font_index: Path | None,
                review_share: float = .25):
    rid = _release_id(release, release_id)
    rows = load_population(release, font_index)
    auditable = [row for row in rows if row["measures"] > 0]
    selected, status_targets = select_status_sample(auditable, sample_size, seed,
                                                     review_share)
    for row in selected:
        row["measure_numbers"] = _measure_sample(
            row["piece_id"], row.pop("measures"), measures_per_piece, seed)
    strata_counts = {key: dict(sorted(Counter(
        row["strata"][key] for row in auditable).items()))
        for key in next(iter(auditable))["strata"]}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "chanterlab-human-audit-plan",
        "release_id": rid,
        "seed": seed,
        "population_size": len(rows),
        "auditable_population_size": len(auditable),
        "zero_measure_exclusions": len(rows) - len(auditable),
        "sample_size": len(selected),
        "status_targets": status_targets,
        "measures_per_piece": measures_per_piece,
        "strata_counts": strata_counts,
        "rubric": {category: {"grades": sorted(GRADES),
                              "unit": "source-to-transcription measure comparison"}
                   for category in CATEGORIES},
        "sample": selected,
    }


def results_template(plan):
    observations = []
    for row in plan["sample"]:
        for measure in row["measure_numbers"]:
            observations.append({"piece_id": row["piece_id"], "measure": measure,
                                 "reviewer_ref": None, "review_date": None,
                                 "evidence_ref": None,
                                 "grades": {category: None for category in CATEGORIES}})
    return {"schema_version": SCHEMA_VERSION,
            "kind": "chanterlab-human-audit-results-private",
            "release_id": plan["release_id"], "seed": plan["seed"],
            "observations": observations}


def _wilson(errors, total, z=1.96):
    if total == 0:
        return None
    p = errors / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return [round(max(0, center - margin), 6), round(min(1, center + margin), 6)]


def summarize(plan, results):
    if results.get("release_id") != plan.get("release_id") or \
            results.get("seed") != plan.get("seed"):
        raise AuditError("results are not bound to this plan")
    expected = {(row["piece_id"], measure) for row in plan["sample"]
                for measure in row["measure_numbers"]}
    observations = results.get("observations", [])
    got = {(row.get("piece_id"), row.get("measure")) for row in observations}
    if got != expected:
        raise AuditError("results need at least one observation per sampled measure")
    reviewer_keys = [(row.get("piece_id"), row.get("measure"),
                      row.get("reviewer_ref")) for row in observations]
    if len(reviewer_keys) != len(set(reviewer_keys)):
        raise AuditError("a reviewer may submit only once per sampled measure")
    for row in observations:
        if not OPAQUE_REF.fullmatch(str(row.get("reviewer_ref") or "")):
            raise AuditError("reviewer_ref must be an opaque identifier")
        if not OPAQUE_REF.fullmatch(str(row.get("evidence_ref") or "")):
            raise AuditError("evidence_ref must be an opaque identifier")
        try:
            date.fromisoformat(row.get("review_date"))
        except (TypeError, ValueError):
            raise AuditError("every observation needs an ISO review_date") from None
        grades = row.get("grades", {})
        if set(grades) != set(CATEGORIES) or not set(grades.values()) <= GRADES:
            raise AuditError("every rubric category needs a valid grade")
    by_category = {}
    obs_groups = defaultdict(list)
    for row in observations:
        obs_groups[(row["piece_id"], row["measure"])].append(row)
    for category in CATEGORIES:
        values = [row["grades"][category] for row in observations]
        usable = [v for v in values if v != "unreviewable"]
        errors = sum(v in {"minor", "major"} for v in usable)
        major = sum(v == "major" for v in usable)
        disagreement = sum(
            len({row["grades"][category] for row in group
                 if row["grades"][category] != "unreviewable"}) > 1
            for group in obs_groups.values())
        multiply_reviewed = sum(len(group) > 1 for group in obs_groups.values())
        by_category[category] = {
            "reviewed": len(usable), "unreviewable": len(values) - len(usable),
            "errors": errors, "major_errors": major,
            "multiply_reviewed_measures": multiply_reviewed,
            "disagreement_measures": disagreement,
            "error_rate": round(errors / len(usable), 6) if usable else None,
            "error_rate_95pct_wilson": _wilson(errors, len(usable)),
        }
    domains = {}
    for domain, categories in DOMAINS.items():
        usable = [row["grades"][category] for row in observations
                  for category in categories
                  if row["grades"][category] != "unreviewable"]
        errors = sum(grade in {"minor", "major"} for grade in usable)
        domains[domain] = {"category_reviews": len(usable), "errors": errors,
                           "error_rate": round(errors / len(usable), 6) if usable else None,
                           "error_rate_95pct_wilson": _wilson(errors, len(usable))}
    sample_by_id = {row["piece_id"]: row for row in plan["sample"]}
    strata = {}
    for dimension in next(iter(sample_by_id.values()))["strata"]:
        groups = defaultdict(list)
        for obs in observations:
            groups[sample_by_id[obs["piece_id"]]["strata"][dimension]].append(obs)
        strata[dimension] = {}
        for value, group in sorted(groups.items()):
            usable = [grade for obs in group for grade in obs["grades"].values()
                      if grade != "unreviewable"]
            errors = sum(grade in {"minor", "major"} for grade in usable)
            strata[dimension][value] = {
                "measure_observations": len(group), "category_reviews": len(usable),
                "errors": errors,
                "error_rate": round(errors / len(usable), 6) if usable else None,
                "error_rate_95pct_wilson": _wilson(errors, len(usable)),
            }
    return {"schema_version": SCHEMA_VERSION,
            "kind": "chanterlab-human-audit-aggregate",
            "release_id": plan["release_id"], "seed": plan["seed"],
            "reviewed_from": min(row["review_date"] for row in observations),
            "reviewed_through": max(row["review_date"] for row in observations),
            "sampled_pieces": plan["sample_size"],
            "sampled_measures": len(expected),
            "reviewer_observations": len(observations),
            "domains": domains, "categories": by_category, "strata": strata,
            "limitations": ["Machine-selected sample; human grades are source comparisons.",
                            "Intervals describe this sample and are not calibrated parser confidence."]}


def cluster_review(rows):
    population = defaultdict(list)
    review = defaultdict(list)
    for row in rows:
        active = tuple(sorted(code for code, count in row["warning_counts"].items() if count))
        signature = "+".join(active) if active else "low-confidence-without-warning"
        population[signature].append(row)
        if row["strata"]["status"] == "review":
            review[signature].append(row)
    out = []
    for signature, members in review.items():
        events = sum(sum(row["warning_counts"].values()) for row in members)
        projected = population[signature]
        out.append({"signature": signature, "piece_count": len(members),
                    "warning_events": events,
                    "projected_catalog_impact": len(projected),
                    "projected_accepted_impact": sum(
                        row["strata"]["status"] == "accepted" for row in projected),
                    "piece_ids": sorted(row["piece_id"] for row in members),
                    "priority_score": len(members) * 1000 + len(projected) * 10 + events})
    out.sort(key=lambda row: (-row["priority_score"], row["signature"]))
    for index, row in enumerate(out, 1):
        row["campaign_id"] = f"parser-campaign-{index:03d}"
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--release", type=Path, required=True)
    plan.add_argument("--release-id")
    plan.add_argument("--font-index", type=Path)
    plan.add_argument("--sample-size", type=int, default=48)
    plan.add_argument("--measures-per-piece", type=int, default=3)
    plan.add_argument("--seed", default="chanterlab-trust04-v1")
    plan.add_argument("--review-share", type=float, default=.25)
    plan.add_argument("--out", type=Path, required=True)
    plan.add_argument("--results-template", type=Path)
    summary = sub.add_parser("summarize")
    summary.add_argument("--plan", type=Path, required=True)
    summary.add_argument("--results", type=Path, required=True)
    summary.add_argument("--out", type=Path, required=True)
    cluster = sub.add_parser("cluster")
    cluster.add_argument("--release", type=Path, required=True)
    cluster.add_argument("--font-index", type=Path)
    cluster.add_argument("--out", type=Path, required=True)
    fonts = sub.add_parser("font-index")
    fonts.add_argument("--release", type=Path, required=True)
    fonts.add_argument("--source-omr-dir", type=Path, required=True)
    fonts.add_argument("--out", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--release", type=Path, required=True)
    prepare.add_argument("--source-omr-dir", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = create_plan(args.release, args.release_id, args.sample_size,
                                args.measures_per_piece, args.seed, args.font_index,
                                args.review_share)
            _dump(args.out, value)
            if args.results_template:
                _dump(args.results_template, results_template(value))
        elif args.command == "summarize":
            _dump(args.out, summarize(_load(args.plan), _load(args.results)))
        elif args.command == "cluster":
            rows = load_population(args.release, args.font_index)
            _dump(args.out, {"schema_version": SCHEMA_VERSION,
                             "kind": "chanterlab-review-clusters",
                             "clusters": cluster_review(rows)})
        elif args.command == "font-index":
            _dump(args.out, build_font_index(args.release, args.source_omr_dir))
        else:
            prepare_dataset(args.release, args.source_omr_dir, args.out)
    except AuditError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
