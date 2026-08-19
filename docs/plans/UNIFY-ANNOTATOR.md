# Plan: unify the tooling and put the golden hymns in the annotator

Written to be executed by a session with **no prior context**. Everything
needed is either here or at a named path. Read this whole file before starting.

Repo: `/mnt/data/code/byzorgan-web-worktrees/chant-annotator`, branch
`chant-align-dataset`.

---

## 1. What the user actually wants

One annotator, containing the hymns he has verified, each named by its own
first words, with the score's implied parallagi printed over the neumes so he
can spot and flag errors.

His words:

> "i want the parallagi to show above the glyphs"
> "no i want it on the main score annotator... why did you make a new app"
> "but the spans are entire pieces though!"
> "can we name them by the first few words of the melos (and the corresponding
> parallagi also named)"

The last two are the design: **a span IS a piece**, and pieces are named from
the score's lyric layer.

---

## 2. State on disk

### The gold data (this is the valuable part — do not regenerate or overwrite)

| what | where |
|---|---|
| 47 audio spans, chanter-cut by ear | `/mnt/data/chant-corpus/texts/cuts_grave-orthros.json` |
| 47 score ranges, chanter-marked | `/mnt/data/chant-corpus/texts/scorecuts_grave-orthros.json` |
| tape-level gold dataset + caveats | `datasets/grave-orthros-tape-gold/` |
| 76 pins + per-glyph notes on one hymn | `datasets/grave-orthros-t03-gold/` |
| span names from score incipits | `/mnt/data/chant-corpus/texts/span_names_grave-orthros.json` |

A span record: `{hymn, t0, t1, lane, label, t_in, skips}` where `lane` is
`melos`/`parallagi`, `t_in` marks where the apichima (held νε) ends and the
notated notes begin, and `skips` are intervals to exclude (Vasilikos talking
mid-span).

A score range: `{hymn, p0, l0, g0, p1, l1, g1, label}` — page, line, and UNIT
index (compound neume), which is the coordinate `load_units_h` already uses.

### The two apps that must become one

**Main annotator** — `tools/chant-reel/annotator/`, systemd user unit
`chant-annotator`, port 8779, reachable at
**https://annotator.lab.alwaysdobetterllc.com/**. Per-piece: pins, glyph notes,
MCR lane, score strip. This is the one the user works in. Pieces live in
`data/<piece-id>/` with `data/index.json` as the picker manifest; 179 exist
already, built by `tools/corpus/prep_hymn_annotator.py` from `hymns.json`.

**Cutter** — `tools/corpus/cutter/`, systemd user unit `chant-cutter`, port
8790, whose routes are proxied through 8779. Whole-tape: waveform, span
marking, score-range picking, parallagi overlay, flagging. Built this session.

The cutter should KEEP its boundary-marking job — that is genuinely
tape-level and has no home in a per-piece annotator. What must move into the
main annotator is the **parallagi overlay and flagging**, and the gold spans
must become annotator pieces.

---

## 3. Facts that cost a lot to establish — do not re-derive or contradict

**Identification from audio does not work.** Four attempts, all at chance:
hymn text over the corpus (20%), text restricted to melos spans (2/8),
score-degrees force-aligned against ASR (2/23), score-degrees against pitch
(1/21). Do not build another one. Names come from the SCORE's lyric layer,
which works (47/47).

**Never score anything by CTC loss.** The loss gate rated identification 81%
when the truth was 20%. Score against the chanter's own data:
`tools/corpus/name_check.py`, `heuristics_eval.py`, and his spans.

**The legend was wrong and is now derived from his atlas.** Use
`/mnt/data/chant-corpus/scores/legend_canon.json`, built by
`tools/corpus/legend_canon.py` from `scores/atlas_chanter.json` (his verified
cluster identities). It agrees with his 25 per-glyph notes 9/9; the old learned
`legend_global.json` agrees 6/9 and is circular (fitted to parallagi).
**Never use `legend_merged.json`** — it is the rotated seed the atlas
explicitly overrides.

**Two anchoring bugs are fixed in `tools/corpus/score_degrees.py`; keep them.**
1. A unit's interval must not be applied to the note the martyria anchors.
2. `load_units` attaches a martyria to the unit BEFORE it — correct at a
   cadence, wrong at a hymn's opening, where it lands one unit outside the
   range. `leading_anchor()` fetches it. The chanter: "grave mode starts with
   the ga martyria so it should start on ga as the beginning pitch"; "the
   opening one is right aligned to the end of the last hymn" — it is printed
   with the previous hymn but names the NEW hymn's first pitch, so the first
   unit TAKES that degree rather than moving from it.

**The parallagi/melos pairing.** On a continuous tape every melos is
immediately preceded by its own parallagi (23/23 on gold). The pairing unit is
the RENDITION, not the hymn: one parallagi can cover the anavathmoi and both
prokeimena, with its melos following. It does NOT hold in the pre-split folders
(mode2-vespers 15/19, pl1-vespers 9/24, pl1-orthros 21/31) — those are real,
not detection errors.

