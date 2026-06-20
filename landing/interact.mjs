// Interaction verification: drives real clicks/inputs via CDP and asserts state.
// Covers the WHOOP-style membership pricing page and the onboarding wizard
// (validation gating, navigation, plan preselect, and the full signup flow against
// a stub /auth/signup backend served on the same origin).
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';

const ROOT = path.resolve('.');
const PORT = 8766;
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const MIME = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.webp':'image/webp', '.svg':'image/svg+xml', '.json':'application/json' };
const sleep = ms => new Promise(r => setTimeout(r, ms));

// static server + stub backend (POST /auth/signup) on the same origin
const server = http.createServer(async (req, res) => {
  if (req.method === 'POST' && req.url.startsWith('/auth/signup')) {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      let payload = {}; try { payload = JSON.parse(body); } catch {}
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ token: 'test-token', user: { email: payload.email, name: payload.name, plan: payload.plan } }));
    });
    return;
  }
  let p = decodeURIComponent(req.url.split('?')[0]); if (p === '/') p = '/index.html';
  const fp = path.join(ROOT, p);
  if (!fp.startsWith(ROOT) || !existsSync(fp)) { res.writeHead(404); res.end('404'); return; }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
  res.end(await readFile(fp));
});
await new Promise(r => server.listen(PORT, r));
const BK = `&backend=http://localhost:${PORT}`;

const chrome = spawn(CHROME, ['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--remote-debugging-port=9334','--user-data-dir=/tmp/gc-interact-profile','--window-size=1440,1700','about:blank'], { stdio:'ignore' });
let version = null;
for (let i=0;i<50;i++){ try { version = await (await fetch('http://localhost:9334/json/version')).json(); break; } catch { await sleep(200); } }
if(!version){ console.error('chrome not reachable'); process.exit(2); }

function cdp(wsUrl){
  const ws = new WebSocket(wsUrl); let id=0; const pending=new Map(); const ls=[];
  const ready = new Promise(r=>ws.onopen=()=>r());
  ws.onmessage = ev => { const m=JSON.parse(ev.data);
    if(m.id&&pending.has(m.id)){ const {resolve,reject}=pending.get(m.id); pending.delete(m.id); m.error?reject(new Error(m.error.message)):resolve(m.result); }
    else if(m.method) ls.forEach(f=>f(m)); };
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{ const m={id:++id,method,params}; if(sessionId)m.sessionId=sessionId; pending.set(m.id,{resolve,reject}); ws.send(JSON.stringify(m)); });
  return { ready, send, on:f=>ls.push(f), close:()=>ws.close() };
}
const b = cdp(version.webSocketDebuggerUrl); await b.ready;

async function open(url){
  const { targetId } = await b.send('Target.createTarget', { url:'about:blank' });
  const { sessionId } = await b.send('Target.attachToTarget', { targetId, flatten:true });
  await b.send('Page.enable', {}, sessionId);
  await b.send('Runtime.enable', {}, sessionId);
  await b.send('Page.navigate', { url }, sessionId);
  await sleep(2200);
  return { targetId, sessionId };
}
async function ev(sessionId, fn){
  const r = await b.send('Runtime.evaluate', { expression:`(${fn})()`, returnByValue:true, awaitPromise:true }, sessionId);
  if(r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'eval error');
  return r.result.value;
}

const checks = [];
const assert = (name, cond, detail='') => { checks.push({ name, pass: !!cond, detail }); };

