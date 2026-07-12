# SCALES-01: Legacy Scales App At /scales/ On Brand Hosts

Status: in-progress (owner approved option A, 2026-07-11). Priority: P2.

Dependencies: none — both apps already ship in the production image. Blocks:
nothing; gives `ONEAPP-02` its preserved legacy route. Parallel-safe: yes
(server routing lane only).

Owned files: `server/byzorgan-web-server.py`, new routing tests in
`training-prototype/omr/tests/` (precedent: the server allowlist unit test
already lives in that CI-run suite), this plan.

## Goal

Make the legacy Byzantine scales app reachable at `chanterlab.com/scales/`
(and www) while leaving every existing route on every host byte-identical.

## Owner Decisions

Option A (path mount) chosen over B (subdomain) and C (wait for ONEAPP-02).
Whether `byz.alwaysdobetterllc.com` keeps serving the legacy app publicly is
explicitly NOT decided here; its behavior must not change.

## Scope And Non-Goals

Routing only. No `web/` UI changes, no ingress/DNS changes, no redirect from
the byz host, no PWA/manifest work.

## Steps

1. In `translate_path`, on root hosts only: map `/scales` and `/scales/*` to
   the legacy webroot (strip the prefix, skip the `/training` rewrite).
2. Confirm the OMR deny-by-default check still evaluates the post-rewrite
   filesystem path, so `/scales/training/omr/**` is filtered identically to
   `/training/omr/**`.
3. Audit `web/` for absolute-path asset references (`/pkg/...`, `fetch('/...')`)
   that would break under a non-root mount; fix to relative if any exist.
4. Add routing tests: real `ThreadingHTTPServer` on an ephemeral port with a
   temp webroot, asserting the host×path matrix below.
5. Smoke locally against the real webroot with a `Host: chanterlab.com` header.

## Acceptance

- `Host: chanterlab.com`: `/` serves the training app; `/scales/` serves the
  legacy index; `/scales` 301s to `/scales/`; `/scales/style.css` resolves to
  `web/style.css`; `/scales/training/omr/pdfs/**` 404s;
  `/training/*` still 301-strips; no `Location` header ever leaks an internal
  prefix.
- `Host: localhost` (and any non-brand host): behavior byte-identical to
  before, `/scales/` 404s (feature is brand-host-only).
- Cache-control classes unchanged (`.js`/`.css`/`.html` under `/scales/` get
  `no-cache` via the existing extension rule).
- Existing server tests and the unified required CI stay green.

## Verification And Rollback

Verification: new pytest cases + manual curl matrix recorded in the PR.
Rollback: revert the single server commit; the route is purely additive.
