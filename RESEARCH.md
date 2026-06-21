# Competitive / reusable OSS landscape

Research across café/retail video analytics, queue & wait-time estimation, table/seat
occupancy, occupancy-reactive automation, and agentic vision. **Headline: no single OSS
project does the full Caffe Steve loop** (single camera → café/table/cleaning ops → an
agent that acts on comfort). The field splits into two halves nobody has joined —
perception (counts/dwell/queue/occupancy) and action (occupancy-reactive automation,
vision-LLM agents that alert). **Our wedge is the seam.**

> Dynamic floor-map generation + the Home-Assistant-style digital-twin render are covered
> separately in **[FLOORMAP_RESEARCH.md](FLOORMAP_RESEARCH.md)**.

## Build on these (permissive licenses)
- **roboflow/supervision** (MIT, ~44.7k★) — our perception spine: `Detections`, `ByteTrack`,
  `PolygonZone` (table/area occupancy), `LineZone` (door footfall), heatmaps. Already in use.
  - `examples/time_in_zone` — the canonical per-ID dwell pattern + a `draw_zones.py` JSON
    zone editor → exactly our table-wait / queue-time need (and our new `--zones` JSON).
- **GetStream/Vision-Agents** (Apache-2.0, ~7.9k★) — blueprint for the action layer:
  CV → LLM → tool-calling/MCP side effects, `trigger_alert()` per frame.
- **Hankanman/Area-Occupancy-Detection** (MIT, ~304★) — the comfort-action brain: occupancy
  *probability + decay*, so ambiance actions gate on a smoothed signal, not raw per-frame
  counts (prevents thrashing music/lights/AC — adopt for our debounce/threshold logic).
- **valentinfrlch/ha-llmvision** (Apache-2.0, ~1.4k★) — camera-event → LLM → event-timeline →
  home automation glue; good UI/timeline pattern.
- **SharpAI/DeepCamera** (MIT, ~2.8k★) — local-first privacy NVR, pluggable `skills.json`
  registry, deduplicated Telegram/Slack alerts.

## Technique borrow-list (mapped to tracks)
- **Perception (A):** lift `FPSBasedTimer`/`ClockBasedTimer` per-ID dwell; wait-time =
  `(exit_frame − entry_frame)/fps` (Roboflow retail-queue tutorial). Table state machine:
  IoU(person, table-zone) + **N-frame state stabilization** to stop flicker + **background-
  subtraction "objects left behind"** as a dirty/uncleared signal (RexxarCHL/library-seat-
  detection) + **human-vs-belongings** distinction (asumansaree). Dual-polygon directional
  counting (zone A→B) for reliable door in/out. RTSP buffer-drain + detect-every-N-frames
  for single-camera real-time (saimj7).
- **Backend (C):** processor pipeline + tool/MCP side effects (Vision-Agents); occupancy
  probability+decay gating (Area-Occupancy); verified-alert/debounce before acting (NVIDIA VSS);
  pluggable skill registry + deduped alerts (DeepCamera).
- **Frontend (D):** color-coded live table status board (Available/Occupied/Held/Needs-clean);
  event timeline for funnel + agent actions; supervision `draw_zones.py` as the non-coder
  zone-setup tool; heatmap/occupancy annotators.

## Differentiation
Action-oriented vision agents (Vision-Agents, ha-llmvision, DeepCamera, NVIDIA VSS) act, but
their actions are **security/alerting/Q&A** — none close the loop to **comfort actuation
(music/lights/scent/AC) driven by occupancy/queue/dwell**, and none model **restaurant table
lifecycle or cleaning cadence**. Occupancy-reactive automation (Area-Occupancy, ESPresense)
controls comfort well but from **sensors, not a camera**, with **no business-ops semantics**.
Café/retail CV repos only **dashboard counts — they never act**. Caffe Steve is the join.

## ⚠️ Red flags
- **Ultralytics YOLO is AGPL-3.0** — using its weights/code in a closed product is copyleft-
  tainting. For a real launch, switch to **RF-DETR or a permissively-licensed detector**, or
  get the Ultralytics Enterprise license. (Fine for a hackathon demo; flag for Track A.)
- **No-license repos** (asumansaree, RexxarCHL, AarohiSingla, etc.): learn the techniques,
  **do not copy code** — reimplement on supervision (MIT).
- **Compute:** heavy models can take ~20 min for a 5-min clip on a V100 — keep light models +
  detect-every-N-frames + tracking-between for single-camera real-time.
- **"Already done?"** No — the full loop is unoccupied territory. Risk is integration effort,
  not a pre-existing competitor.
