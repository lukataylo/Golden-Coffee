# Dynamic floor-map generation — OSS landscape & integration plan

Research into **dynamically generating and rendering a café floor map** for Coffee Steve —
the richer, live, Home-Assistant-style digital-twin look (the reference screenshots) layered
on top of the data we already produce. "Dynamic" splits into **two independent problems** the
field never solves together, so treat them as two layers:

1. **Generation** — *where are the walls/zones/tables?* Turn a single café camera (or a few
   photos) into floor geometry automatically, instead of hand-drawing it.
2. **Rendering** — *make it look alive.* Draw that geometry as an interactive 2D/2.5D/3D
   floor map and bind it to live `SceneEvent` state (occupancy heat, queue, table status,
   the comfort actions the agent fires).

**Headline:** the rendering layer is a solved, drop-in problem with good MIT/Apache OSS. The
generation layer is *not* solved end-to-end for arbitrary rooms — but for our case (one fixed
camera, a known flat floor) the pragmatic 80/20 is **homography → top-down plate + SAM-assisted
zone polygons**, which upgrades `draw_zones.py` from "click polygons by hand" to "click 4 floor
corners, auto-suggest the rest." Full neural room reconstruction is a stretch goal, not the path.

---

## Where we are today (baseline to beat)

- **Geometry is manual.** `perception/draw_zones.py` grabs one frame and you click polygons for
  `entry/queue/counter/seating + T1..T3 + restroom`, written as **normalized `[x,y]` polygons**
  in `zones.json` (`build_geometry`, lines 39-49). That JSON shape is our integration contract —
  any generator should *emit this same shape* and any renderer should *consume it*.
- **The "Floorplan" view is hand-coded.** `dashboard/index.html` (`drawFloor`, ~L746) paints a
  flat top-down `<canvas>` with **four hardcoded vertical-band zones** and a dwell-heat overlay
  driven by `scene.heatmap_grid` + per-zone track counts. It is plain vanilla JS/`<canvas>` —
  **no React, no build step** — which constrains the renderer choice (see below).
- **The data is already rich enough** to drive a real digital twin: `SceneEvent` carries
  `tracks[].zone/bbox`, `occupancy`, `queue_len`, `funnel`, `tables[].status`, `cleaning[]`,
  `heatmap_grid`, `walkaway_gbp`. We are *under-rendering* the data we have.

So the cheapest win is **rendering**; the differentiated win is **generation** (auto-setup =
"works in any café in 2 minutes" — a real product wedge, since manual zone-drawing is the #1
onboarding friction for every retail-CV tool).

---

## Layer 1 — Rendering (the digital-twin look)

The reference screenshots are **`floor3d-card`** (Three.js) — the dominant HA digital twin.

