# EXPAND-01: Upload, Rights, Privacy, And Backend Architecture

Status: blocked on owner/product decisions. Priority: P2/P3.

Dependencies: rights controls, immutable releases, quality loop, privacy policy.
Blocks: every account/upload/director implementation.

Owned files: architecture decision record and threat/data-flow models only until
approved.

## Owner Decisions

Personal-only versus invited choir; supported born-digital input; backend/host;
identity provider; storage region/cost; retention/deletion; permission attestation;
takedown; quotas/abuse; support expectations; whether any audio is ever stored.

## Goal

Choose the smallest private-by-default architecture that can safely turn an
authorized PDF into a reviewable practice score.

## Steps

1. Model data, actors, trust boundaries, jobs, artifacts, and failure states.
2. Define rights attestation and prohibited/public-sharing behavior.
3. Define encryption, access, deletion, retention, backup, audit, and incidents.
4. Estimate operating cost and support burden.
5. Compare local-only, single-user hosted, and choir-hosted options.
6. Record owner decision before implementation plans become ready.

## Acceptance

No ambiguous public sharing; every artifact has owner, purpose, retention, and
deletion; threat model covers unauthorized access and malicious PDFs; cost and
rollback are understood; legal review needs are named rather than assumed.

