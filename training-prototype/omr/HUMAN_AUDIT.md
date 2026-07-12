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
Sealed releases intentionally omit unpublished review reports. Prepare a
private audit dataset to copy sealed accepted reports and regenerate only the
missing review reports from source PDFs:

```sh
.venv/bin/python human_audit.py prepare \
  --release out/release-store/releases/rel-... \
  --source-omr-dir . \
  --out /private/audit-dataset
```

Preparation verifies source hashes and requires the extraction modules to be
byte-identical to the release's parser commit. It discards regenerated
MusicXML, records a report-inventory hash, and never modifies the release.

```sh
.venv/bin/python human_audit.py plan \
  --release /private/audit-dataset \
  --sample-size 48 --measures-per-piece 3 \
  --review-share 0.25 \
  --seed chanterlab-trust04-v1 \
  --out /private/audit-plan.json \
  --results-template /private/audit-results.json
```

The deterministic coverage-first selection spans accepted/review status, font,
layout, voice count, genre, warning profile, confidence bands, and
override/history. If a private font index is unavailable, `font` is honestly
`unknown`; an optional JSON map of catalog ID to `legacy`, `smufl`, `mixed`, or
`unknown` can be supplied with `--font-index`.
The default sample reserves 25% of pieces for the smaller review population;
the exact accepted/review targets are recorded in the plan rather than left to
chance.

Create that private index directly from the source inventory when available:

```sh
.venv/bin/python human_audit.py font-index \
  --release /private/audit-ready-release \
  --source-omr-dir . \
  --out /private/font-index.json
```

The index contains only catalog ID and the coarse family class. It does not
contain source paths, embedded font names, or PDF content.

Three measures per piece are selected by seeded hash. The result template uses
the seven-category rubric: pitch, rhythm, voice, lyric, divisi, layout, and
metadata. Each category is graded `pass`, `minor`, `major`, or `unreviewable`.
Zero-measure failures remain in clustering but are explicitly excluded from
accuracy sampling because there is no transcription measure to compare.

## Aggregate

```sh
.venv/bin/python human_audit.py summarize \
  --plan /private/audit-plan.json \
  --results /private/audit-results.json \
  --out /private/audit-aggregate.json
```

Summarization fails unless every sampled measure has at least one complete,
release-bound observation with an ISO review date and opaque references.
Independent reviewers may submit the same measure; duplicate submissions by
one reviewer are refused and category-level disagreement is reported. The
aggregate names the release, seed, date range, sample sizes, category error
rates, separate semantic/structural domains, Wilson intervals, and stratified
rates. It contains no source material.

## Review Clusters

```sh
.venv/bin/python human_audit.py cluster \
  --release /private/audit-ready-release \
  --out /private/review-clusters.json
```

Review items are grouped by stable warning-code signature. Ordering uses
review piece count first, then projected accepted-plus-review impact for the
same signature, then warning-event volume. Stable ordered campaign IDs make the
output an executable parser backlog. This is a prioritization heuristic, not
evidence that every piece in a cluster has the same semantic defect; a reviewer
must link confirmed observations before a parser campaign is approved.
