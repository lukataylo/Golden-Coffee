/* Golden Coffee Floorplan Scanner — live 3D twin.
 *
 * Consumes the zones.json contract (zones/tables/cleaning + optional room) and
 * builds an extruded scene: colored zone slabs in the XZ plane, thin walls along
 * the room outline, and box/cylinder tables at table centroids. Degrades to a
 * message if WebGL or Three.js is unavailable; the 2D editor keeps working.
 *
 * Coordinate map: normalized (x,y) in [0..1] -> world (x - 0.5, ., y - 0.5) * SIZE,
 * so the floor is centered on the origin. y (image down) maps to +z (depth).
 */
(function () {
  'use strict';

  const SIZE = 10;           // world units across the floor
  const ZONE_H = 0.12;       // zone slab thickness
  const WALL_H = 2.2;        // wall height
  const WALL_T = 0.12;       // wall thickness

  const COLORS = {
    entry: 0x9aa0a6, queue: 0x6fb6e0, counter: 0xd9a441, seating: 0x7ed87e,
    restroom: 0xe0876f, table: 0xb58fe0, room: 0xe7c074, floor: 0x1d1813,
  };

  let THREE, renderer, scene, camera, controls;
  let group;                 // holds all generated geometry
  let started = false, failed = false;
  let autoRotate = true, dragging = false;
  let theta = 0.7, phi = 0.95, radius = 16; // orbit params
  let lastGeom = null;

  const host = () => document.getElementById('canvas3d');
  const msgEl = () => document.getElementById('preview-msg');

  function showMsg(text) { const m = msgEl(); if (m) { m.textContent = text; m.style.display = text ? 'flex' : 'none'; } }

  function webglOK() {
    try {
      const c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext &&
        (c.getContext('webgl') || c.getContext('experimental-webgl')));
    } catch (e) { return false; }
  }

  function ensure() {
    if (started || failed) return started;
    THREE = window.THREE;
    if (!THREE) { failed = true; showMsg('3D unavailable: Three.js failed to load. The 2D editor still works.'); return false; }
    if (!webglOK()) { failed = true; showMsg('3D unavailable: WebGL is not supported here. The 2D editor still works.'); return false; }

    const el = host();
    const w = el.clientWidth || 320, h = el.clientHeight || 240;

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (e) {
      failed = true; showMsg('3D unavailable: ' + (e.message || e)); return false;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    el.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    scene.background = null;

    camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 200);
    placeCamera();

    // Soft lighting.
    scene.add(new THREE.AmbientLight(0xfff2dd, 0.65));
    const key = new THREE.DirectionalLight(0xffe8c4, 0.9);
    key.position.set(8, 14, 6); scene.add(key);
    const fill = new THREE.DirectionalLight(0x6fb6e0, 0.25);
    fill.position.set(-8, 6, -6); scene.add(fill);

    // Base floor.
    const floorGeo = new THREE.PlaneGeometry(SIZE * 1.05, SIZE * 1.05);
    const floorMat = new THREE.MeshStandardMaterial({ color: COLORS.floor, roughness: 0.95, metalness: 0.0 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2; floor.position.y = -0.01; scene.add(floor);

    group = new THREE.Group(); scene.add(group);

    bindControls(el);
    started = true;
    showMsg('');
    animate();
    if (lastGeom) update(lastGeom);
    return true;
  }

  function placeCamera() {
    const x = radius * Math.sin(phi) * Math.cos(theta);
    const z = radius * Math.sin(phi) * Math.sin(theta);
    const y = radius * Math.cos(phi);
    camera.position.set(x, Math.max(2, y), z);
    camera.lookAt(0, 0.5, 0);
  }

  // Minimal orbit controls (no external dependency).
  function bindControls(el) {
    let px = 0, py = 0;
    const down = (e) => { dragging = true; autoRotate = false; const t = pt(e); px = t.x; py = t.y; };
    const move = (e) => {
      if (!dragging) return;
      const t = pt(e); const dx = t.x - px, dy = t.y - py; px = t.x; py = t.y;
      theta -= dx * 0.01;
      phi = Math.min(Math.PI / 2.05, Math.max(0.25, phi - dy * 0.01));
      placeCamera();
      e.preventDefault && e.preventDefault();
    };
    const up = () => { dragging = false; };
    el.addEventListener('mousedown', down);
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    el.addEventListener('touchstart', down, { passive: true });
    el.addEventListener('touchmove', move, { passive: false });
    el.addEventListener('touchend', up);
    el.addEventListener('wheel', (e) => {
      radius = Math.min(40, Math.max(6, radius + Math.sign(e.deltaY) * 1.2));
      placeCamera(); e.preventDefault();
    }, { passive: false });
  }
  function pt(e) {
    const t = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
    return { x: t.clientX || 0, y: t.clientY || 0 };
  }

  function toWorld(p) { return [(p[0] - 0.5) * SIZE, (p[1] - 0.5) * SIZE]; }

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

  function clearGroup() {
    if (!group) return;
    for (let i = group.children.length - 1; i >= 0; i--) {
      const o = group.children[i];
      o.geometry && o.geometry.dispose();
      o.material && o.material.dispose();
      group.remove(o);
    }
  }

  // Build an extruded slab from a normalized polygon in the XZ plane.
  function slab(poly, color, height, y) {
    const shape = new THREE.Shape();
    poly.forEach((p, i) => {
      const [x, z] = toWorld(p);
      if (i === 0) shape.moveTo(x, z); else shape.lineTo(x, z);
    });
    shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);     // shape's XY plane -> world XZ
    geo.translate(0, (y || 0) + height, 0);
    const mat = new THREE.MeshStandardMaterial({
      color, roughness: 0.7, metalness: 0.05, transparent: true, opacity: 0.92,
    });
    return new THREE.Mesh(geo, mat);
  }

  // Thin wall segments along the room outline edges.
  function buildWalls(poly) {
    const mat = new THREE.MeshStandardMaterial({ color: COLORS.room, roughness: 0.85, metalness: 0.04, transparent: true, opacity: 0.5 });
    for (let i = 0; i < poly.length; i++) {
      const a = toWorld(poly[i]); const b = toWorld(poly[(i + 1) % poly.length]);
      const dx = b[0] - a[0], dz = b[1] - a[1];
      const len = Math.hypot(dx, dz);
      if (len < 1e-3) continue;
      const geo = new THREE.BoxGeometry(len, WALL_H, WALL_T);
      const m = new THREE.Mesh(geo, mat);
      m.position.set((a[0] + b[0]) / 2, WALL_H / 2, (a[1] + b[1]) / 2);
      m.rotation.y = -Math.atan2(dz, dx);
      group.add(m);
    }
  }

  function buildTable(poly) {
    const c = toWorld(centroid(poly));
    const mat = new THREE.MeshStandardMaterial({ color: COLORS.table, roughness: 0.5, metalness: 0.1 });
    // Approximate footprint radius from the polygon extent.
    let minx = 1, miny = 1, maxx = 0, maxy = 0;
    poly.forEach((p) => { minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]); miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]); });
    const r = Math.max(0.25, Math.min((maxx - minx), (maxy - miny)) * SIZE * 0.5);
    const geo = new THREE.CylinderGeometry(r, r, 0.75, 20);
    const m = new THREE.Mesh(geo, mat);
    m.position.set(c[0], 0.45, c[1]);
    group.add(m);
    // Leg/pedestal.
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.18, r * 0.22, 0.45, 12), mat);
    leg.position.set(c[0], 0.22, c[1]); group.add(leg);
  }

  function update(geom) {
    lastGeom = geom;
    if (!started) return; // will be applied when ensure() runs
    clearGroup();

    if (geom.room && geom.room.length >= 3) buildWalls(geom.room);

    const zorder = { entry: 0, queue: 1, counter: 2, seating: 3 };
    Object.keys(geom.zones || {}).forEach((k) => {
      const poly = geom.zones[k];
      if (poly && poly.length >= 3) {
        const col = COLORS[k] || 0x888888;
        group.add(slab(poly, col, ZONE_H, (zorder[k] || 0) * 0.002));
      }
    });
    Object.keys(geom.cleaning || {}).forEach((k) => {
      const poly = geom.cleaning[k];
      if (poly && poly.length >= 3) group.add(slab(poly, COLORS[k] || COLORS.restroom, ZONE_H, 0.01));
    });
    Object.keys(geom.tables || {}).forEach((k) => {
      const poly = geom.tables[k];
      if (poly && poly.length >= 3) buildTable(poly);
    });
  }

  function resize() {
    if (!started) return;
    const el = host();
    const w = el.clientWidth || 320, h = el.clientHeight || 240;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }

  function animate() {
    if (!started) return;
    requestAnimationFrame(animate);
    if (autoRotate && !dragging) { theta += 0.0025; placeCamera(); }
    renderer.render(scene, camera);
  }

  window.GCScan3D = {
    ensure, update, resize,
    toggleRotate: () => (autoRotate = !autoRotate),
  };

  window.addEventListener('resize', resize);
})();
