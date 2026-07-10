# Production Platform Orchestrator

Status: staged behind required CI and catalog versioning.

Roadmap IDs: `PROD-01` through `PROD-05`.

Objective: make the app maintainable, secure, accessible, observable, and
offline-capable without destabilizing practice or content.

## Plans

| Order | Plan | Status |
|---|---|---|
| 1 | [`51-product-root-and-modules.md`](51-product-root-and-modules.md) | docs ready; rename blocked on owner |
| 2 | [`52-extractor-modularization.md`](52-extractor-modularization.md) | blocked on trust fixtures/signals |
| 1 | [`53-dependencies-build-security.md`](53-dependencies-build-security.md) | inventory ready after CI |
| 2 | [`54-accessibility-responsive-performance.md`](54-accessibility-responsive-performance.md) | ready after frontend gates |
| 3 | [`55-observability-and-pwa.md`](55-observability-and-pwa.md) | PWA blocked on asset/catalog versioning |

## Collision Rules

Directory renames are late, path-sensitive, and exclusive. Extractor refactor is
never concurrent with parser features. PWA work waits for immutable asset and
catalog identities. Analytics/telemetry requires explicit owner/privacy approval.

## Completion

Root documentation matches reality; high-risk modules have characterized seams;
dependencies/builds are reproducible; security/accessibility/performance gates
run; operational failures are visible without sensitive collection; offline
behavior cannot serve mixed catalog/app versions.