**Measured boundary heuristics** (`docs/plans/BOUNDARY-HEURISTICS.md`):
drop-cap start 26/26 (hard), fade-into-last-second 47/47, martyria endcap
23/26, compound end 21/26, silence before start 46/47.

**The two halves of a pair can need different score ranges.** The doxology
melos stops where the 60-minute tape ran out; its parallagi runs to the end.
The range belongs to the SPAN, not the hymn.

---

## 4. The work

### Step 1 — piece generation from spans

Extend `tools/corpus/prep_hymn_annotator.py` (or add
`prep_span_annotator.py` beside it, reusing its strip rendering) to build an
annotator piece from a **span** rather than a `hymns.json` row.

Input per piece: one span from `cuts_<wd>.json` + its range from
`scorecuts_<wd>.json` + its name from `span_names_<wd>.json`.

- audio: cut `[t0, t1]` from the tape (tape path is in
  `texts/recut_<wd>.json[0].tape`). Honour `skips` by excluding them.
  Record `t_in` in the piece meta so the apichima is visible, not silently
  dropped.
- score strip: the existing renderer, over the span's score range
  (`p0/l0/g0 → p1/l1/g1`), not a `hymns.json` slice.
- notes: `load_units` over that range, same shape the annotator already reads
  (`cp, key, line, x0, x1, y0, y1`).
- `piece_id`: from `span_names_<wd>.json` (`grave-orthros-κατελυσαςτωσταυ-ρω-ωσουτον`,
  with `-parallagi` appended for the parallagi half).
- write `data/<piece-id>/` and add to `data/index.json` with `lane`, the
  ordinal, and the paired piece's id so the UI can offer "hear the other one".

**Acceptance:** 47 new pieces appear in the picker, 23 pairs plus the
unpaired first span; each parallagi and its melos carry the same incipit;
`grave-orthros-t03`'s existing gold piece is NOT clobbered.

### Step 2 — parallagi over the glyphs, in the main annotator

An endpoint already exists: `GET /api/parallagi?piece=<id>` in
`tools/chant-reel/annotator/serve.py` (`parallagi_for()`), returning
`{anchor, anchor_name, degrees, names, unknown}` **index-aligned with the
piece's own `notes` array** — align by index, never by coordinate, which is
how the first attempt ended up drawing nothing.

Verify: `curl 'http://127.0.0.1:8779/api/parallagi?piece=grave-orthros-t03'`
returns anchor 3 (γα) and 76 names.

Drawing was started in `index.html` (`PARA`, `loadParallagi`, and a block in
the ribbon draw loop) but is **not wired up**: `loadParallagi()` is never
called and there is no flags endpoint. Finish it:

- call `loadParallagi(pieceId)` wherever a piece is loaded
- small blue text above each glyph via `glyphRX(gi)`; flagged ones red
- a gold tick on units carrying a martyria (the checksum points)
- a toggle to hide it

**Acceptance:** opening `grave-orthros-t03` shows γα δι γα γα γα βου … above
the neumes.

### Step 3 — flagging

`POST /api/parallagi-flag {piece, gi, shown, note, clear}` →
`data/<piece-id>/parallagi_flags.json`, and `GET /api/parallagi-flags?piece=`
to read them back. A tap in flag mode toggles. Keep a timestamped history copy,
as the other endpoints do.

**Acceptance:** a flag survives a reload and shows red.

### Step 4 — retire the duplication

Once pieces come from spans, delete the score-picker's parallagi overlay
(`/score` in `tools/corpus/cutter/`) so there is one implementation. Keep the
cutter's boundary marking, drop-cap snapping and audio work — that is
tape-level and has no equivalent in the annotator.

---

## 5. Traps

- **`hymns.json` is wrong and must not be trusted as ground truth.** Scored
  against the gold tape: 4/25 right at IoU ≥ 0.90, median 0.56, and it
  over-splits — `t21/t22/t23` are one gold span, as are `t54/t55/t57`. Do not
  write span data back into it without the user asking.
- **Do not use file mtimes for ordering** the Plagal 1st folders; every file
  carries the same stamp. `presplit_map.py:order_key` parses the clock out of
  the filename.
- **`6|17ab` is unresolved.** The atlas says kentimata above an oligon is TWO
  notes (+1, +1); the pipeline emits one unit and the canon legend gives it +2
  as net displacement. The running degree stays right but one label is printed
  where two belong. Ask the user rather than guessing.
- **The cutter's output never touches `hymns.json`.** Keep it that way;
  adopting is a separate reviewable step.
- **Services:** `systemctl --user restart chant-annotator` (8779) and
  `chant-cutter` (8790). The lab proxy forwards
  `annotator.lab.alwaysdobetterllc.com` → 8779. Range requests must survive or
  seeking in a two-hour tape breaks — verify `206` with a correct
  `Content-Range` after any proxy change.

---

## 6. Not in scope

The overall goal — all 16 tapes cut and aligned — needs 12 more tapes cut by
ear and 3 pre-split ones given score ranges. That is the user's work and no
automation measured so far can substitute for it. This plan makes the hymns he
HAS verified usable, and makes the next tape faster.
