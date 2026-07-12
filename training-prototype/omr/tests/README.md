# OMR engine regression suite

Locks the "byte-identical output on clean pieces" bar that every recent
`vector_extract.py` fix has been hand-validated against, ahead of the
staff-grouping / integrity-model work planned in issue #52. See
`test_regression.py`'s module docstring for the full rationale and
`docs/AGILE-RESET-2026-07.md` (issue #53) for the project context.

## Running

From `omr/` (not from `omr/tests/`):

```sh
.venv/bin/python -m pytest tests/
```

If `.venv` doesn't have `pytest` yet:

```sh
uv pip install --python .venv/bin/python pytest
```

(this is the same `uv pip install --python .venv/bin/python <pkg>` pattern
`README.md` already uses to install `pymupdf` into this venv.)

`test_release_descriptor.py` (CAT-01) and the release/restore tooling require
the declared schema-validation dependency:

```sh
uv pip install --python .venv/bin/python -r requirements-release.txt
```

**Local-only by design.** The corpus PDFs live in `omr/pdfs/ingest/`, which
is gitignored (copyrighted Antiochian Sacred Music Library material — see
`SOURCES.md`). Only per-piece sha256 hashes and stat numbers are committed,
in `tests/expectations.json` — never the extracted MusicXML or the source
PDFs. On any machine without the PDF checkout (CI included), every
regression test **skips** with a message naming the missing file; it never
fails or errors. Expect all-skip in CI, all-pass (or a real failure) on a
machine with the library checked out.

## Golden Fixture Registry

`golden_fixtures.json` is the machine-readable feature matrix. Every fixture
has a stable ID, a reason for existing, and explicit engraving/failure
features. Public cases identify the exact semantic test that exercises them.
Private cases contain only a corpus-relative basename and source sha256; they
never contain the PDF, extracted MusicXML, or an absolute local path.

The registry test fails when a required feature is uncovered, when a private
piece drifts away from `expectations.json`, or when an available private PDF
does not match its recorded source hash. All high-risk features feasible with
constructed models run publicly. Mid-piece layout switching remains explicitly
private-only because validating the glyph-to-system decision requires a real
engraved input; three independent private pieces cover it.

The public suite also creates blank and prose-only PDFs in `tmp_path` and
requires the pipeline to refuse them with no emitted score or report. No
generated binary is committed.

## What's covered

`test_regression.py` re-extracts each corpus piece with the current engine
(via `pipeline.py`, subprocess, exactly like production's
`ingest_catalog.py` invokes it) into a pytest tmp dir, then compares:

- **sha256** of the emitted `.musicxml` — catches *any* byte change.
- **Stats** pulled from the confidence report: `measures`, `sections`
  (count), `lyric_verses`, `whole_measure_rests_resized`, `integrity_pct`
  (`measure_integrity_pct` in the report), `voices`, `note_events_per_voice`
  (+ its total), `warnings_count`, `exit_code`.

If the hash changes, the failure message says whether any tracked stat also
moved (and which, old vs. new) — so a legitimate engine change still has to
explain itself, and a pure-formatting change (hash moves, no stat moves) is
visibly distinguished from a substantive one.

Two extra checks:

- **`test_determinism`** — extracts `trisagion_satb` and
  `finley_complete_liturgy` twice each, under different `PYTHONHASHSEED`
  values, and asserts byte-identical output. Guards against a future change
  (e.g. issue #52's staff-grouping rework) accidentally introducing
  hash-order-dependent set/dict iteration into the emitted XML.
- **`test_whole_measure_rest_shrink_hilko_star`** /
  **`test_whole_measure_rest_grow_theophany`** — pin the exact per-measure
  beat math for the two whole-measure-rest normalization corner cases
  (shrink: `hilko_star_antiphon` measures 46/48 = 3.0 beats; grow:
  `theophany_series1` measure 28 = 14.0 beats, measure 30 = 14.25 beats),
  independent of the aggregate `whole_measure_rests_resized` count.

## The corpus

11 pieces in `expectations.json["pieces"]`, picked to cover the failure
modes recent fixes touched:

| id | piece | why it's here |
|---|---|---|
| `trisagion_satb` | 01_trisagion_lozowchuk_satb.pdf | small clean 4-staff SATB, the original bake-off reference |
| `finley_complete_liturgy` | Complete-Liturgy-FrJohnFinley-choral.pdf | large, multi-section (22), multi-verse lyrics |
| `hilko_star_antiphon` | 04c1-2_refrain-trop_of_the_second_antiphon-hilko-star.pdf | shared-staff T+B whole-measure-rest **shrink** (m46/48 = 3.0 beats) |
| `joseph_damascus_first_kathisma` | 11-Joseph-Damascus-First_Kathisma-WNBN.pdf | genuine `FinaleMaestro` SMuFL font, revived by commit 81bc3ba, 100% integrity |
| `theophany_series1` | theophany_series1.pdf | whole-measure-rest **grow** case (14-beat / 14.25-beat bars); messy piece, exit 2 by design — that's the trusted current state |
| `holwey_divine_liturgy` | holwey_divine_liturgy-complete4a.pdf | large liturgy, 20 sections, 581 measures |
| `cherubic_2staff_reduction` | 02_cherubichymn_lozowchuk_adapted_satb.pdf | the documented 2-staff choral-reduction case (roadmap "tie-breaker" section), mid-piece 2↔4-staff switch |
| `finley_little_litany_legacy_maestro` | 03f_little_litany-finley.pdf | true legacy TrueType `Maestro` font (Sonata map), substituted for the Joseph 01-08 set (see below) |
| `receive_ye_tikey_zes` | receive_ye-tikey_zes.pdf | genuine agreeing 4/4 whole rests (no resize needed — the third variant alongside shrink/grow) |
| `finley_entrance_hymn_multiverse` | 07f_entrance_hymn-finley.pdf | multi-verse standalone piece, exercises the verse-toggle data path |
| `bortniansky_cherubic_7` | 13c_cherubic_hymn-bortniansky-7.pdf | chord-dot normalization, upper-voice divisi, and above-staff lyrics |

**Substitution note:** the issue brief suggested "one of the Joseph 01-08
set that's stable" as a legacy-Maestro example. As of this suite's
creation none of those 8 pieces extract above 20% integrity (all exit 2 —
the known shared-staff voice-beat-reconciliation frontier, tracked by
issue #52). `finley_little_litany_legacy_maestro` was used instead; see
`joseph_01_08_review_pile` in `expectations.json` for the detail, and
revisit once #52 lands.

## Determinism finding

Verified by hand during this suite's creation (and now enforced by
`test_determinism`): extracting the same PDF twice — including across
different `PYTHONHASHSEED` values — produces **byte-identical** MusicXML
and confidence-report JSON. The engine avoids timestamps and any
hash-seed-dependent ordering. Straight sha256 comparison is trustworthy;
no canonicalization needed. If `test_determinism` ever starts failing,
switch the comparison to a canonicalized form (e.g. re-serialize through
an XML canonicalizer before hashing) instead of raw bytes, and say so in
the commit message — don't just widen the tolerance.

## Re-blessing expectations

**No engine change (`vector_extract.py`, `pipeline.py`,
`legacy_glyph_map.json`, ...) lands without either green tests here or a
re-bless justified in the commit message.**

To re-bless after a deliberate, reviewed change:

```sh
UPDATE_EXPECTATIONS=1 .venv/bin/python -m pytest tests/
# or
.venv/bin/python -m pytest tests/ --bless
```

This re-extracts every piece whose PDF is present and overwrites its
`sha256`/`stats` entry in `expectations.json` with the current engine's
output (hand-written fields like `notes` are preserved). It does **not**
touch pieces whose PDF is missing locally. Review the resulting `git diff`
of `expectations.json` before committing — it should read as: which
piece(s), which stat(s) moved, and why (tie the "why" to the commit
message of the engine change that caused it). The two whole-measure-rest
spot-check tests are NOT blessable (they assert hardcoded, hand-verified
beat counts) — if a deliberate change legitimately alters that math, update
the hardcoded expected values in `test_regression.py` directly and explain
why in the same commit.

To re-bless one piece only: `-k <piece_id>` narrows to a single
parametrized case, e.g.:

```sh
UPDATE_EXPECTATIONS=1 .venv/bin/python -m pytest tests/ -k trisagion_satb
```

`--bless` changes only the private byte/stat expectations. It cannot update or
bypass `test_golden_fixtures.py` or the dedicated semantic assertions in
`test_regression.py` and `test_fixes.py`. A re-bless is incomplete until those
assertions pass and the reviewed change explains the semantic difference.

## Turning A Defect Into A Fixture

1. Record the source basename and sha256 locally; never add the protected PDF.
2. Reduce the defect to the smallest rights-safe constructed-model assertion
   possible. Add a generated PDF only when the PDF boundary itself matters.
3. Add the real piece to `golden_fixtures.json` and `expectations.json` when it
   supplies layout/font evidence that cannot be represented honestly in a
   synthetic model. State exactly why the piece exists and tag its features.
4. Make the semantic assertion fail on the old parser and pass on the fix.
5. Run both modes: the public-style checkout must pass with exact declared
   skips, and the private checkout must validate every source hash and test.
6. Review semantic output first. Re-bless a byte hash only after the behavior
   change is understood and documented.

## Runtime

The full 11-piece corpus extracts in a few seconds (each piece is
0.1-6s of `pipeline.py` CPU time); the whole suite including pytest
startup and the two doubled-up determinism extractions runs in a few
seconds, comfortably under the ~2 minute budget.
