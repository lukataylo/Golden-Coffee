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

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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
        # Latest annotated JPEG frame (boxes + zones already drawn by perception)
        # plus a monotonically increasing version so MJPEG subscribers can detect
        # new frames without an explicit event/condition.
        self.last_frame: bytes | None = None
        self.frame_version: int = 0

    def set_frame(self, data: bytes) -> None:
        self.last_frame = data
        self.frame_version += 1

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
    return {
        "ok": True,
        "clients": len(hub.clients),
        "has_scene": hub.last_scene is not None,
        "has_frame": hub.last_frame is not None,
    }


@app.post("/frame")
async def frame(request: Request) -> dict:
    """Perception POSTs the latest annotated JPEG (raw image/jpeg body) here."""
    data = await request.body()
    if data:
        hub.set_frame(data)
    return {"ok": True, "bytes": len(data)}


@app.get("/frame.jpg")
async def frame_jpg() -> Response:
    """Latest single annotated frame (poster / polling fallback)."""
    if hub.last_frame is None:
        return Response(status_code=404)
    return Response(
        content=hub.last_frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/stream")
async def stream() -> StreamingResponse:
    """MJPEG (multipart/x-mixed-replace) of the latest annotated frame.

    Consumed directly by an <img src="/stream"> in the dashboard. Polls the
    frame version ~25x/s and emits whenever a new frame arrives.
    """
    boundary = "frame"

    async def gen():
        last_sent = -1
        idle = 0
        while True:
            if hub.frame_version != last_sent and hub.last_frame is not None:
                last_sent = hub.frame_version
                idle = 0
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(hub.last_frame)).encode() + b"\r\n\r\n"
                    + hub.last_frame + b"\r\n"
                )
            else:
                idle += 1
                # Stop a stale connection after ~30s with no new frames so the
                # client can fall back to /frame.jpg or the synthetic map.
                if idle > 750:
                    break
            await asyncio.sleep(0.04)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}"
    )


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
