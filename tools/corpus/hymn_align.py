#!/usr/bin/env python3
"""Align a hymn's audio (parallagi and/or melos) against its BOOK score slice.

Score side: global glyph records (extract_book output, 94-cluster ids) sliced
by (page, line) hymn range -> units (x-overlap groups: base + marks; red
gorgon-family attach as time marks, other red = martyria/fthora, silent).
Legend (unit-key -> interval) is LEARNED: parallagi recordings carry absolute
degree labels (parallagi_align output), so a DTW match units<->labeled events
turns each key's interval into a supervised estimate. Melos then aligns
against the same units under the learned legend.

Usage:
  hymn_align.py legend  <workdir> --hymns hymns.json     (joint legend EM)
  hymn_align.py melos   <workdir> --hymn NAME            (align one melos)
hymns.json rows: {name, p0, l0, p1, l1, parallagi_dir, melos_audio, melos_whisper}
  optional g0/g1: inclusive unit-index trim of the sliced stream (annotator
  glyph #s) for hymns that start/end mid-line between adjacent hymns.
Legend persists at <workdir>/legend_global.json and is updated by 'legend'.
"""
import json, os, sys
from collections import Counter, defaultdict
import numpy as np

GLYPHS = '/mnt/data/chant-corpus/scores/glyphs'
# ---- global cluster roles (94-cluster atlas read; intervals are LEARNED) ----
# RED_TIME was {11, 23, 22, 9} "gorgon + klasma-family hooks". Checked against
# the chanter's cluster export (datasets/exports/clusters/classifications.json,
# 2026-08-18) and the corpus: 9 and 22 are ALWAYS BLACK (110 / 2155 instances),
# so they never reached this red-only test at all, and 23 is ALWAYS RED (759) —
# meaning the sole producer of a "red klasma" was cluster 23, which the chanter
# classifies as "martyria-letter, Letter gamma for ga". Every beat it added was
# phantom. The klasma-family hook set is therefore empty; klasma is cluster 8,
# detected colour-blind below.
RED_TIME = set()
# martyria LETTER clusters -> absolute degree (chanter classifier pass
# 2026-08-18): 14=Πα 23=Γα 34=Δι 52=Κε 67=Βου. 24 REMOVED — it is the nana
# SCALE SIGN (≈Ga context), not the Νη letter; anchoring it to Νη=0 was a -3
# anchor error at Ga cadences. 26=Ζω kept but UNREVIEWED by the chanter.
# 26 = Ζω was carried UNREVIEWED for a long time; the chanter's 2026-08-19
# description of the Ζω martyria as "a greek zeta z with a psifiston looking
# thing under it" is the first confirmation of it, and it identified its
# companion mark as cluster 27 (see MARTYRIA_ANY).
# Nine more martyria letters, chanter-ruled 2026-08-19 from anchor_sheet.py.
# They were found by profile — RED, right-aligned at a line end, not a known
# martyria — after he identified cluster 89 from its shape: "the z martyrria zo
# … looks like a greek zeta z with a psifiston looking thing under it". Every
# instance of each cluster got the same reading, so these are cluster-level, not
# per-instance. 199 hymn openings whose pitch was unreadable.
# Chanter on how to read one: "the greek letters on the top portion of the
# martyria are the actual letters corresponding to the parallagi syllable. the
# symbols below indicate degree and scale (hard chromatic vs soft chromatic vs
# diatonic)" — so only the LETTER anchors, which is why the scale signs stay out
# of MARTYRIA_DEG and live in MARTYRIA_ANY.
MARTYRIA_DEG = {34: 4, 14: 1, 26: 6, 23: 3, 52: 5, 67: 2,
                77: 2, 49: 5, 54: 0, 44: 4, 51: 4, 89: 6, 37: 1, 29: 3, 65: 3}
# The martyria FAMILY, letters and scale signs together, from the chanter's
# atlas. Presence only — these are NOT degree anchors, and cluster 24 in
# particular was wrongly used as one before ("it is the nana scale sign,
# removed from degree anchors"). A scale sign says which scale, the letter says
# which degree, so only letters may anchor. But a cadence is marked by the
# whole compound, so detecting that a martyria is THERE needs the full set.
# 27 is the second part of the Ζω martyria, the same way 15 pairs under the Pa
# indicator. Chanter, 2026-08-19: "the z martyrria zo for some grave mode pieces
# looks like a greek zeta z with a psifiston looking thing under it" — the zeta
# is cluster 26 and the mark under it is 27. The corpus agrees flatly: all 66
# instances of 27 are RED, and 65 of them sit directly beneath a cluster 26.
# Neither 26 nor 27 is in the chanter's atlas, so both were unreviewed; this is
# the first evidence for either, and it confirms the 26=Ζω anchor the aligner had
# been carrying on trust.
MARTYRIA_ANY = set(MARTYRIA_DEG) | {15, 24, 27, 35, 38, 50, 56}
# ---- fthora / pthora ------------------------------------------------------
# A fthora RESPELLS the scale from the note it governs. Atlas, cluster 15, and
# the chanter states it as the general law: "Over a melodic glyph it is a
# FTHORA: that note becomes diatonic Pa regardless of where it lands — ALL
# fthores work this way (note takes on the new degree quality in the new
# scale)."
#
# So mechanically it is a martyria that also changes the genus: the note TAKES
# the named degree, and everything after is counted in the new scale. That is
# what SCALE_SIGN records — cluster -> (genus, degree) — read off the atlas
# names, with the genus vocabulary matching src/tuning/genus.rs.
#
# What is NOT yet known is which printed combination signals one. Every scale
# sign in this book is either stacked with a martyria letter (5995 of them) or
# alone on a heading line (344, mode titles, no neumes at all); NONE sits over a
# note on its own, so the atlas's "over a melodic glyph" shape does not occur
# here in isolation. The chanter's worked example on p375 l9 is a stack of THREE
# reds between two oligons — Πα above, then Κε with the ananes sign under it —
# which he reads as a martyria carrying a pthora to "ke in the diatonic scale".
# 603 stacks in the book hold more than one letter like that. Until he rules
# which part is the pthora, nothing sets `fthora` and the degree walk is
# unaffected; the machinery below is what his answer plugs into.
# The eight clusters the chanter ruled as PTHORAS, 2026-08-19, from
# pthora.html — each glyph boxed individually because "sometimes there is a
# pthora on top of martyria so i need to know specifically what it is".
#
#   2, 37, 39, 40, 45, 63, 65, 70   are pthoras          (708 glyphs)
#   55, 80, 81                      are not              (he ruled "none")
#
# 37 and 65 are in MARTYRIA_DEG as well. That is not a contradiction: he ruled
# on anchors.html what those signs NAME (Pa and Ga), and a pthora names a degree
# — so right-aligned at a hymn opening one still announces the starting pitch,
# which is how leading_anchor uses them. Their degree is therefore known; their
# GENUS is not, because that sheet asked only for the degree.
#
# The other six have no degree yet, so they are detected and flagged but change
# nothing. Note where they sit: 39 (220), 40 (181) and 45 (118) almost never
# share a column with a martyria — they stand over a note on their own, which is
# exactly the shape the atlas describes and which an earlier pass reported as
# occurring ZERO times. It missed them for the same reason the review sheet
# first failed to box them: it only considered clusters already in the table.
#
# WHERE it applies, chanter 2026-08-19: "the pthora effects the note that its on
# … if its on the martyria it changes it in place, if its on a note it effects
# after you move." So it never reaches forward to the following note — an
# earlier version of the review sheet drew it that way and he called it out.
#
#   on a NOTE      (642 of 690)  the note's own interval is applied first, and
#                                the note you land on takes the new degree
#   on a MARTYRIA   (48)         the martyria's stated degree is replaced where
#                                it stands; the next note still moves from it
#
# And WHICH note, when the figure is two: the DOWNBEAT one. Chanter: "i dont
# usually ever see pthora applied to the kentimata btw, could be wrong but they
# seem to only be applied on downbeats, not upbeats, and kentimata never occur
# on a down beat." That last clause is his own earlier ruling, the reason the
# kentimata figure is split at all — so a pthora over an oligon+kentimata
# belongs to the oligon whichever of the two it happens to overlap more.
PTHORA_SKIPS_UPBEAT = 17          # KENTIMATA, defined below
#
# For the degree stream the note case reduces to "this unit takes the pthora's
# degree", since after moving you are on that note either way. The martyria case
# is the one that differs: it rewrites the ANCHOR rather than a sounded note.
# Degrees here are NAMES, not indices, because an index means different things
# in different genera. Chanter, 2026-08-19: "when i say pa hard chromatic that
# means the 0th degree of the hard chromatic scale, remember there are 4 degrees
# repeated every 5th, and di hard chromatic is the 3rd degree (0indexed)."
# src/tuning/genus.rs already models it that way — HardChromatic is the cycle
# [6, 20, 4, 12] from Pa, which is a fourth phase repeating at the fifth, so Pa
# is phase 0 and Di phase 3, exactly as he says. A bare integer would silently
# mean the diatonic 0-6 position instead.
#
# For the degree STREAM this distinction does not bite — the overlay prints the
# parallagi syllable, and Pa is Pa in any genus — but it governs pitch, so the
# name is stored and the genus resolves it.
#
# On grave diatonic, also his: "technically diatonic is all the same there isnt a
# such thing as grave diatonic, but in practice there is.. ga is raised, and
# usually ke is sharpened too. but its technically not a different scale."
# genus.rs carries GraveDiatonic as its own variant for that practice; the theory
# note belongs beside it rather than a silent second diatonic.
DEG_NAME = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo']
HARD_CHROMATIC_PHASE = {'Pa': 0, 'Vou': 1, 'Ga': 2, 'Di': 3}   # repeats at the 5th
# All eight ruled on pthdeg.html, 2026-08-19, three examples each and consistent
# within every cluster.
PTHORA = {2:  ('diatonic', 'Pa'),
          37: ('hard_chromatic', 'Pa'),
          39: ('hard_chromatic', 'Di'),      # phase 3 of the four-step cycle
          40: ('diatonic', 'Ke'),
          45: ('diatonic', 'Di'),
          63: ('diatonic', 'Vou'),
          65: ('diatonic', 'Ni'),
          70: ('grave_diatonic', 'Zo')}
