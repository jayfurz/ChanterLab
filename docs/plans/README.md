# ChanterLab Implementation Plans

Status: active planning index.

The canonical product roadmap is [`docs/APP-ROADMAP-2026.md`](../APP-ROADMAP-2026.md).
This directory turns that roadmap into bounded plans suitable for an
implementation agent. Historical roadmaps remain in place as evidence; do not
continue appending execution work to them.

## Start Here

1. Read [`ORCHESTRATOR.md`](ORCHESTRATOR.md).
2. Read [`00-agent-check-ins.md`](00-agent-check-ins.md).
3. Read [`00-acceptance-gates.md`](00-acceptance-gates.md).
4. Select one ready workstream orchestrator.
5. Execute one pickup plan at a time unless the orchestrator explicitly marks
   plans parallel-safe with disjoint file ownership.

## Workstreams

| Workstream | Objective | Entry gate |
|---|---|---|
| [`00-baseline`](00-baseline/ORCHESTRATOR.md) | Land current work, consolidate branches, require comprehensive CI | Current OMR changes reviewed |
| [`10-catalog-releases`](10-catalog-releases/ORCHESTRATOR.md) | Immutable catalog releases, promotion, rollback, backups, rights controls | Baseline commit known |
| [`20-content-trust`](20-content-trust/ORCHESTRATOR.md) | Quality ledger, confidence signals, golden corpus, human audit | Catalog identity contract frozen |
| [`30-feedback-loop`](30-feedback-loop/ORCHESTRATOR.md) | Singer reports, intake, reviewer workbench, corrections, semantic diffs | Trust IDs/statuses frozen |
| [`40-practice-audio`](40-practice-audio/ORCHESTRATOR.md) | Practice depth, scoring v2, persistence, audio/device reliability | Required CI green |
| [`50-production-platform`](50-production-platform/ORCHESTRATOR.md) | Architecture, dependencies, security, accessibility, PWA, observability | CI and catalog versioning stable |
| [`60-one-app`](60-one-app/ORCHESTRATOR.md) | Common timed-score contract and Byzantine/Western convergence | Practice shell stable |
| [`70-expansion`](70-expansion/ORCHESTRATOR.md) | Uploads, accounts, directors, raster OMR, multipart research | Rights and product gates approved |

## Status Values

- `ready`: dependencies satisfied and owner decisions recorded.
- `in-progress`: one agent owns the plan and its declared files.
- `blocked`: a named dependency or owner decision prevents safe progress.
- `done`: acceptance gates passed and handoff recorded.
- `deferred`: explicitly outside the current investment horizon.

Update status one plan at a time. Do not mark an entire orchestrator complete
because implementation exists; it must also meet its declared verification and
release gates.

## Global Rules

- Do not stop, restart, kill, or bind over the existing service on port `8765`.
- Do not use broad process-kill commands.
- Do not overwrite unrelated or concurrent work in a dirty tree.
- Use a separate worktree for long or overlapping efforts.
- Never commit copyrighted PDFs, derived private MusicXML, crops, tokens, or
  private screenshots.
- Parser fixes require focused semantic tests in the same commit.
- A re-blessed hash requires a written semantic explanation and source evidence.
- Accepted-count growth is not sufficient evidence of correctness.
- Do not introduce a backend, account system, analytics vendor, directory
  rename, branch switch, or public content policy without its owner gate.
- Do not promote generated content directly from an agent worktree.

## Required Pickup-Plan Shape

Every pickup plan declares goal, status, roadmap IDs, dependencies, blockers,
parallel-safety, owned files, owner decisions, scope, non-goals, constraints,
implementation steps, acceptance criteria, verification, rollback, deliverables,
and handoff. If reality invalidates a plan assumption, stop at the diagnosis
check-in and update the plan before broadening the implementation.

