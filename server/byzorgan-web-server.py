#!/usr/bin/env python3
"""Hardened static file server for byzorgan-web (beast :8765).

Drop-in replacement for `python3 -m http.server 8765 --directory
/mnt/data/code/byzorgan-web/web`. Same static serving, plus:

  1. NO directory autoindex, anywhere. A request that resolves to a directory
     is served ONLY if that directory has an index.html/index.htm; otherwise
     it returns 404 (never an enumerable listing). This kills the python
     http.server autoindex that was leaking /training/omr/**.

  2. /training/omr/** is DENY-BY-DEFAULT (allowlist, not blocklist). Only the
     app artifacts and public release marker are served:
         /training/omr/out/ingest/manifest.json
         /training/omr/out/ingest/release.json
         /training/omr/out/ingest/<name>.musicxml   (single path segment)
     Everything else under /training/omr/ returns 404 — the source PDFs
     (pdfs/**), gt_crops/, pages/, verify/, out/** non-ingest artifacts,
     *.report.json, ingest_state.json, the pipeline *.py sources, *.log, etc.
     The public ``release.json`` marker is also allowed so smoke checks can
     identify the exact atomically served catalog release.

  3. Host-aware routing (issue #70): on the chanterlab.com brand hosts
     (chanterlab.com, www.chanterlab.com) the training app is served at the
     ROOT instead of at /training/*:
       - "/" and any path NOT starting with /training are internally mapped
         to training-prototype as if it were mounted at "/" (e.g. GET /js/
         main.js on chanterlab.com serves web/training/js/main.js). Done by
         overriding translate_path() only — self.path itself is never
         mutated, so http.server's own trailing-slash-redirect logic (which
         builds its Location header from self.path, see cpython
         http/server.py SimpleHTTPRequestHandler.send_head) can't leak the
         internal /training prefix back to the client.
       - /training and /training/* 301-redirect to the same path with the
         prefix stripped (canonicalizing old links), query string preserved.
     On every OTHER host (byz.alwaysdobetterllc.com, localhost, anything
     else) behavior is untouched: the legacy Byzantine app at /, the
     /training/ choir app as today. This was verified empirically (see infra
     issue #70 notes): ingress-nginx (use-forwarded-headers: true) forwards
     the original edge Host unchanged to this origin as both the Host header
     itself and X-Forwarded-Host — e.g. a request to https://chanterlab.com/
     arrives here with Host: chanterlab.com. Direct localhost:8765 requests
     (no proxy in front) arrive with Host: localhost:8765 and no
     X-Forwarded-Host at all. Host (stripped of any :port) is therefore the
     routing key.

  4. Legacy scales mount (SCALES-01, docs/plans/80-scales-and-raga/): on the
     same brand hosts, /scales and /scales/* map to the legacy Byzantine app
     as if the legacy webroot were mounted at /scales/ — GET /scales/app.js
     on chanterlab.com serves web/app.js. Implemented in translate_path()
     with the same never-mutate-self.path discipline as point 3, so the
     stdlib trailing-slash redirect for GET /scales emits Location: /scales/
     without leaking anything internal. Every other host is untouched:
     /scales resolves as an ordinary (nonexistent) file there and 404s.
     /scales/training/* is left alone on purpose — it resolves through the
     web/training symlink like it always has on legacy hosts, and the OMR
     allowlist below still applies because it checks the resolved path.

  The /training/omr allowlist policy (point 2) is evaluated against the
  logical path AFTER the root-host rewrite (point 3), i.e. on the same
  resolved filesystem path that will actually be opened — so
  chanterlab.com/omr/pdfs/... is denied exactly like the legacy
  byz.../training/omr/pdfs/... is, and chanterlab.com/omr/out/ingest/... is
  allowed exactly like the legacy equivalent.

The policy decision is made against the SAME sanitized filesystem path the
base handler will actually open (derived via translate_path), so %2e / // /
.. / mixed-encoding tricks cannot desync the check from the bytes served.
"""

import functools
import http.server
import os
import sys
import urllib.parse

WEBROOT = os.environ.get("WEBROOT", "/mnt/data/code/byzorgan-web/web")
BIND = "0.0.0.0"
PORT = 8765

# Hosts that get the training app at "/" instead of the legacy Byzantine app.
ROOT_HOSTS = {"chanterlab.com", "www.chanterlab.com"}

# All logical paths below OMR_PREFIX are denied unless explicitly allowlisted.
# (Logical paths are always webroot-relative, e.g. "/training/omr/..." — this
# is unaffected by which host asked for it.)
OMR_DIR = "/training/omr"          # the directory itself
OMR_PREFIX = "/training/omr/"      # anything under it
OMR_INGEST = "out/ingest/"         # allowed subtree (relative to OMR_PREFIX)


def _omr_allowed(rel: str) -> bool:
    """rel is the path relative to OMR_PREFIX, e.g. 'out/ingest/foo.musicxml'.

    Allow exactly: manifest.json, release.json, and <seg>.musicxml under
    out/ingest, where <seg> is one path segment (no further slashes).
    """
    if rel in (OMR_INGEST + "manifest.json", OMR_INGEST + "release.json"):
        return True
    if rel.startswith(OMR_INGEST):
        tail = rel[len(OMR_INGEST):]
        if tail.endswith(".musicxml") and tail != ".musicxml" and "/" not in tail:
            return True
    return False


