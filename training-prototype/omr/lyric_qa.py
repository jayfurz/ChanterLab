#!/usr/bin/env python3
"""Layered lyric-QA pass for the ChanterLab OMR catalog (issues #77 + #78).

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
classes that are only separable *semantically* or *by consensus*.

THREE LAYERS
------------
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
3. CONSENSUS (categorical) REVIEW  --  issue #78, the ``layer3`` block below.
   Layers 1-2 read each piece in isolation; they cannot see a leak that *looks*
   like a plausible sung word, nor a *dropped* line (absence has no token to
   flag). The owner's insight: hymns of the same liturgical TYPE are settings of
   the SAME canonical text -- there are only so many hymn types, so settings of a
   type validate each other. Layer 3:
     (a) TYPE-CLUSTERS every accepted piece by hymn type (curated regexes for the
         fixed-text Ordinary hymns -- Trisagion, Cherubic, Anaphora, "It is truly
         meet", Great Litany, Dismissal ... -- plus base-type + liturgical-date
         feast keys for the Propers; complete-liturgy books are SLICED into
         per-section settings via their report.json ``sections[]`` measure marks
         so each book contributes a Trisagion setting, an Anaphora setting, ...).
     (b) splits each type into TRANSLATION FAMILIES by normalized token-set
         Jaccard (cheap, interpretable, robust to syllabification; chosen over
         char-n-gram cosine because it draws the English/Greek/Arabic/Slavonic
         and the different-canonical-text boundaries cleanly). This is what keeps
         the 4 languages of the Trisagion, and the three different texts that all
         title-match "Cherubic Hymn", in SEPARATE consensuses instead of
         cross-flagging. Singleton families ("this type's only Arabic setting")
         are marked ``no-family-consensus`` -- vocabulary-checked against nothing,
         never fake-flagged.
     (c) runs CONSENSUS CHECKS per family (>=3 settings): alien DEBRIS tokens (a
         contamination-shaped token carried by a MINORITY of the family), alien
         VOCABULARY (a distinctive word present in one setting but no sibling),
         and MISSING-TEXT (a stream far shorter than the family median, or missing
         a family-shared n-gram block -- the dropped-line signal nothing else can
         see). Transliteration and words shared across the type's other families
         are recognized as legit; consensus flags are arbitrated exactly as layer
         2 arbitrated heuristics -> contamination | legit-variant | uncertain.
   Layer 3 re-discovers layer-1/2 contamination *independently* where the type has
   a family (validation), and finds NEW contamination (a leaked style/editorial
   word or a colon-less clergy cue that layer-2's narrow vocab missed) and NEW
   missing-text that no single-piece pass could ever see.

RE-RUNNABLE
-----------
    cd omr && .venv/bin/python lyric_qa.py            # scans out/ingest/manifest.json
    cd omr && .venv/bin/python lyric_qa.py --manifest <path> --out <report.json>
    cd omr && .venv/bin/python lyric_qa.py --no-layer3 # layers 1-2 only

Deterministic and side-effect-free apart from writing the report. After a
re-ingest, RE-RUN it: the heuristics re-screen the fresh manifest,
``semantic_verdict()`` re-applies the recorded layer-2 judgment, and layer 3
re-clusters the fresh streams from scratch (it holds no per-piece table -- it
recomputes families and consensus each run, so it self-heals as the corpus and
extractor change). Rules that reference specific tokens encode THIS corpus's
2026-07-05 patterns; a future run should re-review its own candidate set rather
than trust them blindly.

OUTPUT (out/lyric_qa_report.json)
---------------------------------
    {
      "generated": "...", "manifest": "...",
      "summary": {counts...},
      "pieces": {
        pieceId: {"title": ..., "flags": [
            {"voice": "T", "category": "role_label",
             "tokens": ["Deacon:", "Dynamis!"], "context": "...",
             "verdict": "contamination", "reason": "..."}],
          "layer3": [
            {"kind": "alien_debris", "type": "trisagion", "section": null,
             "family_size": 33, "token": "Omit", "shape": "nav_rubric",
             "minority": "2/33", "verdict": "contamination", "reason": "...",
             "context": "...", "siblings": ["...", "..."]}]}
      },
      "layer3": {"clusters": {...}, "families": {...}, "validation": {...},
                 "ranked": [...]}
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
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


# =====================================================================
# LAYER 3 -- CONSENSUS (categorical) REVIEW  (issue #78)
# =====================================================================
# Settings of the same hymn TYPE are settings of the same canonical text; within
# a type, TRANSLATION FAMILIES (English / Greek / Arabic / Slavonic, and distinct
# canonical texts that share a title) are separated by lyric-stream Jaccard, and
# each family's settings vote on what belongs. Everything here recomputes from the
# fresh manifest on every run -- there is no per-piece table to go stale.

_L3_PUNCT = " .,;:!?\"'()[]{}-_–—‘’“”·"


def _l3_norm(t: str) -> str:
    """Common-denominator token for family clustering / vocabulary voting: strip
    surrounding punctuation and lowercase. (Deliberately DESTROYS the debris shape
    -- '[At'->'at', 'Deacon:'->'deacon' -- so debris is detected on RAW tokens.)"""
    return t.strip(_L3_PUNCT).lower().replace("’", "'")


def _l3_is_content(n: str) -> bool:
    return bool(n) and not n.isdigit()


# --- hymn-type assignment -------------------------------------------------
# ORDINARY: the fixed-text hymns of the services -- same words every time, so they
# cluster by TYPE alone (no feast needed). Ordered; first match wins.
_L3_ORDINARY = [
    ("trisagion", r"trisagion|thrice[\s-]*holy|holy god,?\s*holy might"),
    ("cherubic_hymn", r"cherubic|cherubikon|let us who mystic|we who mystic"),
    ("receive_me_communion", r"receive me,? o|receive me today"),
    ("let_all_mortal_flesh", r"let all mortal flesh"),
    ("anaphora", r"anaphora|mercy of peace|it is meet and right|"
                 r"holy,? holy,? holy|hymn of victory|we praise thee"),
    ("only_begotten", r"only[\s-]*begotten"),
    ("creed", r"\bcreed\b|symbol of faith|i believe in one god"),
    ("lords_prayer", r"lord'?s prayer|our father"),
    ("great_litany", r"great litany|litany of peace"),
    ("little_litany", r"little litany"),
    ("augmented_litany", r"augmented litany|fervent supplic"),
    ("entrance_hymn", r"entrance hymn|come,? let us worship"),
    ("communion_praise", r"praise the lord from the heavens|communion hymn|"
                         r"receive the body"),
    ("gladsome_light", r"gladsome light|o gladsome|phos hilaron"),
    ("preserve_o_lord", r"preserve,?\s*o lord|ton despot|ton dhespot"),
    ("many_years", r"many years|is polla|eis polla"),
    ("it_is_truly_meet", r"it is truly meet|axion estin"),
    ("great_doxology", r"great doxolog|glory to god in the highest"),
    ("dismissal", r"\bdismissal\b"),
    ("we_have_seen_the_true_light", r"we have seen the true light"),
    ("let_our_mouths", r"let our mouths be filled"),
    ("blessed_be_the_name", r"blessed be the name of the lord"),
    ("magnification", r"more honorable than the cherub|magnificat|megalynarion"),
]
# PROPER: text varies per feast/saint, so the TYPE key carries a feast key
# (liturgical date) -- same base type + same date = same canonical text.
_L3_PROPER = [
    ("apolytikion", r"apolytik|troparion"), ("kontakion", r"kontakion"),
    ("aposticha", r"apostich"), ("stichera", r"sticher|idiomelon"),
    ("theotokion", r"theotokion|stavrotheotok"), ("exapostilarion", r"exapost|photagog"),
    ("kathisma", r"kathisma|sessional"), ("prokeimenon", r"prokeimenon"),
    ("katavasia", r"katavasi"), ("ode", r"\bode\b|canon"),
    ("doxastikon", r"doxastikon|eothin"), ("megalynarion", r"megalynarion"),
    ("antiphon", r"antiphon"),
]
_L3_ORD_RE = [(n, re.compile(p, re.I)) for n, p in _L3_ORDINARY]
_L3_PROP_RE = [(n, re.compile(p, re.I)) for n, p in _L3_PROPER]


def _l3_feast_key(litdate, sub):
    fk = re.sub(r"[^a-z0-9]+", " ", (litdate or sub or "").lower()).strip()
    return fk[:60]


def _l3_hymn_type(text, litdate, sub):
    """(type_id, kind) for a title or section-title. Ordinary -> type-only;
    Proper -> base|feast; else None."""
    for name, rx in _L3_ORD_RE:
        if rx.search(text or ""):
            return name, "ordinary"
    for name, rx in _L3_PROP_RE:
        if rx.search(text or ""):
            return f"{name}|{_l3_feast_key(litdate, sub)}", "proper"
    return None, None


def _l3_voice_measure_streams(xml_path):
    """{voice: [(measure_number, token), ...]} for measure-range section slicing."""
    root = ET.parse(xml_path).getroot()
    names = {}
    for sp in root.iter("score-part"):
        names[sp.get("id")] = (sp.findtext("part-name") or sp.get("id") or "").strip()
    out = {}
    for part in root.findall("part"):
        pid = part.get("id")
        seq = []
        cur = 0
        for mm in part.findall("measure"):
            try:
                cur = int(mm.get("number"))
            except (TypeError, ValueError):
                pass
            for note in mm.iter("note"):
                for ly in note.findall("lyric"):
                    txt = ly.findtext("text")
                    if txt is not None:
                        seq.append((cur, txt))
        out[f"{pid}:{names.get(pid) or pid}"] = seq
    return out


def _l3_load_sections(pid):
    rp = os.path.join(HERE, "out", "ingest", pid + ".report.json")
    if not os.path.exists(rp):
        return []
    try:
        with open(rp, encoding="utf-8") as f:
            return json.load(f).get("sections") or []
    except (json.JSONDecodeError, OSError):
        return []


def _l3_make_setting(pid, title, section, ty, kind, voice_slices):
    """A consensus unit. rep = longest single voice (for length / n-grams);
    allnorm / allraw = union over ALL voices (contamination can sit in one voice
    only, so debris + vocabulary are scanned across every part)."""
    rep = max(voice_slices, key=len) if voice_slices else []
    allraw, allnorm = [], set()
    for vs in voice_slices:
        allraw.extend(vs)
        for t in vs:
            n = _l3_norm(t)
            if _l3_is_content(n):
                allnorm.add(n)
    repnorm = [n for n in (_l3_norm(t) for t in rep) if _l3_is_content(n)]
    if len(repnorm) < 4:
        return None
    return {"pid": pid, "title": title, "section": section, "type": ty,
            "kind": kind, "rep": rep, "allraw": allraw, "repnorm": repnorm,
            "normset": set(repnorm), "allnorm": allnorm}


def _l3_build_settings(manifest):
    """One setting per single-type piece; for complete-liturgy books (>=2 sections
    that map to a known type) one setting per mapped section, sliced by measure."""
    settings = []
    sec_derived = 0
    for entry in manifest:
        pid = entry["id"]
        xml_rel = entry.get("musicxml")
        if not xml_rel:
            continue
        xml = xml_rel if os.path.isabs(xml_rel) else os.path.join(HERE, xml_rel)
        if not os.path.exists(xml):
            continue
        vms = _l3_voice_measure_streams(xml)
        litdate, sub = entry.get("liturgicalDate"), entry.get("sub")
        title = entry.get("title", "")
        mapped = []
        for s in _l3_load_sections(pid):
            st = s.get("title", "")
            ty, kind = _l3_hymn_type(st, litdate, sub)
            if ty is None:
                # recurring section fallback: a clean multi-word heading becomes
                # its own type so identical section titles cluster across books
                key = re.sub(r"[^a-z0-9]+", " ", st.lower()).strip()
                if 8 <= len(key) <= 45 and " " in key and not re.search(r"\d{2,}", key):
                    ty, kind = f"section|{key}", "section"
            mapped.append((s.get("measure", 1), st, ty, kind))
        if sum(1 for m in mapped if m[2]) >= 2:  # complete-liturgy: slice sections
            for j, (meas, st, ty, kind) in enumerate(mapped):
                if not ty:
                    continue
                hi = mapped[j + 1][0] if j + 1 < len(mapped) else 10 ** 9
                vslices = [[t for (mn, t) in seq if meas <= mn < hi]
                           for seq in vms.values()]
                setting = _l3_make_setting(pid, title, st, ty, kind, vslices)
                if setting:
                    settings.append(setting)
                    sec_derived += 1
        else:  # single-type piece: one whole-piece setting
            ty, kind = _l3_hymn_type(title, litdate, sub)
            if ty is None:
                continue
            vslices = [[t for (_, t) in seq] for seq in vms.values()]
            setting = _l3_make_setting(pid, title, None, ty, kind, vslices)
            if setting:
                settings.append(setting)
    return settings, sec_derived


def _l3_jaccard(a, b):
    if not a or not b:
        return 0.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def _l3_families(group, thr=0.5):
    """Connected components of the >=thr Jaccard graph over a type's settings.
    thr=0.5 keeps same-text/same-language settings together while splitting the
    languages and the distinct-canonical-text variants that share a title."""
    n = len(group)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _l3_jaccard(group[i]["normset"], group[j]["normset"]) >= thr:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    comp = defaultdict(list)
    for i in range(n):
        comp[find(i)].append(group[i])
    return list(comp.values())


# --- consensus vocabularies (grounded in the 2026-07-05 corpus review) --------
# Transliterated sung text -- LEGIT even when it is a family singleton.
_L3_TRANSLIT = {
    "agios", "agyos", "theos", "athanatos", "ischyros", "eleison", "kyrie", "doxa",
    "qudduson", "lah", "allah", "qawi", "irhamna", "irham", "illah", "dhi", "ilah",
    "svyatyi", "svyati", "bozhe", "krepkiy", "bessmertniy", "pomiluy", "gospodi",
    "slava", "ton", "dhespotin", "despotin", "polla", "eti", "chronia", "axion",
    "estin", "sabihu", "raba", "allilouia", "alliluia"}
# Extra never-sung words layer-2's vocab does NOT carry: chant-style names and
# editorial / attribution words. When one of these is ALIEN to a family it is a
# leak layer-2 could not catch -> NEW consensus contamination.
_L3_STYLE_EDITORIAL = {
    "starorussky", "znamenny", "kievan", "valaam", "obikhod", "bulgarian",
    "serbian", "galician", "carpatho", "prostopinije", "archpriest", "subdeacon",
    "celebrant", "protodeacon", "gradual", "alternate", "arranged", "adapted",
    "transcribed", "harmonized", "weekdays", "sundays", "melody", "descant",
    "rallentando", "accelerando"}
# nav / performance marks (never sung); 'fine' excluded ('de-fine' syllable).
_L3_NAV = {c for c in RUBRIC_WORDS if c != "fine"} | {
    "coda", "omit", "tutti", "solo", "unison", "ritard", "segno", "dacapo"}
# ALL-CAPS words that are leaked headings, not sung text.
_L3_RUBRIC_CAPS = RUBRIC_CAPS | {"para", "liturgical", "not", "use", "vesper"}


def _l3_debris(raw_list):
    """(shape, wordkey, raw, i) for contamination-shaped RAW tokens in a stream.
    Bracket presence is collapsed to a single 'bracket_span' key."""
    out = []
    has_bracket = False
    for i, raw in enumerate(raw_list):
        low = raw.lower()
        base = re.sub(r"[^a-z]", "", low.rstrip(":"))
        if ("[" in raw) or ("]" in raw):
            has_bracket = True
            continue
        if base in ROLE_LABELS and raw.rstrip().endswith(":"):
            out.append(("role_label", base, raw, i))
        elif base in _L3_NAV:
            out.append(("nav_rubric", base, raw, i))
        elif _DOTTED_ABBREV.match(low) or base in LATIN_ABBREV:
            out.append(("latin_abbrev", base, raw, i))
        else:
            letters = [c for c in raw if c.isalpha()]
            if len(letters) >= 4 and all(c.isupper() for c in letters) \
                    and base in _L3_RUBRIC_CAPS:
                out.append(("allcaps_rubric", base, raw, i))
    if has_bracket:
        out.append(("bracket", "bracket_span", "[...]", -1))
    return out


def _l3_ctx(raw_list, i, w=5):
    if i < 0:  # bracket span
        for j, t in enumerate(raw_list):
            if "[" in t:
                return " ".join(raw_list[j:j + 8])
        return ""
    return " ".join(raw_list[max(0, i - 2):i + w])


def _l3_arbitrate_alien(word, in_other_family):
    """Verdict for a vocabulary token alien to its family (shape-neutral word)."""
    if word in ROLE_LABELS or word in _L3_STYLE_EDITORIAL:
        return ("contamination",
                f"'{word}' present in this setting but no family sibling, and it is "
                f"a clergy/style/editorial word never sung here -- a leak layer-2's "
                f"vocabulary did not carry (NEW consensus find)", "vocab")
    if word in _L3_TRANSLIT or in_other_family:
        return ("legit-variant",
                f"'{word}' is absent from this family but is legitimate sung text "
                f"elsewhere in the type -- a transliteration / translation variant, "
                f"not contamination", "translit")
    if len(word) >= 4 and word.isalpha():
        return ("uncertain",
                f"distinctive word '{word}' in this setting but no family sibling -- "
                f"a translation choice, an added phrase, or a lyric/OCR error", "novel")
    return None


def _l3_consensus(settings):
    """Run the consensus checks. Returns (findings_by_pid, cluster_stats)."""
    bytype = defaultdict(list)
    for s in settings:
        bytype[s["type"]].append(s)
    type_vocab = defaultdict(Counter)  # token -> #settings-of-type containing it
    for s in settings:
        for n in s["allnorm"]:
            type_vocab[s["type"]][n] += 1

    all_families = []
    for t, group in bytype.items():
        if len(group) < 3:  # a type needs >=3 settings for any consensus
            all_families.append((t, group, "small_type"))
            continue
        for fam in _l3_families(group):
            tag = "consensus" if len(fam) >= 3 else (
                "family_size_2" if len(fam) == 2 else "no_family_consensus")
            all_families.append((t, fam, tag))

    findings = defaultdict(list)
    fam_sizes = Counter()
    for t, fam, tag in all_families:
        fam_sizes[tag] += 1
        if tag != "consensus":
            continue
        fs = len(fam)
        mem_debris = [_l3_debris(s["allraw"]) for s in fam]
        carry = Counter()
        for md in mem_debris:
            for wk in {d[1] for d in md}:
                carry[wk] += 1
        # shared long passages: 4-grams present in >=70% of the family, with their
        # median position (fraction of stream length) across the settings that have
        # them -- so a MISSING passage can be classed as an interior gap vs a
        # truncation.
        K = 4
        ngm = defaultdict(set)
        ngm_pos = defaultdict(list)
        for idx, s in enumerate(fam):
            nl = s["repnorm"]
            L = max(1, len(nl))
            seen_g = set()
            for i in range(len(nl) - K + 1):
                g = tuple(nl[i:i + K])
                ngm[g].add(idx)
                if g not in seen_g:
                    seen_g.add(g)
                    ngm_pos[g].append(i / L)
        need = max(2, int(0.7 * fs + 0.5))
        shared = {g: ms for g, ms in ngm.items() if len(ms) >= need}
        block_order = {}
        if shared:
            order_sorted = sorted(
                shared, key=lambda g: sorted(ngm_pos[g])[len(ngm_pos[g]) // 2])
            block_order = {g: i for i, g in enumerate(order_sorted)}
        for idx, s in enumerate(fam):
            sib_union = set().union(*[fam[j]["allnorm"]
                                      for j in range(fs) if j != idx])
            siblings = [" ".join(fam[j]["rep"][:7]) for j in range(fs)
                        if j != idx][:3]
            base = {"type": t, "section": s["section"], "family_size": fs}
            # (a) alien DEBRIS carried by a minority of the family
            # (one finding per distinct debris wordkey; keep first raw surface)
            seen_wk = {}
            for d in mem_debris[idx]:
                seen_wk.setdefault(d[1], d)
            for shape, wk, raw, i in seen_wk.values():
                if carry[wk] / fs > 0.5:
                    continue  # family-wide -> not isolable by consensus (layer-2's job)
                findings[s["pid"]].append({**base, "kind": "alien_debris",
                    "shape": shape, "token": raw, "minority": f"{carry[wk]}/{fs}",
                    "verdict": "contamination",
                    "reason": f"{shape} '{raw}' appears in only {carry[wk]} of {fs} "
                              f"settings of this family -- consensus isolates it as "
                              f"non-sung text local to this setting",
                    "context": _l3_ctx(s["allraw"], i), "siblings": siblings})
            # (b) alien VOCABULARY (rarest few, shape-neutral words). The (count,
            # word) sort is TOTAL so selection is deterministic regardless of the
            # set-iteration order (PYTHONHASHSEED) of allnorm.
            alien = [n for n in s["allnorm"]
                     if n not in sib_union and len(n) >= 4 and n.isalpha()]
            for n in sorted(alien, key=lambda w: (type_vocab[t][w], w))[:6]:
                verdict = _l3_arbitrate_alien(n, type_vocab[t][n] > 1)
                if verdict is None:
                    continue
                v, reason, _kind = verdict
                ci = next((k for k, rt in enumerate(s["allraw"])
                           if _l3_norm(rt) == n), 0)
                findings[s["pid"]].append({**base, "kind": "alien_token",
                    "token": n, "verdict": v, "reason": reason,
                    "context": _l3_ctx(s["allraw"], ci), "siblings": siblings})
            # (c) MISSING TEXT -- an INTERIOR family-shared passage that this
            # setting lacks. The interior test (present blocks both BEFORE and
            # AFTER the gap) is what separates a genuine dropped line from a
            # legitimate truncation / sub-part (e.g. the anaphora opening dialogue
            # is a prefix of the full anaphora, not a piece with a dropped line).
            if shared and len(s["repnorm"]) >= 12:
                present = [block_order[g] for g in shared if idx in shared[g]]
                missing = [g for g in shared if idx not in shared[g]]
                if present and missing:
                    lo, hi = min(present), max(present)
                    interior = sorted((block_order[g], g) for g in missing
                                      if lo < block_order[g] < hi)
                    if len(interior) >= 2:  # a real interior gap, not a tail cut
                        g0 = interior[0][1]
                        haver = fam[min(shared[g0])]
                        findings[s["pid"]].append({**base, "kind": "missing_block",
                            "verdict": "uncertain",
                            "reason": f"{len(interior)} passage(s) shared by >=70% of "
                                      f"the {fs} settings sit BETWEEN passages this "
                                      f"setting does have -- an interior gap, i.e. a "
                                      f"probable dropped line (needs a PDF check)",
                            "missing_passage": " ".join(g0),
                            "context": " ".join(haver["rep"][:16]),
                            "siblings": [haver["pid"]]})
    cluster_stats = {
        "settings": len(settings),
        "types": len(bytype),
        "types_ge3": sum(1 for g in bytype.values() if len(g) >= 3),
        "families_consensus": fam_sizes["consensus"],
        "families_size2": fam_sizes["family_size_2"],
        "families_singleton": fam_sizes["no_family_consensus"],
        "types_too_small": fam_sizes["small_type"],
    }
    return findings, cluster_stats, bytype


def attach_layer3(report, manifest_path):
    """Compute layer 3, attach a ``layer3`` list to each piece and a top-level
    ``layer3`` summary. Mutates and returns ``report``."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    titles = {e["id"]: e.get("title", "") for e in manifest}
    settings, sec_derived = _l3_build_settings(manifest)
    findings, cluster_stats, bytype = _l3_consensus(settings)
    cluster_stats["settings_section_derived"] = sec_derived

    pieces = report["pieces"]
    for pid, fl in findings.items():
        fl.sort(key=lambda f: (
            0 if f["verdict"] == "contamination" else
            1 if f["kind"].startswith("missing") else 2, -f["family_size"]))
        if pid not in pieces:
            pieces[pid] = {"title": titles.get(pid, ""), "flags": []}
        pieces[pid]["layer3"] = fl

    # --- validation: consensus vs the layer-1/2 contamination set (same run) ---
    l12_contam = {pid for pid, p in pieces.items()
                  if any(f.get("verdict") == "contamination" for f in p["flags"])}
    covered = {s["pid"] for t, g in bytype.items() if len(g) >= 3
               for fam in _l3_families(g) if len(fam) >= 3 for s in fam}
    cons_contam = {pid for pid, fl in findings.items()
                   if any(f["verdict"] == "contamination" for f in fl)}
    cons_missing = {pid for pid, fl in findings.items()
                    if any(f["kind"].startswith("missing") for f in fl)}
    reflagged = l12_contam & cons_contam
    new_contam = cons_contam - l12_contam
    verdicts = Counter(f["verdict"] for fl in findings.values() for f in fl)
    kinds = Counter(f["kind"] for fl in findings.values() for f in fl)

    def rank_key(pid):
        fl = findings[pid]
        has_c = any(f["verdict"] == "contamination" for f in fl)
        has_m = any(f["kind"].startswith("missing") for f in fl)
        return (0 if has_c else 1 if has_m else 2,
                -max(f["family_size"] for f in fl))
    ranked = []
    for pid in sorted(findings, key=rank_key)[:60]:
        fl = findings[pid]
        top = fl[0]
        ranked.append({"id": pid, "kind": top["kind"], "type": top["type"],
                       "verdict": top["verdict"], "token": top.get("token"),
                       "section": top.get("section"),
                       "n_contamination": sum(1 for f in fl
                                              if f["verdict"] == "contamination"),
                       "n_missing": sum(1 for f in fl
                                        if f["kind"].startswith("missing"))})

    report["layer3"] = {
        "method": "type-cluster -> Jaccard translation-families (thr=0.5) -> "
                  "consensus (alien-debris / alien-vocab / missing-text) -> "
                  "semantic arbitration",
        "clusters": cluster_stats,
        "verdicts": dict(verdicts),
        "kinds": dict(kinds),
        "validation": {
            "layer12_contamination_pieces": len(l12_contam),
            "layer12_contam_in_a_consensus_family": len(l12_contam & covered),
            "reflagged_by_consensus": len(reflagged),
            "reflagged_of_family_having": f"{len(l12_contam & covered & cons_contam)}"
                                          f"/{len(l12_contam & covered)}",
            "consensus_only_new_contamination_pieces": len(new_contam),
            "consensus_only_new_contamination": sorted(new_contam)[:30],
            "missing_text_pieces": len(cons_missing),
            "note": "layer-1/2 contamination survivors that are family SINGLETONS "
                    "(unique carols / one-off hymns) are structurally invisible to "
                    "consensus; recall is honest against the family-having subset.",
        },
        "pieces_with_findings": len(findings),
        "ranked": ranked,
    }
    return report


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
    ap.add_argument("--no-layer3", action="store_true",
                    help="skip the consensus (categorical) pass")
    args = ap.parse_args()
    report, review_pieces = build_report(args.manifest)
    if not args.no_layer3:
        attach_layer3(report, args.manifest)
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

    if "layer3" in report:
        l3 = report["layer3"]
        c, v = l3["clusters"], l3["validation"]
        print(f"\n--- LAYER 3 (consensus) ---")
        print(f"settings {c['settings']} ({c['settings_section_derived']} from "
              f"complete-liturgy sections); types {c['types']} "
              f"({c['types_ge3']} with >=3 settings)")
        print(f"families: {c['families_consensus']} consensus (>=3), "
              f"{c['families_size2']} size-2, {c['families_singleton']} singleton "
              f"(no-family-consensus)")
        print(f"consensus verdicts: {l3['verdicts']}   kinds: {l3['kinds']}")
        print(f"validation: layer-1/2 contamination pieces {v['layer12_contamination_pieces']}; "
              f"of those in a consensus family {v['layer12_contam_in_a_consensus_family']}; "
              f"RE-FLAGGED by consensus {v['reflagged_of_family_having']} "
              f"(family-having subset)")
        print(f"NEW consensus-only contamination pieces: "
              f"{v['consensus_only_new_contamination_pieces']}; "
              f"missing-text pieces: {v['missing_text_pieces']}")
        print(f"\ntop consensus findings:")
        for r in l3["ranked"][:args.top]:
            tag = ("CONTAM" if r["n_contamination"] else
                   "MISSING" if r["n_missing"] else r["verdict"][:6])
            tok = f" '{r['token']}'" if r.get("token") else ""
            print(f"   {tag:7} {r['id'][:40]:40} {r['kind']:13} "
                  f"[{r['type'][:22]}]{tok}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
