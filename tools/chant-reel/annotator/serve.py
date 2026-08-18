#!/usr/bin/env python3
"""serve.py — annotator static server + server-side export endpoint.

Serves the annotator directory like `python -m http.server` did, plus:

  POST /api/export   body: {piece_id, pins, slots_corrected, mcr_flags}
                     writes pins.json / slots_corrected.json / mcr_flags.json
                     into <exports-dir>/<piece_id>/ (canonical latest) and a
                     timestamped copy under .../history/<stamp>/ so an
                     accidental empty export can never destroy good work.

Usage:
  python3 serve.py [--port 8779] [--bind 0.0.0.0] [--exports-dir DIR]

Default exports dir is ./exports next to this script.
"""
import argparse
import json
import re
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_BODY = 32 * 1024 * 1024
PIECE_RE = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]{1,80}$")   # no "." / ".."

EXPORT_FILES = {          # payload key -> filename written
    "pins": "pins.json",
    "slots_corrected": "slots_corrected.json",
    "mcr_flags": "mcr_flags.json",
    "pitch_ghosts": "pitch_ghosts.json",
    "analytical_notes": "analytical_notes.json",
}
OPTIONAL_KEYS = {"pitch_ghosts": [], "analytical_notes": []}   # defaults for older clients


class Handler(SimpleHTTPRequestHandler):
    exports_dir: Path = HERE / "exports"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".txt": "text/plain; charset=utf-8",
                      ".html": "text/html; charset=utf-8",
                      ".json": "application/json; charset=utf-8"}

    def do_POST(self):
        if self.path.rstrip("/") != "/api/export":
            self.send_error(404, "unknown endpoint")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError(f"bad content length {n}")
            payload = json.loads(self.rfile.read(n))
            piece = payload.get("piece_id", "")
            if not PIECE_RE.match(piece):
                raise ValueError(f"bad piece_id {piece!r}")
            for k, dflt in OPTIONAL_KEYS.items():
                payload.setdefault(k, dflt)
            missing = [k for k in EXPORT_FILES if k not in payload]
            if missing:
                raise ValueError(f"missing keys: {missing}")
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, str(e))
            return

        dest = self.exports_dir / piece
        stamp = time.strftime("%Y%m%d-%H%M%S")
        hist = dest / "history" / stamp
        hist.mkdir(parents=True, exist_ok=True)
        for key, fname in EXPORT_FILES.items():
            text = json.dumps(payload[key], indent=1)
            (dest / fname).write_text(text)
            (hist / fname).write_text(text)

        body = json.dumps({
            "ok": True,
            "dir": str(dest),
            "stamp": stamp,
            "files": list(EXPORT_FILES.values()),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.log_message("export %s -> %s (history/%s)", piece, dest, stamp)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8779)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--exports-dir", default=str(HERE / "exports"))
    args = ap.parse_args()

    Handler.exports_dir = Path(args.exports_dir).resolve()
    Handler.directory = str(HERE)
    httpd = ThreadingHTTPServer((args.bind, args.port),
                                lambda *a, **kw: Handler(*a, directory=str(HERE), **kw))
    print(f"annotator at http://{args.bind}:{args.port}/ "
          f"(exports -> {Handler.exports_dir})")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