# 65 looked like a contradiction — ruled Ga on anchors.html and Ni on
# pthdeg.html — and it is not. He resolved it: "sometimes we see that pthora on
# ga for the triphonos where it basically makes ga a ni. but the martyria stays
# a ga if thats the case."
#
# Both readings hold at once. The NOTE becomes Ni; the martyria printed at that
# spot still shows Ga, because the notation is not rewritten — the reader applies
# the pthora. Which is why he answered Ga when shown the printed sign on
# anchors.html and Ni when asked what it respells to. MARTYRIA_DEG keeps Ga for
# what the glyph names as a martyria, and degree_stream already prefers a fthora
# over a mart_deg on the same unit, which is exactly this rule.
#
# The vocabulary underneath, also his: "'makes it a ga' is like us saying its
# phase 3 of the diatonic scale where normally phase 0 is the ni (goin intervals
# 12-10-8-12-12-10-8)". A degree name IS a phase of the running genus — Ni 0,
# Pa 1, Vou 2, Ga 3, Di 4, Ke 5, Zo 6 — which is why these tables store names
# and genus.rs stores the interval cycle each name indexes into.
PTHORA_UNRULED = set()
NOT_PTHORA = {55, 80, 81}
SCALE_SIGN = {15: ('diatonic', 'Pa'),
              24: ('diatonic', 'Ga'),         # nana
              35: ('diatonic', 'Di'),         # aghia
              38: ('hard_chromatic', 'Pa'),   # phase 0 of the four-step cycle
              50: ('diatonic', 'Ke'),         # ananes
              56: ('diatonic', 'Ni')}         # aghia
# ---- cluster 7 is TWO neumes, told apart by height ------------------------
# The extraction merged psifiston and omalon into one cluster. The chanter found
# it by eye while ruling the kentimata figures, 2026-08-19: "about half have
# omalon underneath" — in figures where the atlas said omalon (cluster 36) could
# not occur at all.
#
# The glyph boxes agree, and the separation is not a judgement call: cluster 7's
# height is bimodal with an EMPTY GAP — 7295 instances at 6.2-6.4 pt, 175 at
# 6.7-6.9 pt, and not one at 6.5 or 6.6. Rendered, the short one is the deep
# U-swoop of a psifiston and the tall one the flat level stroke omalon is named
# for. The chanter ruled 100 of the 175 on cluster7_sheet.py: omalon, 100 of 100.
#
# Neither neume carries an interval or a beat, so no degree and no duration
# moves. What moves is note SEGMENTATION: cluster 7 is a legal base, so a wide
# psifiston under two notes joins them into its own x-overlap group, while an
# omalon is a MARK_ONLY span mark that _note_subgroups is careful to let tie two
# notes without fusing them. That is the same defect already found and fixed for
# the omalons that were correctly clustered.
PSIFISTON, OMALON = 7, 36
OMALON_MIN_H = 6.6              # the empty gap in the height histogram


def _reclass(g):
    """Cluster id for one glyph record, splitting cluster 7 by height."""
    if g['cluster'] == PSIFISTON and g['y1'] - g['y0'] >= OMALON_MIN_H:
        return OMALON
    return g['cluster']


# Cluster 33 is the CHIASMA, the tempo sign — atlas: "a time signature for
# argosyntoma hymns". Chanter, 2026-08-19: "chiasma indicates time symbols …
# argo on top of the xhiasma means slower, and argon and a gorgon next to
# eachother on top of the chiasma mean not quite as slow (in between) and just
# the gorgon means fast. there are also digorgons on top for faster and
# trigorgons for really fast like recititive speed."
#
# It was BLACK and unclassified, so load_units took it as a NOTE BASE. Two
# consequences, both wrong, on 268 instances: it emitted a phantom note for a
# glyph that is never sung, and — because a group with a black candidate never
# reaches the martyria branch — it SWALLOWED the martyria printed with it. 198
# of the 268 sit in a martyria group, which is why hymns opening with a tempo
# sign had no anchor at all. Silencing it recovers both.
#
# A gorgon or argon riding on a chiasma is a TEMPO for the hymn, not a note's
# duration, so it must never reach beats_seq() — silencing the chiasma drops the
# whole group, and the reading is preserved as 'tempo' on the anchored unit.
# ---- tempo signs are COMPOUNDS, recorded by their parts --------------------
# A tempo marking is a CHIASMA with timing marks on it — chanter: "chiasma
# indicates time symbols … argo on top of the xhiasma means slower, and argon
# and a gorgon next to eachother on top of the chiasma mean not quite as slow
# (in between) and just the gorgon means fast. there are also digorgons on top
# for faster and trigorgons for really fast like recititive speed."
#
# The extraction merged each combination into its own cluster, so they arrive
# looking like four unrelated signs. They are not, and modelling them as four
# atomic tempi would be modelling the extraction rather than the notation —
# chanter, 2026-08-19: "they are actually compounds and the easier way is to
# look for them as composite parts and then infer that its a fast/slow whatever
# tempo marking". So what is recorded per cluster is its PARTS, and _tempo()
# derives the reading from them by the same rule it applies to a combination the
# book draws separately. A merged cluster that turns up later needs its parts
# listed here and nothing else; trigorgon/recitative has no cluster yet and will
# work the moment one appears.
TEMPO_PARTS = {33: frozenset({'chiasma', 'gorgon'}),
               42: frozenset({'chiasma', 'digorgon'}),
               43: frozenset({'chiasma', 'argon', 'gorgon'}),
               57: frozenset({'chiasma', 'argon'})}
