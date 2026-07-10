#!/usr/bin/env node
/*
 * ChanterLab — BASE-02 unified browser gate.
 *
 * Runs the full practice-UI flow TWICE — once at a desktop viewport, once at
 * a phone viewport — against a fresh checkout, and fails on any unexpected
 * console/page/network error. This is deliberately broader than smoke.mjs
 * (which stays the fast per-push sanity check): load, library search +
 * select, voice switch, play/stop, a real loop wrap, and a real scoring lap
 * driven by fake-mic audio (proving the #scope canvas actually draws, with a
 * genuine per-pixel check, not just a dimension check).
 *
 * Both viewport runs share ONE Chromium instance launched with fake-mic
 * flags (same technique as detector-verify.mjs) so the mic-driven scoring
 * step works identically at both sizes without a second browser launch.
 *
 * Env vars: same SMOKE_URL / PW_PATH / PW_CHROMIUM resolution as smoke.mjs.
 * Exit code 0 on pass, 1 on any failure (all failures collected, not just
 * the first).
 */
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..', '..');

const DEFAULT_PW_PATH = '/mnt/data/code/chanterlab-score-engine/node_modules/playwright/index.js';
const DEFAULT_PW_CHROMIUM = '/home/justin/bin/chromium';
const DEFAULT_SMOKE_URL = 'http://localhost:8765/training/index.html';

const log = (...a) => console.log('[browser-gate]', ...a);

// ── fake-mic tone (same helper as detector-verify.mjs) ────────────────────
function writeToneWav(file, hz = 220, seconds = 6, sr = 48000, amp = 0.5) {
  const n = seconds * sr;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVE', 8);
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    const s = Math.round(amp * 32767 * Math.sin(2 * Math.PI * hz * i / sr));
    buf.writeInt16LE(s, 44 + i * 2);
  }
  writeFileSync(file, buf);
  return file;
}

// ── env resolution (mirrors smoke.mjs) ─────────────────────────────────────
async function loadPlaywright() {
  const candidates = process.env.PW_PATH ? [process.env.PW_PATH] : [DEFAULT_PW_PATH, 'playwright'];
  let lastErr;
  for (const c of candidates) {
    try {
      const mod = await import(c);
      const chromium = mod.chromium || (mod.default && mod.default.chromium);
      if (chromium) return chromium;
    } catch (e) { lastErr = e; }
  }
  throw new Error(`could not load Playwright from any of: ${candidates.join(', ')}\n${lastErr && (lastErr.stack || lastErr.message)}`);
}
function resolveChromiumExecutable() {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  if (existsSync(DEFAULT_PW_CHROMIUM)) return DEFAULT_PW_CHROMIUM;
  return undefined;
}
async function urlIsUp(url, timeoutMs = 1500) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch { return false; }
}
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
    srv.on('error', reject);
  });
}
async function resolveBaseUrl() {
  if (process.env.SMOKE_URL) {
    const url = process.env.SMOKE_URL;
    if (!(await urlIsUp(url))) throw new Error(`SMOKE_URL=${url} is not responding — start the server first`);
    return { url, ownServer: null };
  }
  if (await urlIsUp(DEFAULT_SMOKE_URL)) return { url: DEFAULT_SMOKE_URL, ownServer: null };
  const port = await findFreePort();
  const child = spawn('python3', ['-m', 'http.server', String(port)], { cwd: REPO_ROOT, stdio: ['ignore', 'ignore', 'inherit'] });
  const url = `http://127.0.0.1:${port}/training-prototype/index.html`;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await urlIsUp(url)) return { url, ownServer: child }; await new Promise((r) => setTimeout(r, 200)); }
  child.kill(); throw new Error(`spawned server on ${port} never came up`);
}

const READY_RE = /^Loaded:/;
async function waitReady(page, note, fail) {
  await page.waitForFunction(
    (re) => new RegExp(re).test(document.getElementById('status')?.textContent || ''),
    READY_RE.source,
    { timeout: 15000 }
  ).catch(async () => {
    const status = await page.textContent('#status').catch(() => '(unreadable)');
    fail(`status never reached "Loaded:" ${note} — last status was "${status}"`);
  });
}

