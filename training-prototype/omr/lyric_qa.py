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
     (a) TYPE-CLUSTERS every accepted piece by hymn type (HYMN_ORDINARY /
         HYMN_PROPER / ANAPHORA_SUB, shared with ingest_catalog.py -- issue
         #81: Trisagion, Cherubic, "It is truly meet", Great Litany, Dismissal
         ..., plus the DL anaphora complex's real 5-way split -- Litany of the
         Anaphora, Mercy of Peace, Sanctus, We Praise Thee, Megalynarion --
         rather than one lumped "anaphora" bucket; plus base-type + feast-id
         keys for the Propers; complete-liturgy books are SLICED into
         per-section settings via their report.json ``sections[]`` measure
         marks so each book contributes a Trisagion setting, a Sanctus
         setting, ...).
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
         and MISSING-TEXT (a family-shared INTERIOR passage this setting lacks
         -- the dropped-line signal nothing else can see). The missing-text
         check (issue #89, after the #86 PDF review found 29/30 top flags were
         QA artifacts) n-grams the RE-JOINED WORD stream, decides passage
         membership on a letters-only blob (syllabification / case / fi-fl
         ligature invariant), never counts a passage carried by a sibling
         section-slice of the same book, and only lets a missing passage
         count as gap EVIDENCE when its content words are absent from the
         local gap window too -- word-order, one-word-insertion/substitution
         and elision variants are suppressed. Transliteration and words shared
         across the type's other families are recognized as legit; consensus
         flags are arbitrated exactly as layer 2 arbitrated heuristics ->
         contamination | legit-variant | uncertain.
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

# Shared taxonomy with ingest_catalog.py (issue #81, off #83's recommendation
# "import HYMN_ORDINARY/HYMN_PROPER from here instead" -- see that module's
# docstring). Previously this module hand-kept a private copy (_L3_ORDINARY /
# _L3_PROPER, plus a single lumped 'anaphora' entry) in sync by hand; a shared
# import removes the drift risk and gives layer 3 the real 5-way anaphora
# split. _ANAPHORA_GENERIC_RE / _DL_OTHER_KEYWORDS are "private" only by
# leading-underscore naming convention in ingest_catalog.py -- they ARE the
# exact compilation guard ingest_catalog.hymn_type() runs, and reusing those
# objects (not re-deriving equivalent ones here) is what keeps this module's
# per-section version of the guard from drifting out of step with it.
from ingest_catalog import (ANAPHORA_SUB, HYMN_ORDINARY, HYMN_PROPER,
                            _ANAPHORA_GENERIC_RE, _DL_OTHER_KEYWORDS)

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

# Typographic ligatures leak from born-digital PDFs into lyric tokens
# ('sacriﬁce' -> syllable token 'ﬁce') and break family n-gram matching
# against siblings that engrave the plain digraph (issue #89 refinement 1).
_L3_LIGATURES = str.maketrans({
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "ft", "ﬆ": "st"})


def _l3_norm(t: str) -> str:
    """Common-denominator token for family clustering / vocabulary voting:
    expand ligatures, strip surrounding punctuation and lowercase.
    (Deliberately DESTROYS the debris shape -- '[At'->'at', 'Deacon:'->'deacon'
    -- so debris is detected on RAW tokens.)"""
    return t.translate(_L3_LIGATURES).strip(_L3_PUNCT).lower().replace("’", "'")


def _l3_is_content(n: str) -> bool:
    return bool(n) and not n.isdigit()


# ---------------------------------------------------------- word/blob streams
# Issue #89: the missing-text (interior-gap) consensus check used to n-gram the
# raw SYLLABLE token stream, so a mere syllabification difference between two
# settings of the same text ('spir it' vs 'spi rit', 'cher-u-bim' vs
# 'che-ru-bim') read as a "missing" passage. The #86 PDF review found 29 of the
# top 30 flags were artifacts of exactly this class (plus section slicing and
# one-word variants). The machinery below makes gram matching robust:
#   * _l3_words     -- re-join begin/middle/end syllables into whole words for
#                      readable, comparable n-gram GENERATION;
#   * _l3_blobstream -- a letters-only concatenation of the stream, because
#                      membership must be syllabification-INVARIANT even when
#                      an edition engraves detached syllables with syllabic
#                      'single' markers (e.g. Anaphora-3rd-Mode-FJ-WNBN, the
#                      one confirmed real drop): a gram is "present" iff its
#                      concatenated letters appear in the blob, however the
#                      setting happened to split them into tokens.

