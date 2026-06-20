// Non-agentic verification harness for the Golden Coffee static pages.
// Serves the dir over HTTP, drives headless Chrome via the DevTools Protocol,
// and reports console errors / uncaught exceptions / failed requests + screenshots.
// No external deps — uses Node 22+ global fetch & WebSocket.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';

const ROOT = path.resolve('.');
const PORT = 8765;
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PAGES = ['index.html', 'pricing.html', 'onboarding.html', 'terms.html', 'signin.html', 'account.html'];
const MIME = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript',
  '.webp':'image/webp', '.png':'image/png', '.json':'application/json', '.svg':'image/svg+xml' };

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---- static server ----
const server = http.createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p === '/') p = '/index.html';
    const fp = path.join(ROOT, p);
    if (!fp.startsWith(ROOT) || !existsSync(fp)) { res.writeHead(404); res.end('404'); return; }
    const body = await readFile(fp);
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise(r => server.listen(PORT, r));

// ---- launch chrome ----
const userDir = '/tmp/gc-verify-profile';
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=9333', `--user-data-dir=${userDir}`,
  '--window-size=1440,1600', 'about:blank'
], { stdio: 'ignore' });

// wait for devtools endpoint
let version = null;
for (let i = 0; i < 50; i++) {
  try { version = await (await fetch('http://localhost:9333/json/version')).json(); break; }
  catch { await sleep(200); }
}
if (!version) { console.error('FAIL: chrome devtools not reachable'); process.exit(2); }

// ---- minimal CDP client over the browser websocket ----
function cdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const listeners = [];
  const ready = new Promise(res => { ws.onopen = () => res(); });
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      listeners.forEach(fn => fn(msg));
    }
  };
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const m = { id: ++id, method, params }; if (sessionId) m.sessionId = sessionId;
    pending.set(m.id, { resolve, reject }); ws.send(JSON.stringify(m));
  });
  return { ready, send, on: fn => listeners.push(fn), close: () => ws.close() };
}

const browser = cdpClient(version.webSocketDebuggerUrl);
await browser.ready;

const results = [];
for (const page of PAGES) {
  // fresh target per page
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });

  const errors = [], warnings = [], failed = [], badStatus = [];
  browser.on(msg => {
    if (msg.sessionId !== sessionId) return;
    if (msg.method === 'Runtime.consoleAPICalled') {
      const t = msg.params.type;
      const text = (msg.params.args || []).map(a => a.value ?? a.description ?? a.unserializableValue ?? '').join(' ');
      if (t === 'error') errors.push('console.error: ' + text);
      else if (t === 'warning') warnings.push('console.warn: ' + text);
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails;
      errors.push('exception: ' + (d.exception?.description || d.text));
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      errors.push('log: ' + msg.params.entry.text + (msg.params.entry.url ? ' [' + msg.params.entry.url + ']' : ''));
    }
    if (msg.method === 'Network.responseReceived' && msg.params.response.status >= 400) {
      badStatus.push(msg.params.response.status + ' ' + msg.params.response.url);
    }
    if (msg.method === 'Network.loadingFailed') {
      failed.push(msg.params.errorText + ' ' + (msg.params.type || ''));
    }
  });

  await browser.send('Runtime.enable', {}, sessionId);
  await browser.send('Log.enable', {}, sessionId);
  await browser.send('Network.enable', {}, sessionId);
  await browser.send('Page.enable', {}, sessionId);

  await browser.send('Page.navigate', { url: `http://localhost:${PORT}/${page}` }, sessionId);
  // index.html renders via the dc-runtime (React UMD from CDN) — give it longer to settle
  await sleep(page === 'index.html' ? 5000 : 2800);

  // run a tiny DOM assertion in-page
  const probe = {
    'pricing.html': `(${() => {
      const memPrice = document.getElementById('memPrice')?.textContent;
      const kitCards = document.querySelectorAll('.kit-card').length;
      const faqItems = document.querySelectorAll('.faq-item').length;
      const roi = document.getElementById('roiValue')?.textContent;
      const econ = !!document.getElementById('economics');
      const leftover = document.body.innerText.includes('{{'); // visible text only
      return JSON.stringify({ memPrice, kitCards, faqItems, roi, economics: econ, leftoverTemplates: leftover });
    }})()`,
    'onboarding.html': `(${() => {
      const panes = document.querySelectorAll('.pane').length;
      const active = document.querySelectorAll('.pane.active').length;
      const steps = document.querySelectorAll('.step-dot').length;
      const nextBtn = !!document.getElementById('btnNext');
      return JSON.stringify({ panes, activePanes: active, steps, nextBtn });
    }})()`,
    'terms.html': `(${() => {
      const sections = document.querySelectorAll('.legal-body section').length;
      const tocLinks = document.querySelectorAll('#toc a').length;
      return JSON.stringify({ sections, tocLinks });
    }})()`,
    'index.html': `(${() => {
      const hasPricingLink = !!document.querySelector('a[href="pricing.html"]');
      const hasTermsLink = !!document.querySelector('a[href="terms.html"]');
      const hasSignin = !!document.querySelector('a[href="signin.html"]');
      return JSON.stringify({ hasPricingLink, hasTermsLink, hasSignin });
    }})()`,
    'signin.html': `(${() => {
      const form = !!document.getElementById('signinForm');
      const email = !!document.getElementById('email');
      const pw = !!document.getElementById('password');
      const gcApi = typeof (window.GC && window.GC.api) === 'function';
      return JSON.stringify({ form, email, pw, gcApi });
    }})()`,
    'account.html': `(${() => {
      // with no token the page should redirect to signin.html
      const redirected = location.pathname.endsWith('signin.html');
      return JSON.stringify({ redirectedToSignin: redirected });
    }})()`
  }[page];

  let domProbe = null;
  if (probe) {
    try {
      const r = await browser.send('Runtime.evaluate', { expression: probe, returnByValue: true }, sessionId);
      domProbe = JSON.parse(r.result.value);
    } catch (e) { domProbe = { probeError: String(e) }; }
  }

  // screenshot
  try {
    const shot = await browser.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: undefined }, sessionId);
    await (await import('node:fs/promises')).writeFile(`/tmp/gc-${page.replace('.html','')}.png`, Buffer.from(shot.data, 'base64'));
  } catch (e) { /* non-fatal */ }

  results.push({ page, errors, warnings: warnings.slice(0, 5),
    failed: failed.filter(f => !/favicon/.test(f)),
    badStatus: badStatus.filter(s => !/favicon/.test(s)), domProbe });
  await browser.send('Target.closeTarget', { targetId });
}

console.log(JSON.stringify(results, null, 2));

browser.close();
chrome.kill('SIGTERM');
server.close();
const totalErrors = results.reduce((n, r) => n + r.errors.length + r.failed.length, 0);
console.log('\n=== SUMMARY: ' + totalErrors + ' error(s)/failed-request(s) across ' + results.length + ' pages ===');
process.exit(totalErrors > 0 ? 1 : 0);
