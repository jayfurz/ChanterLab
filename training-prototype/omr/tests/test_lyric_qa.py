"""Focused semantic tests for the issue #89 lyric-QA precision work.

The #86 PDF-verified review of the layer-3 ``missing_block`` (interior-gap)
candidates found 29 of the top 30 were QA artifacts -- syllabification
differences, fi/fl ligatures, complete-liturgy section slicing, one-word
insertions/substitutions, word-order variants, and verse-interleaved rep
streams -- not real drops. These tests pin the refined behaviour class by
class on small CONSTRUCTED MusicXML models (public-domain liturgical text,
no corpus material), so they run everywhere, PDF checkout or not:

  * normalization units (_l3_norm ligatures, _l3_words syllable re-joining,
    _l3_word_in elision tolerance);
  * verse-split streams (multi-verse engravings no longer interleave);
  * suppression: syllabification variants, one-word insertion, word-order
    variants, second-half-as-verse-2 engravings, sibling section slices,
    scattered family mismatches (different canonical text in one type key);
  * recall: a genuine interior drop STILL flags (the one confirmed real drop
    of the #86 review -- a short-system sung response absent from the
    MusicXML -- is exactly this shape);
  * determinism of the whole report across runs.
"""
from __future__ import annotations

import json
import sys
from xml.sax.saxutils import escape

from conftest import OMR_DIR

sys.path.insert(0, str(OMR_DIR))

import lyric_qa  # noqa: E402
from lyric_qa import (_l3_blobstream, _l3_consensus, _l3_make_setting,  # noqa: E402
                      _l3_norm, _l3_voice_measure_streams, _l3_word_in,
                      _l3_words)

# --------------------------------------------------------------- fixtures
# Public-domain liturgical text (the Trisagion + lesser doxology wording).
OPEN = "holy god holy mighty holy immortal have mercy on us".split()
MID = "glory be to god who has shown forth the light".split()
CLOSE = "both now and ever and unto ages of ages amen".split()
CANON = OPEN + MID + CLOSE