_L3_NGRAM_K = 4
# words too grammatical to carry gap evidence on their own (len<3 tokens are
# already excluded by the len>=3 content-word rule below)
_L3_GAP_STOPWORDS = {"the", "and"}
_L3_WORDCHARS = re.compile(r"[^a-z0-9]+")


def _l3_wordkey(t: str) -> str:
    """Letters-only lowercase form of one token ('GOT-' -> 'got',
    \"receiv'd\" -> 'receivd', 'sacriﬁce' -> 'sacrifice')."""
    return _L3_WORDCHARS.sub("", _l3_norm(t))


def _l3_words(stream):
    """[(word, measure)] from a [(measure, text, syllabic), ...] stream.
    Joins coherent begin/middle*/end syllabic runs into whole words; an
    incoherent marker sequence (interleave damage, missing markers) flushes
    conservatively so no token is ever dropped. Non-letter tokens ('...',
    stray punctuation, page digits) contribute nothing."""
    out = []
    buf, buf_m = [], None

    def flush():
        if buf:
            w = "".join(buf)
            if _l3_is_content(w):
                out.append((w, buf_m))
            del buf[:]

    for mn, txt, syl in stream:
        n = _l3_wordkey(txt)
        if not n:
            continue  # '...' continuation / punct: not a word boundary
        if syl == "begin":
            flush()
            buf.append(n)
            buf_m = mn
        elif syl == "middle":
            if buf:
                buf.append(n)
            else:
                out.append((n, mn))       # incoherent: keep as its own word
        elif syl == "end":
            if buf:
                buf.append(n)
                flush()
            else:
                out.append((n, mn))       # incoherent: keep as its own word
        else:                             # 'single' / marker absent
            flush()
            out.append((n, mn))
    flush()
    return out


def _l3_blobstream(stream):
    """(blob, toks) for a [(measure, text, syllabic), ...] stream, where blob
    is the letters-only lowercase concatenation of every token and toks is
    [(raw_text, measure, blob_start)] for the tokens that contributed."""
    parts, toks = [], []
    pos = 0
    for mn, t, _syl in stream:
        n = _l3_wordkey(t)
        if not n or n.isdigit():
            continue
        toks.append((t, mn, pos))
        parts.append(n)
        pos += len(n)
    return "".join(parts), toks


def _l3_word_in(blob: str, w: str) -> bool:
    """Is word w present in the letters-only blob? Exact substring, plus a
    one-deletion tolerance for elision/spelling variants ('received' matches a
    blob carrying \"receiv'd\", 'heavenly' matches \"heav'nly\") on words long
    enough that a single dropped letter cannot make a spurious match."""
    if w in blob:
        return True
    if len(w) >= 5:
        for i in range(len(w)):
            if w[:i] + w[i + 1:] in blob:
                return True
    return False


def _l3_find_all(blob: str, s: str):
    out = []
    i = blob.find(s)
    while i != -1:
        out.append(i)
        i = blob.find(s, i + 1)
    return out


# --- hymn-type assignment -------------------------------------------------
# ORDINARY: the fixed-text hymns of the services -- same words every time, so
# they cluster by TYPE alone (no feast needed). PROPER: text varies per feast/
# saint, so the TYPE key carries a feast key -- same base type + same feast =
# same canonical text. Both lists (and the DL anaphora-complex 5-way split,
# ANAPHORA_SUB) now come from ingest_catalog.py -- see the import comment
# above. First match wins in each list, exactly as ingest_catalog.hymn_type().
_L3_ANAPHORA_SUB_RE = [(n, re.compile(p, re.I)) for n, p in ANAPHORA_SUB]
_L3_ORD_RE = [(n, re.compile(p, re.I)) for n, p in HYMN_ORDINARY]
_L3_PROP_RE = [(n, re.compile(p, re.I)) for n, p in HYMN_PROPER]

