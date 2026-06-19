# ☕ Golden Coffee — Hospitality Ops Copilot

Turns a coffee shop's existing CCTV/webcam into a live ops copilot: it reads the room
(occupancy, dwell, conversion funnel, staff activity, flow heatmap) and **acts** —
nudging music volume, temperature, discounts, and staff alerts — **without storing a
single face**. Built for the Encode Vibe Coding Hackathon.

Full plan & team split: `~/.claude/plans/help-plan-a-hackathon-crystalline-papert.md`.

## Architecture

```
producers --POST /ingest (SceneEvent)--> [FastAPI hub] --WS /ws--> dashboard
agent     --POST /action (AgentAction)-> [FastAPI hub] --WS /ws--> dashboard
dashboard --POST /override-------------> [FastAPI hub]  (human-in-the-loop)
```

Everyone talks in two shapes only — `SceneEvent` and `AgentAction` in
[`shared/schemas.py`](shared/schemas.py). That contract is what lets all four
workstreams build in parallel against the **mock generator** before real perception exists.

> ⚠️ The WebSocket backend must run on Render/Railway/Fly — **Vercel serverless can't
> hold a socket**. The dashboard (Next.js/v0) stays on Vercel and connects over `wss://`.

## Quick start (clone-and-run skeleton, ~5 min)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in keys when ready

# 1) backend hub
uvicorn backend.main:app --reload --port 8000

# 2) mock data (separate terminal) — proves the pipe end-to-end with no model/camera
python -m shared.mock_events

# 3) dashboard — open dashboard/index.html in a browser (live tiles + action feed)
open dashboard/index.html
```

You should see occupancy/funnel/heatmap tiles updating live. That's the skeleton —
each of the four tracks now builds independently:

```bash
python -m perception.run --source 0          # P1: real YOLO11+supervision events (replaces mock)
python -m agent.agent                         # P2: Claude tool-use loop -> /action
python -m actuators.spotify 40                # P3: prove one real device live
```

## Workstreams (4 people)
- **P1 Perception** — `perception/`, `clips/`. YOLO11 + supervision (ByteTrack, zones, dwell, heatmap, funnel). Emit real `SceneEvent`s.
- **P2 Agent** — `agent/`, `federated/`. Claude tool-use policy + discount engine + FLock.
- **P3 Backend/Actuators** — `backend/`, `actuators/`. WS hub + Spotify/Kasa/Slack live.
- **P4 Frontend/Pitch** — `dashboard/`. Upgrade `index.html` → Next.js/v0 on Vercel; demo deck.

## Pre-hackathon prep
- Spotify **Premium** + app credentials + run the OAuth consent once (`python -m actuators.spotify 40`).
- TP-Link **Kasa** plug + fan/lamp; discover its IP (`kasa discover`).
- Slack Incoming Webhook URL (or Telegram bot).
- `ANTHROPIC_API_KEY`; pre-download `yolo11n.pt`; test FPS on the demo laptop.
- 2–3 staged café clips in `clips/` as the live-demo fallback.
