/* Caffe Steve Floorplan Scanner — 2D editor, capture, trace, export.
 *
 * Geometry contract (perception/run.py load_geometry):
 *   { "zones":   {entry,queue,counter,seating: [[x,y],...]},
 *     "tables":  {T1,T2,T3,...: [[x,y],...]},
 *     "cleaning":{restroom: [[x,y],...]},
 *     "room":    [[x,y],...]   // optional, used only by the 3D twin walls }
 * All coords are normalized to the image/canvas (0..1), top-left origin.
 */
(function () {
  'use strict';

  // ---- Slot definitions: which export bucket each slot lands in. -----------
  const BUCKET = { ZONES: 'zones', TABLES: 'tables', CLEANING: 'cleaning', ROOM: 'room' };
  const SLOTS = [
    { id: 'room',     label: 'Room outline', bucket: BUCKET.ROOM,     color: '#e7c074' },
    { id: 'entry',    label: 'Entry',        bucket: BUCKET.ZONES,    color: '#9aa0a6' },
    { id: 'queue',    label: 'Queue',        bucket: BUCKET.ZONES,    color: '#6fb6e0' },
    { id: 'counter',  label: 'Counter',      bucket: BUCKET.ZONES,    color: '#d9a441' },
    { id: 'seating',  label: 'Seating',      bucket: BUCKET.ZONES,    color: '#7ed87e' },
    { id: 'T1',       label: 'Table T1',     bucket: BUCKET.TABLES,   color: '#b58fe0' },
    { id: 'T2',       label: 'Table T2',     bucket: BUCKET.TABLES,   color: '#b58fe0' },
    { id: 'T3',       label: 'Table T3',     bucket: BUCKET.TABLES,   color: '#b58fe0' },
    { id: 'restroom', label: 'Restroom',     bucket: BUCKET.CLEANING, color: '#e0876f' },
  ];

  // ---- State ---------------------------------------------------------------
  const state = {
    img: null,                 // HTMLImageElement | null (null => blank grid)
    polys: {},                 // slotId -> [[x,y],...] normalized
    activeSlot: 'room',
    nextTable: 4,              // next "add table" id (T4, T5, ...)
  };
  SLOTS.forEach((s) => (state.polys[s.id] = []));

  const slotById = {};
  function rebuildSlotIndex() { SLOTS.forEach((s) => (slotById[s.id] = s)); }
  rebuildSlotIndex();

  // ---- DOM refs ------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);
  const canvas = $('#editor');
  const ctx = canvas.getContext('2d');
  const slotBar = $('#slotbar');
  const statusEl = $('#status');
  const fileInput = $('#fileInput');
  const stage = $('#stage');

  // Device-pixel-aware canvas sizing. We keep an internal CSS size for the
  // drawing surface and map taps through it. Normalized coords are independent
  // of pixel size, so resizing never corrupts geometry.
  let view = { w: 1, h: 1 }; // CSS pixels of the canvas

  function fitCanvas() {
    const rect = stage.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let cssW = Math.max(1, Math.floor(rect.width));
    let cssH = Math.max(1, Math.floor(rect.height));
    // If we have a photo, letterbox the canvas to its aspect ratio.
    if (state.img) {
      const ar = state.img.naturalWidth / state.img.naturalHeight;
      if (cssW / cssH > ar) cssW = Math.floor(cssH * ar);
      else cssH = Math.floor(cssW / ar);
    }
    view.w = cssW; view.h = cssH;
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    render();
  }

  // ---- Rendering -----------------------------------------------------------
  function drawGrid() {
    ctx.fillStyle = '#0b0907';
    ctx.fillRect(0, 0, view.w, view.h);
    ctx.strokeStyle = 'rgba(217,164,65,0.10)';
    ctx.lineWidth = 1;
    const step = Math.max(24, Math.floor(Math.min(view.w, view.h) / 16));
    for (let x = 0; x <= view.w; x += step) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, view.h); ctx.stroke();
    }
    for (let y = 0; y <= view.h; y += step) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(view.w, y); ctx.stroke();
    }
  }

  function render() {
    ctx.clearRect(0, 0, view.w, view.h);
    if (state.img) {
      ctx.drawImage(state.img, 0, 0, view.w, view.h);
      ctx.fillStyle = 'rgba(11,9,7,0.18)'; // gentle scrim for contrast
      ctx.fillRect(0, 0, view.w, view.h);
    } else {
      drawGrid();
    }
    // Draw every completed/in-progress polygon.
    SLOTS.forEach((s) => drawPoly(s, state.polys[s.id], s.id === state.activeSlot));
  }

  function toPx(p) { return [p[0] * view.w, p[1] * view.h]; }

  function drawPoly(slot, poly, isActive) {
    if (!poly.length) return;
    const isRoom = slot.bucket === BUCKET.ROOM;
    ctx.lineWidth = isActive ? 2.5 : 1.6;
    ctx.strokeStyle = slot.color;
    ctx.fillStyle = hexA(slot.color, isActive ? 0.22 : 0.14);
    ctx.beginPath();
    poly.forEach((p, i) => {
      const [x, y] = toPx(p);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    if (poly.length >= 3) { ctx.closePath(); if (!isRoom) ctx.fill(); else ctx.fill(); }
    ctx.stroke();
    // Vertices.
    poly.forEach((p) => {
      const [x, y] = toPx(p);
      ctx.beginPath(); ctx.arc(x, y, isActive ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fillStyle = slot.color; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#14110e'; ctx.stroke();
    });
    // Label at centroid for finished polys.
    if (poly.length >= 3) {
      const c = centroid(poly).map((v, i) => v * (i === 0 ? view.w : view.h));
      ctx.font = '600 12px system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = '#14110e';
      const tw = ctx.measureText(slot.id).width + 12;
      roundRect(c[0] - tw / 2, c[1] - 9, tw, 18, 6); ctx.fillStyle = slot.color; ctx.fill();
      ctx.fillStyle = '#14110e'; ctx.fillText(slot.id, c[0], c[1]);
    }
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // ---- Geometry helpers ----------------------------------------------------
  function centroid(poly) {
    // Area-weighted centroid; mirrors perception/geometry.py for table meshes.
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < poly.length; i++) {
      const [x0, y0] = poly[i];
      const [x1, y1] = poly[(i + 1) % poly.length];
      const cross = x0 * y1 - x1 * y0;
      a += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross;
    }
    if (Math.abs(a) < 1e-12) { // degenerate -> vertex mean
      const m = poly.reduce((s, p) => [s[0] + p[0], s[1] + p[1]], [0, 0]);
      return [m[0] / poly.length, m[1] / poly.length];
    }
    a *= 0.5;
    return [cx / (6 * a), cy / (6 * a)];
  }

  function clamp01(v) { return Math.min(1, Math.max(0, v)); }

  // ---- Export: the zones.json contract ------------------------------------
  // Exposed for the verify snippet. Takes the polys map -> contract object.
  function buildGeometry(polys) {
    const out = { zones: {}, tables: {}, cleaning: {} };
    Object.keys(polys).forEach((id) => {
      const poly = polys[id];
      if (!poly || poly.length < 3) return; // need >= 3 points per contract
      const slot = slotById[id];
      const norm = poly.map((p) => [clamp01(p[0]), clamp01(p[1])]);
      if (slot.bucket === BUCKET.ROOM) out.room = norm;
      else out[slot.bucket][id] = norm;
    });
    return out;
  }
  // Expose for verification / debugging and for the preset "Pick a shop" flow.
  // (pushGeometry / downloadGeometry / apiBase / toast / refit are assigned once
  // their definitions are reached below.)
  window.GCScan = { buildGeometry, SLOTS, state };

  // ---- Interaction ---------------------------------------------------------
  function canvasPoint(ev) {
    const rect = canvas.getBoundingClientRect();
    const t = ev.touches && ev.touches[0] ? ev.touches[0] : ev;
    const x = (t.clientX - rect.left) / rect.width;
    const y = (t.clientY - rect.top) / rect.height;
    return [clamp01(x), clamp01(y)];
  }

  function addPoint(ev) {
    ev.preventDefault();
    const p = canvasPoint(ev);
    state.polys[state.activeSlot].push(p);
    render(); refreshChips(); notify3d();
  }

  canvas.addEventListener('click', addPoint);
  canvas.addEventListener('touchend', (ev) => {
    // touchend gives a stable point; ignore multi-touch (pinch/zoom).
    if (ev.changedTouches && ev.changedTouches.length === 1) addPoint(ev);
  }, { passive: false });

  // ---- Slot bar ------------------------------------------------------------
  function buildSlotBar() {
    slotBar.innerHTML = '';
    SLOTS.forEach((s) => {
      const b = document.createElement('button');
      b.className = 'slot';
      b.dataset.slot = s.id;
      b.innerHTML = `<span class="swatch" style="background:${s.color}"></span>` +
                    `<span class="slot-label">${s.label}</span>` +
                    `<span class="slot-check" aria-hidden="true">&check;</span>`;
      b.addEventListener('click', () => { state.activeSlot = s.id; refreshChips(); render(); });
      slotBar.appendChild(b);
    });
    refreshChips();
  }

  function refreshChips() {
    [...slotBar.children].forEach((b) => {
      const id = b.dataset.slot;
      const done = (state.polys[id] || []).length >= 3;
      b.setAttribute('aria-selected', id === state.activeSlot ? 'true' : 'false');
      b.classList.toggle('done', done);
    });
    const a = slotById[state.activeSlot];
    statusEl.textContent = a
      ? `Active: ${a.label} — tap the canvas to add points (${state.polys[a.id].length})`
      : '';
  }

  function addTable() {
    const id = 'T' + state.nextTable++;
    const slot = { id, label: 'Table ' + id, bucket: BUCKET.TABLES, color: '#b58fe0' };
    // Insert before restroom for tidy ordering.
    const idx = SLOTS.findIndex((s) => s.id === 'restroom');
    SLOTS.splice(idx < 0 ? SLOTS.length : idx, 0, slot);
    state.polys[id] = [];
    rebuildSlotIndex();
    state.activeSlot = id;
    buildSlotBar(); render(); notify3d();
  }

  // ---- Toolbar actions -----------------------------------------------------
  function undoPoint() { state.polys[state.activeSlot].pop(); render(); refreshChips(); notify3d(); }
  function clearSlot() { state.polys[state.activeSlot] = []; render(); refreshChips(); notify3d(); }
  function closePoly() {
    // "Close" is implicit (polygons auto-close on render/export); this just
    // confirms and advances to the next unfinished slot for a smoother flow.
    const cur = state.polys[state.activeSlot];
    if (cur.length < 3) { flash('Need at least 3 points to close.'); return; }
    const next = SLOTS.find((s) => (state.polys[s.id] || []).length < 3);
    if (next) { state.activeSlot = next.id; refreshChips(); render(); }
    else flash('All slots have geometry.');
  }
  function clearAll() {
    SLOTS.forEach((s) => (state.polys[s.id] = []));
    render(); refreshChips(); notify3d();
  }

  // ---- Capture -------------------------------------------------------------
  function loadImageFromFile(file) {
    if (!file || !/^image\//.test(file.type)) { flash('Please choose an image.'); return; }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { state.img = img; fitCanvas(); URL.revokeObjectURL(url); flash('Photo loaded.'); };
    img.onerror = () => { flash('Could not load that image.'); URL.revokeObjectURL(url); };
    img.src = url;
  }

  function useBlank() { state.img = null; fitCanvas(); flash('Blank grid ready — trace away.'); }

  // Drag & drop.
  ['dragenter', 'dragover'].forEach((t) =>
    stage.addEventListener(t, (e) => { e.preventDefault(); stage.classList.add('drop'); }));
  ['dragleave', 'drop'].forEach((t) =>
    stage.addEventListener(t, (e) => { e.preventDefault(); stage.classList.remove('drop'); }));
  stage.addEventListener('drop', (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) loadImageFromFile(f);
  });

  function onFilePick(e) {
    const f = e.target.files && e.target.files[0];
    if (f) loadImageFromFile(f);
    e.target.value = ''; // allow re-picking the same file
  }
  fileInput.addEventListener('change', onFilePick);
  const galleryInput = $('#galleryInput');
  if (galleryInput) galleryInput.addEventListener('change', onFilePick);

  // ---- Export & push -------------------------------------------------------
  function apiBase() {
    const q = new URLSearchParams(location.search).get('api');
    if (q) return q.replace(/\/$/, '');
    if (location.origin && location.protocol.startsWith('http')) return location.origin;
    return 'https://golden-coffee-production.up.railway.app';
  }

  function validateForExport() {
    const g = buildGeometry(state.polys);
    const errs = [];
    ['entry', 'queue', 'counter', 'seating'].forEach((z) => {
      if (!g.zones[z]) errs.push(`zone "${z}" missing (need >=3 points)`);
    });
    return { g, errs };
  }

  // Trigger a zones.json download for any geometry object (editor or preset).
  function downloadGeometry(g, name) {
    const blob = new Blob([JSON.stringify(g, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name || 'zones.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    flash((name || 'zones.json') + ' downloaded.');
  }

  // POST any geometry object to ${API}/geometry. Shared by the editor and the
  // preset "Push to live" flow so they speak the exact same contract + endpoint.
  async function pushGeometry(g) {
    const url = apiBase() + '/geometry';
    flash('Pushing to ' + url + ' …');
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(g),
      });
      if (res.ok) flash('Pushed to live ☁ — ' + res.status);
      else flash('Push failed: ' + res.status + ' ' + res.statusText, true);
      return res;
    } catch (e) {
      flash('Push error: ' + (e && e.message ? e.message : e), true);
      throw e;
    }
  }

  function downloadJSON() {
    const { g, errs } = validateForExport();
    if (errs.length) flash('Heads up: ' + errs.join('; '), true);
    downloadGeometry(g, 'zones.json');
  }

  async function pushLive() {
    const { g, errs } = validateForExport();
    if (errs.length && !confirm('Geometry incomplete:\n' + errs.join('\n') + '\n\nPush anyway?')) return;
    return pushGeometry(g);
  }

  // ---- 3D bridge -----------------------------------------------------------
  function notify3d() {
    if (window.GCScan3D && window.GCScan3D.update) {
      try { window.GCScan3D.update(buildGeometry(state.polys)); } catch (e) { /* ignore */ }
    }
  }

  // ---- Misc UI -------------------------------------------------------------
  let flashTimer;
  function flash(msg, isErr) {
    const el = $('#toast');
    el.textContent = msg;
    el.className = 'toast show' + (isErr ? ' err' : '');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (el.className = 'toast'), 3200);
  }

  function togglePreview() {
    const panel = $('#preview');
    const open = panel.classList.toggle('open');
    $('#togglePreview').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open && window.GCScan3D) {
      window.GCScan3D.ensure();
      notify3d();
      window.GCScan3D.resize && window.GCScan3D.resize();
      // After the open transition, resize again (height animates) and bring the
      // panel into view on short screens where the page now scrolls.
      setTimeout(() => {
        window.GCScan3D.resize && window.GCScan3D.resize();
        try { panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) { /* noop */ }
      }, 280);
    }
  }

  // ---- Wire up -------------------------------------------------------------
  $('#useBlank').addEventListener('click', useBlank);
  $('#addTable').addEventListener('click', addTable);
  $('#undo').addEventListener('click', undoPoint);
  $('#clearSlot').addEventListener('click', clearSlot);
  $('#close').addEventListener('click', closePoly);
  $('#clearAll').addEventListener('click', clearAll);
  $('#download').addEventListener('click', downloadJSON);
  $('#push').addEventListener('click', pushLive);
  $('#togglePreview').addEventListener('click', togglePreview);

  window.addEventListener('resize', fitCanvas);

  // Extend the public surface for the preset gallery / home flow (home.js).
  Object.assign(window.GCScan, {
    pushGeometry, downloadGeometry, apiBase, refit: fitCanvas, toast: flash,
  });

  buildSlotBar();
  fitCanvas();

  // ---- Service worker registration (guarded) ------------------------------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./sw.js').catch(() => { /* offline cache optional */ });
    });
  }
})();
