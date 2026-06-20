# Golden Coffee — Team Tracks

Four parallel tracks, one owner each, paired with their AI coding agent. Everyone
works against two shared contracts so the tracks never block each other:
`shared/schemas.py` (SceneEvent + AgentAction) and the backend WebSocket. Start the
mock (`python -m shared.mock_events`) and you can build any track without the others.

**Integration points:** Sat midday (P1 real events → P2/P4), Sat eve (P2 actions →
P3 devices → P4 feed), Sun AM full dress rehearsal. PR into `main`; don't commit
secrets (`.env` is gitignored).

Product framing (locked): **ambient autopilot + rush copilot — "your café, but it
runs itself", privacy-first.** Every action helps customers or staff. No employee
scoring, no surge pricing, no using discomfort to move people along.

---

## Track A — Perception & Vision  ·  `perception/` `clips/` `eval/`
Owns what the camera understands. Current state: YOLO11 + supervision (ByteTrack,
zones, dwell, funnel, heatmap), table wait-times + cleaning monitor, MJPEG stream.

- [x] **Real zone geometry tool** shipped: `python -m perception.draw_zones --source <cam>`
      (click polygons → `zones.json`) loaded by `perception.run --zones zones.json`.
      → **Do this for the demo camera** (placeholder bands are the biggest accuracy gap).
- [x] **Model flag** shipped: `--model yolo11m/x`. Still TODO: optional SAHI tiled
      inference for distant/overlapping people (eval shows yolo11n under-detects dense scenes).
- [ ] **Licensing**: Ultralytics YOLO is **AGPL-3.0** — fine for the hackathon, but for a
      real product switch to RF-DETR / a permissive detector (see RESEARCH.md).
- [ ] **Staff vs customer**: a real classifier (apron/uniform colour or station
      heuristic) so "served" and "bussed" events fire reliably (today it's a crude proxy).
- [ ] **Calibrate thresholds** on real footage: counter-dwell→ordered, table wait
      WARN/CRIT, cleaning DUE/OVERDUE.
- [ ] Keep the eval green: re-run `python -m eval.run_eval && python -m eval.score`
      after changes; aim to hold café-representative count MAE ≤ 1.

## Track B — Agent & Intelligence  ·  `agent/` `federated/`
Owns decisions. Current state: deterministic comfort + rush + table/cleaning policy;
Claude tool-use path gated behind `ANTHROPIC_API_KEY`.

- [ ] **Wire Claude live**: set the key, confirm the tool-use path mirrors the rule
      policy and produces good rationales; fall back to rules on error.
- [ ] **Walkaway £ metric**: dollarize lost walk-offs (avg ticket × abandons) — the
      ownable headline ("you lost ~£120 today to the queue"). Add to the agent/scene.
- [ ] **Footfall forecast**: simple time-series over occupancy → next-hour staffing /
      prep suggestion (the recurring-value, gap-in-market feature).
- [ ] **Time-of-day comfort**: morning = brighter + citrus; evening = warm + dim.
- [x] **Local music model** (`agent/music_model.py`): on-device softmax model maps
      the scene (occupancy/queue/energy/time-of-day) → a café mood (genre + BPM +
      playlist), emitting `set_music`. Trained locally, no API key. See MUSIC.md.
- [ ] **FLock**: minimal federated integration (privacy story + sponsor bounty).

## Track C — Backend & Actuators / Integrations  ·  `backend/` `actuators/`
Owns the hub + the real devices. Current state: FastAPI WS hub + MJPEG, executor
(`actuators/run.py`) driving Spotify, IR AC, Hue lights, scent, Telegram.

- [ ] **Configure + test every device** (fill `.env`): Spotify Premium+active device,
      Hue bridge pairing, learn IR cool/warm codes, scent (webhook or IR), Telegram bot.
- [ ] **Live demo wiring**: run perception + agent + `actuators/run.py` against the
      Railway backend; confirm each action visibly/audibly fires.
- [ ] **Harden**: lightweight auth token on `/ingest` + `/frame`, `/stream` backpressure,
      basic metrics on `/health`.
- [ ] **Persist a metrics log** (append JSON / SQLite) so Track B's forecast has history.

## Track D — Frontend & Product  ·  `dashboard/` + pitch
Owns the surface + the story. Current state: feed-dominant dashboard with Live /
Floorplan / Tables views, Comfort autopilot panel, action feed, ethics panel.

- [ ] **Polish** the Tables/Cleaning + Comfort views; verify responsive + a11y.
- [ ] **Surface the £-walkaway headline** once Track B emits it.
- [ ] **Pitch deck + 3-min demo script** around ambient autopilot + rush copilot;
      pick the single hero moment (agent reads the room → comfort/music change live).
- [ ] **Backup demo video** of a clean run (live-demo insurance).
- [ ] **Sponsor bounty**: move the dashboard to Vercel via v0, OR coordinate with B on
      FLock — claim at least one bounty for real.

---

## Open cross-cutting tasks
- [ ] Decide demo hardware (which Hue/IR/scent devices we actually bring).
- [x] **Geometry is first-class** (`perception/geometry.py`): validation (bad coords /
      degenerate / missing-zone now fail loudly on load), believable café presets
      generated headlessly (`perception.run --preset counter_top --tables N --gen-zones
      zones.json`, no GUI), and auto-table layout. `draw_zones` takes `--tables N` /
      `--load`. Still to do: capture the *actual venue* geometry on its camera.
- [ ] One-line eval summary + the privacy stance on a pitch slide (D, from A's eval).