# label -> "ordinary"/"proper", for resolving the manifest's own `hymnType`
# field back to a clustering kind (item 2 below). "megalynarion" is the one
# label BOTH ANAPHORA_SUB (the DL anaphora complex's fixed-text Megalynarion/
# Axion Estin) and HYMN_PROPER (a saint's/feast's megalynarion, which DOES
# vary by feast) can produce -- see _l3_kind_of(), which disambiguates it by
# bookName exactly as ingest_catalog.hymn_type() does, rather than trusting
# this static table for that one label.
_HYMN_KIND = {label: "ordinary" for label, _ in HYMN_ORDINARY}
_HYMN_KIND.update({label: "ordinary" for label, _ in ANAPHORA_SUB})
_HYMN_KIND["anaphora"] = "ordinary"   # the 0-/2+-cue generic fallback label
for _label, _ in HYMN_PROPER:
    _HYMN_KIND.setdefault(_label, "proper")


def _l3_feast_key(feast_id, litdate, sub):
    """Feast/day family key for a PROPER hymn (issue #81 item 3). Prefers the
    manifest's `feastId` field (ingest_catalog.feast_id()), which strips the
    per-item liturgicalDate order-prefix ('A1-Pascha' -> 'pascha') so that
    same-day settings by different composers actually share a key -- the old
    raw-liturgicalDate/sub normalization baked that per-item prefix into the
    key instead, which is exactly why issue #83 found most Triodion/
    Pentecostarion propers were singleton families (712 of them keyed on raw
    liturgicalDate/sub). Falls back to the raw normalization when feastId is
    absent -- fields not yet materialized on the current manifest, or a book
    feast_id() doesn't cover."""
    if feast_id:
        return feast_id
    fk = re.sub(r"[^a-z0-9]+", " ", (litdate or sub or "").lower()).strip()
    return fk[:60]


def _l3_hymn_type(text, litdate, sub, book=None, feast_id=None):
    """(type_id, kind) for a title or section-title. Mirrors
    ingest_catalog.hymn_type()'s control flow: a Divine Liturgy title/section
    that mentions the anaphora complex is resolved by ANAPHORA_SUB's 5-way
    split (compilation-guarded -- 0 specific cues or 2+ conflicting cues
    collapses to the generic 'anaphora' label; a title that ALSO reaches
    beyond the anaphora/megalynarion complex, e.g. a combined section heading,
    is left unclassified) and returns from there without falling through to
    the generic Ordinary/Proper loops below (same as ingest_catalog.py).
    Otherwise: Ordinary -> type-only; Proper -> base|feast_key; else None.
    Deliberately operates on ONE text blob (a section title, or the whole
    piece title as a fallback) rather than ingest_catalog.hymn_type()'s fuller
    name+filename+all-section-titles blob -- this module classifies per
    section already, so the narrower input is the right granularity; the
    guard LOGIC (the regex sets + the two-stage hits/guard decision) is
    exactly shared, not reimplemented."""
    text = text or ""
    if book == "Divine Liturgy":
        hits = {label for label, rx in _L3_ANAPHORA_SUB_RE if rx.search(text)}
        if hits or _ANAPHORA_GENERIC_RE.search(text):
            if any(kw in text.lower() for kw in _DL_OTHER_KEYWORDS):
                return None, None   # spans beyond the anaphora complex
            if len(hits) == 1:
                return next(iter(hits)), "ordinary"
            return "anaphora", "ordinary"  # 0 specific or 2+ cues
    for name, rx in _L3_ORD_RE:
        if rx.search(text):
            return name, "ordinary"
    for name, rx in _L3_PROP_RE:
        if rx.search(text):
            return f"{name}|{_l3_feast_key(feast_id, litdate, sub)}", "proper"
    return None, None


def _l3_kind_of(slug, book):
    """Ordinary vs proper for a manifest `hymnType` slug (item 2 below). See
    the _HYMN_KIND comment for why "megalynarion" needs the bookName check
    rather than a static lookup."""
    if slug == "megalynarion":
        return "ordinary" if book == "Divine Liturgy" else "proper"
    return _HYMN_KIND.get(slug, "ordinary")


