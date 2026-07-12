# RAGA-01: Raga Scale Presets And Sargam Labels

Status: in-progress (owner greenlit 2026-07-11). Priority: P2.

Dependencies: none hard. If the wasm bindings do not yet export the engine's
`Genus::Custom { name, intervals, canonical_root }`, a minimal wasm-bindgen
export in `src/lib.rs` is in scope (no tuning-engine semantic changes).
Blocks: `RAGA-02` (shared `web/app.js`/`web/index.html` edits) and `RAGA-03`.
Parallel-safe: no — sequential within this lane.

Owned files: `web/app.js`, `web/index.html`, `web/ui/scale_ladder.js`,
`web/ui/note_indicator.js`, any new raga preset/label module under `web/`,
optionally `src/lib.rs` (+ local wasm rebuild, artifacts stay untracked).

## Goal

Let a singer pick a raga the way they pick a Byzantine preset, and see the
ladder and note feedback in sargam names (Sa Re Ga Ma Pa Dha Ni), so an Indian
classical student can practice against the same pitch-detection HUD.

## Owner Decisions

- Naming is Hindustani-only (owner, 2026-07-11; the friend's tradition).
  Carnatic melakarta equivalents stay as code comments for reference.
- One tradition at a time (owner, 2026-07-11): an app-mode switch in the
  HEADER (mobile and desktop) selects Byzantine or Hindustani, replacing the
  earlier settings-panel label toggle. Hindustani mode forces sargam labels,
  shows only raga presets, retitles Reference Ni to Reference Sa, and hides
  Byzantine notation tools (pthora/chroa palettes, quick pthora, score
  practice, exercises and the Train tab pending RAGA-03) — Byzantine
  notation is meaningless to a Hindustani learner and vice versa. Byzantine
  mode is unchanged from today. Names never mix: Byzantine Ni is the tonic
  while sargam Ni is the 7th (Pa and Ga also collide).
- Hindustani mode carries a distinct warm accent so the modes read
  differently at a glance; deeper visual overhaul iterates on the
  field-test checkpoint.
- Initial intervals are 12-ET-snapped onto the 72-moria grid; Sa maps to the
  existing Reference Ni anchor.

## Starter Presets (moria steps from Sa, sum 72)

| Hindustani / Carnatic | Steps |
|---|---|
| Bilawal / Shankarabharanam | 12 12 6 12 12 12 6 |
| Yaman / Kalyani | 12 12 12 6 12 12 6 |
| Kafi / Kharaharapriya | 12 6 12 12 12 6 12 |
| Bhairavi / Hanumatodi | 6 12 12 12 6 12 12 |
| Bhairav / Mayamalavagowla | 6 18 6 12 6 18 6 |
| Todi / Shubhapantuvarali | 6 12 18 6 6 18 6 |

## Scope And Non-Goals

Presets, labels, and the toggle only. Non-goals: ascent/descent asymmetry
(vakra), gamaka/meend, shruti-true just-intonation variants (`RAGA-04`),
tanpura audio (`RAGA-02`), any training-prototype change.

## Steps

1. Verify the JS-reachable wasm surface for custom genera; add a minimal
   export if missing and record the signature here.
2. Define the six presets as data (intervals + dual names + sargam degree
   names), wired into the existing preset button/apply path.
3. Add the sargam label toggle and thread it through every degree-name render
   site (ladder, note indicator/HUD, ison and quick-pthora degree buttons,
   exercise text) behind one mapping function.
4. Persist the toggle with the existing preset/localStorage mechanism without
   breaking saved Byzantine presets.
5. ESLint + existing web/score tests + manual mobile (Sing/Scale/Train tabs)
   and desktop passes; screenshot evidence in the PR.

## Acceptance

Selecting a raga preset retunes the ladder to the declared moria; the sung-note
HUD snaps and scores against those degrees; sargam labels appear everywhere
degree names render and nowhere else when off; Byzantine presets, pthora
drag/drop, and saved presets behave exactly as before; CI green.

## Verification And Rollback

Verification: preset moria asserted against this table in a focused test where
the preset data lives; manual singer check. Rollback: revert the PR; presets
are additive data plus one toggle.
