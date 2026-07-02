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
    dots: int = 0
    grace: bool = False


@dataclass(eq=False)
class Stem:
    x: float
    y0: float
    y1: float
    heads: list = field(default_factory=list)
    nbeams: int = 0
    flag: Optional[tuple] = None

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
    lyric: Optional[dict] = None
    unison_assumed: bool = False
    ambiguous: bool = False    # lone whole / centered rest on a shared staff

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


def _page_glyphs(page):
    """All font glyphs on the page with positions."""
    music, text_tokens = [], []
    raw = page.get_text("rawdict")
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                font = span["font"]
                is_music = "Bravura" in font or "Opus" in font or \
                           "Maestro" in font or "Leland" in font or \
                           "Emmentaler" in font
                if is_music:
                    for ch in span["chars"]:
                        bb = ch["bbox"]
                        music.append(Glyph(ord(ch["c"]), ch["origin"][0],
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
    return {"text": text, "x0": x0, "x1": x1, "cx": (x0 + x1) / 2, "y": y,
            "size": span["size"], "font": span["font"]}


def _page_paths(page):
    """Classified vector paths: staff-candidate hlines, short hlines, vlines,
    filled quads (beam candidates), curves (tie/slur candidates)."""
    long_h, short_h, vlines, quads, curves = [], [], [], [], []
    for d in page.get_drawings():
        items = d["items"]
        ops = "".join(i[0] for i in items)
        if set(ops) <= {"l"}:
            segs = [(i[1], i[2]) for i in items if i[0] == "l"]
            if len(segs) == 1:
                p1, p2 = segs[0]
                dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                if dy < 0.7 and dx > 2:
                    rec = (min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2)
                    (long_h if dx > 80 else short_h).append(rec)
                elif dx < 1.2 and dy > 2:
                    vlines.append(((p1.x + p2.x) / 2, min(p1.y, p2.y),
                                   max(p1.y, p2.y)))
            elif len(segs) >= 3 and d.get("fill") is not None:
                xs = [p.x for s in segs for p in s]
                ys = [p.y for s in segs for p in s]
                quads.append((min(xs), min(ys), max(xs), max(ys)))
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
    # merge duplicated segments at the same y (indented first system etc.)
    ys = {}
    for x0, x1, y in sorted(cands, key=lambda r: r[2]):
        key = None
        for yy in ys:
            if abs(yy - y) < 0.5:
                key = yy
                break
        if key is None:
            ys[y] = [x0, x1]
        else:
            ys[key][0] = min(ys[key][0], x0)
            ys[key][1] = max(ys[key][1], x1)
    items = sorted((y, x0, x1) for y, (x0, x1) in ys.items())
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


def _group_systems(staves, music_glyphs, page_no, report):
    """Group staves into systems. Prefer bracket glyphs (E003 top / E004
    bottom); fall back to gap-based grouping."""
    tops = sorted(g.y for g in music_glyphs if g.cp == 0xE003)
    bots = sorted(g.y for g in music_glyphs if g.cp == 0xE004)
    systems = []
    if tops and len(tops) == len(bots):
        for t, b in zip(tops, bots):
            ss = [s for s in staves if t - 8 <= s.top and s.bot <= b + 8]
            if ss:
                systems.append(System(staves=sorted(ss, key=lambda s: s.top),
                                      page=page_no))
        grouped = {id(s) for sy in systems for s in sy.staves}
        left = [s for s in staves if id(s) not in grouped]
        if left:
            report.warn(f"p{page_no}: {len(left)} staves outside any bracket "
                        f"— grouped as their own system")
            systems.append(System(staves=sorted(left, key=lambda s: s.top),
                                  page=page_no))
    else:
        # gap heuristic: same system if vertical gap < 2.5 staff heights
        cur = []
        for s in sorted(staves, key=lambda s: s.top):
            if cur and s.top - cur[-1].bot > 2.5 * (cur[-1].bot - cur[-1].top):
                systems.append(System(staves=cur, page=page_no))
                cur = []
            cur.append(s)
        if cur:
            systems.append(System(staves=cur, page=page_no))
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


def extract_page(page, page_no, report, measure_offset, tempo_state):
    music, tokens = _page_glyphs(page)
    long_h, short_h, vlines, quads, curves = _page_paths(page)
    staves = _find_staves(long_h, page_no, report)
    if not staves:
        report.note(f"p{page_no}: no staves — skipped (title/blank page)")
        return [], measure_offset
    systems = _group_systems(staves, music, page_no, report)
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

    # ---- stems & barlines from vlines
    # A head attaches to the stem nearest one of its EDGES (up-stems sit at
    # the right edge, down-stems at the left; chord seconds alternate sides).
    # One stem per head — unison primes (S half + A quarter on one pitch)
    # otherwise get cross-attached.
    stems, bar_candidates = [], []
    stem_recs = []
    for x, y0, y1 in vlines:
        s_near = _assign_staff(Glyph(0, x, (y0 + y1) / 2, x, y0, x, y1, 0),
                               all_staves)
        if s_near is None:
            continue
        sp = s_near.sp
        if y1 - y0 < 1.5 * sp:
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
        hit = 0
        for st in stems:
            if qx0 - 1.0 <= st.x <= qx1 + 1.0 and \
                    qy0 - 1.5 * s_near.sp <= st.y0 <= qy1 + 1.5 * s_near.sp or \
                    qx0 - 1.0 <= st.x <= qx1 + 1.0 and \
                    qy0 - 1.5 * s_near.sp <= st.y1 <= qy1 + 1.5 * s_near.sp:
                st.nbeams += 1
                hit += 1
        if hit < 2:
            report.stats["beam_quads_with_lt2_stems"] += 1

    # ---- flags -> stems
    for g in music:
        if g.cp in FLAGS:
            n, direction = FLAGS[g.cp]
            best, bd = None, 1e9
            for st in stems:
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
    for g in music:
        if g.cp == AUG_DOT:
            s = _assign_staff(g, all_staves)
            if s is None:
                continue
            cands = [h for h in heads if h.staff is s
                     and 0 < g.cx - h.g.x1 < 3.0 * s.sp
                     and abs(h.g.y - g.y) < 0.8 * s.sp]
            if cands:
                h = min(cands, key=lambda h: g.cx - h.g.x1)
                h.dots += 1
            else:
                report.warn(f"p{page_no}: augmentation dot at "
                            f"({g.x:.0f},{g.y:.0f}) matched no notehead")

    # ---- tempo (metronome mark: met-note glyph + '= NN' text)
    if tempo_state.get("bpm") is None:
        met = [g for g in music if g.cp in MET_NOTES]
        for g in met:
            for t in tokens:
                m = re.match(r"=?\s*(\d{2,3})$", t["text"].replace(" ", ""))
                if m and abs(t["y"] - g.y) < 12 and 0 < t["x0"] - g.x < 60:
                    unit = MET_NOTES[g.cp]
                    tempo_state["bpm"] = int(m.group(1)) * unit
                    report.note(f"p{page_no}: tempo mark -> quarter = "
                                f"{tempo_state['bpm']:.0f}")

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


def _build_system_events(sy, all_heads, all_stems, music, report, page_no):
    staff_ids = {id(s) for s in sy.staves}
    heads = [h for h in all_heads if id(h.staff) in staff_ids]
    sv = _staff_voices(sy)
    events = defaultdict(list)
    ambiguous_out = defaultdict(list)

    # 1. stemmed events (chords grouped by stem)
    used = set()
    for st in all_stems:
        st_heads = [h for h in st.heads if id(h.staff) in staff_ids
                    and h.stem is st]
        if not st_heads:
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
                   beats=beats, dots=max(h.dots for h in st_heads),
                   staff=staff, stem_dir=st.direction)
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
            ev = Event(x=g.x0, kind="rest", beats=RESTS[g.cp], staff=s)
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
                 stem_dir=ev.stem_dir, unison_assumed=ev.unison_assumed)


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
        sols_per_pair = []
        for up, down, staff in pairs:
            slo, shi = _measure_ranges(staff, sy.bar_xs)[mi]
            u_evs = [e for e in sy.events.get(up, [])
                     if e.staff is staff and slo <= e.x < shi]
            d_evs = [e for e in sy.events.get(down, [])
                     if e.staff is staff and slo <= e.x < shi]
            p_evs = [e for e in pending_by_staff.get(id(staff), [])
                     if slo <= e.x < shi]
            sols = _pair_solutions(u_evs, d_evs, p_evs, staff, up, down)
            sols_per_pair.append(sols)
        per_measure.append(sols_per_pair)

        # joint choice: same measure length across the staves, minimal cost
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
            # consensus measure length from the other voices
            others = []
            for ov in sy.events:
                if ov == v:
                    continue
                oevs = [e for e in sy.events[ov]
                        if mi < len(sranges) and
                        _measure_ranges(e.staff, sy.bar_xs)[mi][0] <= e.x <
                        _measure_ranges(e.staff, sy.bar_xs)[mi][1]]
                osum = sum(e.total_beats for e in oevs)
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


