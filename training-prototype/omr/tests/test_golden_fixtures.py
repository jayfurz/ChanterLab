"""TRUST-03 rights-safe semantic fixtures and private-fixture registry."""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import fitz
import pytest

from conftest import OMR_DIR, PDF_DIR, run_pipeline

import sys
sys.path.insert(0, str(OMR_DIR))
import vector_extract as ve


REGISTRY_PATH = Path(__file__).with_name("golden_fixtures.json")
EXPECTATIONS_PATH = Path(__file__).with_name("expectations.json")


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


PRIVATE_CASES = _registry()["private"]


def _glyph(x, y):
    return ve.Glyph(0xE0A4, x, y, x - 2, y - 2, x + 2, y + 2, 12)


def _head(step, *, acc=None, x=10, y=20):
    return ve.Head(_glyph(x, y), "black", 1.0, step=step, acc=acc)


def test_registry_is_complete_rights_safe_and_source_bound():
    registry = _registry()
    expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    public_features = {f for case in registry["public"] for f in case["features"]}
    all_features = public_features | {
        f for case in registry["private"] for f in case["features"]
    }

    assert registry["schema_version"] == 1
    assert set(registry["required_features"]) == all_features
    assert set(registry["required_features"]) - public_features == \
        set(registry["private_only_features"])
    assert {case["id"] for case in registry["private"]} == set(expectations["pieces"])
    for case in registry["public"]:
        assert case["why"] and case["test"].startswith("test_golden_fixtures.py::")
    for case in registry["private"]:
        assert case["why"]
        assert re.fullmatch(r"[0-9a-f]{64}", case["source_sha256"])
        assert Path(case["pdf"]).name == case["pdf"]
        assert not (Path(__file__).parent / case["pdf"]).exists()


@pytest.mark.parametrize("case", PRIVATE_CASES, ids=lambda case: case["id"])
def test_private_source_hash(case):
    path = PDF_DIR / case["pdf"]
    if not path.exists():
        pytest.skip(f"private golden source unavailable: {case['pdf']}")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["source_sha256"]


def test_staff_and_font_routing():
    assert ve._music_font_family("Finale Maestro SMuFL") == "smufl"
    assert ve._music_font_family("FinaleMaestro") == "smufl"
    assert ve._music_font_family("Maestro") == "finale"
    assert ve._music_font_family("Times New Roman") is None

    staves = [ve.Staff(i * 20, i * 20 + 8, 0, 100, []) for i in range(4)]
    one = ve.System(staves[:1], 1, layout="1staff")
    two = ve.System(staves[:2], 1, layout="2staff")
    four = ve.System(staves, 1, layout="4staff")
    assert list(ve._staff_voices(one).values()) == [("S",)]
    assert list(ve._staff_voices(two).values()) == [("S", "A"), ("T", "B")]
    assert list(ve._staff_voices(four).values()) == [("S",), ("A",), ("T",), ("B",)]


def test_constructed_musicxml_semantics():
    flag_staff = ve.Staff(0, 40, 0, 100, [])
    flag_head = _head(35, y=20)
    flag_head.staff = flag_staff
    flag_stem = ve.Stem(10, 5, 22, heads=[flag_head], flag=(1, None))
    flag_head.stem = flag_stem
    flag_system = ve.System([flag_staff], 1, layout="1staff")
    ve._build_system_events(flag_system, [flag_head], [flag_stem], [],
                            ve.Report(), 1)
    assert flag_system.events["S"][0].beats == .5

    chord = ve.Event(10, "note", [_head(35, acc=1), _head(37)], beats=1,
                     dots=1, stem_dir="up", beam_group=1, nbeams=1,
                     tie_start=True,
                     lyric=[{"number": 1, "syllabic": "begin", "text": "A"},
                            {"number": 2, "syllabic": "single", "text": "O"}])
    tied = ve.Event(20, "note", [_head(35, x=20)], beats=.5,
                    stem_dir="up", beam_group=1, nbeams=1, tie_stop=True)
    beamed = ve.Event(30, "note", [_head(36, x=30)], beats=.5,
                      stem_dir="up", beam_group=1, nbeams=1)
    rest = ve.Event(40, "rest", beats=1)
    divisi = ve.Event(12, "note", [_head(34, x=12)], beats=4, divisi=True)
    score = {v: [[chord, tied, beamed, rest] if v == "S" else [ve.Event(10, "rest", beats=3)]]
             for v in ve.VOICE_ORDER}
    result = {
        "title": "Rights-safe semantic fixture",
        "voices": list(ve.VOICE_ORDER),
        "score": score,
        "divisi": {"S": [[divisi]], "A": [[]], "T": [[]], "B": [[]]},
        "meta": [{"sums": {v: sum(e.total_beats for e in score[v][0]) for v in ve.VOICE_ORDER},
                  "x_range": (0, 100), "sp": 5, "key": 1,
                  "new_system": True, "tempo": None}],
        "sections": [{"measure": 1, "title": "Section One"}],
    }
    root = ET.fromstring(ve.emit_musicxml(result))
    assert len(root.findall("./part-list/score-part")) == 4
    soprano = root.find("./part[@id='P1']/measure")
    assert soprano is not None
    notes = soprano.findall("note")
    assert notes[0].find("chord") is None and notes[1].find("chord") is not None
    assert notes[0].find("dot") is not None
    assert notes[0].find("accidental").text == "sharp"
    assert notes[0].find("tie[@type='start']") is not None
    assert notes[2].find("tie[@type='stop']") is not None
    assert [x.text for x in notes[0].findall("lyric/text")] == ["A", "O"]
    assert soprano.find("backup") is not None
    assert soprano.find("note/voice").text == "1"
    assert soprano.find("note[voice='2']") is not None
    assert soprano.find("direction/direction-type/words").text == "Section One"
    assert soprano.find("note/beam[@number='1']") is not None
    assert any(n.find("rest") is not None for n in notes)


