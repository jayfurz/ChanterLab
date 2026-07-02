// Headless screenshot helper for the choir-training prototype.
// Usage: node shot.mjs <url> <outPng> [voiceKey] [--play] [--piece=id]
//        [--w=1400] [--h=1000] [--mobile] [--mic] [--wait=ms] [--click=sel]
//        [--viewport-only]
// --mobile = 390x844 + touch + dpr 3 (iPhone-ish). Use --w=360 for small Android.
// --mic    = grant mic permission with Chromium's fake audio device.
const PW = process.env.PW_PATH || '/mnt/data/code/chanterlab-score-engine/node_modules/playwright/index.js';
const pw = await import(PW);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const url = process.argv[2];
const out = process.argv[3];
const voice = process.argv[4] && !process.argv[4].startsWith('--') ? process.argv[4] : null;
const flag = (n) => process.argv.includes(n);
const opt = (n, d) => {
  const a = process.argv.find((x) => x.startsWith(n + '='));
  return a ? a.split('=')[1] : d;
};

const mobile = flag('--mobile');
const width = Number(opt('--w', mobile ? 390 : 1400));
const height = Number(opt('--h', mobile ? 844 : 1000));

const exe = process.env.PW_CHROMIUM || '/home/justin/bin/chromium';
const args = ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'];
if (flag('--mic')) args.push('--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream');
const browser = await chromium.launch({ executablePath: exe, args });
const ctx = await browser.newContext({
  viewport: { width, height },
  isMobile: mobile,
  hasTouch: mobile,
  deviceScaleFactor: mobile ? 3 : 1,
  permissions: flag('--mic') ? ['microphone'] : [],
});
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERR ' + e.message));

await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
const pieceId = opt('--piece', null);
if (pieceId) { await page.selectOption('#pieceSelect', pieceId); await page.waitForTimeout(1500); }
if (voice) { await page.click(`.vbtn:has-text("${voice}")`); await page.waitForTimeout(600); }
const clickSel = opt('--click', null);
if (clickSel) { await page.click(clickSel); await page.waitForTimeout(800); }
if (flag('--play')) { await page.click('#play'); await page.waitForTimeout(Number(opt('--wait', 1800))); }

// report layout facts useful for the responsive audit
const audit = await page.evaluate(() => {
  const d = document.documentElement;
  const osmd = document.getElementById('osmd');
  const svg = osmd ? osmd.querySelector('svg') : null;
  const b = document.querySelector('.vbtn');
  const r = b ? b.getBoundingClientRect() : null;
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    docScrollW: d.scrollWidth,
    pageOverflowsX: d.scrollWidth > window.innerWidth,
    osmd: osmd ? { w: osmd.clientWidth, scrollW: osmd.scrollWidth, h: osmd.clientHeight } : null,
    svg: svg ? { w: svg.clientWidth, h: svg.clientHeight } : null,
    vbtn: r ? { w: Math.round(r.width), h: Math.round(r.height) } : null,
  };
});
console.log('AUDIT:', JSON.stringify(audit));
const status = await page.textContent('#status').catch(() => '');
await page.screenshot({ path: out, fullPage: !flag('--viewport-only') });
console.log('STATUS:', status);
if (errors.length) console.log('JS_ERRORS:\n' + errors.join('\n'));
await browser.close();
