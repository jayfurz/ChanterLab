# ChanterLab — Agile Reset (July 2026)

Status: **approved by owner 2026-07-04, executed same day.** Decisions:
direction confirmed (training app is the product, Byzantine integrates in as
we go — distinct notation/font set, inheriting the Rust/WASM crown jewels);
tracker reset = full scorched earth (all 36 legacy issues closed as
overcome-by-events; still-valid ideas carried forward inside the new epics);
PDF exposure remediated (block PDFs + directory listings at the serving
layer, library stays public pending the licensing epic).
Prepared from a full audit of the tracker (36 issues, all filed 2026-05-04,
none ever closed) against the current state of the code (`choir-training`
@ 60b36fb, 1,491-piece ingested library, live at
byz.alwaysdobetterllc.com/training/ + chanterlab.com/training/).

---

## 1. Direction (the decision everything else hangs off)

**Recommendation: the training app is the product.** The May plan assumed a
Byzantine interval-drill curriculum (Grand Tour, course map, badges). What
actually shipped — and what has users' features — is a score-driven practice
tool: OMR-ingested liturgical library, per-voice practice, singscope, sections,
now fast loading. The old `web/` app keeps its two crown jewels (Rust/WASM
pitch detection + tuning engine, Byzantine neume support); those migrate INTO
the training app over time rather than the training app being ported into the
old shell (the roadmap's original Phase 1–2).

Consequences if confirmed:
- `docs/choir-training-roadmap.md` stays the vision doc; its Phase 1–2 is
  re-scoped from "integrate into main app" to "extract what main has that
  training needs" (detector, PSOLA, neume mode).
- `main` (the Pages-deployed Byzantine app) goes maintenance-only until its
  assets are absorbed.
- Branch strategy needs a decision: merge `choir-training` → `main`
  (Pages would then also publish the training app — no copyrighted content is
  committed, so this is safe), or flip the default branch. Local `main` is
  stale (5 ahead / 11 behind origin) and needs a reset to origin either way.
  Open PR #38 (Byzantine neume OCR) becomes part of the "neume mode" epic.

## 2. Issue triage (36 open issues)

**Close as obsolete (10)** — describe the abandoned drill-curriculum product.
Close with a comment linking this doc + roadmap:
#3 (EX-03b moria sequencer), #8 (AUD-05b step-through), #10 (EX-04 Grand Tour
library), #24 (EX-05 exercise JSON import/export), #25 (EX-06 adaptive
generator), #29 (CRS-01 course map), #30 (CRS-02 auto-unlock), #31 (CRS-03
daily plan), #32 (CRS-04 streaks), #33 (CRS-05 badges).

