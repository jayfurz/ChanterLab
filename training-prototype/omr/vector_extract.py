#!/usr/bin/env python3
"""vector_extract.py — SATB MusicXML extraction from born-digital engraving PDFs.

Not OMR. Born-digital scores (Dorico/Sibelius/MuseScore exports) place every
musical symbol as a SMuFL music-font glyph (here: Bravura) or a vector path at
exact coordinates. This module reads those primitives straight out of the PDF
with PyMuPDF and reassembles notation:

  staff lines (5-line groups of horizontal paths)  -> staff coordinate systems
  clef/key glyphs                                  -> pitch reference per staff
  notehead glyphs (incl. Bravura oversized alts)   -> (staff, step, x)
  stems/beams (vector lines/quads) + flag/dot glyphs -> durations, chords
  barlines                                          -> measures
  stem direction                                    -> voice split on shared staves
  text spans below staves                           -> lyric syllables per note
  tie curves                                        -> tied notes

Layouts handled:
  * 4 staves per system (S/A/T/B each on its own staff)
  * 2 staves per system (S+A on treble, T+B on bass; stem-up = upper voice,
    stem-down = lower voice, single-stem chords split top/bottom, lone
    whole-notes / single streams treated as unison a2 and reported)

Output: 4-part MusicXML (score-partwise) + a confidence report (dict / JSON)
listing every assumption and inconsistency found, so a human (or a Phase-4
correction UI) knows exactly where to look.

Usage:
  .venv/bin/python vector_extract.py pdfs/01_trisagion_lozowchuk_satb.pdf \
      -o out/trisagion_vector.musicxml --report out/trisagion_vector.report.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

# ---------------------------------------------------------------- SMuFL tables

NOTEHEADS = {
    0xE0A0: ("whole", 8.0), 0xE0A1: ("whole", 8.0),   # double whole ~ treat as 8
    0xE0A2: ("whole", 4.0), 0xE0A3: ("half", 2.0), 0xE0A4: ("black", 1.0),
    # Bravura "oversized" optional glyphs (Dorico default noteheads)
    0xF4BA: ("whole", 8.0), 0xF4BC: ("whole", 4.0),
    0xF4BD: ("half", 2.0), 0xF4BE: ("black", 1.0),
}
CLEFS = {0xE050: "treble", 0xE052: "treble8", 0xE062: "bass", 0xE05C: "alto"}
# diatonic number (octave*7 + letter C=0..B=6) of the BOTTOM staff line
CLEF_BOTTOM_LINE = {"treble": 4 * 7 + 2, "treble8": 3 * 7 + 2,
                    "bass": 2 * 7 + 4, "alto": 3 * 7 + 3}
ACCIDENTALS = {0xE260: -1, 0xE261: 0, 0xE262: +1}  # flat, natural, sharp
ACC_NAMES = {-1: "flat", 0: "natural", +1: "sharp"}
RESTS = {0xE4E3: 4.0, 0xE4E4: 2.0, 0xE4E5: 1.0, 0xE4E6: 0.5, 0xE4E7: 0.25}
FLAGS = {0xE240: (1, "up"), 0xE241: (1, "down"),
         0xE242: (2, "up"), 0xE243: (2, "down")}
AUG_DOT = 0xE1E7
TIMESIG_DIGITS = {cp: cp - 0xE080 for cp in range(0xE080, 0xE08A)}
BARLINE_GLYPHS = set(range(0xE040, 0xE04A))
MET_NOTES = {0xECA2: 2.0, 0xECA3: 2.0, 0xECA5: 1.0, 0xECA7: 0.5, 0xECA9: 0.25}
IGNORED_INFO = {0xE000, 0xE003, 0xE004, 0xE26A, 0xE26B, 0xE0F5, 0xE0F6,
                0xE4CE, 0xECB7}  # braces/brackets, parens, breath, met-dot
DYNAMICS = set(range(0xE520, 0xE550))

# ----------------------------------------- legacy Finale (Sonata-layout) fonts
#
# Born-digital Finale exports (Maestro / Petrucci) place every music symbol as
# an ASCII / MacRoman / PUA-twin codepoint from the old Sonata layout, not a
# SMuFL PUA glyph. We translate them to SMuFL at ingestion so every table and
# check above keys on SMuFL unchanged. legacy_glyph_map.json — verified from
# PDF crops — is the single source of truth for the codepoints; an entry whose
# "smufl" is null means "drop this glyph" (dynamics / articulations the engine
# must never see).

# "FinaleMaestro" / "Finale Maestro" is the SMuFL font shipped with Finale 27+
# (it emits real SMuFL PUA codepoints, e.g. 0xE0A4 noteheadBlack) — NOT the old
# Sonata-layout TrueType "Maestro". It must be classified smufl BEFORE the
# legacy "Maestro" substring below, or its glyphs get run through the legacy map
# (which has no 0xE0xx entries) and every note is dropped as unmapped.
_SMUFL_FONTS = ("Bravura", "Leland", "Petaluma", "Emmentaler",
                "FinaleMaestro", "Finale Maestro")
_LEGACY_FONTS = ("Maestro", "Petrucci", "Sonata", "Opus", "Engraver")
# The SMuFL musical PUA block. The legacy Sonata layout never emits codepoints
# here (its glyphs live at ASCII/MacRoman plus 0xF000-0xF0FF PUA-twins), so a
# codepoint in this range inside a legacy-classified span is a genuine SMuFL
# glyph from a Finale-SMuFL hybrid and is passed through rather than dropped.
_SMUFL_PUA = range(0xE000, 0xF000)
_MUSIC_WHITESPACE = {0x20, 0xA0}   # space / no-break space: drop, never count


def _load_legacy_map():
    """Parse legacy_glyph_map.json (next to this file) into
    {family_key: {int_cp: int_smufl_or_None}}. Fail soft — an empty map plus a
    stderr warning — if the file is missing or unparseable."""
    path = os.path.join(os.path.dirname(__file__), "legacy_glyph_map.json")
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"[vector_extract] WARNING: could not load {path} ({exc}); "
              f"legacy Finale fonts will not be remapped", file=sys.stderr)
        return out
    for fam, table in raw.items():
        if fam in ("families", "_notes") or not isinstance(table, dict):
            continue
        fam_map = {}
        for cp_hex, entry in table.items():
            try:
                cp = int(cp_hex, 16)
            except (TypeError, ValueError):
                continue
            smufl = entry.get("smufl") if isinstance(entry, dict) else None
            fam_map[cp] = int(smufl, 16) if smufl else None
        out[fam] = fam_map
    return out


LEGACY_MAP = _load_legacy_map()


def _music_font_family(font_name):
    """Classify a span font name: 'smufl' (glyphs already SMuFL PUA), 'finale'
    (legacy Sonata-layout codepoints needing remap), or None (not a music
    font). SMuFL indicators are checked BEFORE legacy names so a hybrid like
    'Finale Maestro SMuFL' is treated as SMuFL, not legacy."""
    if not font_name:
        return None
    for k in _SMUFL_FONTS:
        if k in font_name:
            return "smufl"
    if "SMuFL" in font_name:
        return "smufl"
    for k in _LEGACY_FONTS:
        if k in font_name:
            return "finale"
    return None


LETTERS = "CDEFGAB"
STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]

VOICE_ORDER = ["S", "A", "T", "B"]
VOICE_NAMES = {"S": "Soprano", "A": "Alto", "T": "Tenor", "B": "Bass"}


# ------------------------------------------------------------------ dataclasses

@dataclass(eq=False)
class Glyph:
    cp: int
    x: float           # origin x
    y: float           # origin y
    x0: float
    y0: float
    x1: float
    y1: float
    size: float

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2


@dataclass(eq=False)
class Head:
    g: Glyph
    kind: str          # black | half | whole
    beats: float       # base beats before flags/beams/dots
    staff: "Staff" = None
    step: int = 0      # diatonic number (sounding, incl. clef octave shift)
    acc: Optional[int] = None   # printed accidental alter
    stem: Optional["Stem"] = None
    # A shared notehead written for two voices on a divided staff carries an
    # up-stem AND a down-stem (issue #69). `stem` holds the nearer (primary)
    # one; `stem2`, when set, the opposite-direction second stem. Genuine
    # single-stem heads leave stem2 None and behave exactly as before.
    stem2: Optional["Stem"] = None
    dots: int = 0
    dot_ys: list = field(default_factory=list)  # y of each attached aug dot,
    # so a dual-stem head can split its dots between the two voices by position
    grace: bool = False


_BEAM_GROUP_SEQ = [0]


def _next_beam_group():
    _BEAM_GROUP_SEQ[0] += 1
    return _BEAM_GROUP_SEQ[0]


@dataclass(eq=False)
class Stem:
    x: float
    y0: float
    y1: float
    heads: list = field(default_factory=list)
    nbeams: int = 0
    flag: Optional[tuple] = None
    beam_group: Optional[int] = None

    @property
    def direction(self):
        if not self.heads:
            return None
        top = min(h.g.y for h in self.heads)
        bot = max(h.g.y for h in self.heads)
        above = top - self.y0
        below = self.y1 - bot
        return "up" if above > below else "down"


@dataclass(eq=False)
class Event:
    x: float
    kind: str                  # note | rest
    heads: list = field(default_factory=list)   # sorted high->low pitch
    beats: float = 0.0
    dots: int = 0
    staff: "Staff" = None
    voice: Optional[str] = None
    stem_dir: Optional[str] = None
    tie_start: bool = False
    tie_stop: bool = False
    lyric: list = field(default_factory=list)   # verse dicts: {text,syllabic,number}
    unison_assumed: bool = False
    ambiguous: bool = False    # lone whole / centered rest on a shared staff
    beam_group: Optional[int] = None   # id shared by stems under one beam
    nbeams: int = 0                    # beam levels on this event's stem
    whole_measure: bool = False        # SMuFL restWhole (U+E4E3): its true
    # value is the length of the measure it sits in, NOT the fixed 4.0 in RESTS.
    # The provisional 4.0 stays on `beats` but is corrected by the whole-measure-
    # rest normalization pass in assemble() before metering/emission.

    @property
    def total_beats(self):
        b = self.beats
        add = self.beats / 2
        for _ in range(self.dots):
            b += add
            add /= 2
        return b


@dataclass(eq=False)
class Staff:
    top: float
    bot: float
    x0: float
    x1: float
    lines: list
    page: int = 0
    clef: Optional[str] = None
    clef_x: float = 0.0
    key_fifths: int = 0
    system: "System" = None

    @property
    def sp(self):
        return (self.bot - self.top) / 4

    @property
    def mid(self):
        return (self.top + self.bot) / 2

    def step_of(self, y: float):
        """Diatonic number for a notehead center y (sounding pitch)."""
        steps = (self.bot - y) / (self.sp / 2)
        n = round(steps)
        return CLEF_BOTTOM_LINE[self.clef] + n, abs(steps - n)


@dataclass(eq=False)
class System:
    staves: list
    page: int
    bar_xs: list = field(default_factory=list)
    layout: str = "4staff"     # or 2staff
    events: dict = field(default_factory=dict)   # voice -> [Event] (x-sorted)
    ts_beats: Optional[float] = None   # printed time-sig length (quarter units),
    # captured but NOT used for metering (beat sums win — see the note in
    # extract_page); a fallback for whole-measure-rest normalization only.


# ------------------------------------------------------------------- extraction

class Report:
    def __init__(self):
        self.warnings = []
        self.info = []
        self.stats = defaultdict(int)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.info.append(msg)

    def as_dict(self):
        return {"stats": dict(self.stats), "warnings": self.warnings,
                "info": self.info}


def _page_glyphs(page, page_no=0, report=None):
    """All font glyphs on the page with positions. Legacy Finale music fonts
    are remapped to SMuFL codepoints at ingestion (see LEGACY_MAP): glyphs that
    map to null are dropped silently, unknown glyphs are dropped and reported so
    the map can be extended. SMuFL fonts pass through unchanged."""
    music, text_tokens = [], []
    unmapped_seen = set()
    raw = page.get_text("rawdict")
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                font = span["font"]
                fam = _music_font_family(font)
                if fam is not None:
                    fam_map = LEGACY_MAP.get(fam) if fam != "smufl" else None
                    for ch in span["chars"]:
                        cp = ord(ch["c"])
                        if fam != "smufl":
                            # legacy Finale: translate Sonata cp -> SMuFL
                            if cp in _MUSIC_WHITESPACE:
                                continue          # blank advance, never count
                            if fam_map is not None and cp in fam_map:
                                smufl = fam_map[cp]
                                if smufl is None:
                                    continue      # explicit ignore glyph
                                cp = smufl
                            elif cp in _SMUFL_PUA:
                                # Finale-SMuFL hybrid: this span was classified
                                # legacy by name, but the codepoint is a real
                                # SMuFL glyph the legacy layout never uses. Pass
                                # it through unchanged (see _SMUFL_PUA note).
                                pass
                            else:
                                # unknown legacy glyph: drop + record once/page
                                if report is not None:
                                    report.stats["unmapped_music_glyphs"] += 1
                                    raw_cp = ord(ch["c"])
                                    if (fam, raw_cp) not in unmapped_seen:
                                        unmapped_seen.add((fam, raw_cp))
                                        bb = ch["bbox"]
                                        report.note(
                                            f"p{page_no}: unmapped {fam} glyph "
                                            f"0x{raw_cp:X} at "
                                            f"({bb[0]:.0f},{bb[1]:.0f}) "
                                            f"— dropped")
                                continue
                        if report is not None:
                            report.stats["music_glyphs_total"] += 1
                        bb = ch["bbox"]
                        music.append(Glyph(cp, ch["origin"][0],
                                           ch["origin"][1], bb[0], bb[1],
                                           bb[2], bb[3], span["size"]))
                else:
                    # tokenize into words on whitespace / big gaps
                    cur = []
                    for ch in span["chars"]:
                        if ch["c"].isspace():
                            if cur:
                                text_tokens.append(_mk_token(cur, span))
                                cur = []
                            continue
                        if cur and ch["bbox"][0] - cur[-1]["bbox"][2] > span["size"] * 0.6:
                            text_tokens.append(_mk_token(cur, span))
                            cur = []
                        cur.append(ch)
                    if cur:
                        text_tokens.append(_mk_token(cur, span))
    return music, text_tokens


def _mk_token(chars, span):
    text = "".join(c["c"] for c in chars)
    x0 = chars[0]["bbox"][0]
    x1 = chars[-1]["bbox"][2]
    y = chars[0]["origin"][1]
    font = span["font"]
    # italic marks an *alternate verse* (roman verse 1 / italic verse 2) and
    # corroborates expression text; PyMuPDF's italic flag (bit 1) and the ",Italic"
    # font-name suffix agree in this corpus, so OR them for robustness.
    italic = bool(span.get("flags", 0) & 2) or ("italic" in font.lower())
    return {"text": text, "x0": x0, "x1": x1, "cx": (x0 + x1) / 2, "y": y,
            "size": span["size"], "font": font, "italic": italic}


def _page_paths(page):
    """Classified vector paths: staff-candidate hlines, short hlines, vlines,
    filled quads (beam candidates), curves (tie/slur candidates)."""
    long_h, short_h, vlines, quads, curves = [], [], [], [], []
    for d in page.get_drawings():
        items = d["items"]
        ops = "".join(i[0] for i in items)
        if set(ops) <= {"l"}:
            segs = [(i[1], i[2]) for i in items if i[0] == "l"]
            if len(segs) >= 3 and d.get("fill") is not None:
                # filled polyline = beam: keep as a quad, do NOT read its edges
                # as individual staff/bar lines (they may be shallow-slanted).
                xs = [p.x for s in segs for p in s]
                ys = [p.y for s in segs for p in s]
                quads.append((min(xs), min(ys), max(xs), max(ys)))
            else:
                # Finale draws each staff line as several parallel hairline
                # strokes grouped into ONE path, so a stroked line drawing can
                # hold many segments (the old len==1 gate dropped every such
                # staff). Collapse near-collinear horizontal segments into one
                # line per band so a thick line reads as a single staff line —
                # otherwise its 0.7pt thickness splits across the 0.5pt merge
                # tolerance in _find_staves. SMuFL single-segment paths pass
                # through as one line each, unchanged.
                hs = sorted(((min(p1.x, p2.x), max(p1.x, p2.x),
                              (p1.y + p2.y) / 2) for p1, p2 in segs
                             if abs(p2.y - p1.y) < 0.7 and abs(p2.x - p1.x) > 2),
                            key=lambda r: r[2])
                bands = []
                for x0, x1, y in hs:
                    if bands and y - bands[-1][2] <= 1.0:
                        b = bands[-1]
                        bands[-1] = (min(b[0], x0), max(b[1], x1),
                                     (b[2] + y) / 2)
                    else:
                        bands.append((x0, x1, y))
                for x0, x1, y in bands:
                    (long_h if x1 - x0 > 80 else short_h).append((x0, x1, y))
                for p1, p2 in segs:
                    dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                    if dx < 1.2 and dy > 2:
                        vlines.append(((p1.x + p2.x) / 2, min(p1.y, p2.y),
                                       max(p1.y, p2.y)))
        elif "c" in ops and d.get("fill") is not None:
            pts = []
            for i in items:
                if i[0] == "c":
                    pts.extend([i[1], i[2], i[3], i[4]])
                elif i[0] == "l":
                    pts.extend([i[1], i[2]])
            if pts:
                r = d["rect"]
                curves.append((r.x0, r.y0, r.x1, r.y1, pts))
    return long_h, short_h, vlines, quads, curves


def _find_staves(long_h, page_no, report):
    """Cluster long horizontal lines into 5-line staves.

    Robust to non-staff long lines (lyric melisma extenders, text rules):
    only lines close to the page's maximum line width are staff candidates,
    then a sliding 5-line window requires near-equal gaps.
    """
    if not long_h:
        return []
    max_w = max(x1 - x0 for x0, x1, y in long_h)
    cands = [(x0, x1, y) for x0, x1, y in long_h if x1 - x0 >= 0.55 * max_w]
    # merge duplicated segments at the same y (indented first system etc.).
    # Legacy Finale draws a staff line as several overlaid hairline strokes
    # from separate paths; _page_paths bands them per-path but leaves near-dup
    # bands up to ~1pt apart. A 0.5pt tolerance left a 0.5pt-split line as SIX
    # lines in one band, so the 5-line window rejected the staff (a whole
    # system's staff went undetected — see 01-ManyYears). Real staff lines sit
    # ~one staff-space (>=4pt) apart, so a 1pt merge tolerance is safe.
    ys = {}   # first-seen y -> [x0, x1, y_sum, n]
    for x0, x1, y in sorted(cands, key=lambda r: r[2]):
        key = None
        for yy in ys:
            if abs(yy - y) < 1.0:
                key = yy
                break
        if key is None:
            ys[y] = [x0, x1, y, 1]
        else:
            e = ys[key]
            e[0] = min(e[0], x0)
            e[1] = max(e[1], x1)
            e[2] += y      # average merged duplicates so the line sits at its
            e[3] += 1      # true centre (a low-biased key would skew the gap-
    # evenness test below and drop an otherwise valid staff)
    items = sorted((yc / n, x0, x1) for x0, x1, yc, n in ys.values())
    staves = []
    i = 0
    skipped = []
    while i + 5 <= len(items):
        win = items[i:i + 5]
        gaps = [win[k + 1][0] - win[k][0] for k in range(4)]
        if 2.0 <= min(gaps) and max(gaps) <= 12.0 and \
                max(gaps) - min(gaps) < 1.0:
            staves.append(Staff(top=win[0][0], bot=win[4][0],
                                x0=min(c[1] for c in win),
                                x1=max(c[2] for c in win),
                                lines=[c[0] for c in win], page=page_no))
            i += 5
        else:
            skipped.append(items[i])
            i += 1
    skipped.extend(items[i:] if not staves else [])
    if skipped:
        report.note(f"p{page_no}: {len(skipped)} long hlines not part of any "
                    f"5-line staff (extenders/rules) — ignored")
    return staves


def _connector_groups(ss, vlines):
    """Group vertically-adjacent staves joined by a connector vline into
    systems. A vline *connects* two adjacent staves when it bridges the gap
    between them — its top reaches into/above the upper staff and its bottom
    into/below the lower staff. This catches the system-start barline/brace
    (drawn at the left edge spanning every staff of a system) and any interior
    barline that spans more than one staff, while rejecting stems and ledger
    strokes (far too short to cross a 50-60pt inter-staff gap). `ss` must be
    sorted by `top`. Returns a list of ascending staff-index lists (systems);
    staves no connector touches come back as singletons."""
    n = len(ss)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for x, y0, y1 in vlines:
        for i in range(n - 1):
            a, b = ss[i], ss[i + 1]
            tol = 0.6 * a.sp
            if y0 <= a.bot + tol and y1 >= b.top - tol:
                union(i, i + 1)
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    return [sorted(g) for _, g in sorted(comps.items())]


def _group_systems(staves, music_glyphs, vlines, page_no, report):
    """Group staves into systems. Preference order (most robust first):
      1. SMuFL bracket glyphs (E003 top / E004 bottom) when present;
      2. system connector vlines — the initial barline/brace stroke that
         bridges the staves of a system, plus any interior barline spanning
         more than one staff (see _connector_groups). This is essential for
         legacy Finale choral engravings, where LYRICS printed between the
         staves inflate the inter-staff gap past any fixed multiple of the
         staff height. The gap heuristic then reads every staff as its own
         1-staff system, so `_system_layout` maps them all to Soprano in turn
         and the whole score collapses into one concatenated voice;
      3. no evidence at all -> each staff is its own single-staff system.
         There is deliberately NO vertical-gap fallback here (see below)."""
    tops = sorted(g.y for g in music_glyphs if g.cp == 0xE003)
    bots = sorted(g.y for g in music_glyphs if g.cp == 0xE004)
    ss = sorted(staves, key=lambda s: s.top)
    systems = []
    if tops and len(tops) == len(bots):
        # (1) SMuFL bracket glyphs — primary
        for t, b in zip(tops, bots):
            grp = [s for s in ss if t - 8 <= s.top and s.bot <= b + 8]
            if grp:
                systems.append(System(staves=grp, page=page_no))
        grouped = {id(s) for sy in systems for s in sy.staves}
        left = [s for s in ss if id(s) not in grouped]
        if left:
            report.warn(f"p{page_no}: {len(left)} staves outside any bracket "
                        f"— grouped as their own system")
            systems.append(System(staves=left, page=page_no))
    else:
        groups = _connector_groups(ss, vlines)
        if any(len(g) >= 2 for g in groups):
            # (2) evidence-based: connector lines bridge each system's staves
            for g in groups:
                systems.append(System(staves=[ss[i] for i in g],
                                      page=page_no))
            multi = sum(1 for g in groups if len(g) >= 2)
            report.note(f"p{page_no}: grouped {len(ss)} staves into "
                        f"{len(systems)} systems via {multi} connector "
                        f"line(s) (no bracket glyphs)")
        else:
            # (3) no bracket glyph and no connector line joins ANY two staves:
            # there is no positive evidence that any staves share a system, so
            # each staff is emitted as its own single-staff system.
            #
            # A vertical-gap heuristic used to live here (merge adjacent staves
            # when their gap < 2.5 staff heights). For the born-digital chant
            # corpus it was actively harmful (issue #52, Mode A): single-line
            # troparia are engraved ~2.0-2.6 staff-heights apart -- straddling
            # any fixed multiple -- so the heuristic fused N stacked single-staff
            # chant systems into one phantom N-staff "system", which
            # _system_layout then mapped to S/A/T/B/X4..., inventing voices that
            # never existed on the page and collapsing the melody. A 150-piece
            # sweep found 74 pieces hit this false merge; every genuinely
            # multi-staff piece in the corpus is instead grouped by the
            # connector-line evidence in branch (2) (the system-start barline
            # spans exactly the staves of one system -- commit 62e54ee), so
            # nothing here should ever have been merged. Staves with no
            # connector are exactly the single-staff systems of monophonic
            # chant; keep them separate.
            for s in ss:
                systems.append(System(staves=[s], page=page_no))
    systems.sort(key=lambda sy: sy.staves[0].top)
    return systems


def _assign_staff(g, staves, max_ledger=6.0):
    best, bd = None, 1e9
    for s in staves:
        if s.top - max_ledger * s.sp <= g.y <= s.bot + max_ledger * s.sp:
            d = 0.0 if s.top <= g.y <= s.bot else min(abs(g.y - s.top),
                                                      abs(g.y - s.bot))
            if d < bd:
                best, bd = s, d
    return best


def _time_sig_beats(ts_digits):
    """Best-effort measure length (in quarter-note beats) from printed time-sig
    digit glyphs, e.g. a 3-over-4 stack -> 3.0. Returns None when the digits do
    NOT form a single clean single-digit numerator-over-denominator pair — we
    never guess (callers fall back to the documented 4.0 default). Used only as
    a last resort by whole-measure-rest normalization when a measure has no
    real-content voice to take the length from."""
    if len(ts_digits) < 2:
        return None
    # cluster into vertical stacks by x proximity (numerator above denominator)
    xs = sorted(ts_digits, key=lambda g: g.cx)
    stacks, cur = [], [xs[0]]
    for g in xs[1:]:
        w = max(cur[-1].x1 - cur[-1].x0, g.x1 - g.x0, 1.0)
        if abs(g.cx - cur[-1].cx) < 1.2 * w:
            cur.append(g)
        else:
            stacks.append(cur)
            cur = [g]
    stacks.append(cur)
    # accept only an unambiguous single stack of exactly two digits
    stacks = [st for st in stacks if len(st) >= 2]
    if len(stacks) != 1 or len(stacks[0]) != 2:
        return None
    st = sorted(stacks[0], key=lambda g: g.y)   # top (small y) = numerator
    num = TIMESIG_DIGITS[st[0].cp]
    den = TIMESIG_DIGITS[st[1].cp]
    if num <= 0 or den <= 0:
        return None
    return num * 4.0 / den


def extract_page(page, page_no, report, measure_offset, tempo_state):
    music, tokens = _page_glyphs(page, page_no, report)
    long_h, short_h, vlines, quads, curves = _page_paths(page)
    staves = _find_staves(long_h, page_no, report)
    if not staves:
        report.note(f"p{page_no}: no staves — skipped (title/blank page)")
        return [], measure_offset
    systems = _group_systems(staves, music, vlines, page_no, report)
    for sy in systems:
        for s in sy.staves:
            s.system = sy

    all_staves = [s for sy in systems for s in sy.staves]

    # dominant music-glyph size = staff size; smaller = grace/metronome text
    sizes = defaultdict(int)
    for g in music:
        if g.cp in NOTEHEADS:
            sizes[round(g.size)] += 1
    main_size = max(sizes, key=sizes.get) if sizes else 20

    # ---- clefs
    for g in music:
        if g.cp in CLEFS:
            s = _assign_staff(g, all_staves, max_ledger=2)
            if s is None:
                continue
            if s.clef is None or g.x < s.clef_x:
                s.clef = CLEFS[g.cp]
                s.clef_x = g.x
    for s in all_staves:
        if s.clef is None:
            report.warn(f"p{page_no}: staff at y~{s.top:.0f} has no clef — "
                        f"assuming treble")
            s.clef, s.clef_x = "treble", s.x0

    # ---- noteheads
    heads = []
    for g in music:
        if g.cp in NOTEHEADS:
            kind, beats = NOTEHEADS[g.cp]
            if g.size < 0.75 * main_size:
                report.stats["grace_or_cue_heads_skipped"] += 1
                continue
            s = _assign_staff(g, all_staves)
            if s is None:
                report.warn(f"p{page_no}: notehead at ({g.x:.0f},{g.y:.0f}) "
                            f"not near any staff — dropped")
                continue
            h = Head(g=g, kind=kind, beats=beats, staff=s)
            h.step, err = s.step_of(g.y)
            if err > 0.3:
                report.warn(f"p{page_no}: notehead at ({g.x:.0f},{g.y:.0f}) "
                            f"off-grid by {err:.2f} half-spaces")
            heads.append(h)

    # ---- parenthesized (optional/divisi) noteheads -> excluded from rhythm
    for g in music:
        if g.cp == 0xE0F5:  # noteheadParenthesisLeft
            for h in heads:
                sp = h.staff.sp
                if -0.5 <= h.g.x0 - g.x < 2.2 * sp and \
                        abs(h.g.y - g.y) < 0.7 * sp:
                    h.grace = True  # reuse flag: excluded from events
                    report.stats["parenthesized_optional_notes_skipped"] += 1
    if any(h.grace for h in heads):
        report.note(f"p{page_no}: parenthesized optional notes excluded "
                    f"(divisi alternatives; see stats)")
    heads = [h for h in heads if not h.grace]

    # ---- key signatures (accidentals in the clef zone, before first head)
    first_head_x = {}
    for h in heads:
        k = id(h.staff)
        if k not in first_head_x or h.g.x < first_head_x[k]:
            first_head_x[k] = h.g.x
    keysig_glyphs = set()
    for s in all_staves:
        zone_end = min(first_head_x.get(id(s), s.x1),
                       s.clef_x + 16 * s.sp)
        accs = [g for g in music if g.cp in ACCIDENTALS
                and s.top - 2 * s.sp < g.y < s.bot + 2 * s.sp
                and s.clef_x < g.x < zone_end]
        sharps = sum(1 for g in accs if ACCIDENTALS[g.cp] == 1)
        flats = sum(1 for g in accs if ACCIDENTALS[g.cp] == -1)
        if sharps and flats:
            report.warn(f"p{page_no}: staff y~{s.top:.0f}: mixed key-sig "
                        f"accidentals ({sharps}#, {flats}b)")
        s.key_fifths = sharps if sharps else -flats
        keysig_glyphs.update(id(g) for g in accs)

    # ---- time signature digits (none in the Antiochian corpus, but handled)
    ts_digits = [g for g in music if g.cp in TIMESIG_DIGITS]
    if ts_digits:
        report.note(f"p{page_no}: time-signature digits present "
                    f"({len(ts_digits)}) — emitted from beat sums anyway")
        # Capture (don't meter with) the printed length per system, as a
        # fallback for whole-measure-rest normalization (see assemble()).
        for sy in systems:
            top = min(s.top for s in sy.staves)
            bot = max(s.bot for s in sy.staves)
            b = _time_sig_beats([g for g in ts_digits
                                 if top - 2 < g.y < bot + 2])
            if b is not None:
                sy.ts_beats = b

    # ---- stems & barlines from vlines
    # A head attaches to the stem nearest one of its EDGES (up-stems sit at
    # the right edge, down-stems at the left; chord seconds alternate sides).
    # One stem per head — unison primes (S half + A quarter on one pitch)
    # otherwise get cross-attached.
    #
    # Minimum stem height: some genuine half-note stems render shorter than
    # the "standard" length and were falling just under the old 1.5*sp cutoff
    # (measured on real PDF vlines: 1.23*sp-1.50*sp across several pieces/
    # fonts -- e.g. mgf_0306aba_dormition.2ndant 6.12pt/6.96pt at sp=4.98
    # (1.23*sp/1.40*sp), The_King_of_Heaven 7.26pt/7.69pt at sp=5.13
    # (1.42*sp/1.50*sp) -- each confirmed by rendering the source PDF: a
    # real half-note stem sitting right at the notehead, not a hairline/tie
    # artifact). 1.2*sp keeps a small margin below the weakest measured case
    # while still excluding short unrelated fragments.
    stems, bar_candidates = [], []
    stem_recs = []
    for x, y0, y1 in vlines:
        s_near = _assign_staff(Glyph(0, x, (y0 + y1) / 2, x, y0, x, y1, 0),
                               all_staves)
        if s_near is None:
            continue
        sp = s_near.sp
        if y1 - y0 < 1.2 * sp:
            continue
        stem_recs.append((x, y0, y1, sp))
    best_stem = {}   # head id -> (score, rec)
    for rec in stem_recs:
        x, y0, y1, sp = rec
        for h in heads:
            if h.kind == "whole":     # wholes never carry stems
                continue
            if h.g.x0 - 1.0 <= x <= h.g.x1 + 1.0 and \
                    y0 - 0.75 * sp <= h.g.y <= y1 + 0.75 * sp:
                score = min(abs(x - h.g.x0), abs(x - h.g.x1))
                cur = best_stem.get(id(h))
                if cur is None or score < cur[0]:
                    best_stem[id(h)] = (score, rec)
    by_rec = defaultdict(list)
    for h in heads:
        got = best_stem.get(id(h))
        if got is not None:
            by_rec[got[1]].append(h)
    for rec in stem_recs:
        x, y0, y1, sp = rec
        attached = by_rec.get(rec, [])
        if attached:
            st = Stem(x=x, y0=y0, y1=y1, heads=attached)
            for h in attached:
                h.stem = st
            stems.append(st)
        else:
            bar_candidates.append((x, y0, y1))

    # ---- shared-notehead DUAL stems (issue #69)
    # A unison (or divided a2) written for two voices on ONE shared staff puts
    # both an up-stem and a down-stem on the SAME notehead. The per-head match
    # above claims only the nearer stem; the opposite one is left unclaimed and
    # would otherwise orphan its flag ("flag matched no stem" — issue #59's
    # measured signature). Rescue such an unclaimed vline as a genuine SECOND
    # stem only on STRONG evidence: it sits at the head's OTHER edge, points the
    # OPPOSITE way, terminates AT the notehead, and runs a real stem length away
    # from it — and only on a 2-voices-per-staff (divided) staff, where a second
    # stem actually means a second voice. This is deliberately conservative:
    # marking a head dual re-routes its flag and aug dots per voice (see
    # _build_system_events / _head_dots), so a spurious second stem would
    # mis-duration a note that was fine. This pass ONLY appends to `stems` (for
    # flag/beam matching); it leaves bar_candidates untouched, so barline
    # detection stays byte-identical (a claimed vline is a short notehead stem,
    # never staff-spanning, so its lingering in bar_candidates is a no-op).
    # Every genuine single-stem head keeps stem2 None and stays byte-identical.
    claimed_recs = {best_stem[id(h)][1] for h in heads if id(h) in best_stem}
    for rec in stem_recs:
        x, y0, y1, sp = rec
        if rec in claimed_recs:
            continue
        best_h, best_de = None, 1e9
        for h in heads:
            if h.kind == "whole" or h.stem is None or h.stem2 is not None:
                continue
            if h.staff.system is None or len(h.staff.system.staves) != 2:
                continue      # dual stem => two voices => only on a shared staff
            if not (h.g.x0 - 1.0 <= x <= h.g.x1 + 1.0 and
                    y0 - 0.75 * sp <= h.g.y <= y1 + 0.75 * sp):
                continue
            tdir = "up" if (h.g.y - y0) > (y1 - h.g.y) else "down"
            if tdir == h.stem.direction:
                continue      # must oppose the primary stem's direction
            if tdir == "up":  # head at the stem's bottom, stem rising above it
                if abs(y1 - h.g.y) > 0.5 * sp or (h.g.y - y0) < 1.3 * sp:
                    continue
                edge = h.g.x1
            else:             # head at the stem's top, stem falling below it
                if abs(y0 - h.g.y) > 0.5 * sp or (y1 - h.g.y) < 1.3 * sp:
                    continue
                edge = h.g.x0
            de = abs(x - edge)
            if de <= 1.0 and de < best_de:
                best_de, best_h = de, h
        if best_h is not None:
            st = Stem(x=x, y0=y0, y1=y1, heads=[best_h])
            best_h.stem2 = st
            stems.append(st)
            report.stats["dual_stems_recovered"] += 1
        else:
            bar_candidates.append((x, y0, y1))

    # systemic barlines (tall vlines spanning systems) + per-staff barlines
    for sy in systems:
        top, bot = sy.staves[0].top, sy.staves[-1].bot
        xs = []
        min_x = max(s.clef_x for s in sy.staves) + 2  # skip system-start line
        for x, y0, y1 in bar_candidates:
            covers_staff = any(abs(y0 - s.top) < 2.5 and abs(y1 - s.bot) < 2.5
                               for s in sy.staves)
            spans_system = y0 < top + 2.5 and y1 > bot - 2.5
            if covers_staff or spans_system:
                if min_x <= x <= sy.staves[0].x1 + 2:
                    xs.append(x)
        # barline glyphs (repeat/heavy barlines are font glyphs in Dorico)
        for g in music:
            if g.cp in BARLINE_GLYPHS and top - 10 < g.y1 and g.y0 < bot + 10:
                xs.append(g.x)
                report.note(f"p{page_no}: barline glyph U+{g.cp:04X} at "
                            f"x={g.x:.0f} (repeat/heavy) treated as barline")
        xs.sort()
        merged = []
        for x in xs:
            if merged and x - merged[-1] < 4.0:
                continue
            merged.append(x)
        sy.bar_xs = merged
        if not merged:
            report.warn(f"p{page_no}: system at y~{top:.0f} has no barlines "
                        f"— whole system treated as one measure")
            sy.bar_xs = [sy.staves[0].x1 + 1]

    # ---- beams -> stems
    for (qx0, qy0, qx1, qy1) in quads:
        qh = qy1 - qy0
        qw = qx1 - qx0
        s_near = _assign_staff(Glyph(0, qx0, (qy0 + qy1) / 2, qx0, qy0,
                                     qx1, qy1, 0), all_staves)
        # min width 0.7*sp keeps 16th-stub beams; slanted beams have tall
        # bboxes, so the height cap is generous
        if s_near is None or qw < 0.7 * s_near.sp or qh > 3.5 * s_near.sp:
            continue
        hit_stems = []
        for st in stems:
            if qx0 - 1.0 <= st.x <= qx1 + 1.0 and \
                    qy0 - 1.5 * s_near.sp <= st.y0 <= qy1 + 1.5 * s_near.sp or \
                    qx0 - 1.0 <= st.x <= qx1 + 1.0 and \
                    qy0 - 1.5 * s_near.sp <= st.y1 <= qy1 + 1.5 * s_near.sp:
                st.nbeams += 1
                hit_stems.append(st)
        if len(hit_stems) < 2:
            report.stats["beam_quads_with_lt2_stems"] += 1
        # union stems joined by this quad into one beam group
        gids = [st.beam_group for st in hit_stems if st.beam_group is not None]
        gid = gids[0] if gids else _next_beam_group()
        for st in stems:
            if st.beam_group in gids[1:]:
                st.beam_group = gid
        for st in hit_stems:
            st.beam_group = gid

    # ---- flags -> stems
    # A flag only ever sits at the end of ITS OWN stem (an "up" flag hooks
    # off an up-stem's top, a "down" flag off a down-stem's bottom) -- it can
    # never legitimately attach to a stem pointing the other way. The old
    # code scored every stem on distance alone, so a same-x wrong-direction
    # stem belonging to a different note/voice could out-score the correct
    # one purely by sitting a little closer in x (measured on
    # A_Precious_Adornment_II p1: the true up-stem was 12.6pt away at
    # dx-weighted score 14.2, but a same-column down-stem 4pt away scored
    # 6.6 and would have won without this filter). Filtering by direction
    # first removes that silent cross-voice mis-attachment risk even though,
    # in this corpus, the dominant failure mode turned out to be a different
    # (out-of-scope) one -- see the issue notes.
    for g in music:
        if g.cp in FLAGS:
            n, direction = FLAGS[g.cp]
            best, bd = None, 1e9
            for st in stems:
                if st.direction != direction:
                    continue
                d = abs(st.x - g.x)
                end_y = st.y0 if direction == "up" else st.y1
                d += abs(end_y - g.y) * 0.2
                if d < bd:
                    best, bd = st, d
            if best is not None and bd < 6:
                best.flag = (n, direction)
            else:
                report.warn(f"p{page_no}: flag at ({g.x:.0f},{g.y:.0f}) "
                            f"matched no stem")

    # ---- accidentals -> heads (excluding key signatures)
    for g in music:
        if g.cp in ACCIDENTALS and id(g) not in keysig_glyphs:
            s = _assign_staff(g, all_staves)
            if s is None:
                continue
            cands = [h for h in heads if h.staff is s
                     and 0 < h.g.x0 - g.x1 < 2.5 * s.sp
                     and abs(h.g.y - g.y) < 0.7 * s.sp]
            if cands:
                h = min(cands, key=lambda h: h.g.x0 - g.x1)
                h.acc = ACCIDENTALS[g.cp]
            else:
                report.warn(f"p{page_no}: accidental at ({g.x:.0f},{g.y:.0f}) "
                            f"matched no notehead")

    # ---- augmentation dots -> heads
    # NOTE: an earlier version of this fix also widened the lower bound to
    # -1.1*sp for "whole"/"half" heads, to admit the generous bbox side-
    # bearing measured on one Toensing whole note (Gladsome_Light_20Toensing
    # p5). That widening was reverted: on the broader corpus it let a dot
    # prefer the wrong nearby head in a chord/stacked-interval passage
    # (CarolsofNativity-Set2 p3-p16: 5 dots re-attached with negative dx,
    # net REGRESSION of measures_with_consistent_beat_sums from 274/297 to
    # 270/297 -- confirmed by isolating this one change with the other two
    # fixes held constant). Left at the original strict "0 <" edge; the
    # Gladsome near-miss is deliberately left unfixed rather than risk
    # collateral silent re-duration elsewhere -- see issue notes.
    for g in music:
        if g.cp == AUG_DOT:
            if g.size < 0.75 * main_size:
                continue  # cue/grace-sized dot; its notehead was excluded too
            s = _assign_staff(g, all_staves)
            if s is None:
                continue
            cands = [h for h in heads if h.staff is s
                     and 0 < g.cx - h.g.x1 < 3.0 * s.sp
                     and abs(h.g.y - g.y) < 0.8 * s.sp]
            if cands:
                h = min(cands, key=lambda h: g.cx - h.g.x1)
                h.dots += 1
                h.dot_ys.append(g.y)
            else:
                # The same dot glyph also draws repeat-barline dots (both
                # legacy fonts reuse one "." for both -- see
                # legacy_glyph_map.json's note on 0x2E) and this engine has
                # no repeat-sign model. A dot with no notehead in reach that
                # also sits right next to a barline, or before this staff's
                # very first note (a start-of-system repeat sign), is that
                # decoration rather than a missed rhythm attachment: don't
                # report a defect that was never one. Verified by rendering
                # the source PDF at several such sites (hilko_star_antiphon,
                # receive_ye-tikey_zes, theophany_series1 p18, all_saints_
                # series p9 -- all confirmed repeat dots next to a barline).
                bar_xs = s.system.bar_xs if s.system else []
                near_bar = any(abs(bx - g.cx) < 2.0 * s.sp for bx in bar_xs)
                before_first_note = g.cx < first_head_x.get(id(s), 1e18)
                if near_bar or before_first_note:
                    report.stats["repeat_sign_dots_ignored"] += 1
                    continue
                report.warn(f"p{page_no}: augmentation dot at "
                            f"({g.x:.0f},{g.y:.0f}) matched no notehead")

    # ---- tempo (metronome marks: met-note glyph + '= NN' text, all of them)
    for g in music:
        if g.cp not in MET_NOTES:
            continue
        for t in tokens:
            m = re.match(r"=?\s*(\d{2,3})$", t["text"].replace(" ", ""))
            if m and abs(t["y"] - g.y) < 12 and 0 < t["x0"] - g.x < 60:
                unit = MET_NOTES[g.cp]
                mark = {"page": page_no, "x": g.x, "y": g.y,
                        "per_minute": int(m.group(1)), "unit": unit,
                        "qpm": int(m.group(1)) * unit}
                if not any(mk["page"] == page_no and abs(mk["x"] - g.x) < 4
                           for mk in tempo_state["marks"]):
                    tempo_state["marks"].append(mark)
                    if tempo_state.get("bpm") is None:
                        tempo_state["bpm"] = mark["qpm"]
                    report.note(f"p{page_no}: tempo mark -> quarter = "
                                f"{mark['qpm']:.0f} at x={g.x:.0f}")
                break

    # ---- build events per system
    for sy in systems:
        sy.layout = _system_layout(sy, report, page_no)
        _build_system_events(sy, heads, stems, music, report, page_no)
        _attach_lyrics(sy, tokens, report, page_no)

    # ---- ties (same-pitch curves)
    _apply_ties(systems, curves, report, page_no)

    return systems, measure_offset


def _system_layout(sy, report, page_no):
    n = len(sy.staves)
    if n == 4:
        return "4staff"
    if n == 2:
        return "2staff"
    if n == 1:
        report.warn(f"p{page_no}: single-staff system — treated as Soprano")
        return "1staff"
    report.warn(f"p{page_no}: unexpected {n}-staff system — mapping "
                f"staves to S/A/T/B in order")
    return "4staff"


def _staff_voices(sy):
    """voice(s) carried by each staff of the system."""
    if sy.layout == "2staff":
        return {id(sy.staves[0]): ("S", "A"), id(sy.staves[1]): ("T", "B")}
    out = {}
    for i, s in enumerate(sy.staves):
        out[id(s)] = (VOICE_ORDER[i] if i < 4 else f"X{i}",)
    return out


def _head_dots(h, st):
    """Augmentation dots for head `h` as carried by stem `st` (`st` is h's
    PRIMARY stem here; the partner voice is then filled by the reconciliation's
    unison duplication, which copies this resolved count). A single-stem head
    gives ALL its dots (unchanged -- keeps every non-dual note byte-identical,
    quirks like duplicate dot glyphs included). A shared-notehead dual-stem
    head (issue #69) resolves its dots PER VOICE:

      * a divided pair prints one dot per voice, straddling the head -> the
        stem's voice takes the dot on its side of the head center (e.g.
        A_Precious_Adornment_II's dotted-half unison, else both dots merge onto
        one head and mis-read as double-dotted, over by 0.5 a beat);
      * a plain unison prints ONE dot for BOTH voices -> it counts for either
        (else the note reads undotted, short by the dot's value).

    Dots drawn as duplicate glyphs at the same spot (a born-digital quirk) are
    de-duplicated first so the shared single dot isn't mistaken for a stack."""
    if h.stem2 is None:
        return h.dots
    distinct = []
    for y in sorted(h.dot_ys):
        if not distinct or y - distinct[-1] > 1.5:
            distinct.append(y)
    if len(distinct) <= 1:
        return len(distinct)          # a single shared dot -> both voices
    up_dots = sum(1 for y in distinct if y <= h.g.y)
    return up_dots if st.direction == "up" else len(distinct) - up_dots


def _build_system_events(sy, all_heads, all_stems, music, report, page_no):
    staff_ids = {id(s) for s in sy.staves}
    heads = [h for h in all_heads if id(h.staff) in staff_ids]
    sv = _staff_voices(sy)
    events = defaultdict(list)
    ambiguous_out = defaultdict(list)

    # 1. stemmed events (chords grouped by stem). A head is matched to `st` as
    # its primary stem OR (issue #69) its opposite-direction second stem, so a
    # shared-notehead dual stem's flag is claimed and the head is recognised as
    # dual; the second-stem-only event is then skipped (see below) and its
    # partner voice filled by the reconciliation's unison duplication.
    used = set()
    for st in all_stems:
        st_heads = [h for h in st.heads if id(h.staff) in staff_ids
                    and (h.stem is st or h.stem2 is st)]
        if not st_heads:
            continue
        # A recovered opposite-direction SECOND stem (issue #69) exists only to
        # (a) claim its otherwise-orphaned flag ("flag matched no stem") and
        # (b) mark its notehead as dual so the PRIMARY event below resolves aug
        # dots to the right voice. The partner voice's note is then populated by
        # the shared-staff reconciliation's unison duplication, which already
        # balances beat sums. Emitting a separate event per stem instead
        # double-read beamed unison runs -- the two stems of one notehead catch
        # beam quads asymmetrically, desyncing a homophonic S+A eighth run into
        # eighths vs quarters -- so skip the second-stem-only event here.
        if all(h.stem2 is st for h in st_heads):
            used.update(id(h) for h in st_heads)
            continue
        staff = st_heads[0].staff
        beats = st_heads[0].beats
        if st_heads[0].kind == "black":
            if st.flag:
                beats = 1.0 / (2 ** st.flag[0])
            elif st.nbeams:
                beats = 1.0 / (2 ** st.nbeams)
        ev = Event(x=min(h.g.x0 for h in st_heads), kind="note",
                   heads=sorted(st_heads, key=lambda h: -h.step),
                   beats=beats, dots=max(_head_dots(h, st) for h in st_heads),
                   staff=staff, stem_dir=st.direction,
                   beam_group=st.beam_group, nbeams=st.nbeams)
        used.update(id(h) for h in st_heads)
        _route_event(ev, sv, events, ambiguous_out, report, page_no)

    # 2. unstemmed heads (whole notes) — group stacked ones
    loose = sorted([h for h in heads if id(h) not in used],
                   key=lambda h: (h.g.x0, h.g.y))
    grouped = []
    for h in loose:
        if h.kind != "whole":
            report.warn(f"p{page_no}: {h.kind} notehead without stem at "
                        f"({h.g.x:.0f},{h.g.y:.0f}) — kept as-is")
        placed = False
        for grp in grouped:
            if grp[0].staff is h.staff and abs(grp[0].g.x0 - h.g.x0) < 2.0 * h.staff.sp:
                grp.append(h)
                placed = True
                break
        if not placed:
            grouped.append([h])
    for grp in grouped:
        ev = Event(x=min(h.g.x0 for h in grp), kind="note",
                   heads=sorted(grp, key=lambda h: -h.step),
                   beats=grp[0].beats, dots=max(h.dots for h in grp),
                   staff=grp[0].staff, stem_dir=None)
        _route_event(ev, sv, events, ambiguous_out, report, page_no)

    # 3. rests
    ambiguous = ambiguous_out       # staff id -> events needing voice choice
    for g in music:
        if g.cp in RESTS:
            s = _assign_staff(g, sy.staves, max_ledger=3)
            if s is None or id(s) not in staff_ids:
                continue
            ev = Event(x=g.x0, kind="rest", beats=RESTS[g.cp], staff=s,
                       whole_measure=(g.cp == 0xE4E3))
            voices = sv[id(s)]
            if len(voices) == 1:
                ev.voice = voices[0]
                events[voices[0]].append(ev)
            else:
                off = (g.y - s.mid) / s.sp
                if off < -0.9:
                    ev.voice = voices[0]
                    events[voices[0]].append(ev)
                elif off > 0.9:
                    ev.voice = voices[1]
                    events[voices[1]].append(ev)
                else:  # centered rest: shared or one-voice — decided later
                    ev.ambiguous = True
                    ambiguous[id(s)].append(ev)

    for v in events:
        events[v].sort(key=lambda e: e.x)
    sy.events = dict(events)

    # 4. shared-staff reconciliation: unison duplication + ambiguous routing
    if sy.layout == "2staff":
        _reconcile_shared(sy, ambiguous, report, page_no)
    else:
        # ambiguity can't exist on single-voice staves; assign directly
        for sid, evs in ambiguous.items():
            for e in evs:
                v = sv[sid][0]
                e.voice = v
                sy.events.setdefault(v, []).append(e)
        for v in sy.events:
            sy.events[v].sort(key=lambda e: e.x)
        _merge_divisi(sy, report, page_no)


def _route_event(ev, sv, events, ambiguous_out, report, page_no):
    voices = sv[id(ev.staff)]
    if len(voices) == 1:
        ev.voice = voices[0]
        events[voices[0]].append(ev)
        return
    up, down = voices
    if ev.stem_dir == "up":
        ev.voice = up
        events[up].append(ev)
    elif ev.stem_dir == "down":
        ev.voice = down
        events[down].append(ev)
    else:
        # unstemmed (whole notes): stacked pair or lone — both are voice
        # decisions resolved by the measure-level search
        ev.ambiguous = True
        ambiguous_out[id(ev.staff)].append(ev)
    # NOTE: single-stem chords stay whole in the stem voice; donating the
    # inner head to the partner voice is a choice for the measure-level
    # search (_reconcile_shared), constrained by beat sums.


def _clone_event(ev, heads, voice):
    return Event(x=ev.x, kind=ev.kind, heads=list(heads), beats=ev.beats,
                 dots=ev.dots, staff=ev.staff, voice=voice,
                 stem_dir=ev.stem_dir, unison_assumed=ev.unison_assumed,
                 beam_group=ev.beam_group, nbeams=ev.nbeams,
                 whole_measure=ev.whole_measure)


def _cluster_columns(events, sp):
    """Cluster events into time columns by x (stacked seconds are offset by
    up to ~1.2 staff spaces; consecutive notes are >= 2 spaces apart)."""
    xs = sorted(e.x for e in events)
    cols = []
    for x in xs:
        if cols and x - cols[-1][-1] < 1.5 * sp:
            cols[-1].append(x)
        else:
            cols.append([x])
    centers = [sum(c) / len(c) for c in cols]

    def col_index(e):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - e.x))
    return centers, col_index