const VIEWPORTS = [
  { name: 'desktop', width: 1400, height: 900, expectDevice: 'desktop' },
  // isMobile/hasTouch matter here, not just a narrow viewport: without them
  // Chromium doesn't honor a mobile layout width, so matchMedia(max-width)
  // still reads a wide desktop layout even at width:390 (same fix already
  // proven by omr/shot.mjs's --mobile flag).
  { name: 'phone', width: 390, height: 844, expectDevice: 'mobile', isMobile: true, hasTouch: true, deviceScaleFactor: 3 },
];
const ALLOWED_FAILING_URL_RE = /omr\/out\/ingest\/manifest\.json(?:$|[?#])/;

async function runViewport(browser, url, vp) {
  const failures = [];
  const fail = (msg) => { failures.push(msg); log(`FAIL [${vp.name}]:`, msg); };
  const responses = [];
  const consoleErrors = [];
  const pageErrors = [];

  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    permissions: ['microphone'],
    ...(vp.isMobile ? { isMobile: true, hasTouch: !!vp.hasTouch, deviceScaleFactor: vp.deviceScaleFactor || 1 } : {}),
  });
  const page = await ctx.newPage();
  page.on('response', (r) => responses.push({ url: r.url(), status: r.status() }));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => pageErrors.push(e.message));

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });

    // 1. core hooks + ready + parsed sanity
    await page.waitForFunction(() => !!(window.__training && window.__library && window.__tour), { timeout: 10000 })
      .catch(() => fail('window.__training / window.__library / window.__tour never appeared'));
    await waitReady(page, 'on startup', fail);
    const parsed1 = await page.evaluate(() => window.__training.parsed());
    if (!parsed1) fail('parsed() is null after startup load');
    else if (!(parsed1.measureCount > 0)) fail(`parsed().measureCount not > 0 (got ${parsed1.measureCount})`);

    // device breakpoint sanity. NOTE: __tour.device() is only computed inside
    // startTour() (js/tour.js), so it's stale until a test actually starts
    // the tour (see smoke.mjs for that path) — check the same matchMedia
    // query directly here instead of depending on tour-module state.
    const isMobileLayout = await page.evaluate(() => window.matchMedia('(max-width:759px)').matches);
    const device = isMobileLayout ? 'mobile' : 'desktop';
    if (device !== vp.expectDevice) fail(`matchMedia(max-width:759px) implies '${device}' at ${vp.width}px, expected '${vp.expectDevice}'`);

    // Mobile groups Practice/Sound/More into tabs behind a collapsible
    // #expandHandle (desktop stacks all three panes visibly, no tabs — see
    // js/tour.js's own comment on #paneStrip being display:none there).
    // A piece reload (e.g. via the library) can re-collapse the transport,
    // so this re-checks live state on every call rather than once up front.
    const showPane = async (name) => {
      const tabbed = await page.evaluate(() => {
        const ps = document.getElementById('paneStrip');
        return !!ps && getComputedStyle(ps).display !== 'none';
      });
      if (!tabbed) return;
      const expanded = await page.evaluate(() => document.getElementById('expandHandle')?.getAttribute('aria-expanded') === 'true');
      if (!expanded) await page.click('#expandHandle');
      await page.click(`[data-pane="${name}"]`);
    };

    // 2. nonblank SCORE check — OSMD renders #osmd as an SVG, not a canvas;
    //    "nonblank" here means real drawable vector content, not just a
    //    nonzero bounding box.
    const scoreDrawn = await page.evaluate(() => {
      const svg = document.querySelector('#osmd svg');
      if (!svg) return { ok: false, reason: 'no svg' };
      const box = svg.getBoundingClientRect();
      const marks = svg.querySelectorAll('path, rect, g > g').length;
      return { ok: box.width > 0 && box.height > 0 && marks > 0, box: { w: box.width, h: box.height }, marks };
    });
    if (!scoreDrawn.ok) fail(`#osmd svg not drawn: ${JSON.stringify(scoreDrawn)}`);

    // 3. LIBRARY: open, search for both committed fixtures, select 'control'
    //    (a real click through the .lib-row -> loadPieceById path, not
    //    __library.select — smoke.mjs already covers the JS-API path).
    await showPane('more');
    await page.click('#libraryBtn');
    await page.waitForFunction(() => !document.getElementById('libraryOverlay')?.hidden, { timeout: 5000 })
      .catch(() => fail('library overlay never opened'));
    await page.fill('#libSearch', 'control');
    await page.waitForTimeout(250); // libSearchTimer debounce (120ms) + render
    const rowIds = await page.$$eval('.lib-row', (rows) => rows.map((r) => r.dataset.id));
    if (!rowIds.includes('control')) fail(`library search "control" did not surface the 'control' row (got ${JSON.stringify(rowIds)})`);
    if (!rowIds.includes('control2')) fail(`library search "control" did not surface the 'control2' row (got ${JSON.stringify(rowIds)})`);
    const controlRow = await page.$('.lib-row[data-id="control"]');
    if (controlRow) await controlRow.click();
    else { fail('.lib-row[data-id="control"] not clickable'); await page.click('#libClose').catch(() => {}); }
    await page.waitForFunction(() => document.getElementById('libraryOverlay')?.hidden, { timeout: 5000 })
      .catch(() => fail('library overlay never closed after selecting a row'));
    await waitReady(page, 'after library row select', fail);

    // 4. VOICE: control_satb is 4-part (S/A/T/B) -> #voicePicker has 4 .vbtn.
    await showPane('practice');
    const voiceLabelsBefore = await page.$$eval('#voicePicker .vbtn', (b) => b.map((x) => ({ text: x.textContent, active: x.classList.contains('active') })));
    if (voiceLabelsBefore.length < 2) {
      fail(`#voicePicker has < 2 .vbtn (got ${voiceLabelsBefore.length}) — cannot exercise voice switch`);
    } else {
      const buttons = await page.$$('#voicePicker .vbtn');
      await buttons[1].click();
      const afterSwitch = await page.$$eval('#voicePicker .vbtn', (b) => b.map((x) => x.classList.contains('active')));
      if (!afterSwitch[1] || afterSwitch[0]) fail(`voice switch: expected button[1] active/button[0] inactive, got ${JSON.stringify(afterSwitch)}`);
      const chipAfter = (await page.textContent('#voiceChip') || '').trim();
      if (chipAfter === '' ) fail('#voiceChip empty after voice switch');
      await buttons[0].click(); // restore Soprano for the steps below
    }

    // 5. LOOP: loop measures 1..2, play, and prove it actually WRAPS back to
    //    measure 1 instead of continuing past measure 2 — a real loop, not
    //    just "the checkbox is checked".
    await showPane('practice');
    await page.fill('#loopFrom', '1');
    await page.fill('#loopTo', '2');
    const loopCheckbox = await page.$('#loopOn');
    const loopWasOn = await page.evaluate((el) => el.checked, loopCheckbox);
    if (!loopWasOn) await loopCheckbox.click();
    await page.click('#play');
    await page.waitForFunction(() => window.__training.playState() === 'playing', { timeout: 8000 })
      .catch(() => fail('loop test: playState never became "playing"'));
    const parseMeasure = (t) => { const m = /^m (\d+)/.exec((t || '').trim()); return m ? Number(m[1]) : null; };
    let reachedTo = false, wrapped = false;
    const loopDeadline = Date.now() + 15000;
    let lastMeasure = null;
    while (Date.now() < loopDeadline && !wrapped) {
      const text = await page.textContent('#posOut').catch(() => null);
      const measure = parseMeasure(text);
      if (measure != null) {
        if (measure >= 2) reachedTo = true;
        if (reachedTo && lastMeasure != null && measure < lastMeasure) wrapped = true;
        lastMeasure = measure;
      }
      if (!wrapped) await page.waitForTimeout(150);
    }
    if (!reachedTo) fail('loop test: #posOut never reached measure 2');
    else if (!wrapped) fail('loop test: #posOut reached measure 2 but never wrapped back to measure 1 within 15s — loop did not engage');
    // startPlayback() auto-collapses the transport on mobile (setOverlay(false)
    // — a "focus while playing" UX, harmless on desktop where CSS keeps panes
    // stacked regardless) — re-show before the next pane-scoped click.
    await showPane('practice');
    await loopCheckbox.click(); // turn loop back off
    await page.click('#stop');
    await page.waitForFunction(() => window.__training.playState() === 'stopped', { timeout: 5000 })
      .catch(() => fail('loop test: playState never returned to "stopped"'));

    // 6. SCORING + SCOPE: real fake-mic audio (not injectSample) drives both
    //    a genuine scoring lap AND proves the #scope canvas actually draws,
    //    via a real per-pixel check (not just nonzero width/height).
    await page.click('#play');
    await page.waitForFunction(() => window.__training.playState() === 'playing', { timeout: 8000 })
      .catch(() => fail('scoring test: playState never became "playing"'));
    // #micBtn lives in the Sound pane; Play just auto-collapsed the transport
    // on mobile (see the loop step's comment above), so (re-)show it now.
    await showPane('sound');
    await page.click('#micBtn');
    await page.waitForFunction(() => window.__training.practiceSamples().length > 8, { timeout: 12000 })
      .catch(() => fail('scoring test: practiceSamples never exceeded 8 (fake-mic not streaming)'));
    await page.waitForTimeout(500);

    const scopePixels = await page.evaluate(() => {
      const c = document.getElementById('scope');
      if (!c || !c.width || !c.height) return { ok: false, reason: 'no canvas dims' };
      const ctx = c.getContext('2d');
      const { data } = ctx.getImageData(0, 0, c.width, c.height);
      const bg = [data[0], data[1], data[2], data[3]];
      let differing = 0;
      const stride = 4 * 37; // coarse stride, plenty fast, plenty of coverage
      for (let i = 0; i < data.length; i += stride) {
        if (Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]) + Math.abs(data[i + 3] - bg[3]) > 24) differing++;
      }
      return { ok: differing >= 5, differing, w: c.width, h: c.height };
    });
    if (!scopePixels.ok) fail(`#scope canvas not drawn (nonblank pixel check failed): ${JSON.stringify(scopePixels)}`);

    await page.click('#micBtn').catch(() => {}); // mic off before stop
    await page.click('#stop');
    await page.waitForFunction(() => window.__training.playState() === 'stopped', { timeout: 5000 })
      .catch(() => fail('scoring test: playState never returned to "stopped"'));

    const reportVisible = await page.evaluate(() => !document.getElementById('scoreReport')?.hidden);
    if (!reportVisible) fail('#scoreReport did not become visible after a played+mic\'d lap');
    else {
      const totals = (await page.textContent('#scoreReportTotals') || '').trim();
      if (!totals) fail('#scoreReportTotals is empty after a scored lap');
      await page.click('#scoreReportClose').catch(() => {});
    }

    // 7. error budget — same reconciliation as smoke.mjs.
    const badResponses = responses.filter((r) => r.status >= 400);
    const allowedBad = badResponses.filter((r) => ALLOWED_FAILING_URL_RE.test(r.url));
    const unexpectedBad = badResponses.filter((r) => !ALLOWED_FAILING_URL_RE.test(r.url));
    if (unexpectedBad.length) fail(`unexpected failed response(s): ${unexpectedBad.map((r) => `${r.status} ${r.url}`).join('; ')}`);
    const genericResourceErrors = consoleErrors.filter((t) => /Failed to load resource/.test(t));
    const otherConsoleErrors = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
    if (otherConsoleErrors.length) fail(`unexpected console error(s): ${otherConsoleErrors.join(' | ')}`);
    if (genericResourceErrors.length > allowedBad.length) {
      fail(`${genericResourceErrors.length} generic "Failed to load resource" console error(s) but only ${allowedBad.length} allow-listed 404 response(s)`);
    }
    if (pageErrors.length) fail(`uncaught page error(s): ${pageErrors.join(' | ')}`);
  } catch (e) {
    fail(`unhandled exception during ${vp.name} run: ${e.stack || e.message}`);
  } finally {
    if (failures.length) {
      const shotPath = path.join(__dirname, `browser-gate-${vp.name}-failure.png`);
      try { await page.screenshot({ path: shotPath, fullPage: true }); log(`saved failure screenshot: ${shotPath}`); }
      catch (e2) { log(`could not save failure screenshot: ${e2.message}`); }
    }
    await ctx.close().catch(() => {});
  }
  return failures;
}

