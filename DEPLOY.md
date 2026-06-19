# Deploying the Golden Coffee hub to Railway

The hub is a FastAPI WebSocket server that also serves the dashboard UI at `/`.
It must run on a long-lived server (Railway/Render/Fly) — **not** Vercel
serverless, which can't hold a WebSocket open.

This deploy uses the `Dockerfile` at the repo root, which installs only
`requirements-backend.txt` (no torch/ultralytics/opencv — those are perception
deps and are huge/unneeded for the hub).

## Prerequisites

```bash
npm i -g @railway/cli      # or: brew install railway
railway login              # opens a browser to authenticate
```

## First-time deploy

From the repo root:

```bash
railway init               # create a new project (or: railway link to attach to an existing one)
railway up                 # build the Dockerfile and deploy
railway domain             # generate a public https/wss domain
```

`railway up` builds the image, installs `requirements-backend.txt`, and starts:

```
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Railway injects `$PORT` automatically — no need to set it yourself.

## Verify

Open the domain from `railway domain` in a browser — you should see the
dashboard. Health check:

```bash
curl https://<your-domain>/health      # -> {"ok": true, ...}
```

The dashboard connects to its own host's `/ws` by default. To point a
separately hosted dashboard at this backend, pass `?ws=wss://<your-domain>/ws`
in the URL.

## Environment variables

The hub itself needs no secrets. Producers/agent/actuators run on the demo laptop
(`actuators/run.py` drives the devices, not Railway) and read keys from `.env`
(`ANTHROPIC_API_KEY`, Spotify, Broadlink IR, Telegram — see `.env.example`).
If you ever need to set one on the Railway service:

```bash
railway variables --set "ANTHROPIC_API_KEY=sk-ant-..."
```

## Redeploy

```bash
railway up                 # re-run after pushing changes
```
