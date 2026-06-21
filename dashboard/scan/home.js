/* Caffe Steve — home gallery & simplified flow.
 *
 * Default path is two taps: pick a coffee-shop card -> the layout loads into the
 * shared live 3D twin -> "Use this layout -> Push to live" POSTs the exact
 * zones.json contract to ${API}/geometry. "Scan my own (advanced)" reveals the
 * original photo->trace editor (untouched, just demoted off the default path).
 *
 * The single WebGL renderer (#canvas3d, driven by scan3d.js) is re-parented
 * between the preset twin and the advanced preview so there is only ever one
 * GL context.
 */
(function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const presets = window.GC_PRESETS || [];

  // Zone / feature colors for the flat 2D mini-plan thumbnails on the cards.
  const MINI = {
    entry: '#9aa0a6', queue: '#6fb6e0', counter: '#d9a441', seating: '#7ed87e',
    off: '#86c79a', restroom: '#e0876f', table: '#b58fe0', room: '#e7c074',
  };

  // ---- Shared 3D host relocation ------------------------------------------
  const canvas3d = $('#canvas3d');

  function relocate(target) {
    if (!canvas3d || !target) return;
    canvas3d.removeAttribute('hidden');
    if (canvas3d.parentNode !== target) target.appendChild(canvas3d);
  }
  function parkCanvas() {
    if (!canvas3d) return;
    canvas3d.setAttribute('hidden', '');
    if (canvas3d.parentNode !== document.body) document.body.appendChild(canvas3d);
  }
  function render3d(geom) {
    const D = window.GCScan3D;
    if (!D) return;
    D.ensure();
    D.update(geom);
    D.resize && D.resize();
    // Height/width animate in; resize again after layout settles.
    setTimeout(() => D.resize && D.resize(), 60);
    setTimeout(() => D.resize && D.resize(), 320);
  }

  // ---- View routing --------------------------------------------------------
  function setView(name) {
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    const el = document.getElementById('view-' + name);
    if (el) el.classList.add('active');
    try { window.scrollTo({ top: 0, behavior: 'instant' }); } catch (e) { window.scrollTo(0, 0); }
  }

  // ---- 2D mini-plan thumbnails --------------------------------------------
  function drawMini(canvas, geom) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = canvas.clientWidth || 96, ch = canvas.clientHeight || 84;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = cw, H = ch;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0b0907'; ctx.fillRect(0, 0, W, H);

    const fillPoly = (poly, fill, stroke) => {
      if (!poly || poly.length < 3) return;
      ctx.beginPath();
      poly.forEach((p, i) => { const x = p[0] * W, y = p[1] * H; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.lineWidth = 1; ctx.strokeStyle = stroke; ctx.stroke(); }
    };
    const a = (hex, al) => { const n = parseInt(hex.slice(1), 16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${al})`; };

    // room outline
    if (geom.room) { fillPoly(geom.room, a(MINI.room, 0.06), a(MINI.room, 0.5)); }
    // zones
    Object.keys(geom.zones || {}).forEach((k) => {
      const c = MINI[k] || '#888';
      fillPoly(geom.zones[k], a(c, k === 'counter' ? 0.5 : 0.32), a(c, 0.85));
    });
    // cleaning
    Object.keys(geom.cleaning || {}).forEach((k) => fillPoly(geom.cleaning[k], a(MINI.restroom, 0.4), a(MINI.restroom, 0.85)));
    // tables
    Object.keys(geom.tables || {}).forEach((k) => fillPoly(geom.tables[k], MINI.table, '#14110e'));
  }

  // ---- Preset preview ------------------------------------------------------
  let current = null;

  function openPreset(p) {
    current = p;
    $('#presetName').textContent = p.name;
    $('#presetBlurb').textContent = p.blurb;
    setView('preset');
    relocate($('#presetStage'));
    render3d(p.geometry);
  }

  // ---- Build the gallery ---------------------------------------------------
  function buildGallery() {
    const grid = $('#presetGrid');
    if (!grid) return;
    grid.innerHTML = '';
    presets.forEach((p) => {
      const card = document.createElement('button');
      card.className = 'card'; card.type = 'button'; card.setAttribute('role', 'listitem');
      card.setAttribute('aria-label', p.name);
      card.innerHTML =
        '<div class="thumb"><canvas></canvas></div>' +
        '<div class="meta">' +
          '<div class="nm">' + p.name + '</div>' +
          '<div class="bl">' + p.blurb + '</div>' +
          '<div class="go">Open in 3D &rarr;</div>' +
        '</div>';
      card.addEventListener('click', () => openPreset(p));
      grid.appendChild(card);
      const cv = card.querySelector('canvas');
      // Draw after layout so clientWidth/Height are known.
      requestAnimationFrame(() => drawMini(cv, p.geometry));
    });
  }

  // ---- Wire up -------------------------------------------------------------
  function wire() {
    $('#presetBack').addEventListener('click', () => { parkCanvas(); setView('home'); });
    $('#presetPush').addEventListener('click', () => {
      if (current && window.GCScan && window.GCScan.pushGeometry) window.GCScan.pushGeometry(current.geometry);
    });
    $('#presetDownload').addEventListener('click', () => {
      if (current && window.GCScan && window.GCScan.downloadGeometry) {
        window.GCScan.downloadGeometry(current.geometry, current.id + '.zones.json');
      }
    });

    $('#openAdvanced').addEventListener('click', () => {
      setView('advanced');
      relocate($('#advPreviewHost'));
      window.GCScan && window.GCScan.refit && window.GCScan.refit();
    });
    $('#advBack').addEventListener('click', () => { parkCanvas(); setView('home'); });
  }

  buildGallery();
  wire();

  // Expose a tiny hook for the Playwright verification harness.
  window.GCHome = { openPreset, setView, presets };

  // Redraw thumbnails on resize / orientation change so they stay crisp.
  window.addEventListener('resize', () => {
    document.querySelectorAll('#presetGrid .card').forEach((card, i) => {
      const cv = card.querySelector('canvas');
      if (cv && presets[i]) drawMini(cv, presets[i].geometry);
    });
  });
})();
