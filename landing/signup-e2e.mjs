// End-to-end test of the Coffee Steve sign-up / user-management flow.
//
// Spins up a REAL local backend (FastAPI, throwaway SQLite), serves the static
// landing dir, drives headless Chrome via the DevTools Protocol through the whole
// onboarding wizard, and asserts:
//   1. completing the 6-step wizard creates an account (POST /auth/signup)
//   2. the success screen appears and a token is stored
//   3. account.html loads the authenticated profile and shows the 5 answers
//   4. sign-out clears the session; account.html then redirects to sign-in
//   5. signing back in with the same credentials works
//   6. a duplicate sign-up surfaces the "already exists" error
//   7. the backend's admin view captured the data
//
// No external deps — Node 22+ global fetch/WebSocket + the repo's .venv python.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync, rmSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';

const ROOT = path.resolve('.');                 // landing/
const REPO = path.resolve('..');                // repo root
const STATIC_PORT = 8766;
const BACKEND_PORT = 8078;
const BACKEND = `http://127.0.0.1:${BACKEND_PORT}`;
const ADMIN_TOKEN = 'e2e-admin-token';
const DB = path.join(os.tmpdir(), `gc-signup-e2e-${process.pid}.db`);
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PY = path.join(REPO, '.venv', 'bin', 'python');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const MIME = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript',
  '.webp':'image/webp', '.png':'image/png', '.json':'application/json', '.svg':'image/svg+xml' };

const fails = [];
const ok = (cond, msg) => { if (cond) console.log('  PASS  ' + msg); else { console.log('  FAIL  ' + msg); fails.push(msg); } };

// unique email per run so reruns don't collide on the persistent admin path
const EMAIL = `e2e+${Date.now()}@hearth.co`;
const PASSWORD = 'roastedbeans1';

// ---- cleanup any stale db ----
for (const ext of ['', '-wal', '-shm']) { try { rmSync(DB + ext, { force: true }); } catch {} }

// ---- 1. backend ----
const backend = spawn(PY, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
  '--port', String(BACKEND_PORT), '--log-level', 'warning'], {
  cwd: REPO,
  env: { ...process.env, GC_USERS_DB: DB, ADMIN_TOKEN, INGEST_TOKEN: '' },
  stdio: 'ignore',
});
let up = false;
for (let i = 0; i < 60; i++) {
  try { const r = await fetch(`${BACKEND}/health`); if (r.ok) { up = true; break; } } catch {}
  await sleep(250);
}
if (!up) { console.error('FAIL: backend did not start'); backend.kill('SIGKILL'); process.exit(2); }

// ---- 2. static server ----
const server = http.createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p === '/') p = '/index.html';
    const fp = path.join(ROOT, p);
    if (!fp.startsWith(ROOT) || !existsSync(fp)) { res.writeHead(404); res.end('404'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(await readFile(fp));
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise(r => server.listen(STATIC_PORT, r));

// ---- 3. chrome ----
const userDir = path.join(os.tmpdir(), 'gc-signup-e2e-profile');
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=9334', `--user-data-dir=${userDir}`,
  '--window-size=1280,2000', 'about:blank'], { stdio: 'ignore' });

let version = null;
for (let i = 0; i < 50; i++) {
  try { version = await (await fetch('http://localhost:9334/json/version')).json(); break; }
  catch { await sleep(200); }
}
if (!version) { console.error('FAIL: chrome devtools not reachable'); cleanup(2); }

function cdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0; const pending = new Map(); const listeners = [];
  const ready = new Promise(res => { ws.onopen = () => res(); });
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) listeners.forEach(fn => fn(msg));
  };
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const m = { id: ++id, method, params }; if (sessionId) m.sessionId = sessionId;
    pending.set(m.id, { resolve, reject }); ws.send(JSON.stringify(m));
  });
  return { ready, send, on: fn => listeners.push(fn), close: () => ws.close() };
}

const browser = cdpClient(version.webSocketDebuggerUrl);
await browser.ready;
const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });
const pageErrors = [];
browser.on(msg => {
  if (msg.sessionId !== sessionId) return;
  if (msg.method === 'Runtime.exceptionThrown') {
    const d = msg.params.exceptionDetails;
    pageErrors.push(d.exception?.description || d.text);
  }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    pageErrors.push('console.error: ' + (msg.params.args || []).map(a => a.value ?? a.description ?? '').join(' '));
  }
});
await browser.send('Runtime.enable', {}, sessionId);
await browser.send('Page.enable', {}, sessionId);

const evald = async (expr) => {
  const r = await browser.send('Runtime.evaluate',
    { expression: expr, returnByValue: true, awaitPromise: true }, sessionId);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'eval error');
  return r.result.value;
};
const nav = async (url) => {
  await browser.send('Page.navigate', { url }, sessionId);
  await sleep(700);
};

// helpers that run inside the page
const setInput = (id, v) => evald(`(()=>{const e=document.getElementById(${JSON.stringify(id)});` +
  `e.value=${JSON.stringify(v)};e.dispatchEvent(new Event('input',{bubbles:true}));return e.value;})()`);