def _attach_lyrics(sy, tokens, report, page_no):
    """Lyric tokens live in the band below a staff; attach to nearest onset."""
    for si, staff in enumerate(sy.staves):
        band_top = staff.bot + 0.5 * staff.sp
        nxt = sy.staves[si + 1] if si + 1 < len(sy.staves) else None
        band_bot = (nxt.top - 2 * staff.sp) if nxt is not None \
            else staff.bot + 8 * staff.sp
        band = [t for t in tokens
                if band_top < t["y"] < band_bot
                and staff.x0 - 2 <= t["cx"] <= staff.x1 + 2
                and t["size"] > 6]
        if not band:
            continue
        # events that can carry a lyric: notes on this staff
        voices = [v for v, evs in sy.events.items()
                  if any(e.staff is staff for e in evs)]
        carriers = defaultdict(list)
        for v in voices:
            carriers[v] = [e for e in sy.events[v]
                           if e.staff is staff and e.kind == "note"]
        band.sort(key=lambda t: t["x0"])
        words = [t for t in band if t["text"].strip("-_")]
        for i, t in enumerate(words):
            txt = t["text"]
            prev_hyph = i > 0 and _hyphen_between(band, words[i - 1], t)
            next_hyph = i + 1 < len(words) and _hyphen_between(band, t, words[i + 1])
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
                if best.lyric is None:
                    best.lyric = {"text": txt, "syllabic": syl}
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
        if v1 == v2 and h1.step == h2.step and h1.staff is h2.staff:
            e1.tie_start = True
            e2.tie_stop = True
            report.stats["ties_detected"] += 1
        else:
            report.stats["slurs_detected"] += 1


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
    tempo_state = {"bpm": None}
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
    for sy in all_systems:
        ref_staff = sy.staves[0]
        ranges = _measure_ranges(ref_staff, sy.bar_xs)
        staff_ranges = {id(s): _measure_ranges(s, sy.bar_xs) for s in sy.staves}
        key = ref_staff.key_fifths
        for mi in range(len(ranges)):
            meta = {"key": key, "sums": {}, "system_page": sy.page}
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

    # measure-integrity check
    consistent = 0
    for i, meta in enumerate(measure_meta):
        sums = {v: round(meta["sums"].get(v, 0), 4) for v in voices_present}
        nonzero = [s for s in sums.values() if s > 0]
        if nonzero and max(nonzero) - min(nonzero) < 1e-6 and \
                len(nonzero) == len(voices_present):
            consistent += 1
        else:
            report.warn(f"measure {i + 1}: voice beat sums disagree: {sums}")
    report.stats["measures_with_consistent_beat_sums"] = consistent
    if n_meas:
        report.stats["measure_integrity_pct"] = round(100 * consistent / n_meas, 1)

    return {"title": title, "voices": voices_present, "score": score,
            "meta": measure_meta, "tempo": tempo_state["bpm"],
            "report": report}


