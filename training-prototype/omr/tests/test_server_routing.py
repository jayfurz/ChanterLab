"""SCALES-01 host-routing tests for server/byzorgan-web-server.py.

Lives in this suite (not beside the server) because the unified required CI's
omr-rights-safe job runs exactly this directory, and the server already has a
unit test here (test_catalog_release.test_server_allowlist_exposes_marker_but_
not_descriptor). All content is synthetic and rights-safe.

Each test drives a real ThreadingHTTPServer on an ephemeral port against a
temp webroot shaped like the production layout, so the Host-header routing,
the stdlib trailing-slash redirect, and the OMR allowlist are exercised on the
same code path production uses — no handler internals are faked.
"""
from __future__ import annotations

import functools
import http.client
import http.server
import importlib.util
import threading
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_PATH = TESTS_DIR.parents[2] / "server" / "byzorgan-web-server.py"

BRAND_HOST = "chanterlab.com"
LEGACY_HOST = "localhost"


def _load_server_module():
    spec = importlib.util.spec_from_file_location("chanterlab_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def webroot(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("webroot")
    (root / "index.html").write_text("LEGACY-INDEX")
    (root / "style.css").write_text("LEGACY-CSS")
    training = root / "training"
    training.mkdir()
    (training / "index.html").write_text("TRAINING-INDEX")
    ingest_dir = training / "omr" / "out" / "ingest"
    ingest_dir.mkdir(parents=True)
    (ingest_dir / "manifest.json").write_text("[]")
    pdfs = training / "omr" / "pdfs"
    pdfs.mkdir()
    (pdfs / "secret.pdf").write_text("NEVER-SERVED")
    return root


@pytest.fixture(scope="module")
def server(webroot):
    module = _load_server_module()

    class QuietHandler(module.HardenedHandler):
        def log_message(self, *args):  # keep pytest output readable
            pass

    handler = functools.partial(QuietHandler, directory=str(webroot))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str, host: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Host": host})
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read().decode()
    finally:
        conn.close()


# --- brand host: /scales/* is the legacy app ---

def test_brand_root_still_serves_training(server):
    status, _, body = _get(server, "/", BRAND_HOST)
    assert (status, body) == (200, "TRAINING-INDEX")


def test_brand_scales_dir_serves_legacy_index(server):
    status, headers, body = _get(server, "/scales/", BRAND_HOST)
    assert (status, body) == (200, "LEGACY-INDEX")
    assert headers.get("Cache-Control") == "no-cache"


def test_brand_scales_asset_resolves_under_legacy_webroot(server):
    status, headers, body = _get(server, "/scales/style.css", BRAND_HOST)
    assert (status, body) == (200, "LEGACY-CSS")
    assert headers.get("Cache-Control") == "no-cache"


def test_brand_scales_without_slash_redirects_without_leaking(server):
    status, headers, _ = _get(server, "/scales", BRAND_HOST)
    assert status == 301
    assert headers.get("Location") == "/scales/"


def test_brand_scales_omr_denied_exactly_like_legacy(server):
    status, _, _ = _get(server, "/scales/training/omr/pdfs/secret.pdf", BRAND_HOST)
    assert status == 404


def test_brand_scales_omr_ingest_allowlisted_exactly_like_legacy(server):
    status, _, body = _get(
        server, "/scales/training/omr/out/ingest/manifest.json", BRAND_HOST
    )
    assert (status, body) == (200, "[]")


def test_brand_training_prefix_still_canonicalizes(server):
    status, headers, _ = _get(server, "/training/style.css?v=1", BRAND_HOST)
    assert status == 301
    assert headers.get("Location") == "/style.css?v=1"


# --- non-brand hosts: byte-identical to before, /scales does not exist ---

def test_legacy_root_still_serves_legacy(server):
    status, _, body = _get(server, "/", LEGACY_HOST)
    assert (status, body) == (200, "LEGACY-INDEX")


def test_legacy_training_still_serves_training(server):
    status, _, body = _get(server, "/training/", LEGACY_HOST)
    assert (status, body) == (200, "TRAINING-INDEX")


def test_legacy_scales_is_a_plain_404(server):
    for path in ("/scales", "/scales/", "/scales/style.css"):
        status, _, _ = _get(server, path, LEGACY_HOST)
        assert status == 404, path


def test_legacy_omr_deny_unchanged(server):
    status, _, _ = _get(server, "/training/omr/pdfs/secret.pdf", LEGACY_HOST)
    assert status == 404