CHIASMA = 33
# 42 (344), 43 (195) and 57 (60) were doing exactly what 33 did before it was
# silenced: black and unclassified, so read as NOTE BASES — phantom notes, and a
# swallowed martyria wherever one is printed with them, because a group holding
# a black candidate never reaches the martyria branch.
SILENT_BLACK = {12, 61, 55} | set(TEMPO_PARTS)
# 19 is the ANTIKENOMA. The atlas already calls it "orthographic/qualitative
# only, no quantitative value", but it was not MARK_ONLY, so — being ~34 pt wide
# — it was a legal base that swallowed every note it spanned. Chanter on
# 19|10be+17ab+21ab+22ab+4ab, 2026-08-19: "these are three compound glyphs. the
# antikenoma below the middle neume … is just overlapping the span of three
# neumes." Exactly the fusing defect already fixed for the omalon and the
# eteron; it just needs the same treatment.
MARK_ONLY = {36, 13, 27, 10, 16, 9, 19}  # dots/kentima slabs: never a base alone
# cluster 9 (chanter export): "Antikenoma that has a apli right underneath.
# Orthographical but the apli still applies. Apli adds the extra beat" — a mark
# compound, never a note, and it carries exactly one apli beat. Always black
# (110 instances), so the old red-only klasma test lost every one of them.
# Cluster 36 is the OMALON, not an apli (chanter, 2026-08-18, t03 gi6): it ties
# two notes and is qualitative/orthographic only, carrying no beat. It was
# adding a spurious beat to ~261 units corpus-wide.
# The real duration dots are cluster 10, and they are COUNTED, not flagged
# (chanter, 2026-08-18): "apli is one beat, dipli is two beats, tripli is 3".
# Corpus: 980 units carry one dot, 1092 two, 7 three — 2079 units that
# contributed no duration at all until this was wired.
DOTS = {10}
APLI_COMPOUND = {9}         # antikenoma+apli: one apli beat, never a note
# Gorgon family -> order k. Table-of-Byzantine-Notation-Symbols.pdf, "Rhythmic
# Symbols": a gorgon of order k takes k/(k+1) of a beat off a window of k+1
# symbols starting one BEFORE the sign. gorgon "takes half a beat off the
# symbol and the symbol before it (eighth notes)" -> ½ ½; digorgon "two-thirds
# off the symbol, and the symbols before and after it (triplets)" -> ⅓ ⅓ ⅓;
# trigorgon "¾ off the symbol, the symbol before it, and the two after it
# (sixteenth notes)" -> ¼ ¼ ¼ ¼. The PDF's second illustration of each is the
# klasma case (2 - ½ = 1½, 2 - ⅔ = 1⅓, 2 - ¾ = 1¼), which is exactly the
# chanter's t03 gi12 reading: "it steals a 1/2 beat from the previous note with
# the klasma which makes the previous note 1-1/2 beats".
GORGON_ORDER = {11: 1, 25: 2, 30: 3}
# Klasma "adds a beat to the symbol" (PDF). The atlas calls cluster 8 the BLACK
# klasma, and klasma detection used to look at RED glyphs only — so 2100 units
# carrying an 8ab/8be klasma added nothing, against 25 caught by the red path.
# Detection is now colour-blind.
KLASMA = {8}
# argon "adds a beat to the symbol and removes half a beat from the two
# symbols before it"
ARGON = {58, 90}
# ---- oligon + kentimata is TWO notes, not one net displacement -------------
# Chanter, 2026-08-19, resolving the last open figure in the atlas:
#
#   "yes oligon kentimata are two notes. oligon +1 then kentimata +1 (if the
#    oligon is on the bottom) byzantine neumes in general go bottom to top, the
#    other variation is the kentimata under the oligon. that means the kentimata
#    +1 first then the oligon +1. it's done that way because kentimata can never
#    be on a down beat."
#
# So the figure is read BOTTOM TO TOP and emits two units of +1 each. The
# pipeline used to emit one unit whose key (6|17ab) the canon legend gave +2 as
# net displacement: the running degree stayed right, but one label was printed
# where two belong, and the figure occupied one beat where it occupies two.
#
# Timing, same message:
#
#   "the meaning of the gorgon on top changes slightly. on top of the oligon
#    kentimata it makes both the oligon and the kentimata half a beat. in the
#    case of the kentimata under the oligon, the gorgon on top is as if the
#    gorgon is on the first neume, the kentimata, and therefore makes that neume
#    1/2 beat as well as the preceding note, shortening it by 1/2 beat
#    (following the general rules about gorgon/digorgon/trigorgon/dotted
#    equivalents) while the oligon maintains the full beat, and if a klasma or
#    apli/dipli/tripli is on the kentimata under the oligon the beats are added
#    to the oligon."
#
# Both timing rules fall straight out of the GENERIC gorgon window once the
# figure is two units and the gorgon is attached to the KENTIMATA — no special
# case is needed in beats_seq():
#
#   kentimata ABOVE (read oligon, kentimata): gorgon sits on the second unit, so
#     its k+1 window covers the oligon and the kentimata -> ½ ½, and it never
#     reaches the note before the figure. Exactly "makes both half a beat".
#   kentimata BELOW (read kentimata, oligon): gorgon sits on the first unit, so
#     its window covers the preceding note and the kentimata -> the kentimata is
#     ½ and the note before it loses ½, while the oligon keeps its full beat.
#     Exactly "as if the gorgon is on the first neume".
#
# Duration marks go the other way, to the OLIGON — his rule for the
# kentimata-below case. There is no above-case rule to write, because the
# chanter ruled the above case cannot happen: "kentimata over oligon never have
# klasma/apli ever so no need to infer or do a rule. that is probably 22 or 37
# mistakes on mcr".
#
# That is a testable prediction, and the corpus keeps it 113/113. Every one of
# the 113 split figures carrying a klasma or a dot is kentimata-BELOW-oligon —
# 6|17be+8ab (37), 7|17ab+6ab+8ab (22) and 19|10be+17ab+6ab (54) — and not one
# of the 3556 kentimata-above figures carries either. The 22 and 54 are worth
# noting: their keys mark every glyph 'ab' because those are positions relative
# to a psifiston/antikenoma BASE, not relative to the oligon, so the key alone
# cannot tell the two variants apart. Only the ken-vs-oligon geometry can, and it
# puts all 76 of them in the half his rule says they must be in. So the figures
# he suspected were MCR errors are not errors at all; they are the legal variant,
# and the pipeline had simply lost the distinction by reading position off the
# wrong glyph.
#
# It stays a prediction rather than an assumption: if an above-case figure ever
# does turn up carrying duration, _split_kentimata marks it 'suspect' rather than
# quietly handing the beat to the oligon, so it surfaces as a recognition error
# to check instead of as a silent extra beat.
# The figure's ORDER is read off the geometry, because the key cannot always
# carry it. In 6|17ab / 6|17be the 'ab'/'be' is measured against the oligon and
# says it outright. In 7|17ab+6ab (1012 in the book) it is measured against the
# PSIFISTON base, so both glyphs read 'above the base' and neither is known to be
# above the OTHER. Geometry splits those 1012 into 934 kentimata-over and 78
# kentimata-under, cleanly bimodal with an empty middle (+4.65..+4.85 pt under,
# -5.15..-4.70 pt over).
#
# The chanter reviewed all 78 on the review sheet (kentimata_sheet.py) and ruled
# them, 2026-08-19: "are all kentimata under. most have psifiston underneath and
# maybe gorgon or argo on top." So geometry is right 78/78 where he looked.
#
# His description also yields a NOTATIONAL check independent of the geometry, and
# it is nearly perfect: every one of the 78 carries a red timing mark on top
# (41 gorgon-family + 37 argon), against 1 of the 934. Two unrelated signals
# agreeing 1011/1012 is why the split is trusted on this key without hand-ruling
# the remaining 934.
OLIGON, KENTIMATA = 6, 17
# The CARRIER case. Chanter, 2026-08-19, ruling the whole family at once:
#
#   "apostrophos kentimata over oligon is just an apostrophos kentimata. oligon
#    is ignored. ison kentimata over oligon the olgion is ignored too. elafron
#    kentimata over oligon is also just elafron kentimata (-2 +1) and
#    occasionally the elafron is actually a running elafron so the other
#    possibility is running elafron kentimata over oligon, oligon is ignored and
#    it's the same as just having a running elafron and then an oligon."
#
# So there are two shapes, and which one applies turns on whether the figure
# holds a quantity BESIDES the oligon and the kentimata:
#
#   bare   — nothing else: the oligon is the melodic note. Two notes, +1 then +1,
#            ordered bottom to top (6|17ab, 6|17be).
#   carrier— something else: the oligon is orthographic "used as a table"
#            (atlas) and is DROPPED. Two notes, that neume then the kentimata's
#            +1. His last clause is the same statement: a kentimata after a
#            running elafron behaves as an oligon would, because +1 is what both
#            are worth.
#
# Every 17-bearing key that survives the bare split is a carrier one — 2135
# units — and the rule reproduces the atlas's independently locked NET values
# exactly, which is the check that it is right:
#   22|17be+21be  ison 0 + kentimata +1 = +1   atlas-locked +1
#   47|17be+21be  elafron -2 + kentimata +1 = -1   atlas-locked -1
# It also answers 4|17be+6be (660 units), where the carrier is drawn with the
# ordinary oligon cluster rather than 21: apostrofos -1 then kentimata +1, net 0,
# where the old fall-back to a bare apostrofos gave -1 as a single note.
CARRIER_OLIGON = 21
OLIGONS = {OLIGON, CARRIER_OLIGON}
# Neumes that can be the melodic partner in a carrier figure — things that are a
# NOTE on their own. Deliberately excludes the jump MARKS (16 kentima, 28 ypsili,
# 83): those modify a note rather than being one, so 28|17be+6be (23 units) and
# its relatives are left as single units for the chanter to rule on separately.
# 47 is the elaphron combination variant: the atlas gives it no interval of its
# own but locks 47|17be+21be at -1, which with the kentimata's +1 makes the
# elaphron -2 — the plain elaphron value.
CARRIER_PARTNER = {3: 1, 4: -1, 5: 0, 20: -2, 22: 0, 41: -1, 47: -2, 48: -4}
# A jump MARK is not a partner — it modifies the oligon, which stays the note.
# Chanter, 2026-08-19, ruling the figures the carrier rule did not reach:
#   "ypseli on the left of a kentimata means +5 then +1; ypseli on the right of
#    the kentimata means +4 then the kentimata +1"
#   "thats two notes, oligon with kentima on the right first +2, then the
#    kentimata (+1)"
#   "oligon + ypseli first (jump of +4) then kentimata, with a psifiston
#    underneath (psifiston must be used if oligon kentimata compounds are
#    followed by a descending neume)"
# The ypsili's LEFT/RIGHT is horizontal and the unit key only records ab/be,
# which is vertical — so the key cannot carry this and the interval is resolved
# here and written onto the unit as 'iv', which degree_stream prefers.
JUMP_MARK = {16: 2, 28: 4, 83: 7}
# The RUNNING ELAFRON is two glyphs that make ONE note. "the elaphrom with
# apostrophos inside the elafron is -3 and then the kentimata" — matching the
# atlas's locked 20|41be = -3.
RUNNING_ELAFRON = ({47, 41}, {20, 41})
# Not a note at all. Chanter on 4|17ab+4be+6ab: "is a mode signature it's just a
# martyria that is two steps up from vou ie dhi. for mode 2 usually used." So the
# whole compound anchors the degree rather than being sung, and emitting it as a
# note both invented a note and lost the anchor.
MODE_SIGNATURE = {'4|17ab+4be+6ab': 4}          # Δι
# ---- the yporrhoe is TWO notes in ONE glyph -------------------------------
# Atlas, cluster 18: "TWO notes -1 -1". It had no interval of its own, so all
# 1100 of them contributed ZERO to the degree stream — the single largest hole
# left in the legend. Chanter, 2026-08-19: "yes split the yporrhoe".
#
# Unlike the kentimata figure this is not two glyphs. It is one compact mark
# 6.0 pt wide (an oligon is 34), so there is no sub-geometry to divide and both
# notes carry the SAME box: the glyph simply stays lit across both. Halving a
# 6 pt box would repeat the mistake the chanter already called out on the
# kentimata, where the halves were not where the notes were.
#
# A gorgon rides on the SECOND note, so the generic beats_seq window covers the
# pair and makes both half a beat — the standard reading of a gorgon over a
# two-note figure. Duration marks go there too; the atlas notes the book draws
# yporrhoe + gorgon/digorgon as separate glyphs, so those reach this normally.
# Duration placement is INFERRED (37 units, 18|10be) and not yet chanter-ruled.
YPORRHOE = 18
YPORRHOE_STEP = -1
# ---- NOT IMPLEMENTED: the pthora ------------------------------------------
# One of the two 7|17ab+21ab+41ab+47ab figures (p375 l9) also carries a pthora,
# which RESPELLS the scale from that note on. The chanter's worked example,
# 2026-08-19, kept verbatim because it is the whole specification:
#
#   "that one is the same as previous but it also has a pthora symbol that
#    transforms the scale to be ke in the diatonic scale (ie degree 5) right on
#    the -3 note. in that case, since martyria before says high pa in hard
#    chromatic where it is degree3 in the hard chromatic scale (see chant script
#    rules where it is 0-indexed) (which is the π´ ie pa with a ' on it with the
#    circle with the / going out of the circle) going down three makes it ke so
#    that ke becomes the ke in the diatonic scale, then +1 lands on zo. there is
#    a psifiston below."
#
# Doing this properly means carrying the SCALE alongside the degree — the
# martyria's lower symbols say hard chromatic / soft chromatic / diatonic, and
# only the letter on top names the degree. degree_stream today tracks the degree
# alone, so a pthora cannot be expressed. Left unimplemented rather than faked;
# the running degree stays right through this figure because -3 then +1 holds in
# either spelling, only the SCALE it lands in is unrecorded.
# Clusters that carry melodic quantity (atlas: every cluster with a non-null
# interval, plus the jump marks).
MELODIC_CLUSTERS = {3, 4, 5, 6, 17, 20, 22, 41, 48, 83, 16, 28, 47}
NEUME_BAND = 22.0           # pt from a line's note centres; past this a red
                            # glyph is a heading, not part of the music
MART_OPEN_GAP = 40.0        # pt: past this a martyria is right-aligned, i.e.
                            # the next hymn's opening sign, NOT a cadence check
MIN_BEAT = 0.125            # floor: stacked deductions must not go negative
W_MV, MV_CAP = 1.0, 2.6
SKIP_U, SKIP_E = 1.2, 0.25
MAX_DU, MAX_DE = 4, 10
W_DUR, DUR_CAP = 0.5, 1.2
ITERS = 3

