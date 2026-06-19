/*
 * Golden Coffee — isometric 3D floor map (P0 from FLOORMAP_RESEARCH.md).
 *
 * Extrudes the dashboard's normalized zone bands into a Three.js isometric
 * "digital twin" and binds it to live SceneEvent state: zone occupancy heat,
 * per-zone head-count, anonymous track dots, table status pucks, a staff-alert
 * beacon, and — the differentiator — the agent's *comfort actions* made visible
 * (room light brightness/warmth follow set_lighting; a counter ring pulses with
 * set_music_volume). No build step: a single UMD Three.js + this file.
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
  var FW = 10, FD = 6.4;            // floor width (x) / depth (z)
  var WALL_H = 1.15, TILE_H = 0.18;

  // normalized (x within frame, y within frame) -> world XZ on the floor
  function wx(nx) { return (nx - 0.5) * FW; }
  function wz(ny) { return (ny - 0.5) * FD; }

  function parseHex(hex) {
    var h = String(hex || "#888888").replace("#", "");
    return { r: parseInt(h.substr(0, 2), 16), g: parseInt(h.substr(2, 2), 16), b: parseInt(h.substr(4, 2), 16) };
  }
  function rgbToColor(c) { return new T.Color(c.r / 255, c.g / 255, c.b / 255); }
  function lerp(a, b, t) { return a + (b - a) * t; }

  var S = null; // module singleton state

  function makeLabelSprite(text) {
    var cv = document.createElement("canvas"); cv.width = 256; cv.height = 64;
    var tex = new T.CanvasTexture(cv);
    tex.minFilter = T.LinearFilter;
    var mat = new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false });
    var sp = new T.Sprite(mat);
    sp.scale.set(2.4, 0.6, 1);
    sp.renderOrder = 10;
    sp.userData = { cv: cv, tex: tex, last: "" };
    return sp;
  }
  function drawLabel(sprite, title, count) {
    var key = title + "|" + count;
    if (sprite.userData.last === key) return;
    sprite.userData.last = key;
    var cv = sprite.userData.cv, ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.font = "700 22px system-ui, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(243,237,227,0.92)";
    ctx.fillText(title.toUpperCase(), cv.width / 2, 20);
    ctx.font = "600 26px system-ui, sans-serif";
    ctx.fillStyle = "rgba(231,192,116,0.95)";
    ctx.fillText(count + (count === 1 ? " person" : " people"), cv.width / 2, 46);
    sprite.userData.tex.needsUpdate = true;
  }

  var Floor3D = {
    available: function () {
      if (!T) return false;
      try {
        var c = document.createElement("canvas");
        return !!(window.WebGLRenderingContext &&
          (c.getContext("webgl") || c.getContext("experimental-webgl")));
      } catch (e) { return false; }
    },

    init: function (canvas, cfg) {
      if (S || !this.available()) return !!S;
      cfg = cfg || {};
      var zones = cfg.zones || [];

      var renderer;
      try {
        renderer = new T.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
      } catch (e) { return false; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = T.PCFSoftShadowMap;

      var scene = new T.Scene();
      scene.background = null;

      // orthographic isometric camera (true digital-twin look)
      var cam = new T.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);

      // lighting (ambient is comfort-driven; key light casts the soft shadows)
      var ambient = new T.AmbientLight(0xffffff, 0.75);
      scene.add(ambient);
      var key = new T.DirectionalLight(0xffffff, 0.85);
      key.position.set(6, 12, 5); key.castShadow = true;
      key.shadow.mapSize.set(1024, 1024);
      key.shadow.camera.left = -9; key.shadow.camera.right = 9;
      key.shadow.camera.top = 9; key.shadow.camera.bottom = -9;
      scene.add(key);
      var rim = new T.DirectionalLight(0x88aaff, 0.25);
      rim.position.set(-6, 5, -6); scene.add(rim);

      // base plate (the room floor) + soft grid
      var baseGeo = new T.BoxGeometry(FW + 0.8, 0.3, FD + 0.8);
      var baseMat = new T.MeshStandardMaterial({ color: 0x1a1510, roughness: 0.95, metalness: 0 });
      var base = new T.Mesh(baseGeo, baseMat);
      base.position.y = -0.15; base.receiveShadow = true; scene.add(base);
      var grid = new T.GridHelper(Math.max(FW, FD) + 0.8, 16, 0x3a3024, 0x271f17);
      grid.position.y = 0.001; scene.add(grid);

      // glassy perimeter walls (the enclosure in the reference renders)
      var wallMat = new T.MeshStandardMaterial({ color: 0x9fb6c8, transparent: true, opacity: 0.10, roughness: 0.2, metalness: 0.1, side: T.DoubleSide });
      function wall(w, d, x, z) {
        var m = new T.Mesh(new T.BoxGeometry(w, WALL_H, d), wallMat);
        m.position.set(x, WALL_H / 2, z); scene.add(m);
      }
      wall(FW + 0.4, 0.08, 0, -FD / 2);   wall(FW + 0.4, 0.08, 0, FD / 2);
      wall(0.08, FD + 0.4, -FW / 2, 0);   wall(0.08, FD + 0.4, FW / 2, 0);

      // zone tiles (extruded slabs), one per zone band
      var zoneMeshes = {}, zoneLabels = {};
      zones.forEach(function (z) {
        var w = z.w * FW, d = FD - 0.3;
        var cx = wx(z.x + z.w / 2);
        var base = parseHex((cfg.zoneColors && cfg.zoneColors[z.z]) || "#7d7263");
        var mat = new T.MeshStandardMaterial({
          color: rgbToColor(base), roughness: 0.7, metalness: 0.05,
          emissive: rgbToColor(base), emissiveIntensity: 0.0
        });
        var mesh = new T.Mesh(new T.BoxGeometry(w - 0.12, TILE_H, d), mat);
        mesh.position.set(cx, TILE_H / 2, 0); mesh.receiveShadow = true;
        scene.add(mesh);
        zoneMeshes[z.z] = mesh;

        var label = makeLabelSprite(z.label || z.z);
        label.position.set(cx, 1.35, -d / 2 + 0.3);
        scene.add(label); zoneLabels[z.z] = label;
      });

      // table pucks — fixed slots inside the seating band, bound by id to status
      var seating = null;
      zones.forEach(function (z) { if (z.z === "seating") seating = z; });
      var tableMeshes = {};
      var TBL_SLOTS = [
        { id: "T1", nx: 0.18, ny: 0.30 },
        { id: "T2", nx: 0.55, ny: 0.62 },
        { id: "T3", nx: 0.82, ny: 0.32 }
      ];
      if (seating) {
        TBL_SLOTS.forEach(function (slot) {
          var nx = seating.x + slot.nx * seating.w;
          var mat = new T.MeshStandardMaterial({ color: 0x6b5d4a, roughness: 0.6, emissive: 0x000000, emissiveIntensity: 0.4 });
          var puck = new T.Mesh(new T.CylinderGeometry(0.42, 0.42, 0.22, 24), mat);
          puck.position.set(wx(nx), 0.3, wz(slot.ny)); puck.castShadow = true;
          scene.add(puck);
          tableMeshes[slot.id] = puck;
        });
      }

      // music ring near the counter (scales/pulses with volume)
      var counter = null; zones.forEach(function (z) { if (z.z === "counter") counter = z; });
      var musicRing = new T.Mesh(
        new T.TorusGeometry(0.5, 0.05, 12, 40),
        new T.MeshStandardMaterial({ color: 0xe7c074, emissive: 0xe7c074, emissiveIntensity: 0.6, transparent: true, opacity: 0.0 })
      );
      musicRing.rotation.x = Math.PI / 2;
      musicRing.position.set(wx(counter ? counter.x + counter.w / 2 : 0.5), 0.25, wz(0.78));
      scene.add(musicRing);

      // staff-alert beacon (hidden until flashAlert)
      var beacon = new T.Mesh(
        new T.CylinderGeometry(0.12, 0.34, 1.8, 20, 1, true),
        new T.MeshBasicMaterial({ color: 0xff5a46, transparent: true, opacity: 0.0, side: T.DoubleSide })
      );
      beacon.position.y = 0.9; scene.add(beacon);

      // CCTV marker (single-camera story)
      var cctv = new T.Mesh(new T.SphereGeometry(0.16, 16, 16),
        new T.MeshStandardMaterial({ color: 0xe7c074, emissive: 0xe7c074, emissiveIntensity: 0.4 }));
      cctv.position.set(0, 2.4, -FD / 2 + 0.2); scene.add(cctv);

      // track-marker pool (reused; anonymous dots)
      var trackPool = [];
      function makeTrack() {
        var g = new T.Group();
        var body = new T.Mesh(new T.CylinderGeometry(0.14, 0.16, 0.5, 16),
          new T.MeshStandardMaterial({ color: 0xfff7ec, emissive: 0x000000, emissiveIntensity: 0.3 }));
        body.position.y = 0.35; body.castShadow = true; g.add(body);
        var glow = new T.Mesh(new T.SphereGeometry(0.26, 16, 16),
          new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.14 }));
        glow.position.y = 0.55; g.add(glow);
        g.userData = { body: body, glow: glow };
        g.visible = false; scene.add(g); trackPool.push(g); return g;
      }

      S = {
        renderer: renderer, scene: scene, cam: cam, ambient: ambient, key: key,
        zoneMeshes: zoneMeshes, zoneLabels: zoneLabels, tableMeshes: tableMeshes,
        musicRing: musicRing, beacon: beacon, trackPool: trackPool, makeTrack: makeTrack,
        cfg: cfg, zones: zones,
        scene_data: { ts: null, tracks: [] }, comfort: {},
        azimuth: -0.7, elevation: 0.62, dragging: false, px: 0, py: 0, lastUser: 0,
        alertZone: null, alertUntil: 0, active: false, raf: null,
        heat: {}, // per-zone smoothed emissive intensity
        clock: new T.Clock()
      };

      // pointer drag to orbit (auto-rotate resumes after idle)
      canvas.style.touchAction = "none";
      canvas.addEventListener("pointerdown", function (e) { S.dragging = true; S.px = e.clientX; S.py = e.clientY; S.lastUser = performance.now(); });
      window.addEventListener("pointerup", function () { S.dragging = false; });
      window.addEventListener("pointermove", function (e) {
        if (!S.dragging) return;
        S.azimuth -= (e.clientX - S.px) * 0.01;
        S.elevation = Math.max(0.25, Math.min(1.25, S.elevation - (e.clientY - S.py) * 0.005));
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

    update: function (scene, comfort) {
      if (!S) return;
      if (scene) S.scene_data = scene;
      if (comfort) S.comfort = comfort;
    },

    flashAlert: function (zone, text) {
      if (!S) return;
      S.alertZone = zone || "queue";
      S.alertUntil = performance.now() + 6000;
    },

    resize: function () {
      if (!S) return;
      var cv = S.renderer.domElement;
      var w = cv.clientWidth || (cv.parentNode && cv.parentNode.clientWidth) || 800;
      var h = cv.clientHeight || Math.round(w * 9 / 16);
      S.renderer.setSize(w, h, false);
      var aspect = w / h, view = 7.2;
      S.cam.left = -view * aspect; S.cam.right = view * aspect;
      S.cam.top = view; S.cam.bottom = -view;
      S.cam.updateProjectionMatrix();
    }
  };

  function loop() {
    S.raf = requestAnimationFrame(loop);
    if (!S.active) return;
    var dt = Math.min(S.clock.getDelta(), 0.05);
    var now = performance.now();
    var sc = S.scene_data || {}, cf = S.comfort || {};

    // auto-rotate when the user hasn't touched it recently
    if (!S.dragging && now - S.lastUser > 2500) S.azimuth += dt * 0.12;
    var R = 16, ce = Math.cos(S.elevation), se = Math.sin(S.elevation);
    S.cam.position.set(R * ce * Math.sin(S.azimuth), R * se, R * ce * Math.cos(S.azimuth));
    S.cam.lookAt(0, 0, 0);

    // comfort -> room light (the visible feedback loop)
    var bright = (cf.brightness == null ? 72 : cf.brightness) / 100;
    S.ambient.intensity = lerp(S.ambient.intensity, 0.35 + bright * 0.9, 0.08);
    var warmCol = cf.warmth === "warm" ? { r: 255, g: 217, b: 160 }
      : cf.warmth === "cool" ? { r: 188, g: 216, b: 255 }
        : { r: 255, g: 250, b: 240 };
    S.ambient.color.lerp(rgbToColor(warmCol), 0.06);

    // zone occupancy heat (smoothed) -> emissive glow on each slab
    var intensityFn = S.cfg.intensityFn, occFn = S.cfg.occColorFn;
    S.zones.forEach(function (z) {
      var mesh = S.zoneMeshes[z.z]; if (!mesh) return;
      var target = (sc.ts != null && intensityFn) ? intensityFn(z, sc) : 0;
      S.heat[z.z] = lerp(S.heat[z.z] || 0, target, 0.1);
      var v = S.heat[z.z];
      mesh.material.emissiveIntensity = 0.05 + v * 0.85;
      if (occFn) {
        var css = occFn(v, 1); // "rgba(r,g,b,a)"
        var m = css.match(/\d+/g);
        if (m) mesh.material.emissive.setRGB(m[0] / 255, m[1] / 255, m[2] / 255);
      }
      // count label
      var cnt = 0; (sc.tracks || []).forEach(function (t) { if (t.zone === z.z) cnt++; });
      if (S.zoneLabels[z.z]) drawLabel(S.zoneLabels[z.z], z.label || z.z, cnt);
    });

    // table pucks -> status colour
    var TBL_COL = { empty: 0x6b5d4a, seated: 0x7ed87e, waiting: 0xe0a341, overdue: 0xe85c46 };
    (sc.tables || []).forEach(function (t) {
      var puck = S.tableMeshes[t.id]; if (!puck) return;
      var col = TBL_COL[t.status] != null ? TBL_COL[t.status] : (t.occupied ? TBL_COL.seated : TBL_COL.empty);
      puck.material.color.lerp(new T.Color(col), 0.15);
      puck.material.emissive.lerp(new T.Color(col), 0.15);
      puck.material.emissiveIntensity = (t.status === "overdue") ? 0.6 + 0.3 * Math.sin(now / 200) : 0.3;
      puck.position.y = lerp(puck.position.y, t.needs_cleaning ? 0.22 : 0.3, 0.1);
    });

    // music ring pulse
    var vol = cf.volume == null ? 0 : cf.volume;
    var ringOn = vol > 0 ? 0.5 : 0;
    S.musicRing.material.opacity = lerp(S.musicRing.material.opacity, ringOn, 0.08);
    var pulse = 1 + 0.12 * Math.sin(now / 260) * (vol / 100);
    S.musicRing.scale.set(pulse, pulse, 1);
    S.musicRing.material.emissiveIntensity = 0.4 + 0.6 * (vol / 100);

    // anonymous track dots
    var tracks = sc.tracks || [];
    for (var i = 0; i < tracks.length; i++) {
      var g = S.trackPool[i] || S.makeTrack();
      var t = tracks[i];
      var z = null; S.zones.forEach(function (zz) { if (zz.z === t.zone) z = zz; });
      if (!z) z = S.zones[0];
      var bb = (t.bbox && t.bbox.length === 4) ? t.bbox : null;
      var bx = bb ? (bb[0] + bb[2]) / 2 : 0.5;     // fraction within the zone band
      var by = bb ? (bb[1] + bb[3]) / 2 : 0.5;     // fraction of full depth
      var pad = 0.08;
      var nx = z.x + pad * z.w + bx * z.w * (1 - 2 * pad);
      var ny = 0.12 + by * 0.76;
      var tx = wx(nx), tz = wz(ny);
      g.visible = true;
      g.position.x = lerp(g.position.x, tx, 0.2);
      g.position.z = lerp(g.position.z, tz, 0.2);
      var staff = t.role === "staff";
      var col = staff ? 0xb58fe0 : 0xfff7ec;
      g.userData.body.material.color.setHex(col);
      g.userData.body.material.emissive.setHex(staff ? 0x4a2f7a : 0x000000);
      g.userData.glow.material.color.setHex(staff ? 0xb58fe0 : 0xffe6b0);
      g.userData.body.scale.y = staff ? 1.25 : 1;
    }
    for (var k = tracks.length; k < S.trackPool.length; k++) S.trackPool[k].visible = false;

    // staff-alert beacon
    var alertOn = S.alertZone && now < S.alertUntil;
    if (alertOn) {
      var az = null; S.zones.forEach(function (zz) { if (zz.z === S.alertZone) az = zz; });
      if (az) S.beacon.position.x = wx(az.x + az.w / 2);
      S.beacon.position.z = 0;
      S.beacon.material.opacity = 0.35 + 0.35 * Math.abs(Math.sin(now / 220));
    } else {
      S.beacon.material.opacity = lerp(S.beacon.material.opacity, 0, 0.1);
      if (S.beacon.material.opacity < 0.01) S.alertZone = null;
    }

    S.renderer.render(S.scene, S.cam);
  }

  if (typeof window !== "undefined") window.Floor3D = Floor3D;
})();
