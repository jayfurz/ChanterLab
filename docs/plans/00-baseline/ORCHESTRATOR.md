# Baseline Orchestrator

Status: ready.

Roadmap IDs: `BASE-00` through `BASE-02`.

Objective: establish a committed, deployable, comprehensively tested baseline
before catalog, trust, feedback, or practice work expands.

## Plans

| Order | Plan | Status | Blocks |
|---|---|---|---|
| 1 | [`00-land-current-omr-fixes.md`](00-land-current-omr-fixes.md) | done at `e77ffa7` | all OMR/catalog work |
| 2 | [`01-branch-and-deployment.md`](01-branch-and-deployment.md) | decided 2026-07-09; in-progress (worktree `base01-reconcile`) | required CI and releases |
| 3 | [`02-unified-required-ci.md`](02-unified-required-ci.md) | blocked on plan 01 | all later implementation |

## Ownership

Plan 00 is complete. Plans 01 and 02 own Git branch/deployment documentation and
`.github/workflows/`. Do not combine parser work with workflow or branch changes.

## Wave Gate

Parser-fix evidence was recorded with commits `7be4d13`, `6815071`, and
`e77ffa7`. Owner decision recorded 2026-07-09: reconcile `origin/choir-training`
into `origin/main` (merge commit, `main` stays canonical default), and add an
explicit minimal promote/release step (worktree checkouts + atomic symlink
swap) replacing the live-working-tree deploy model. See plan 01 for the full
decision record, sequence, and the catalog-data plumbing risk it must not
regress. Required CI must pass on the reconciled `main` before promotion.

## Completion

The baseline is complete when a clean checkout of the shipped branch runs all
public gates, the private corpus gate has a documented runner, and production
deployment consumes code from the same branch/commit family.