async function main() {
  const wav = writeToneWav(path.join(tmpdir(), 'chanterlab-browser-gate-a3-220.wav'));
  const { url, ownServer } = await resolveBaseUrl();
  log(`target: ${url}`);
  const chromium = await loadPlaywright();
  const executablePath = resolveChromiumExecutable();
  const launchOpts = {
    args: [
      '--no-sandbox',
      '--autoplay-policy=no-user-gesture-required',
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
      `--use-file-for-fake-audio-capture=${wav}`,
    ],
  };
  if (executablePath) launchOpts.executablePath = executablePath;
  log(`launching chromium${executablePath ? ' (' + executablePath + ')' : ' (playwright-managed)'} with fake mic ${wav}`);
  const browser = await chromium.launch(launchOpts);

  const allFailures = [];
  try {
    for (const vp of VIEWPORTS) {
      log(`── viewport: ${vp.name} (${vp.width}x${vp.height}) ──`);
      const failures = await runViewport(browser, url, vp);
      allFailures.push(...failures.map((f) => `[${vp.name}] ${f}`));
    }
  } finally {
    await browser.close().catch(() => {});
    if (ownServer) ownServer.kill();
  }

  if (allFailures.length) {
    console.error(`\n[browser-gate] FAIL (${allFailures.length}):`);
    allFailures.forEach((f, i) => console.error(`  ${i + 1}. ${f}`));
    process.exitCode = 1;
  } else {
    log('PASS — load, library search+select, voice switch, play/stop, a real loop wrap, and a ' +
        'real fake-mic scoring lap (with nonblank #scope pixels) all held at desktop and phone viewports, ' +
        'zero unexpected console/page errors or failed requests.');
  }
}

main().catch((e) => {
  console.error('[browser-gate] FATAL:', e.stack || e);
  process.exitCode = 1;
});
