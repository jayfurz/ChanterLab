# BASE-01: Consolidate Branch And Deployment

Status: complete 2026-07-10. Priority: P0.

Dependencies: `BASE-00`. Blocks: `BASE-02`, catalog releases, directory rename.

Owned files: branch policy documentation, deployment workflows/configuration,
`.github/workflows/`, a new release/promote script, `byzorgan-web-server.py`
(WEBROOT wiring only).

## Owner Decision (recorded 2026-07-09)

**Branch:** Reconcile, don't switch. `origin/main` (11 unique commits: CI,
clippy/rustfmt, ESLint, proptest, DSP cleanup) and `origin/choir-training` (98
unique commits: the choir app, OMR system, audio work, recent fixes) diverged
from a common ancestor `1410e2e6`. Merge `choir-training` into `main` with a
merge commit (never rebase/rewrite choir-training's published history), keep
`main` as the canonical default branch, and archive `choir-training` read-only.

**Done 2026-07-10.** Reconciliation merged via
[PR #91](https://github.com/jayfurz/ChanterLab/pull/91) (`5696a2d` on `main`),
full suite green both in the reconciliation worktree and on the real post-merge
CI run (Rust, JS, 36/36 OMR corpus, Playwright smoke, Pages `web/training`
exclusion verified live at the deployed Pages URL). `choir-training` is now
GitHub-branch-protected with `lock_branch: true` (verified: a push attempt was
rejected with "Cannot change this locked branch") — permanently recoverable,
not deletable, not pushable. Freeze tags
(`freeze/main-pre-reconcile`, `freeze/choir-training-pre-reconcile`) remain.

Owner archived `choir-training` ahead of the original "after production
verification" sequencing above. This is safe: locking only affects the
GitHub-hosted ref, not beast's local filesystem checkout, which keeps serving
chanterlab.com from choir-training exactly as before, untouched. One
consequence worth remembering: any urgent hotfix to what's *currently* live
on beast can no longer be pushed to `choir-training` — target `main` (which
now contains everything choir-training had) and pull that onto beast instead,
or temporarily unlock the branch if a same-branch hotfix is truly needed
before the production cutover (BASE-01 deployment sub-plan / VPS migration)
lands.

A legacy-syntax `git merge-tree` dry run initially looked conflict-free; a
Codex review (`gpt-5.6-sol`, 2026-07-10) that actually checked out the merge in
the reconciliation worktree found that was wrong. **Corrected finding:**
- `.gitignore` is a real textual conflict — both branches edited the same base
  line. `main` turns the no-trailing-newline `.claude` line into a
  newline-terminated `.claude` (plus adds `/web/pkg`, `/web/pkg-worklet`
  earlier in the file); `choir-training` replaces that same line with
  `.claude.scratch/` and `.scratch/`. Resolve as a deliberate union: keep
  `.claude`, `.claude.scratch/`, `.scratch/`, `/web/pkg`, `/web/pkg-worklet`.
- `web/audio/voice_worklet.js` was changed on **both** branches (main:
  edge-neighbor velocity fix; choir-training: reference-repitch playback). Git
  can combine them textually without conflict markers, but that does not prove
  both behaviors survive — inspect the merged file against both parent diffs
  and run tests covering both changes before trusting it.
- `.github/workflows/`: main has `pages.yml` (legacy Byzantine engine ->
  GitHub Pages, unrelated site to chanterlab.com); choir-training adds
  `training-smoke.yml`. Both must coexist. `training-smoke.yml`'s triggers
  only cover `choir-training` today — after reconciliation it must also run on
  `main` (push + PR), or `main` loses its only training-app CI coverage.
  `pages.yml`'s artifact must explicitly exclude `web/training` (see owner
  decision below) rather than relying on documentation alone, since `web/`
  after the merge contains the `training` symlink and Pages otherwise builds
  from `web/` on every push to `main`.
- `Makefile`: main added `test`/`lint`/`check` targets that only cover the
  Rust/WASM engine + root JS lint. They do not cover the OMR Python pipeline
  or training-prototype JS. Note the gap prominently (contributors will
  otherwise reasonably mistake `make check` for complete validation); closing
  it is BASE-02 scope.
- `README.md`, `docs/ARCHITECTURE.md`: unchanged on choir-training since the
  merge-base, so no git conflict, but both need real edits after the merge to
  stop describing only the legacy engine (semantic reconciliation, not a git
  operation).
- OMR's 36-test suite skips corpus-dependent cases when private PDFs are
  absent. Report exact collected/passed/failed/skipped/error counts from the
  reconciliation worktree, not a bare "pytest passed."
- "Required CI on the exact promoted SHA" needs enforcement after merge: a
  PR's test-merge SHA can differ from the actual resulting `main` SHA: wait
  for required checks on the commit `main` actually points to post-merge
  before promoting it.

Sequence: tag both frozen heads (done) -> reconciliation branch off
`origin/main` (done, worktree `base01-reconcile`) -> merge `origin/choir-training`
(merge commit) -> resolve `.gitignore` as the union above -> verify
`voice_worklet.js` -> deliberate edits to the files above -> full suite (Rust,
build, lint, scoring, detector, browser, all 36 OMR tests, exact counts) ->
reviewed PR into `main` -> wait for required CI on the actual post-merge `main`
SHA -> promote via the new release process below -> archive `choir-training`
(tag + branch protection, not deletion).

**Deployment — SUPERSEDED 2026-07-10, target moved to the VPS.** The live
`byzorgan-web.service` (systemd user unit on beast, `Restart=always`) serves
`/mnt/data/code/byzorgan-web/web` directly off this working tree's live disk
state — edits are public before commit or CI. The original plan (below, kept
for record) was a minimal beast-local promote script: worktree checkouts,
clean release directories, atomic symlink swap. Codex reviewed that design
(2026-07-10, `gpt-5.6-sol`) and it is sound, but the owner then decided to
move the *entire* serving stack off beast onto the existing `tenants-vps`
Hetzner VPS (`adb-prod-1`), not just the catalog data — replacing the beast
systemd unit rather than fronting it. Investigation findings grounding the new
plan:

- `infra/tenants/byzorgan/values.yaml` already models today's setup as an
  Argo-managed "external bridge" tenant (`site.enabled: false`,
  `services: [{mode: external, port: 8765, external: {ip: 192.168.50.166},
  hosts: [byz.alwaysdobetterllc.com, chanterlab.com, www.chanterlab.com]}]`),
  rendered by the `tenants` ApplicationSet onto the in-cluster (beast-k8s)
  destination — with a comment already anticipating this exact move:
  "containerize in phase 3 (it has a Makefile build — image mode candidate)."
- `tenants-vps/*` is a separate ApplicationSet targeting a different cluster
  destination (`name: vps`) — the remote Hetzner box. Adding
  `tenants-vps/byzorgan/values.yaml` (mirroring the `theodigital`/`freshair`
  container-mode pattern: image + `pvc: {mountPath, size}` + `hosts:`) is the
  standard, already-proven way every other tenant gets onto the VPS.
- **DNS cutover is pure and trivial**: `platform/cloudflared/tunnel-ingress.yaml`
  is a single catch-all rule per tunnel ("every hostname whose CNAME points at
  this tunnel is handed to ingress-nginx... cutovers are pure DNS"). Moving
  `chanterlab.com`/`www`/`byz.alwaysdobetterllc.com` from the `beast-k8s`
  tunnel to the `vps-prod` tunnel (id `7f0c3793-4a9e-42d9-9bdf-79cc95400491`)
  is a Cloudflare DNS change, not a cluster change, and is instantly
  reversible by pointing the CNAME back.
- This also resolves the earlier "build artifact" owner decision more
  idiomatically than a manual checksum-fetch step would have: a container
  image built and pushed by CI, referenced by digest, *is* the
  checksum-verified artifact. "Promote" becomes the same GitOps pattern every
  other tenant already uses — bump the image tag in
  `tenants-vps/byzorgan/values.yaml`, commit, push; ArgoCD (`selfHeal: true`)
  converges. Rollback = revert that commit (or `argocd app rollback`). No
  bespoke symlink-swap script is needed at all.
- **Rights boundary, unchanged by this move**: `training-prototype/omr/SOURCES.md`
  confirms the catalog paths already publicly served today
  (`omr/out/ingest/*.musicxml`, `manifest.json`, the 4 gitignored
  `content/*.musicxml` pieces) are "used with permission" content the app is
  meant to serve — moving them to a VPS-backed PVC changes *where* the same
  already-public bytes live, not *what* is exposed. The raw source material
  never served today (`omr/pdfs/`, `omr/pages/`, `omr/gt_crops/`, `omr/shots/`)
  must not be part of that PVC or migration — only the allowlisted subtree the
  server already exposes. The OMR extraction pipeline itself (touches the
  private PDF corpus) keeps running wherever it runs today; only its finished,
  already-public output is synced to the VPS, matching the existing
  `deploy_site.sh`/`backup.sh` pattern of "content is rebuildable, mirror only
  the served output."

**Canary deployed and verified live, 2026-07-10.** All of the "remaining
before implementation" items below are done. Summary, fullest detail in PR
history:

- Container image: [ChanterLab#92](https://github.com/jayfurz/ChanterLab/pull/92)
  (build), [#93](https://github.com/jayfurz/ChanterLab/pull/93) (Tailscale
  registry access — the registry's real hostname is Tailscale-only, the
  public mirror is SSO-gated with no bypass), [#94](https://github.com/jayfurz/ChanterLab/pull/94)
  (fixed the 4 gitignored content built-ins: baking them into the image only
  worked on a local build with those files already on disk — GitHub Actions'
  checkout never has gitignored files — fixed via PVC-backed symlinks
  instead, mounted at a neutral `/srv/chanterlab/data`, not directly at
  `training-prototype/omr/out`).
- Kubernetes/GitOps: [infra#1](https://git.lab.alwaysdobetterllc.com/jfursov/infra/pulls/1)
  and [infra#2](https://git.lab.alwaysdobetterllc.com/jfursov/infra/pulls/2)
  (`tenants-vps/byzorgan/values.yaml` + `scripts/publish_chanterlab_catalog.sh`,
  matching each image fix). `tenant-byzorgan` namespace, PVC, Deployment,
  Service, and Ingress are live on the VPS cluster.
- `gitea-pull` image-pull secret created in `tenant-byzorgan` — not strictly
  required (the registry allows anonymous reads) but wired correctly.
- Catalog published: `scripts/publish_chanterlab_catalog.sh` ran for real
  against the live PVC — 3,351 manifest-referenced `.musicxml` files + all 4
  approved content built-ins, atomically promoted.
- DNS: `chanterlab-vps-canary.alwaysdobetterllc.com` cut over via
  `scripts/cutover.py` (to the `vps-prod` tunnel), health-checked
  automatically by the script itself.
- Verified end-to-end through the real public canary URL over HTTPS: legacy
  app at `/`, training app at `/training/`, catalog manifest and all 5
  built-ins 200, OMR denylist paths still 404.
- One CI gap found and worked around, not yet fixed: the
  `tailscale/github-action` step in `container-image.yml` succeeded once
  (workflow_dispatch test) then failed identically on every retry — signature
  of a single-use rather than reusable Tailscale auth key. Worked around by
  building and pushing the image directly from beast (which already has
  tailnet + registry access) instead of blocking on a new key. **Owner
  follow-up needed:** recreate `TAILSCALE_AUTHKEY` in the Tailscale admin
  console with "Reusable" explicitly enabled, or CI will keep failing on
  every subsequent push to `main`.
- **Fixed 2026-07-10, same day:** `TAILSCALE_AUTHKEY` recreated as a genuinely
  reusable key and confirmed by running the workflow twice back-to-back —
  CI no longer needs the manual beast-push workaround.

**All three real production hostnames cut over 2026-07-10 and verified
stable.** `chanterlab.com`, `www.chanterlab.com`, and
`byz.alwaysdobetterllc.com` all serve from the VPS now, each re-verified
directly against the pod (explicit `Host` header, covering root, catalog
manifest, all 5 built-ins, the `/training` redirect or prefix as
appropriate, and denied OMR paths) before DNS was touched, then re-verified
over the real public HTTPS path across multiple passes after.

One real incident along the way, worth recording plainly: the first
`chanterlab.com` cutover attempt hit a 404 for roughly a minute — the
Ingress had never actually listed `chanterlab.com` in its `hosts`, only the
canary hostname, so ingress-nginx had no matching rule. Root cause: the
canary hostname never exercises `byzorgan-web-server.py`'s `ROOT_HOSTS`
root-mounting behavior that `chanterlab.com` specifically needs, so that
code path went genuinely untested before real traffic hit it — a real gap
in pre-cutover verification, not something caught in advance. Rolled back to
beast via `scripts/cutover.py --rollback` within about a minute; this
doubles as the rollback proof BASE-01 originally asked for, proven for real
rather than only staged. Fixed by adding the hostname to the Ingress and,
this time, verifying the exact `Host`-header behavior directly against the
pod before any further DNS changes — the discipline the first attempt
skipped.

Beast's systemd unit is untouched and still running as an instant fallback
target (`scripts/cutover.py <host> --rollback`). Decommissioning it and
archiving `choir-training`'s remaining live role are deliberate follow-on
owner decisions, not done as part of this cutover.

**Independently re-verified 2026-07-10** (separate session, fresh checkout,
no reliance on the above record): `origin/main` at `9c37da8` matches PRs
#91-94; the VPS deployment's live image tag is the exact `9c37da8...` digest;
`tenant-byzorgan/byzorgan-web` is 1/1 with zero restarts and its PVC is
`Bound`; all three hostnames (`chanterlab.com`, `www.chanterlab.com`,
`byz.alwaysdobetterllc.com`) return `200`; the `beast` kubectl context still
resolves as a rollback target. BASE-01 is complete at the promoted level.

<details>
<summary>Original beast-local design (superseded, kept for record — Codex-reviewed and sound if the VPS move is ever reversed)</summary>

1. Agents work only in separate worktrees; nothing lands in the tree that
   backs production by direct edit.
2. Required CI must pass on the exact SHA being promoted (the actual
   post-merge SHA, not a PR test-merge SHA).
3. CI builds and publishes the WASM artifacts (`web/pkg`, `web/pkg-worklet`,
   and whatever produces `training-prototype/pkg-worklet`) with checksums; the
   promote script fetches and verifies them for the approved SHA.
4. A deploy script materializes a clean, detached checkout of the approved SHA
   into a new release directory (e.g. `/mnt/data/code/releases/<sha>/`), then
   lays the fetched/verified build artifacts into it.
5. Every release directory symlinks `training-prototype/omr/out` and the 4
   gitignored `content/*.musicxml` files back to one stable, persistent
   location (`byzorgan-web-server.py`'s allowlist resolves paths lexically —
   `abspath`/`relpath`, not `realpath` — so a symlinked subtree does not
   escape the OMR allowlist check).
6. Smoke-test the release directory (not the live symlink) before cutover, on
   an explicit host/port the smoke test controls.
7. Atomically retarget a `current` symlink using `rename(2)` semantics (temp
   symlink in the same directory, then rename over `current`), serialized with
   a lock; `WEBROOT`/bind/port become configurable.
8. Record the deployed SHA; retain `current` + previous + a bounded window;
   never delete a directory a deployment record still references.
9. Rollback = retarget `current` to the previous release directory; no
   rebuild, no re-checkout, no `git checkout` in a live tree.

</details>

**Owner decision — Pages boundary:** `pages.yml`'s artifact must explicitly
exclude `web/training` (build from a staging directory that omits it, and fail
the workflow if the training app leaks in) rather than relying on
documentation to keep the legacy Pages site product-free.

No CD system, queue, or automation beyond a manual, audited promote command is
needed yet. Code deployment stays a separate operation from `CAT-02` catalog
promotion — this plan only makes sure code promotion doesn't silently orphan
the catalog data that already lives outside git.

## Steps

1. Inventory branch protection, workflow triggers, symlinks, service deployment,
   and rollback behavior. (Done — see decision record above.)
2. ~~Present the smallest safe branch/deploy options and migration risk.~~ Done;
   owner chose reconciliation + explicit minimal release over the smallest-safe
   default proposed initially.
3. ~~Record the owner's decision before edits.~~ Done, this section.
4. Execute the reconciliation merge and the release-script/service changes in
   a dedicated worktree; update workflow triggers and deployment documentation.
5. Verify a candidate commit reaches a release directory and rollback returns
   to the prior release directory without touching catalog data or the git
   working tree.

## Constraints

Do not force-push, delete branches, or alter the live service without a tested
staging proof first. Do not bind over port `8765`. Do not rewrite
`choir-training`'s published history (merge, never rebase). Do not let the
release script's clean-checkout step drop the untracked catalog data.

## Acceptance

- One canonical branch (`main`, post-reconciliation) and release source are
  documented.
- Every required check runs before the deploy gate.
- Code deploy and catalog promotion remain separate operations, and the deploy
  script provably preserves catalog availability across a cutover.
- Rollback procedure names exact commands/controls (symlink retarget) and is
  tested in staging.
- `choir-training` remains recoverable (tag + archived branch) until
  owner-approved cleanup.

## Handoff

Report the reconciliation PR, merge evidence (test counts), the release
script, staging proof (including catalog-availability check), rollback proof,
branch-protection follow-up, and any manual repository-setting changes.

