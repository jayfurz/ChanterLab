"""Focused regression tests for the three Bortniansky Cherubic No. 7 parser
fixes (2026-07-09). The byte-hash suite in test_regression.py locks the whole
emitted file (bortniansky_cherubic_7 was added there too), but that skips
wherever the copyrighted PDF is absent; these add:

  * pure-logic UNIT tests for the two new decision points (_chord_dots and the
    above-staff rubric guard _looks_syllabified) that run wherever the engine
    imports, no PDF needed; and
  * PDF-gated INTEGRATION tests asserting each fix by name in the emitted
    MusicXML, so a byte change is explained in terms of the behaviour that
    moved, not just a hash mismatch.
"""
from __future__ import annotations

import re
import sys
import types

import pytest

from conftest import OMR_DIR, PDF_DIR, run_pipeline, skip_if_pdf_missing

sys.path.insert(0, str(OMR_DIR))
# importorskip so a machine without PyMuPDF skips (like the PDF-gated tests)
# rather than erroring at collection.
ve = pytest.importorskip("vector_extract")


# --------------------------------------------------------------------------
# Fix 1 — _chord_dots: a chord's per-notehead dots collapse to ONE shared count
# --------------------------------------------------------------------------
def _head(dots, stem2=None):
    # _chord_dots only reads .dots and .stem2
    return types.SimpleNamespace(dots=dots, stem2=stem2)


@pytest.mark.parametrize("per_head, expected", [
    ([2, 0], 1),      # single-dotted 3rd, both dots piled onto the higher head
    ([0, 2], 1),      # piled onto the lower head
    ([1, 1], 1),      # already one-per-head (must stay 1)
    ([2, 2], 2),      # genuinely double-dotted chord
    ([3, 0, 0], 1),   # single-dotted 3-note chord, all dots piled
    ([1, 1, 1], 1),   # correctly attached 3-note chord
])
def test_chord_dots_spreads_piled_dots(per_head, expected):
    assert ve._chord_dots([_head(d) for d in per_head]) == expected


@pytest.mark.parametrize("dots", [0, 1, 2])
def test_chord_dots_single_note_unchanged(dots):
    # a lone note keeps its literal dot count (real double-dots survive)
    assert ve._chord_dots([_head(dots)]) == dots


def test_chord_dots_leaves_dualstem_to_head_dots():
    # dual-stem shared noteheads (issue #69) resolve per voice elsewhere;
    # _chord_dots must NOT spread them (falls back to max when no stem passed).
    heads = [_head(2, stem2=object()), _head(0, stem2=object())]
    assert ve._chord_dots(heads) == 2


# --------------------------------------------------------------------------
# Fix 3 — _looks_syllabified: accept hyphenated lyrics, reject above-staff prose
# --------------------------------------------------------------------------
def _toks(*words):
    return [{"text": w} for w in words]


def test_looks_syllabified_accepts_hyphenated_lyric():
    # "and sing to the life - giv - ing Trin - i - ty,"
    line = _toks("and", "sing", "to", "the", "life", "-", "giv", "-", "ing",
                 "Trin", "-", "i", "-", "ty,")
    assert ve._looks_syllabified(line) is True


@pytest.mark.parametrize("prose", [
    ("Continue", "to", "Only", "Begotten", "Son"),
    ("D.S.", "al", "Coda"),
    ("(When", "one", "priest", "is"),
    ("as", "noted", "next", "page."),
    ("pp",),
    ("and", "sing", "to"),      # 3 words but zero syllable hyphens
])
def test_looks_syllabified_rejects_prose_and_dynamics(prose):
    assert ve._looks_syllabified(_toks(*prose)) is False


# --------------------------------------------------------------------------
# The fixes, asserted by name in the emitted MusicXML (PDF-gated)
# --------------------------------------------------------------------------
PIECE_ID = "bortniansky_cherubic_7"
PIECE_PDF = "13c_cherubic_hymn-bortniansky-7.pdf"


def _soprano_part(xml: str) -> str:
    return xml.split('<part id="P1">', 1)[1].split('<part id="P2">', 1)[0]


def _measure(part: str, n: int) -> str:
    return re.search(rf'<measure number="{n}"[^>]*>(.*?)</measure>', part,
                     re.S).group(1)


@pytest.fixture(scope="module")
def bortniansky_soprano(tmp_path_factory):
    pdf = PDF_DIR / PIECE_PDF
    skip_if_pdf_missing(PIECE_ID, pdf)
    proc, xml_path, _ = run_pipeline(pdf, tmp_path_factory.mktemp("bort"))
    assert xml_path.exists(), f"pipeline produced no output; stderr:\n{proc.stderr}"
    xml = xml_path.read_text(encoding="utf-8")
    return xml, _soprano_part(xml)


def test_bly_chord_is_single_dotted(bortniansky_soprano):
    # m48 Soprano "bly" chord: single-dotted half (dur 12), NOT double (dur 14)
    m48 = _measure(bortniansky_soprano[1], 48)
    assert "<text>bly</text>" in m48
    assert "<dot/><dot/>" not in m48                  # no double-dot
    assert 'duration>12</duration><type>half</type><dot/>' in m48
    assert "<time" not in m48                          # stays 4/4, no invented 9/8


def test_angel_wholenote_is_soprano_voice2(bortniansky_soprano):
    # m51 Soprano: melisma in voice 1 + sustained A4 whole in voice 2 via backup
    m51 = _measure(bortniansky_soprano[1], 51)
    assert "<backup>" in m51 and "<voice>2</voice>" in m51
    assert re.search(r'<step>A</step><octave>4</octave></pitch>'
                     r'<duration>16</duration><voice>2</voice><type>whole</type>',
                     m51), "A4 whole note not emitted as soprano voice 2"


def test_upper_voice_lyrics_captured_above_staff(bortniansky_soprano):
    # the diverging Soprano's own above-staff line, previously dropped
    texts = re.findall(r'<text>([^<]*)</text>', bortniansky_soprano[1])
    seq = " ".join(texts)
    assert "and sing to the" in seq
    assert "life giv ing" in seq


def test_no_double_dots_anywhere(bortniansky_soprano):
    assert "<dot/><dot/>" not in bortniansky_soprano[0]
