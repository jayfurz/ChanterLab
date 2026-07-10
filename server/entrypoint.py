#!/usr/bin/env python3
"""Bind the app to one catalog release, then start the hardened server.

Normal pods use ``CATALOG_POINTER=current``. A disposable pre-promotion smoke
pod can use ``releases/<release-id>`` against the same PVC without changing
the live pointer.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DATA_ROOT = Path("/srv/chanterlab/data")
TRAINING_ROOT = Path("/srv/chanterlab/training-prototype")
BUILTINS = (
    "trisagion_omr.musicxml",
    "trisagion_vector.musicxml",
    "cherubic_vector.musicxml",
    "anaphora_vector.musicxml",
)
_POINTER_RE = re.compile(r"^(?:current|releases/rel-\d{8}T\d{6}Z-[0-9a-f]{12})$")


def _replace_symlink(path: Path, target: Path) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.unlink(missing_ok=True)
    os.symlink(target, tmp)
    os.replace(tmp, path)


def configure_catalog(pointer: str) -> None:
    if not _POINTER_RE.fullmatch(pointer):
        raise RuntimeError(f"invalid CATALOG_POINTER: {pointer!r}")
    release = DATA_ROOT / pointer
    required = [release / "out" / "ingest" / "manifest.json",
                release / "out" / "ingest" / "release.json"]
    required.extend(release / "content" / name for name in BUILTINS)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("catalog release is incomplete: " + ", ".join(missing))

    _replace_symlink(TRAINING_ROOT / "omr" / "out", release / "out")
    for name in BUILTINS:
        _replace_symlink(TRAINING_ROOT / "content" / name, release / "content" / name)


def main() -> int:
    pointer = os.environ.get("CATALOG_POINTER", "current")
    try:
        configure_catalog(pointer)
    except RuntimeError as e:
        print(f"chanterlab-entrypoint: {e}", file=sys.stderr)
        return 1
    os.execv(sys.executable, [sys.executable, "/opt/chanterlab-server/byzorgan-web-server.py"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
