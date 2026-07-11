# Content Trust Orchestrator

Status: `TRUST-01` schema v1 was owner-approved and implemented 2026-07-11.
After separate owner production approval, its first ledger-bearing catalog
release, `rel-20260711T155237Z-a3fdb875e54f`, was promoted the same day.

Roadmap IDs: `TRUST-01` through `TRUST-05`.

Objective: make score confidence, provenance, verification, and residual risk
measurable and honest rather than inferred from measure integrity.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`21-quality-ledger-status.md`](21-quality-ledger-status.md) | complete; schema v1 merged and first ledger-bearing release promoted |
| 2 | [`22-confidence-signals.md`](22-confidence-signals.md) | ready; schema v1 approved |
| 2 | [`23-golden-corpus-fixtures.md`](23-golden-corpus-fixtures.md) | ready; required CI complete; parallel-safe with 22 under separate files |
| 3 | [`24-human-audit-review-clustering.md`](24-human-audit-review-clustering.md) | blocked on 22-23 |
| 4 | [`25-library-provenance-ui.md`](25-library-provenance-ui.md) | ready; schema v1 and catalog IDs available |

## Ownership

Serialize `vector_extract.py` and expectations changes. Schema work owns release
metadata; UI work owns library/current-piece display only after schema freeze.
Human audit may read private artifacts but must emit only approved summaries.

## Completion

A production score exposes immutable provenance and trust status; confidence is
multidimensional; known failure classes have semantic fixtures; private corpus
verification is distinguishable from public CI; and human sampling estimates
real accuracy by meaningful strata.
