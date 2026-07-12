# TRUST-04: Human Accuracy Audit And Review Clustering

Status: in progress; tooling and release-bound sample staged 2026-07-11,
human grading pending. Priority: P1.

Dependencies: stable ledger/signals/fixtures. Blocks: credible accuracy claims
and review campaign ordering.

Owned files: sampling/report tooling and approved aggregate results; private
review artifacts remain outside the public repository.

## Goal

Estimate actual transcription accuracy and turn the review queue into systemic
parser campaigns rather than an unstructured pile.

## Steps

1. Define strata by font, layout, voice count, genre, warning profile, confidence,
   and override/history.
2. Draw a reproducible sample of accepted and review scores.
3. Define measure-level review rubric for pitch, rhythm, voice, lyric, divisi,
   layout, and metadata.
4. Capture reviewer evidence and disagreement.
5. Estimate error rates with sample sizes and uncertainty, not a single headline.
6. Cluster review items by failure signature and projected catalog impact.
7. Produce the ordered parser campaign backlog.

## Acceptance

Sampling is reproducible; results distinguish structural and semantic accuracy;
private source material is not published; clusters link to evidence; every
accuracy claim names release, strata, sample size, and review date.

## Implementation Record

`human_audit.py` now prepares a private audit dataset from a sealed release,
verifies parser/source identity, draws a deterministic coverage-first sample,
emits a seven-category review template, validates opaque reviewer evidence,
calculates Wilson 95% intervals, records independent reviewer disagreement,
and orders review signatures into parser campaigns by review count and
projected catalog impact. `HUMAN_AUDIT.md` documents the privacy boundary and
operator workflow. Twenty focused tests cover the fail-closed contracts.

An audit-only release, `rel-20260712T020654Z-2ed9d59c020b`, was built and
sealed but not promoted. It is bound to parser `7ece091`, contains the same
3,358 accepted outputs as the current catalog plus confidence-vector reports;
its manifest and all 3,793 state records are object-identical and every served
MusicXML file is byte-identical. It passed 211 private tests with no failures
or skips. Because sealed releases
correctly omit unpublished reports, the private dataset copied those 3,358
reports and regenerated only the 125 review reports from source-hash-verified
PDFs. Its 3,483-report inventory hash is
`6c7a5ed045b6f9f4ae8f71fc4bf8d3f580fed05c38f6bcc1c80e2941e046524f`.

The staged `chanterlab-trust04-v1` sample contains 48 pieces: 36 accepted and
12 review. It covers 42 legacy, 4 SMuFL, and 2 mixed-font pieces across one-,
two-, three-, four-, and six-staff layout modes. Three zero-measure failures
remain in clustering but are excluded from accuracy sampling; the plan contains
141 source-comparison measures. Clustering accounts for all 125 review pieces
in 48 stable signatures and emits an ordered private campaign backlog.

Repository verification passed 220 tests with private PDFs and passed 190 with
30 explicit private-only skips in public mode. No production release pointer,
acceptance policy, trust status, or MusicXML changed.

TRUST-04 is not complete and no accuracy claim exists yet. Completion requires
human reviewers to grade the staged measures, record any disagreement, review
the private campaign evidence, and approve only a privacy-safe aggregate.
