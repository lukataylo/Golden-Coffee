// Headless smoke test for the live demo dashboard.
//
// Renders dashboard/index.html in demo mode in a real browser, asserts the page
// loads with NO JavaScript errors, the 3D canvas mounts, and the hero chips
// (conversion + £-at-risk) actually populate from synthetic scenes. This is the
// regression guard for "does the demo visibly work" — what unit tests can't cover.
// Resource 404s for backend endpoints (/stream, /music/*) are expected and ignored
// in the no-backend static serve; only real JS errors fail the run.
//
// Usage (serve dashboard/ first, e.g. `python3 -m http.server 8099` in dashboard/):
//   NODE_PATH=$(npm root -g) node scripts/smoke_dashboard.cjs
const { chromium } = require('playwright');

const BASE = process.env.SMOKE_BASE || 'http://127.0.0.1:8099';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  const jsErrors = [];
  page.on('pageerror', e => jsErrors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) jsErrors.push('console: ' + m.text());
  });

  await page.goto(`${BASE}/?demo=1`, { waitUntil: 'load' });
  await page.waitForTimeout(8000); // let the demo run so chips populate

  const state = await page.evaluate(() => ({
    conv: (document.getElementById('chip-conv') || {}).textContent || '',
    risk: (document.getElementById('chip-risk') || {}).textContent || '',
    mood: (document.getElementById('chip-mood') || {}).textContent || '',
    canvas: !!document.querySelector('canvas'),
  }));
  await page.screenshot({ path: process.env.SMOKE_SHOT || '/tmp/dashboard_demo.png' });
  await browser.close();

  const fail = (msg) => { console.error('SMOKE FAIL:', msg); process.exit(1); };
  if (jsErrors.length) fail('JS errors on the page:\n  ' + jsErrors.join('\n  '));
  if (!state.canvas) fail('3D canvas did not mount');
  if (!/%$/.test(state.conv)) fail(`conversion chip did not populate (got "${state.conv}")`);
  if (!/^£\d/.test(state.risk)) fail(`£-at-risk chip did not populate (got "${state.risk}")`);

  console.log('SMOKE OK —', JSON.stringify(state));
})().catch(e => { console.error('SMOKE FATAL', e); process.exit(1); });