def _reconcile_shared(sy, pending_by_staff, report, page_no):
    """Shared-staff (2 voices per staff) reconciliation as a measure-level
    constrained search.

    Definite facts from engraving: stem-up events belong to the upper voice,
    stem-down to the lower. The genuinely ambiguous notations are:
      * written unisons (one stem, one head, both voices sing it),
      * single-stem chords (top head = upper voice + bottom = lower voice,
        OR a divisi chord entirely within one voice),
      * lone whole notes (no stem at all),
      * stacked/side-by-side whole-note pairs,
      * centered rests (shared or one voice resting mid-divergence).

    A DFS walks the note columns of each measure, branching at each ambiguous
    choice, keeping both voices' beat cursors. Solutions must end with both
    voices at the same beat count, and the two staves of the system must
    agree on the measure length. Small prior costs encode engraving
    conventions to break ties. Every non-trivial choice is reported.
    """
    pairs = [("S", "A", sy.staves[0]), ("T", "B", sy.staves[1])]
    ranges = _measure_ranges(sy.staves[0], sy.bar_xs)
    per_measure = []
    for mi, (lo, hi) in enumerate(ranges):
        # A ragged final measure (staves of differing width) can make one
        # staff's range list shorter than the reference staff's, which used to
        # IndexError here on real legacy pieces. Degrade a failed measure to
        # the simplest routing (ambiguous events -> primary voice) rather than
        # aborting the whole score.
        try:
            sols_per_pair = []
            for up, down, staff in pairs:
                sranges = _measure_ranges(staff, sy.bar_xs)
                slo, shi = sranges[mi]
                u_evs = [e for e in sy.events.get(up, [])
                         if e.staff is staff and slo <= e.x < shi]
                d_evs = [e for e in sy.events.get(down, [])
                         if e.staff is staff and slo <= e.x < shi]
                p_evs = [e for e in pending_by_staff.get(id(staff), [])
                         if slo <= e.x < shi]
                sols = _pair_solutions(u_evs, d_evs, p_evs, staff, up, down)
                sols_per_pair.append(sols)
            per_measure.append(sols_per_pair)

            # joint choice: same measure length across the staves, min cost
            best = None
            for sa in sols_per_pair[0]:
                for sb in sols_per_pair[1]:
                    mismatch = abs(sa["M"] - sb["M"]) > 1e-6
                    unbal = sa["unbal"] + sb["unbal"]
                    cost = sa["cost"] + sb["cost"] + \
                        (1000 if mismatch else 0) + 100 * unbal
                    if best is None or cost < best[0]:
                        best = (cost, sa, sb)
            if best is None:
                continue
            _, sa, sb = best
            for sol, (up, down, staff) in ((sa, pairs[0]), (sb, pairs[1])):
                if sol["unbal"]:
                    report.warn(f"p{page_no}: measure {mi + 1} of system at "
                                f"y~{staff.top:.0f}: could not balance "
                                f"{up}/{down} ({sol['cumU']} vs {sol['cumD']})")
                _commit_solution(sy, sol, up, down, report)
            if abs(sa["M"] - sb["M"]) > 1e-6:
                report.warn(f"p{page_no}: measure {mi + 1}: staves disagree on "
                            f"length ({sa['M']} vs {sb['M']} beats)")
        except IndexError:
            report.stats["shared_measures_degraded"] += 1
            report.warn(f"p{page_no}: measure {mi + 1} of system at "
                        f"y~{sy.staves[0].top:.0f}: reconciliation failed "
                        f"(ragged staff ranges) — routing ambiguous events to "
                        f"primary voice")
            for up, down, staff in pairs:
                for e in pending_by_staff.get(id(staff), []):
                    if lo <= e.x < hi and e.voice is None:
                        e.voice = up
                        sy.events.setdefault(up, []).append(e)

    for v in sy.events:
        sy.events[v].sort(key=lambda e: e.x)


