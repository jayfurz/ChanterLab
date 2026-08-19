#!/usr/bin/env python3
"""serve.py — boundary cutter: mark each hymn's start and end by ear.

Every automatic attempt at this has been measured and found wanting: silence
walks overran into the next hymn, forced-alignment windows smeared the final
melisma, and CTC identification turned out ~20% correct (see
docs/plans/RESEP-IDENTIFICATION.md). The chanter can settle a boundary in
seconds that the pipeline gets wrong in minutes, so this hands him the tape.

Serves the tapes with HTTP Range support -- SimpleHTTPRequestHandler does not,
and without it a browser cannot seek inside a two-hour recording, which is the
one thing a cutter must do.

  GET  /api/tapes           workdirs, tape URL, hymn list, existing bounds
  GET  /tape/<workdir>      the audio, range-enabled
  POST /api/cuts            {workdir, cuts:[{hymn,t0,t1}]} -> cuts_<wd>.json

Writes to /mnt/data/chant-corpus/texts/cuts_<workdir>.json and never touches
hymns.json; adopting is a separate, reviewable step.

Usage:  serve.py [--port 8790] [--bind 0.0.0.0]
"""
import argparse
import glob
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
TEXTS = '/mnt/data/chant-corpus/texts'
WORKDIRS = '/mnt/data/chant-corpus/workdirs'
WD_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
MAX_BODY = 8 * 1024 * 1024
MIME = {'.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}


def tapes():
    out = {}
    for f in sorted(glob.glob(f'{TEXTS}/recut_*.json')):
        wd = os.path.basename(f)[6:-5]
        try:
            rows = json.load(open(f))
        except Exception:
            continue
        tape = rows[0].get('tape') if rows else None
        if not tape or not os.path.exists(tape):
            continue
        cur = {r['hymn']: r.get('cur') for r in rows}
        hj = f'{WORKDIRS}/{wd}/hymns.json'
        if not os.path.exists(hj):
            continue
        saved = {}
        sf = f'{TEXTS}/cuts_{wd}.json'
        if os.path.exists(sf):
            try:
                saved = {c['hymn']: c for c in json.load(open(sf))['cuts']}
            except Exception:
                saved = {}
        hymns = []
        for h in json.load(open(hj)):
            n = h['name']
            s = saved.get(n)
            hymns.append({'name': n, 'cur': cur.get(n),
                          't0': s['t0'] if s else None,
                          't1': s['t1'] if s else None,
                          'page': h.get('p0'), 'line': h.get('l0')})
        out[wd] = {'tape': tape, 'basename': os.path.basename(tape),
                   'hymns': hymns}
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p in ('/', '/index.html'):
            f = os.path.join(HERE, 'index.html')
            return self._send(200, open(f, 'rb').read(),
                              'text/html; charset=utf-8')
        if p == '/api/tapes':
            return self._send(200, json.dumps(tapes(), ensure_ascii=False))
        if p.startswith('/tape/'):
            return self.serve_tape(unquote(p[6:]))
        self._send(404, '{"error":"not found"}')

    def serve_tape(self, wd):
        if not WD_RE.match(wd):
            return self._send(400, '{"error":"bad workdir"}')
        t = tapes().get(wd)
        if not t:
            return self._send(404, '{"error":"unknown workdir"}')
        path = t['tape']
        size = os.path.getsize(path)
        ctype = MIME.get(os.path.splitext(path)[1].lower(),
                         'application/octet-stream')
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng.strip())
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    start = min(int(a), size - 1)
                    if b:
                        end = min(int(b), size - 1)
                else:                       # suffix range: last N bytes
                    start = max(size - int(b or 0), 0)
                code = 206
        if start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        n = end - start + 1
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(n))
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with open(path, 'rb') as fh:
            fh.seek(start)
            left = n
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return          # normal: the browser seeked away
                left -= len(chunk)

    def do_POST(self):
        if self.path.split('?')[0] != '/api/cuts':
            return self._send(404, '{"error":"not found"}')
        try:
            n = int(self.headers.get('Content-Length', 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError('bad length')
            body = json.loads(self.rfile.read(n))
            wd = body.get('workdir', '')
            if not WD_RE.match(wd):
                raise ValueError('bad workdir')
            cuts = []
            for c in body.get('cuts', []):
                t0, t1 = c.get('t0'), c.get('t1')
                if t0 is None or t1 is None:
                    continue
                t0, t1 = float(t0), float(t1)
                if t1 <= t0:
                    raise ValueError(f"{c.get('hymn')}: end is not after start")
                cuts.append({'hymn': str(c['hymn']),
                             't0': round(t0, 3), 't1': round(t1, 3)})
        except Exception as e:
            return self._send(400, json.dumps({'error': str(e)}))
        out = f'{TEXTS}/cuts_{wd}.json'
        payload = {'workdir': wd, 'saved': time.strftime('%Y-%m-%dT%H:%M:%S'),
                   'cuts': cuts}
        # keep a history copy: an accidental empty save must not destroy work
        hd = f'{TEXTS}/cuts_history'
        os.makedirs(hd, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        json.dump(payload, open(f'{hd}/cuts_{wd}_{stamp}.json', 'w'), indent=1)
        json.dump(payload, open(out, 'w'), indent=1)
        self._send(200, json.dumps({'ok': True, 'n': len(cuts), 'path': out}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8790)
    ap.add_argument('--bind', default='0.0.0.0')
    a = ap.parse_args()
    t = tapes()
    print(f'cutter on http://{a.bind}:{a.port}/  ({len(t)} tapes)')
    for wd, v in t.items():
        done = sum(1 for h in v['hymns'] if h['t0'] is not None)
        print(f'  {wd:16s} {len(v["hymns"]):3d} hymns, {done:3d} already cut')
    ThreadingHTTPServer((a.bind, a.port), H).serve_forever()


if __name__ == '__main__':
    main()