def _l3_type_from_manifest_field(entry):
    """(type_id, kind) for a whole-piece (non-sliced) setting, using the
    manifest's own `hymnType` field directly (issue #81 item 2) instead of
    re-deriving the type from the title alone. `hymnType` was computed by
    ingest_catalog.hymn_type() from a fuller signal (name + filename + every
    in-score section title) and already carries its own compilation-guard
    verdict -- an explicit None there means "this is a compilation, don't
    guess", which is trusted here too, not treated as "field missing" (the
    caller only takes this path when the key is present at all; see
    `"hymnType" in entry` at the call site)."""
    slug = entry.get("hymnType")
    if not slug:
        return None, None
    kind = _l3_kind_of(slug, entry.get("bookName"))
    if kind == "proper":
        fk = _l3_feast_key(entry.get("feastId"), entry.get("liturgicalDate"),
                           entry.get("sub"))
        return f"{slug}|{fk}", "proper"
    return slug, "ordinary"


def _l3_voice_measure_streams(xml_path):
    """{f"{part}:{label}:v{verse}": [(measure, token, syllabic), ...]} for
    measure-range section slicing. VERSE-SPLIT (issue #89 refinement 4): the
    old version concatenated every <lyric> regardless of its number attribute,
    so multi-verse / multilingual stacked settings produced an interleaved
    stream ('It is meet to is wor meet to ship') whose n-grams matched nothing
    -- the root of the 'garbled rep-voice' false positives. Each (part, verse)
    is now its own stream, and the syllabic marker rides along for word
    re-joining."""
    root = ET.parse(xml_path).getroot()
    names = {}
    for sp in root.iter("score-part"):
        names[sp.get("id")] = (sp.findtext("part-name") or sp.get("id") or "").strip()
    out = {}
    for part in root.findall("part"):
        pid = part.get("id")
        byverse = defaultdict(list)
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
                        byverse[ly.get("number", "1")].append(
                            (cur, txt, ly.findtext("syllabic")))
        label = names.get(pid) or pid
        for num in sorted(byverse):
            out[f"{pid}:{label}:v{num}"] = byverse[num]
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


def _l3_make_setting(pid, title, section, ty, kind, verse_slices,
                     part_slices=None, piece_blobs=None):
    """A consensus unit.

    verse_slices: one stream per (voice, verse) -- the CLEAN streams the
    missing-text machinery n-grams (rep = the longest one). part_slices: one
    stream per voice with its verses concatenated -- family clustering keys
    (``normset``, and the tiny-stream gate) stay on the per-VOICE token set
    exactly as before the issue #89 verse split, because a normset is a SET
    (order-insensitive) and re-keying it on a single verse would reshuffle
    families and lose unrelated debris/vocabulary findings. allnorm / allraw =
    union over ALL voices (contamination can sit in one voice only, so debris
    + vocabulary are scanned across every part). piece_blobs (section-sliced
    books only) carries the WHOLE piece's letters-only streams so a passage
    living in a sibling slice is never reported missing from this one."""
    if part_slices is None:
        part_slices = verse_slices
    rep = max(verse_slices, key=len) if verse_slices else []
    allraw, allnorm = [], set()
    for vs in part_slices:
        for _mn, t, _syl in vs:
            allraw.append(t)
            n = _l3_norm(t)
            if _l3_is_content(n):
                allnorm.add(n)
    part_rep = max(part_slices, key=len) if part_slices else []
    repnorm = [n for n in (_l3_norm(t) for _mn, t, _syl in part_rep)
               if _l3_is_content(n)]
    if len(repnorm) < 4:
        return None
    blob, toks = _l3_blobstream(rep)
    # every verse stream's blob, not just the rep's: a setting that engraves
    # the text's two halves as verse 1 / verse 2 under the same notes (common
    # for cherubic hymns) HAS the second half -- in another stream.
    all_blobs = [b for b in (_l3_blobstream(vs)[0] for vs in verse_slices) if b]
    return {"pid": pid, "title": title, "section": section, "type": ty,
            "kind": kind, "rep": rep, "allraw": allraw, "repnorm": repnorm,
            "normset": set(repnorm), "allnorm": allnorm,
            "repwords": [w for w, _ in _l3_words(rep)],
            "blob": blob, "toks": toks, "all_blobs": all_blobs,
            "piece_blobs": piece_blobs}


