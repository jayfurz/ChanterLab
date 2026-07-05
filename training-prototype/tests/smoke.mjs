#!/usr/bin/env node
/*
 * ChanterLab — choir-training CI smoke test (GitHub issue #51).
 *
 * Serves the choir-training prototype headlessly and drives the core
 * practice loop: page loads -> a built-in piece parses & renders -> Play
 * advances the cursor -> Stop resets -> switching pieces still works --
 * with zero unexpected console/page errors or failed network requests.
 * Run by .github/workflows/training-smoke.yml on every push/PR to
 * choir-training; also runnable standalone on a dev box (see below).
 *
 * ---------------------------------------------------------------------
 * CAVEAT — only ONE of the "5 built-in" pieces is actually usable in CI.
 * ---------------------------------------------------------------------
 * training-prototype/app.js's PIECES array lists 5 built-in ids: control,
 * trisagion_v, cherubic_v, anaphora_v, trisagion. But training-prototype/
 * .gitignore excludes 4 of their backing MusicXML files (they're vector/OMR
 * extractions of a copyrighted Antiochian Sacred Music Library edition —
 * see omr/SOURCES.md). Only content/control_satb.musicxml is committed.
 * app.js's own loadPieceById() catch block already has a dedicated hint
 * for this exact situation ("score is gitignored (copyrighted source);
 * regenerate via omr/README.md"), so this is a known, intentional state of
 * the repo, not something this test works around by accident.
 *
 * Verified directly: `git archive HEAD | tar -x` into a scratch dir (i.e.
 * exactly what a CI checkout produces) and served that tree — selecting
 * trisagion_v there 404s, and while app.js itself handles the failure
 * gracefully (no thrown/uncaught error), Chromium *also* logs a synthetic
 * "Failed to load resource: ... 404" console error for the network
 * response regardless of whether app code catches it.
 *
 * So: the full ready -> parse -> play -> posOut-advances -> stop
 * assertions always run against `control` (guaranteed present in every
 * environment). For the "switch to a second built-in" assertion, this
 * script *probes first* — a plain HTTP GET, not through the app — for
 * whether a second built-in's MusicXML is actually servable here:
 *   - if yes (local dev box, where the OMR-derived files sit on disk even
 *     though gitignored): do a REAL cross-piece switch and check the new
 *     piece's parsed() differs and is non-trivial.
 *   - if no (CI, fresh checkout): fall back to reselecting `control` via
 *     window.__library.select. This still exercises the whole
 *     stop() -> loadScore() -> buildAudio() switching pipeline end to end;
 *     it just can't prove two *different* scores render, because CI has
 *     no second score to prove it with. That gap is real and documented
 *     here rather than papered over with a broad 404/console-error
 *     allowlist.
 *
 * ---------------------------------------------------------------------
 * Error budget.
 * ---------------------------------------------------------------------
 * The ONE expected non-2xx response in this whole run is
 * training/omr/out/ingest/manifest.json — the gitignored ingested-library
 * manifest that app.js's loadLibraryManifest() unconditionally fetches on
 * startup (and already catches internally). It's 200 if you've run the OMR
 * ingester locally, 404 on a fresh clone/CI; both are fine. Chromium's
 * synthetic "Failed to load resource" console message does NOT include the
 * offending URL, so rather than blanket-ignoring every such message, we
 * reconcile by count: each allow-listed 404 *response* excuses exactly one
 * generic "Failed to load resource" console error. Any extra one (or any
 * other console error, any other bad response, any uncaught page error)
 * fails the run — e.g. if app.js itself ever 404s, that's still caught.
 *
 * ---------------------------------------------------------------------
 * Audio.
 * ---------------------------------------------------------------------
 * CI's headless Chromium has no real audio device. This script never
 * asserts on audible sound — only on window.__training.playState() and
 * the #posOut cursor readout, which are pure Tone.Transport/OSMD state and
 * advance identically whether or not audio actually reaches a speaker.
 * Tone.Transport does need a "started" AudioContext to run its clock at
 * all in a browser, which normally requires a user gesture; passing
 * --autoplay-policy=no-user-gesture-required (the same flag already proven
 * to work headless on this machine by training-prototype/omr/shot.mjs)
 * lets Tone.start() succeed from a plain page.click(), no fake audio
 * device needed. This has been verified against both a live dev server
 * and a git-archive CI simulation (see this repo's issue #51 discussion).
 *
 * ---------------------------------------------------------------------
 * Environment resolution (works both locally and in CI).
 * ---------------------------------------------------------------------
 *   SMOKE_URL      Full URL to training/index.html (or wherever it's
 *                  served). If unset, defaults to the always-on local dev
 *                  instance (http://localhost:8765/training/index.html,
 *                  see the byzorgan-web.service systemd unit). If that
 *                  isn't reachable either, this script spawns its own
 *                  `python3 -m http.server` rooted at the repo root and
 *                  targets training-prototype/index.html *directly* —
 *                  sidestepping the web/training symlink entirely, which
 *                  is the fallback the issue asked for in case a CI
 *                  checkout ever fails to materialize it as a real
 *                  symlink. (In the actual CI workflow, the workflow
 *                  itself starts the server and passes SMOKE_URL in.)
 *   PW_PATH        Path to a Playwright package entry point (index.js) to
 *                  `import()`. Defaults to the local dev box's Playwright
 *                  install; also tries the bare "playwright" specifier
 *                  (resolves via normal node_modules lookup — this is what
 *                  CI's `npm install playwright` provides).
 *   PW_CHROMIUM    Path to a Chromium executable. Defaults to the local
 *                  dev box's `/home/justin/bin/chromium` *if it exists*;
 *                  otherwise no executablePath is passed at all, so
 *                  Playwright uses its own managed browser (what CI's
 *                  `npx playwright install --with-deps chromium` sets up).
 *   SMOKE_SCREENSHOT  Where to save a screenshot on failure. Defaults to
 *                  training-prototype/tests/smoke-failure.png.
 *
 * Exit code 0 on pass, 1 on any failure (all failures are collected and
 * printed together, not just the first one).
 */