def _pair_solutions(u_evs, d_evs, p_evs, staff, up, down, max_nodes=20000):
    """Enumerate interpretations of one staff-measure. Returns a list of
    dicts: {cost, M, cumU, cumD, unbal, actions} where actions are
    (kind, event, target) tuples; kinds: dup, donate, assign(list)."""
    sp = staff.sp
    all_evs = u_evs + d_evs + p_evs
    if not all_evs:
        return [{"cost": 0.0, "M": 0.0, "cumU": 0, "cumD": 0, "unbal": 0,
                 "actions": []}]
    centers, col_index = _cluster_columns(all_evs, sp)
    cells = [{"u": [], "d": [], "p": []} for _ in centers]
    for e in u_evs:
        cells[col_index(e)]["u"].append(e)
    for e in d_evs:
        cells[col_index(e)]["d"].append(e)
    for e in p_evs:
        cells[col_index(e)]["p"].append(e)
    last_def = {"u": max((e.x for e in u_evs), default=-1),
                "d": max((e.x for e in d_evs), default=-1)}

    sols = []
    best_unbal = [None]
    nodes = [0]

    def record(cumU, cumD, cost, actions):
        if abs(cumU - cumD) < 1e-6:
            sols.append({"cost": cost, "M": cumU, "cumU": cumU, "cumD": cumD,
                         "unbal": 0, "actions": list(actions)})
        else:
            cand = {"cost": cost + abs(cumU - cumD), "M": max(cumU, cumD),
                    "cumU": cumU, "cumD": cumD, "unbal": 1,
                    "actions": list(actions)}
            if best_unbal[0] is None or cand["cost"] < best_unbal[0]["cost"]:
                best_unbal[0] = cand

    def explore(ci, cumU, cumD, cost, actions):
        if nodes[0] > max_nodes or len(sols) > 400:
            return
        nodes[0] += 1
        if ci == len(cells):
            record(cumU, cumD, cost, actions)
            return
        cell = cells[ci]
        u_here, d_here, p_here = cell["u"], cell["d"], cell["p"]
        u_beats = sum(e.total_beats for e in u_here)
        d_beats = sum(e.total_beats for e in d_here)
        in_sync = abs(cumU - cumD) < 1e-6

        # option sets are built as (dcostU..., addU, addD, extra_actions)
        variants = [(0.0, 0.0, 0.0, [])]

        if u_here and not d_here and not p_here and in_sync:
            note_evs = [e for e in u_here if e.kind == "note"]
            if note_evs:
                later = last_def["d"] > max(e.x for e in note_evs)
                multi = [e for e in note_evs if len(e.heads) >= 2]
                if multi:
                    # donate the bottom head(s) of the chord to the partner
                    give = sum(e.total_beats for e in multi)
                    variants = [(0.0, 0.0, give,
                                 [("donate", e, down) for e in multi]),
                                (0.4, 0.0, 0.0, [])]
                else:
                    dup_cost = 0.0 if later else 0.2
                    skip_cost = 0.6 if later else 0.1
                    variants = [(dup_cost, 0.0,
                                 sum(e.total_beats for e in note_evs),
                                 [("dup", e, down) for e in note_evs]),
                                (skip_cost, 0.0, 0.0, [])]
        elif d_here and not u_here and not p_here and in_sync:
            note_evs = [e for e in d_here if e.kind == "note"]
            if note_evs:
                later = last_def["u"] > max(e.x for e in note_evs)
                multi = [e for e in note_evs if len(e.heads) >= 2]
                if multi:
                    give = sum(e.total_beats for e in multi)
                    variants = [(0.0, give, 0.0,
                                 [("donate", e, up) for e in multi]),
                                (0.4, 0.0, 0.0, [])]
                else:
                    dup_cost = 0.0 if later else 0.2
                    skip_cost = 0.6 if later else 0.1
                    variants = [(dup_cost,
                                 sum(e.total_beats for e in note_evs),
                                 0.0, [("dup", e, up) for e in note_evs]),
                                (skip_cost, 0.0, 0.0, [])]

        pend_opts = [[]]
        for e in p_here:
            opts = []
            busy_u = bool(u_here)
            busy_d = bool(d_here)
            lag_u = cumU < cumD - 1e-6
            lag_d = cumD < cumU - 1e-6
            if e.kind == "note" and len(e.heads) >= 2:
                # stacked / side-by-side whole pair
                opts.append((0.0, "split", e))
                if not busy_u:
                    opts.append((0.5, "all_u", e))
                if not busy_d:
                    opts.append((0.5, "all_d", e))
            elif e.kind == "rest":
                if lag_u and not busy_u:
                    opts.append((0.0, "to_u", e))
                elif lag_d and not busy_d:
                    opts.append((0.0, "to_d", e))
                else:
                    if not (busy_u or busy_d):
                        opts.append((0.0, "to_both", e))
                    if not busy_u:
                        opts.append((0.4, "to_u", e))
                    if not busy_d:
                        opts.append((0.4, "to_d", e))
            else:  # lone whole
                nu = min((x for x in (ev.x for ev in u_evs) if x > e.x + sp),
                         default=1e9)
                nd = min((x for x in (ev.x for ev in d_evs) if x > e.x + sp),
                         default=1e9)
                if not busy_u:
                    prior = 0.1 if nd < nu - sp else 0.3
                    opts.append((prior, "to_u", e))
                if not busy_d:
                    prior = 0.1 if nu < nd - sp else 0.3
                    opts.append((prior, "to_d", e))
                if not (busy_u or busy_d) and abs(cumU - cumD) < 1e-6:
                    opts.append((0.2, "to_both", e))
            if not opts:
                opts.append((0.5, "to_u" if not busy_u else "to_d", e))
            new_po = []
            for combo in pend_opts:
                for o in opts:
                    new_po.append(combo + [o])
            pend_opts = new_po

        for (vc, du, dd, acts) in variants:
            for combo in pend_opts:
                pu, pd, pc = 0.0, 0.0, 0.0
                pacts = []
                for (oc, tag, e) in combo:
                    pc += oc
                    tb = e.total_beats
                    if tag == "split":
                        pu += tb
                        pd += tb
                        pacts.append(("assign_split", e, None))
                    elif tag == "all_u":
                        pu += tb
                        pacts.append(("assign", e, up))
                    elif tag == "all_d":
                        pd += tb
                        pacts.append(("assign", e, down))
                    elif tag == "to_u":
                        pu += tb
                        pacts.append(("assign", e, up))
                    elif tag == "to_d":
                        pd += tb
                        pacts.append(("assign", e, down))
                    elif tag == "to_both":
                        pu += tb
                        pd += tb
                        pacts.append(("assign_both", e, None))
                explore(ci + 1,
                        cumU + u_beats + du + pu,
                        cumD + d_beats + dd + pd,
                        cost + vc + pc,
                        actions + acts + pacts)

    explore(0, 0.0, 0.0, 0.0, [])
    if not sols and best_unbal[0] is not None:
        return [best_unbal[0]]
    if not sols:
        return [{"cost": 0.0, "M": 0.0, "cumU": 0, "cumD": 0, "unbal": 0,
                 "actions": []}]
    # keep the cheapest few per distinct M
    by_m = {}
    for s in sorted(sols, key=lambda s: s["cost"]):
        by_m.setdefault(round(s["M"], 4), s)
    return list(by_m.values())


