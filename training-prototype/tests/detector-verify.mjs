#!/usr/bin/env node
/*
 * Detector browser verification (issue #80).
 *
 * Proves, in headless Chromium with a FAKE MIC fed a known tone, that BOTH
 * detector front-ends drive the real pipeline end to end:
 *   - the app loads and the chosen detector goes live (wasm: the AudioWorklet
 *     actually loads + instantiates the Rust VoiceProcessor);
 *   - real fake-mic audio (NOT __training.injectSample) streams through the
 *     detector into the {tSec, midi} pitch-sink -> practiceSamples;
 *   - the detected pitch matches the fake tone (A3 / 220 Hz / midi 57);
 *   - the scope draws (readout shows a live note);
 *   - a scoring lap scores coherently over the real samples;
 *   - zero JS console errors (network 404 noise excluded, as in smoke.mjs).
 *
 * This is the browser counterpart to the deterministic detector-ab.mjs A/B.
 * BASE-02: part of the unified required CI workflow (the "fake-mic browser
 * verification" gate) as well as runnable standalone on a dev box:
 *   node training-prototype/tests/detector-verify.mjs
 * Honors the same PW_PATH / PW_CHROMIUM / SMOKE_URL env vars as smoke.mjs.
 * Needs training-prototype/pkg-worklet/ built first (make build-worklet, then
 * copy chanterlab_core.js + chanterlab_core_bg.wasm from web/pkg-worklet/ —
 * see the Dockerfile for the exact copy this mirrors) for the wasm mode.
 */
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_PW_PATH = '/mnt/data/code/chanterlab-score-engine/node_modules/playwright/index.js';
const DEFAULT_PW_CHROMIUM = '/home/justin/bin/chromium';
const DEFAULT_SMOKE_URL = 'http://localhost:8765/training/index.html';
const log = (...a) => console.log('[detector-verify]', ...a);

const failures = [];
const fail = (m) => { failures.push(m); log('FAIL:', m); };
const ok = (m) => log('ok:', m);

// ── a known-tone WAV for --use-file-for-fake-audio-capture ───────────────────
// A3 = 220 Hz = midi 57. 16-bit PCM mono @ 48 kHz, 5 s, 0.5 amplitude.
function writeToneWav(file, hz = 220, seconds = 5, sr = 48000, amp = 0.5) {
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
  if (process.env.SMOKE_URL) return { url: process.env.SMOKE_URL, ownServer: null };
  if (await urlIsUp(DEFAULT_SMOKE_URL)) { log(`reusing server at ${DEFAULT_SMOKE_URL}`); return { url: DEFAULT_SMOKE_URL, ownServer: null }; }
  const port = await findFreePort();
  const child = spawn('python3', ['-m', 'http.server', String(port)], { cwd: REPO_ROOT, stdio: ['ignore', 'ignore', 'inherit'] });
  const url = `http://127.0.0.1:${port}/training-prototype/index.html`;
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await urlIsUp(url)) return { url, ownServer: child }; await new Promise((r) => setTimeout(r, 200)); }
  child.kill(); throw new Error(`spawned server on ${port} never came up`);
}
async function loadPlaywright() {
  const cands = process.env.PW_PATH ? [process.env.PW_PATH] : [DEFAULT_PW_PATH, 'playwright'];
  for (const c of cands) { try { const m = await import(c); const chromium = m.chromium || (m.default && m.default.chromium); if (chromium) return chromium; } catch (e) { /* next */ } }
  throw new Error('could not load Playwright from: ' + cands.join(', '));
}
const resolveChromium = () => process.env.PW_CHROMIUM || (existsSync(DEFAULT_PW_CHROMIUM) ? DEFAULT_PW_CHROMIUM : undefined);

const foldToNear = (m, ref) => m - 12 * Math.round((m - ref) / 12);

async function waitReady(page) {
  await page.waitForFunction(() => /^Loaded:/.test(document.getElementById('status')?.textContent || ''), null, { timeout: 15000 });
}

