# Catalog release runbook (CAT-02)

The active catalog is never an ingest directory. It is one symlink:

```text
<store>/staging/.staging-*/       interrupted/resumable candidates, never served
<store>/releases/rel-*/           sealed, read-only releases, never modified
<store>/current -> releases/rel-* atomically replaced production pointer
<store>/previous -> releases/rel-* retained rollback target
```

Each release contains `out/` (manifest, published MusicXML, reports, state,
and public `release.json` marker), release-scoped `overrides/`, the four
publication-approved `content/` built-ins, `release-descriptor.json`, build
metadata, and verification evidence. Source PDFs are shared inputs and are
never copied into a release or onto the production PVC.

## Build a new extraction

Use a clean checkout at the exact app/parser SHA intended for release:

```sh
cd training-prototype/omr
STORE=/mnt/data/chanterlab-catalog-releases
APP_SHA=$(git rev-parse HEAD)

CANDIDATE=$(.venv/bin/python catalog_release.py new \
  --store "$STORE" \
  --source-omr-dir "$PWD" \
  --app-sha "$APP_SHA")

.venv/bin/python ingest_catalog.py \
  --candidate-dir "$CANDIDATE" \
  --categories choral,chant

.venv/bin/python catalog_release.py verify \
  --candidate "$CANDIDATE" \
  --python "$PWD/.venv/bin/python"

RELEASE_DIR=$(.venv/bin/python catalog_release.py seal \
  --store "$STORE" \
  --candidate "$CANDIDATE" \
  --source-omr-dir "$PWD")
RELEASE_ID=$(basename "$RELEASE_DIR")

.venv/bin/python catalog_release.py diff \
  --store "$STORE" --release-id "$RELEASE_ID"
```

`new` snapshots overrides/tombstones and approved built-ins before extraction.
Resuming with `ingest_catalog.py --candidate-dir` is allowed only while the
parser checkout and cached upstream catalog still match the recorded build
metadata. A crash leaves files under `staging/`; it cannot affect `current`.

## One-time legacy import

The pre-CAT-02 catalog can be copied without re-extraction, but its historical
parser SHA must be supplied explicitly from ingestion records; the tool never
infers it from the importer checkout:

```sh
CANDIDATE=$(.venv/bin/python catalog_release.py import-existing \
  --store "$STORE" --source-omr-dir "$PWD" \
  --parser-sha <historical-parser-sha> --app-sha <target-app-sha>)
.venv/bin/python catalog_release.py verify \
  --candidate "$CANDIDATE" --python "$PWD/.venv/bin/python"
RELEASE_DIR=$(.venv/bin/python catalog_release.py seal \
  --store "$STORE" --candidate "$CANDIDATE" --source-omr-dir "$PWD")
```

Only manifest-published MusicXML/reports, full state, overrides/tombstones,
and approved built-ins are copied. Stale unlisted MusicXML is excluded.

## Local promotion and rollback

Both commands require the exact release ID as the approval token:

```sh
.venv/bin/python catalog_release.py promote \
  --store "$STORE" --release-id "$RELEASE_ID" --approve "$RELEASE_ID"

PREVIOUS=$(.venv/bin/python catalog_release.py status --store "$STORE" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["previous"])')
.venv/bin/python catalog_release.py rollback \
  --store "$STORE" --approve "$PREVIOUS"
```

Promotion validates the descriptor and every actual file hash again before
switching. Releases are retained; CAT-02 deliberately performs no pruning.

## Production publish

The infra publisher transfers an already sealed tree, verifies every byte,
runs the exact target container image in a disposable pod bound directly to
the candidate, and only then replaces the PVC's `current` symlink:

```sh
cd /mnt/data/code/infra
./scripts/publish_chanterlab_catalog.sh "$RELEASE_DIR" \
  --approve "$RELEASE_ID" \
  --image "git.lab.alwaysdobetterllc.com/jfursov/chanterlab-web:<validated-sha>"
```

The first migration uses `--bootstrap`: the old container continues reading
the legacy `data/out` layout while `current` is installed. Deploy the new
current-pointer-aware image through GitOps, then run the HTTP smoke against
all three production hostnames. Normal later publishes smoke publicly and
restore the former pointer automatically on failure.

Production rollback is also one pointer replacement and only accepts the
retained `previous` release:

```sh
./scripts/rollback_chanterlab_catalog.sh "$PREVIOUS" --approve "$PREVIOUS"
```

The public marker is `/omr/out/ingest/release.json` on ChanterLab root hosts
and `/training/omr/out/ingest/release.json` on the legacy host. It contains
only schema version, release ID, and content fingerprint; reports, state,
descriptor, overrides, and source material remain denied by the server.