def _commit_solution(sy, sol, up, down, report):
    for kind, e, target in sol["actions"]:
        if kind == "dup":
            e2 = _clone_event(e, e.heads, target)
            e2.unison_assumed = True
            sy.events.setdefault(target, []).append(e2)
            report.stats["unison_events_duplicated"] += 1
        elif kind == "donate":
            heads = sorted(e.heads, key=lambda h: -h.step)
            if target == down:      # up-stem chord gives its bottom head(s)
                keep, give = heads[:1], heads[1:]
            else:                   # down-stem chord gives its top head(s)
                keep, give = heads[-1:], heads[:-1]
            e.heads = keep
            e2 = _clone_event(e, give, target)
            sy.events.setdefault(target, []).append(e2)
            report.stats["single_stem_chords_split"] += 1
        elif kind == "assign":
            e2 = _clone_event(e, e.heads, target)
            e2.kind = e.kind
            e2.ambiguous = False
            sy.events.setdefault(target, []).append(e2)
            report.stats["ambiguous_events_routed"] += 1
        elif kind == "assign_both":
            for v in (up, down):
                e2 = _clone_event(e, e.heads, v)
                e2.kind = e.kind
                e2.ambiguous = False
                e2.unison_assumed = e.kind == "note"
                sy.events.setdefault(v, []).append(e2)
            report.stats["ambiguous_events_routed"] += 1
        elif kind == "assign_split":
            heads = sorted(e.heads, key=lambda h: -h.step)
            e_top = _clone_event(e, heads[:1], up)
            e_bot = _clone_event(e, heads[1:], down)
            e_top.ambiguous = e_bot.ambiguous = False
            sy.events.setdefault(up, []).append(e_top)
            sy.events.setdefault(down, []).append(e_bot)
            report.stats["stacked_wholes_split"] += 1