def _l3_part_streams(vms):
    """Concatenate a part's verse streams back into one stream per part (for
    the family-clustering token sets -- see _l3_make_setting)."""
    parts = defaultdict(list)
    for key, seq in vms.items():
        parts[key.rsplit(":v", 1)[0]].extend(seq)
    return list(parts.values())


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
        book, feast_id = entry.get("bookName"), entry.get("feastId")
        title = entry.get("title", "")
        mapped = []
        for s in _l3_load_sections(pid):
            st = s.get("title", "")
            ty, kind = _l3_hymn_type(st, litdate, sub, book, feast_id)
            if ty is None:
                # recurring section fallback: a clean multi-word heading becomes
                # its own type so identical section titles cluster across books
                key = re.sub(r"[^a-z0-9]+", " ", st.lower()).strip()
                if 8 <= len(key) <= 45 and " " in key and not re.search(r"\d{2,}", key):
                    ty, kind = f"section|{key}", "section"
            mapped.append((s.get("measure", 1), st, ty, kind))
        if sum(1 for m in mapped if m[2]) >= 2:  # complete-liturgy: slice sections
            # the WHOLE piece's letters-only streams: a passage that a slice
            # "misses" but a sibling slice (or a span across the slice
            # boundary) carries is present in the BOOK -- not a drop.
            piece_blobs = [b for b in
                           (_l3_blobstream(seq)[0] for seq in vms.values()) if b]
            part_streams = _l3_part_streams(vms)
            for j, (meas, st, ty, kind) in enumerate(mapped):
                if not ty:
                    continue
                hi = mapped[j + 1][0] if j + 1 < len(mapped) else 10 ** 9
                vslices = [[(mn, t, syl) for (mn, t, syl) in seq
                            if meas <= mn < hi] for seq in vms.values()]
                pslices = [[(mn, t, syl) for (mn, t, syl) in seq
                            if meas <= mn < hi] for seq in part_streams]
                setting = _l3_make_setting(pid, title, st, ty, kind, vslices,
                                           pslices, piece_blobs)
                if setting:
                    settings.append(setting)
                    sec_derived += 1
        else:  # single-type piece: one whole-piece setting. Prefer the
            # manifest's own hymnType field (issue #81 item 2) when this
            # manifest carries it at all -- an explicit null is a trusted
            # "compilation, don't guess" verdict from ingest time, not a
            # missing-field signal, so it is NOT treated as a cue to fall
            # back to the from-scratch title match.
            if "hymnType" in entry:
                ty, kind = _l3_type_from_manifest_field(entry)
            else:
                ty, kind = _l3_hymn_type(title, litdate, sub, book, feast_id)
            if ty is None:
                continue
            setting = _l3_make_setting(pid, title, None, ty, kind,
                                       list(vms.values()),
                                       _l3_part_streams(vms))
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


def _l3_blob_ctx(setting, cat, w=16):
    """~w raw tokens of `setting` around the first blob occurrence of the
    letters-only passage `cat` (for the reviewer's context display)."""
    toks = setting["toks"]
    p = setting["blob"].find(cat)
    j = 0
    if p != -1:
        while j + 1 < len(toks) and toks[j + 1][2] <= p:
            j += 1
        j = max(0, j - 2)
    return " ".join(t for t, _mn, _st in toks[j:j + w])


