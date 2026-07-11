"""Shared parsing for private override lifecycle state.

``overrides/RETIRED`` records retired *override files*, not retired scores.
Keeping the parser here prevents ingestion, release validation, and the
quality ledger from disagreeing about inline comments or whitespace.
"""
from __future__ import annotations

from pathlib import Path


def load_retired_stems(override_dir: str | Path) -> list[str]:
    """Return sorted unique stems from ``overrides/RETIRED``.

    A ``#`` starts a comment anywhere on a line, matching the long-standing
    ingestion behavior. Empty lines are ignored.
    """
    retired_path = Path(override_dir) / "RETIRED"
    if not retired_path.is_file():
        return []
    stems = {
        line.split("#", 1)[0].strip()
        for line in retired_path.read_text(encoding="utf-8").splitlines()
    }
    stems.discard("")
    return sorted(stems)
