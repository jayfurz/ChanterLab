# ChanterLab Program Orchestrator

Status: active. BASE-00 through CAT-03 completed 2026-07-10; `TRUST-01` schema
v1 was owner-approved and implemented 2026-07-11. Its first ledger-bearing
catalog release, `rel-20260711T155237Z-a3fdb875e54f`, was then promoted after
separate owner production approval. `TRUST-02` confidence instrumentation was
then completed and corpus-verified without a catalog promotion. `TRUST-03`
golden fixtures subsequently made the public/private evidence boundary
machine-verifiable. `TRUST-04` audit tooling and a release-bound private sample
are staged, but no human accuracy result has been claimed.

Objective: execute `docs/APP-ROADMAP-2026.md` as independently reviewable
workstreams while keeping the live practice app and catalog safe.

## Preflight

1. Read the roadmap, check-in protocol, and acceptance gates.
2. Record branch, HEAD SHA, dirty files, current catalog identity, and live
   service status without changing port `8765`.
3. Finish or isolate existing work before assigning overlapping files.
4. Mark the selected pickup plan `in-progress` and name its owner in the chat
   check-in. Do not edit status files merely to claim work.
5. Use a separate worktree for multi-day work or any plan that overlaps active
   changes.

## Dependency Spine

```text
BASE-00 -> BASE-01 -> BASE-02 -> CAT-01 -> CAT-02 -> CAT-03 [complete]
  -> TRUST-01 quality ledger [first ledger-bearing release promoted]
  -> LOOP-01 report capture/storage
  -> LOOP-02 reviewer/correction workbench
  -> LOOP-03 semantic diff/promotion

BASE-02 -> PRACTICE/AUDIO lanes
CAT-02 + TRUST-01 -> production/PWA lanes
TRUST + LOOP + RIGHTS -> uploads/director expansion
stable practice shell -> one-app convergence

SCALES-01 -> RAGA-01 -> RAGA-02 [owner-approved 2026-07-11; independent lane
  on legacy web/ + server routing files only — see 80-scales-and-raga/]
```

## Global Waves

### Wave 0: Protect The Baseline (Complete)

The reviewed parser sequence landed as `7be4d13`, `6815071`, and `e77ffa7`.
Treat `e77ffa7` as the content-system baseline until a later plan deliberately
changes it. Do not mix unplanned parser work into branch, CI, or release plans.

### Wave 1: Make Changes Reproducible (Complete)

Run branch/deploy consolidation, required CI, and the catalog-release contract.
Rights-policy clarification and transport characterization may run in parallel
only with disjoint files.

### Wave 2: Establish Content Trust

Atomic releases, the quality-ledger implementation, the first ledger-bearing
promotion, confidence instrumentation, and golden fixtures are complete.
Human-audit tooling is implemented under the approved ledger vocabulary; its
staged source comparisons still require human reviewers.

### Wave 3: Close The User Feedback Loop

Choose report storage, then implement capture, intake, reviewer workbench,
correction audit, and semantic release approval in order.

### Wave 4: Deepen Practice And Harden Production

Practice, scoring, audio, dependencies/security, and accessibility can proceed
in ownership lanes. Serialize plans that touch shared transport, scope, scoring,
library, loader, main, index, or style files.

### Wave 5: Converge And Expand

Define the common timed-score contract before UI convergence. Uploads, accounts,
director tools, raster OMR, and multipart assessment remain behind owner, rights,
privacy, and evidence gates.

## Shared-File Collision Map

- OMR lane: `vector_extract.py`, OMR tests, expectations; always serialize.
- Catalog lane: `ingest_catalog.py`, manifests/state/release tooling; serialize
  schema, promotion, trust, and diff changes.
- Practice lane: `js/transport.js`, `js/main.js`, `index.html`, `style.css`;
  serialize unless an orchestrator assigns exclusive submodules.
- Library loop: `js/library.js`, `js/model.js`, `js/loader.js`; provenance,
  reporting, and persistence require ordered integration.
- Audio/scoring: `scope.js`, `scoring.js`, calibration and detector tests require
  a frozen sample/timing contract before parallel work.
- Workflow/branch changes form one lane.
- Directory rename and root-doc graduation happen late and exclusively.

## Portfolio Completion Gate

The program is not complete until production app code and catalog releases are
reproducible, trust is visible, reports enter a review/correction loop, rollback
is proven, core practice/audio gates are green, rights controls are operational,
and residual research work is explicitly deferred rather than implied shipped.

## Completion Report

Report completed plan IDs, commits, release IDs, migrations, production smoke,
corpus deltas, private/device evidence, waivers, owner decisions, remaining
risks, and the next ready plans.