def beats_written(u):
    """Duration a unit carries on its own, BEFORE gorgon-family deductions.

    Chanter, 2026-08-18: the duration dots are counted, not flagged — "apli is
    one beat, dipli is two beats, tripli is 3". The PDF agrees: klasma "adds a
    beat", aplē "same as klasma", diplē "adds two beats", triplē "adds three".
    A rest is worth its dots.
    """
    if u.get('rest'):
        return float(u.get('dots', 0)) or 1.0
    return 1.0 + (1.0 if u['klasma'] else 0.0) + u.get('dots', 0)


def beats_seq(units):
    """Per-unit beats for a whole unit stream — the single source of truth.

    Must be a sequence pass, not a per-unit function: the gorgon family and the
    argon reach into their NEIGHBOURS, so a note's duration is not a property of
    that note alone. This is why callers take a list rather than mapping over
    units.
    """
    b = [beats_written(u) for u in units]
    n = len(b)
    # A note is shortened by AT MOST ONE gorgon-like sign. Chanter, 2026-08-19:
    # "no notes should ever be shortened twice. gorgons do not stack", and on
    # reviewing the actual pages: "they all apply to different notes … in all
    # cases every note is only being affected by one gorgon like entity at any
    # time."
    #
    # The signs themselves were detected correctly — he confirmed all 14 sampled
    # pairs as gorgon-family, including two his eye caught as digorgons, which is
    # what cluster 25 already is. The fault was purely arithmetic: a gorgon's
    # window is k+1 symbols starting one BEFORE the sign, so a note carrying its
    # own sign that was also reached by the next one lost its share twice. 622
    # notes ended on the MIN_BEAT floor that way — the floor admitting the logic
    # was wrong rather than protecting against anything.
    #
    # A note's OWN sign wins; a neighbour's reach applies only to a note that has
    # none. That keeps the klasma reading intact (a 2-beat note under a gorgon is
    # 1½) and keeps the chanter's kentimata-under-oligon rule, where the gorgon
    # does shorten the note before the figure — that note simply has no sign of
    # its own to defend it.
    ded = [0.0] * n
    own = [False] * n
    for j, u in enumerate(units):
        k = u.get('timing', 0)
        if not k:                   # gorgon k=1, digorgon k=2, trigorgon k=3
            continue
        d = k / (k + 1.0)           # ½, ⅔, ¾
        for i in range(j - 1, j + k):        # k+1 symbols, starting one before
            if not 0 <= i < n:
                continue
            if i == j:              # the note the sign is written on
                ded[i], own[i] = d, True
            elif not own[i]:        # a neighbour's reach, only if unclaimed
                ded[i] = max(ded[i], d)
    for i in range(n):
        b[i] -= ded[i]
    for j, u in enumerate(units):
        if u.get('argon'):
            b[j] += 1.0
            for i in (j - 1, j - 2):
                if i >= 0:
                    b[i] -= 0.5
    return [max(x, MIN_BEAT) for x in b]


def beats_of(u):
    """Deprecated single-unit view — no neighbour effects. Use beats_seq()."""
    return max(beats_written(u) - (0.5 if u.get('timing') else 0.0), MIN_BEAT)


def _xov(a, b):
    """x-overlap wide enough to call two glyphs part of one figure"""
    return (min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
            > 0.35 * min(a['x1'] - a['x0'], b['x1'] - b['x0']))


def _note_subgroups(cands):
    """Split base candidates that a wide SPAN mark merged transitively.

    Candidates that DIRECTLY x-overlap are one compound note (ison printed over
    a petasti, petasti+oligon). Candidates that never touch each other are
    separate notes which a connector merely ties together, and used to be fused
    into a single unit. Chanter, t03 gi6: "it should be split into an oligon and
    ison (two neumes)… the omalon is qualitative/orthographic", and "another
    glyph that is sometimes two wide is the eteron".

    The span marks this rescues, by how often they bridge two notes:
      31  red,   w~39  bridges 324/325 occurrences  — ETERON (chanter-confirmed)
      36  black, w~35  bridges 225/261              — OMALON (chanter-confirmed)
      25  red,   w~18  digorgon (thirds across 3 notes)
      74  red,   w~44  bridges 10/10                — wide eteron variant, unconfirmed
      85  red,   w~38  tie/syndesmos
      30  red,   w~25  trigorgon
    The rule is generic, so a span mark does not need to be classified for its
    notes to come apart correctly.
    """
    subs, used = [], [False] * len(cands)
    for i in range(len(cands)):
        if used[i]:
            continue
        cur = [cands[i]]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(cands)):
                if used[j]:
                    continue
                if any(_xov(x, cands[j]) for x in cur):
                    cur.append(cands[j])
                    used[j] = True
                    changed = True
        subs.append(cur)
    subs.sort(key=lambda s: min(x['x0'] for x in s))
    return subs


def _tempo(grp):
    """The tempo a group's sign states. See TEMPO_SIGN for the chanter's scale.

    Read off the CLUSTER, because the timing is part of the sign's shape here.
    A separate gorgon or argon glyph riding on the sign is honoured too, for the
    combinations the book may write out rather than merge — but it is never
    allowed to reach beats_seq(), because this is a tempo for the hymn and not a
    half-beat stolen from the note before.
    """
    ORDER = {'gorgon': 1, 'digorgon': 2, 'trigorgon': 3}
    parts = set()
    for x in grp:
        parts |= TEMPO_PARTS.get(x['cluster'], set())     # merged compound
        if x['cluster'] in GORGON_ORDER:                  # drawn separately
            parts.add({1: 'gorgon', 2: 'digorgon', 3: 'trigorgon'}[
                GORGON_ORDER[x['cluster']]])
        if x['cluster'] in ARGON:
            parts.add('argon')
    k = max((ORDER[p] for p in parts if p in ORDER), default=0)
    if 'argon' in parts:
        return 'medium' if k else 'slow'     # "not quite as slow (in between)"
    return {0: 'plain', 1: 'fast', 2: 'faster', 3: 'recitative'}[k]


def _mk_unit(pl, mine, base, fig, part=None, sx=None, yr=None, drop=()):
    """One unit from a glyph group. `drop` removes clusters that belong to the
    figure's OTHER half (see _split_kentimata); `sx` is the shared sort x of a
    split figure, since its notes are stacked and cannot be ordered by x0."""
    mine = [x for x in mine if x is base or x['cluster'] not in drop]
    black = [x for x in mine if not x['red']
             and x['cluster'] not in SILENT_BLACK]
    marks = []
    for x in black:
        if x is base:
            continue
        pos = ('ab' if (x['y0'] + x['y1']) / 2
               < (base['y0'] + base['y1']) / 2 - 1 else 'be')
        marks.append(f"{x['cluster']}{pos}")
    timing = max((GORGON_ORDER[x['cluster']] for x in mine
                  if x['cluster'] in GORGON_ORDER), default=0)
    x0, x1 = min(x['x0'] for x in mine), max(x['x1'] for x in mine)
    y0, y1 = yr if yr else (min(x['y0'] for x in mine), max(x['y1'] for x in mine))
    return {'pl': pl, 'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1,
            'sx': x0 if sx is None else sx,
            'key': f"{base['cluster']}|{'+'.join(sorted(marks))}",
            'base': base['cluster'],
            'gorgon': timing >= 1, 'klasma': any(x['cluster'] in KLASMA for x in mine),
            'timing': timing, 'rest': False,
            'argon': any(x['cluster'] in ARGON for x in mine),
            'dots': (sum(1 for x in black if x['cluster'] in DOTS)
                     + sum(1 for x in black if x['cluster'] in APLI_COMPOUND)),
            'apli': any(x['cluster'] in DOTS or x['cluster'] in APLI_COMPOUND
                        for x in black),
            # 'fig' is the unit's index in the PRE-SPLIT stream, which is what a
            # chanter-marked g0/g1 or pin index means — reindex_kentimata.py
            # migrates through it. It is unique only WITHIN one load_units call:
            # units_for() calls load_units once per page and concatenates, so fig
            # repeats across pages. Group on (pl, fig), or use 'part' — 0 opens a
            # split figure and 1 continues it — which needs no key at all.
            'fig': fig, 'part': part}


def _split_yporrhoe(pl, mine, fig, base):
    """The yporrhoe as its two descending notes. See YPORRHOE above."""
    # The gorgon goes on the FIRST note. Chanter, 2026-08-19: "the yporrhoe
    # having gorgon on top means gorgon is applied to the first note of the
    # yporrhoe" — so the generic window covers the note BEFORE the figure and
    # the yporrhoe's first note, leaving its second note a full beat. Exactly
    # the kentimata-under-oligon shape, and the opposite of what this did: the
    # gorgon sat on the second note and made the pair ½ + ½.
    #
    # Duration marks stay on the second note, where the figure is held. The
    # first note otherwise takes the bare glyph; an earlier version passed it
    # the non-gorgon marks too and so counted a klasma twice, once per half.
    #
    # The two notes DESCEND, and the glyph is drawn that way, so the highlight
    # splits it top half then bottom half. Chanter, 2026-08-19: "for yphorroe
    # highlight top half then the bottom half". Vertical, unlike anything else
    # here — the kentimata figure is two separate glyphs and keeps its own boxes.
    ym = (base['y0'] + base['y1']) / 2
    gorgons = [x for x in mine if x['cluster'] in GORGON_ORDER]
    gids = {id(x) for x in gorgons}
    rest = [x for x in mine if id(x) not in gids]
    out = [_mk_unit(pl, [base] + gorgons, base, fig, part=0, sx=base['x0'],
                    yr=(base['y0'], ym)),
           _mk_unit(pl, rest, base, fig, part=1, sx=base['x0'],
                    yr=(ym, base['y1']))]
    for u in out:
        u['iv'] = YPORRHOE_STEP
    return out


