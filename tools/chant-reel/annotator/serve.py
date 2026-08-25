#!/usr/bin/env python3
"""serve.py — annotator static server + server-side export endpoint.

Serves the annotator directory like `python -m http.server` did, plus:

  POST /api/export   body: {piece_id, pins, slots_corrected, mcr_flags}
                     writes pins.json / slots_corrected.json / mcr_flags.json
                     into <exports-dir>/<piece_id>/ (canonical latest) and a
                     timestamped copy under .../history/<stamp>/ so an
                     accidental empty export can never destroy good work.

  GET  /api/parallagi?piece=<id>          the degree per glyph, index-aligned
                                          with the piece's own notes array
  POST /api/parallagi-flag  body: {piece, gi, shown, note, clear}
  GET  /api/parallagi-flags?piece=<id>    what the chanter rejected, so a later
                                          legend fix can be scored against the
                                          label he was actually shown

Usage:
  python3 serve.py [--port 8779] [--bind 0.0.0.0] [--exports-dir DIR]

Default exports dir is ./exports next to this script.
"""
import argparse
import json
import os
import re
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_BODY = 32 * 1024 * 1024
# Span pieces are named from the score's lyric layer, so a piece id is Greek:
# "grave-orthros-κατελυσαςτωσταυ-ρω-ωσουτον-parallagi" (longest in the gold
# set is 54 chars). This guards a filesystem path, so it stays a strict
# allowlist — Greek and Greek Extended added, "/" "\" NUL and "."/".." still
# rejected, length still capped.
PIECE_RE = re.compile(
    "^(?!\\.+$)[A-Za-z0-9._\u0370-\u03ff\u1f00-\u1fff-]{1,80}$")

EXPORT_FILES = {          # payload key -> filename written
    "pins": "pins.json",
    "slots_corrected": "slots_corrected.json",
    "mcr_flags": "mcr_flags.json",
    "pitch_ghosts": "pitch_ghosts.json",
    "analytical_notes": "analytical_notes.json",
}
FLAGS_FILE = "parallagi_flags.json"   # under data/<piece>/, not exports/
OPTIONAL_KEYS = {"pitch_ghosts": [], "analytical_notes": []}   # defaults for older clients


# The boundary cutter runs as its own service on 8790, bound to localhost. It
# is reachable over tailscale, but the chanter works through
# annotator.lab.alwaysdobetterllc.com, which the lab proxy forwards to THIS
# port — so its routes are passed through from here rather than asking him to
# use a second hostname. "/" stays the pin annotator; nothing is shadowed.
CUTTER = ('127.0.0.1', 8790)
CUTTER_PREFIXES = ('/score', '/cut', '/tape/', '/page/', '/api/tapes',
                   '/api/score/', '/api/peaks/', '/api/degrees/',
                   '/api/cuts', '/api/scorecuts', '/api/span',
                   '/api/degree-flag', '/book', '/api/book', '/paudio/')


# The cutter owns '/api/degree-flag'; these two are the annotator's own and
# must be answered here, so they are checked before the proxy test.
LOCAL_PREFIXES = ('/api/parallagi', '/api/parallagi-flag',
                  '/api/parallagi-flags', '/api/piece-peaks',
                  '/api/prep-par', '/api/transpose')


def _is_cutter(path):
    p = path.split('?')[0]
    if any(p == x for x in LOCAL_PREFIXES):
        return False
    return any(p == x.rstrip('/') or p.startswith(x) for x in CUTTER_PREFIXES)


CORPUS_TOOLS = '/mnt/data/code/byzorgan-web-worktrees/chant-annotator/tools/corpus'
CANON = '/mnt/data/chant-corpus/scores/legend_canon.json'
DEG_GR = ['νη', 'πα', 'βου', 'γα', 'δι', 'κε', 'ζω']


def _piece_arg(raw):
    """One piece id off the wire, decoded and validated (None if it fails).

    http.server decodes the request line as latin-1, so a Greek id arrives
    either percent-encoded (what fetch() sends) or as utf-8 bytes read as
    latin-1. Undo both before matching, or every span piece 400s.
    """
    from urllib.parse import unquote
    pid = unquote(raw, encoding='utf-8', errors='replace')
    if any(c in pid for c in ('/', '\\', '\0')):
        return None
    if '\ufffd' in pid:
        try:
            pid = unquote(raw, encoding='latin-1').encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            return None
    return pid if PIECE_RE.match(pid) else None