def _merge_divisi(sy, report, page_no):
    """Single-voice staves (4-staff layout) can still carry a second stream
    (divisi a2: octave basses, held note under a moving line). Detect via the
    measure length consensus of the other voices; pick the subset of events
    that fills exactly that length with the most musical continuity (chords
    merged when equal duration at the same column); report what was dropped.
    """
    ranges = _measure_ranges(sy.staves[0], sy.bar_xs)
    for vi, staff in enumerate(sy.staves):
        v = VOICE_ORDER[vi] if vi < 4 else None
        if v is None or v not in sy.events:
            continue
        sp = staff.sp
        sranges = _measure_ranges(staff, sy.bar_xs)
        for mi, (lo, hi) in enumerate(sranges):
            evs = [e for e in sy.events[v]
                   if e.staff is staff and lo <= e.x < hi]
            notes = [e for e in evs if e.kind == "note"]
            total = sum(e.total_beats for e in evs)
            # consensus measure length from the other voices. Guard each event
            # against ITS OWN staff's range list — ragged final measures make
            # some staves shorter, and indexing [mi] blindly used to IndexError.
            others = []
            for ov in sy.events:
                if ov == v:
                    continue
                osum = 0.0
                for e in sy.events[ov]:
                    er = _measure_ranges(e.staff, sy.bar_xs)
                    if mi < len(er) and er[mi][0] <= e.x < er[mi][1]:
                        osum += e.total_beats
                if osum > 0:
                    others.append(round(osum, 4))
            if not others:
                continue
            m_hint = max(set(others), key=others.count)
            if abs(total - m_hint) < 1e-6 or total < m_hint:
                continue
            # first: merge equal-duration same-column pairs into chords
            centers, col_index = _cluster_columns(notes, sp)
            bycol = defaultdict(list)
            for e in notes:
                bycol[col_index(e)].append(e)
            for ci, cell in bycol.items():
                while len(cell) >= 2:
                    cell.sort(key=lambda e: -max(h.step for h in e.heads))
                    merged = False
                    for extra in cell[1:]:
                        if abs(extra.total_beats - cell[0].total_beats) < 1e-6:
                            cell[0].heads.extend(extra.heads)
                            cell[0].heads.sort(key=lambda h: -h.step)
                            sy.events[v].remove(extra)
                            cell.remove(extra)
                            report.stats["divisi_columns_merged"] += 1
                            merged = True
                            break
                    if not merged:
                        break
            evs = [e for e in sy.events[v]
                   if e.staff is staff and lo <= e.x < hi]
            notes = [e for e in evs if e.kind == "note"]
            rest_beats = sum(e.total_beats for e in evs if e.kind == "rest")
            total = sum(e.total_beats for e in evs)
            if abs(total - m_hint) < 1e-6:
                continue
            # subset selection: keep the most continuous line summing to
            # m_hint; drop the rest (divisi extras)
            target = m_hint - rest_beats
            best = None
            n = len(notes)
            if n > 17:
                report.warn(f"p{page_no}: {v} staff measure at "
                            f"x[{lo:.0f},{hi:.0f}): {n} events too many for "
                            f"divisi subset search — left as-is")
                continue
            for mask in range(1, 1 << n):
                ssum = 0.0
                for i in range(n):
                    if mask >> i & 1:
                        ssum += notes[i].total_beats
                if abs(ssum - target) > 1e-6:
                    continue
                chosen = [notes[i] for i in range(n) if mask >> i & 1]
                penal = sum(2.0 for e in chosen if e.stem_dir is None)
                prev = None
                for e in chosen:
                    step = max(h.step for h in e.heads)
                    if prev is not None:
                        penal += 0.5 * abs(step - prev)
                    prev = step
                if best is None or penal < best[0]:
                    best = (penal, chosen)
            if best is None:
                report.warn(f"p{page_no}: {v} staff measure at "
                            f"x[{lo:.0f},{hi:.0f}) sums {total} vs consensus "
                            f"{m_hint} and no subset fits — left as-is")
                continue
            drop = [e for e in notes if e not in best[1]]
            for e in drop:
                sy.events[v].remove(e)
            report.stats["divisi_events_dropped"] += len(drop)
            if drop:
                names = " ".join(
                    f"{LETTERS[max(h.step for h in e.heads) % 7]}"
                    f"{max(h.step for h in e.heads) // 7}" for e in drop)
                report.warn(f"p{page_no}: {v} staff divisi in measure at "
                            f"x[{lo:.0f},{hi:.0f}): dropped secondary "
                            f"stream [{names}] (correction-UI material)")


def _measure_ranges(staff, bar_xs):
    lo = staff.x0 - 1
    out = []
    for x in bar_xs:
        out.append((lo, x))
        lo = x
    if lo < staff.x1 - 4:
        out.append((lo, staff.x1 + 2))
    return out


# ----------------------------------------------------------------- lyric text
# The band below a staff holds sung syllables, but also leaks tempo/dynamic
# marks ('cresc.', 'rit.', 'Slower', 'hold', 'breath'), navigation text
# ('To Coda', 'D.C. al Coda'), metronome/copyright lines and big breath-comma
# glyphs. Two robustness rules separate lyrics from that noise WITHOUT the
# classic butchering traps (never filter on ALL-CAPS or word shape — 'LORD HAVE
# MER-CY' is a real lyric; never drop a line merely for being italic — italic
# marks an alternate verse):
#   * an expression-VOCAB match only condemns a token when the token stands
#     alone as its own short line of directions; a vocab string that is a real
#     word syllable ('rit:' = the -rit of 'Spi-rit') rides a line with content
#     words and survives untouched;
#   * italic is available (Event/token level) as corroboration but is never the
#     sole reason to drop.
# _EXPR_VOCAB / _EXPR_EXTRA are defined just after _SECTION_STOPWORDS (which
# they reuse); both are module globals resolved when these functions run.
_EXPR_CONNECTIVE = {          # function words that carry a direction, not content
    "a", "al", "il", "el", "la", "le", "lo", "e", "ed", "o", "di", "da",
    "de", "del", "in", "con", "col", "sul", "su", "to", "of", "and", "the",
    "non", "un", "una", "uno", "ma", "piu", "sempre", "au", "aux", "du", "et"}