def _xml(parts):
    """Minimal MusicXML: parts = [(label, {verse_number: [(text, syllabic)|
    text, ...]}), ...]. Tokens of every verse attach to that part's notes in
    order (verse 2 stacks under the same notes, like a real second text line);
    4 quarter notes per measure."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<score-partwise version="3.1">', "<part-list>"]
    for i, (label, _verses) in enumerate(parts, 1):
        out.append(f'<score-part id="P{i}"><part-name>{escape(label)}'
                   f"</part-name></score-part>")
    out.append("</part-list>")
    for i, (_label, verses) in enumerate(parts, 1):
        n_notes = max(len(v) for v in verses.values())
        out.append(f'<part id="P{i}">')
        for m in range((n_notes + 3) // 4):
            out.append(f'<measure number="{m + 1}">')
            for k in range(m * 4, min(m * 4 + 4, n_notes)):
                lyr = ""
                for num, toks in sorted(verses.items()):
                    if k < len(toks):
                        t = toks[k]
                        text, syl = t if isinstance(t, tuple) else (t, "single")
                        lyr += (f'<lyric number="{num}"><syllabic>{syl}'
                                f"</syllabic><text>{escape(text)}</text></lyric>")
                out.append("<note><pitch><step>C</step><octave>4</octave>"
                           "</pitch><duration>4</duration>"
                           f"<type>quarter</type>{lyr}</note>")
            out.append("</measure>")
        out.append("</part>")
    out.append("</score-partwise>")
    return "\n".join(out)


def _run_qa(tmp_path, pieces):
    """pieces = [(pid, parts)] -> full layered report over a tmp manifest."""
    entries = []
    for pid, parts in pieces:
        p = tmp_path / f"{pid}.musicxml"
        p.write_text(_xml(parts), encoding="utf-8")
        entries.append({"id": pid, "title": pid, "musicxml": str(p),
                        "hymnType": "trisagion"})
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps(entries), encoding="utf-8")
    report, _review = lyric_qa.build_report(str(man))
    lyric_qa.attach_layer3(report, str(man))
    return report


def _missing(report, pid):
    return [f for f in report["pieces"].get(pid, {}).get("layer3", [])
            if f["kind"] == "missing_block"]


def _plain(pid, words):
    return (pid, [("S", {1: list(words)})])


# ------------------------------------------------------------ normalization
def test_l3_norm_expands_ligatures_and_strips_punct():
    assert _l3_norm("sacriﬁce.") == "sacrifice"   # fi ligature
    assert _l3_norm("ﬂowing") == "flowing"        # fl ligature
    assert _l3_norm("GOT-") == "got"
    assert _l3_norm("Deacon:") == "deacon"


def test_l3_words_joins_syllabic_runs():
    stream = [(1, "Ho", "begin"), (1, "ly", "end"), (1, "God", "single"),
              (2, "Migh", "begin"), (2, "ty", "end")]
    assert [w for w, _ in _l3_words(stream)] == ["holy", "god", "mighty"]
    # word measure = measure of the FIRST syllable
    assert _l3_words(stream)[2][1] == 2


def test_l3_words_survives_incoherent_markers_and_ellipsis():
    # begin,begin flushes; orphan middle/end kept as own words; a '...'
    # continuation token inside a word is not a boundary
    assert [w for w, _ in _l3_words(
        [(1, "a", "begin"), (1, "b", "begin"), (1, "c", "end")])] == ["a", "bc"]
    assert [w for w, _ in _l3_words([(1, "mor", "middle")])] == ["mor"]
    assert [w for w, _ in _l3_words(
        [(1, "Ho", "begin"), (1, "...", None), (1, "ly", "end")])] == ["holy"]


def test_l3_word_in_tolerates_one_elision():
    blob = "wehavereceivdtheheavnlyspirit"
    assert _l3_word_in(blob, "received")      # receiv'd
    assert _l3_word_in(blob, "heavenly")      # heav'nly
    assert not _l3_word_in(blob, "beheld")
    assert not _l3_word_in("abc", "lift")     # short words: exact only


def test_voice_streams_are_verse_split(tmp_path):
    p = tmp_path / "vs.musicxml"
    p.write_text(_xml([("S", {1: OPEN, 2: MID})]), encoding="utf-8")
    vms = _l3_voice_measure_streams(str(p))
    assert set(vms) == {"P1:S:v1", "P1:S:v2"}
    assert [t for _m, t, _s in vms["P1:S:v1"]] == OPEN
    assert [t for _m, t, _s in vms["P1:S:v2"]] == MID


# ------------------------------------- suppression: the #86 artifact classes
def _syllabify(word, cuts):
    """'immortal', (2, 5) -> ['im', 'mor', 'tal'] as ('single') tokens --
    the detached-syllable engraving (Anaphora-3rd-Mode style) whose syllabic
    markers give NO join information."""
    parts, prev = [], 0
    for c in cuts:
        parts.append(word[prev:c])
        prev = c
    parts.append(word[prev:])
    return [(s, "single") for s in parts]


def test_syllabification_difference_is_not_a_missing_block(tmp_path):
    # one setting splits 'mighty' / 'shown' / 'ages' into detached
    # syllable-'single' tokens; letters are identical -> no flag anywhere
    variant = []
    for w in CANON:
        if w in ("mighty", "shown", "ages"):
            variant.extend(_syllabify(w, (len(w) // 2,)))
        else:
            variant.append(w)
    report = _run_qa(tmp_path, [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON), ("split_setting", [("S", {1: variant})])])
    for pid in ("sib_a", "sib_b", "sib_c", "split_setting"):
        assert _missing(report, pid) == [], pid


def test_one_word_insertion_is_not_a_missing_block(tmp_path):
    ins = CANON.index("immortal")
    variant = CANON[:ins] + ["and"] + CANON[ins:]   # 'holy AND immortal'
    report = _run_qa(tmp_path, [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON), _plain("inserted", variant)])
    assert _missing(report, "inserted") == []


def test_word_order_variant_is_not_a_missing_block(tmp_path):
    i, j = CANON.index("glory"), CANON.index("light") + 1
    reordered = CANON[:i] + CANON[i:j][::-1] + CANON[j:]
    report = _run_qa(tmp_path, [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON), _plain("reordered", reordered)])
    assert _missing(report, "reordered") == []


def test_second_half_as_verse_two_is_not_a_missing_block(tmp_path):
    # the setting engraves OPEN+CLOSE as verse 1 and MID as a second text
    # line under the same notes: the text is all THERE, in another stream
    report = _run_qa(tmp_path, [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON),
        ("stacked", [("S", {1: OPEN + CLOSE, 2: MID})])])
    assert _missing(report, "stacked") == []


# --------------------------------------------- recall: a real drop STILL flags
def test_genuine_interior_drop_is_flagged(tmp_path):
    report = _run_qa(tmp_path, [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON), _plain("dropped", OPEN + CLOSE)])
    flags = _missing(report, "dropped")
    assert flags, "an interior dropped line must survive the FP filters"
    f = flags[0]
    assert "interior gap" in f["reason"]
    assert f["verdict"] == "uncertain"
    # the evidence names words of the dropped line that appear nowhere else
    assert set(f["missing_words"]) & {"shown", "forth", "light", "glory"}
    for pid in ("sib_a", "sib_b", "sib_c"):
        assert _missing(report, pid) == [], pid


# ----------------------------------- unit level: sibling slices + mismatches
def _setting(pid, words, ty="trisagion", piece_blobs=None, section=None):
    stream = [(i // 4 + 1, t, "single") for i, t in enumerate(words)]
    s = _l3_make_setting(pid, pid, section, ty, "ordinary", [stream],
                         piece_blobs=piece_blobs)
    assert s is not None
    return s


def test_passage_in_sibling_slice_is_not_missing():
    # a sliced book's Trisagion section lacks MID -- but the BOOK carries it
    # (in the sibling slice): with piece_blobs the flag is suppressed, and
    # without them the identical evidence still flags (control)
    full_stream = [(i // 4 + 1, t, "single") for i, t in enumerate(CANON)]
    book_blob = _l3_blobstream(full_stream)[0]
    sibs = [_setting(f"sib_{k}", CANON) for k in "abc"]

    flagged = _setting("book", OPEN + CLOSE, piece_blobs=[book_blob],
                       section="Trisagion Hymn")
    findings, _stats, _bytype, mstats = _l3_consensus(sibs + [flagged])
    assert [f for f in findings.get("book", [])
            if f["kind"] == "missing_block"] == []
    assert mstats.get("sibling_slice_present", 0) > 0

    control = _setting("book", OPEN + CLOSE, section="Trisagion Hymn")
    findings, _stats, _bytype, _m = _l3_consensus(sibs + [control])
    assert [f for f in findings.get("book", [])
            if f["kind"] == "missing_block"]


def test_scattered_family_mismatch_is_suppressed():
    # two different canonical texts bridged into one family by a combined
    # book (which interleaves them, ode by ode): the X-only setting "misses"
    # all of Y in dozens of scattered interior runs -- that is a different
    # TEXT, not dropped lines
    xs = [a + b for a in ("za", "ne", "ko", "ri", "mu")
          for b in ("lat", "ver", "dun", "sim", "bor")]
    ys = [a + b for a in ("pel", "tos", "gar", "vin", "hol")
          for b in ("ma", "ne", "ki", "ro", "du")]
    shared = [a + b for a in ("fa", "so", "lu")
              for b in ("men", "dor", "tik", "bel", "nam")]
    x_text, y_text = [], []
    for k in range(25):
        x_text.append(xs[k])
        y_text.append(ys[k])
        if k % 2 == 0:
            x_text.append(shared[(k // 2) % 15])
            y_text.append(shared[(k // 2 + 7) % 15])
    combined = []
    for k in range(0, len(x_text), 6):    # ode-by-ode interleave
        combined.extend(x_text[k:k + 6])
        combined.extend(y_text[k:k + 6])
    x = _setting("x_only", x_text)
    y = _setting("y_only", y_text)
    xy = _setting("combined", combined)
    findings, _stats, _bytype, mstats = _l3_consensus([x, y, xy])
    assert [f for f in findings.get("x_only", [])
            if f["kind"] == "missing_block"] == []
    assert mstats.get("family_mismatch_suppressed", 0) >= 1


# ---------------------------------------------------------------- determinism
def test_report_is_deterministic(tmp_path):
    pieces = [
        _plain("sib_a", CANON), _plain("sib_b", CANON),
        _plain("sib_c", CANON), _plain("dropped", OPEN + CLOSE)]
    a = _run_qa(tmp_path, pieces)
    b = _run_qa(tmp_path, pieces)
    a.pop("generated"), b.pop("generated")
    assert a == b