def parallagi_for(piece_id):
    """The degree each glyph of a piece should be sung on.

    Computed against the piece's OWN notes array so the result is index-aligned
    with what the annotator draws — no matching by coordinate, which is where
    an overlay silently ends up showing nothing.

    The anchor comes from the martyria printed before the hymn. load_units
    attaches a martyria to the unit BEFORE it (right at a cadence, wrong at a
    hymn's opening), so it sits just outside the slice and has to be fetched
    deliberately. Chanter: "grave mode starts with the ga martyria so it should
    start on ga as the beginning pitch".
    """
    import sys
    if CORPUS_TOOLS not in sys.path:
        sys.path.insert(0, CORPUS_TOOLS)
    dd = HERE / 'data' / piece_id / 'annotator_data.json'
    if not dd.exists():
        return {'error': f'no data for {piece_id}'}
    D = json.loads(dd.read_text())
    notes = D.get('notes', [])
    keys = (json.loads(open(CANON).read())['keys'] if os.path.exists(CANON)
            else {})

    # A span piece is not a hymns.json row and its id will never match "-tNN",
    # so the generator resolves leading_anchor() over the span's own score
    # range and records it. Prefer it; the regex path below still serves the
    # 179 pieces prep_hymn_annotator.py built.
    anchor = D.get('meta', {}).get('parallagi_anchor')
    m = None if anchor is not None else re.match(r'^(.*)-t(\d+)$', piece_id)
    if m:
        wd, num = m.group(1), m.group(2)
        hj = f'/mnt/data/chant-corpus/workdirs/{wd}/hymns.json'
        if os.path.exists(hj):
            row = next((h for h in json.loads(open(hj).read())
                        if h['name'].rstrip('_') == f't{num}'), None)
            if row:
                try:
                    from hymn_align import load_units
                    from score_degrees import leading_anchor
                    us, _ = load_units(row['p0'], 0, row['p0'], 10 ** 6)
                    g0 = next((i for i, u in enumerate(us)
                               if u['pl'][1] >= row['l0']), 0)
                    anchor = leading_anchor(row['p0'], g0)
                except Exception:
                    anchor = None
    if anchor is None:
        # Named mode-workdir pieces (mode1-kyrie-ekekraxa, ...-par) match
        # neither the span path nor -tNN: resolve the anchor from the piece's
        # own source row — the '-par' pieces anchor on the PARALLAGI's range.
        s = D.get('meta', {}).get('source') or {}
        if s.get('workdir') and s.get('hymn'):
            hy = s['hymn']
            base = hy[:-4] if hy.endswith('-par') else hy
            hj = os.path.join(s['workdir'], 'hymns.json')
            if os.path.exists(hj):
                row = next((h for h in json.loads(open(hj).read())
                            if h['name'] in (hy, base)), None)
                if row:
                    rng = (row.get('par_score') or row) if hy.endswith('-par') \
                        else row
                    try:
                        from score_degrees import leading_anchor
                        anchor = leading_anchor(rng['p0'], rng.get('g0') or 0)
                    except Exception:
                        anchor = None
                    if anchor is None:
                        # No printed opening martyria (katefthynthito starts
                        # mid-column): let degree_stream find the first
                        # MID-STREAM martyria and walk its value back to what
                        # the opening must have been.
                        try:
                            from hymn_align import load_units_h
                            from score_degrees import degree_stream, \
                                leading_anchor
                            pr = dict(row)
                            pr.update({k: rng[k] for k in
                                       ('p0', 'l0', 'g0', 'p1', 'l1', 'g1')
                                       if rng.get(k) is not None})
                            us, _ = load_units_h(pr)

                            def _iv(u):
                                v = u.get('iv')
                                if v is None:
                                    v = keys.get(u['key'],
                                                 keys.get('%s|' % u['base'], 0)) or 0
                                return v

                            def _walk(stream, start=None):
                                # unfiltered per-unit degrees (degree_stream
                                # drops Nones and loses unit alignment)
                                dv, o = start, []
                                for u in stream:
                                    if u.get('mart_deg') is not None:
                                        dv = u['mart_deg']
                                    elif dv is not None:
                                        dv += _iv(u)
                                    o.append(dv)
                                return o
                            ds = _walk(us)
                            j = next((i for i, v in enumerate(ds)
                                      if v is not None), None)
                            def _backwalk(stream, dstream, upto):
                                back = dstream[upto]
                                for k in range(upto, -1, -1):
                                    back -= _iv(stream[k])
                                return back
                            if j is not None and len(us) == len(notes):
                                anchor = _backwalk(us, ds, j)
                            elif hy.endswith('-par'):
                                # an abbreviated parallagi (a cadence formula)
                                # can hold no martyria at all: anchor it from
                                # the FULL hymn's stream at the par range's
                                # first unit
                                fus, _ = load_units_h(row)
                                fds = _walk(fus)
                                ident = lambda x: (x['pl'][0], x['pl'][1],
                                                   round(x['x0'], 1))
                                fids = [ident(x) for x in fus]
                                if us and ident(us[0]) in fids:
                                    i0 = fids.index(ident(us[0]))
                                    v = fds[i0]
                                    if v is None:
                                        jj = next((i for i, x in enumerate(fds)
                                                   if x is not None), None)
                                        base0 = None
                                        if jj is not None:
                                            base0 = _backwalk(fus, fds, jj)
                                        else:
                                            # the whole versicle prints no
                                            # martyria: its opening anchor is
                                            # the previous hymn's right-aligned
                                            # one, which leading_anchor finds
                                            base0 = leading_anchor(
                                                row['p0'], row.get('g0') or 0)
                                        if base0 is not None:
                                            v = base0
                                            for k in range(0, i0 + 1):
                                                v += _iv(fus[k])
                                    if v is not None:
                                        anchor = v - _iv(us[0])
                        except Exception:
                            anchor = None

    # The opening martyria gives the pitch the hymn starts FROM; the first neume
    # moves from it like any other, and an ison needs no special case because
    # its interval is 0. See score_degrees.degree_stream for the chanter's
    # ruling — taking the anchor discarded the opening neume's own interval.
    # The chanter's own corrections, from /api/parallagi-flag. An ison and an
    # oligon are the SAME BAR in this font, so shape-level extraction cannot
    # tell them apart and a run of bars reads as +1 each when one of them does
    # not move — "glyph 47 is supposed to be di.. its been wrong for a while".
    # A correction is an absolute degree at that glyph, exactly like a martyria:
    # it fixes the note AND everything after it, which is why one tap repairs a
    # whole run.
    fixes = {}
    ff = HERE / 'data' / piece_id / 'parallagi_flags.json'
    if ff.exists():
        try:
            for k, v in (json.loads(ff.read_text()).get('notes') or {}).items():
                c = (v or {}).get('correct')
                if c in DEG_GR:
                    fixes[int(k)] = DEG_GR.index(c)
        except Exception:
            fixes = {}

    deg, out = anchor, []
    for gi, n in enumerate(notes):
        if gi in fixes:
            deg = fixes[gi]
            out.append(deg % 7)
            continue
        if n.get('fthora'):
            deg = n['fthora'][1]          # respelled; see score_degrees
        elif deg is not None:
            # an explicit chanter reading on the note wins over the legend;
            # see score_degrees.degree_stream for why the key cannot carry it
            iv = n.get('iv')
            if iv is None:
                iv = keys.get(n.get('key'), keys.get(f"{n.get('cp')}|"))
            deg = deg + iv if iv is not None else None
        out.append(None if deg is None else deg % 7)
    return {'piece': piece_id, 'anchor': anchor,
            'anchor_name': DEG_GR[anchor % 7] if anchor is not None else None,
            'degrees': out,
            'names': [None if d is None else DEG_GR[d] for d in out],
            'unknown': sum(1 for n in notes
                           if n.get('key') not in keys)}