**Rewrite/retarget (8)** — still wanted, wrong framing (moria drills → score
practice; several are half-shipped in the prototype's singscope):
#5 (FB-06 live readout → cents for SATB / moria for chant; partially shipped),
#6 (VIS-04/05 tolerance bands → ±50¢ glow shipped, generalize),
#7 (TCH-02 persistence → + store imported/verified scores),
#13 (FB-04 score report → per-loop report on a chosen SATB line),
#14 (FB-05 pass/fail → per-note against the gold lane),
#17 (REC-02 ideal trace → gold target lane shipped; close-as-done or extend),
#21 (AUD-10 timbre → per-voice timbre),
#35 (DATA-01 stats → per-piece/per-voice trends, not per-interval).

**Keep as-is (18):** #2, #4, #9, #11, #12, #15, #16, #18, #19, #20, #22, #23,
#26, #27, #28, #34, #36, #37. Generic capabilities that apply to either
notation world. Highlights that gained relevance: #18 (range/auto-transpose),
#36 (offline/PWA), #37 (mic calibration — needed for choir bleed handling).

## 3. Milestones (replace the drill-curriculum set)

Retire: "Phase 1: Core Drills", "Phase 2: Interval Training",
"Phase 3: Course & Polish" (empty), "Post-Launch".

- **M1 — Hardening & Rights** (now): PDF/artifact exposure remediation
  (done 2026-07-04 if the in-flight fix verifies), licensing & attribution
  policy for the library (SOURCES.md terms → what may be public; composer
  attribution surfaced in the app), OMR review-queue triage (1,992 review
  items; Joseph-of-Damascus cluster extracts at 0% integrity), scrub the one
  committed copyrighted screenshot going forward.
- **M2 — Practice Depth**: per-note scoring + pass/fail + loop report
  (#13/#14 rewritten), verse-2 display toggle (data already in manifest),
  range/auto-transpose (#18), per-voice timbre (#21), on-target chime (#11),
  target-pitch replay (#4), mic calibration (#37).
- **M3 — One App**: WASM pitch detector + PSOLA into the training app
  (replaces JS autocorrelation), Byzantine neume mode (absorbs PR #38 +
  `.chant` engine), offline/PWA (#36), persistence (#7 rewritten).
- **M4 — Ops & Scale**: branch consolidation + default-branch decision, CI for
  training-prototype (headless Playwright smoke) + omr (pytest on
  vector_extract regression corpus), OMR correction UI (roadmap §3.4 residuals),
  section detection for small-header books (Hilko), rubric-word lyric
  residuals (~60 files), review-queue promotion workflow.

## 4. Labels to add

`area:omr`, `area:choir`, `area:library`, `area:licensing`, `area:infra`
(existing `audio:`/`viz:`/`feedback:`/`platform:`/`recording:` taxonomy stays).

## 5. New epics to file (seed issues)

1. **EPIC: Library rights & attribution** (M1) — decide + implement what is
   publicly served vs auth-gated; per-piece attribution in the UI; takedown
   path documented.
2. **EPIC: OMR quality loop** (M1/M4) — review-queue triage dashboard,
   correction UI for the §3.4 residual classes, integrity-gate tuning,
   Joseph-of-Damascus failure-mode fix, small-title section detection.
3. **EPIC: Practice scoring v1** (M2) — per-note hit detection on the gold
   lane → loop report → pass/fail thresholds; reuses exercise_mode patterns.
4. **EPIC: One app — detector & neume mode** (M3) — WASM detector swap,
   PSOLA, Byzantine notation as a second score type behind the same transport.
5. **EPIC: Productionize the training app** (M4) — modularize app.js (2k+
   lines), error handling, headless smoke suite in CI, PWA shell.

## 6. Proposed Sprint 1 (2 weeks)

1. Verify + document the exposure fix; write the licensing policy page (M1).
2. Verse-2 toggle in the singscope (small, high singer value; data ships).
3. Per-note hit detection spike on one piece (scoring v1 seed).
4. Joseph-of-Damascus extraction failure: diagnose the 0%-integrity cluster
   (biggest review-queue win; ~9 pieces).
5. CI: GitHub Action running the headless Playwright smoke (load Finley,
   sections, play) on pushes to `choir-training`.
6. Tracker reset execution (close/rewrite/create per §2–§5) once approved.

## 7. Execution checklist (owner chose scorched earth: close ALL 36)

- [ ] `gh issue close` ×36 with a reset comment; still-valid ideas are
      carried forward by "Carries forward: #N" lines in the new epic bodies
      (supersedes the §2 close-10/rewrite-8 split)
- [ ] Create labels (§4), milestones (§3), close old milestones
- [ ] File 5 epics + Sprint-1 issues, assign milestones
- [ ] Branch decision executed later under M4 (merge or default-branch flip +
      local main reset)
- [ ] PR #38 stays open; absorbed by the M3 "One App" epic

## 8. Sprint 1 retrospective (completed 2026-07-04)

All five issues shipped and closed in one orchestrated day (#47-#51):
verse toggle (a1d2749), scoring spike (41521b8), CI smoke (016f7e1,
green from run 1), licensing + attribution (9e9a8bc), and the
FinaleMaestro font fix (81bc3ba) which grew the accepted library
1,491 → 1,539 (+48 pieces, 9 Joseph-of-Damascus booklets at 100%).
Model tiering: opus on the two open-ended tasks (both paid off —
the font root-cause and the scoring-coverage design call), sonnet on
the three well-scoped ones (all first-pass clean).

Retro lesson: three of five tasks serialized on app.js — the monolith
is now the orchestration bottleneck. Addressed in Sprint 2's stretch.

## 9. Sprint 2 (filed 2026-07-04, label `sprint-2`)

Wave A (parallel): #53 OMR regression harness (pytest, locks the
byte-identical bar — prerequisite for risky OMR work) · #54
review-queue triage (find the next FinaleMaestro-scale systemic win
among 1,944 rejects) · #58 monophonic playback UX (play the melody by
default — tester-reported: Psalm 135 "shows notes but doesn't play";
first in the app.js queue, small + users actively confused) · #56
exposure canary + screenshot scrub.
Wave B: #52 residual Joseph failures (after #53) · #55 scoring v1
(per-lap scoring, on-screen report, strictness setting; after #58
frees app.js).
Wave C (stretch, after #55): #57 modularize app.js into native ES
modules so future sprints can parallelize app work.

Suggested tiers: opus for #52 and #54 (open-ended diagnosis), sonnet
for #53/#55/#56/#58, opus for #57 (large refactor, no-regression bar).

## 10. Sprint 3 (filed 2026-07-04, label `sprint-3`) — owner field-testing feedback

Sourced from the owner's first real practice session on the live site:
- #63 audio unlock — first Play is silent until the mic button is
  touched (root cause found: Tone.start() only fires in the mic
  handler; Play never unlocks the AudioContext)
- #64 landing experience — default piece becomes Trisagion 10A
  (10a_trisagion_hymn-hilko-t3_0) with fallback to the control fixture
  (which stays CI-only; it also truncates "have mercy on") + first-run
  onboarding (absorbs the coach-mark from #61)
- #65 sound engine: diagnose + fix popping/crackling (envelopes,
  master limiter, main-thread contention) — measured, not by-ear
- #66 sampled voices behind a toggle (licensing-clean set, ≤3 MB,
  synth stays the fallback) — after #65, same module
- #67 in-app practice recording (mic + accompaniment mixed via
  MediaStreamDestination) — solves the owner's UGC screen-recording
  mix problem and gives users a share feature
- #68 business model & market research memo — Orthodox beachhead →
  generic "upload your repertoire" choir market; competitive scan;
  pricing candidates; docs/BUSINESS-MODEL memo for owner decisions
- #59 (carried in) glyph-attachment tolerances — the ~40-70-piece
  SATB quick win; the OMR slot is free all sprint

Waves (post-#57 modules permitting): A: #63 + #64 (parallel: audio vs
library/main modules) + #68 research + #59 omr · B: #65 → #66 · C: #67.
Tiers: opus #65/#67/#68, sonnet #63/#64/#66/#59.

## 11. Sprint 2 retrospective (completed 2026-07-04)

All seven issues + one owner side-quest shipped in one orchestrated
day. Headline: **the accepted library more than doubled — 1,539 →
3,296 pieces** (#52: per-system integrity + evidence-only staff
grouping, gated behind #53's new 14-test regression harness), after
#54's triage proved 91% of the review queue was the SATB metric
mis-scoring chant, not extraction failure. The UX audit (#58) found
the monophonic-silence bug affected 82% of the library; wave-1 fixes
shipped same-day (melody-plays-by-default, audio/status desync,
mobile-collapsed transport, friendly errors). Scoring v1 (#55):
per-lap results, tappable worst-spots, strictness presets. #56:
exposure canary timer + screenshot scrub. #57: app.js split into nine
ES modules, zero behavior change, opening parallel-work seams.
Side-quest: full corpus archived to truenas (additive daily mirror).

Retro lessons: (1) triage-before-fix paid off enormously — #54
re-scoped #52 mid-flight from ~13 pieces to ~1,600; (2) the regression
harness let the riskiest OMR change of the project land with
confidence same-day; (3) owner field-testing (Sprint 3's source)
catches what headless audits cannot (audio unlock, sound quality,
recording workflows).

## 12. Sprint 3 retrospective (completed 2026-07-05)

All seven issues closed (+ #70 added mid-sprint) — every one sourced
from the owner's first real practice session. Audio-unlock guard +
Trisagion 10B landing + first-run onboarding (#63/#64, one combined
agent since they shared files); pops/crackles measured-and-fixed —
headroom limiter + doubled scheduler lookahead, envelope clicks ruled
OUT by data (#65); self-generated formant "Voices" instrument, 639KB,
CC0-risk-free because the CC0 libraries had no vocal samples (#66);
in-app mixed practice recording — the owner's UGC pipeline (#67);
glyph-attachment fix landed with an honest negative result — 1
crossing not 40-70, premise overturned by measurement, follow-up #69
filed for the real dual-stem refactor (#59); business-model memo
delivered, #68 left open for owner decisions; chanterlab.com now
serves the app at ROOT via host-aware origin routing (#70, owner
go-ahead mid-sprint). Catalog: 3,297 accepted.

Retro lessons: (1) owner field-testing generated the whole sprint —
institutionalize a "founder plays with it" session per sprint;
(2) the CI fresh-checkout gate caught a real staging omission
(state.js exports) that local verification structurally could not;
(3) measurement-before-fixing paid again twice (#65's ruled-out
envelope theory, #59's overturned premise) — cheaper than shipping
plausible-but-wrong fixes.
