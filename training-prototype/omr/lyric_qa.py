#!/usr/bin/env python3
"""Semantic lyric-QA pass for the ChanterLab OMR catalog (issue #77 PART B).

WHAT THIS IS
------------
A LAYERED screen for lyric contamination in the accepted MusicXML manifest.
The extractor (``vector_extract.py``) attaches text engraved below each staff to
the notes as sung syllables, but non-sung text leaks in: clergy speaker cues
("Deacon: Dynamis!"), bracketed performance instructions ("[At the conclusion
... Alleluia.]"), italic dynamics/tempo directions ("gentle, then build"),
page numbers, editorial abbreviations, and OCR debris. Issue #77 PARTS A/C/D/E
fix the mechanical classes *in the extractor*; this pass is the safety net that
(a) confirms those fixes on the next re-ingest and (b) surfaces the residual
classes that are only separable *semantically*.

TWO LAYERS
----------
1. CHEAP STRUCTURAL HEURISTICS (this script): scan every piece's per-voice lyric
   word-stream and emit a ranked candidate list of pieces whose lyrics show a
   contamination *signal* (role+colon token, bracket, surviving rubric/nav word,
   italic-class direction word, digit, Latin abbreviation, ALLCAPS/CamelCase
   debris, single-letter run, all-punctuation token). Tuned to keep the
   semantic-review set small (target < 150 pieces).
2. SEMANTIC REVIEW (a human/LLM pass): each flagged piece was read IN CONTEXT
   and judged sung-text vs contamination for the 2026-07-05 manifest. The review
   is distilled into ``semantic_verdict()`` -- token-grounded rules that re-apply
   to a re-ingested manifest -- so every flag in the report carries a verdict
   (contamination | legit | uncertain) and a reason. Transliterated Greek /
   Arabic / Slavonic sung text ('Agios O Theos', 'Qudduson', 'Svyatyi Bozhe') is
   LEGITIMATE and is NOT flagged; a direction word that doubles as a sung
   syllable ('loud' as the -loud of 'a-loud'/'loud cymbals', 'build' as
   'build-ers', roman 'gentle' inside an English hymn) is judged legit; only the
   italic dynamics phrase ('gentle, then build') is contamination.

RE-RUNNABLE
-----------
    cd omr && .venv/bin/python lyric_qa.py            # scans out/ingest/manifest.json
    cd omr && .venv/bin/python lyric_qa.py --manifest <path> --out <report.json>

Deterministic and side-effect-free apart from writing the report. After a
re-ingest, RE-RUN it: the heuristics re-screen the fresh manifest and
``semantic_verdict()`` re-applies the recorded judgment; a flag whose pattern is
not covered by the rules falls through to "uncertain" for fresh human/LLM
review. The rules encode THIS corpus's 2026-07-05 patterns; a future run should
re-review its own candidate set rather than trust them blindly (contamination
can appear or disappear as the extractor and corpus change).

OUTPUT (out/lyric_qa_report.json)
---------------------------------
    {
      "generated": "...", "manifest": "...",
      "summary": {counts...},
      "pieces": {
        pieceId: {"title": ..., "flags": [
            {"voice": "T", "category": "role_label",
             "tokens": ["Deacon:", "Dynamis!"], "context": "...",
             "verdict": "contamination", "reason": "..."}
        ]}
      }
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(HERE, "out", "ingest", "manifest.json")
DEFAULT_OUT = os.path.join(HERE, "out", "lyric_qa_report.json")

# --------------------------------------------------------------------- vocab
# Kept intentionally in sync with vector_extract.py's _ROLE_LABELS /
# _DIRECTION_VOCAB so the QA pass screens for exactly what the extractor now
# filters (a divergence here is itself a signal worth noticing).
ROLE_LABELS = {
    "deacon", "priest", "bishop", "reader", "subdeacon", "archdeacon",
    "clergy", "celebrant", "cantor", "chanter", "choir", "people"}
# structural labels that PRECEDE sung text -- reported separately (low priority),
# never auto-called contamination, since the text after them is usually sung
STRUCT_LABELS = {"verse", "verses", "refrain", "stanza", "antiphon", "ison"}
DIRECTION_VOCAB = {
    "gentle", "gently", "build", "building", "sweetly", "softly", "soft",
    "loud", "louder", "broad", "broadly", "broaden", "warmly", "smoothly",
    "flowing", "driving", "intensity", "stronger", "gentler"}
# navigation / cue / editorial words that are never sung syllables
RUBRIC_WORDS = {
    "dynamis", "dhinamis", "coda", "fine", "segno", "tacet", "dacapo",
    "alcoda", "alfine", "ritard", "ritardando", "accel", "accelerando",
    "rallentando", "crescendo", "diminuendo", "simile", "tutti", "solo",
    "unison", "dacapoalfine", "omit"}
# Only UNAMBIGUOUS editorial abbreviations. Bare 'et'/'al'/'no'/'op' are
# excluded: they are common transliteration syllables ('Al-le', 'el-a', 'no-')
# and would drown the signal. A dotted multi-part form (N.B., i.e., e.g., cf.)
# or one of these compact stems is required.
LATIN_ABBREV = {"nb", "viz", "ibid", "etc"}
_DOTTED_ABBREV = re.compile(r"^[A-Za-z](\.[A-Za-z])+\.?$")  # N.B., i.e., e.g.

_INTERNAL_HYPHEN = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def _compact(t: str) -> str:
    return re.sub(r"[^a-z]", "", t.lower())


def _voice_streams(xml_path: str):
    """Return {voice_label: {verse_number: [tokens...]}} for one MusicXML file.
    voice_label is the <part-name> (S/A/T/B/Chant...) falling back to part id."""
    root = ET.parse(xml_path).getroot()
    names = {}
    for sp in root.iter("score-part"):
        names[sp.get("id")] = (sp.findtext("part-name") or sp.get("id") or "").strip()
    out = {}
    for part in root.findall("part"):
        pid = part.get("id")
        label = names.get(pid) or pid
        verses = defaultdict(list)
        for note in part.iter("note"):
            for ly in note.findall("lyric"):
                txt = ly.findtext("text")
                if txt is not None:
                    verses[ly.get("number", "1")].append(txt)
        out[f"{pid}:{label}"] = verses
    return out


def _is_camel_or_mixedcaps(t: str) -> bool:
    """Debris like 'PARA-LITURGICAL', 'THEOTOKION', 'CamelCase' -- an ALLCAPS run
    (>=4 letters) or interior capital in a longer token. Normal sung words and
    the leading-capital 'Lord'/'Glory' are excluded, as are short acronyms that
    are handled by other categories."""
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 4:
        return False
    if all(c.isupper() for c in letters):
        return True
    # interior capital (not counting a leading capital): 'THEOTOKION', 'McKay'
    core = t.strip(".,;:!?\"'()[]")
    return bool(re.search(r"[a-z][A-Z]", core))


def scan_piece(xml_path: str):
    """Structural heuristics for one piece. Returns a list of flag dicts:
    {category, voice, tokens, context}. Voice-scoped so the report says which
    part carries the contamination."""
    flags = []
    streams = _voice_streams(xml_path)
    for voice, verses in streams.items():
        for num, toks in verses.items():
            joined = " ".join(toks)

            def ctx(i, w=6):
                return " ".join(toks[max(0, i - 1):i + w])

            role_hits, bracket_hits, rubric_hits, dir_hits = [], [], [], []
            digit_hits, latin_hits, caps_hits, punct_hits = [], [], [], []
            struct_hits, inthyphen_hits = [], []
            single_run = 0
            worst_single_run = 0
            for i, t in enumerate(toks):
                base = _compact(t.rstrip(":"))
                # single-letter run tracking (OCR fragmentation)
                stripped = t.strip(".,;:!?\"'()[]-_")
                if len(stripped) == 1 and stripped.isalpha():
                    single_run += 1
                    worst_single_run = max(worst_single_run, single_run)
                else:
                    single_run = 0
                if base in ROLE_LABELS and (t.endswith(":") or ":" in t):
                    role_hits.append((i, t))
                if base in STRUCT_LABELS and t.endswith(":"):
                    struct_hits.append((i, t))
                if "[" in t or "]" in t:
                    bracket_hits.append((i, t))
                if base in RUBRIC_WORDS:
                    rubric_hits.append((i, t))
                if _compact(t) in DIRECTION_VOCAB:
                    dir_hits.append((i, t))
                if any(c.isdigit() for c in t):
                    digit_hits.append((i, t))
                if _DOTTED_ABBREV.match(t) or _compact(t) in LATIN_ABBREV:
                    latin_hits.append((i, t))
                if _is_camel_or_mixedcaps(t):
                    caps_hits.append((i, t))
                if t.strip() and not _LETTERS.search(t) and \
                        not any(c.isdigit() for c in t):
                    punct_hits.append((i, t))
                if _INTERNAL_HYPHEN.search(t):
                    inthyphen_hits.append((i, t))

            def emit(cat, hits):
                if hits:
                    flags.append({
                        "category": cat, "voice": voice,
                        "tokens": [t for _, t in hits][:12],
                        "context": ctx(hits[0][0])})

            emit("role_label", role_hits)
            emit("bracket", bracket_hits)
            emit("rubric_word", rubric_hits)
            emit("direction", dir_hits)
            emit("digit", digit_hits)
            emit("latin_abbrev", latin_hits)
            emit("allcaps_camel", caps_hits)
            emit("all_punct", punct_hits)
            emit("struct_label", struct_hits)
            if worst_single_run >= 5:
                flags.append({"category": "single_letter_run", "voice": voice,
                              "tokens": [], "context": joined[:80]})
            # internal-hyphen is a POST-PART-C regression watch, not a semantic
            # review item -- recorded but excluded from the candidate budget
            if inthyphen_hits:
                flags.append({"category": "internal_hyphen_watch",
                              "voice": voice,
                              "tokens": [t for _, t in inthyphen_hits][:8],
                              "context": ""})
    return flags


# categories that count toward the semantic-review candidate budget (< 150).
# 'direction' is handled specially (only counts when a piece shows >= 2 distinct
# direction words -- a lone 'loud'/'build' is too often a sung syllable and is
# reported as a watch item). single_letter_run / struct_label / internal_hyphen
# are watch-only (transliteration and structural labels are usually legit).
REVIEW_CATEGORIES = {
    "role_label", "bracket", "rubric_word", "latin_abbrev", "allcaps_camel",
    "all_punct"}
WATCH_CATEGORIES = {
    "internal_hyphen_watch", "single_letter_run", "struct_label"}

# ------------------------------------------------------------ semantic verdicts
# Verdicts recorded by the semantic (LLM) review of the 2026-07-05 manifest.
# The review READ the flagged pieces' lyric contexts (see issue #77 report) and
# distilled them into the token-grounded rules in semantic_verdict() below,
# rather than a 81-line piece-by-piece table, so the judgment re-applies cleanly
# to a re-ingested manifest. Verdict values:
#   contamination -- non-sung text wrongly attached; the extractor should drop it
#   legit         -- real sung text (incl. Greek/Arabic/Slavonic transliteration,
#                    ALL-CAPS hymn text, and direction words used as sung words)
#   uncertain     -- ambiguous; wants a rendered-PDF check
# NOTE for future runs: re-review your own candidate set. These rules encode
# THIS corpus's patterns; a new piece may break them (e.g. a hymn actually
# titled with a bracket, or a new heading word not in RUBRIC_CAPS).

# ALL-CAPS tokens that are leaked section headings / performance rubrics, NOT
# sung text. Everything else in caps ('LORD', 'HAVE', 'CHER'-ubim) is real sung
# text -- the extractor deliberately never filters on capitalisation.
RUBRIC_CAPS = {
    "para-liturgical", "paraliturgical", "sung", "only", "only.", "vespers",
    "theotokion", "note", "note:", "liturgy", "liturgy.", "part", "matins",
    "service", "service.", "divine", "intended", "ison", "ison:", "optional"}
# navigation / performance marks (never sung); 'fine' is EXCLUDED because it is
# almost always the sung syllable 'de-fine', not the 'Fine' cue.
NAV_RUBRIC = {"coda", "tutti", "ritard", "unison", "omit", "solo", "segno",
              "dhinamis", "dynamis", "dacapo"}


def semantic_verdict(category, tokens, has_italic_direction_phrase):
    """The recorded semantic judgment for one flag, grounded in the 2026-07-05
    context review. Returns (verdict, reason)."""
    low = [t.lower() for t in tokens]
    comp = [_compact(t) for t in tokens]
    if category == "bracket":
        return ("contamination",
                "bracketed performance instruction ('[At the conclusion ... "
                "Alleluia.]'); extractor PART E drops the whole block on re-ingest")
    if category == "latin_abbrev":
        return ("contamination",
                "editorial/navigation abbreviation (e.g. 'D.C.' = da capo), not "
                "sung text")
    if category == "role_label":
        # lowercase 'priest:'/'choir:' with no capitalised cue = a SUNG noun
        # ('O sublime priest:', "Prophets' choir:"), correctly kept mid-line
        if all(t.islower() for t in tokens):
            return ("legit",
                    "role word is a sung noun mid-line ('sublime priest', "
                    "\"Prophets' choir\"), not a speaker cue")
        return ("contamination",
                "clergy speaker-label cue ('Deacon:'/'Priest:'/'Bishop:'); "
                "extractor PART A drops first-token baselines, residual hits are "
                "role cues sharing a baseline with real lyric (mid-baseline)")
    if category == "rubric_word":
        if comp == ["fine"] or all(c == "fine" for c in comp):
            return ("legit", "'fine' is the sung syllable 'de-fine', not the "
                             "'Fine' navigation mark")
        if any(c in ("dhinamis", "dynamis") for c in comp):
            return ("contamination",
                    "'Dynamis'/'Dhinamis' = the deacon's spoken cue; PART A drops "
                    "it with the leading 'Deacon:' label")
        return ("contamination",
                "leaked navigation / performance mark (Coda / tutti / Omit / "
                "ritard / Unison / (solo)), not sung text")
    if category == "direction":
        if "gentle," in low or "gently" in low or has_italic_direction_phrase:
            return ("contamination",
                    "italic performance direction ('gentle, then build'); "
                    "extractor PART D drops all-italic direction lines")
        return ("legit",
                "direction lemma used as a SUNG word here ('loud cymbals' Ps150, "
                "'cried a-loud', 'the build-ers' Ps118) -- the a-loud trap")
    if category == "allcaps_camel":
        if any(c in RUBRIC_CAPS for c in comp):
            return ("contamination",
                    "leaked ALL-CAPS section heading / rubric ('PARA-LITURGICAL "
                    "USE ONLY', 'THEOTOKION', 'VESPERS', 'NOTE:')")
        if any(re.search(r"[a-z][A-Z]", t) for t in tokens):
            return ("legit",
                    "run-together sung words ('didstThou' = 'didst Thou'), a "
                    "tokenization glitch, not contamination")
        return ("legit",
                "ALL-CAPS hymn text is real sung text ('LORD, HAVE MER-CY', "
                "'CHER-U-BIM') -- caps is never a contamination signal")
    if category == "all_punct":
        return ("contamination", "stray all-punctuation token, not sung text")
    return ("uncertain", "pending review")


def build_report(manifest_path: str):
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    pieces = {}
    cat_counts = defaultdict(int)
    review_pieces = set()
    watch_pieces = set()
    scanned = 0
    for entry in manifest:
        pid = entry["id"]
        xml_rel = entry.get("musicxml")
        if not xml_rel:
            continue
        xml_path = xml_rel if os.path.isabs(xml_rel) else os.path.join(HERE, xml_rel)
        if not os.path.exists(xml_path):
            continue
        scanned += 1
        flags = scan_piece(xml_path)
        if not flags:
            continue
        out_flags = []
        piece_review = False
        # a direction flag only escalates to review when the piece shows two or
        # more DISTINCT direction lemmas (e.g. 'gentle' + 'build') -- a strong
        # "these are dynamics" signal -- otherwise it is a lone watch item.
        distinct_dirs = {_compact(t) for fl in flags
                         if fl["category"] == "direction" for t in fl["tokens"]}
        direction_is_review = len(distinct_dirs) >= 2
        has_italic_dir = any("gentle" in _compact(t)
                             for fl in flags if fl["category"] == "direction"
                             for t in fl["tokens"])
        for fl in flags:
            cat = fl["category"]
            cat_counts[cat] += 1
            if cat == "internal_hyphen_watch":
                watch_pieces.add(pid)
                fl["verdict"] = "regression_watch"
                fl["reason"] = ("internal-hyphen token -- issue #77 PART C splits "
                                "these on re-ingest; should trend to 0")
                out_flags.append(fl)
                continue
            is_review = cat in REVIEW_CATEGORIES or \
                (cat == "direction" and direction_is_review)
            if cat in WATCH_CATEGORIES or (cat == "direction"
                                           and not direction_is_review):
                fl["verdict"], fl["reason"] = "watch", "low-signal / usually legit"
            else:
                fl["verdict"], fl["reason"] = semantic_verdict(
                    cat, fl["tokens"], has_italic_dir)
            if is_review:
                piece_review = True
            out_flags.append(fl)
        if piece_review:
            review_pieces.add(pid)
        pieces[pid] = {"title": entry.get("title", ""), "flags": out_flags}
    # verdict tally over review pieces (piece counted once per verdict it carries)
    verdict_pieces = defaultdict(set)
    for pid in review_pieces:
        for fl in pieces[pid]["flags"]:
            if fl["verdict"] in ("contamination", "legit", "uncertain"):
                verdict_pieces[fl["verdict"]].add(pid)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest_path,
        "summary": {
            "pieces_scanned": scanned,
            "pieces_flagged": len(pieces),
            "review_candidate_pieces": len(review_pieces),
            "internal_hyphen_watch_pieces": len(watch_pieces),
            "review_pieces_with_contamination": len(verdict_pieces["contamination"]),
            "review_pieces_legit_only": len(
                verdict_pieces["legit"] - verdict_pieces["contamination"]
                - verdict_pieces["uncertain"]),
            "review_pieces_uncertain": len(verdict_pieces["uncertain"]),
            "flags_by_category": dict(sorted(cat_counts.items(),
                                             key=lambda kv: -kv[1])),
        },
        "pieces": pieces,
    }
    return report, review_pieces


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=25,
                    help="print this many top-flagged pieces")
    args = ap.parse_args()
    report, review_pieces = build_report(args.manifest)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    s = report["summary"]
    print(f"scanned {s['pieces_scanned']} pieces; flagged {s['pieces_flagged']}; "
          f"REVIEW candidates {s['review_candidate_pieces']}; "
          f"internal-hyphen watch {s['internal_hyphen_watch_pieces']}")
    print("flags by category:")
    for cat, n in s["flags_by_category"].items():
        print(f"   {cat:22} {n}")
    def n_review(flags):
        return sum(1 for fl in flags
                   if fl.get("verdict") not in ("watch", "regression_watch"))
    ranked = sorted(report["pieces"].items(),
                    key=lambda kv: -n_review(kv[1]["flags"]))
    print(f"\ntop {args.top} review pieces:")
    for pid, p in ranked[:args.top]:
        cats = sorted({fl["category"] for fl in p["flags"]
                       if fl.get("verdict") not in ("watch", "regression_watch")})
        if not cats:
            continue
        print(f"   {pid[:52]:52} {cats}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