def _kentimata_pair(mine):
    """The figure's two notes, or None if this group is not one.

    Returns (partner, kentimata, carrier) where `partner` is the glyph the
    kentimata is a second note to and `carrier` is the orthographic oligon to
    drop, if any. See the CARRIER_PARTNER block above for the chanter's rule.
    """
    ken = [x for x in mine if x['cluster'] == KENTIMATA]
    oli = [x for x in mine if x['cluster'] in OLIGONS]
    if len(ken) != 1 or len(oli) != 1:
        return None
    ken, oli = ken[0], oli[0]
    others = [x for x in mine if x is not ken and x is not oli
              and x['cluster'] in MELODIC_CLUSTERS]
    if not others:
        return oli, ken, None, None          # bare: the oligon IS the note
    jumps = [x for x in others if x['cluster'] in JUMP_MARK]
    notes = [x for x in others if x['cluster'] in CARRIER_PARTNER]
    if len(jumps) == 1 and not notes:
        # the oligon stays the note, the mark says how far it jumps
        j = jumps[0]
        if j['cluster'] == 28:
            # left of the kentimata the oligon counts too (+1 +4); right of it
            # the oligon is orthographic and only the ypsili's +4 is sung
            iv = 5 if (j['x0'] + j['x1']) < (ken['x0'] + ken['x1']) else 4
        else:
            iv = JUMP_MARK[j['cluster']]
        return oli, ken, None, iv
    if not jumps and notes:
        if len(notes) == 1:
            return notes[0], ken, oli, None
        if {x['cluster'] for x in notes} in RUNNING_ELAFRON:
            head = max(notes, key=lambda x: (x['x1'] - x['x0']) * (x['y1'] - x['y0']))
            return head, ken, oli, -3
    return None


def _split_kentimata(pl, mine, fig, oli, ken, carrier=None, iv=None):
    """The kentimata figure as its two notes, in reading order.

    `oli` is the melodic partner — the oligon itself in the bare figure, or the
    apostrofos/ison/elaphron it carries in the carrier figure, where `carrier`
    is the orthographic oligon to drop.

    Bare figure: bottom to top, the lower glyph is sung first. Carrier figure:
    the partner is always first, since the carrier oligon it sits on is not
    sung at all and the kentimata is what follows it.

    The gorgon family goes with the KENTIMATA and the duration marks with the
    partner — see the chanter quotes at OLIGON/KENTIMATA above; between them
    those two assignments make the generic beats_seq() window produce both of
    his timing rules.

    Each note keeps its OWN glyph's box. An earlier version split the figure's
    box into left and right halves so two parallagi labels would not collide,
    but the notes are not laid out left-to-right — they are stacked — so the
    playback highlight lit the left half and then the right half of one glyph.
    Chanter, 2026-08-19: "that is not the intuitive way of doing that. I would
    instead only highlight the oligon, and then for the second one highlight the
    kentimata." Which is what a true box gives.

    Reading order can then no longer come from x0, since a kentimata sitting
    UNDER an oligon is sung first but starts further right. 'sx' carries the
    figure's shared x for sorting and 'part' breaks the tie, leaving x0/x1/y0/y1
    free to describe the glyph the chanter actually sees lit.
    """
    # in a carrier figure the partner is always sung first; only the bare
    # figure is ordered by which glyph sits lower on the page
    below = (carrier is None
             and (ken['y0'] + ken['y1']) / 2 > (oli['y0'] + oli['y1']) / 2 + 1)
    first, second = (ken, oli) if below else (oli, ken)
    if carrier is not None:
        mine = [x for x in mine if x is not carrier]
    X0 = min(x['x0'] for x in mine)
    gorgons = [x for x in mine if x['cluster'] in GORGON_ORDER]
    gids = {id(x) for x in gorgons}          # identity: glyph dicts compare equal
    # the kentimata half: its own glyph plus the gorgon family, nothing else
    ken_mine = [ken] + gorgons
    # the oligon half: everything else, so klasma/apli/dipli/tripli land here
    oli_mine = [x for x in mine if x is not ken and id(x) not in gids]
    if not oli_mine:
        oli_mine = [oli]
    a_mine, b_mine = ((ken_mine, oli_mine) if below else (oli_mine, ken_mine))
    out = [
        _mk_unit(pl, a_mine, first, fig, part=0, sx=X0, drop={KENTIMATA}),
        _mk_unit(pl, b_mine, second, fig, part=1, sx=X0, drop={KENTIMATA}),
    ]
    if iv is not None:
        # explicit reading from the chanter; the key cannot express it
        (out[1] if below else out[0])['iv'] = iv
    if not below and any(u['klasma'] or u['dots'] for u in out):
        # cannot happen in the book as read today (0 of 3556) — see above
        for u in out:
            u['suspect'] = ('duration mark on a kentimata-over-oligon figure: '
                            'the chanter rules this impossible, so the glyph '
                            'recognition is likely wrong here')
    return out


def _attach_pthoras(units, recs):
    """Hang each pthora on the unit it sits over. See PTHORA for the rules.

    A pthora on a MARTYRIA is left alone here: it rewrites an anchor, not a
    sounded note, and the anchor is resolved by leading_anchor() outside this
    function. Only the note case is attached.
    """
    if not units:
        return
    import statistics as _st
    by_line = defaultdict(list)
    for u in units:
        if not u.get('rest'):
            by_line[u['pl']].append(u)
    for g in recs:
        if not g['red'] or g['cluster'] not in PTHORA:
            continue
        us = by_line.get((g['page'], g['line']))
        if not us:
            continue
        cy = _st.median([(u['y0'] + u['y1']) / 2 for u in us])
        if abs((g['y0'] + g['y1']) / 2 - cy) > NEUME_BAND:
            continue                      # a heading, not part of the music
        hits = [u for u in us
                if min(u['x1'], g['x1']) - max(u['x0'], g['x0']) > 1]
        if not hits:
            continue                      # on a martyria, or on nothing
        u = max(hits, key=lambda u: min(u['x1'], g['x1']) - max(u['x0'], g['x0']))
        if u['base'] == PTHORA_SKIPS_UPBEAT:      # never the upbeat half
            sib = [q for q in us if q.get('fig') == u.get('fig') and q is not u]
            if sib:
                u = sib[0]
        u['fthora'] = PTHORA[g['cluster']]


def load_units(p0, l0, p1, l1):
    """units for the hymn slice [(p0,l0) .. (p1,l1))"""
    recs, lyr = [], []
    for p in range(p0, p1 + 1):
        f = os.path.join(GLYPHS, f'page{p:03d}.json')
        d = json.load(open(f))
        for g in d['glyphs']:
            key = (p, g['line'])
            if (p == p0 and g['line'] < l0) or (p == p1 and g['line'] >= l1) \
               or p > p1:
                continue
            g['cluster'] = _reclass(g)
            recs.append(g)
        for w in d.get('lyrics', []):
            if (p == p0 and w.get('line', 0) < l0) or (p == p1 and w.get('line', 0) >= l1):
                continue
            lyr.append(w)
    units = []
    fig = 0                  # index in the PRE-SPLIT unit stream (see 'fig')
    pending_open = None      # a martyria printed before the first note
    by_line = defaultdict(list)
    for g in recs:
        by_line[(g['page'], g['line'])].append(g)
    for pl in sorted(by_line):
        gl = sorted(by_line[pl], key=lambda g: g['x0'])
        used = [False] * len(gl)
        for i, g in enumerate(gl):
            if used[i]:
                continue
            grp = [g]; used[i] = True
            changed = True
            while changed:
                changed = False
                for j, h in enumerate(gl):
                    if used[j]:
                        continue
                    if any(min(x['x1'], h['x1']) - max(x['x0'], h['x0'])
                           > 0.35 * min(x['x1'] - x['x0'], h['x1'] - h['x0'])
                           for x in grp):
                        grp.append(h); used[j] = True; changed = True
            cands = [x for x in grp if not x['red']
                     and x['cluster'] not in SILENT_BLACK
                     and x['cluster'] not in MARK_ONLY]
            if not cands:
                n_dots = sum(1 for x in grp if x['cluster'] in DOTS)
                if n_dots:
                    # vareia + aplē/diplē/triplē and no note = a REST worth that
                    # many beats. Chanter, 2026-08-18: "rests should be units,
                    # they take up time … even if the chanter skips them … it is
                    # still what the music notation is saying one should do".
                    # 81 of these corpus-wide, every one exactly (10, 12), and
                    # all were being dropped for having no base candidate.
                    units.append({'pl': pl, 'x0': min(x['x0'] for x in grp),
                                  'x1': max(x['x1'] for x in grp),
                                  'y0': min(x['y0'] for x in grp),
                                  'y1': max(x['y1'] for x in grp),
                                  'key': 'rest', 'base': None, 'rest': True,
                                  'gorgon': False, 'klasma': False,
                                  'timing': 0, 'argon': False, 'dots': n_dots,
                                  'apli': True, 'fig': fig, 'part': None})
                    fig += 1
                    continue
                # martyria letters state the ABSOLUTE degree of the melody at
                # this cadence — recorded as an anchor on the previous unit
                degs = [MARTYRIA_DEG[x['cluster']] for x in grp
                        if x['red'] and x['cluster'] in MARTYRIA_DEG]
                if degs and not units:
                    # A martyria with NOTHING before it — the very first thing on
                    # the page. It cannot attach to the previous unit because
                    # there is none, and it was being dropped on the floor.
                    # Chanter, on s01: "the first martyria in theos kyrios that
                    # im pinning is ga but for somereason the glyph 0 says zo" —
                    # the Γα opening p520 line 0 was lost, so leading_anchor fell
                    # back to the previous page's trailing Ζω.
                    #
                    # NO `continue` here, deliberately. This branch must not
                    # change the control flow, because 'fig' has to keep counting
                    # exactly as it did — it is the key the chanter's hand-marked
                    # g0/g1 are migrated through, and an extra or missing slot
                    # slides every index on the page. Recording it and falling
                    # through leaves the numbering untouched.
                    pending_open = degs[0]
                if any(x['cluster'] in TEMPO_PARTS for x in grp):
                    # 'fig' must keep meaning "index in the stream the chanter
                    # counted against", because reindex_kentimata.py migrates his
                    # hand-marked g0/g1 and pins through it. The chiasma used to
                    # emit a phantom note, so it occupied an index in that
                    # stream; silencing it here would silently renumber every
                    # figure after it and slide 19 of his 47 marked ranges. It
                    # keeps its slot without producing a unit.
                    fig += 1
                if degs and units:
                    # A line can END with TWO martyrias: the CADENCE one that
                    # names the note just sung, printed right after it, and the
                    # OPENING one for the next hymn, right-aligned to the far
                    # margin. Chanter: "the opening one is right aligned to the
                    # end of the last hymn". Both land on the same unit — the
                    # last note of the line — and the assignment below is a
                    # plain overwrite, so the opening one silently destroyed the
                    # cadence one. Example: page 521 line 4 carries Ζω at x=167
                    # (the cadence) and Γα at x=515 (the opening), and unit 68
                    # kept only Γα.
                    #
                    # mart_deg KEEPS the overwrite, because leading_anchor()
                    # wants exactly the right-aligned opening one and every
                    # anchor in use depends on that. mart_all preserves the whole
                    # sequence in printed order, so the cadence martyria — which
                    # is the checksum the parallagi overlay marks — is no longer
                    # thrown away. 91 units corpus-wide carry more than one.
                    units[-1].setdefault('mart_all', []).extend(degs)
                    # OPENING vs CADENCE. Chanter, 2026-08-19: "sometimes the
                    # right aligned martyria are just a sign for the opening of
                    # the next hymn and dont act as a checksum btw. little weird
                    # but it happens." So the two kinds mean different things and
                    # must not be pooled: a cadence martyria NAMES the note just
                    # sung and is a checkable claim about the melody; a
                    # right-aligned one announces the next hymn's starting pitch
                    # and says nothing about the note it is printed beside.
                    #
                    # They separate on the x-gap to whatever is printed before
                    # them, which is flatly bimodal over the book: 679 martyrias
                    # sit within 20 pt (inline) and 254 at 80 pt or more
                    # (flung out to the margin), with a thin valley between —
                    # hence the 40 pt cut. On page 521 line 4 the cadence Ζω has
                    # a 7 pt gap and the opening Γα a 336 pt one.
                    if any(x['cluster'] in TEMPO_PARTS for x in grp):
                        units[-1]['tempo'] = _tempo(grp)
                    left = [h for h in gl if h['x1'] <= min(x['x0'] for x in grp) + 1]
                    gap = (min(x['x0'] for x in grp) - max(h['x1'] for h in left)
                           if left else 0.0)
                    if gap >= MART_OPEN_GAP:
                        units[-1]['mart_open'] = degs[0]
                    else:
                        units[-1].setdefault('mart_cad', []).extend(degs)
                    units[-1]['mart_deg'] = degs[0]
                continue                      # martyria/silent group: no slot
            # one unit per NOTE, not per x-overlap group: a span mark that ties
            # two notes must not fuse them (see _note_subgroups)
            subs = _note_subgroups(cands)
            spans = [(min(x['x0'] for x in s), max(x['x1'] for x in s)) for s in subs]
            cand_ids = {id(c) for c in cands}
            extra = [[] for _ in subs]
            for x in grp:                     # marks/reds go to the note they cover most
                if id(x) in cand_ids:
                    continue
                k = max(range(len(subs)),
                        key=lambda i: min(x['x1'], spans[i][1]) - max(x['x0'], spans[i][0]))
                extra[k].append(x)
            for s, ex in zip(subs, extra):
                mine = s + ex
                base = max(s, key=lambda x: (x['x1'] - x['x0']) * (x['y1'] - x['y0']))
                if pending_open is not None:
                    _pend, pending_open = pending_open, None
                else:
                    _pend = None
                n_before = len(units)
                if base['cluster'] == YPORRHOE:
                    units.extend(_split_yporrhoe(pl, mine, fig, base))
                else:
                    pair = _kentimata_pair(mine)
                    if pair is not None:
                        units.extend(_split_kentimata(pl, mine, fig, *pair))
                    else:
                        u = _mk_unit(pl, mine, base, fig)
                        if u['key'] in MODE_SIGNATURE:
                            if units:
                                units[-1]['mart_deg'] = MODE_SIGNATURE[u['key']]
                                units[-1].setdefault('mart_cad', []).append(
                                    MODE_SIGNATURE[u['key']])
                            pending_open = _pend    # nothing sounded; keep waiting
                            fig += 1
                            continue
                        units.append(u)
                if _pend is not None and len(units) > n_before:
                    units[n_before]['mart_before'] = _pend   # the note it opens
                fig += 1
    # sort on the figure's shared x, then on reading order within it
    _attach_pthoras(units, recs)
    units.sort(key=lambda u: (u['pl'], u.get('sx', u['x0']),
                              u['part'] if u.get('part') is not None else 0))
    return units, lyr

