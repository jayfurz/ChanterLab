"""Shared fixtures/config for the OMR engine regression suite (issue #53).

Run from ``omr/``::

    .venv/bin/python -m pytest tests/

Re-bless (after a deliberate, reviewed engine change)::

    UPDATE_EXPECTATIONS=1 .venv/bin/python -m pytest tests/
    # or
    .venv/bin/python -m pytest tests/ --bless

Either flips every comparison test in ``test_regression.py`` from "compare
against tests/expectations.json" to "record what the CURRENT engine
produces" -- extractions still run, absent-PDF tests still skip, but the
committed expectations file is overwritten with fresh sha256/stats instead
of being diffed against. See ``tests/README.md`` for the re-bless policy
(no engine change lands without either green tests or a justified re-bless).

This suite is LOCAL-ONLY BY DESIGN: the corpus PDFs are copyrighted works
under ``omr/pdfs/`` (gitignored, never committed) and the MusicXML/report
output they produce is derived from them, so it is not committed either.
Only sha256 hashes and stat numbers are committed. On a machine without the
PDFs (e.g. CI) every regression test SKIPs with a clear message rather than
failing or erroring.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

OMR_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
PDF_DIR = OMR_DIR / "pdfs" / "ingest"
VENV_PYTHON = OMR_DIR / ".venv" / "bin" / "python"
PIPELINE_PYTHON = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
PIPELINE = OMR_DIR / "pipeline.py"
EXPECTATIONS_PATH = TESTS_DIR / "expectations.json"

EXTRACT_TIMEOUT = 180  # s per piece; mirrors ingest_catalog.py's EXTRACT_TIMEOUT


def pytest_addoption(parser):
    parser.addoption(
        "--bless", action="store_true", default=False,
        help="Re-bless tests/expectations.json from the CURRENT engine "
             "output instead of comparing against it. Use only after a "
             "deliberate, reviewed vector_extract.py/pipeline.py change -- "
             "justify the diff in the commit message.",
    )


@pytest.fixture(scope="session")
def bless_mode(pytestconfig) -> bool:
    return bool(pytestconfig.getoption("--bless")) or \
        os.environ.get("UPDATE_EXPECTATIONS") == "1"


def load_expectations() -> dict:
    with open(EXPECTATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


# Updates collected during a --bless run, flushed once at session end so a
# partially-failed run (e.g. a crash mid-suite) never corrupts the committed
# file with only some pieces re-blessed.
_bless_updates: dict[str, dict] = {}


def record_bless(piece_id: str, entry: dict) -> None:
    _bless_updates[piece_id] = entry


def pytest_sessionfinish(session, exitstatus):
    if not _bless_updates:
        return
    if exitstatus != 0:
        # A red bless run must not rewrite expectations.json: the semantic
        # tests would catch a bad re-bless next run anyway, but flushing here
        # leaves a confusing half-blessed diff in the working tree.
        print(f"\n[bless] session failed (exit {exitstatus}); discarding "
              f"{len(_bless_updates)} staged expectation update(s)")
        return
    data = load_expectations()
    for piece_id, entry in _bless_updates.items():
        # Preserve hand-written fields (e.g. "notes") that bless doesn't
        # know about; only overwrite what it computed.
        existing = data["pieces"].setdefault(piece_id, {})
        existing.update(entry)
    with open(EXPECTATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"\n[bless] wrote {len(_bless_updates)} updated expectation(s) "
          f"to {EXPECTATIONS_PATH}")


def run_pipeline(pdf_path: Path, out_dir: Path, *, env: dict | None = None):
    """Run pipeline.py exactly the way production (ingest_catalog.py) does:
    subprocess, venv python, default ``--pages auto`` / ``--min-integrity
    90``. Writes into ``out_dir`` (a pytest tmp_path -- never the repo).

    Returns (CompletedProcess, xml_path, report_path).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_path = out_dir / (pdf_path.stem + ".musicxml")
    report_path = out_dir / (pdf_path.stem + ".report.json")
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    proc = subprocess.run(
        [str(PIPELINE_PYTHON), str(PIPELINE), str(pdf_path),
         "-o", str(xml_path), "--report", str(report_path)],
        capture_output=True, text=True, timeout=EXTRACT_TIMEOUT,
        cwd=OMR_DIR, env=run_env,
    )
    return proc, xml_path, report_path


def skip_if_pdf_missing(piece_id: str, pdf_path: Path) -> None:
    if not pdf_path.exists():
        pytest.skip(
            f"{piece_id}: source PDF not present locally ({pdf_path}) -- "
            f"the corpus PDFs are copyrighted and gitignored/local-only "
            f"(see tests/README.md); this test only runs where the "
            f"Antiochian library checkout lives.")