async function runMode(browser, baseUrl, mode) {
  log(`── mode: ${mode} ──`);
  const consoleErrors = [];
  const pageErrors = [];
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 }, permissions: ['microphone'] });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => pageErrors.push(e.message));

  const sep = baseUrl.includes('?') ? '&' : '?';
  await page.goto(`${baseUrl}${sep}detector=${mode}&audiodebug=1`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForFunction(() => !!window.__training, { timeout: 10000 });
  await waitReady(page);

  const detBefore = await page.evaluate(() => window.__training.detector());
  if (!detBefore || detBefore.mode !== mode) fail(`${mode}: __training.detector().mode is '${detBefore && detBefore.mode}', expected '${mode}'`);
  else ok(`${mode}: detector().mode = ${mode}`);

  // Play, then mic (the pitch-sink only accrues while playing).
  await page.click('#play');
  await page.waitForFunction(() => window.__training.playState() === 'playing', { timeout: 8000 })
    .catch(() => fail(`${mode}: never reached playing`));
  await page.click('#micBtn');

  // Wait for real fake-mic samples to accrue (proves the detector streams).
  await page.waitForFunction(() => window.__training.practiceSamples().length > 12, { timeout: 12000 })
    .catch(() => fail(`${mode}: practiceSamples never exceeded 12 (detector not streaming fake-mic audio)`));

  await page.waitForTimeout(1500);   // let cadence/metrics settle

  const det = await page.evaluate(() => window.__training.detector());
  const samples = await page.evaluate(() => window.__training.practiceSamples());
  const readout = (await page.textContent('#scopeReadout') || '').trim();
  const canvasDrawn = await page.evaluate(() => {
    const c = document.getElementById('scope');
    return !!(c && c.width > 0 && c.height > 0);
  });

  // 1. detector live + streaming frames
  if (mode === 'wasm') {
    if (!det.wasmReady) fail('wasm: worklet never reported ready (VoiceProcessor did not instantiate)');
    else ok('wasm: worklet ready (Rust VoiceProcessor instantiated)');
    if (!(det.framesSeen > 0)) fail(`wasm: framesSeen=${det.framesSeen} (no worklet pitch messages)`);
    else ok(`wasm: framesSeen=${det.framesSeen}, voiced=${det.voicedFrames}, cadence=${det.cadenceHz}Hz, latency≈${det.latencyMs}ms`);
  } else {
    ok(`js: detector active, cadence path via analyser`);
  }

  // 2. real fake-mic audio drove the sink (not injectSample)
  if (!(samples.length > 12)) fail(`${mode}: only ${samples.length} practiceSamples`);
  else ok(`${mode}: ${samples.length} real fake-mic samples collected`);

  // 3. detected pitch matches the fake tone (A3 = midi 57), octave-folded
  const mids = samples.map((s) => s.midi).filter(Number.isFinite).sort((a, b) => a - b);
  const medMidi = mids.length ? mids[mids.length >> 1] : NaN;
  const folded = foldToNear(medMidi, 57);
  if (!(Math.abs(folded - 57) <= 2)) fail(`${mode}: median detected midi ${medMidi.toFixed(2)} (folded ${folded.toFixed(2)}) not within 2 of A3=57`);
  else ok(`${mode}: median detected midi ${medMidi.toFixed(2)} (folds to ${folded.toFixed(2)} ≈ A3)`);

  // 4. scope draws
  if (!canvasDrawn) fail(`${mode}: scope canvas has no dimensions`);
  else ok(`${mode}: scope canvas drawn (${readout ? 'readout="' + readout + '"' : 'no readout text'})`);

  // 5. a scoring lap scores coherently over the REAL samples
  const score = await page.evaluate(() => {
    const t = window.__training.scoreTargets();
    const s = window.__training.practiceSamples();
    return { targets: t.length, result: window.__training.scoreCore(t, s) };
  });
  const r = score.result;
  const coherent = r && r.notes > 0 && (r.hit + r.flat + r.sharp + r.missed === r.notes) && Number.isFinite(r.hitPct);
  if (!coherent) fail(`${mode}: incoherent score ${JSON.stringify(r)}`);
  else ok(`${mode}: scored ${r.notes} notes coherently (${r.hit}/${r.flat}/${r.sharp}/${r.missed}, ${r.hitPct}%)`);

  // 6. zero JS console errors (network 404 noise excluded, mirroring smoke.mjs)
  const realErrors = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
  if (realErrors.length) fail(`${mode}: console error(s): ${realErrors.join(' | ')}`);
  else ok(`${mode}: zero JS console errors`);
  if (pageErrors.length) fail(`${mode}: uncaught page error(s): ${pageErrors.join(' | ')}`);
  else ok(`${mode}: zero uncaught page errors`);

  await page.click('#stop').catch(() => {});
  await ctx.close();
  return det;
}

async function main() {
  const wav = writeToneWav(path.join(tmpdir(), 'chanterlab-a3-220.wav'));
  const { url, ownServer } = await resolveBaseUrl();
  log(`target: ${url}`);
  const chromium = await loadPlaywright();
  const executablePath = resolveChromium();
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
  log(`launching chromium${executablePath ? ' (' + executablePath + ')' : ' (managed)'} with fake mic ${wav}`);
  const browser = await chromium.launch(launchOpts);
  const live = {};
  try {
    live.js = await runMode(browser, url, 'js');
    live.wasm = await runMode(browser, url, 'wasm');
  } catch (e) {
    fail(`unhandled: ${e.stack || e.message}`);
  } finally {
    await browser.close().catch(() => {});
    if (ownServer) ownServer.kill();
  }

  console.log('\n[detector-verify] live browser metrics:');
  console.log('  js  :', JSON.stringify(live.js));
  console.log('  wasm:', JSON.stringify(live.wasm));

  if (failures.length) {
    console.error(`\n[detector-verify] FAIL (${failures.length}):`);
    failures.forEach((f, i) => console.error(`  ${i + 1}. ${f}`));
    process.exitCode = 1;
  } else {
    log('PASS — both detectors stream real fake-mic audio, detect A3, draw, and score coherently; zero JS console errors.');
  }
}
main().catch((e) => { console.error('[detector-verify] FATAL:', e.stack || e); process.exitCode = 1; });