import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..', '..'); // training-prototype/tests -> repo root

const DEFAULT_PW_PATH = '/mnt/data/code/chanterlab-score-engine/node_modules/playwright/index.js';
const DEFAULT_PW_CHROMIUM = '/home/justin/bin/chromium';
const DEFAULT_SMOKE_URL = 'http://localhost:8765/training/index.html';

const log = (...a) => console.log('[smoke]', ...a);

// ---- resolve Playwright --------------------------------------------------
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
  return undefined; // let Playwright use its own managed/installed browser
}

// ---- base URL resolution (server reuse / fallback spawn) ----------------
async function urlIsUp(url, timeoutMs = 1500) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  } finally {
    // no-op
  }
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

async function resolveBaseUrl() {
  if (process.env.SMOKE_URL) {
    const url = process.env.SMOKE_URL;
    if (!(await urlIsUp(url))) throw new Error(`SMOKE_URL=${url} is not responding — start the server first`);
    return { url, ownServer: null };
  }
  if (await urlIsUp(DEFAULT_SMOKE_URL)) {
    log(`reusing already-running server at ${DEFAULT_SMOKE_URL}`);
    return { url: DEFAULT_SMOKE_URL, ownServer: null };
  }
  const port = await findFreePort();
  log(`no server found at ${DEFAULT_SMOKE_URL}; spawning python3 -m http.server ${port} ` +
      `(repo root, targeting training-prototype/ directly — bypasses the web/training symlink)`);
  const child = spawn('python3', ['-m', 'http.server', String(port)], {
    cwd: REPO_ROOT,
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  const url = `http://127.0.0.1:${port}/training-prototype/index.html`;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await urlIsUp(url)) return { url, ownServer: child };
    await new Promise((r) => setTimeout(r, 200));
  }
  child.kill();
  throw new Error(`spawned server on port ${port} never came up`);
}