// ---------------- PRICING (WHOOP membership) ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/pricing.html`);

  // structure: single membership card, 4 kit cards, economics section present
  const struct = await ev(sessionId, () => ({
    memPrice: document.getElementById('memPrice').textContent,
    kit: document.querySelectorAll('.kit-card').length,
    econ: !!document.getElementById('economics'),
    leftover: document.body.innerText.includes('{{')  // visible text only — ignores the swap script's own literal
  }));
  assert('pricing: membership headline is £99/mo', struct.memPrice==='£99', struct.memPrice);
  assert('pricing: kit shows 4 included devices', struct.kit===4, String(struct.kit));
  assert('pricing: unit-economics section present (for judges)', struct.econ===true);
  assert('pricing: no leftover template placeholders', struct.leftover===false);

  // ROI default matches computed (no stale flash); £3.50 x 2 x (6x4.33) = £182
  const roiInit = await ev(sessionId, () => document.getElementById('roiValue').textContent);
  assert('pricing: ROI default matches computed output', roiInit==='£182', roiInit);

  // billing toggle: £99/month -> £990/year (no rounding drift)
  await ev(sessionId, () => document.getElementById('billingToggle').click());
  await sleep(200);
  const annual = await ev(sessionId, () => ({
    price: document.getElementById('memPrice').textContent,
    per: document.getElementById('memPer').textContent,
    aria: document.getElementById('billingToggle').getAttribute('aria-checked'),
    sub: document.getElementById('memSub').textContent
  }));
  assert('pricing: annual toggle shows £990/year', annual.price==='£990' && /year/.test(annual.per), JSON.stringify(annual));
  assert('pricing: annual sub mentions 2 months free', /2 months free/.test(annual.sub) && annual.aria==='true', annual.sub);

  // label click switches back to monthly
  await ev(sessionId, () => document.getElementById('lblMonthly').click());
  await sleep(150);
  const backMonthly = await ev(sessionId, () => document.getElementById('memPrice').textContent);
  assert('pricing: clicking "Monthly" label returns to £99', backMonthly==='£99', backMonthly);

  // ROI recalculates and is referenced against the £99 membership
  await ev(sessionId, () => { const d=document.getElementById('drinks'); d.value='6'; d.dispatchEvent(new Event('input',{bubbles:true})); });
  await sleep(500);
  const roi = await ev(sessionId, () => ({ v: document.getElementById('roiValue').textContent, note: document.getElementById('roiNote').innerHTML }));
  assert('pricing: ROI grows on slider input', parseInt(roi.v.replace(/[^0-9]/g,''),10) > 182, roi.v);
  assert('pricing: ROI note references £99 membership', /£99/.test(roi.note));

  // FAQ accordion exclusivity + aria
  const faq = await ev(sessionId, () => {
    const items = document.querySelectorAll('.faq-item');
    items[2].querySelector('.faq-q').click();
    return { count: items.length, open: document.querySelectorAll('.faq-item.open').length,
             aria: items[2].querySelector('.faq-q').getAttribute('aria-expanded') };
  });
  assert('pricing: FAQ opens one item exclusively with aria-expanded', faq.open===1 && faq.aria==='true', JSON.stringify(faq));
  assert('pricing: membership FAQ has the expected items', faq.count===8, String(faq.count));

  await b.send('Target.closeTarget', { targetId });
}

// ---------------- ONBOARDING: membership preselect ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/onboarding.html?plan=membership`);
  const sel = await ev(sessionId, () => document.querySelector('.plan-opt.sel')?.dataset.plan);
  assert('onboarding: ?plan=membership preselects the membership', sel==='membership', `selected=${sel}`);
  await b.send('Target.closeTarget', { targetId });
}

// ---------------- ONBOARDING: malformed ?plan must NOT brick the wizard ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/onboarding.html?plan=${encodeURIComponent('a"]b')}`);
  const alive = await ev(sessionId, () => {
    const chip = document.querySelector('[data-chips] .chip');
    chip.click();
    return { chipSelected: chip.classList.contains('sel'),
             defaultPlan: document.querySelector('.plan-opt.sel')?.dataset.plan };
  });
  assert('onboarding: malformed ?plan does not brick wizard (chips still work)', alive.chipSelected===true, JSON.stringify(alive));
  assert('onboarding: malformed ?plan falls back to membership', alive.defaultPlan==='membership', alive.defaultPlan);
  await b.send('Target.closeTarget', { targetId });
}

// ---------------- ONBOARDING: empty step 0 blocked ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/onboarding.html`);
  await ev(sessionId, () => document.getElementById('btnNext').click());
  await sleep(300);
  const blocked = await ev(sessionId, () => ({
    step: document.querySelector('.pane.active')?.dataset.step,
    errs: document.querySelectorAll('.err-msg.show').length
  }));
  assert('onboarding: empty step 0 blocked by validation', blocked.step==='0' && blocked.errs>0, JSON.stringify(blocked));
  await b.send('Target.closeTarget', { targetId });
}

