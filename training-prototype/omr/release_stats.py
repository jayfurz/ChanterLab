#!/usr/bin/env python3
"""CAT-03: generate a nonprivate counts/confidence/trust summary from a
release descriptor, so operational docs can cite a live command instead of
a hand-copied number that silently goes stale as new releases are sealed.

Every field here already exists in release-descriptor.json (CAT-01 schema);
this only selects and formats the nonprivate subset — counts, hashes'
presence, and trust/confidence — never paths, PDF content, or report text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import catalog_release as cr


def summarize(descriptor: dict) -> dict:
    return {
        "release_id": descriptor["release_id"],
        "parent_release_id": descriptor.get("parent_release_id"),
        "generated_at": descriptor["generated_at"],
        "code": {
            "parser_git_sha": descriptor["code"]["parser_git_sha"],
            "app_git_sha": descriptor["code"]["app_git_sha"],
        },
        "counts": {
            "manifest_entries": descriptor["manifest"]["entry_count"],
            "musicxml": descriptor["musicxml"]["count"],
            "reports": descriptor["reports"]["count"],
            "state_records": descriptor["state"]["record_count"],
            "overrides": descriptor["overrides"]["count"],
            "bundled_content": descriptor.get("bundled_content", {}).get("count", 0),
        },
        "trust": {
            "status_counts": descriptor["trust"]["status_counts"],
            "confidence": descriptor["trust"]["confidence"],
        },
        # Aggregate-only. Reviewer/evidence history remains in the private
        # release-local snapshot and is intentionally never projected here.
        "quality_ledger": descriptor.get("quality_ledger"),
        "readiness": descriptor["readiness"],
    }


def format_markdown(summary: dict) -> str:
    c = summary["counts"]
    return (
        f"`{summary['release_id']}` (app `{summary['code']['app_git_sha']}`, "
        f"generated {summary['generated_at']}): {c['manifest_entries']} "
        f"manifest entries, {c['musicxml']} MusicXML, {c['reports']} reports, "
        f"{c['state_records']} state records"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", required=True, type=Path)
    ap.add_argument("--release-id", default=None, help="defaults to the current pointer")
    ap.add_argument("--markdown", action="store_true", help="print a one-line doc-embeddable summary instead of JSON")
    args = ap.parse_args(argv)

    store = args.store.resolve()
    release_id = args.release_id or cr._pointer_release_id(store, "current")
    if not release_id:
        print("release_stats: no release-id given and no current pointer set", file=sys.stderr)
        return 1
    try:
        descriptor = cr.validate_release(cr._release_path(store, release_id))
    except (cr.ReleaseError, OSError) as e:
        print(f"release_stats: cannot validate {release_id}: {e}", file=sys.stderr)
        return 1
    summary = summarize(descriptor)
    if args.markdown:
        print(format_markdown(summary))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