| Project | License | Stack | Fit for Coffee Steve |
|---|---|---|---|
| [adizanni/floor3d-card](https://github.com/adizanni/floor3d-card) | **MIT** | Three.js + TS | The exact look in the screenshots. But it's a **Home Assistant Lovelace card** — model authored in SweetHome3D → exported `.obj`/`.glb`, entities bound by object-id. Great if we pivot the dashboard *into* HA; heavy to lift into our standalone dashboard. **Borrow the pattern, not the card.** |
| [floor3dpro-card](https://github.com/levonisyas/floor3dpro-card) | MIT (fork) | game-engine backbone | "PRO" fork of the above; same HA-coupling caveat. |
| [cvdlab/react-planner](https://github.com/cvdlab/react-planner) | MIT | React + Three.js | Draw 2D plan → walk it in 3D. **Unmaintained (~6 yrs)** and React-only — mismatch with our vanilla dashboard. Good reference for the 2D-plan → 3D-extrude trick. |
| [ekymo/homeRoughEditor](https://github.com/ekymo/homeRoughEditor) | **MIT** | **Vanilla JS + SVG** (no jQuery/React) | Best license+stack match to our dashboard. SVG floor-plan *editor* (walls/rooms/openings). Could double as our in-browser zone editor. Caveat: no built-in JSON export (a TODO) — we'd wire `zones.json` import/export ourselves. |
| [tomek-em/floorplan](https://github.com/tomek-em/floorplan) | check repo | Three.js | Small, readable "3D floorplan in plain Three.js" reference — closest to what we'd actually write. |
| **Roll-our-own** | — | Three.js *or* CSS/Canvas isometric | **Recommended.** See below. |

**Recommendation — extrude our existing `zones.json` in Three.js.** Three.js is a single CDN
`<script>` (no build step, fits our vanilla dashboard) and supports an **orthographic isometric
camera**. The recipe is mechanical and small:

1. Read the normalized polygons we already produce (zones + tables).
2. For each polygon: `THREE.Shape` → `ExtrudeGeometry` (low walls / table blocks) on a floor plane.
3. **Bind live state** exactly like floor3d-card binds HA entities — but to `SceneEvent` fields:
   zone emissive colour = `zoneIntensity()` (reuse our existing heat ramp); table block colour =
   `table.status` (empty/seated/waiting/overdue); a pulsing marker for `notify_staff`; glow/tint
   shifts when the agent fires `set_lighting`/`set_music_volume` so the *comfort actions are
   visible on the map*. That last point is our differentiator — RESEARCH.md notes no existing
   tool closes the loop to comfort actuation; rendering it on the twin makes the loop legible.
4. Animated track dots = `tracks[].bbox` centroids projected to the floor (next section).

For a **lighter, dependency-free** alternative that still reads as a "3D map," a **CSS/2.5D
isometric `<canvas>`** (painter's-algorithm quads) gives the look with zero new libraries — a
safe hackathon fallback if WebGL is flaky on the demo laptop.

---

## Layer 2 — Generation (auto floor geometry from the camera)

Four families, cheapest/most-robust first. For a **fixed overhead-ish café camera on a flat
floor**, #1 alone gets us most of the way; #2–#4 are accuracy/wow upgrades.

### 1. Homography / inverse-perspective mapping — *the pragmatic core* ✅
Classic OpenCV `getPerspectiveTransform` / `findHomography`: pick 4+ floor points, get a 3×3
matrix mapping camera pixels → a true **top-down (bird's-eye) plane**. This is the right tool
because our floor *is* a single plane and the camera is fixed.

- **Generates the plate:** warp a frame → an orthographic floor image to author/snap zones onto.
- **Generates the data overlay (bigger win):** project every `tracks[].bbox` **foot-point**
  through H → real top-down positions. That turns our heatmap and dots from "camera-perspective
  smear" into a metrically-honest occupancy map, and **reduces occlusion overlap** for tracking.
- **Integration:** add `--calibrate` to `draw_zones.py` (click 4 floor corners → store H in
  `zones.json`); perception applies H to foot-points; dashboard renders true top-down. Pure
  NumPy/OpenCV, no new heavy deps, runs real-time. *This is the single highest-leverage change.*
- Refs: OpenCV BEV/IPM tutorials; [2D-homography for CCTV traffic data](https://arxiv.org/pdf/2401.07220).

### 2. Monocular depth → point cloud → top-down (auto-plate without manual corners)
If we want the floor plate **without** clicking calibration points, run a monocular depth model
once and collapse the floor points to a top-down occupancy/height grid.

- [Depth-Anything-3 / V2](https://github.com/ByteDance-Seed/Depth-Anything-3) — SOTA zero-shot
  monocular depth, real-time on a consumer GPU (small variants). Open weights.
- [UniK3D (CVPR 2025)](https://github.com/lpiccinelli-eth/UniK3D) — universal-camera monocular
  3D, handles wide-FOV/fisheye café cams; emits metric 3D points to fold into a BEV grid.
- Caveat: relative depth needs one scale anchor (a known dimension) to be metric; heavier than
  homography. Best as a **one-time setup pass**, not per-frame. Check licenses before shipping.

### 3. SAM2-assisted auto-zoning — *upgrade `draw_zones.py` from clicks to suggestions*
Use [Segment Anything 2](https://docs.ultralytics.com/models/sam/) (image+video, ~6× SAM-image
accuracy) so the operator **clicks once inside "the counter," "the seating area," each table**
and gets a clean polygon back — auto-converted to our normalized `zones.json` shape. This is the
exact pattern [Roboflow Annotate](https://blog.roboflow.com/how-to-use-segment-anything-model-sam/)
uses for browser polygon labelling, and it sits naturally next to our existing supervision stack
(RESEARCH.md already commits us to `roboflow/supervision`, MIT). Watch SAM/Ultralytics licensing
(see flags). Biggest UX win per hour of work; pairs perfectly with homography (#1).

### 4. Neural floor-plan reconstruction / LLM-from-photos — *stretch / wow only*
End-to-end "photos → CAD-style plan." Impressive, but **not reliable enough to depend on**:

- [zlzeng/DeepFloorplan](https://github.com/zlzeng/DeepFloorplan) (ICCV'19) /
  [CubiCasa5K](https://github.com/mageaustralia/FloorPlanAnalyzer) — recognise rooms/walls **from
  an existing floor-plan *drawing***, not from a live café photo. Useful only if the owner already
  has a blueprint to import.
- [360-DFPE](https://arxiv.org/pdf/2112.06180) / room-layout estimators — strong but want
  **360° panoramas**, not a normal café cam.
- **LLM photo→floor-plan (GPT-5 / Claude / Gemini):** [Blueprint-Bench (2025)](https://andonlabs.com/evals/blueprint-bench)
  is the cold-shower data point — converting apartment photos to scaled 2D plans, *most models
  score at/below the random baseline and well under humans*; agentic iteration didn't help.
  **Do not put an LLM on the critical path for geometry.** (We can still use Claude for *labelling/
  semantics* — "this region is the queue" — which it's good at, not metric layout.)

---

## Recommended integration path (phased, contract-stable)

The constant across all phases: **everything reads/writes the normalized-polygon `zones.json`**
already defined by `build_geometry`, so generation and rendering stay decoupled (same discipline
as `SceneEvent`/`AgentAction`).

- **P0 — Render what we already have (½ day, highest demo ROI). ✅ SHIPPED.**
  `dashboard/floor3d.js` — a Three.js isometric extrusion of the current zone bands + tables, bound
  to live `SceneEvent` (zone occupancy heat, per-zone head-count, anonymous track dots, table-status
  pucks, a staff-alert beacon, and **comfort-action glow**: room light brightness/warmth follow
  `set_lighting`, a counter ring pulses with `set_music_volume`). Three.js is **vendored locally**
  (`dashboard/vendor/three.min.js`, MIT) so it works offline; a 3D/2D toggle falls back to the
  original `<canvas>` heatmap if WebGL is unavailable. Ships with a **Demo mode** (header button /
  `?demo=1` / auto-starts on `file://`) — a self-contained synthetic café that mirrors
  `shared/mock_events.py` and fires believable agent actions, so the whole product runs from a
  single file with no backend, perception, or camera.
- **P1 — Honest geometry via homography (½–1 day, highest accuracy ROI).** `draw_zones --calibrate`
  (4 floor corners → H in `zones.json`); project track foot-points top-down; warped floor plate as
  the map background. Removes the perspective smear from heatmap + dots.
- **P2 — SAM2-assisted zoning (1 day).** Click-once-per-region polygon suggestions in `draw_zones`
  (or a `homeRoughEditor`-style in-browser editor) → normalized `zones.json`. Onboarding drops from
  "draw every polygon" to "tap each area."
- **P3 — Stretch.** Monocular-depth auto-plate (no manual corners) and/or blueprint import — only
  if P0–P2 land with time to spare.

This sequencing maximizes demo polish first, then accuracy, then the "works in any café" product
story — without ever touching the shared schema.

## ⚠️ Licensing flags (same rigor as RESEARCH.md)
- **SAM via Ultralytics** inherits the **AGPL-3.0** concern already flagged for YOLO in RESEARCH.md.
  Prefer Meta's original SAM2 weights/repo (Apache-2.0) or RF-DETR-adjacent permissive tooling for
  anything shipped in a closed product; Ultralytics packaging is fine for the hackathon demo.
- **Depth-Anything / UniK3D:** verify weight licenses before commercial use (research checkpoints
  often carry non-commercial terms even when code is permissive).
- **floor3d-card / react-planner / homeRoughEditor:** all **MIT** — safe to borrow patterns or fork.
- **Homography / OpenCV path:** BSD/Apache — clean, no copyleft, and it's the recommended core.

## Sources
- [adizanni/floor3d-card (MIT, Three.js HA digital twin)](https://github.com/adizanni/floor3d-card) ·
  [floor3dpro-card fork](https://github.com/levonisyas/floor3dpro-card) ·
  [HA community: Interactive 3D floor plan](https://community.home-assistant.io/t/your-home-digital-twin-interactive-floor-3d-plan/301549)
- [cvdlab/react-planner](https://github.com/cvdlab/react-planner) · [ekymo/homeRoughEditor (MIT, vanilla SVG)](https://github.com/ekymo/homeRoughEditor) · [tomek-em/floorplan (Three.js)](https://github.com/tomek-em/floorplan)
- [Three.js isometric perspective (Frontend Masters)](https://frontendmasters.com/courses/canvas-webgl/capabilities-of-three-js-isometric-perspective/) · [HTML5 Canvas isometric 2.5D](https://docs.bswen.com/blog/2026-02-21-isometric-25d-canvas-games/)
- [OpenCV bird's-eye-view / IPM guide](https://dhyanchands.medium.com/building-a-perfect-birds-eye-view-bev-in-opencv-geometry-scaling-and-real-world-design-d8f3a4fe2922) · [2D homography for CCTV traffic data (arXiv)](https://arxiv.org/pdf/2401.07220)
- [Depth-Anything-3](https://github.com/ByteDance-Seed/Depth-Anything-3) · [UniK3D, CVPR 2025](https://github.com/lpiccinelli-eth/UniK3D) · [Depth estimation model roundup (Roboflow)](https://blog.roboflow.com/depth-estimation-models/)
- [Segment Anything 2 (Ultralytics docs)](https://docs.ultralytics.com/models/sam/) · [SAM auto-polygon labelling (Roboflow)](https://blog.roboflow.com/how-to-use-segment-anything-model-sam/)
- [zlzeng/DeepFloorplan (ICCV'19)](https://github.com/zlzeng/DeepFloorplan) · [FloorPlanAnalyzer / CubiCasa5K](https://github.com/mageaustralia/FloorPlanAnalyzer) · [360-DFPE (arXiv)](https://arxiv.org/pdf/2112.06180)
- [Blueprint-Bench: photos→floorplan eval (Andon Labs)](https://andonlabs.com/evals/blueprint-bench) · [Blueprint-Bench paper (arXiv)](https://arxiv.org/pdf/2509.25229)
</content>
</invoke>
