"""OMR engine regression suite (issue #53).

Every recent ``vector_extract.py`` fix has been hand-validated against a
"byte-identical output on clean pieces" bar. This suite automates that
check ahead of the riskier staff-grouping / integrity-model work planned in
issue #52: it re-extracts a ~10-piece corpus (picked to cover the failure
modes recent fixes touched -- shared-staff voice separation, whole-measure-
rest shrink/grow, legacy vs SMuFL font families, 2-staff choral reductions,
multi-section/multi-verse lyrics) from the LOCAL source PDFs and compares
the result against committed expectations (``tests/expectations.json``):
a per-piece sha256 of the emitted MusicXML, plus key stats pulled from the
confidence report (measures, sections, lyric_verses,
whole_measure_rests_resized, integrity_pct, voices, note_events_per_voice).

Comparing stats *and* the hash means a future change that legitimately
alters the emitted bytes still has to explain, in the failure output,
exactly which tracked stat moved (or that none did -- i.e. the change is
purely formatting/ordering).

LOCAL-ONLY BY DESIGN: the corpus PDFs are copyrighted and live under
``omr/pdfs/`` (gitignored). On a machine without them (e.g. CI) every test
here SKIPs with a clear message instead of failing.

Run from ``omr/``::

    .venv/bin/python -m pytest tests/

Re-bless after a deliberate, reviewed engine change (see README.md policy)::

    UPDATE_EXPECTATIONS=1 .venv/bin/python -m pytest tests/
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

from conftest import PDF_DIR, load_expectations, run_pipeline, record_bless, \
    skip_if_pdf_missing

_EXPECTATIONS = load_expectations()
_PIECES = _EXPECTATIONS["pieces"]


def _sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _stats_of(rep: dict, exit_code: int) -> dict:
    """Pull exactly the stats the issue asked us to lock down out of a
    confidence report dict (as loaded from <out>.report.json)."""
    s = rep.get("stats", {})
    note_counts = rep.get("note_events_per_voice", {})
    return {
        "measures": s.get("measures"),
        "sections": len(rep.get("sections") or []),
        "lyric_verses": rep.get("lyric_verses"),
        "whole_measure_rests_resized": s.get("whole_measure_rests_resized", 0),
        "integrity_pct": s.get("measure_integrity_pct"),
        "voices": rep.get("voices"),
        "note_events_per_voice": note_counts,
        "note_events_total": sum(note_counts.values()),
        "warnings_count": len(rep.get("warnings") or []),
        "exit_code": exit_code,
    }


def _extract_and_check(piece_id: str, tmp_path, bless_mode: bool):
    """Extract one corpus piece and either record (bless) or compare its
    sha256 + tracked stats against tests/expectations.json. Returns
    (xml_path, rep, stats) for callers that want the raw extraction too."""
    entry = _PIECES[piece_id]
    pdf_path = PDF_DIR / entry["pdf"]
    skip_if_pdf_missing(piece_id, pdf_path)

    proc, xml_path, report_path = run_pipeline(pdf_path, tmp_path)
    assert xml_path.exists() and report_path.exists(), (
        f"{piece_id}: pipeline.py produced no output "
        f"(exit {proc.returncode}); stderr:\n{proc.stderr}")

    got_sha = _sha256_of(xml_path)
    with open(report_path, encoding="utf-8") as f:
        rep = json.load(f)
    got_stats = _stats_of(rep, proc.returncode)

    if bless_mode:
        record_bless(piece_id, {
            "pdf": entry["pdf"],
            "sha256": got_sha,
            "stats": got_stats,
        })
        return xml_path, rep, got_stats

    exp_sha = entry["sha256"]
    exp_stats = entry["stats"]
    mismatches = {k: (v, got_stats.get(k))
                  for k, v in exp_stats.items() if got_stats.get(k) != v}
    hash_changed = got_sha != exp_sha

    if mismatches or hash_changed:
        lines = [f"{piece_id}: regression vs committed expectations."]
        if hash_changed:
            lines.append(f"  sha256 expected: {exp_sha}")
            lines.append(f"  sha256 got:      {got_sha}")
        else:
            lines.append("  sha256: unchanged")
        if mismatches:
            lines.append("  stat changes:")
            for k, (exp_v, got_v) in mismatches.items():
                lines.append(f"    {k}: expected {exp_v!r}, got {got_v!r}")
        else:
            lines.append("  (no tracked stat moved -- the emitted bytes "
                          "changed some other way, e.g. formatting, "
                          "attribute ordering, or an untracked field)")
        lines.append("")
        lines.append(
            "If this is an intentional, reviewed engine change: re-bless "
            "with `UPDATE_EXPECTATIONS=1 .venv/bin/python -m pytest "
            f"tests/ -k {piece_id}` (or --bless) and say why in the commit "
            "message. See tests/README.md.")
        pytest.fail("\n".join(lines))

    return xml_path, rep, got_stats


@pytest.mark.parametrize("piece_id", sorted(_PIECES))
def test_piece_regression(piece_id, tmp_path, bless_mode):
    """Byte-identical (+ stat-identical) extraction for one corpus piece."""
    _extract_and_check(piece_id, tmp_path, bless_mode)


# --------------------------------------------------------------------------
# Determinism guard: extract twice (with different PYTHONHASHSEED, to catch
# a future regression that leaks Python's hash-randomized dict/set ordering
# into the output) and require byte-identical MusicXML. Manually verified
# during this suite's creation on both a small piece (trisagion) and the
# largest one (Finley complete liturgy) -- see README.md "Determinism".
# Kept as an automated test, not just tribal knowledge, since issue #52's
# staff-grouping rework is exactly the kind of change that could introduce
# set-based grouping with nondeterministic order.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("piece_id", [
    "trisagion_satb",              # small, fast
    "finley_complete_liturgy",      # largest / most structurally complex
])
def test_determinism(piece_id, tmp_path):
    entry = _PIECES[piece_id]
    pdf_path = PDF_DIR / entry["pdf"]
    skip_if_pdf_missing(piece_id, pdf_path)

    proc1, xml1, _ = run_pipeline(pdf_path, tmp_path / "run1",
                                   env={"PYTHONHASHSEED": "1"})
    proc2, xml2, _ = run_pipeline(pdf_path, tmp_path / "run2",
                                   env={"PYTHONHASHSEED": "999999"})
    assert proc1.returncode == proc2.returncode, (
        f"{piece_id}: exit code differs across runs "
        f"({proc1.returncode} vs {proc2.returncode}) -- nondeterministic")

    sha1, sha2 = _sha256_of(xml1), _sha256_of(xml2)
    assert sha1 == sha2, (
        f"{piece_id}: extraction is NOT deterministic across "
        f"PYTHONHASHSEED values ({sha1} vs {sha2}). The regression suite's "
        f"sha256 comparisons assume determinism -- if this legitimately "
        f"starts firing, switch the comparison to a canonicalized form "
        f"(e.g. re-serialize through an XML canonicalizer) instead of raw "
        f"bytes, and note why in the commit message.")


# --------------------------------------------------------------------------
# Fine-grained spot checks: the two whole-measure-rest normalization corner
# cases the corpus was specifically chosen to cover (see
# vector_extract.py's "whole-measure-rest normalization" comment). These
# pin the exact per-measure beat math, not just aggregate stats, so a future
# change to the shrink/grow logic has to explain itself here even if it
# doesn't move whole_measure_rests_resized's count.
# --------------------------------------------------------------------------

def _measure_total_beats(xml_path, part_id: str, measure_number: str) -> float:
    """Sum note/rest durations (in beats) for one <measure> of one <part> of
    an emitted MusicXML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    divisions = None
    for d in root.iter("divisions"):
        divisions = int(d.text)
        break
    assert divisions, f"no <divisions> found in {xml_path}"
    for part in root.findall("part"):
        if part.get("id") != part_id:
            continue
        for measure in part.findall("measure"):
            if measure.get("number") != measure_number:
                continue
            total = 0
            for note in measure.findall("note"):
                dur = note.find("duration")
                if dur is not None:
                    total += int(dur.text)
            return total / divisions
    pytest.fail(f"part {part_id} measure {measure_number} not found in "
                f"{xml_path}")