def read_parallagi_flags(piece_id):
    """The flags on a piece: {piece, flags:[gi], notes:{"<gi>": {...}}}.

    Missing file is not an error — a piece nobody has flagged yet reads as
    empty, which is what the overlay expects on first load.
    """
    f = HERE / 'data' / piece_id / FLAGS_FILE
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            notes = d.get('notes') or {}
            return {'piece': piece_id,
                    'flags': sorted(int(k) for k in notes),
                    'notes': notes}
        except (ValueError, TypeError):
            pass
    return {'piece': piece_id, 'flags': [], 'notes': {}}


_QO = {}


def piece_peaks(pid):
    """Neural onset peaks for a piece's audio, cached beside it.

    The chanter taps onsets by ear (~±100 ms); the quick_onset net localises
    the acoustic attack far tighter, so 'Align to peaks' snaps tapped markers
    onto the nearest detected peak. Same recipe as mode_ident.peaks_and_degrees:
    sigmoid maxima >= 0.5, greedy 18-frame minimum separation.
    """
    d = HERE / 'data' / pid
    wav = d / 'audio.wav'
    if not wav.exists():
        for alt in ('audio.m4a', 'audio.mp3'):
            if (d / alt).exists():
                wav = d / alt
                break
    if not wav.exists():
        return None
    cache = d / 'piece_peaks.json'
    if cache.exists() and cache.stat().st_mtime >= wav.stat().st_mtime:
        return json.load(open(cache))
    # torch lives in the corpus venv, not the service's interpreter — run the
    # detector out of process and read its cache file back
    import subprocess
    script = (
        "import json, sys, numpy as np, torch\n"
        "sys.path.insert(0, %r)\n"
        "import quick_onset as QO\n"
        "net = QO.Net()\n"
        "net.load_state_dict(torch.load(%r, map_location='cpu')); net.eval()\n"
        "y = QO.audio(%r)\n"
        "with torch.inference_mode():\n"
        "    prob = torch.sigmoid(net(torch.from_numpy(QO.features(y))"
        ".unsqueeze(0)))[0].numpy()\n"
        "idx = np.where((prob[1:-1] >= prob[:-2]) & (prob[1:-1] > prob[2:])"
        " & (prob[1:-1] >= 0.5))[0] + 1\n"
        "fr = []\n"
        "for i in idx[np.argsort(-prob[idx])]:\n"
        "    if all(abs(int(i) - j) >= 18 for j in fr): fr.append(int(i))\n"
        "json.dump({'onsets': [round(f * QO.HOP / QO.SR, 3)"
        " for f in sorted(fr)]}, open(%r, 'w'))\n"
    ) % (str(HERE.parent.parent / 'neural'),
         '/mnt/data/chant-corpus/models/quick_onset_s020406_e200.pt',
         str(wav), str(cache))
    r = subprocess.run(['/mnt/data/chant-corpus/venv/bin/python3', '-c', script],
                       capture_output=True, text=True, timeout=240)
    if not cache.exists():
        raise RuntimeError('peak detector failed: ' +
                           (r.stderr or r.stdout)[-200:])
    return json.load(open(cache))