def load_units_h(h):
    """units + lyrics for a hymns.json row. Optional g0/g1 (annotator glyph
    #s, inclusive) trim the unit stream when a hymn starts or ends mid-line —
    adjacent hymns share lines, so (page,line) ranges alone over-slice.
    unitdeg_*/iv_ovr_* indices are relative to THIS trimmed stream."""
    units, lyr = load_units(h['p0'], h['l0'], h['p1'], h['l1'])
    g0, g1 = h.get('g0'), h.get('g1')
    if g0 is None and g1 is None:
        return units, lyr
    lo = 0 if g0 is None else int(g0)
    hi = len(units) - 1 if g1 is None else int(g1)
    kept = units[lo:hi + 1]
    if kept:
        pl0, kx0 = kept[0]['pl'], kept[0]['x0']
        pl1, kx1 = kept[-1]['pl'], kept[-1]['x1']
        def _keep(w):
            pl = (w['page'], w.get('line', 0))
            if pl < pl0 or pl > pl1:
                return False
            if pl == pl0 and w['x1'] < kx0 - 2:
                return False
            if pl == pl1 and w['x0'] > kx1 + 2:
                return False
            return True
        lyr = [w for w in lyr if _keep(w)]
    return kept, lyr

W_ABS, ABS_CAP = 0.55, 2.0
W_MART = 1.6

def iv_of(iv, u):
    """unknown mark-combos fall back to the bare base glyph's interval
    (marks are mostly quality/time; better than a silent 0 default)"""
    k = u['key']
    if k in iv:
        return iv[k]
    return iv.get(f"{u['base']}|", 0)

def dtw(units, deg_obs, iv, start=None, times=None, spb=None, drone_c=None,
        exp_abs=None, beats=None):
    """monotonic DTW: units claim labeled events; movement cost on degree
    deltas under the current legend + ABSOLUTE degree anchor (score-side
    cumulative degree from a fitted hymn start-degree — prevents the path
    sliding off-by-one through repeated-glyph stretches).
    start=None searches the best start degree; returns (path, start, cost).

    REST units never reach the DP: they are notated silence, so they can never
    claim a sung event, but the time they occupy still has to separate the notes
    on either side. They are filtered out here and their beats folded into the
    PRECEDING note. Chanter, 2026-08-18: "on a rest, the chanter STOPS singing …
    it should be folded into the duration of the PREVIOUS note, otherwise the
    next note will go on for too long instead of being delayed the duration of
    the rest as it should." Since the duration prior measures onset-to-onset,
    charging the rest to the note before it is what delays the next onset;
    charging it forward would have stretched the wrong note.
    Returned path indices are always against the ORIGINAL unit stream."""
    if any(u.get('rest') for u in units):
        keep = [j for j, u in enumerate(units) if not u.get('rest')]
        if not keep:
            return None
        allb = beats if beats is not None else beats_seq(units)
        cb = np.concatenate([[0.0], np.cumsum(allb)])
        # each kept note carries its own beats plus any rest that FOLLOWS it,
        # up to the next kept note
        kb = []
        for m, j in enumerate(keep):
            nxt = keep[m + 1] if m + 1 < len(keep) else len(allb)
            kb.append(float(cb[nxt] - cb[j]))
        got = dtw([units[j] for j in keep], deg_obs, iv, start=start, times=times,
                  spb=spb, drone_c=drone_c,
                  exp_abs=([exp_abs[j] for j in keep]
                           if exp_abs is not None else None),
                  beats=kb)
        if got is None:
            return None
        path, st, cost = got
        return [(keep[j], k) for j, k in path], st, cost
    N, K = len(units), len(deg_obs)
    exp = np.zeros(N + 1)
    for j, u in enumerate(units):
        exp[j + 1] = exp[j] + iv_of(iv, u)
    if exp_abs is not None:
        # parallagi-anchored ABSOLUTE degree per unit overrides the
        # legend-cumulative expectation (kills tail-key error accumulation)
        exp[1:] = np.asarray(exp_abs, dtype=float)
        exp[0] = exp[1]
        start = 0
    if start is None:
        # start and the caller's Ni/degree hypothesis are coupled through the
        # absolute term — a narrow search around the observed opening suffices
        est = int(round(float(np.median(deg_obs[:6]))) - round(exp[1]))
        best = None
        for s in range(est - 2, est + 3):
            got = dtw(units, deg_obs, iv, start=s, times=times, spb=spb,
                      drone_c=drone_c, exp_abs=exp_abs, beats=beats)
            if got and (best is None or got[2] < best[2]):
                best = got
        return best
    BIG = 1e18
    deg = np.asarray(deg_obs, dtype=float)
    abs_c = W_ABS * np.minimum(np.abs(deg[None, :] - (start + exp[1:])[:, None]),
                               ABS_CAP)                       # [j, k]
    mart_c = np.zeros((N, K))
    for j, u in enumerate(units):
        md = u.get('mart_deg')
        if md is not None:
            mart_c[j] = W_MART * np.min(np.abs(
                deg[None, :] - (md + 7 * np.arange(-1, 2))[:, None]), axis=0)
    dd = {o: deg[o:] - deg[:-o] for o in range(1, MAX_DE + 1)}   # deg[k]-deg[k-o]
    fee = np.full(K, SKIP_E)
    if drone_c is not None:
        fee = np.where(np.abs(np.asarray(drone_c[1]) - drone_c[0]) <= 45.0,
                       0.05, SKIP_E)          # ison-singer captures skip cheap
    FEE = np.concatenate([[0.0], np.cumsum(fee)])
    use_dur = times is not None and spb is not None
    if use_dur:
        t = np.asarray(times, dtype=float)
        dt = {o: np.maximum(t[o:] - t[:-o], 0.02) for o in range(1, MAX_DE + 1)}
        bs = np.array(beats if beats is not None else beats_seq(units))
        CB = np.concatenate([[0.0], np.cumsum(bs)])
    D = np.full((N, K), BIG)
    Pj = np.full((N, K), -1, dtype=np.int32)
    Pk = np.full((N, K), -1, dtype=np.int32)
    k0 = min(8, K)
    D[0, :k0] = 0.3 * np.arange(k0) + abs_c[0, :k0] + mart_c[0, :k0]
    for j in range(1, N):
        best = np.full(K, BIG)
        bj = np.full(K, -1, dtype=np.int32)
        bk = np.full(K, -1, dtype=np.int32)
        for j2 in range(max(0, j - MAX_DU), j):
            ce = exp[j + 1] - exp[j2 + 1]
            base_pen = SKIP_U * (j - j2 - 1)
            row = D[j2]
            if use_dur:
                # elapsed beats from the ONSET of j2 to the ONSET of j, i.e. the
                # durations of units j2 .. j-1. This used to read
                # CB[j+1] - CB[j2+1] (units j2+1 .. j) — off by one unit, which
                # was invisible while every beat was 1.0 or 2.0 and became real
                # the moment the duration model gave units 0.125 .. 4.0 beats.
                B = max(CB[j] - CB[j2], 0.25)
            for o in range(1, MAX_DE + 1):
                if o >= K:
                    break
                skip_fees = FEE[o:K] - FEE[1:K - o + 1] if o > 1 else 0.0
                cand = (row[:-o] + W_MV * np.minimum(np.abs(dd[o] - ce), MV_CAP)
                        + base_pen + skip_fees)
                if use_dur:
                    cand = cand + W_DUR * np.minimum(
                        np.abs(np.log(dt[o] / (B * spb))), DUR_CAP)
                upd = cand < best[o:]
                if upd.any():
                    idx = np.nonzero(upd)[0] + o
                    best[idx] = cand[idx - o]
                    bj[idx] = j2
                    bk[idx] = idx - o
        D[j] = best + abs_c[j] + mart_c[j]
        Pj[j], Pk[j] = bj, bk
    endc = D[N - 1] + 0.3 * (K - 1 - np.arange(K))
    if float(endc.min()) >= BIG * 0.5:
        return None
    k = int(np.argmin(endc))
    cost = float(endc[k])
    path, j = [], N - 1
    while j >= 0 and k >= 0:
        path.append((j, k))
        j, k = int(Pj[j, k]), int(Pk[j, k])
    path.reverse()
    return path, start, cost

