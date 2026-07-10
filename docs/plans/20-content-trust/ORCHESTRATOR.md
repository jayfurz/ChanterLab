# Content Trust Orchestrator

Status: ready. `CAT-01` and `CAT-02` completed 2026-07-10.

Roadmap IDs: `TRUST-01` through `TRUST-05`.

Objective: make score confidence, provenance, verification, and residual risk
measurable and honest rather than inferred from measure integrity.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`21-quality-ledger-status.md`](21-quality-ledger-status.md) | ready |
| 2 | [`22-confidence-signals.md`](22-confidence-signals.md) | blocked on 21 |
| 2 | [`23-golden-corpus-fixtures.md`](23-golden-corpus-fixtures.md) | ready after required CI; parallel-safe with 22 under separate files |
| 3 | [`24-human-audit-review-clustering.md`](24-human-audit-review-clustering.md) | blocked on 21-23 |
| 4 | [`25-library-provenance-ui.md`](25-library-provenance-ui.md) | blocked on 21 schema and catalog IDs |

## Ownership

Serialize `vector_extract.py` and expectations changes. Schema work owns release
metadata; UI work owns library/current-piece display only after schema freeze.
Human audit may read private artifacts but must emit only approved summaries.

## Completion

A production score exposes immutable provenance and trust status; confidence is
multidimensional; known failure classes have semantic fixtures; private corpus
verification is distinguishable from public CI; and human sampling estimates
real accuracy by meaningful strata.