_PREP_JOBS = {}


def prep_par_start(pid):
    """Build the -par piece for a melos piece in the background.

    The chanter cuts a '#par' span in the book, then presses Par♪ in the
    annotator — a one-off batch can never keep up with that, so the piece is
    built on demand: ~1 min of alignment in a subprocess, polled by the page.
    """
    target = HERE / 'data' / (pid + '-par') / 'annotator_data.json'
    if target.exists():
        return {'status': 'ready'}
    dd = HERE / 'data' / pid / 'annotator_data.json'
    if not dd.exists():
        return {'status': 'error', 'error': 'no such piece'}
    s = (json.loads(dd.read_text()).get('meta') or {}).get('source') or {}
    if not s.get('workdir') or not s.get('hymn'):
        return {'status': 'error', 'error': 'piece has no source row'}
    j = _PREP_JOBS.get(pid)
    if j is not None and j.poll() is None:
        return {'status': 'building'}
    if j is not None and j.returncode not in (0, None):
        _PREP_JOBS.pop(pid, None)
        return {'status': 'error', 'error': 'previous build failed (rc %s) — '
                'see prep_par.%s.log' % (j.returncode, pid)}
    log = open(str(HERE / 'data' / ('prep_par.%s.log' % pid)), 'w')
    _PREP_JOBS[pid] = __import__('subprocess').Popen(
        ['/mnt/data/chant-corpus/venv/bin/python3',
         os.path.join(CORPUS_TOOLS, 'prep_par_piece.py'),
         '--workdir', s['workdir'], '--hymn', s['hymn']],
        stdout=log, stderr=log)
    return {'status': 'started'}


_TRANS_JOBS = {}