// ---- constants ------------------------------------------------------------
const BUILTIN_IDS = ['control', 'trisagion_v', 'cherubic_v', 'anaphora_v', 'trisagion'];
const BUILTIN_URL_SUFFIX = {
  control: 'content/control_satb.musicxml',
  trisagion_v: 'content/trisagion_vector.musicxml',
  cherubic_v: 'content/cherubic_vector.musicxml',
  anaphora_v: 'content/anaphora_vector.musicxml',
  trisagion: 'content/trisagion_omr.musicxml',
};
// See "Error budget" in the header. Matches whatever base path we're served
// under (training/... or training-prototype/...).
const ALLOWED_FAILING_URL_RE = /omr\/out\/ingest\/manifest\.json(?:$|[?#])/;
const READY_RE = /^Loaded:/;

async function waitReady(page, note) {
  await page.waitForFunction(
    (re) => new RegExp(re).test(document.getElementById('status')?.textContent || ''),
    READY_RE.source,
    { timeout: 15000 }
  ).catch(async () => {
    const status = await page.textContent('#status').catch(() => '(unreadable)');
    fail(`status never reached "Loaded:" ${note} — last status was "${status}"`);
  });
}

const failures = [];
function fail(msg) { failures.push(msg); log('FAIL:', msg); }

async function main() {
  const { url, ownServer } = await resolveBaseUrl();
  const u = new URL(url);
  const origin = u.origin;
  const basePath = u.pathname.replace(/index\.html$/, '');
  log(`target: ${url}`);

  const chromium = await loadPlaywright();
  const executablePath = resolveChromiumExecutable();
  const launchOpts = { args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] };
  if (executablePath) launchOpts.executablePath = executablePath;
  log(`launching chromium${executablePath ? ' (' + executablePath + ')' : ' (playwright-managed)'}`);
  const browser = await chromium.launch(launchOpts);

  const responses = [];
  const consoleErrors = [];
  const pageErrors = [];
  let page = null;

  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    page = await ctx.newPage();
    page.on('response', (r) => responses.push({ url: r.url(), status: r.status() }));
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', (e) => pageErrors.push(e.message));

    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });

    // 1. core hooks present
    await page.waitForFunction(() => !!(window.__training && window.__library), { timeout: 10000 })
      .catch(() => fail('window.__training / window.__library never appeared'));

    // 2. startup piece (PIECES[0] === control) reaches ready
    await waitReady(page, 'on startup');

    // 3. parsed score sanity
    const parsed1 = await page.evaluate(() => window.__training.parsed());
    if (!parsed1) fail('window.__training.parsed() is null after startup load');
    else if (!(parsed1.measureCount > 0)) fail(`parsed().measureCount not > 0 (got ${parsed1.measureCount})`);

    // 4. #pieceSelect (the hidden "headless test" select — see index.html's
    //    comment above it) is populated with all 5 known built-in ids.
    const optionValues = await page.$$eval('#pieceSelect option', (opts) => opts.map((o) => o.value));
    const missingIds = BUILTIN_IDS.filter((id) => !optionValues.includes(id));
    if (missingIds.length) fail(`#pieceSelect missing option(s): ${missingIds.join(', ')}`);

    // 5. Piece switching. Probe (plain HTTP, NOT through the browser/app) for a
    //    second built-in that's actually servable here — see the big header
    //    comment for why this is necessary and honest rather than flaky.
    let altId = null;
    for (const id of BUILTIN_IDS) {
      if (id === 'control') continue;
      const probeUrl = origin + basePath + BUILTIN_URL_SUFFIX[id];
      if (await urlIsUp(probeUrl)) { altId = id; break; }
    }
    if (altId) {
      log(`piece-switch: "${altId}" is servable here — testing a real cross-piece switch via window.__library.select`);
      const switchResult = await page.evaluate((id) => window.__library.select(id), altId);
      if (switchResult == null) fail(`__library.select(${altId}) returned null (unresolved id?)`);
      await waitReady(page, `after switching to ${altId}`);
      const parsed2 = await page.evaluate(() => window.__training.parsed());
      if (!parsed2) fail(`parsed() is null after switching to ${altId}`);
      else if (!(parsed2.measureCount > 0)) fail(`parsed().measureCount not > 0 after switching to ${altId}`);

      // Return to `control` through the OTHER stated mechanism (the native
      // #pieceSelect dropdown) — this is a real value transition (altId ->
      // control) so it genuinely exercises the 'change' listener + reload.
      await page.selectOption('#pieceSelect', 'control');
      await waitReady(page, 'after #pieceSelect -> control');
    } else {
      log('piece-switch: no second built-in MusicXML is servable here (expected in CI — 4 of the 5 ' +
          'built-ins are gitignored copyrighted extractions; see this script\'s header) — reselecting ' +
          '"control" via window.__library.select to at least exercise the switch machinery end-to-end');
      const switchResult = await page.evaluate(() => window.__library.select('control'));
      if (switchResult == null) fail('__library.select(control) returned null');
      await waitReady(page, 'after re-selecting control');
    }

    // 6. Play advances the cursor.
    const stateBefore = await page.evaluate(() => window.__training.playState());
    if (stateBefore !== 'stopped') fail(`expected playState 'stopped' before Play, got '${stateBefore}'`);
    await page.click('#play');
    await page.waitForFunction(() => window.__training.playState() === 'playing', { timeout: 8000 })
      .catch(() => fail('playState never became "playing" within 8s of clicking #play'));
    const posAtStart = await page.textContent('#posOut');
    await page.waitForFunction(
      (start) => document.getElementById('posOut')?.textContent !== start,
      posAtStart,
      { timeout: 8000 }
    ).catch(() => fail(`#posOut never advanced past "${posAtStart}" within 8s of playing`));

    // 7. Stop resets.
    await page.click('#stop');
    await page.waitForFunction(() => window.__training.playState() === 'stopped', { timeout: 5000 })
      .catch(() => fail('playState never returned to "stopped" after clicking #stop'));
    const posAfterStop = (await page.textContent('#posOut') || '').trim();
    if (posAfterStop !== 'm –') fail(`#posOut after Stop expected "m –", got "${posAfterStop}"`);

    // 8. Reconcile network/console errors — see "Error budget" in the header.
    const badResponses = responses.filter((r) => r.status >= 400);
    const allowedBad = badResponses.filter((r) => ALLOWED_FAILING_URL_RE.test(r.url));
    const unexpectedBad = badResponses.filter((r) => !ALLOWED_FAILING_URL_RE.test(r.url));
    if (unexpectedBad.length) {
      fail(`unexpected failed response(s): ${unexpectedBad.map((r) => `${r.status} ${r.url}`).join('; ')}`);
    }
    const genericResourceErrors = consoleErrors.filter((t) => /Failed to load resource/.test(t));
    const otherConsoleErrors = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
    if (otherConsoleErrors.length) fail(`unexpected console error(s): ${otherConsoleErrors.join(' | ')}`);
    if (genericResourceErrors.length > allowedBad.length) {
      fail(`${genericResourceErrors.length} generic "Failed to load resource" console error(s) but only ` +
           `${allowedBad.length} allow-listed 404 response(s) to account for them`);
    }
    if (pageErrors.length) fail(`uncaught page error(s): ${pageErrors.join(' | ')}`);
  } catch (e) {
    fail(`unhandled exception during smoke run: ${e.stack || e.message}`);
  } finally {
    if (failures.length && page) {
      const shotPath = process.env.SMOKE_SCREENSHOT || path.join(__dirname, 'smoke-failure.png');
      try {
        await page.screenshot({ path: shotPath, fullPage: true });
        log(`saved failure screenshot: ${shotPath}`);
      } catch (e2) {
        log(`could not save failure screenshot: ${e2.message}`);
      }
    }
    await browser.close().catch(() => {});
    if (ownServer) ownServer.kill();
  }

  if (failures.length) {
    console.error(`\n[smoke] FAIL (${failures.length}):`);
    failures.forEach((f, i) => console.error(`  ${i + 1}. ${f}`));
    process.exitCode = 1;
  } else {
    log('PASS — load -> ready -> parse -> piece-switch -> play -> posOut advances -> stop, ' +
        'zero unexpected console/page errors or failed requests.');
  }
}

main().catch((e) => {
  console.error('[smoke] FATAL:', e.stack || e);
  process.exitCode = 1;
});