// ---------------- ONBOARDING: full signup flow to success (stub backend) ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/onboarding.html?plan=membership${BK}`);

  // step 0 — fill text fields + first chip of every chip-group
  const s1 = await ev(sessionId, async () => {
    const wait = ms => new Promise(r=>setTimeout(r,ms));
    const set=(id,v)=>{ const e=document.getElementById(id); if(e){ e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); } };
    set('venueName','Hearth & Co'); set('covers','24'); set('postcode','EC1A 1BB');
    document.querySelectorAll('.pane[data-step="0"] [data-chips]').forEach(g => g.querySelector('.chip').click());
    document.getElementById('btnNext').click(); await wait(500);
    return document.querySelector('.pane.active')?.dataset.step;
  });
  assert('onboarding: valid step 0 advances to step 1', s1==='1', `step=${s1}`);

  // step 1 — camera chips, then advance through devices(2) + membership(3) to account(4)
  const s4 = await ev(sessionId, async () => {
    const wait = ms => new Promise(r=>setTimeout(r,ms));
    document.querySelectorAll('.pane[data-step="1"] [data-chips]').forEach(g => g.querySelector('.chip').click());
    const next=()=>document.getElementById('btnNext').click();
    next(); await wait(450);  // 1 -> 2
    next(); await wait(450);  // 2 -> 3
    next(); await wait(450);  // 3 -> 4
    return document.querySelector('.pane.active')?.dataset.step;
  });
  assert('onboarding: advances through to account step', s4==='4', `step=${s4}`);

  // step 4 — account (name, email, password>=8, agree) -> review
  const review = await ev(sessionId, async () => {
    const wait = ms => new Promise(r=>setTimeout(r,ms));
    const set=(id,v)=>{ const e=document.getElementById(id); if(e){ e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); } };
    set('ownerName','Sam Mara'); set('email','sam@hearth.co'); set('password','supersecret');
    const ag=document.getElementById('agree'); ag.checked=true; ag.dispatchEvent(new Event('change',{bubbles:true}));
    document.getElementById('btnNext').click(); await wait(500);
    return { step: document.querySelector('.pane.active')?.dataset.step,
             rows: document.querySelectorAll('#reviewBox .review-row').length,
             planLine: [...document.querySelectorAll('#reviewBox .review-row')].map(r=>r.textContent).find(t=>/Membership/.test(t)) || '',
             btn: document.getElementById('btnNext').textContent };
  });
  assert('onboarding: reaches review with populated summary', review.step==='5' && review.rows>=8, JSON.stringify({step:review.step,rows:review.rows}));
  assert('onboarding: review shows the membership plan', /Membership/.test(review.planLine), review.planLine);
  assert('onboarding: confirm button relabels on review', /Confirm/i.test(review.btn), review.btn);

  // confirm -> POST /auth/signup (stub) -> success
  const done = await ev(sessionId, async () => {
    const wait = ms => new Promise(r=>setTimeout(r,ms));
    document.getElementById('btnNext').click(); await wait(1200);
    return { step: document.querySelector('.pane.active')?.dataset.step,
             actionsHidden: getComputedStyle(document.getElementById('obActions')).display==='none',
             email: document.getElementById('doneEmail').textContent,
             plan: document.getElementById('donePlan').textContent };
  });
  assert('onboarding: confirm reaches success screen', done.step==='6' && done.actionsHidden, JSON.stringify(done));
  assert('onboarding: success echoes entered email', done.email==='sam@hearth.co', done.email);
  assert('onboarding: success names the membership', /Membership/.test(done.plan), done.plan);

  await b.send('Target.closeTarget', { targetId });
}

// ---------------- ONBOARDING: invalid email + short password block ----------------
{
  const { sessionId, targetId } = await open(`http://localhost:${PORT}/onboarding.html?plan=membership${BK}`);
  const blocked = await ev(sessionId, async () => {
    const wait = ms => new Promise(r=>setTimeout(r,ms));
    const set=(id,v)=>{ const e=document.getElementById(id); if(e){ e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); } };
    set('venueName','X'); set('covers','10'); set('postcode','E1');
    document.querySelectorAll('.pane[data-step="0"] [data-chips]').forEach(g => g.querySelector('.chip').click());
    const next=()=>document.getElementById('btnNext').click();
    next(); await wait(450);
    document.querySelectorAll('.pane[data-step="1"] [data-chips]').forEach(g => g.querySelector('.chip').click());
    next(); await wait(450); // ->2
    next(); await wait(450); // ->3
    next(); await wait(450); // ->4
    set('ownerName','A'); set('email','not-an-email'); set('password','short');
    document.getElementById('agree').checked=true;
    next(); await wait(300);
    return { step: document.querySelector('.pane.active')?.dataset.step,
             emailErr: document.querySelector('[data-err=email]').classList.contains('show'),
             pwErr: document.querySelector('[data-err=password]').classList.contains('show') };
  });
  assert('onboarding: invalid email blocks advance', blocked.step==='4' && blocked.emailErr, JSON.stringify(blocked));
  assert('onboarding: short password blocks advance', blocked.pwErr===true, JSON.stringify(blocked));
  await b.send('Target.closeTarget', { targetId });
}

// ---------------- report ----------------
console.log('\nINTERACTION CHECKS\n');
let fails = 0;
for(const c of checks){ console.log((c.pass?'  PASS  ':'  FAIL  ')+c.name+(c.detail?('   ('+c.detail+')'):'')); if(!c.pass) fails++; }
console.log(`\n=== ${checks.length-fails}/${checks.length} passed, ${fails} failed ===`);

b.close(); chrome.kill('SIGTERM'); server.close();
process.exit(fails>0?1:0);
