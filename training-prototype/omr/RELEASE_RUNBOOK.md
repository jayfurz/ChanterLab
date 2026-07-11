# Catalog Release Runbook

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
metadata, verification evidence, and a private immutable
`trust/quality-ledger.json` snapshot when built by TRUST-01-aware tooling.
Source PDFs are shared inputs and are never copied into a release or onto the
production PVC.

## Release environment

Release, promotion, and restore validation fail closed unless the OMR venv has
the declared JSON Schema validator. Before running any command in this
runbook, provision it once in the venv:

```sh
cd training-prototype/omr
uv pip install --python .venv/bin/python -r requirements-release.txt
```

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
  --python "$PWD/.venv/bin/python" \
  --source-omr-dir "$PWD"

RELEASE_DIR=$(.venv/bin/python catalog_release.py seal \
  --store "$STORE" \
  --candidate "$CANDIDATE" \
  --source-omr-dir "$PWD")
RELEASE_ID=$(basename "$RELEASE_DIR")

.venv/bin/python catalog_release.py diff \
  --store "$STORE" --release-id "$RELEASE_ID"
```

`new` snapshots overrides/tombstones, the private quality-ledger journal (if
one exists), and approved built-ins before extraction. The ledger journal is
reconciled only at seal time into an immutable release snapshot; do not edit a
candidate's copied journal after verification. Fresh ingestion records each
source PDF hash immediately around extraction; verification and sealing both
refuse source, journal, metadata, manifest, MusicXML, report, override, or
built-in changes after candidate verification. Sealing prunes non-manifest
MusicXML/reports, removes the mutable journal, and retains exactly the private
`trust/quality-ledger.json` snapshot in the sealed release.
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
  --candidate "$CANDIDATE" --python "$PWD/.venv/bin/python" \
  --source-omr-dir "$PWD"
RELEASE_DIR=$(.venv/bin/python catalog_release.py seal \
  --store "$STORE" --candidate "$CANDIDATE" --source-omr-dir "$PWD")
```

Only manifest-published MusicXML/reports, full state, overrides/tombstones,
the private quality-ledger journal when present, and approved built-ins are
copied. Stale unlisted MusicXML is excluded.

`import-existing` stamps the PDF bytes observed when the migration candidate
starts, then binds them through verify/seal. That detects drift during the
migration but cannot prove what bytes produced an older legacy extraction; use
a fresh `new` reimport when extraction-time provenance is required.

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
For a ledger-bearing candidate, validation additionally proves the immutable
ledger hash, exact manifest reconciliation, score/source provenance, and
descriptor binding. Owner approval of the TRUST-01 vocabulary is required
before promoting the first ledger-bearing production release.

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
descriptor, quality ledger, overrides, and source material remain denied by
the server.

## Backup and restore (CAT-03)

`backup_restore.py` defines the restore contract; run `backup_restore.py sets`
for the exact source/state/override/private-quality-journal, sealed-release,
pointer, and verification evidence sets. `staging/`, `.promotion.lock`, and
OMR scratch directories are deliberately excluded because they are unserved
and regenerable.

Infra's `chanterlab-corpus-archive.timer` runs daily at 03:00 MST and performs
the transport to the private TrueNAS mirror with permanent retention. It
archives mutable PDFs, state, reports, overrides, tombstones, and the private
quality-ledger journal from the source checkout, but
captures sealed releases plus `current`/`previous` from the live VPS PVC while
the shared promotion lock is held. Each run also stores two required pieces of
evidence beside the release tree:

- `backup-hash-manifest.json`: a timestamped exact SHA-256 inventory of the
  mutable sets.
- `release-snapshot.json`: the production `current`/`previous` release IDs
  captured with the tar stream.

No credentials are in the payload; SSH access and any future at-rest key stay
in `infra/secrets/`, never in this catalog. This backup class deliberately
matches the existing platform convention of no file-level encryption at rest.
The TrueNAS archive root is owner-only (`0700`) and this waiver must be
revisited if the platform's storage-encryption baseline changes.

Recovery objectives: target RPO is 24 hours (the daily timer; trigger it
manually after an exceptional catalog promotion), and target RTO is 30 minutes
from available TrueNAS access to a validated restored tree. The initial
off-machine drill on 2026-07-10 transferred a 1,953,410,131-byte, 25,555-file
archive in 18 seconds and reached strict restore validation in 24 seconds.
Run a full off-machine restore drill quarterly and after any material
backup-layout change; the next scheduled drill is due 2026-10-10.

Restore into a clean location and prove every byte, not just "the copy
completed":

```sh
# 1. Copy the private TrueNAS archive to a temporary local archive view.
#    Keep it separate from the exact restore destination. The host/path are
#    the private values documented in infra, not application secrets.
ARCHIVE_COPY=$(mktemp -d)
RESTORE_DIR=$(mktemp -d)
ARCHIVE_HOST=<private-backup-host>
ARCHIVE_PATH=<private-chanterlab-archive-path>
ssh "$ARCHIVE_HOST" "tar -C '$ARCHIVE_PATH' -cf - ." \
  | tar -C "$ARCHIVE_COPY" -xpf -

cd training-prototype/omr
uv pip install --python .venv/bin/python -r requirements-release.txt
EVIDENCE="$ARCHIVE_COPY/out/release-store/backup-hash-manifest.json"
.venv/bin/python backup_restore.py materialize \
  --archive-root "$ARCHIVE_COPY" \
  --destination "$RESTORE_DIR" \
  --hash-manifest "$EVIDENCE"
```

`materialize` copies only manifest-listed mutable files from the additive
mirror, so a deleted retired override cannot reappear in the recovery tree.
It then runs strict `verify-store`: every sealed release fingerprint and file
hash is recomputed; the pointer targets must be valid, distinct, relative,
and match `release-snapshot.json`; and the mutable inventory must exactly
match `backup-hash-manifest.json`. A ledger-bearing release also revalidates
its private `trust/quality-ledger.json` snapshot. Exit code is nonzero on any
problem.

Prove the restored data is actually operable, not just byte-valid, by running
the normal local promotion/rollback commands above against
`$RESTORE_DIR/out/release-store` before trusting it.

### Off-machine drill record (2026-07-10)

The actual TrueNAS archive was restored into a clean location. Its bound
12,125-file mutable hash manifest, both sealed release fingerprints, and the
exact `current`/`previous` snapshot all validated with zero problems. The
restored store began at
`rel-20260710T200845Z-d1d822d75972` with
`rel-20260710T202424Z-d1d822d75972` as `previous`; it was promoted to the
previous release and rolled back. The original pointer/evidence digest was
reproduced exactly, then strict verification passed again. This is the measured
24-second end-to-end recovery result used for the RTO above, not the earlier
local-only validation metric.

## Generated statistics (CAT-03)

Never hand-copy catalog totals into a doc as a bare, undated number — either
cite a specific release ID (a dated snapshot, like the initial-release entry
above) or point at this command:

```sh
.venv/bin/python release_stats.py --store out/release-store            # current pointer, JSON
.venv/bin/python release_stats.py --store out/release-store --release-id <id>
.venv/bin/python release_stats.py --store out/release-store --markdown  # one-line, doc-embeddable
```

The command validates the selected sealed release before formatting. Output is
the nonprivate subset of its release descriptor only: counts, trust/status
distribution, confidence, and aggregate quality-ledger counts — never paths,
PDF content, report text, reviewer references, or evidence history.