def _l3_consensus(settings):
    """Run the consensus checks. Returns (findings_by_pid, cluster_stats,
    bytype, missing_filter_stats)."""
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
    mstats = Counter()
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
        # shared long passages, present in >=70% of the family, with their
        # median position (fraction of stream length) across the settings that
        # have them -- so a MISSING passage can be classed as an interior gap
        # vs a truncation. Issue #89 rework: grams are GENERATED from each
        # member's re-joined WORD stream (readable, syllabification-free), but
        # MEMBERSHIP is decided on the letters-only blob, so any
        # syllabification/casing/ligature spelling of the same letters counts
        # as having the passage. The length/content eligibility guards keep
        # stopword-runs and too-short concatenations from matching spuriously.
        K = _L3_NGRAM_K
        gram_cat = {}                     # gram -> concatenated letters
        for s in fam:
            wl = s["repwords"]
            for i in range(len(wl) - K + 1):
                g = tuple(wl[i:i + K])
                if g in gram_cat:
                    continue
                cat = "".join(g)
                if len(cat) < 10:
                    continue
                if sum(1 for w in g if len(w) >= 3
                       and w not in _L3_GAP_STOPWORDS) < 2:
                    continue
                gram_cat[g] = cat
        ngm = defaultdict(set)            # gram -> member idxs that HAVE it
        ngm_pos = defaultdict(list)       # gram -> blob-position fractions
        for idx, s in enumerate(fam):
            blob = s["blob"]
            L = max(1, len(blob))
            for g, cat in gram_cat.items():
                p = blob.find(cat)
                if p != -1:
                    ngm[g].add(idx)
                    ngm_pos[g].append(p / L)
                    continue
                # not in the rep stream, but carried by another voice/verse
                # stream (e.g. second-half-as-verse-2 engraving) -- the
                # setting HAS the passage; position from that stream.
                for b in s["all_blobs"]:
                    q = b.find(cat)
                    if q != -1:
                        ngm[g].add(idx)
                        ngm_pos[g].append(q / max(1, len(b)))
                        break
        need = max(2, int(0.7 * fs + 0.5))
        shared = {g: ms for g, ms in ngm.items() if len(ms) >= need}
        block_order = {}
        if shared:
            order_sorted = sorted(
                shared,
                key=lambda g: (sorted(ngm_pos[g])[len(ngm_pos[g]) // 2], g))
            block_order = {g: i for i, g in enumerate(order_sorted)}
        for idx, s in enumerate(fam):
            sib_union = set().union(*[fam[j]["allnorm"]
                                      for j in range(fs) if j != idx])
            siblings = [" ".join(tt for _mn, tt, _sy in fam[j]["rep"][:7])
                        for j in range(fs) if j != idx][:3]
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
            # Issue #89 refinements on top of the interior test:
            #   * a passage carried by a SIBLING SLICE of the same book (or
            #     spanning a slice boundary) is present in the piece -- skip;
            #   * a missing gram only carries gap EVIDENCE when its content
            #     words are absent from the local gap window too -- a
            #     word-order / one-word-insertion / substitution / elision
            #     variant has the words right there and is suppressed;
            #   * flag on >=2 evidencing grams, or one whose content words
            #     (>=3 of them) are ALL locally absent (a single short dropped
            #     response line, the #88 short-system class).
            if shared and len(s["repwords"]) >= 8:
                blob = s["blob"]
                # anchors must sit in the REP stream (windows are rep-blob
                # coordinates); a passage carried only by another verse stream
                # is "present" for missing-ness but cannot anchor a window.
                present = {}
                for g in shared:
                    if idx in shared[g]:
                        ps = _l3_find_all(blob, gram_cat[g])
                        if ps:
                            present[g] = ps
                pblobs = s.get("piece_blobs")
                missing = []
                for g in shared:
                    if idx in shared[g]:
                        continue
                    if pblobs and any(gram_cat[g] in b for b in pblobs):
                        mstats["sibling_slice_present"] += 1
                        continue
                    missing.append(g)
                if present and missing:
                    orders = [block_order[g] for g in present]
                    lo, hi = min(orders), max(orders)
                    interior = sorted((block_order[g], g) for g in missing
                                      if lo < block_order[g] < hi)
                    pres_sorted = sorted((block_order[g], g) for g in present)
                    real = []
                    for o, g in interior:
                        # gap window: from the nearest present passage BEFORE
                        # the gap (canonical family order) to the nearest one
                        # AFTER it, INCLUDING the anchor text itself -- a
                        # variant gram usually shares words with its
                        # neighboring anchors ('holy mighty holy immor...'
                        # against a 'holy and immortal' insertion edition).
                        prev_g = max((po, pg) for po, pg in pres_sorted
                                     if po < o)[1]
                        next_g = min((po, pg) for po, pg in pres_sorted
                                     if po > o)[1]
                        w_lo = min(present[prev_g])
                        w_hi = max(p + len(gram_cat[next_g])
                                   for p in present[next_g])
                        if w_hi < w_lo:
                            w_lo, w_hi = w_hi, w_lo   # order-drift safety
                        window = blob[max(0, w_lo - 12):w_hi + 12]
                        content = list(dict.fromkeys(
                            w for w in g if len(w) >= 3
                            and w not in _L3_GAP_STOPWORDS))
                        # a content word only counts as gap evidence when it
                        # is absent from the local window AND from the whole
                        # piece (every voice/verse stream, and every sibling
                        # slice of a sliced book): issue #89 -- 'requires the
                        # span's CONTENT WORDS absent, not just the 4-gram'.
                        # This is what suppresses reordered translations,
                        # verse-interleaved responsory engravings, and
                        # phrase-adjacency differences; a real drop's words
                        # never reached the MusicXML at all.
                        everywhere = s["all_blobs"] + (pblobs or [])
                        absent = [w for w in content
                                  if not _l3_word_in(window, w)
                                  and not any(_l3_word_in(b, w)
                                              for b in everywhere)]
                        if len(absent) >= 2:
                            real.append((o, g, content, absent))
                        else:
                            mstats["local_variant_suppressed"] += 1
                    strong = [r for r in real if len(r[3]) == len(r[2]) >= 3]
                    # DIFFERENT-TEXT GUARD: a genuine dropped line is a
                    # CONTIGUOUS run (or two) of missing passages; a setting
                    # whose evidencing gaps are SCATTERED across a large share
                    # of the family's canonical text is a different
                    # translation / different canonical text that the type key
                    # + Jaccard clustering failed to separate (the fam=3
                    # ode/katavasia families), not a piece with dropped lines.
                    runs, prev_o = 0, None
                    for o, _g, _c, _a in real:
                        if prev_o is None or o - prev_o > 2:
                            runs += 1
                        prev_o = o
                    if runs >= 3 and (len(real) > max(5, 0.5 * len(present))
                                      or len(real) >= 12):
                        mstats["family_mismatch_suppressed"] += 1
                    elif len(real) >= 2 or strong:
                        g0 = (strong[0] if strong and len(real) < 2
                              else real[0])[1]
                        haver = fam[min(shared[g0])]
                        mstats["flagged_settings"] += 1
                        mstats["evidencing_grams"] += len(real)
                        findings[s["pid"]].append({**base, "kind": "missing_block",
                            "verdict": "uncertain",
                            "reason": f"{len(real)} passage(s) shared by >=70% of "
                                      f"the {fs} settings sit BETWEEN passages this "
                                      f"setting does have, with their content words "
                                      f"absent from the gap region -- an interior "
                                      f"gap, i.e. a probable dropped line (needs a "
                                      f"PDF check)",
                            "missing_passage": " ".join(g0),
                            "missing_words": sorted(
                                {w for _o, _g, _c, ab in real for w in ab}),
                            "evidence_grams": len(real),
                            "present_grams": len(present),
                            "gap_runs": runs,
                            "context": _l3_blob_ctx(haver, gram_cat[g0]),
                            "siblings": [haver["pid"]]})
                    elif interior:
                        mstats["settings_fully_suppressed"] += 1
    cluster_stats = {
        "settings": len(settings),
        "types": len(bytype),
        "types_ge3": sum(1 for g in bytype.values() if len(g) >= 3),
        "families_consensus": fam_sizes["consensus"],
        "families_size2": fam_sizes["family_size_2"],
        "families_singleton": fam_sizes["no_family_consensus"],
        "types_too_small": fam_sizes["small_type"],
    }
    return findings, cluster_stats, bytype, dict(mstats)


def attach_layer3(report, manifest_path):
    """Compute layer 3, attach a ``layer3`` list to each piece and a top-level
    ``layer3`` summary. Mutates and returns ``report``."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    titles = {e["id"]: e.get("title", "") for e in manifest}
    settings, sec_derived = _l3_build_settings(manifest)
    findings, cluster_stats, bytype, missing_filter = _l3_consensus(settings)
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
                  "semantic arbitration; missing-text via word-joined n-grams "
                  "with letters-only blob membership + local content-word gap "
                  "test (issue #89)",
        "clusters": cluster_stats,
        "missing_block_filter": missing_filter,
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
        print(f"missing-block filter (issue #89): {l3['missing_block_filter']}")
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
