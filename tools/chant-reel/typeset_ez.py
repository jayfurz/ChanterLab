#!/usr/bin/env python3
"""typeset_ez.py — typeset Byzantine notation with the EZ fonts via headless Chrome.

Spec: a list of tokens, each {"k": "<keystrokes>", "red": bool, "dy": px}.
Keystrokes are the EZ Psaltica ASCII keys (cp = 0xF000 + ord(key)); a token's
chars render as one <span> so zero-width marks compose onto the preceding
note.  Red tokens render in the traditional rubric red.  Output: tight-cropped
RGBA PNG at the requested pixel size.

Usage:
  python3 typeset_ez.py --out fig.png --size 64 --spec '[{"k":"1"},{"k":"s","red":true}]'
"""
import argparse
import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import numpy as np
import websocket
from PIL import Image

HERE = Path(__file__).resolve().parent
FONT = HERE.parent.parent / 'docs/references/ByzMusicFonts/Fonts/EZ Psaltica.TTF'
CHROME = Path.home() / '.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell'
RED = '#c41e1e'


def typeset(spec, size=64, port=9341, font=None):
    b64 = base64.b64encode((Path(font) if font else FONT).read_bytes()).decode()
    spans = []
    for tok in spec:
        txt = tok['ch'] if tok.get('ch') else ''.join(chr(0xF000 + ord(c)) for c in tok['k'])
        style = f'color:{RED};' if tok.get('red') else ''
        if tok.get('dy'):
            style += f'position:relative;top:{tok["dy"]}px;'
        spans.append(f'<span style="{style}">{txt}</span>')
    html = ('<meta charset="utf-8"><style>@font-face{font-family:EZ;src:url(data:font/ttf;base64,' + b64 +
            ')} body{background:#f7f2e8;margin:0} '
            f'.ez{{font-family:EZ;font-size:{size}px;white-space:pre;padding:{size}px {size//2}px}}</style>'
            '<div class="ez">' + ''.join(spans) + '</div>')
    tmp = HERE / '_typeset_tmp.html'
    tmp.write_text(html)
    shell = subprocess.Popen([str(CHROME), '--headless', '--disable-gpu', '--no-sandbox',
                              f'--remote-debugging-port={port}', '--remote-allow-origins=*',
                              '--window-size=2200,700', '--hide-scrollbars', 'about:blank'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://localhost:{port}/json'))
                if tabs:
                    break
            except Exception:
                time.sleep(0.2)
        ws = websocket.create_connection(tabs[0]['webSocketDebuggerUrl'], timeout=30)
        mid = [0]

        def send(method, params=None):
            mid[0] += 1
            ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
            while True:
                m = json.loads(ws.recv())
                if m.get('id') == mid[0]:
                    return m.get('result', {})
        send('Page.enable')
        send('Page.navigate', {'url': 'file://' + str(tmp)})
        time.sleep(1.2)
        shot = send('Page.captureScreenshot', {'format': 'png'})
        im = Image.open(__import__('io').BytesIO(base64.b64decode(shot['data']))).convert('RGB')
    finally:
        shell.terminate()
        tmp.unlink(missing_ok=True)
    a = np.asarray(im).astype(int)
    ink = (np.abs(a - np.array([247, 242, 232])).sum(axis=2) > 60)
    ys, xs = np.nonzero(ink)
    if not len(xs):
        raise SystemExit('nothing rendered')
    x0, x1, y0, y1 = xs.min() - 2, xs.max() + 3, ys.min() - 2, ys.max() + 3
    crop = a[y0:y1, x0:x1]
    dist = np.abs(crop - np.array([247, 242, 232])).sum(axis=2)
    alpha = np.clip(dist * 2, 0, 255).astype(np.uint8)
    out = np.dstack([crop.astype(np.uint8), alpha])
    return Image.fromarray(out, 'RGBA')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--size', type=int, default=64)
    ap.add_argument('--spec', required=True, help='JSON token list')
    args = ap.parse_args()
    img = typeset(json.loads(args.spec), args.size)
    img.save(args.out)
    print(f'{args.out}: {img.width}x{img.height}')


def typeset_units(units, size=64, port=9342, font=None):
    """units: list of token-lists (a note's base char + its marks render as one
    <span class=u>).  Returns (RGBA image, [ [x0,y0,x1,y1] per unit ])."""
    spec = []
    for i, unit in enumerate(units):
        merged = {'ch': ''.join(t['ch'] for t in unit), 'unit': True}
        # a unit is red only if ALL its chars are marks; mixed units render
        # per-char via nested spans instead
        spec.append(unit)
    b64 = base64.b64encode((Path(font) if font else FONT).read_bytes()).decode()
    RED_CSS = RED
    inner = []
    for unit in units:
        parts = []
        for tok in unit:
            style = f'color:{RED_CSS};' if tok.get('red') else ''
            if tok.get('dy'):
                style += f'position:relative;top:{tok["dy"]}px;'
            parts.append(f'<span style="{style}">{tok["ch"]}</span>')
        inner.append('<span class="u">' + ''.join(parts) + '</span>')
    html = ('<meta charset="utf-8"><style>@font-face{font-family:EZ;src:url(data:font/ttf;base64,' + b64 +
            ')} body{background:#f7f2e8;margin:0} '
            f'.ez{{font-family:EZ;font-size:{size}px;white-space:pre;padding:{size}px {size//2}px}}</style>'
            '<div class="ez">' + ''.join(inner) + '</div>')
    tmp = HERE / '_typeset_tmp.html'
    tmp.write_text(html)
    shell = subprocess.Popen([str(CHROME), '--headless', '--disable-gpu', '--no-sandbox',
                              f'--remote-debugging-port={port}', '--remote-allow-origins=*',
                              '--window-size=2200,700', '--hide-scrollbars', 'about:blank'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://localhost:{port}/json'))
                if tabs:
                    break
            except Exception:
                time.sleep(0.2)
        ws = websocket.create_connection(tabs[0]['webSocketDebuggerUrl'], timeout=30)
        mid = [0]

        def send(method, params=None):
            mid[0] += 1
            ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
            while True:
                m = json.loads(ws.recv())
                if m.get('id') == mid[0]:
                    return m.get('result', {})
        send('Page.enable')
        send('Runtime.enable')
        send('Page.navigate', {'url': 'file://' + str(tmp)})
        time.sleep(1.2)
        rects = json.loads(send('Runtime.evaluate', {'expression':
            "JSON.stringify([...document.querySelectorAll('.u')].map(s => {"
            "const r = s.getBoundingClientRect(); return [r.x, r.y, r.right, r.bottom];}))"
            })['result']['value'])
        shot = send('Page.captureScreenshot', {'format': 'png'})
        im = Image.open(__import__('io').BytesIO(base64.b64decode(shot['data']))).convert('RGB')
    finally:
        shell.terminate()
        tmp.unlink(missing_ok=True)
    a = np.asarray(im).astype(int)
    ink = (np.abs(a - np.array([247, 242, 232])).sum(axis=2) > 60)
    ys, xs = np.nonzero(ink)
    x0, x1, y0, y1 = xs.min() - 2, xs.max() + 3, ys.min() - 2, ys.max() + 3
    crop = a[y0:y1, x0:x1]
    dist = np.abs(crop - np.array([247, 242, 232])).sum(axis=2)
    alpha = np.clip(dist * 2, 0, 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([crop.astype(np.uint8), alpha]), 'RGBA')
    boxes = [[r[0] - x0, r[1] - y0, r[2] - x0, r[3] - y0] for r in rects]
    return out, boxes
