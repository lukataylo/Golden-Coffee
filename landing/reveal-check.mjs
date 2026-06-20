// Confirms scroll-reveal actually makes below-fold content visible.
// Loads pricing.html, scrolls in steps, then asserts computed opacity===1 on
// elements that start hidden (ROI box, comparison table, final CTA).
import http from 'node:http'; import { readFile } from 'node:fs/promises'; import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process'; import path from 'node:path';
const ROOT = path.resolve('.'); const PORT = 8767;
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const MIME = { '.html':'text/html','.css':'text/css','.js':'text/javascript','.svg':'image/svg+xml' };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const server = http.createServer(async (req,res)=>{ let p=decodeURIComponent(req.url.split('?')[0]); if(p==='/')p='/index.html';
  const fp=path.join(ROOT,p); if(!existsSync(fp)){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':MIME[path.extname(fp)]||'text/plain'}); res.end(await readFile(fp)); });
await new Promise(r=>server.listen(PORT,r));
const chrome = spawn(CHROME,['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=9335',
  '--user-data-dir=/tmp/gc-reveal-profile','--window-size=1440,1000','about:blank'],{stdio:'ignore'});
let v=null; for(let i=0;i<50;i++){ try{ v=await (await fetch('http://localhost:9335/json/version')).json(); break;}catch{await sleep(200);} }
function cdp(u){ const ws=new WebSocket(u); let id=0; const pend=new Map(); const ls=[];
  const ready=new Promise(r=>ws.onopen=()=>r());
  ws.onmessage=ev=>{const m=JSON.parse(ev.data); if(m.id&&pend.has(m.id)){const{resolve,reject}=pend.get(m.id);pend.delete(m.id);m.error?reject(new Error(m.error.message)):resolve(m.result);} else if(m.method)ls.forEach(f=>f(m));};
  return {ready,on:f=>ls.push(f),send:(method,params={},sid)=>new Promise((resolve,reject)=>{const m={id:++id,method,params};if(sid)m.sessionId=sid;pend.set(m.id,{resolve,reject});ws.send(JSON.stringify(m));}),close:()=>ws.close()}; }
const b=cdp(v.webSocketDebuggerUrl); await b.ready;
const {targetId}=await b.send('Target.createTarget',{url:'about:blank'});
const {sessionId}=await b.send('Target.attachToTarget',{targetId,flatten:true});
await b.send('Page.enable',{},sessionId); await b.send('Runtime.enable',{},sessionId);
await b.send('Page.navigate',{url:`http://localhost:${PORT}/pricing.html`},sessionId);
await sleep(1800);
const ev=async fn=>{ const r=await b.send('Runtime.evaluate',{expression:`(${fn})()`,returnByValue:true,awaitPromise:true},sessionId); return r.result.value; };

// before scroll: capture opacity of a far-down element
const targets = ['.roi','.cmp','.final-cta'];
const before = await ev(`()=>{const o={};${JSON.stringify(targets)}.forEach(s=>{const e=document.querySelector(s);o[s]=e?getComputedStyle(e).opacity:'missing';});return o;}`);

// scroll down gradually to trigger IntersectionObserver, then to bottom
await ev(`async ()=>{const wait=ms=>new Promise(r=>setTimeout(r,ms));
  const H=document.body.scrollHeight; for(let y=0;y<=H;y+=600){window.scrollTo(0,y);await wait(120);} window.scrollTo(0,H); await wait(500);}`);
await sleep(600);
const after = await ev(`()=>{const o={};${JSON.stringify(targets)}.forEach(s=>{const e=document.querySelector(s);o[s]=e?getComputedStyle(e).opacity:'missing';});return o;}`);

console.log('opacity BEFORE scroll:', JSON.stringify(before));
console.log('opacity AFTER scroll: ', JSON.stringify(after));
let fails=0;
targets.forEach(s=>{ const ok = parseFloat(after[s])>0.95; console.log((ok?'  PASS  ':'  FAIL  ')+s+' reveals to opacity '+after[s]); if(!ok)fails++; });
b.close(); chrome.kill('SIGTERM'); server.close();
console.log(`\n=== ${targets.length-fails}/${targets.length} below-fold sections reveal correctly ===`);
process.exit(fails>0?1:0);
