/*
 * Golden Coffee — isometric 3D floor map (P0 from FLOORMAP_RESEARCH.md).
 *
 * Extrudes the dashboard's normalized zone bands into a Three.js isometric
 * "digital twin" and binds it to live SceneEvent state: zone occupancy heat,
 * per-zone head-count, anonymous track people, table-status discs, a staff-alert
 * beacon, and — the differentiator — the agent's *comfort actions* made visible
 * (room light brightness/warmth follow set_lighting; a counter ring pulses with
 * set_music_volume). Procedural café furniture (counter, espresso machine, pastry
 * case, queue posts, café tables + chairs, door) makes it read as a real place.
 * No build step, no assets: one vendored Three.js (UMD) + this file, fully offline.
 *
 * Public API (window.Floor3D):
 *   init(canvas, cfg)  cfg = { zones, zoneColors, intensityFn, occColorFn }
 *   available()        -> bool   (THREE present AND a WebGL context is creatable)
 *   setActive(on)      start/stop the render loop (call when the view shows/hides)
 *   update(scene, comfort)       push the latest SceneEvent + comfort state
 *   flashAlert(zone, text)       pulse a beacon over a zone for ~6s
 *   resize()                     re-fit to the canvas's current box
 */
(function () {
  "use strict";

  var T = (typeof window !== "undefined") ? window.THREE : null;

  // ---- world scale (normalized 0..1 frame coords -> world units) ----
  var FW = 11, FD = 7;              // floor width (x) / depth (z)
  var WALL_H = 1.5;

  function wx(nx) { return (nx - 0.5) * FW; }
  function wz(ny) { return (ny - 0.5) * FD; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function parseHex(hex) {
    var h = String(hex || "#888888").replace("#", "");
    return { r: parseInt(h.substr(0, 2), 16) / 255, g: parseInt(h.substr(2, 2), 16) / 255, b: parseInt(h.substr(4, 2), 16) / 255 };
  }
  function col(hex) { var c = parseHex(hex); return new T.Color(c.r, c.g, c.b); }

  var S = null;

  // ---------- procedural textures ----------
  function woodTexture() {
    var cv = document.createElement("canvas"); cv.width = cv.height = 512;
    var x = cv.getContext("2d");
    x.fillStyle = "#5b4631"; x.fillRect(0, 0, 512, 512);
    for (var p = 0; p < 8; p++) {                       // planks
      var px = p * 64, shade = 86 + ((p * 53) % 30);
      x.fillStyle = "rgb(" + (shade + 10) + "," + (shade - 14) + "," + (shade - 38) + ")";
      x.fillRect(px, 0, 62, 512);
      for (var g = 0; g < 28; g++) {                    // grain
        x.strokeStyle = "rgba(40,28,18," + (0.04 + Math.random() * 0.06) + ")";
        x.lineWidth = 1; x.beginPath();
        var gy = Math.random() * 512;
        x.moveTo(px + 2, gy); x.bezierCurveTo(px + 20, gy + 6, px + 40, gy - 6, px + 60, gy + 2); x.stroke();
      }
      x.fillStyle = "rgba(20,12,6,0.5)"; x.fillRect(px + 62, 0, 2, 512); // seam
    }
    var tex = new T.CanvasTexture(cv);
    tex.wrapS = tex.wrapT = T.RepeatWrapping; tex.repeat.set(3, 2);
    if (T.sRGBEncoding) tex.encoding = T.sRGBEncoding;
    tex.anisotropy = 4;
    return tex;
  }

  // soft round glow texture (heat rugs, contact shadows)
  function radialTexture(inner, outer) {
    var cv = document.createElement("canvas"); cv.width = cv.height = 128;
    var x = cv.getContext("2d");
    var g = x.createRadialGradient(64, 64, 4, 64, 64, 64);
    g.addColorStop(0, inner); g.addColorStop(1, outer);
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
    return new T.CanvasTexture(cv);
  }

  // rounded-rect flat shape (for zone rugs), laid in the XZ plane
  function roundedRug(w, h, r, mat) {
    var s = new T.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y);
    s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    var geo = new T.ShapeGeometry(s);
    var m = new T.Mesh(geo, mat); m.rotation.x = -Math.PI / 2;
    return m;
  }

  // floating rounded label chip
  function makeChip(text) {
    var cv = document.createElement("canvas"); cv.width = 320; cv.height = 96;
    var tex = new T.CanvasTexture(cv); tex.minFilter = T.LinearFilter;
    var mat = new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false });
    var sp = new T.Sprite(mat); sp.scale.set(2.15, 0.645, 1); sp.renderOrder = 20;
    sp.userData = { cv: cv, tex: tex, last: "" };
    return sp;
  }
  function drawChip(chip, title, count) {
    var key = title + "|" + count; if (chip.userData.last === key) return;
    chip.userData.last = key;
    var cv = chip.userData.cv, x = cv.getContext("2d");
    x.clearRect(0, 0, cv.width, cv.height);
    var w = cv.width, h = cv.height, r = 26;
    x.fillStyle = "rgba(18,14,10,0.82)";
    x.beginPath();
    x.moveTo(r, 6); x.lineTo(w - r, 6); x.quadraticCurveTo(w - 4, 6, w - 4, 6 + r);
    x.lineTo(w - 4, h - r); x.quadraticCurveTo(w - 4, h - 4, w - r, h - 4);
    x.lineTo(r, h - 4); x.quadraticCurveTo(4, h - 4, 4, h - r);
    x.lineTo(4, 6 + r); x.quadraticCurveTo(4, 6, r, 6); x.fill();
    x.strokeStyle = "rgba(231,192,116,0.35)"; x.lineWidth = 2; x.stroke();
    x.textAlign = "left"; x.textBaseline = "middle";
    x.font = "700 30px system-ui, sans-serif"; x.fillStyle = "rgba(243,237,227,0.95)";
    x.fillText(title.toUpperCase(), 26, 38);
    x.font = "600 26px system-ui, sans-serif"; x.fillStyle = "rgba(231,192,116,0.95)";
    x.fillText(count + (count === 1 ? " person" : " people"), 26, 72);
    chip.userData.tex.needsUpdate = true;
  }

  // ---------- furniture primitives ----------
  function box(w, h, d, color, opts) {
    opts = opts || {};
    var m = new T.Mesh(new T.BoxGeometry(w, h, d),
      new T.MeshStandardMaterial({ color: col(color), roughness: opts.rough == null ? 0.7 : opts.rough,
        metalness: opts.metal || 0, transparent: !!opts.opacity, opacity: opts.opacity == null ? 1 : opts.opacity }));
    m.castShadow = !opts.noShadow; m.receiveShadow = true;
    return m;
  }
  function cyl(rt, rb, h, color, opts) {
    opts = opts || {};
    var m = new T.Mesh(new T.CylinderGeometry(rt, rb, h, opts.seg || 20),
      new T.MeshStandardMaterial({ color: col(color), roughness: opts.rough == null ? 0.6 : opts.rough, metalness: opts.metal || 0 }));
    m.castShadow = true; m.receiveShadow = true; return m;
  }

  function buildCounter(zone) {
    var g = new T.Group();
    var cx = wx(zone.x + zone.w / 2), w = zone.w * FW * 0.86;
    // counter body + warm wood top
    var bodyZ = wz(0.74);
    var base = box(w, 1.0, 0.7, "#241d17", { rough: 0.85 }); base.position.set(cx, 0.5, bodyZ); g.add(base);
    var top = box(w + 0.1, 0.12, 0.82, "#7a5836", { rough: 0.5 }); top.position.set(cx, 1.06, bodyZ); g.add(top);
    // espresso machine (metallic) with two group heads
    var em = box(0.7, 0.5, 0.5, "#cfd3d8", { metal: 0.85, rough: 0.3 }); em.position.set(cx - w * 0.28, 1.37, bodyZ); g.add(em);
    [-0.14, 0.14].forEach(function (o) {
      var gh = cyl(0.05, 0.06, 0.18, "#3a3a3e", { metal: 0.6, rough: 0.4 });
      gh.position.set(cx - w * 0.28 + o, 1.16, bodyZ + 0.27); g.add(gh);
    });
    var wand = cyl(0.012, 0.012, 0.22, "#9fa3a8", { metal: 0.8 });
    wand.position.set(cx - w * 0.28 + 0.24, 1.2, bodyZ + 0.22); wand.rotation.z = 0.5; g.add(wand);
    // pastry case (glass) on the counter
    var glass = box(0.95, 0.42, 0.6, "#bfe0ff", { opacity: 0.22, rough: 0.05, metal: 0.1, noShadow: true });
    glass.position.set(cx + w * 0.22, 1.33, bodyZ); g.add(glass);
    [-0.18, 0, 0.18].forEach(function (o, i) {
      var p = box(0.18, 0.06, 0.34, i === 1 ? "#d8a657" : "#caa06a", { rough: 0.6, noShadow: true });
      p.position.set(cx + w * 0.22 + o, 1.16, bodyZ); g.add(p);
    });
    return g;
  }

  function buildQueuePosts(zone) {
    var g = new T.Group();
    var n = 3, x0 = zone.x + 0.18 * zone.w, x1 = zone.x + 0.82 * zone.w;
    var pts = [];
    for (var i = 0; i < n; i++) {
      var nx = x0 + (x1 - x0) * (i / (n - 1));
      var post = cyl(0.045, 0.06, 0.95, "#c8ccd2", { metal: 0.85, rough: 0.25 });
      post.position.set(wx(nx), 0.47, wz(0.5)); g.add(post);
      var cap = new T.Mesh(new T.SphereGeometry(0.08, 14, 14),
        new T.MeshStandardMaterial({ color: col("#e7c074"), metal: 0.7, roughness: 0.3, metalness: 0.7 }));
      cap.position.set(wx(nx), 0.98, wz(0.5)); cap.castShadow = true; g.add(cap);
      pts.push(new T.Vector3(wx(nx), 0.8, wz(0.5)));
    }
    for (var k = 0; k < pts.length - 1; k++) {           // hanging ropes
      var a = pts[k], b = pts[k + 1], mid = a.clone().add(b).multiplyScalar(0.5); mid.y -= 0.18;
      var curve = new T.QuadraticBezierCurve3(a, mid, b);
      var rope = new T.Mesh(new T.TubeGeometry(curve, 12, 0.022, 6, false),
        new T.MeshStandardMaterial({ color: col("#6b3f2a"), roughness: 0.8 }));
      g.add(rope);
    }
    return g;
  }

  function buildChairs(cx, cz) {
    var g = new T.Group();
    [[0, 0.62], [0, -0.62], [0.62, 0], [-0.62, 0]].forEach(function (o) {
      var seat = box(0.34, 0.08, 0.34, "#4a3b2e", { rough: 0.8 });
      seat.position.set(cx + o[0], 0.42, cz + o[1]); g.add(seat);
      var legc = box(0.34, 0.42, 0.06, "#3a2e23", { rough: 0.8, noShadow: true });
      legc.position.set(cx + o[0] + (o[0] > 0 ? 0.14 : o[0] < 0 ? -0.14 : 0), 0.46, cz + o[1] + (o[1] > 0 ? 0.14 : o[1] < 0 ? -0.14 : 0));
      g.add(legc);
    });
    return g;
  }

  function buildDoor(zone) {
    var g = new T.Group();
    var cx = wx(zone.x + zone.w / 2), z = wz(0.5), gap = 0.55;
    [-1, 1].forEach(function (s) {
      var jamb = box(0.12, WALL_H, 0.14, "#2c2622", { rough: 0.7 });
      jamb.position.set(cx + s * gap, WALL_H / 2, z); g.add(jamb);
    });
    var lintel = box(gap * 2 + 0.24, 0.16, 0.14, "#2c2622", { rough: 0.7 });
    lintel.position.set(cx, WALL_H - 0.08, z); g.add(lintel);
    var mat = roundedRug(1.1, 0.7, 0.12, new T.MeshStandardMaterial({ color: col("#3a2f25"), roughness: 0.95 }));
    mat.position.set(cx, 0.02, z + 0.5); g.add(mat);
    return g;
  }

  // ---------- main ----------
  var Floor3D = {
    available: function () {
      if (!T) return false;
      try {
        var c = document.createElement("canvas");
        return !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl")));
      } catch (e) { return false; }
    },

    init: function (canvas, cfg) {
      if (S || !this.available()) return !!S;
      cfg = cfg || {};
      var zones = cfg.zones || [];

      var renderer;
      try { renderer = new T.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true }); }
      catch (e) { return false; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
      if (T.sRGBEncoding) renderer.outputEncoding = T.sRGBEncoding;
      if (T.ACESFilmicToneMapping) { renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1; }

      var scene = new T.Scene();
      scene.fog = new T.Fog(0x0c0a08, 22, 40);

      // soft procedural environment so standard materials get gentle reflections
      try {
        var ec = document.createElement("canvas"); ec.width = 16; ec.height = 64;
        var eg = ec.getContext("2d"), grd = eg.createLinearGradient(0, 0, 0, 64);
        grd.addColorStop(0, "#494256"); grd.addColorStop(0.55, "#6c625a"); grd.addColorStop(1, "#15110d");
        eg.fillStyle = grd; eg.fillRect(0, 0, 16, 64);
        var etex = new T.CanvasTexture(ec); etex.mapping = T.EquirectangularReflectionMapping;
        var pmrem = new T.PMREMGenerator(renderer);
        scene.environment = pmrem.fromEquirectangular(etex).texture;
        etex.dispose(); pmrem.dispose();
      } catch (e) { /* envmap optional */ }

      var cam = new T.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);

      // lighting: warm key + sky/ground fill + cool rim
      var hemi = new T.HemisphereLight(0xfff1dc, 0x2a2018, 0.7); scene.add(hemi);
      var key = new T.DirectionalLight(0xfff0d8, 2.0);
      key.position.set(7, 13, 6); key.castShadow = true;
      key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0004; key.shadow.radius = 4;
      var sc = key.shadow.camera; sc.left = -10; sc.right = 10; sc.top = 10; sc.bottom = -10; sc.near = 1; sc.far = 40;
      scene.add(key);
      var rim = new T.DirectionalLight(0x95b4ff, 0.35); rim.position.set(-7, 6, -7); scene.add(rim);

      // base plate (recessed) + wood floor
      var plate = box(FW + 1.0, 0.5, FD + 1.0, "#16110c", { rough: 1, noShadow: true });
      plate.position.y = -0.26; plate.castShadow = false; scene.add(plate);
      var floorMat = new T.MeshStandardMaterial({ map: woodTexture(), roughness: 0.82, metalness: 0.04 });
      var floor = new T.Mesh(new T.BoxGeometry(FW, 0.12, FD), floorMat);
      floor.position.y = 0; floor.receiveShadow = true; scene.add(floor);

      // frosted glass perimeter walls with bright edge trim
      var wallMat = new T.MeshStandardMaterial({ color: col("#aebfce"), transparent: true, opacity: 0.08,
        roughness: 0.15, metalness: 0.1, side: T.DoubleSide });
      var edgeMat = new T.LineBasicMaterial({ color: 0x9fb0c4, transparent: true, opacity: 0.45 });
      function wall(w, d, x, z) {
        var geo = new T.BoxGeometry(w, WALL_H, d);
        var m = new T.Mesh(geo, wallMat); m.position.set(x, WALL_H / 2, z); scene.add(m);
        var e = new T.LineSegments(new T.EdgesGeometry(geo), edgeMat); e.position.copy(m.position); scene.add(e);
      }
      wall(FW + 0.3, 0.06, 0, -FD / 2); wall(FW + 0.3, 0.06, 0, FD / 2);
      wall(0.06, FD + 0.3, -FW / 2, 0); wall(0.06, FD + 0.3, FW / 2, 0);

      // zone rugs (static tint) + heat overlays (driven by occupancy)
      var heatTex = radialTexture("rgba(255,255,255,0.95)", "rgba(255,255,255,0)");
      var zoneHeat = {}, zoneChips = {};
      zones.forEach(function (z, zi) {
        var w = z.w * FW - 0.3, d = FD - 0.5, cx = wx(z.x + z.w / 2);
        var base = (cfg.zoneColors && cfg.zoneColors[z.z]) || "#7d7263";
        var rug = roundedRug(w, d, 0.25, new T.MeshStandardMaterial({
          color: col(base), roughness: 0.92, metalness: 0, transparent: true, opacity: 0.22 }));
        rug.position.set(cx, 0.065, 0); rug.receiveShadow = true; scene.add(rug);
        var heat = roundedRug(w, d, 0.25, new T.MeshBasicMaterial({
          map: heatTex, color: col(base), transparent: true, opacity: 0, blending: T.AdditiveBlending, depthWrite: false }));
        heat.position.set(cx, 0.07, 0); heat.renderOrder = 2; scene.add(heat);
        zoneHeat[z.z] = heat;
        var chip = makeChip(z.label || z.z);
        // stagger height by index so adjacent (narrow) zones' labels don't collide
        var hy = 1.55 + (zi % 2) * 0.62;
        chip.position.set(cx, hy, -d / 2 + 0.3); scene.add(chip); zoneChips[z.z] = chip;
      });

      // furniture per zone
      var byName = {}; zones.forEach(function (z) { byName[z.z] = z; });
      if (byName.counter) scene.add(buildCounter(byName.counter));
      if (byName.queue) scene.add(buildQueuePosts(byName.queue));
      if (byName.entry) scene.add(buildDoor(byName.entry));

      // café tables (status-bound) + chairs, inside the seating band
      var seating = byName.seating, tableMeshes = {};
      var TBL = [{ id: "T1", nx: 0.20, ny: 0.30 }, { id: "T2", nx: 0.54, ny: 0.64 }, { id: "T3", nx: 0.84, ny: 0.32 }];
      if (seating) TBL.forEach(function (slot) {
        var nx = seating.x + slot.nx * seating.w, cx = wx(nx), cz = wz(slot.ny);
        scene.add(buildChairs(cx, cz));
        var pole = cyl(0.05, 0.07, 0.5, "#2c2622", { rough: 0.6 }); pole.position.set(cx, 0.27, cz); scene.add(pole);
        var topMat = new T.MeshStandardMaterial({ color: col("#6b5d4a"), roughness: 0.5, emissive: col("#000000"), emissiveIntensity: 0.4 });
        var top = new T.Mesh(new T.CylinderGeometry(0.44, 0.44, 0.08, 28), topMat);
        top.position.set(cx, 0.55, cz); top.castShadow = true; top.receiveShadow = true; scene.add(top);
        tableMeshes[slot.id] = top;
      });

      // music ring near the counter
      var counter = byName.counter;
      var musicRing = new T.Mesh(new T.TorusGeometry(0.55, 0.05, 14, 48),
        new T.MeshStandardMaterial({ color: col("#e7c074"), emissive: col("#e7c074"), emissiveIntensity: 0.7, transparent: true, opacity: 0, toneMapped: false }));
      musicRing.rotation.x = Math.PI / 2;
      musicRing.position.set(wx(counter ? counter.x + counter.w / 2 : 0.5), 0.3, wz(0.5)); scene.add(musicRing);

      // staff-alert beacon
      var beacon = new T.Group();
      var colm = new T.Mesh(new T.CylinderGeometry(0.1, 0.36, 2.0, 22, 1, true),
        new T.MeshBasicMaterial({ color: 0xff5a46, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false, blending: T.AdditiveBlending }));
      colm.position.y = 1.0; beacon.add(colm);
      beacon.userData = { colm: colm }; scene.add(beacon);

      // CCTV on the back wall + faint FOV
      var cam3 = new T.Group();
      var camBody = box(0.34, 0.2, 0.2, "#1c1813", { rough: 0.5 }); cam3.add(camBody);
      var lens = cyl(0.07, 0.07, 0.12, "#0a0a0c", { metal: 0.6, rough: 0.3 }); lens.rotation.x = Math.PI / 2; lens.position.set(0, -0.02, 0.14); cam3.add(lens);
      cam3.position.set(0, WALL_H - 0.25, -FD / 2 + 0.18); scene.add(cam3);

      // contact-shadow + person pool
      var shadowTex = radialTexture("rgba(0,0,0,0.5)", "rgba(0,0,0,0)");
      var pool = [];
      function makePerson() {
        var g = new T.Group();
        var bodyMat = new T.MeshStandardMaterial({ color: col("#f3ede3"), roughness: 0.55, emissive: col("#000000"), emissiveIntensity: 0.0 });
        var body = new T.Mesh(new T.CylinderGeometry(0.13, 0.17, 0.46, 16), bodyMat); body.position.y = 0.33; body.castShadow = true; g.add(body);
        var head = new T.Mesh(new T.SphereGeometry(0.13, 18, 18), bodyMat); head.position.y = 0.66; head.castShadow = true; g.add(head);
        var glow = new T.Mesh(new T.SphereGeometry(0.3, 16, 16),
          new T.MeshBasicMaterial({ color: 0xffe6b0, transparent: true, opacity: 0.12, depthWrite: false })); glow.position.y = 0.55; g.add(glow);
        var sh = new T.Mesh(new T.PlaneGeometry(0.6, 0.6), new T.MeshBasicMaterial({ map: shadowTex, transparent: true, opacity: 0.5, depthWrite: false }));
        sh.rotation.x = -Math.PI / 2; sh.position.y = 0.085; g.add(sh);
        g.userData = { body: body, head: head, glow: glow, mat: bodyMat };
        g.visible = false; scene.add(g); pool.push(g); return g;
      }

      S = {
        renderer: renderer, scene: scene, cam: cam, hemi: hemi, key: key,
        zoneHeat: zoneHeat, zoneChips: zoneChips, tableMeshes: tableMeshes,
        musicRing: musicRing, beacon: beacon, pool: pool, makePerson: makePerson,
        cfg: cfg, zones: zones, byName: byName,
        scene_data: { ts: null, tracks: [] }, comfort: {},
        azimuth: -0.62, elevation: 0.62, dragging: false, px: 0, py: 0, lastUser: 0,
        alertZone: null, alertUntil: 0, active: false, raf: null,
        heat: {}, clock: new T.Clock()
      };

      canvas.style.touchAction = "none";
      canvas.addEventListener("pointerdown", function (e) { S.dragging = true; S.px = e.clientX; S.py = e.clientY; S.lastUser = performance.now(); });
      window.addEventListener("pointerup", function () { S.dragging = false; });
      window.addEventListener("pointermove", function (e) {
        if (!S.dragging) return;
        S.azimuth -= (e.clientX - S.px) * 0.01;
        S.elevation = Math.max(0.28, Math.min(1.2, S.elevation - (e.clientY - S.py) * 0.005));
        S.px = e.clientX; S.py = e.clientY; S.lastUser = performance.now();
      });

      this.resize();
      return true;
    },

    setActive: function (on) {
      if (!S) return;
      S.active = !!on;
      if (on && !S.raf) loop();
      if (!on && S.raf) { cancelAnimationFrame(S.raf); S.raf = null; }
    },
    update: function (scene, comfort) { if (!S) return; if (scene) S.scene_data = scene; if (comfort) S.comfort = comfort; },
    flashAlert: function (zone) { if (!S) return; S.alertZone = zone || "queue"; S.alertUntil = performance.now() + 6000; },
    resize: function () {
      if (!S) return;
      var cv = S.renderer.domElement;
      var w = cv.clientWidth || (cv.parentNode && cv.parentNode.clientWidth) || 800;
      var h = cv.clientHeight || Math.round(w * 9 / 16);
      S.renderer.setSize(w, h, false);
      var aspect = w / h, view = 6.7;
      S.cam.left = -view * aspect; S.cam.right = view * aspect; S.cam.top = view; S.cam.bottom = -view;
      S.cam.updateProjectionMatrix();
    }
  };

  function loop() {
    S.raf = requestAnimationFrame(loop);
    if (!S.active) return;
    var dt = Math.min(S.clock.getDelta(), 0.05), now = performance.now();
    var sc = S.scene_data || {}, cf = S.comfort || {};

    if (!S.dragging && now - S.lastUser > 2500) S.azimuth += dt * 0.1;
    var R = 17, ce = Math.cos(S.elevation), se = Math.sin(S.elevation);
    S.cam.position.set(R * ce * Math.sin(S.azimuth), R * se, R * ce * Math.cos(S.azimuth));
    S.cam.lookAt(0, 0.3, 0);

    // comfort -> room light (the visible feedback loop)
    var bright = (cf.brightness == null ? 72 : cf.brightness) / 100;
    S.hemi.intensity = lerp(S.hemi.intensity, 0.4 + bright * 0.7, 0.07);
    S.key.intensity = lerp(S.key.intensity, 1.1 + bright * 1.3, 0.07);
    var warm = cf.warmth === "warm" ? "#ffdba0" : cf.warmth === "cool" ? "#cfe0ff" : "#fff2e2";
    S.key.color.lerp(col(warm), 0.05); S.hemi.color.lerp(col(warm), 0.05);

    // zone occupancy heat -> glowing rug
    var intensityFn = S.cfg.intensityFn, occFn = S.cfg.occColorFn;
    S.zones.forEach(function (z) {
      var heat = S.zoneHeat[z.z]; if (!heat) return;
      var target = (sc.ts != null && intensityFn) ? intensityFn(z, sc) : 0;
      S.heat[z.z] = lerp(S.heat[z.z] || 0, target, 0.1); var v = S.heat[z.z];
      heat.material.opacity = v * 0.7;
      if (occFn) { var m = occFn(v, 1).match(/\d+/g); if (m) heat.material.color.setRGB(m[0] / 255, m[1] / 255, m[2] / 255); }
      var cnt = 0; (sc.tracks || []).forEach(function (t) { if (t.zone === z.z) cnt++; });
      if (S.zoneChips[z.z]) drawChip(S.zoneChips[z.z], z.label || z.z, cnt);
    });

    // table discs -> status colour
    var TBL_COL = { empty: "#6b5d4a", seated: "#7ed87e", waiting: "#e0a341", overdue: "#e85c46" };
    (sc.tables || []).forEach(function (t) {
      var top = S.tableMeshes[t.id]; if (!top) return;
      var c = col(TBL_COL[t.status] || (t.occupied ? TBL_COL.seated : TBL_COL.empty));
      top.material.color.lerp(c, 0.15); top.material.emissive.lerp(c, 0.15);
      top.material.emissiveIntensity = (t.status === "overdue") ? 0.55 + 0.3 * Math.sin(now / 200) : 0.25;
      top.position.y = lerp(top.position.y, t.needs_cleaning ? 0.5 : 0.55, 0.1);
    });

    // music ring pulse
    var vol = cf.volume == null ? 0 : cf.volume;
    S.musicRing.material.opacity = lerp(S.musicRing.material.opacity, vol > 0 ? 0.55 : 0, 0.08);
    var pulse = 1 + 0.14 * Math.sin(now / 240) * (vol / 100);
    S.musicRing.scale.set(pulse, pulse, 1);
    S.musicRing.material.emissiveIntensity = 0.45 + 0.7 * (vol / 100);

    // people
    var tracks = sc.tracks || [];
    for (var i = 0; i < tracks.length; i++) {
      var g = S.pool[i] || S.makePerson(), t = tracks[i];
      var z = S.byName[t.zone] || S.zones[0];
      var bb = (t.bbox && t.bbox.length === 4) ? t.bbox : null;
      var bx = bb ? (bb[0] + bb[2]) / 2 : 0.5, by = bb ? (bb[1] + bb[3]) / 2 : 0.5;
      var pad = 0.1, nx = z.x + pad * z.w + bx * z.w * (1 - 2 * pad), ny = 0.16 + by * 0.68;
      g.visible = true;
      g.position.x = lerp(g.position.x, wx(nx), 0.18);
      g.position.z = lerp(g.position.z, wz(ny), 0.18);
      var staff = t.role === "staff";
      g.userData.mat.color.lerp(col(staff ? "#b58fe0" : "#f3ede3"), 0.2);
      g.userData.mat.emissive.lerp(col(staff ? "#3a2563" : "#000000"), 0.2);
      g.userData.mat.emissiveIntensity = staff ? 0.4 : 0.0;
      g.userData.glow.material.color.setHex(staff ? 0xc9a8f0 : 0xffe6b0);
      g.scale.y = staff ? 1.14 : 1;
    }
    for (var k = tracks.length; k < S.pool.length; k++) S.pool[k].visible = false;

    // staff-alert beacon
    var alertOn = S.alertZone && now < S.alertUntil;
    if (alertOn) {
      var az = S.byName[S.alertZone];
      if (az) S.beacon.position.x = wx(az.x + az.w / 2);
      S.beacon.position.z = 0;
      S.beacon.userData.colm.material.opacity = 0.3 + 0.3 * Math.abs(Math.sin(now / 220));
    } else {
      var o = S.beacon.userData.colm.material; o.opacity = lerp(o.opacity, 0, 0.1);
      if (o.opacity < 0.01) S.alertZone = null;
    }

    S.renderer.render(S.scene, S.cam);
  }

  if (typeof window !== "undefined") window.Floor3D = Floor3D;
})();
