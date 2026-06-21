/* Caffe Steve — "Connect & auto-map" camera-first setup flow.
 *
 * A 3-screen, mobile-first onboarding that reads like:
 *   connect a camera  ->  it auto-detects your zones  ->  go live.
 *
 * It produces the SAME geometry contract as the rest of the pipeline
 * (perception/run.py load_geometry, mirrored in app.js):
 *
 *   { room, zones:{entry,queue,counter,seating}, tables:{T1..}, cleaning:{restroom} }
 *
 * All polygons are normalized 0..1 (top-left origin) to the displayed feed,
 * every polygon has >= 3 points, and the result is POSTed to ${API}/geometry.
 *
 * NOTE ON "AUTO-DETECTION":  The suggested zones on screen 2 are a HEURISTIC
 * DEFAULT layout (counter along the top, queue in front, entry lower-left,
 * seating right/lower, restroom in a corner) — NOT the output of a trained
 * detector. It is a sensible starting point the user drags to fit. A real
 * auto-detector (e.g. a segmentation / layout model running server-side, or a
 * call to ${API}/detect-zones returning the same normalized polygon contract)
 * would plug in at suggestZones() below: replace the static layout with the
 * model's polygons and keep the rest of the drag-to-fit + POST flow unchanged.
 */
(function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- API resolution: ?api= param, else same-origin http, else default. ----
  function apiBase() {
    const q = new URLSearchParams(location.search).get('api');
    if (q) return q.replace(/\/$/, '');
    if (location.origin && location.protocol.startsWith('http')) return location.origin;
    return 'https://golden-coffee-production.up.railway.app';
  }
  const API = apiBase();

  // ---- Zone definitions (buckets + colors mirror app.js SLOTS). --------------
  const ZONE_DEFS = [
    { id: 'counter',  label: 'Counter',  bucket: 'zones',    color: '#d9a441' },
    { id: 'queue',    label: 'Queue',    bucket: 'zones',    color: '#6fb6e0' },
    { id: 'entry',    label: 'Entry',    bucket: 'zones',    color: '#9aa0a6' },
    { id: 'seating',  label: 'Seating',  bucket: 'zones',    color: '#7ed87e' },
    { id: 'restroom', label: 'Restroom', bucket: 'cleaning', color: '#e0876f' },
  ];
  const TABLE_COLOR = '#b58fe0';

  // A rectangle, clockwise from top-left -> a valid 4-point polygon.
  const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  const sq = (cx, cy, s) => rect(cx - s, cy - s, cx + s, cy + s);

  // ---- HEURISTIC DEFAULT ZONE SUGGESTION (see file header). -----------------
  // Returns the normalized polygon map for a typical café camera framing.
  function suggestZones() {
    return {
      counter:  rect(0.07, 0.09, 0.71, 0.27),  // along the top wall
      queue:    rect(0.17, 0.31, 0.71, 0.49),   // in front of the counter
      entry:    rect(0.05, 0.71, 0.31, 0.93),   // lower-left (the way in)
      seating:  rect(0.37, 0.53, 0.94, 0.93),   // right / lower floor
      restroom: rect(0.77, 0.07, 0.93, 0.25),   // tucked in the top-right corner
    };
  }

  // ---- State ----------------------------------------------------------------
  const state = {
    feedMode: 'demo',          // 'live' | 'demo'
    feedUrl: '',               // url that loaded, if any
    zones: {},                 // id -> [[x,y],...] normalized (incl. restroom)
    tables: {},                // T1.. -> polygon
    nextTable: 1,
    activeZone: 'counter',
    revealT: 1,                // 0..1 scan-reveal progress (1 = fully shown)
  };

  // ====================================================================== //
  //  SCREEN NAVIGATION                                                     //
  // ====================================================================== //
  function goScreen(n) {
    [1, 2, 3].forEach((i) => {
      $('#screen-' + i).classList.toggle('active', i === n);
      const dot = document.querySelector('.stepdot[data-dot="' + i + '"]');
      if (dot) dot.classList.toggle('on', i <= n);
    });
    window.scrollTo(0, 0);
    if (n === 2) enterScreen2();
    if (n === 3) enterScreen3();
  }

  // ====================================================================== //
  //  FEED LOADING  (try MJPEG stream -> frame.jpg -> built-in CSS still)   //
  // ====================================================================== //
  // Resolve to {mode:'live'|'demo', url}. Tries the live camera first and
  // always falls back so the pane looks alive even with no backend.
  function loadFeed(setStatus) {
    setStatus && setStatus('Connecting to camera…');
    return new Promise((resolve) => {
      let settled = false;
      const done = (mode, url) => {
        if (settled) return; settled = true;
        state.feedMode = mode; state.feedUrl = url || '';
        applyFeedToPanes();
        resolve({ mode, url });
      };

      // Step 1: MJPEG stream, with a ~3s patience window.
      const streamUrl = API + '/stream';
      const probe = new Image();
      const t = setTimeout(tryFrame, 3000);
      probe.onload = () => { clearTimeout(t); done('live', streamUrl); };
      probe.onerror = () => { clearTimeout(t); tryFrame(); };
      try { probe.src = streamUrl; } catch (e) { clearTimeout(t); tryFrame(); }

      // Step 2: single snapshot.
      function tryFrame() {
        if (settled) return;
        const frameUrl = API + '/frame.jpg';
        const img2 = new Image();
        img2.onload = () => done('live', frameUrl);
        img2.onerror = () => done('demo', '');   // Step 3: built-in CSS still
        try { img2.src = frameUrl + '?t=' + Date.now(); }
        catch (e) { done('demo', ''); }
      }
    });
  }

  // Reflect current feed state into both screen-1 and screen-2 panes + badges.
  function applyFeedToPanes() {
    [['feed1', 'feedImg1', 'badge1', 'feedMeta1'],
     ['feed2', 'feedImg2', 'badge2', null]].forEach(([fId, imgId, badgeId, metaId]) => {
      const feed = document.getElementById(fId);
      const img = document.getElementById(imgId);
      const badge = document.getElementById(badgeId);
      if (!feed || !img || !badge) return;
      if (state.feedMode === 'live' && state.feedUrl) {
        img.src = state.feedUrl;
        feed.classList.add('has-img');
        badge.className = 'badge live';
        badge.querySelector('.lbl').textContent = 'LIVE';
      } else {
        feed.classList.remove('has-img');
        badge.className = 'badge demo';
        badge.querySelector('.lbl').textContent = 'DEMO';
      }
      if (metaId) {
        const meta = document.getElementById(metaId);
        if (meta) meta.textContent = state.feedMode === 'live'
          ? state.feedUrl : 'Built-in demo café scene (no camera reachable)';
      }
    });
  }

  // ====================================================================== //
  //  SCREEN 1 — Connect a camera                                           //
  // ====================================================================== //
  const status1 = $('#status1');
  function setStatus1(msg, kind) { status1.textContent = msg || ''; status1.className = 'status ' + (kind || ''); }

  async function connect(sourceLabel) {
    $('#feed1Wrap').hidden = false;
    setStatus1('Connecting…');
    const r = await loadFeed(setStatus1);
    if (r.mode === 'live') setStatus1('Camera connected. ' + sourceLabel, 'ok');
    else setStatus1('No camera reachable — using the built-in demo feed so you can try the flow.', '');
    $('#toScreen2').hidden = false;
    $('#toScreen2').focus();
  }

  $('#btnConnect').addEventListener('click', () => {
    const url = $('#rtspUrl').value.trim();
    if (!url) { setStatus1('Paste an RTSP / stream URL first, or use the demo feed.', 'err'); $('#rtspUrl').focus(); return; }
    connect('Streaming from your URL.');
  });
  $('#btnDemo').addEventListener('click', () => connect('Using the demo feed.'));
  // QR scan is a STUB: it just reveals / focuses the URL field.
  $('#btnQr').addEventListener('click', () => {
    $('#rtspUrl').focus();
    setStatus1('QR scan is stubbed in this prototype — paste a URL or use the demo feed.', '');
  });
  $('#toScreen2').addEventListener('click', () => goScreen(2));

  // ====================================================================== //
  //  SCREEN 2 — Confirm auto-zones (the "magic" beat)                      //
  // ====================================================================== //
  const overlay = $('#overlay');
  const octx = overlay.getContext('2d');
  let view = { w: 1, h: 1 };

  function fitOverlay() {
    const feed = $('#feed2');
    const rectb = feed.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    view.w = Math.max(1, Math.floor(rectb.width));
    view.h = Math.max(1, Math.floor(rectb.height));
    overlay.width = Math.floor(view.w * dpr);
    overlay.height = Math.floor(view.h * dpr);
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawOverlay();
  }

  const colorOf = (id) => {
    const d = ZONE_DEFS.find((z) => z.id === id);
    return d ? d.color : TABLE_COLOR;
  };
  const labelOf = (id) => {
    const d = ZONE_DEFS.find((z) => z.id === id);
    return d ? d.label : id;
  };
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function centroid(poly) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < poly.length; i++) {
      const [x0, y0] = poly[i], [x1, y1] = poly[(i + 1) % poly.length];
      const c = x0 * y1 - x1 * y0; a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c;
    }
    if (Math.abs(a) < 1e-12) {
      const m = poly.reduce((s, p) => [s[0] + p[0], s[1] + p[1]], [0, 0]);
      return [m[0] / poly.length, m[1] / poly.length];
    }
    a *= 0.5; return [cx / (6 * a), cy / (6 * a)];
  }
  const toPx = (p) => [p[0] * view.w, p[1] * view.h];

  // All editable polygons (zones + restroom + tables) in one list for drawing
  // and hit-testing.
  function eachPoly(fn) {
    ZONE_DEFS.forEach((d) => { if (state.zones[d.id]) fn(d.id, state.zones[d.id], d.color, labelOf(d.id)); });
    Object.keys(state.tables).forEach((id) => fn(id, state.tables[id], TABLE_COLOR, id));
  }

  function drawPoly(id, poly, color, label, isActive) {
    if (!poly || !poly.length) return;
    const reveal = state.revealT;
    octx.save();
    octx.globalAlpha = reveal;
    octx.lineWidth = isActive ? 3 : 1.8;
    octx.strokeStyle = color;
    octx.fillStyle = hexA(color, isActive ? 0.26 : 0.16);
    octx.beginPath();
    poly.forEach((p, i) => { const [x, y] = toPx(p); i === 0 ? octx.moveTo(x, y) : octx.lineTo(x, y); });
    octx.closePath(); octx.fill(); octx.stroke();

    // Label chip at centroid (only once mostly revealed, to keep the reveal clean).
    if (reveal > 0.85) {
      const c = centroid(poly); const cx = c[0] * view.w, cy = c[1] * view.h;
      octx.font = '700 12px system-ui, sans-serif';
      octx.textAlign = 'center'; octx.textBaseline = 'middle';
      const tw = octx.measureText(label).width + 14;
      roundRect(cx - tw / 2, cy - 10, tw, 20, 7); octx.fillStyle = color; octx.fill();
      octx.fillStyle = '#14110e'; octx.fillText(label, cx, cy);
    }
    // Draggable corner handles.
    poly.forEach((p) => {
      const [x, y] = toPx(p);
      octx.beginPath(); octx.arc(x, y, isActive ? 9 : 6, 0, Math.PI * 2);
      octx.fillStyle = color; octx.fill();
      octx.lineWidth = 2; octx.strokeStyle = '#14110e'; octx.stroke();
    });
    octx.restore();
  }
  function roundRect(x, y, w, h, r) {
    octx.beginPath();
    octx.moveTo(x + r, y);
    octx.arcTo(x + w, y, x + w, y + h, r);
    octx.arcTo(x + w, y + h, x, y + h, r);
    octx.arcTo(x, y + h, x, y, r);
    octx.arcTo(x, y, x + w, y, r);
    octx.closePath();
  }

  function drawOverlay() {
    octx.clearRect(0, 0, view.w, view.h);
    // scan sweep line during reveal
    if (state.revealT < 1 && !reduceMotion) {
      const y = state.revealT * view.h;
      const g = octx.createLinearGradient(0, y - 40, 0, y + 6);
      g.addColorStop(0, 'rgba(255,154,45,0)');
      g.addColorStop(1, 'rgba(255,154,45,0.5)');
      octx.fillStyle = g; octx.fillRect(0, Math.max(0, y - 40), view.w, 46);
      octx.strokeStyle = 'rgba(255,154,45,0.9)'; octx.lineWidth = 2;
      octx.beginPath(); octx.moveTo(0, y); octx.lineTo(view.w, y); octx.stroke();
    }
    eachPoly((id, poly, color, label) => drawPoly(id, poly, color, label, id === state.activeZone));
  }

  // --- Scan reveal animation (disabled under prefers-reduced-motion) ---------
  function playReveal() {
    if (reduceMotion) { state.revealT = 1; drawOverlay(); finishReveal(); return; }
    state.revealT = 0;
    const start = performance.now(), DUR = 1100;
    (function step(now) {
      state.revealT = Math.min(1, (now - start) / DUR);
      drawOverlay();
      if (state.revealT < 1) requestAnimationFrame(step); else finishReveal();
    })(start);
  }
  function finishReveal() {
    $('#s2title').textContent = 'We detected your zones';
    $('#s2lede').textContent = 'A smart starting layout — drag the corner handles to fit your room.';
    setStatus2('Tip: tap a zone chip, then drag its handles.', '');
  }

  function enterScreen2() {
    if (!Object.keys(state.zones).length) {
      state.zones = suggestZones();         // heuristic default (see header)
    }
    applyFeedToPanes();
    buildChips();
    fitOverlay();
    $('#s2title').textContent = 'Finding your zones…';
    $('#s2lede').textContent = 'Scanning the frame…';
    playReveal();
  }

  const status2 = $('#status2');
  function setStatus2(msg, kind) { status2.textContent = msg || ''; status2.className = 'status ' + (kind || ''); }

  function buildChips() {
    const bar = $('#zoneChips'); bar.innerHTML = '';
    const ids = ZONE_DEFS.map((d) => d.id).concat(Object.keys(state.tables));
    ids.forEach((id) => {
      const b = document.createElement('button');
      b.className = 'chip'; b.type = 'button'; b.dataset.zone = id;
      b.setAttribute('aria-pressed', id === state.activeZone ? 'true' : 'false');
      b.innerHTML = `<span class="sw" style="background:${colorOf(id)}"></span>${labelOf(id)}`;
      b.addEventListener('click', () => { state.activeZone = id; refreshChips(); drawOverlay(); });
      bar.appendChild(b);
    });
  }
  function refreshChips() {
    [...$('#zoneChips').children].forEach((b) =>
      b.setAttribute('aria-pressed', b.dataset.zone === state.activeZone ? 'true' : 'false'));
  }

  // --- Drag handles (pointer + touch) ---------------------------------------
  let drag = null;  // { id, idx }
  function ptNorm(ev) {
    const rectb = overlay.getBoundingClientRect();
    const t = (ev.touches && ev.touches[0]) || ev;
    return [
      Math.min(1, Math.max(0, (t.clientX - rectb.left) / rectb.width)),
      Math.min(1, Math.max(0, (t.clientY - rectb.top) / rectb.height)),
    ];
  }
  function hitTest(nx, ny) {
    const HR = 22 / Math.max(view.w, view.h);   // ~22px hit radius, normalized
    let best = null, bestD = HR;
    const consider = (id, poly) => {
      poly.forEach((p, idx) => {
        const d = Math.hypot(p[0] - nx, p[1] - ny);
        if (d < bestD) { bestD = d; best = { id, idx }; }
      });
    };
    // Prefer the active zone's handles, then everything else.
    if (state.zones[state.activeZone]) consider(state.activeZone, state.zones[state.activeZone]);
    if (state.tables[state.activeZone]) consider(state.activeZone, state.tables[state.activeZone]);
    eachPoly((id, poly) => { if (id !== state.activeZone) consider(id, poly); });
    return best;
  }
  function polyOf(id) { return state.zones[id] || state.tables[id]; }

  function onDown(ev) {
    const [nx, ny] = ptNorm(ev);
    const hit = hitTest(nx, ny);
    if (!hit) return;
    drag = hit;
    if (hit.id !== state.activeZone && (state.zones[hit.id] || state.tables[hit.id])) {
      state.activeZone = hit.id; refreshChips();
    }
    ev.preventDefault();
    drawOverlay();
  }
  function onMove(ev) {
    if (!drag) return;
    const [nx, ny] = ptNorm(ev);
    const poly = polyOf(drag.id);
    if (poly && poly[drag.idx]) { poly[drag.idx][0] = nx; poly[drag.idx][1] = ny; }
    ev.preventDefault();
    drawOverlay();
  }
  function onUp() { if (drag) { drag = null; drawOverlay(); } }

  overlay.addEventListener('pointerdown', onDown);
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  // Touch fallback for browsers without pointer events.
  overlay.addEventListener('touchstart', onDown, { passive: false });
  window.addEventListener('touchmove', onMove, { passive: false });
  window.addEventListener('touchend', onUp);

  $('#btnAddTable').addEventListener('click', () => {
    // Drop a table in the middle of the seating zone (or center as fallback).
    const seat = state.zones.seating;
    let cx = 0.62, cy = 0.72;
    if (seat) { const c = centroid(seat); cx = c[0]; cy = c[1]; }
    cx += (state.nextTable % 3) * 0.08 - 0.08;
    cy += Math.floor(state.nextTable / 3) * 0.1 - 0.05;
    const id = 'T' + state.nextTable++;
    state.tables[id] = sq(Math.min(0.92, Math.max(0.08, cx)), Math.min(0.92, Math.max(0.08, cy)), 0.045);
    state.activeZone = id;
    buildChips(); drawOverlay();
    setStatus2('Added ' + id + ' — drag its handles to size it.', '');
  });

  $('#btnReset').addEventListener('click', () => {
    state.zones = suggestZones(); state.tables = {}; state.nextTable = 1;
    state.activeZone = 'counter';
    buildChips(); drawOverlay();
    setStatus2('Zones reset to the suggested layout.', '');
  });

  $('#backTo1').addEventListener('click', () => goScreen(1));

  // ---- Build the zones.json contract object. -------------------------------
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  function buildGeometry() {
    const out = { room: rect(0, 0, 1, 1), zones: {}, tables: {}, cleaning: {} };
    ZONE_DEFS.forEach((d) => {
      const poly = state.zones[d.id];
      if (!poly || poly.length < 3) return;
      const norm = poly.map((p) => [clamp01(p[0]), clamp01(p[1])]);
      if (d.bucket === 'zones') out.zones[d.id] = norm;
      else out.cleaning[d.id] = norm;        // restroom
    });
    Object.keys(state.tables).forEach((id) => {
      const poly = state.tables[id];
      if (poly && poly.length >= 3) out.tables[id] = poly.map((p) => [clamp01(p[0]), clamp01(p[1])]);
    });
    return out;
  }

  async function goLive() {
    const g = buildGeometry();
    const required = ['entry', 'queue', 'counter', 'seating'];
    const missing = required.filter((z) => !g.zones[z] || g.zones[z].length < 3);
    if (missing.length) { setStatus2('Missing zones: ' + missing.join(', '), 'err'); return; }

    state.lastGeometry = g;
    const url = API + '/geometry';
    setStatus2('Pushing your layout to ' + url + ' …', '');
    $('#btnGoLive').disabled = true;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(g),
      });
      if (res.ok) setStatus2('Pushed to live ☁ (' + res.status + ')', 'ok');
      else setStatus2('Server returned ' + res.status + ' — showing your twin anyway.', 'err');
    } catch (e) {
      setStatus2('Could not reach the server (' + (e && e.message ? e.message : e) + ') — showing your twin anyway.', 'err');
    } finally {
      $('#btnGoLive').disabled = false;
      goScreen(3);   // always reveal the twin so the user sees their geometry
    }
  }
  $('#btnGoLive').addEventListener('click', goLive);

  // ====================================================================== //
  //  SCREEN 3 — Go live (mini 3D twin via scan3d.js)                       //
  // ====================================================================== //
  function enterScreen3() {
    const g = state.lastGeometry || buildGeometry();
    if (window.GCScan3D) {
      try {
        window.GCScan3D.ensure();
        window.GCScan3D.update(g);
        window.GCScan3D.resize && window.GCScan3D.resize();
        setTimeout(() => window.GCScan3D.resize && window.GCScan3D.resize(), 120);
      } catch (e) { /* twin is confirmation-only; flow still completed */ }
    }
    // Keep the dashboard link pointing at same-origin root when served by the backend.
    $('#openDash').href = (location.protocol.startsWith('http')) ? './' : (API + '/');
    $('#status3').textContent = 'Tip: drag the twin to orbit. Open the dashboard to watch it live.';
  }
  $('#backTo2').addEventListener('click', () => goScreen(2));

  // ---- Resize handling ------------------------------------------------------
  window.addEventListener('resize', () => {
    if ($('#screen-2').classList.contains('active')) fitOverlay();
  });

  // ---- Expose a small surface for verification / debugging. -----------------
  window.GCConnect = { state, buildGeometry, suggestZones, apiBase: () => API, goScreen };
})();