def test_whole_measure_rest_shrink_hilko_star(tmp_path):
    """hilko_star_antiphon: T (P3) and B (P4) measures 46 and 48 are
    genuinely 3.0-beat bars; the engine must shrink their whole rest down
    from the 4.0-beat default rather than leave it at 4.0 (which would have
    desynced the next entrance -- the exact defect this normalization
    fixes)."""
    piece_id = "hilko_star_antiphon"
    entry = _PIECES[piece_id]
    pdf_path = PDF_DIR / entry["pdf"]
    skip_if_pdf_missing(piece_id, pdf_path)

    _, xml_path, _ = run_pipeline(pdf_path, tmp_path)
    for part_id in ("P3", "P4"):
        for measure in ("46", "48"):
            beats = _measure_total_beats(xml_path, part_id, measure)
            assert beats == pytest.approx(3.0), (
                f"{piece_id}: part {part_id} measure {measure} expected "
                f"3.0 beats (shrunk whole rest matching the real S/A "
                f"content), got {beats}")


def test_whole_measure_rest_grow_theophany(tmp_path):
    """theophany_series1: a 14-beat chant melisma bar (parts P1/P2) -- the
    exact example in vector_extract.py's whole-measure-rest-normalization
    comment -- so the whole rest there must GROW from the 4.0-beat default up
    to 14.0, not stay truncated at 4.0 (which would cue the next entrance
    early). Parts P3/P4 cover the same grow path at 14.25 beats.

    Measure NUMBERS updated 28->36 (P1/P2, 14.0) and 30->38 (P3/P4, 14.25) for
    the issue #52 staff-grouping fix: theophany is a mixed chant+SATB booklet;
    its Byzantine-chant troparia pages (single-staff systems) were previously
    fused into phantom multi-staff systems by the removed vertical-gap
    heuristic, undercounting their measures. Splitting them back into the
    single-staff systems actually engraved renumbers the later SATB melisma
    bars downstream (94 -> 116 total measures). The GROW physics is unchanged
    -- the two melismas still normalize to exactly 14.0 and 14.25 beats, only
    their sequential measure index moved. These are hand-verified beat counts,
    not blessable stats (see tests/README.md)."""
    piece_id = "theophany_series1"
    entry = _PIECES[piece_id]
    pdf_path = PDF_DIR / entry["pdf"]
    skip_if_pdf_missing(piece_id, pdf_path)

    _, xml_path, _ = run_pipeline(pdf_path, tmp_path)
    for part_id in ("P1", "P2"):
        beats = _measure_total_beats(xml_path, part_id, "36")
        assert beats == pytest.approx(14.0), (
            f"{piece_id}: part {part_id} measure 36 expected 14.0 beats "
            f"(grown whole rest), got {beats}")
    for part_id in ("P3", "P4"):
        beats = _measure_total_beats(xml_path, part_id, "38")
        assert beats == pytest.approx(14.25), (
            f"{piece_id}: part {part_id} measure 38 expected 14.25 beats "
            f"(grown whole rest), got {beats}")