def _find_title(doc, first_music_page, first_staff_top, report):
    """Largest text above the first staff on the first page with music."""
    raw = doc[first_music_page - 1].get_text("dict")
    best, bs = None, 0
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                if "Bravura" in s["font"] or any(0xE000 <= ord(c) <= 0xF8FF
                                                 for c in t):
                    continue   # music glyphs, not words
                if s["bbox"][1] < first_staff_top and len(t) > 3 and \
                        s["size"] > bs:
                    best, bs = t, s["size"]
    return best or "Untitled"


# --------------------------------------------------------------- MusicXML emit

DIVISIONS = 4
TYPE_OF = {4.0: "whole", 2.0: "half", 1.0: "quarter", 0.5: "eighth",
           0.25: "16th", 8.0: "breve"}


def _esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def emit_musicxml(result):
    score, voices = result["score"], result["voices"]
    meta = result["meta"]
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

    n_meas = len(meta)
    for i, v in enumerate(voices):
        w(f'  <part id="P{i + 1}">')
        cur_key = None
        cur_beats = None
        for mi in range(n_meas):
            evs = score[v][mi]
            m_sum = max([meta[mi]["sums"].get(vv, 0) for vv in voices] + [0])
            w(f'    <measure number="{mi + 1}">')
            attrs = []
            if mi == 0:
                attrs.append(f'<divisions>{DIVISIONS}</divisions>')
            if meta[mi]["key"] != cur_key:
                cur_key = meta[mi]["key"]
                attrs.append(f'<key><fifths>{cur_key}</fifths></key>')
            beats_frac = _beats_fraction(m_sum)
            if beats_frac and beats_frac != cur_beats:
                cur_beats = beats_frac
                bn, bt = beats_frac
                attrs.append(f'<time print-object="no"><beats>{bn}</beats>'
                             f'<beat-type>{bt}</beat-type></time>')
            if mi == 0:
                attrs.append(_clef_xml(v))
            if attrs:
                w('      <attributes>' + "".join(attrs) + '</attributes>')
            if mi == 0 and result["tempo"]:
                w(f'      <direction placement="above"><direction-type>'
                  f'<words></words></direction-type>'
                  f'<sound tempo="{result["tempo"]:.0f}"/></direction>')
            # accidental memory for this measure (per step+octave)
            memory = {}
            for e in evs:
                _emit_event(w, e, memory, cur_key)
            # pad under-full measures so parts stay aligned
            deficit = m_sum - meta[mi]["sums"].get(v, 0)
            if deficit > 1e-6:
                w(f'      <forward><duration>'
                  f'{int(round(deficit * DIVISIONS))}</duration></forward>')
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


def _emit_event(w, e, memory, key_fifths):
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
        if alter:
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
        if e.tie_start or e.tie_stop:
            nots = []
            if e.tie_start:
                nots.append('<tied type="start"/>')
            if e.tie_stop:
                nots.append('<tied type="stop"/>')
            parts.append('<notations>' + "".join(nots) + '</notations>')
        if hi == 0 and e.lyric:
            parts.append(f'<lyric><syllabic>{e.lyric["syllabic"]}</syllabic>'
                         f'<text>{_esc(e.lyric["text"])}</text></lyric>')
        parts.append('</note>')
        w("".join(parts))


# ------------------------------------------------------------------------ main

def run(pdf_path, out_path=None, report_path=None, pages=None, quiet=False):
    report = Report()
    result = build_score(pdf_path, pages=pages, report=report)
    xml = emit_musicxml(result)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml)
    rep = report.as_dict()
    rep["title"] = result["title"]
    rep["voices"] = result["voices"]
    rep["tempo_qpm"] = result["tempo"]
    note_counts = {v: sum(len([e for e in m if e.kind == "note"])
                          for m in result["score"][v])
                   for v in result["voices"]}
    rep["note_events_per_voice"] = note_counts
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