def transpose_start(pid, st):
    """Render a pitch-shifted copy of a piece's audio, cached beside it.

    The chanter is a baritone; singing along is easier a few semitones up.
    rubberband -p <st> -F shifts pitch with FORMANT PRESERVATION and leaves
    duration untouched, so every onset, tap and highlight stays valid and
    nobody sounds like a chipmunk. Renders take ~10-40 s; background job +
    polling, like prep-par.
    """
    try:
        st = int(st)
    except (TypeError, ValueError):
        return {'status': 'error', 'error': 'bad semitones'}
    if not -12 <= st <= 12:
        return {'status': 'error', 'error': 'semitones out of range'}
    d = HERE / 'data' / pid
    src = d / 'audio.wav'
    if not src.exists():
        return {'status': 'error', 'error': 'no audio.wav for this piece'}
    if st == 0:
        return {'status': 'ready', 'url': f'data/{pid}/audio.wav'}
    out = d / ('audio.st%+d.wav' % st)
    url = f'data/{pid}/{out.name}'
    real = src.resolve()
    if out.exists() and out.stat().st_mtime >= real.stat().st_mtime:
        return {'status': 'ready', 'url': url}
    key = f'{pid}:{st}'
    j = _TRANS_JOBS.get(key)
    if j is not None and j.poll() is None:
        return {'status': 'building'}
    if j is not None and j.returncode not in (0, None) and not out.exists():
        _TRANS_JOBS.pop(key, None)
        return {'status': 'error', 'error': 'render failed (rc %s)' % j.returncode}
    import subprocess
    log = open(str(d / 'transpose.log'), 'a')
    _TRANS_JOBS[key] = subprocess.Popen(
        ['rubberband', '-p', str(st), '-F', str(real), str(out) + '.tmp.wav'],
        stdout=log, stderr=log)
    # a tiny shim renames atomically when done, so a half-rendered file can
    # never be served (today's lesson, thrice over)
    import threading

    def _finish(job=_TRANS_JOBS[key], tmp=str(out) + '.tmp.wav', dst=str(out)):
        job.wait()
        if job.returncode == 0 and os.path.exists(tmp):
            os.replace(tmp, dst)
        elif os.path.exists(tmp):
            os.unlink(tmp)
    threading.Thread(target=_finish, daemon=True).start()
    return {'status': 'started'}


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # HTML must never be heuristically cached: UI fixes ship many times a
        # day and a stale index.html hides them (chanter 2026-08-24: a new
        # toolbar button was invisible until a hard reload).
        p = self.path.split('?')[0]
        if p.endswith('.html') or p.endswith('/') or p == '':
            self.send_header('Cache-Control', 'no-cache')
        elif '/data/' in p and '/audio.' in p:
            # piece audio is rebuilt in place whenever spans change; a browser
            # that fetched mid-write kept a truncated copy TWICE today (dogmatic
            # 3:34/4:43, thou-kyrie a quarter in). Never let it keep one.
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _proxy(self, method):
        """Forward one request to the cutter, streaming the body back.

        Range requests must survive intact or seeking inside a two-hour tape
        breaks, so status and headers are copied rather than regenerated.
        """
        import http.client
        body = b''
        n = int(self.headers.get('Content-Length', 0) or 0)
        if n:
            body = self.rfile.read(n)
        try:
            c = http.client.HTTPConnection(*CUTTER, timeout=300)
            hdrs = {k: v for k, v in self.headers.items()
                    if k.lower() in ('range', 'content-type', 'accept')}
            c.request(method, self.path, body=body or None, headers=hdrs)
            r = c.getresponse()
        except Exception as e:
            self.send_error(502, f'cutter unreachable: {e}')
            return
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ('connection', 'transfer-encoding'):
                continue
            self.send_header(k, v)
        self.end_headers()
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
                break
        c.close()

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query_piece(self):
        """The validated 'piece' query arg, or None (400 already sent)."""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        pid = _piece_arg((q.get('piece') or [''])[0])
        if pid is None:
            self._json({'error': 'bad piece'}, 400)
        return pid

    def do_GET(self):
        route = self.path.split('?')[0]
        if route == '/api/transpose':
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            pid = (q.get('piece') or [''])[0]
            if not PIECE_RE.match(pid):
                return self._json({'error': 'bad piece'}, 400)
            self._json(transpose_start(pid, (q.get('st') or ['0'])[0]))
            return
        if route == '/api/prep-par':
            pid = self._query_piece()
            if pid is not None:
                self._json(prep_par_start(pid))
            return
        if route == '/api/piece-peaks':
            pid = self._query_piece()
            if pid is None:
                return
            try:
                d = piece_peaks(pid)
            except Exception as e:
                return self._json({'error': str(e)[:150]}, 500)
            if d is None:
                return self._json({'error': 'no audio'}, 404)
            self._json(d)
            return
        if route == '/api/parallagi':
            pid = self._query_piece()
            if pid is not None:
                self._json(parallagi_for(pid))
            return
        if route == '/api/parallagi-flags':
            pid = self._query_piece()
            if pid is not None:
                self._json(read_parallagi_flags(pid))
            return
        if _is_cutter(self.path):
            return self._proxy('GET')
        return super().do_GET()

    def do_HEAD(self):
        if _is_cutter(self.path):
            return self._proxy('HEAD')
        return super().do_HEAD()

    exports_dir: Path = HERE / "exports"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".txt": "text/plain; charset=utf-8",
                      ".html": "text/html; charset=utf-8",
                      ".json": "application/json; charset=utf-8"}

    def do_POST(self):
        if self.path.rstrip('/') == '/api/parallagi-flag':
            self.handle_parallagi_flag()
            return
        if _is_cutter(self.path):
            return self._proxy('POST')
        if self.path.rstrip("/") == "/api/clusters":
            self.handle_clusters()
            return
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

    def handle_clusters(self):
        """POST /api/clusters — save the cluster classifier's state
        (classifications + chanter-marked wrong examples + notes) into
        <exports-dir>/clusters/classifications.json with timestamped history,
        same never-destroy pattern as piece exports."""
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError(f"bad content length {n}")
            payload = json.loads(self.rfile.read(n))
            if "classifications" not in payload:
                raise ValueError("missing key: classifications")
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, str(e))
            return
        dest = self.exports_dir / "clusters"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (dest / "history").mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=1)
        (dest / "classifications.json").write_text(text)
        (dest / "history" / f"{stamp}.json").write_text(text)
        body = json.dumps({"ok": True, "dir": str(dest), "stamp": stamp}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.log_message("clusters -> %s (history/%s)", dest, stamp)

    def handle_parallagi_flag(self):
        """POST /api/parallagi-flag — the chanter rejecting one printed degree.

        'shown' is the degree name the overlay had on screen when he tapped, so
        a later legend fix can be scored against what he actually rejected
        rather than against whatever the current legend would print. 'clear'
        removes the flag. Written to data/<piece>/parallagi_flags.json with a
        timestamped history copy, the same never-destroy pattern as exports.
        """
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError(f"bad content length {n}")
            payload = json.loads(self.rfile.read(n))
            piece = _piece_arg(str(payload.get("piece", "")))
            if piece is None:
                raise ValueError(f"bad piece {payload.get('piece')!r}")
            if not (HERE / 'data' / piece).is_dir():
                raise ValueError(f"no such piece {piece}")
            gi = int(payload["gi"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            self.send_error(400, str(e))
            return

        state = read_parallagi_flags(piece)
        notes = state["notes"]
        if payload.get("clear"):
            notes.pop(str(gi), None)
        else:
            # 'correct' is the degree it SHOULD be. Optional — a bare flag
            # still just says "this is wrong" — but when present it is applied
            # as an absolute degree from that glyph on, so one tap repairs the
            # whole run after it. That is what the ison/oligon ambiguity needs:
            # the two are the same bar in this font, so a mis-read one shifts
            # everything downstream and there is no shape evidence to fix it.
            corr = payload.get("correct")
            if corr is not None and corr not in DEG_GR:
                self.send_error(400, f"correct must be one of {DEG_GR}, got {corr!r}")
                return
            notes[str(gi)] = {"gi": gi,
                              "shown": payload.get("shown"),
                              "correct": corr,
                              "note": payload.get("note") or "",
                              "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        state["flags"] = sorted(int(k) for k in notes)

        dest = HERE / 'data' / piece
        stamp = time.strftime("%Y%m%d-%H%M%S")
        hist = dest / "history" / stamp
        hist.mkdir(parents=True, exist_ok=True)
        text = json.dumps(state, ensure_ascii=False, indent=1)
        (dest / FLAGS_FILE).write_text(text, encoding='utf-8')
        (hist / FLAGS_FILE).write_text(text, encoding='utf-8')
        self._json({"ok": True, "piece": piece, "gi": gi, "stamp": stamp,
                    "flags": state["flags"]})
        self.log_message("parallagi-flag %s gi=%s -> %s (history/%s)",
                         piece, gi, dest / FLAGS_FILE, stamp)


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
