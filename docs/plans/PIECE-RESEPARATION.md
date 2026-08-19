# Piece re-separation — the rebuild both halves of the goal now depend on

Working plan, 2026-08-19. Companion to `CHANT-MODEL-ACCURACY.md` and
`ONSET-MODEL.md`.

Goal being served: *align every sheet music score with the proper start and end,
and cut each audio track to exactly the right length, for all eight modes in
both Vespers and Orthros.*

---

## 1. Where the goal actually stands

| | session start | now |
|---|---|---|
| score slices starting exactly on a drop cap | 93/173 (54 %) | **110/173 (64 %)** |
| tracks force-aligned to canonical text | 0 | **173/173**, 14 workdirs, 8 modes, both services |
| audio tracks ending mid-sound ("clipped") | 126/157 (80 %) | **52/157 (33 %)** |
| onset accuracy vs the 76 chanter pins | 0.485 s (DTW) | **0.028 s** (forced alignment) |

Neither half is finished, and both are now blocked on the *same* thing.

## 2. The single shared blocker

**The piece files are wrongly segmented.** They were cut from hour-long tapes
before any of the current evidence existed, and the errors show up on both
sides:

- **A parallagi file is not one hymn.** One 179 s parallagi covers two melos
  tracks. Measured over the 55 hymns that have both, melos/parallagi length
  ratio is 1.55 with a 21.65 s median gap — while the chanter's rule
  ("paralagi then melos right after of the same hymn and length") is true in
  aggregate at median 1.02. The rule is right; the FILES are wrong.
- **That destroys the cutter's bound.** A hymn cannot run past the next recorded
  piece, which is the only principled right edge available — but the nearest
  usable neighbour today is the next *melos*, with a parallagi in between, so
  the bound permits tens of seconds where a real final-note decay is under a
  second. Every attempt to use it measured worse than not using it
  (33 % → 50 % → 53 % clipped).
- **It caps identification confidence.** Only 52 % of tracks reach ≤4.5/tok,
  partly because a track's audio does not correspond to exactly one hymn's text.
  Below that threshold no boundary may be moved, which is why score alignment
  stalls at 64 %.

## 3. What is now available that was not

The rebuild is worth doing *now* because three things exist that did not before:

1. **Canonical text for the whole Oktoechos** — 826 combined / 2 249 over-split
   entries incl. the Horologion ordinary (`glt_fetch.py`).
2. **CTC likelihood as an acoustic decision procedure** — it identifies which
   hymn a span of audio is, validated on t03 (correct 3.51/tok, wrong 4.99+).
3. **Envelope correlation that locates any audio inside its tape** at 0.90–1.00,
   so tape time and piece time are interchangeable (`audio_recut.py`).

## 4. The rebuild

**RESEP-01 (L) — segment the tape by text, not by silence.**
Slide the canonical texts of a mode's service along the tape and score each
placement by CTC likelihood, taking a monotonic best path over the whole tape.
This is the same order constraint used on the score side, applied to audio: each
hymn's end is pinned by the next hymn's start, so no arbitrary window edge is
involved and the melisma has nowhere to smear. Output: one span per hymn, plus
spans for parallagi (identifiable by their solfège syllable stream rather than
the text) and speech.
*Acceptance:* every span is bounded on both sides by another span; median
inter-span gap under 2 s; no span overlaps.

**RESEP-02 (M) — re-cut from those spans.**
Start = first aligned word − lead; end = last aligned word + decay, hard-bounded
by the next span. Because the bound is now the true neighbour, the extend-only
rule becomes safe.
*Acceptance:* clipped under 5 % corpus-wide, median tail 0.3–1.5 s (mode2 and
pl1-vespers, the two clean workdirs, sit at 1.57 s and 1.74 s).

**RESEP-03 (S) — re-pair parallagi to melos.**
With one span per hymn, the chanter's length rule becomes a *check* rather than
a guess: flag any pair outside ±15 %.
*Acceptance:* ≥90 % of pairs within ±15 %, against 20 % today.

**RESEP-04 (M) — re-run identification and boundaries.**
With one hymn per span, `loss_per_token` should fall broadly; re-run
`boundary_from_fa.py` with the same 4.5/tok gate.
*Acceptance:* ≥90 % of hymns at ≤4.5/tok; drop-cap starts ≥90 %.

## 5. Sequencing and gates

RESEP-01 gates everything. Do not re-cut audio or move boundaries until every
span is bounded on both sides — that property is precisely what all the failed
end-finders lacked.

Re-cutting changes the time base, so any hymn carrying pins must have them
shifted by its own start delta, recorded per hymn. Gold #2 (`t03`, 76 pins) and
gold #1 are frozen separately with their own audio checksums and are not
silently affected, but they must be re-frozen deliberately afterwards.

## 5b. Results, and the one diagnostic that explains what is left

Delivered (2026-08-19):

| | before | after |
|---|---|---|
| audio clipped, tracks cut at segment edges | 33 % (RMS) | **8 %** (10/127) |
| median tail | 0.17 s | **0.48 s** |
| workdirs at zero clipped | 1 | **6** |
| identification median | 4.48/tok | **3.85/tok** |
| identification clearing the 4.5 gate | 52 % | **83 %** (143/173) |
| score starts on a drop cap | 54 % | **69 %** (120/173) |

What is left is 46 tracks below the confidence gate, concentrated in mode3
(2/10), pl4 (2/4) and pl4-orthros (11/25). Two causes, and the second is the
real one:

1. **Editorial prose in the candidate pool.** The Horologion appendices contain
   rubrics that EXPLAIN the chant rather than being chanted — "Οἱ Καταβασίες
   εἶναι οἱ Εἱρμοὶ τοῦ πρώτου κανόνος", "Πῶς νὰ εὕρῃς τὰ λόγια τῶν Καταβασιῶν".
   They are modern Greek, so the function words identify them; `tape_solve.py`
   now filters them. This was mode3's visible symptom but not its cause —
   filtering barely moved the numbers.

2. **A FLAT score distribution means the segment is not one hymn.** For mode3's
   `kyrie-ekekraxa`, all eight cached options sit within 0.09/tok of each other
   (4.84–4.93) and none is the right text. When no text fits, the segment
   contains something other than a single hymn — a parallagi and melos merged, or
   several psalm verses. That is a SEGMENTATION failure surfacing as an
   identification failure, and the flat distribution is how to detect it
   automatically.

**RESEP-05 (M), the next step:** use score flatness as a segmentation signal.
Where a segment's best options are within a small margin of each other, re-cut
that segment with a lower silence threshold and re-score only it. The tape-level
threshold (0.8 s) is right on average — it recovers 56 segments against 59 known
pieces on grave orthros — but it cannot be right for every passage of every
tape, and flatness says exactly where it is wrong. The score cache makes this
cheap: only the offending segments need re-scoring.

## 6. Non-goals

- Further tuning of the RMS cutter. Four variants were measured; refinement
  without a correct bound does not help.
- Using whisper for anything but a corroborated bound — it misses 55 % of the
  sung audio here and emits 463 s over silence.
- Trusting the clipped metric alone as proof of "perfectly cut": it cannot
  distinguish a cut-off final note from a file that ends inside the next hymn.
