# 🛠️ Local setup

Golden Coffee is built to **run anywhere with zero keys** — the mock generator and the rule-based
agent prove the whole pipeline without a camera, a model, or an API key. Real perception and real
devices are opt-in on top.

## Prerequisites

- **Python 3.11**
- (Optional) a webcam or a video file for real perception
- (Optional) Spotify Premium, Philips Hue, a Broadlink RM4, a scent diffuser, a Telegram bot — only
  if you want real devices to fire

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # full stack (perception + agent + actuators)
cp .env.example .env                      # all values optional — blanks degrade gracefully
```

> Deploying just the hub? Use the slim `requirements-backend.txt` (FastAPI/uvicorn only, no
> torch/ultralytics) — that's what the `Dockerfile` and Railway use.

## 2. Run the core loop (no camera, no key)

Three terminals, all from the repo root with the venv active:

```bash
# terminal 1 — the realtime hub (also serves the dashboard at /)
uvicorn backend.main:app --reload --port 8000

# terminal 2 — synthetic café scenes
python -m shared.mock_events

# terminal 3 — the agent (deterministic policy; no API key needed)
python -m agent.agent
```

Then open <http://127.0.0.1:8000> — live tiles, the action feed, the Comfort Index, and the 3D twin.

**Even lighter:** open the dashboard and click **▶ Demo** (or append `?demo=1`) for a fully
self-contained synthetic café with no backend at all.

## 3. Offline self-tests (no backend, no key)

```bash
python -m agent.policy          # exercise the rule engine on synthetic scenes, print actions
python -m agent.agent --once    # replay synthetic scenes through the agent, print actions
python -m federated.flock_model # run the federated learning demo (3 simulated cafés)
python -m eval.run_eval && python -m eval.score   # perception accuracy eval
```

## 4. Real perception

```bash
python -m perception.run --source 0                          # webcam → POST SceneEvents (+ MJPEG /stream)
python -m perception.run --source clips/people-walking.mp4   # a video file
python -m perception.run --source 0 --privacy-mode           # strip bboxes + DP-noise the heatmap
python -m perception.run --source clips/x.mp4 --dry-run --max-frames 60   # no backend, just print
```

Real venue geometry (instead of placeholder vertical-band zones):

```bash
# Option A — the scanner PWA: open /scan/, pick a layout or trace your own, "Push to live"
# Option B — generate a believable preset headlessly:
python -m perception.run --preset counter_top --tables 6 --gen-zones zones.json
# Option C — draw polygons by hand on a camera frame (GUI):
python -m perception.draw_zones --source 0 --out zones.json
# then run with it:
python -m perception.run --source 0 --zones zones.json
```

## 5. Real devices (actuators)

```bash
python -m actuators.run     # subscribe to /ws and drive whatever is configured in .env
```

Fill in `.env` for the devices you actually have (everything is optional and degrades gracefully):

| Device | Env vars | One-time setup |
|---|---|---|
| **Agent (Claude)** | `ANTHROPIC_API_KEY`, `AGENT_MODEL` | leave blank to use the deterministic rule policy |
| **Spotify** | `SPOTIPY_CLIENT_ID/SECRET/REDIRECT_URI` | Premium + an active device; run OAuth once: `python -m actuators.spotify 40` (redirect must be `127.0.0.1`, not `localhost`) |
| **AC / heater (IR)** | `BROADLINK_HOST`, `BROADLINK_IR_COOL/WARM` | `python -m actuators.infrared --discover`, then `--learn cool|warm` |
| **Lighting (Hue)** | `HUE_BRIDGE_IP`, `HUE_GROUP` | press the bridge button, then `python -m actuators.lights 70 warm` to pair |
| **Scent** | `SCENT_WEBHOOK_URL` *or* `SCENT_IR_ON/OFF` | a webhook (Home Assistant / Shelly / IFTTT) or learned IR codes |
| **Telegram** | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | `@BotFather` → `/newbot`; message the bot, then `python -m actuators.notify --chat-id` |

## 6. Point at a remote backend

Producers, the agent, and actuators all read the hub address from `.env`:

```bash
BACKEND_URL=https://golden-coffee-production.up.railway.app
BACKEND_WS=wss://golden-coffee-production.up.railway.app/ws
```

Optionally set `INGEST_TOKEN` (a shared secret) — if set on the hub, producers must send it as the
`X-Token` header on `/ingest` and `/frame`. Left blank in dev so the demo "just works."

## 7. Deploy

- **Hub → Railway** (FastAPI WebSocket server + dashboard): see [DEPLOY.md](../DEPLOY.md).
- **Marketing/onboarding app & static dashboard → Vercel**: see [VERCEL.md](../VERCEL.md).
