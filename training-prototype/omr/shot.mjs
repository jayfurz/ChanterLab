// Headless screenshot helper for the choir-training prototype.
// Usage: node shot.mjs <url> <outPng> [voiceKey] [--play]
// Playwright is vendored in a sibling repo's node_modules for this prototype.
const PW = process.env.PW_PATH || '/mnt/data/code/chanterlab-score-engine/node_modules/playwright/index.js';
const pw = await import(PW);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const url = process.argv[2];
const out = process.argv[3];
const voice = process.argv[4] && !process.argv[4].startsWith('--') ? process.argv[4] : null;
const doPlay = process.argv.includes('--play');

const exe = process.env.PW_CHROMIUM || '/home/justin/bin/chromium';
const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERR ' + e.message));

const pieceArg = process.argv.find((a) => a.startsWith('--piece='));
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
if (pieceArg) {
  const id = pieceArg.split('=')[1];
  await page.selectOption('#pieceSelect', id);
  await page.waitForTimeout(1500);
}
if (voice) { await page.click(`.vbtn:has-text("${voice}")`); await page.waitForTimeout(600); }
if (doPlay) { await page.click('#play'); await page.waitForTimeout(1800); }
const status = await page.textContent('#status').catch(() => '');
await page.screenshot({ path: out, fullPage: true });
console.log('STATUS:', status);
if (errors.length) console.log('JS_ERRORS:\n' + errors.join('\n'));
await browser.close();