def dtw_time(units, times):
    """bootstrap matching: beat-position vs time-position (parallagi is
    note-precise, ~1:1) — no interval knowledge needed"""
    beats = np.array(beats_seq(units))
    cb = np.concatenate([[0], np.cumsum(beats)])
    pos_u = cb[:-1] / max(cb[-1], 1e-9)
    t = np.array(times)
    pos_e = (t - t[0]) / max(t[-1] - t[0], 1e-9)
    N, K = len(units), len(t)
    BIG = 1e18
    D = np.full((N, K), BIG)
    P = np.full((N, K, 2), -1, dtype=int)
    D[0, :min(8, K)] = 0.3 * np.arange(min(8, K))
    for j in range(1, N):
        for k in range(1, K):
            b, ba = BIG, (-1, -1)
            for j2 in range(max(0, j - MAX_DU), j):
                for k2 in range(max(0, k - MAX_DE), k):
                    if D[j2, k2] >= BIG:
                        continue
                    c = (D[j2, k2] + 6.0 * abs(pos_u[j] - pos_e[k])
                         + SKIP_U * (j - j2 - 1) + SKIP_E * (k - k2 - 1))
                    if c < b:
                        b, ba = c, (j2, k2)
            D[j, k] = b
            P[j, k] = ba
    ends = [(D[N - 1, k] + 0.3 * (K - 1 - k), k) for k in range(K) if D[N - 1, k] < BIG]
    if not ends:
        return None
    _, k = min(ends)
    path, j = [], N - 1
    while j >= 0 and k >= 0:
        path.append((j, k))
        j, k = P[j, k]
    path.reverse()
    return path

# chanter-verified cluster identities (scores/atlas_chanter.json, 2026-08-18):
# these keys are GROUND TRUTH — seeded into every legend and LOCKED against EM
# vote overwrites, because the previous rotated seed (4=oligon 5=apostrofos
# 6=ison) was "confirmed" by EM through circular unitdeg pairing. Kentima
# composites: 16be (below/right of base) = +2, 16ab (top-middle) = +3.
CHANTER_LOCK = {'6|': 1, '5|': 0, '4|': -1, '3|': 1, '17|': 1, '20|': -2,
                '6|16be': 2, '6|16ab': 3, '3|16ab': 3,
                # classifier pass 2026-08-18 (marks: 8=klasma, 17=kentimata,
                # 21=carrier oligon, 22=ison-variant, 41=apostrofos-variant,
                # 13=oligon-variant, 10=apli/dipli dots):
                '22|': 0, '48|': -4, '41|': -1,
                '3|13ab': 2, '3|13ab+8be': 2,        # petasti+oligon = +2
                '20|41be': -3, '20|41be+8ab': -3,    # apostrofos in elafron
                '3|22ab': 0, '3|22ab+8be': 0,        # ison over petasti
                '22|17be+21be': 1,                   # ison+kentimata/carrier
                '7|17ab+21ab+22ab': 1,               # same over psifiston
                '47|17be+21be': -1,                  # elafron+kentimata/carrier
                '20|10be+10be': -2}                  # elafron + dipli dots


def cmd_legend(wd, hymns):
    os.makedirs(wd, exist_ok=True)
    lg_path = os.path.join(wd, 'legend_global.json')
    if os.path.exists(lg_path):
        iv = dict(json.load(open(lg_path))['keys'])
    else:
        iv = {}
    iv.update(CHANTER_LOCK)
    data = []
    for h in hymns:
        if not h.get('parallagi_dir'):
            continue
        evf = os.path.join(h['parallagi_dir'], 'events_full.jsonl')
        if not os.path.exists(evf):
            continue
        ev = [json.loads(l) for l in open(evf)]
        deg = [r['degree_abs'] for r in ev]
        times = [r['t0'] for r in ev]
        units, _ = load_units_h(h)
        data.append((h['name'], units, deg, times))
        n_mart = sum('mart_deg' in u for u in units)
        print(f"{h['name'][:44]:44s} units {len(units):4d} labeled-events "
              f"{len(deg)} martyries {n_mart}")
    for it in range(ITERS):
        votes = defaultdict(list)
        agree = tot = 0
        for name, units, deg, times in data:
            got = dtw(units, deg, iv)
            path = got[0] if got else None
            if not path:
                continue
            for (j2, k2), (j, k) in zip(path, path[1:]):
                if j - j2 == 1:
                    votes[units[j]['key']].append(deg[k] - deg[k2])
                exp = sum(iv.get(units[x]['key'], 0) for x in range(j2 + 1, j + 1))
                tot += 1
                agree += (deg[k] - deg[k2] == exp)
        changed = 0
        for key, obs in votes.items():
            if key in CHANTER_LOCK:
                continue               # ground truth never yields to votes
            if len(obs) >= 2:
                new = int(np.clip(round(float(np.median(obs))), -4, 4))
                if iv.get(key) != new:
                    iv[key] = new
                    changed += 1
        print(f"legend iter {it}: agreement {agree / max(tot, 1):.2f} "
              f"({tot} pairs), {changed} keys changed, {len(iv)} keys known")
    support = Counter()
    for name, units, deg, times in data:
        got = dtw(units, deg, iv)
        path = got[0] if got else []
        for j, _ in path:
            support[units[j]['key']] += 1
        # persist unit -> absolute degree (parallagi-anchored); unmatched
        # units fill by cumulating legend intervals from the nearest match
        ud = {j: int(deg[k]) for j, k in path}
        filled = {}
        last = None
        for j in range(len(units)):
            if j in ud:
                filled[j] = ud[j]
                last = j
            elif last is not None:
                filled[j] = filled[j - 1] + iv_of(iv, units[j])
        for j in range(len(units) - 1, -1, -1):
            if j not in filled and j + 1 in filled:
                filled[j] = filled[j + 1] - iv_of(iv, units[j + 1])
        json.dump({str(j): filled[j] for j in sorted(filled)},
                  open(os.path.join(wd, f'unitdeg_{name}.json'), 'w'))
    json.dump({'keys': iv, 'support': dict(support)}, open(lg_path, 'w'), indent=1)
    print(f"saved {len(iv)} keys -> {lg_path}")
    for k, n in support.most_common(12):
        print(f"  {k:14s} -> {iv.get(k, 0):+d}  (matched {n})")

SOFT_CYCLE = [8, 14, 8, 12]
HARD_STEPS = [4, 6, 20, 4, 12, 6, 20]     # octave-cyclic, hard chromatic from Πα
CPM = 1200.0 / 72.0

def trochos(d):
    """soft-chromatic absolute ladder position (moria), fifth-periodic"""
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += SOFT_CYCLE[i % 4]
    else:
        for i in range(-1, d - 1, -1):
            m -= SOFT_CYCLE[i % 4]
    return m

def hard_pos(d):
    """hard-chromatic absolute ladder position (moria), octave-cyclic"""
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += HARD_STEPS[i % 7]
    else:
        for i in range(-1, d - 1, -1):
            m -= HARD_STEPS[i % 7]
    return m

DIA_STEPS = [12, 10, 8, 12, 12, 10, 8]

def dia_pos(d):
    m = 0.0
    if d >= 0:
        for i in range(d):
            m += DIA_STEPS[i % 7]
    else:
        for i in range(-1, d - 1, -1):
            m -= DIA_STEPS[i % 7]
    return m

# mode 2 uses BOTH scales by genre (chanter guidance): soft chromatic for the
# sticheraric verses, hard chromatic from Πα for heirmologic pieces — the
# score marks it with different martyria/fthores. Until fthora clusters are
# decoded, cmd_melos hypothesis-tests the ladders per hymn (or honors an
# explicit hymns.json 'genus': diatonic modes pass 'diatonic').
LADDERS = {'soft_chromatic': trochos, 'hard_chromatic': hard_pos,
           'diatonic': dia_pos}