class HardenedHandler(http.server.SimpleHTTPRequestHandler):
    # --- serve .musicxml with a sane content type (cosmetic; fetch().text()
    #     doesn't care, but keeps things tidy) ---
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".musicxml": "application/vnd.recordare.musicxml+xml",
        ".mjs": "text/javascript",
        ".wasm": "application/wasm",
    }

    # App code must never be served stale: without an origin Cache-Control,
    # Cloudflare edge-caches .css/.js for 4h and Safari heuristic-caches them
    # locally, so any HTML restructure ships new markup against old
    # styles/modules (2026-07-05 iPhone incident: all tab panes rendered at
    # once). no-cache = revalidate every time; unchanged files still answer
    # 304 via If-Modified-Since, so the cost is a conditional request, not a
    # re-download. Vendor libs and audio samples are effectively immutable —
    # let them cache for a day.
    _NO_CACHE_EXTS = (".html", ".css", ".js", ".mjs", ".json")
    _LONG_CACHE_PREFIXES = ("/vendor/", "/samples/", "/training/vendor/",
                            "/training/samples/")

    def end_headers(self):
        path = self.path.split("?", 1)[0].lower()
        if any(path.startswith(p) for p in self._LONG_CACHE_PREFIXES):
            self.send_header("Cache-Control", "public, max-age=86400")
        elif path.endswith(self._NO_CACHE_EXTS) or path.rstrip("/") in ("", "/training", "/scales"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _root_host(self) -> bool:
        """True when this request's Host header names a chanterlab.com brand
        host (root-mounted training app). False for byz.alwaysdobetterllc.com,
        localhost, or anything else — those keep today's behavior exactly."""
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        return host in ROOT_HOSTS

    def translate_path(self, path):
        # Root-host rewrite: map "/x" -> "/training/x" before the normal
        # translate_path resolves it under WEBROOT, so the training app is
        # served as if mounted at "/". Paths already starting with /training
        # are left alone (they're either a legacy-host request, or a
        # root-host request about to be 301-redirected by send_head() before
        # translate_path is ever consulted for them — see
        # _redirect_legacy_training_prefix).
        #
        # NOTE: this only overrides how the FILE is resolved. self.path
        # itself is never mutated, so http.server's own trailing-slash
        # redirect (send_head, which builds its Location from self.path, not
        # from translate_path's output) still reflects the client's original
        # URL and can't leak the internal /training prefix back out.
        if self._root_host():
            raw = path.split("?", 1)[0].split("#", 1)[0]
            if raw == "/scales" or raw.startswith("/scales/"):
                # Legacy scales mount (docstring point 4): strip the prefix
                # and skip the /training rewrite so /scales/* resolves under
                # the legacy webroot exactly as "/" does on non-brand hosts.
                stripped = path[len("/scales"):]
                path = stripped if stripped.startswith("/") else "/" + stripped
            elif raw != "/training" and not raw.startswith("/training/"):
                path = "/training" + path
        return super().translate_path(path)

    def _logical_path(self) -> str:
        """The request path as a leading-slash logical path, derived from the
        exact sanitized filesystem path the base handler will open (after the
        root-host rewrite in translate_path, if any). Traversal components
        are already stripped by translate_path, so this cannot escape
        WEBROOT."""
        fs = self.translate_path(self.path)
        root = os.path.abspath(self.directory)
        rel = os.path.relpath(fs, root)
        if rel == os.curdir or rel == ".":
            return "/"
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            # Shouldn't happen (translate_path strips '..'), but never treat an
            # out-of-root path as an allowlisted one.
            return "/__outside__/" + rel.replace(os.sep, "/")
        return "/" + rel.replace(os.sep, "/")

    def _denied(self) -> bool:
        p = self._logical_path()
        if p == OMR_DIR:
            return True  # the omr/ directory root itself
        if p.startswith(OMR_PREFIX):
            return not _omr_allowed(p[len(OMR_PREFIX):])
        return False

    def _redirect_legacy_training_prefix(self) -> bool:
        """Root hosts only: canonicalize /training and /training/* to the
        same path with the prefix stripped (301, query string preserved).
        Returns True iff a redirect response was sent (caller must stop)."""
        if not self._root_host():
            return False
        split = urllib.parse.urlsplit(self.path)
        if split.path != "/training" and not split.path.startswith("/training/"):
            return False
        new_path = split.path[len("/training"):] or "/"
        new_url = urllib.parse.urlunsplit(("", "", new_path, split.query, ""))
        self.send_response(301)
        self.send_header("Location", new_url)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def send_head(self):
        # do_GET and do_HEAD both route through send_head, so this one gate
        # covers both verbs.
        if self._redirect_legacy_training_prefix():
            return None
        if self._denied():
            self.send_error(404, "Not Found")
            return None
        return super().send_head()

    def list_directory(self, path):
        # Reached only when a directory has no index.html/index.htm. Never emit
        # an autoindex — 404 instead.
        self.send_error(404, "Not Found")
        return None


def main() -> int:
    if not os.path.isdir(WEBROOT):
        sys.stderr.write("byzorgan-web-server: webroot missing: %s\n" % WEBROOT)
        return 1
    handler = functools.partial(HardenedHandler, directory=WEBROOT)
    httpd = http.server.ThreadingHTTPServer((BIND, PORT), handler)
    sys.stderr.write(
        "byzorgan-web-server: serving %s on %s:%d "
        "(no autoindex; /training/omr allowlisted; chanterlab.com/www "
        "root-mounted, legacy scales at /scales/)\n"
        % (WEBROOT, BIND, PORT)
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
