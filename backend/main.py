"""Golden Coffee backend — the realtime hub.

Decouples producers from consumers so all four workstreams can run independently:

  producers --POST /ingest (SceneEvent)--> [hub] --WS /ws--> dashboard
  agent     --POST /action (AgentAction)-> [hub] --WS /ws--> dashboard + actuators
  dashboard --POST /override-------------> [hub] (human-in-the-loop action)

Run locally:  uvicorn backend.main:app --reload --port 8000
Deploy:       Render / Railway / Fly (NOT Vercel — serverless can't hold a socket).

The hub keeps the last scene + a rolling action log so a freshly-connected
dashboard (or the agent) gets immediate state instead of a blank screen.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from shared.schemas import AgentAction, SceneEvent

# Repo root is the parent of this file's directory (backend/). Resolve to an
# absolute path so static serving works regardless of the container CWD.
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"

app = FastAPI(title="Golden Coffee Hub")

# CORS so the Vercel-hosted dashboard can hit the REST endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Hub:
    """Fan-out to all connected websocket clients + small in-memory history."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.last_scene: dict | None = None
        self.action_log: deque[dict] = deque(maxlen=50)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        # Replay current state to the newcomer.
        if self.last_scene:
            await ws.send_json(self.last_scene)
        for action in self.action_log:
            await ws.send_json(action)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            dead = []
            for ws in self.clients:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws)


hub = Hub()


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "clients": len(hub.clients), "has_scene": hub.last_scene is not None}


@app.post("/ingest")
async def ingest(event: SceneEvent) -> dict:
    """Producers (mock_events or perception) push scenes here."""
    payload = event.model_dump()
    hub.last_scene = payload
    await hub.broadcast(payload)
    return {"ok": True}


@app.post("/action")
async def action(act: AgentAction) -> dict:
    """The agent pushes decisions here. Actuator wiring (Spotify/plug/Slack)
    can subscribe over /ws or be called inline here later."""
    payload = act.model_dump()
    hub.action_log.append(payload)
    await hub.broadcast(payload)
    return {"ok": True}


@app.post("/override")
async def override(act: AgentAction) -> dict:
    """Human-in-the-loop: dashboard buttons fire actions with auto=False."""
    act.auto = False
    act.ts = time.time()
    payload = act.model_dump()
    hub.action_log.append(payload)
    await hub.broadcast(payload)
    return {"ok": True}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await hub.connect(websocket)
    try:
        while True:
            # We don't expect inbound messages, but keep the socket alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)


# --- Static dashboard --------------------------------------------------------
# Serve the dashboard UI at "/". The REST + WS endpoints above are registered
# first, so they always win the route match; this catch-all mount is last.


@app.get("/")
async def index() -> FileResponse:
    """Serve the dashboard's index.html at the site root."""
    return FileResponse(DASHBOARD_DIR / "index.html")


# Mount the whole dashboard/ dir for any other static assets (CSS/JS/images).
# Must be the LAST route registered so it doesn't shadow the API endpoints.
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