_FOOTNOTE_KILL = {"nb"}       # 'N.B.' — always an editorial footnote


def _lyric_compact(text):
    """Letters-only lowercase form of a token, for expression-vocab matching
    ('rit:' -> 'rit', 'D.C.' -> 'dc', 'breath....' -> 'breath')."""
    return re.sub(r"[^a-z]", "", text.lower())


def _is_dash(text):
    """A pure ASCII hyphen/underscore token — a syllable connector kept in the
    line so _hyphen_between can see it, but never emitted as a lyric."""
    return text != "" and all(c in "-_" for c in text)


def _lyric_kill_token(text):
    """A token that condemns its whole text line as non-lyric: a metronome mark
    or dated copyright/footer line (contains a digit or '='), a footnote (leads
    with '*' or is 'N.B.'). Matches the old =/digit/N.B./* backstop."""
    if any(c.isdigit() for c in text) or "=" in text:
        return True
    if text.startswith("*"):
        return True
    return _lyric_compact(text) in _FOOTNOTE_KILL


def _drop_non_lyric_lines(band):
    """Cluster band tokens into text lines by baseline y and return them ordered
    top->bottom (each line a list of tokens) after removing non-sung text.
    _attach_lyrics treats each returned line as a separate verse.

    Filtering:
      * junk tokens (no letter and not a hyphen connector) are removed in place
        — big breath-comma glyphs, '(', U+2011/U+00AD pseudo-hyphens, digit runs;
      * a whole line is dropped when _lyric_kill_token flags it (metronome mark,
        dated copyright, '*'/N.B. footnote);
      * a short line made entirely of directions + function words, with at least
        one real direction and NO content word, is dropped ('cresc.', 'To Coda',
        'D.C. al Coda', 'poco a poco rit.'). One content word keeps the line, so
        'hold fast', 'the Son' and 'Glory ... Spi-rit:' survive.
    """
    lines = []                                   # [[repr_baseline_y, [tokens]]]
    for t in sorted(band, key=lambda t: t["y"]):
        if lines and t["y"] - lines[-1][0] <= 1.5:
            grp = lines[-1][1]
            grp.append(t)
            lines[-1][0] = sum(x["y"] for x in grp) / len(grp)
        else:
            lines.append([t["y"], [t]])
    kept = []
    for _y, toks in lines:
        toks = sorted(toks, key=lambda t: t["x0"])
        if any(_lyric_kill_token(t["text"]) for t in toks):
            continue
        toks = [t for t in toks
                if _is_dash(t["text"]) or any(c.isalpha() for c in t["text"])]
        words = [t for t in toks if not _is_dash(t["text"])]
        if not words:
            continue
        if len(words) <= 5:
            expr = content = 0
            for t in words:
                c = _lyric_compact(t["text"])
                if c in _EXPR_VOCAB:
                    expr += 1
                elif c not in _EXPR_CONNECTIVE:
                    content += 1
            if expr >= 1 and content == 0:
                continue          # a pure musical-direction / navigation line
        kept.append(toks)
    return kept