def test_lyric_semantics():
    lyric = [{"text": x} for x in ("and", "sing", "life-giv-ing", "Trin-i-ty")]
    rubric = [{"text": x} for x in ("D.S.", "al", "Coda")]
    assert ve._looks_syllabified(lyric)
    assert not ve._looks_syllabified(rubric)
    assert ve._syl(False, True) == "begin"
    assert ve._syl(True, True) == "middle"
    assert ve._syl(True, False) == "end"


def test_generated_nonmusic_pdf_is_refused(tmp_path):
    for name, prose in (("blank", None), ("prose", "This is not a musical score.")):
        pdf = tmp_path / f"{name}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        if prose:
            page.insert_text((72, 72), prose)
        doc.save(pdf)
        doc.close()
        proc, xml_path, report_path = run_pipeline(pdf, tmp_path / name)
        assert proc.returncode == 3
        assert "no born-digital Western staff notation found" in proc.stderr
        assert not xml_path.exists()
        assert not report_path.exists()


def test_short_staff_recovery_constructed():
    """Issue #88: 5-line groups the full-width filter rejects are recovered
    when (and only when) they look like a staff AND carry music. Locks:

      * classic full-width detection is untouched (strictly additive pass);
      * a narrow aligned 5-line group with a notehead is recovered (the
        short single-staff sung-response systems, 373 corpus pieces);
      * a staff whose lines are drawn as two abutting segments is joined
        and recovered;
      * ragged-end line stacks (text rules / melisma extenders) and aligned
        stacks with NO notehead near them never fabricate a staff.
    """
    rep = ve.Report()
    long_h = []
    for k in range(5):                            # full-width staff (w=500)
        long_h.append((50.0, 550.0, 100.0 + 5 * k))
    for k in range(5):                            # short response staff
        long_h.append((50.0, 250.0, 200.0 + 5 * k))
    for k in range(5):                            # ragged right ends
        long_h.append((50.0, 250.0 - 12 * k, 300.0 + 5 * k))
    for k in range(5):                            # aligned but note-less
        long_h.append((50.0, 250.0, 400.0 + 5 * k))
    for k in range(5):                            # two abutting segments
        long_h.append((50.0, 150.0, 500.0 + 5 * k))
        long_h.append((152.0, 250.0, 500.0 + 5 * k))
    music = [_glyph(150, 210), _glyph(150, 310), _glyph(150, 510)]

    staves = ve._find_staves(long_h, 1, rep, music)

    assert sorted(s.top for s in staves) == [100.0, 200.0, 500.0]
    assert rep.stats["short_staves_recovered"] == 2
    seg = next(s for s in staves if s.top == 500.0)
    assert seg.x0 == 50.0 and seg.x1 == 250.0     # segments joined
    full = next(s for s in staves if s.top == 100.0)
    assert full.x1 == 550.0                       # classic pass untouched


def test_anaphora_short_system_responses_recovered(tmp_path):
    """Issue #88 exemplar (private, PDF-gated): the sung responses engraved
    as narrow single-staff systems — 'And with thy spir-it.' (system 4) and
    'It is meet and right.' (system 6) — must reach the MusicXML. Before the
    recovery pass every line of those systems failed the width filter and
    26 noteheads were dropped 'not near any staff'."""
    pdf = PDF_DIR / "Anaphora-3rd-Mode-FJ-WNBN.pdf"
    if not pdf.exists():
        pytest.skip("private golden source unavailable: "
                    "Anaphora-3rd-Mode-FJ-WNBN.pdf (copyrighted, local-only)")
    proc, xml_path, report_path = run_pipeline(pdf, tmp_path)
    assert proc.returncode == 0
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    assert rep["stats"].get("short_staves_recovered", 0) >= 4
    assert not [w for w in rep.get("warnings", [])
                if "not near any staff" in str(w)]
    text = " ".join(t.text or "" for t in
                    ET.parse(xml_path).getroot().iter("text"))
    joined = " ".join(text.split())
    assert "And with thy spir it." in joined
    assert "It is meet and right." in joined
