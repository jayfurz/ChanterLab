# Human Accuracy Audit v1

`human_audit.py` creates a reproducible, release-bound review sample, validates
private reviewer observations, publishes aggregate rates with Wilson 95%
intervals, and clusters the review queue by stable failure signature.

It does not infer transcription accuracy from confidence signals. Accuracy
exists only after a person compares the sampled source measures with the
transcription and completes every rubric category.

## Privacy Boundary

Audit plans may contain public catalog IDs, strata, warning counts, and measure
numbers. Reviewer result files are private and must remain outside the Git
repository. Use only opaque `reviewer_ref` and `evidence_ref` values: no names,
email addresses, filesystem paths, score text, screenshots, or PDF excerpts.
Only the aggregate output may be proposed for publication.

## Plan

The input release must contain `omr-confidence-vector-v1`. A release without
those vectors is refused rather than silently classified from legacy integrity.

```sh
.venv/bin/python human_audit.py plan \
  --release out/release-store/current \
  --sample-size 48 --measures-per-piece 3 \
  --seed chanterlab-trust04-v1 \
  --out /private/audit-plan.json \
  --results-template /private/audit-results.json
```

The deterministic coverage-first selection spans accepted/review status, font,
layout, voice count, genre, warning profile, confidence bands, and
override/history. If a private font index is unavailable, `font` is honestly
`unknown`; an optional JSON map of catalog ID to `legacy`, `smufl`, `mixed`, or
`unknown` can be supplied with `--font-index`.

Three measures per piece are selected by seeded hash. The result template uses
the seven-category rubric: pitch, rhythm, voice, lyric, divisi, layout, and
metadata. Each category is graded `pass`, `minor`, `major`, or `unreviewable`.

## Aggregate

```sh
.venv/bin/python human_audit.py summarize \
  --plan /private/audit-plan.json \
  --results /private/audit-results.json \
  --out /private/audit-aggregate.json
```

Summarization fails unless every sampled measure has exactly one complete,
release-bound observation with an ISO review date and opaque references. The
aggregate names the release, seed, date range, sample sizes, category error
rates, Wilson intervals, and stratified rates. It contains no source material.

## Review Clusters

```sh
.venv/bin/python human_audit.py cluster \
  --release /private/audit-ready-release \
  --out /private/review-clusters.json
```

Review items are grouped by stable warning-code signature. Ordering uses
affected piece count first, then warning-event volume. This is a campaign
backlog heuristic, not evidence that every piece in a cluster has the same
semantic defect; a reviewer must link confirmed observations before a parser
campaign is approved.