def _attach_lyrics(sy, tokens, report, page_no):
    """Lyric tokens live in the band below a staff. Each surviving text line in
    that band is a separate verse (top line = verse 1); each verse's syllables
    are x-sorted, hyphenated and attached to their own nearest note onsets, so
    stacked verses (e.g. a roman verse 1 over an italic alternate verse 2) never
    interleave into one garbled line."""
    for si, staff in enumerate(sy.staves):
        band_top = staff.bot + 0.5 * staff.sp
        nxt = sy.staves[si + 1] if si + 1 < len(sy.staves) else None
        band_bot = (nxt.top - 0.5 * staff.sp) if nxt is not None \
            else staff.bot + 8 * staff.sp
        band = [t for t in tokens
                if band_top < t["y"] < band_bot
                and staff.x0 - 2 <= t["cx"] <= staff.x1 + 2
                and t["size"] > 6]
        lines = _drop_non_lyric_lines(band)
        if not lines:
            continue
        # events that can carry a lyric: notes on this staff
        voices = [v for v, evs in sy.events.items()
                  if any(e.staff is staff for e in evs)]
        carriers = {v: [e for e in sy.events[v]
                        if e.staff is staff and e.kind == "note"]
                    for v in voices}
        # verse index = baseline order (top line = verse 1), assigned only from
        # its own tokens. Every real lyric line becomes a verse — never dropped:
        # per the design, treating a lone continuation line as an extra verse
        # garbles nothing because verse 1 stays coherent. The one line we skip
        # (without dropping any *real* lyric) is a stray section title that fell
        # into the last staff's tall band: it towers over the verse-1 text, so a
        # line whose median glyph size far exceeds verse 1's is not a verse.
        v1_size = None
        verse_k = 0
        for line in lines:
            sizes = sorted(t["size"] for t in line)
            med = sizes[len(sizes) // 2]
            if v1_size is None:
                v1_size = med
            elif med > 1.6 * v1_size:
                continue          # oversized => a title, not an alternate verse
            verse_k += 1
            _attach_verse_line(line, verse_k, staff, voices, carriers, report)


def _attach_verse_line(line, k, staff, voices, carriers, report):
    """X-sort, hyphenate and attach one verse line's syllables to nearest notes.
    Each note carries at most one syllable per verse number k."""
    line = sorted(line, key=lambda t: t["x0"])
    words = [t for t in line if t["text"].strip("-_")]
    for i, t in enumerate(words):
        txt = t["text"]
        prev_hyph = i > 0 and _hyphen_between(line, words[i - 1], t)
        next_hyph = i + 1 < len(words) and _hyphen_between(line, t, words[i + 1])
        if prev_hyph and next_hyph:
            syl = "middle"
        elif next_hyph:
            syl = "begin"
        elif prev_hyph:
            syl = "end"
        else:
            syl = "single"
        for v in voices:
            evs = carriers[v]
            if not evs:
                continue
            best = min(evs, key=lambda e: abs(e.x - t["cx"]))
            if abs(best.x - t["cx"]) > 6 * staff.sp:
                report.stats["lyric_tokens_unmatched"] += 1
                continue
            if any(l.get("number") == k for l in best.lyric):
                continue
            best.lyric.append({"text": txt, "syllabic": syl, "number": k})
            report.stats["lyric_syllables_attached"] += 1


def _hyphen_between(band, a, b):
    return any(t["text"] == "-" and a["x1"] - 1 <= t["x0"] and
               t["x1"] <= b["x0"] + 1 for t in band)


def _apply_ties(systems, curves, report, page_no):
    evs_all = []
    for sy in systems:
        for v, evs in sy.events.items():
            for e in evs:
                if e.kind == "note":
                    evs_all.append((sy, v, e))
    for (cx0, cy0, cx1, cy1, pts) in curves:
        left = min(pts, key=lambda p: p.x)
        right = max(pts, key=lambda p: p.x)
        lcand = _nearest_head_event(evs_all, left.x, left.y, side="left")
        rcand = _nearest_head_event(evs_all, right.x, right.y, side="right")
        if not lcand or not rcand:
            report.stats["curves_unmatched"] += 1
            continue
        (sy1, v1, e1, h1), (sy2, v2, e2, h2) = lcand, rcand
        if e1 is e2:
            report.stats["curves_within_one_event"] += 1
            continue
        if v1 == v2 and h1.step == h2.step and h1.staff is h2.staff and \
                _adjacent_in_voice(sy1, v1, e1, e2):
            e1.tie_start = True
            e2.tie_stop = True
            report.stats["ties_detected"] += 1
        else:
            # same-pitch but non-adjacent endpoints = a melisma slur whose
            # first and last notes coincide (very common in chant) — NOT a tie
            report.stats["slurs_detected"] += 1


def _adjacent_in_voice(sy, v, e1, e2):
    """True iff no other note event of voice v on the same staff lies
    strictly between e1 and e2 (a tie may only join consecutive notes)."""
    lo, hi = min(e1.x, e2.x), max(e1.x, e2.x)
    for e in sy.events.get(v, []):
        if e is e1 or e is e2 or e.kind != "note" or e.staff is not e1.staff:
            continue
        if lo < e.x < hi:
            return False
    return True


def _nearest_head_event(evs_all, x, y, side):
    best, bd = None, 1e9
    for sy, v, e in evs_all:
        for h in e.heads:
            sp = h.staff.sp
            dx = (x - h.g.x1) if side == "left" else (h.g.x0 - x)
            if -1.5 * sp < dx < 4 * sp and abs(h.g.y - y) < 1.6 * sp:
                d = abs(dx) + abs(h.g.y - y)
                if d < bd:
                    best, bd = (sy, v, e, h), d
    return best


# --------------------------------------------------------------- score assembly

def build_score(pdf_path, pages=None, report=None):
    report = report or Report()
    doc = fitz.open(pdf_path)
    tempo_state = {"bpm": None, "marks": []}
    all_systems = []
    for pno in range(len(doc)):
        if pages and (pno + 1) not in pages:
            continue
        systems, _ = extract_page(doc[pno], pno + 1, report, 0, tempo_state)
        all_systems.extend(systems)

    first_music_page = all_systems[0].page if all_systems else 1
    title = _find_title(doc, first_music_page,
                        all_systems[0].staves[0].top if all_systems else 1e9,
                        report)

    # assemble measures: voice -> list of measures; measure = list of events
    voices_present = [v for v in VOICE_ORDER
                      if any(v in sy.events for sy in all_systems)]
    score = {v: [] for v in voices_present}
    measure_meta = []
    for si, sy in enumerate(all_systems):
        ref_staff = sy.staves[0]
        ranges = _measure_ranges(ref_staff, sy.bar_xs)
        staff_ranges = {id(s): _measure_ranges(s, sy.bar_xs) for s in sy.staves}
        key = ref_staff.key_fifths
        for mi in range(len(ranges)):
            meta = {"key": key, "sums": {}, "system_page": sy.page,
                    "system_index": si, "new_system": mi == 0,
                    "x_range": ranges[mi], "sp": ref_staff.sp,
                    "system_top": sy.staves[0].top,
                    "system_bot": sy.staves[-1].bot,
                    "ts_beats": sy.ts_beats}
            for v in voices_present:
                evs = []
                for e in sy.events.get(v, []):
                    lo, hi = staff_ranges[id(e.staff)][mi] \
                        if mi < len(staff_ranges[id(e.staff)]) else ranges[mi]
                    if lo <= e.x < hi:
                        evs.append(e)
                evs.sort(key=lambda e: e.x)
                score[v].append(evs)
                meta["sums"][v] = sum(e.total_beats for e in evs)
            measure_meta.append(meta)

    # ---- attach tempo marks to the measure under them
    for mark in tempo_state["marks"]:
        best = None
        for mi, meta in enumerate(measure_meta):
            if meta["system_page"] != mark["page"]:
                continue
            sy_top = meta["system_top"]
            if sy_top < mark["y"] - 6:      # mark must sit above the system
                continue
            lo, hi = meta["x_range"]
            dx = 0.0 if lo - 6 <= mark["x"] < hi else \
                min(abs(mark["x"] - lo), abs(mark["x"] - hi))
            score_d = (sy_top - mark["y"]) + 4 * dx
            if best is None or score_d < best[0]:
                best = (score_d, mi)
        if best is not None:
            measure_meta[best[1]].setdefault("tempo", dict(mark))

    # drop measures that are empty in every voice (slivers next to final
    # thick barlines, decorative ranges) — report them
    keep = [mi for mi in range(len(measure_meta))
            if any(score[v][mi] for v in voices_present)]
    if len(keep) != len(measure_meta):
        report.note(f"dropped {len(measure_meta) - len(keep)} empty "
                    f"measure slivers")
        for v in voices_present:
            score[v] = [score[v][mi] for mi in keep]
        measure_meta = [measure_meta[mi] for mi in keep]

    n_meas = len(measure_meta)
    report.stats["measures"] = n_meas
    report.stats["systems"] = len(all_systems)

    # collapse-detection signals for the downstream ingest gate: a score that
    # extracted as one concatenated Soprano shows up here as a run of 1-staff
    # systems (mode == 1). A healthy SATB score has a mode of 2 or 4.
    staff_counts = [len(sy.staves) for sy in all_systems]
    report.stats["single_staff_systems"] = sum(1 for c in staff_counts
                                               if c == 1)
    if staff_counts:
        report.stats["staves_per_system_mode"] = max(
            set(staff_counts), key=staff_counts.count)

    # ---- whole-measure-rest normalization -----------------------------------
    # SMuFL restWhole (U+E4E3) is a *whole-measure* rest: its true value is the
    # length of the measure it occupies, not the fixed 4-beat semibreve the
    # RESTS table gives it (see Event.whole_measure). In free/mixed-meter chant
    # a voice may rest a whole measure that is really 3 beats (implied 3/4)
    # while other voices carry real 3-beat content; the provisional 4.0 would
    # then win the per-measure max, mislabel the time signature (4/4 not 3/4)
    # and force a spurious <forward> pad on the correct voices. The mirror
    # defect grows the other way: a whole rest stuck at the 4.0 default in a bar
    # whose real content runs LONGER (e.g. a 14-beat chant melisma) truncates
    # the rest, cueing that voice's next entrance too EARLY. Rescale each
    # whole-rest voice — UP or DOWN — to the measure's true length, taken from
    # the voices that carry real (non-whole-rest) content. Growing never lifts
    # the per-measure max (ref is already <= that max), so the emitted time
    # signature is unchanged; only the rest's own length is corrected. Genuine
    # full-measure rests that already agree with real content are left untouched.
    wm_resized = 0        # rest-voice measures corrected
    wm_no_ref = 0         # flagged measures with no real-content reference voice
    for mi, meta in enumerate(measure_meta):
        wm_voices = [v for v in voices_present
                     if any(e.whole_measure for e in score[v][mi])]
        if not wm_voices:
            continue
        # reference = longest real-content voice (no whole-rest, has content)
        ref_sums = [meta["sums"][v] for v in voices_present
                    if v not in wm_voices and meta["sums"].get(v, 0) > 1e-6]
        if ref_sums:
            ref = max(ref_sums)
        else:
            # no trustworthy reference: fall back to a captured printed time
            # signature if we have one, else leave the 4.0 default (never guess).
            ref = meta.get("ts_beats")
            if ref is None:
                if any(meta["sums"].get(v, 0) > 1e-6 for v in wm_voices):
                    wm_no_ref += 1
                continue
        for v in wm_voices:
            if abs(meta["sums"].get(v, 0) - ref) <= 1e-6:
                continue   # rest already matches real content — genuine full-
                           # measure rest (both the grow and shrink paths skip)
            evs = score[v][mi]
            wm = [e for e in evs if e.whole_measure]
            others = sum(e.total_beats for e in evs if not e.whole_measure)
            needed = ref - others
            if needed < -1e-6:
                continue   # real content already overflows ref; don't touch
            share = needed / len(wm)
            for e in wm:
                e.beats = share
                e.dots = 0
            meta["sums"][v] = ref
            wm_resized += 1
    if wm_resized:
        report.note(f"whole-measure-rest normalization: resized {wm_resized} "
                    f"rest-voice measure(s) to the measure's true length")
    if wm_no_ref:
        report.note(f"whole-measure-rest normalization: {wm_no_ref} flagged "
                    f"measure(s) had no reference voice — left at default")
    report.stats["whole_measure_rests_resized"] = wm_resized

    # measure-integrity check
    #
    # A measure is "consistent" when every voice it is expected to carry is
    # present and all of them agree on their beat sum. The set of expected
    # voices is taken PER SYSTEM, not piece-global (issue #52, Mode B): a
    # piece-global set makes every genuinely single-voice measure of a
    # monophonic chant -- or of the chant sections of a mixed chant+SATB
    # booklet -- fail merely because some OTHER system somewhere in the piece
    # has 4 staves. So a GENUINELY MONOPHONIC system (a single staff = one
    # melody line) is scored against the single voice it carries (Soprano).
    #
    # Every MULTI-staff system keeps the strict piece-global expectation and is
    # scored against all of voices_present, exactly as before. This is
    # deliberately conservative (the issue's "no phantom leniency" bar): the
    # relief is granted ONLY where the page unambiguously shows one line of
    # music, never to a multi-staff system -- so a genuine voice collapse, a
    # wrong note duration, or a dropped voice in a real SATB/2-staff system
    # still disagrees and still fails, and a piece with a mis-detected N-staff
    # system (e.g. a 3-staff S/A/shared-T-B engraving whose bottom Bass isn't
    # split out yet) is held to the full voice set rather than let off.
    vp_set = set(voices_present)
    sys_expected = []
    for sy in all_systems:
        if len(sy.staves) == 1:
            sv = _staff_voices(sy)
            mono = {v for s in sy.staves for v in sv[id(s)]}
            sys_expected.append((mono & vp_set) or vp_set)
        else:
            sys_expected.append(vp_set)
    consistent = 0
    multivoice_measures = 0
    for i, meta in enumerate(measure_meta):
        expected = sys_expected[meta["system_index"]]
        if len(expected) > 1:
            multivoice_measures += 1
        sums = {v: round(meta["sums"].get(v, 0), 4)
                for v in voices_present if v in expected}
        nonzero = [s for s in sums.values() if s > 0]
        if nonzero and max(nonzero) - min(nonzero) < 1e-6 and \
                len(nonzero) == len(expected):
            consistent += 1
        else:
            report.warn(f"measure {i + 1}: voice beat sums disagree: {sums}")
    report.stats["measures_with_consistent_beat_sums"] = consistent
    # how many measures are scored as multi-voice (downstream gate can tell a
    # clean monophonic extraction from a collapsed/penalized polyphonic one).
    report.stats["multivoice_measures"] = multivoice_measures
    if n_meas:
        report.stats["measure_integrity_pct"] = round(100 * consistent / n_meas, 1)

    # per-piece section index (hymn titles -> section-start measure numbers) for
    # jumping to a hymn inside a concatenated complete-service score.
    sections = _find_sections(doc, measure_meta, title, report)

    return {"title": title, "voices": voices_present, "score": score,
            "meta": measure_meta, "tempo": tempo_state["bpm"],
            "report": report, "systems": all_systems, "sections": sections}


def _find_title(doc, first_music_page, first_staff_top, report):
    """Largest text above the first staff on the first page with music."""
    raw = doc[first_music_page - 1].get_text("dict")
    best, bs = None, 0
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                if _music_font_family(s["font"]) is not None or \
                        any(0xE000 <= ord(c) <= 0xF8FF for c in t):
                    continue   # music glyphs (SMuFL or legacy Finale), not words
                if s["bbox"][1] < first_staff_top and len(t) > 3 and \
                        s["size"] > bs:
                    best, bs = t, s["size"]
    return best or "Untitled"


# ------------------------------------------------------------ section headers
# Complete-service scores concatenate many hymns into one file. Each hymn is
# introduced by a large title line engraved in the gap above the top staff of
# the system where it starts ("The Great Litany", "Cherubic Hymn", ...). We
# generalise _find_title to run per system across the whole document and attach
# each detected title to the printed measure number of the first measure of the
# system below it, producing a per-piece section index for in-score navigation.
#
# The heuristic is deliberately conservative — it is better to miss a marginal
# header than to invent a section from stray text:
#   * a header must tower over the ordinary lyric/body text (SECTION_SIZE_RATIO
#     * the document's modal body font size) — this rejects running headers,
#     composer credits and verse numbers, which sit at or below body size;
#   * AND it must reach SECTION_MODE_RATIO * the document's own dominant title
#     size — this rejects expression/tempo text ("slower", "in tempo") that is
#     bigger than lyrics but smaller than a real hymn title;
#   * it must read like a title (>= 3 ASCII letters, has a vowel, almost all
#     ordinary title characters) — this rejects page tags like "13-F", bare
#     verse numbers "3.", stray punctuation, and notehead runs that unrecognised
#     music fonts emit as large "text" (e.g. 'Tamburo' -> 'œœœ˙');
#   * a short exact-match stopword list drops any tempo mark ("rit.") that slips
#     through at near-title size;
#   * it must sit in the vertical gap above a system's top staff (below the
#     previous system on the page), not over the music itself.
SECTION_SIZE_RATIO = 1.5     # header font >= this * modal body size (recall gate)
SECTION_MODE_RATIO = 0.8     # ... AND >= this * the doc's dominant title size,
#   which separates real hymn titles from expression/tempo text (e.g. "slower",
#   "in tempo") that is larger than lyrics but well short of a hymn title.
SECTION_MIN_LETTERS = 3
# punctuation that legitimately appears in hymn titles (straight + typographic)
_TITLE_PUNCT = set(" .,:;!?#&/()+-*'\"") | {
    "’", "‘", "“", "”", "–", "—"}
# exact musical-direction tokens that are never hymn titles (backstop for marks
# engraved at near-title size); matched against the letters-only normalised form
_SECTION_STOPWORDS = {
    "rit", "ritard", "ritardando", "accel", "accelerando", "rall",
    "rallentando", "a tempo", "in tempo", "tempo", "meno mosso", "piu mosso",
    "poco rit", "molto rit", "cresc", "crescendo", "dim", "diminuendo",
    "da capo", "dc al fine", "dc al coda", "al coda", "al fine", "fine",
    "coda", "segno", "tacet", "solo", "tutti", "unison"}

# Expression/dynamic/tempo vocabulary for lyric filtering (see _drop_non_lyric_
# lines). Built from the section stopwords in letters-only compact form, plus
# dynamics/articulation/navigation words that leak into the lyric band but are
# never used as hymn-section titles. Matched only against standalone tokens on
# a direction-only line, so ambiguous English words (hold, breath, faster) that
# also occur as real lyrics survive when they sit among content words.
_EXPR_EXTRA = {
    "hold", "breath", "slower", "faster", "poco", "molto", "meno", "mosso",
    "legato", "staccato", "dolce", "marcato", "riten", "ritenuto", "ritard",
    "ritardando", "decresc", "decrescendo", "sfz", "espress", "espressivo",
    "div", "unis", "dc", "tocoda", "sostenuto", "simile", "rubato", "nb"}
_EXPR_VOCAB = ({re.sub(r"[^a-z]", "", w) for w in _SECTION_STOPWORDS}
               | _EXPR_EXTRA) - {""}


def _section_norm(t):
    """Letters-and-spaces-only lowercase form for stopword matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", t.lower())).strip()


def _section_body_size(doc, pages):
    """Char-weighted modal font size of ordinary (non-music, word-like) text on
    the given music pages — the 'lyric/body' size headers must tower over."""
    from collections import Counter
    hist = Counter()
    for pno in sorted(pages):
        for b in doc[pno - 1].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    t = s["text"].strip()
                    if len(t) < 2 or not any(ch.isalpha() for ch in t):
                        continue
                    if _music_font_family(s["font"]) is not None or \
                            any(0xE000 <= ord(c) <= 0xF8FF for c in t):
                        continue
                    hist[round(s["size"], 1)] += len(t)
    return hist.most_common(1)[0][0] if hist else 11.0


def _looks_like_title(t):
    """A title line reads as words, not a page tag / verse number / stray glyph
    / run of unrecognised music-font notehead characters. Requires real Latin
    words: enough ASCII letters, at least one vowel, and a body made almost
    entirely of ordinary title characters. This rejects notehead runs that some
    unrecognised music fonts (e.g. 'Tamburo' -> 'œœœ˙') emit as large text."""
    if not t:
        return False
    ascii_letters = sum(1 for ch in t if "a" <= ch <= "z" or "A" <= ch <= "Z")
    if ascii_letters < SECTION_MIN_LETTERS:
        return False
    if not any(ch in "aeiouAEIOU" for ch in t):
        return False
    ordinary = sum(1 for ch in t
                   if (ch.isascii() and ch.isalnum()) or ch in _TITLE_PUNCT)
    return ordinary / len(t) >= 0.8


def _merge_title_lines(tlines):
    """Join a title that is engraved across several stacked lines (e.g. 'Litany'
    over 'In the Name of the Lord') into one string. Anchored on the largest
    line, absorbing vertically-adjacent lines of comparable size; smaller or
    far-away title-sized text is left out. tlines: [(y0, size, text)]. Returns
    (title, anchor_size) or None."""
    if not tlines:
        return None
    tlines = sorted(tlines)                     # top to bottom
    smax = max(sz for _, sz, _ in tlines)
    block, prev_y = [], None
    for y0, sz, text in tlines:
        if sz < 0.85 * smax:                    # sub-size text, not the title
            continue
        if prev_y is not None and y0 - prev_y > 3 * smax:
            break                               # a separate block further down
        block.append(text)
        prev_y = y0
    title = " ".join(block).strip()
    return (title, smax) if title else None


def _find_sections(doc, measure_meta, title, report):
    """Detect hymn/section titles across the whole document and map each to the
    printed measure number where it starts. Returns [{title, measure}] sorted
    ascending by measure; the first entry is normally the work-title at m.1."""
    if not measure_meta:
        return []
    pages = {m["system_page"] for m in measure_meta}
    thresh = _section_body_size(doc, pages) * SECTION_SIZE_RATIO

    # group measures into systems; the section start is the first (lowest-index,
    # i.e. lowest printed number) measure kept for each system.
    systems = {}
    for mi, m in enumerate(measure_meta):
        si = m["system_index"]
        g = systems.get(si)
        if g is None:
            systems[si] = {"page": m["system_page"], "top": m["system_top"],
                           "bot": m["system_bot"], "first_mi": mi}
        else:
            g["first_mi"] = min(g["first_mi"], mi)

    raw_cache = {}
    prev_bot = {}          # page -> bottom of the last system seen above
    found = []             # (measure_number, title, size)
    for si, g in systems.items():
        page, top = g["page"], g["top"]
        lo = prev_bot.get(page, 0.0)
        raw = raw_cache.get(page)
        if raw is None:
            raw = raw_cache[page] = doc[page - 1].get_text("dict")
        # collect title-sized text lines sitting in the gap above the staff
        tlines = []        # (y0, size, text)
        for b in raw["blocks"]:
            for l in b.get("lines", []):
                spans = []
                for s in l["spans"]:
                    if not s["text"].strip() or s["size"] < thresh:
                        continue
                    ts = s["text"].strip()
                    if _music_font_family(s["font"]) is not None or \
                            any(0xE000 <= ord(c) <= 0xF8FF for c in ts):
                        continue
                    yc = 0.5 * (s["bbox"][1] + s["bbox"][3])
                    if lo - 2 <= yc < top - 2:      # in the gap above the staff
                        spans.append(s)
                if not spans:
                    continue
                spans.sort(key=lambda s: s["bbox"][0])
                text = re.sub(r"\s+", " ",
                              "".join(s["text"] for s in spans)).strip()
                if _looks_like_title(text):        # drops page tags / stray glyphs
                    tlines.append((min(s["bbox"][1] for s in spans),
                                   max(s["size"] for s in spans), text))
        merged = _merge_title_lines(tlines)
        if merged:
            found.append((g["first_mi"] + 1, merged[0], round(merged[1], 1)))
        prev_bot[page] = max(prev_bot.get(page, 0.0), g["bot"])

    # dominant title size for this document: real hymn titles recur at one large
    # size; expression/tempo marks that clear the body threshold are smaller and
    # fall below MODE_RATIO * that size, so they get dropped here.
    from collections import Counter
    mode_size = Counter(sz for _, _, sz in found).most_common(1)[0][0] \
        if found else 0
    found = [f for f in found
             if f[2] >= SECTION_MODE_RATIO * mode_size
             and _section_norm(f[1]) not in _SECTION_STOPWORDS]

    found.sort(key=lambda x: x[0])
    sections = []
    for meas, ttl, _sz in found:
        if sections and sections[-1]["measure"] == meas:
            continue        # one header per measure
        if sections and sections[-1]["title"].lower() == ttl.lower():
            continue        # dedup consecutive identical titles (running heads)
        sections.append({"title": ttl, "measure": meas})

    # the index should open at the top of the piece: if detection did not place
    # a header at measure 1, seed it with the work-title.
    if not sections or sections[0]["measure"] > 1:
        sections.insert(0, {"title": title, "measure": 1})
        if len(sections) > 1 and \
                sections[1]["title"].lower() == sections[0]["title"].lower():
            sections.pop(1)

    report.stats["sections"] = len(sections)
    return sections


# --------------------------------------------------------------- MusicXML emit

DIVISIONS = 4
TYPE_OF = {4.0: "whole", 2.0: "half", 1.0: "quarter", 0.5: "eighth",
           0.25: "16th", 8.0: "breve"}


def _esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


MAX_MEASURE_BEATS = 6.5   # unmetered chant: split longer measures for layout
SPLIT_TARGET_BEATS = 4.5


def _voice_onsets(evs):
    """Cumulative beat position at which each event starts + total."""
    pos, cur = [], 0.0
    for e in evs:
        pos.append(round(cur, 4))
        cur += e.total_beats
    return pos, round(cur, 4)


def _split_points(score, voices, mi, m_sum):
    """Beat positions where a long measure can be split: every voice either
    has an event onset there or has already run out of events (deficit)."""
    common = None
    for v in voices:
        evs = score[v][mi]
        pos, total = _voice_onsets(evs)
        cand = {p for p in pos if 0 < p < m_sum}
        cand |= {round(p * 0.25, 4) for p in range(1, int(m_sum * 4))
                 if p * 0.25 >= total}   # after this voice's last event
        common = cand if common is None else (common & cand)
    if not common:
        return []
    n_seg = max(2, math.ceil(m_sum / SPLIT_TARGET_BEATS))
    ideal = m_sum / n_seg
    chosen, last = [], 0.0
    for k in range(1, n_seg):
        target = k * ideal
        cands = [p for p in sorted(common)
                 if p > last + 1.0 and p < m_sum - 1.0 + 1e-6]
        if not cands:
            break
        p = min(cands, key=lambda p: abs(p - target))
        if p - last < 1.0:
            continue
        chosen.append(p)
        last = p
    return chosen


def _layout_measures(result):
    """Turn extracted measures into layout measures: long unmetered measures
    are split at all-voice onset boundaries (joined by invisible barlines)
    so renderers can wrap lines and space notes like the engraving."""
    score, voices, meta = result["score"], result["voices"], result["meta"]
    out = []
    for mi in range(len(meta)):
        m_sum = max([meta[mi]["sums"].get(v, 0) for v in voices] + [0])
        splits = _split_points(score, voices, mi, m_sum) \
            if m_sum > MAX_MEASURE_BEATS else []
        bounds = [0.0] + splits + [m_sum]
        lo, hi = meta[mi]["x_range"]
        sp = meta[mi].get("sp") or 6.0
        for si in range(len(bounds) - 1):
            b0, b1 = bounds[si], bounds[si + 1]
            seg_events = {}
            seg_sums = {}
            for v in voices:
                evs = score[v][mi]
                pos, _total = _voice_onsets(evs)
                seg = [e for e, p in zip(evs, pos) if b0 - 1e-6 <= p < b1 - 1e-6]
                seg_events[v] = seg
                seg_sums[v] = sum(e.total_beats for e in seg)
            frac0, frac1 = (b0 / m_sum if m_sum else 0), \
                           (b1 / m_sum if m_sum else 1)
            width = (hi - lo) * (frac1 - frac0) / sp * 10
            out.append({
                "number": mi + 1,
                "implicit": si > 0,
                "events": seg_events,
                "sums": seg_sums,
                "m_sum": round(b1 - b0, 4),
                "key": meta[mi]["key"],
                "new_system": meta[mi].get("new_system") and si == 0,
                "tempo": meta[mi].get("tempo") if si == 0 else None,
                "invisible_right": si < len(bounds) - 2,
                "width_tenths": width,
                "first_of_printed": si == 0,
            })
    return out


BEAT_UNIT_NAMES = {2.0: "half", 1.0: "quarter", 0.5: "eighth"}


def _beam_xml(evs):
    """Per-event beam element strings for one measure of one voice."""
    beams = [""] * len(evs)
    i = 0
    while i < len(evs):
        e = evs[i]
        if e.kind != "note" or e.beam_group is None or e.beats >= 1.0:
            i += 1
            continue
        j = i
        while j + 1 < len(evs) and evs[j + 1].kind == "note" and \
                evs[j + 1].beam_group == e.beam_group and \
                evs[j + 1].beats < 1.0:
            j += 1
        if j > i:   # run of >= 2 notes under one beam
            for k in range(i, j + 1):
                pos = ("begin" if k == i else
                       "end" if k == j else "continue")
                parts = [f'<beam number="1">{pos}</beam>']
                if evs[k].nbeams >= 2:
                    left = k > i and evs[k - 1].nbeams >= 2
                    right = k < j and evs[k + 1].nbeams >= 2
                    if left and right:
                        parts.append('<beam number="2">continue</beam>')
                    elif right:
                        parts.append('<beam number="2">begin</beam>')
                    elif left:
                        parts.append('<beam number="2">end</beam>')
                    else:
                        hook = "backward hook" if k > i else "forward hook"
                        parts.append(f'<beam number="2">{hook}</beam>')
                beams[k] = "".join(parts)
        i = j + 1
    return beams


def emit_musicxml(result):
    voices = result["voices"]
    lay = _layout_measures(result)
    # section-start markers, keyed by printed measure number (first title wins)
    section_words = {}
    for sec in result.get("sections", []):
        section_words.setdefault(sec["measure"], sec["title"])
    out = []
    w = out.append
    w('<?xml version="1.0" encoding="UTF-8"?>')
    w('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 '
      'Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">')
    w('<score-partwise version="3.1">')
    w(f'  <work><work-title>{_esc(result["title"])}</work-title></work>')
    w('  <identification><encoding>'
      '<software>ChanterLab vector_extract (born-digital PDF glyph '
      'extraction)</software></encoding></identification>')
    w('  <part-list>')
    for i, v in enumerate(voices):
        w(f'    <score-part id="P{i + 1}">'
          f'<part-name>{VOICE_NAMES.get(v, v)}</part-name></score-part>')
    w('  </part-list>')

    for i, v in enumerate(voices):
        w(f'  <part id="P{i + 1}">')
        cur_key = None
        cur_beats = None
        memory = {}
        for li, lm in enumerate(lay):
            evs = lm["events"][v]
            m_sum = lm["m_sum"]
            impl = ' implicit="yes"' if lm["implicit"] else ''
            w(f'    <measure number="{lm["number"]}"{impl} '
              f'width="{lm["width_tenths"]:.0f}">')
            if lm["new_system"] and li > 0:
                w('      <print new-system="yes"/>')
            attrs = []
            if li == 0:
                attrs.append(f'<divisions>{DIVISIONS}</divisions>')
            if lm["key"] != cur_key:
                cur_key = lm["key"]
                attrs.append(f'<key><fifths>{cur_key}</fifths></key>')
            beats_frac = _beats_fraction(m_sum)
            if beats_frac and beats_frac != cur_beats:
                cur_beats = beats_frac
                bn, bt = beats_frac
                attrs.append(f'<time print-object="no"><beats>{bn}</beats>'
                             f'<beat-type>{bt}</beat-type></time>')
            if li == 0:
                attrs.append(_clef_xml(v))
            if attrs:
                w('      <attributes>' + "".join(attrs) + '</attributes>')
            # section header marker on the top part's section-start measures, so
            # the MusicXML is self-describing (the app's section index is built
            # from report.json/manifest, but this keeps the score standalone).
            if i == 0 and lm["first_of_printed"] and \
                    lm["number"] in section_words:
                w('      <direction placement="above"><direction-type>'
                  f'<words>{_esc(section_words[lm["number"]])}</words>'
                  '</direction-type></direction>')
            if lm["tempo"] and i == 0:   # metronome mark on the top part only
                mk = lm["tempo"]
                unit = BEAT_UNIT_NAMES.get(mk["unit"], "quarter")
                w(f'      <direction placement="above"><direction-type>'
                  f'<metronome><beat-unit>{unit}</beat-unit>'
                  f'<per-minute>{mk["per_minute"]}</per-minute></metronome>'
                  f'</direction-type>'
                  f'<sound tempo="{mk["qpm"]:.0f}"/></direction>')
            # accidental memory resets per PRINTED measure (splits carry it)
            if lm["first_of_printed"]:
                memory = {}
            beam_xml = _beam_xml(evs)
            for e, bx in zip(evs, beam_xml):
                _emit_event(w, e, memory, cur_key, bx)
            # pad under-full measures so parts stay aligned
            deficit = m_sum - lm["sums"].get(v, 0)
            if deficit > 1e-6:
                w(f'      <forward><duration>'
                  f'{int(round(deficit * DIVISIONS))}</duration></forward>')
            if lm["invisible_right"]:
                w('      <barline location="right">'
                  '<bar-style>none</bar-style></barline>')
            w('    </measure>')
        w('  </part>')
    w('</score-partwise>')
    return "\n".join(out)


def _beats_fraction(m_sum):
    if m_sum <= 0:
        return None
    for den, mult in ((4, 1), (8, 2), (16, 4)):
        n = m_sum * mult
        if abs(n - round(n)) < 1e-6:
            return (int(round(n)), den)
    return None


def _clef_xml(v):
    if v == "B":
        return '<clef><sign>F</sign><line>4</line></clef>'
    if v == "T":
        return ('<clef><sign>G</sign><line>2</line>'
                '<clef-octave-change>-1</clef-octave-change></clef>')
    return '<clef><sign>G</sign><line>2</line></clef>'


def _emit_event(w, e, memory, key_fifths, beam_xml=""):
    dur = int(round(e.total_beats * DIVISIONS))
    typ = TYPE_OF.get(e.beats)
    if e.kind == "rest":
        w('      <note><rest/>'
          f'<duration>{dur}</duration>'
          + (f'<type>{typ}</type>' if typ else "")
          + "".join('<dot/>' for _ in range(e.dots)) + '</note>')
        return
    key_map = {}
    if key_fifths > 0:
        for s_ in SHARP_ORDER[:key_fifths]:
            key_map[s_] = 1
    elif key_fifths < 0:
        for s_ in FLAT_ORDER[:-key_fifths]:
            key_map[s_] = -1
    for hi, h in enumerate(e.heads):
        letter = LETTERS[h.step % 7]
        octave = h.step // 7
        mkey = (letter, octave)
        if h.acc is not None:
            alter = h.acc
            memory[mkey] = alter
            acc_xml = f'<accidental>{ACC_NAMES[h.acc]}</accidental>'
        elif mkey in memory:
            alter = memory[mkey]
            acc_xml = ''
        else:
            alter = key_map.get(letter, 0)
            acc_xml = ''
        parts = ['      <note>']
        if hi > 0:
            parts.append('<chord/>')
        parts.append(f'<pitch><step>{letter}</step>')
        # Emit <alter> explicitly whenever it differs from natural OR the key
        # signature would otherwise alter this step (an unadorned <pitch> in a
        # sharp/flat key is still natural per MusicXML, but naive consumers
        # apply the key signature — an explicit 0 keeps everyone honest).
        if alter or key_map.get(letter, 0):
            parts.append(f'<alter>{alter}</alter>')
        parts.append(f'<octave>{octave}</octave></pitch>')
        parts.append(f'<duration>{dur}</duration>')
        if e.tie_start:
            parts.append('<tie type="start"/>')
        if e.tie_stop:
            parts.append('<tie type="stop"/>')
        if typ:
            parts.append(f'<type>{typ}</type>')
        parts.extend('<dot/>' for _ in range(e.dots))
        parts.append(acc_xml)
        if e.stem_dir:
            parts.append(f'<stem>{e.stem_dir}</stem>')
        if hi == 0 and beam_xml:
            parts.append(beam_xml)
        if e.tie_start or e.tie_stop:
            nots = []
            if e.tie_start:
                nots.append('<tied type="start"/>')
            if e.tie_stop:
                nots.append('<tied type="stop"/>')
            parts.append('<notations>' + "".join(nots) + '</notations>')
        if hi == 0 and e.lyric:
            # one <lyric number="k"> per verse, verse 1 first in document order
            # (the app reads lyric[0]; OSMD stacks all by their number attr).
            for ly in sorted(e.lyric, key=lambda d: d.get("number", 1)):
                parts.append(
                    f'<lyric number="{ly.get("number", 1)}">'
                    f'<syllabic>{ly["syllabic"]}</syllabic>'
                    f'<text>{_esc(ly["text"])}</text></lyric>')
        parts.append('</note>')
        w("".join(parts))


# ------------------------------------------------------------------------ main

def run(pdf_path, out_path=None, report_path=None, pages=None, quiet=False):
    report = Report()
    result = build_score(pdf_path, pages=pages, report=report)
    xml = emit_musicxml(result)
    # legacy-font coverage: if too many music glyphs went unmapped the Sonata
    # map is likely incomplete for this piece — surface it as a warning.
    unmapped = report.stats.get("unmapped_music_glyphs", 0)
    denom = report.stats.get("music_glyphs_total", 0) + unmapped
    if unmapped and denom and unmapped > 0.02 * denom:
        report.warn(f"legacy-font coverage: {unmapped} unmapped music glyphs "
                    f"= {100 * unmapped / denom:.1f}% of {denom} total — the "
                    f"Sonata glyph map may be incomplete for this piece")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml)
    rep = report.as_dict()
    rep["title"] = result["title"]
    rep["voices"] = result["voices"]
    rep["tempo_qpm"] = result["tempo"]
    rep["sections"] = result.get("sections", [])
    note_counts = {v: sum(len([e for e in m if e.kind == "note"])
                          for m in result["score"][v])
                   for v in result["voices"]}
    rep["note_events_per_voice"] = note_counts
    # max number of stacked verse lines seen under any staff (for future app UI)
    rep["lyric_verses"] = max(
        (ly.get("number", 1)
         for v in result["voices"] for m in result["score"][v]
         for e in m for ly in e.lyric),
        default=0)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    if not quiet:
        s = rep["stats"]
        print(f"[vector_extract] {pdf_path}")
        print(f"  title: {result['title']}")
        print(f"  systems: {s.get('systems')}  measures: {s.get('measures')}"
              f"  integrity: {s.get('measure_integrity_pct')}% of measures "
              f"have all voices agreeing on beat sums")
        print(f"  note events per voice: {note_counts}")
        secs = rep.get("sections") or []
        if len(secs) > 1:
            print(f"  sections: {len(secs)} detected")
            for sec in secs:
                print(f"    m{sec['measure']:>4}  {sec['title']}")
        print(f"  warnings: {len(rep['warnings'])}")
        for wmsg in rep["warnings"][:12]:
            print(f"    ! {wmsg}")
        if len(rep["warnings"]) > 12:
            print(f"    ... and {len(rep['warnings']) - 12} more (see report)")
    return result, rep, xml


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="output MusicXML path")
    ap.add_argument("--report", help="output JSON confidence report path")
    ap.add_argument("--pages", help="1-based page list, e.g. 2,3,4")
    args = ap.parse_args()
    pages = [int(p) for p in args.pages.split(",")] if args.pages else None
    run(args.pdf, args.out, args.report, pages)


if __name__ == "__main__":
    main()