def cmd_melos(wd, hymns, name):
    import subprocess
    h = next(x for x in hymns if x['name'] == name)
    iv = json.load(open(os.path.join(wd, 'legend_global.json')))['keys']
    units, lyr = load_units_h(h)
    # chanter interval overrides ({unit_index: interval}, from the annotator
    # verification lane): the Ioannou font prints some neumes shape-identically
    # (ison vs oligon are the same bar), so shape-level extraction can't
    # disambiguate — the chanter's reading wins. Implemented by giving the
    # unit a synthetic private key so every iv_of lookup resolves to the
    # override without touching the shared legend.
    ivo = os.path.join(wd, f'iv_ovr_{name}.json')
    if os.path.exists(ivo):
        iv = dict(iv)
        n_ovr = 0
        for k, v in json.load(open(ivo)).items():
            j = int(k)
            if 0 <= j < len(units):
                units[j]['key'] = f'#ovr{j}'
                iv[f'#ovr{j}'] = v
                n_ovr += 1
        print(f'  {n_ovr} chanter interval overrides from {os.path.basename(ivo)}')
    udf = os.path.join(wd, f'unitdeg_{name}.json')
    unit_deg = None
    if os.path.exists(udf):
        raw_ud = {int(k): v for k, v in json.load(open(udf)).items()}
        if len(raw_ud) >= 0.8 * len(units):
            unit_deg = [raw_ud.get(j) for j in range(len(units))]
    mdir = os.path.join(wd, 'melos_' + name)
    os.makedirs(mdir, exist_ok=True)
    wav = os.path.join(mdir, 'audio.wav')
    if not os.path.exists(os.path.join(mdir, 'voice_notes.json')):
        # NEVER let ffmpeg write through audio.wav. It may be a SYMLINK to the
        # corpus source (restore_melos_audio.py makes it one to avoid a second
        # copy of 1.1 GB), and 'ffmpeg -y -i SRC ... audio.wav' then reads and
        # writes the same file: on 2026-08-19 that truncated
        # pieces/.../004_melos_fixed.wav from 53.4 s to 4.8 s. It was rebuilt
        # from the tape via texts/recut_grave-orthros.json, which records the
        # span it was cut from at corr 1.0 — but nothing should depend on such a
        # record existing. Render to a scratch file and move it into place, which
        # REPLACES the symlink and leaves its target untouched.
        tmp = wav + '.tmp.wav'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', h['melos_audio'],
                        '-ac', '1', '-ar', '44100', tmp], check=True)
        os.replace(tmp, wav)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(
            os.path.abspath(__file__)), '..', 'mcr', 'segment_tracks.py'),
            wav, mdir], check=True)
    vn = json.load(open(os.path.join(mdir, 'voice_notes.json')))
    cents = np.array([v[2] for v in vn])
    dur = np.array([v[1] - v[0] for v in vn])
    # Ni search: histogram peak is SOME degree; quantize events -> degrees
    # under each hypothesis and take the best DTW fit against the score
    hist, edges = np.histogram(cents, bins=np.arange(cents.min(), cents.max() + 30, 30),
                               weights=np.clip(dur, 0, 3))
    peak = float(edges[np.argmax(hist)] + 15)
    drone_lvl = peak            # most-persistent level = ison candidate
    best = None
    # genre determines genus (chanter rule: stichera=soft, heirmologic=hard
    # chromatic in mode 2) — honor hymns.json when it says so
    lads = ({h['genus']: LADDERS[h['genus']]} if h.get('genus') in LADDERS
            else LADDERS)
    for genus, pos in lads.items():
        for kdeg in range(0, 8):
            ni = peak - pos(kdeg) * CPM
            lad = {d: ni + pos(d) * CPM for d in range(-8, 16)}
            deg_obs = [min(lad, key=lambda d: abs(lad[d] - c)) for c in cents]
            ev_t = [v[0] for v in vn]
            beats_tot = sum(beats_seq(units))
            spb = max((ev_t[-1] - ev_t[0]) / max(beats_tot, 1.0), 0.05)
            got = dtw(units, deg_obs, iv, times=ev_t, spb=spb,
                      drone_c=(drone_lvl, cents), exp_abs=unit_deg)
            if got and (best is None or got[2] < best[3]):
                best = (kdeg, ni, got[0], got[2], deg_obs, genus, got[1], lad)
    kdeg, ni, path, cost, deg_obs, genus, start_deg, lad0 = best
    # empirical per-degree center refit (Vasilikos's practice sits 30-70c off
    # theory; nearest-THEORY quantization mislabels borderline notes). Two
    # rounds: matched events vote centers (clamped +-80c of theory), events
    # requantize, re-align.
    exp_cum = {}
    deg_obs_kept = deg_obs
    for _ in range(2):
        d = start_deg
        if unit_deg is not None:
            exp_by_unit = list(unit_deg)
        else:
            exp_by_unit = []
            for u in units:
                d += iv_of(iv, u)
                exp_by_unit.append(d)
        by_deg = {}
        for j, k in path:
            by_deg.setdefault(exp_by_unit[j], []).append(cents[k])
        emp = dict(lad0)
        for dg, cs_ in by_deg.items():
            if dg in emp and len(cs_) >= 2:
                th = lad0[dg]
                emp[dg] = float(np.clip(np.median(cs_), th - 80, th + 80))
        deg_obs = [min(emp, key=lambda dd: abs(emp[dd] - c)) for c in cents]
        ev_t = [v[0] for v in vn]
        got = dtw(units, deg_obs, iv, start=None if unit_deg else start_deg,
                  exp_abs=unit_deg,
                  drone_c=(drone_lvl, cents), times=ev_t,
                  spb=max((ev_t[-1] - ev_t[0]) / max(sum(
                      beats_seq(units)), 1.0), 0.05))
        if not got:
            break
        def agree_of(pth, dobs):
            ok = n = 0
            for (j2, k2), (j, k) in zip(pth, pth[1:]):
                e = sum(iv_of(iv, units[x]) for x in range(j2 + 1, j + 1))
                n += 1
                ok += (dobs[k] - dobs[k2] == e)
            return (ok / n if n else 0.0), n
        a_old, n_old = agree_of(path, best[4] if _ == 0 else deg_obs_kept)
        a_new, n_new = agree_of(got[0], deg_obs)
        # accept only if internal consistency improves (cost is not
        # comparable across different quantizations)
        if (a_new, n_new) > (a_old, n_old):
            path, start_deg, cost = got
            deg_obs_kept = deg_obs
        else:
            deg_obs = best[4] if _ == 0 else deg_obs_kept
            break
    agree = tot = 0
    agree_c = 0
    pos_g = LADDERS[genus]
    exp_deg_cum = []
    dd_ = start_deg
    for u in units:
        dd_ += iv_of(iv, u)
        exp_deg_cum.append(dd_)
    for (j2, k2), (j, k) in zip(path, path[1:]):
        if unit_deg is not None:
            exp = unit_deg[j] - unit_deg[j2]
            e1, e2 = unit_deg[j], unit_deg[j2]
        else:
            exp = sum(iv_of(iv, units[x]) for x in range(j2 + 1, j + 1))
            e1, e2 = exp_deg_cum[j], exp_deg_cum[j2]
        tot += 1
        agree += (deg_obs[k] - deg_obs[k2] == exp)
        # attraction-tolerant: sung interval within 55c of the notated one
        # (a note under έλξεις deviates by design — performance practice,
        # not misalignment)
        obs_c = cents[k] - cents[k2]
        exp_c = (pos_g(e1) - pos_g(e2)) * CPM
        agree_c += (abs(obs_c - exp_c) <= 55.0)
    out = []
    for j, k in path:
        u = units[j]
        out.append({'unit': int(j), 'page': int(u['pl'][0]), 'line': int(u['pl'][1]),
                    'key': u['key'], 'interval': int(iv.get(u['key'], 0)),
                    't0': float(vn[k][0]), 't1': float(vn[k][1]),
                    'cents': float(cents[k]), 'degree_obs': int(deg_obs[k]),
                    'gorgon': bool(u['gorgon']), 'klasma': bool(u['klasma'])})
    json.dump(out, open(os.path.join(mdir, 'aligned.json'), 'w'), indent=1)
    if '--em' in sys.argv:
        # melos-EM: matched single-step pairs vote intervals for keys the
        # parallagi seed didn't cover (agreement ~0.83 -> votes trustworthy)
        lg = json.load(open(os.path.join(wd, 'legend_global.json')))
        votes = defaultdict(list)
        for (j2, k2), (j, k) in zip(path, path[1:]):
            if j - j2 == 1:
                votes[units[j]['key']].append(deg_obs[k] - deg_obs[k2])
        changed = 0
        for key, obs in votes.items():
            if len(obs) >= 3:
                new = int(np.clip(round(float(np.median(obs))), -4, 4))
                if lg['keys'].get(key) != new:
                    lg['keys'][key] = new
                    changed += 1
        json.dump(lg, open(os.path.join(wd, 'legend_global.json'), 'w'), indent=1)
        print(f"  em: {changed} keys updated ({len(lg['keys'])} known)")
    summ = {'hymn': name, 'genus': genus, 'start': int(start_deg),
            'ni_cents_rel55': round(float(ni), 1),
            'n_units': len(units),
            'n_events': len(vn), 'n_matched': len(path), 'coverage_units_pct':
            round(100 * len(path) / max(len(units), 1), 1),
            'movement_agreement': round(agree / max(tot, 1), 2),
            'movement_agreement_cents': round(agree_c / max(tot, 1), 2),
            'ni_hz': round(55 * 2 ** (ni / 1200), 1)}
    json.dump(summ, open(os.path.join(mdir, 'summary.json'), 'w'), indent=1)
    print(f"{name:24s} {genus[:4]:4s} units {len(units):4d} events {len(vn):4d} "
          f"matched {len(path):4d} ({summ['coverage_units_pct']}%) mv-agree "
          f"{summ['movement_agreement']} Ni {summ['ni_hz']}Hz")

if __name__ == '__main__':
    mode = sys.argv[1]
    wd = sys.argv[2]
    hymns = json.load(open(sys.argv[sys.argv.index('--hymns') + 1]))
    if mode == 'legend':
        cmd_legend(wd, hymns)
    elif mode == 'melos':
        name = sys.argv[sys.argv.index('--hymn') + 1]
        cmd_melos(wd, hymns, name)