const clickChip = (group, val) => evald(`(()=>{const c=document.querySelector('[data-chips=${JSON.stringify(group)}] .chip[data-val=${JSON.stringify(val)}]');` +
  `if(!c)return 'missing';c.click();return c.classList.contains('sel');})()`);
const clickId = (id) => evald(`(()=>{const e=document.getElementById(${JSON.stringify(id)});if(!e)return false;e.click();return true;})()`);
const clickNext = () => evald(`document.getElementById('btnNext').click(); true`);
const activeStep = () => evald(`(()=>{const a=document.querySelector('.pane.active');return a?a.getAttribute('data-step'):null;})()`);
const waitFor = async (expr, ms = 10000) => {
  const t = Date.now();
  while (Date.now() - t < ms) { try { if (await evald(expr)) return true; } catch {} await sleep(150); }
  return false;
};
const waitStep = (s, ms = 10000) => waitFor(
  `(()=>{const a=document.querySelector('.pane.active');return !!a && a.getAttribute('data-step')===${JSON.stringify(String(s))};})()`, ms);
// click Continue, then wait until the wizard actually lands on the target step
const advanceTo = async (s) => { await clickNext(); return waitStep(s); };

try {
  console.log(`\n== ONBOARDING WIZARD (backend ${BACKEND}) ==`);
  await nav(`http://localhost:${STATIC_PORT}/onboarding.html?backend=${encodeURIComponent(BACKEND)}&email=${encodeURIComponent(EMAIL)}`);
  // wait until gc.js + the wizard IIFE have initialised (not CDN-blocked)
  ok(await waitFor(`typeof window.GC !== 'undefined' && !!document.getElementById('btnNext')`),
    'page initialised (GC + wizard ready, not CDN-blocked)');

  ok(await evald(`document.getElementById('email').value === ${JSON.stringify(EMAIL)}`), 'hero email prefilled from ?email=');
  ok(await activeStep() === '0', 'starts on step 0');

  // step 0 — the 5-question data capture
  await setInput('venueName', 'Hearth & Co');
  ok(await clickChip('business_type', 'Café') === true, 'Q1 business_type selected');
  ok(await clickChip('ambiance', 'Cosy & calm') === true, 'Q2 ambiance selected');
  ok(await clickChip('busiest_period', 'Morning rush') === true, 'Q3 busiest_period selected');
  ok(await clickChip('primary_goal', 'Faster service') === true, 'Q4 primary_goal selected');
  await setInput('covers', '24');

  // try advancing with a missing answer first -> must NOT advance
  await clickNext(); await sleep(700);
  ok(await activeStep() === '0', 'validation blocks advance when postcode missing');
  await setInput('postcode', 'EC1A 1BB');
  ok(await advanceTo('1'), 'advanced to step 1 (camera)');

  // step 1 — camera
  await clickChip('cameraPos', 'Ceiling / overview');
  await clickChip('cameraType', 'USB / webcam');
  ok(await advanceTo('2'), 'advanced to step 2 (devices)');

  // step 2 — devices (toggle one)
  await evald(`(()=>{const sw=document.querySelector('[data-dev="spotify"] .sw');if(sw)sw.click();})()`);
  ok(await advanceTo('3'), 'advanced to step 3 (plan)');

  // step 3 — plan (default autopilot)
  ok(await advanceTo('4'), 'advanced to step 4 (account)');

  // step 4 — account
  await setInput('ownerName', 'Sam Mara');
  // password too short -> blocked
  await setInput('password', 'short');
  await clickId('agree');
  await clickNext(); await sleep(700);
  ok(await activeStep() === '4', 'validation blocks short password');
  await setInput('password', PASSWORD);
  ok(await advanceTo('5'), 'advanced to step 5 (review)');

  // review should reflect captured answers
  const review = await evald(`document.getElementById('reviewBox').textContent`);
  ok(/Cosy & calm/.test(review) && /Morning rush/.test(review) && /Faster service/.test(review),
    'review shows the captured 5-question answers');

  // confirm -> POST /auth/signup -> success screen
  await clickNext();
  let reached = false;
  for (let i = 0; i < 30; i++) { if (await activeStep() === '6') { reached = true; break; } await sleep(300); }
  ok(reached, 'sign-up succeeded — reached success screen');
  ok(await evald(`!!localStorage.getItem('gc_token')`), 'auth token stored after sign-up');

  // ---- account page ----
  console.log('\n== ACCOUNT PAGE ==');
  await nav(`http://localhost:${STATIC_PORT}/account.html?backend=${encodeURIComponent(BACKEND)}`);
  await sleep(1500);
  ok(await evald(`document.getElementById('content').style.display === 'block'`), 'account content rendered (authenticated)');
  const profText = await evald(`document.getElementById('profileBox').textContent`);
  ok(/Café/.test(profText), 'account shows business type');
  ok(/Cosy & calm/.test(profText), 'account shows ambiance');
  ok(/Morning rush/.test(profText), 'account shows busiest period');
  ok(/Faster service/.test(profText), 'account shows primary goal');
  ok(/spotify/.test(profText), 'account shows connected device');
  ok(await evald(`document.getElementById('firstName').textContent === 'Sam'`), 'greets the user by first name');

  // ---- sign out ----
  console.log('\n== SIGN OUT + SIGN IN ==');
  await evald(`document.getElementById('signout').click(); true`);
  await sleep(1500);
  ok(await evald(`location.pathname.endsWith('signin.html')`), 'sign-out redirects to sign-in');
  ok(await evald(`!localStorage.getItem('gc_token')`), 'session cleared on sign-out');

  // ---- sign in again ----
  await nav(`http://localhost:${STATIC_PORT}/signin.html?backend=${encodeURIComponent(BACKEND)}`);
  await sleep(600);
  await setInput('email', EMAIL);
  await setInput('password', PASSWORD);
  await evald(`document.getElementById('signinForm').requestSubmit(); true`);
  let signedIn = false;
  for (let i = 0; i < 30; i++) { if (await evald(`location.pathname.endsWith('account.html')`)) { signedIn = true; break; } await sleep(300); }
  ok(signedIn, 'sign-in with correct credentials lands on account');

  // ---- wrong password on a fresh sign-in ----
  // clear the session first, else signin.html auto-redirects to account
  await evald(`(()=>{try{localStorage.removeItem('gc_token');localStorage.removeItem('gc_user');}catch(e){}})()`);
  await nav(`http://localhost:${STATIC_PORT}/signin.html?backend=${encodeURIComponent(BACKEND)}`);
  await waitFor(`!!document.getElementById('email')`);
  await setInput('email', EMAIL);
  await setInput('password', 'totally-wrong');
  await evald(`document.getElementById('signinForm').requestSubmit(); true`);
  await sleep(1500);
  ok(await evald(`document.getElementById('alert').style.display === 'block'`), 'wrong password shows an error');
  ok(await evald(`location.pathname.endsWith('signin.html')`), 'wrong password keeps you on sign-in');

  // ---- duplicate sign-up surfaces guidance ----
  console.log('\n== DUPLICATE SIGN-UP ==');
  await nav(`http://localhost:${STATIC_PORT}/onboarding.html?backend=${encodeURIComponent(BACKEND)}`);
  await waitFor(`typeof window.GC !== 'undefined' && !!document.getElementById('btnNext')`);
  await setInput('venueName', 'Hearth & Co');
  await clickChip('business_type', 'Café'); await clickChip('ambiance', 'Cosy & calm');
  await clickChip('busiest_period', 'Morning rush'); await clickChip('primary_goal', 'Faster service');
  await setInput('covers', '24'); await setInput('postcode', 'EC1A 1BB');
  await advanceTo('1');
  await clickChip('cameraPos', 'Ceiling / overview'); await clickChip('cameraType', 'USB / webcam');
  await advanceTo('2');                   // -> devices
  await advanceTo('3');                   // -> plan
  await advanceTo('4');                   // -> account
  await setInput('ownerName', 'Sam Mara'); await setInput('email', EMAIL);
  await setInput('password', PASSWORD); await clickId('agree');
  await advanceTo('5');                   // -> review
  await clickNext();                      // submit -> should 409
  const dupErrShown = await waitFor(`/already has an account/i.test(document.getElementById('obError').textContent)`, 8000);
  ok(await activeStep() === '5', 'duplicate sign-up stays on review (not success)');
  const dupErr = await evald(`document.getElementById('obError').textContent`);
  ok(dupErrShown && /already has an account/i.test(dupErr) && /sign in/i.test(dupErr), 'duplicate shows "already exists + sign in" guidance');

  // ---- backend admin captured everything ----
  console.log('\n== BACKEND DATA CAPTURE ==');
  const admin = await (await fetch(`${BACKEND}/admin/signups`, { headers: { 'X-Admin-Token': ADMIN_TOKEN } })).json();
  const mine = admin.signups.find(s => s.email === EMAIL.toLowerCase());
  ok(!!mine, 'admin view contains the captured signup');
  if (mine) {
    ok(mine.profile.ambiance === 'Cosy & calm', 'captured ambiance persisted server-side');
    ok(Array.isArray(mine.profile.devices) && mine.profile.devices.includes('spotify'), 'captured devices persisted as a list');
  }

  ok(pageErrors.length === 0, 'no uncaught page errors during the flow' + (pageErrors.length ? ' — ' + pageErrors.join(' | ') : ''));
} catch (e) {
  console.error('\nE2E EXCEPTION:', e);
  fails.push('exception: ' + e.message);
}

function cleanup(code) {
  try { browser.close(); } catch {}
  try { chrome.kill('SIGTERM'); } catch {}
  try { server.close(); } catch {}
  try { backend.kill('SIGTERM'); } catch {}
  for (const ext of ['', '-wal', '-shm']) { try { rmSync(DB + ext, { force: true }); } catch {} }
  process.exit(code);
}

console.log(`\n=== E2E: ${fails.length === 0 ? 'ALL PASSED' : fails.length + ' FAILURE(S)'} ===`);
cleanup(fails.length ? 1 : 0);
