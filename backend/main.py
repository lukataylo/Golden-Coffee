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
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

# Load .env so local runs see keys (Spotify, tokens, etc.). On Railway the real
# env vars are injected and take precedence — load_dotenv never overrides them.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from shared.schemas import AgentAction, MusicModeEvent, SceneEvent

# Repo root is the parent of this file's directory (backend/). Resolve to an
# absolute path so static serving works regardless of the container CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "dashboard"

# Optional shared-secret: if INGEST_TOKEN is set, producers must send it as
# X-Token on /ingest and /frame. Left empty in dev so the demo "just works".
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")
# Append-only metrics history (for Track B's footfall/labour forecasting).
METRICS_PATH = REPO_ROOT / "data" / "metrics.jsonl"
# Active floorplan geometry (zones.json shape) scanned by the PWA — perception
# (--zones) and the dashboard read this to use real venue geometry.
GEOMETRY_PATH = REPO_ROOT / "data" / "geometry.json"
CONFIG_PATH   = REPO_ROOT / "data" / "config.json"


def _require_token(x_token: Optional[str]) -> None:
    if INGEST_TOKEN and x_token != INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="bad or missing X-Token")


def _log_metrics(event: dict) -> None:
    """Append a compact metrics row so history has a record. Best-effort."""
    row = {
        "ts": event.get("ts"),
        "occupancy": event.get("occupancy", 0),
        "queue_len": event.get("queue_len", 0),
        "tables_waiting": sum(
            1 for t in event.get("tables", []) if t.get("status") in ("waiting", "overdue")
        ),
        "cleaning_overdue": sum(
            1 for c in event.get("cleaning", []) if c.get("status") == "overdue"
        ),
    }
    try:
        METRICS_PATH.parent.mkdir(exist_ok=True)
        with METRICS_PATH.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:
        pass  # never let logging break ingestion

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
        self.last_scene: Optional[dict] = None
        self.action_log: deque[dict] = deque(maxlen=50)
        self._lock = asyncio.Lock()
        # Latest annotated JPEG frame (boxes + zones already drawn by perception)
        # plus a monotonically increasing version so MJPEG subscribers can detect
        # new frames without an explicit event/condition.
        self.last_frame: Optional[bytes] = None
        self.frame_version: int = 0
        self.geometry: Optional[dict] = None  # active floorplan geometry (zones.json)
        # Music mode — "auto" (model picks) or "custom" (employee picks).
        self.music_mode: str = "auto"
        self.music_source: dict = {}

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
            # Send a COPY tagged as replayed so consumers (e.g. the actuator
            # executor) can skip re-firing real devices. Don't mutate the stored
            # dict — the dashboard still wants the un-flagged history.
            await ws.send_json({**action, "replayed": True})
        # Always send current music mode so a freshly-connected agent/dashboard
        # knows whether to suppress music actions.
        await ws.send_json({
            "type": "music_mode", "ts": time.time(),
            "mode": self.music_mode, **self.music_source,
        })

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            dead = []
            # Iterate a snapshot: connect()/disconnect() can mutate self.clients
            # during the await below (set-changed-size-during-iteration -> 500).
            for ws in list(self.clients):
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
async def frame(request: Request, x_token: Optional[str] = Header(None)) -> dict:
    """Perception POSTs the latest annotated JPEG (raw image/jpeg body) here."""
    _require_token(x_token)
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
                if idle > 3750:
                    break
            # Poll fast (~8ms) so a new frame reaches the browser with minimal added
            # latency (the old 40ms poll added up to 40ms and capped /stream at 25fps).
            await asyncio.sleep(0.008)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}"
    )


@app.post("/ingest")
async def ingest(event: SceneEvent, x_token: Optional[str] = Header(None)) -> dict:
    """Producers (mock_events or perception) push scenes here."""
    _require_token(x_token)
    payload = event.model_dump()
    hub.last_scene = payload
    _log_metrics(payload)
    await hub.broadcast(payload)
    return {"ok": True}


@app.get("/metrics")
async def metrics(limit: int = 200) -> dict:
    """Recent metrics history + a small summary (for forecasting / the pitch)."""
    rows: list[dict] = []
    if METRICS_PATH.exists():
        lines = METRICS_PATH.read_text().splitlines()[-limit:]
        for ln in lines:
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    summary = {
        "samples": len(rows),
        "peak_occupancy": max((r.get("occupancy", 0) for r in rows), default=0),
    }
    return {"summary": summary, "recent": rows}


@app.post("/onchain/snapshot")
async def onchain_snapshot(limit: int = 500) -> dict:
    """Anchor the anonymized metrics history + agent ACTION audit trail to Walrus
    (Sui ecosystem) — a tamper-proof, independently-verifiable record of what the
    café AI did, privacy-first (aggregate numbers only, no faces). Returns the
    Walrus blobId + a public read URL anyone can verify."""
    from onchain.walrus import store_blob

    rows: list[dict] = []
    if METRICS_PATH.exists():
        for ln in METRICS_PATH.read_text().splitlines()[-limit:]:
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    snapshot = {
        "kind": "golden-coffee-ops-snapshot",
        "ts": time.time(),
        "metrics": rows,
        "actions": list(hub.action_log),  # the agent's action audit trail + rationales
        "summary": {
            "metric_samples": len(rows),
            "actions_logged": len(hub.action_log),
            "peak_occupancy": max((r.get("occupancy", 0) for r in rows), default=0),
        },
    }
    try:
        res = await asyncio.to_thread(
            store_blob, json.dumps(snapshot).encode(), 5
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Walrus store failed: {exc}")
    return {"ok": True, "walrus": res, "anchored": snapshot["summary"]}


@app.post("/geometry")
async def set_geometry(request: Request) -> dict:
    """Store the active floorplan geometry (zones.json shape) scanned by the PWA.
    perception (--zones) and the dashboard read this to use the REAL venue layout.
    Open like /override (browser/PWA writes it)."""
    try:
        geo = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(geo, dict) or not any(k in geo for k in ("zones", "tables", "cleaning")):
        raise HTTPException(status_code=422, detail="expected zones.json shape (zones/tables/cleaning)")
    try:
        GEOMETRY_PATH.parent.mkdir(exist_ok=True)
        GEOMETRY_PATH.write_text(json.dumps(geo))
    except Exception:
        pass
    hub.geometry = geo
    await hub.broadcast({"type": "geometry", "geometry": geo})  # live dashboards can re-render
    return {
        "ok": True,
        "zones": list((geo.get("zones") or {}).keys()),
        "tables": list((geo.get("tables") or {}).keys()),
        "cleaning": list((geo.get("cleaning") or {}).keys()),
    }


@app.get("/geometry")
async def get_geometry() -> dict:
    """Return the active floorplan geometry (or {} if none scanned yet)."""
    if hub.geometry is not None:
        return hub.geometry
    if GEOMETRY_PATH.exists():
        try:
            return json.loads(GEOMETRY_PATH.read_text())
        except Exception:
            pass
    return {}


@app.get("/config")
async def get_config() -> dict:
    """Return persisted venue config (camera source, etc.)."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


@app.post("/config")
async def set_config(request: Request) -> dict:
    """Persist venue config written by the setup wizard (camera source, etc.)."""
    body = await request.json()
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    # Merge with existing config so we don't overwrite unrelated keys
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    existing.update(body)
    CONFIG_PATH.write_text(json.dumps(existing, indent=2))
    return {"ok": True, **existing}


_ASK_SYSTEM = (
    "You are the comfort copilot for a coffee shop. Map the staff's natural-language "
    "request to ONE action. Reply with ONLY a JSON object: "
    '{"action": one of set_music_volume|set_temperature|set_lighting|set_scent|push_discount|notify_staff, '
    '"params": {...}, "rationale": "one short sentence"}. '
    "Params: set_music_volume{volume:0-100}, set_temperature{target_c:16-26}, "
    "set_lighting{brightness:0-100,warmth:warm|neutral|cool}, set_scent{intensity:0-100,scent}, "
    "push_discount{text}, notify_staff{text}. No prose, JSON only."
)


def _ask_keyword(q: str) -> Optional[dict]:
    """Deterministic fallback when no LLM is configured."""
    t = q.lower()
    if any(w in t for w in ("warmer", "warm up", "warm it", "cold", "chilly", "freezing", "heat")):
        return {"action": "set_temperature", "params": {"target_c": 22.5}, "rationale": "Warming the room."}
    if any(w in t for w in ("cooler", "cool down", "cool it", "too warm", "too hot", "hot", "stuffy")):
        return {"action": "set_temperature", "params": {"target_c": 19.5}, "rationale": "Cooling the room."}
    if any(w in t for w in ("louder", "turn up", "more music")):
        return {"action": "set_music_volume", "params": {"volume": 65}, "rationale": "Lifting the music."}
    if any(w in t for w in ("quieter", "softer", "turn down")):
        return {"action": "set_music_volume", "params": {"volume": 35}, "rationale": "Softening the music."}
    if any(w in t for w in ("dim", "cosy", "cozy", "warm glow")):
        return {"action": "set_lighting", "params": {"brightness": 35, "warmth": "warm"}, "rationale": "Dimming to a warm glow."}
    if "bright" in t:
        return {"action": "set_lighting", "params": {"brightness": 85, "warmth": "neutral"}, "rationale": "Brightening the room."}
    if any(w in t for w in ("fresh", "scent", "air")):
        return {"action": "set_scent", "params": {"intensity": 60, "scent": "fresh citrus"}, "rationale": "Freshening the air."}
    if any(w in t for w in ("treat", "discount", "offer")):
        return {"action": "push_discount", "params": {"text": "20% off pastries"}, "rationale": "Sharing a treat."}
    if any(w in t for w in ("till", "queue", "staff", "help")):
        return {"action": "notify_staff", "params": {"text": "Open a second till — queue building."}, "rationale": "Calling for a hand."}
    return None


@app.post("/ask")
async def ask(request: Request) -> dict:
    """Natural-language command -> one comfort action. Uses the LLM (Claude → Gemini
    backup, see shared.llm) and falls back to a keyword parser. Broadcasts the action
    like /override so the dashboard + actuators react. Powers the dashboard command bar."""
    from shared import llm

    try:
        q = str((await request.json()).get("q", "")).strip()
    except Exception:
        q = ""
    if not q:
        raise HTTPException(status_code=400, detail="missing q")

    parsed: Optional[dict] = None
    text = await asyncio.to_thread(llm.complete, _ASK_SYSTEM, q, 200)
    if text:
        try:
            s = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            cand = json.loads(s)
            if isinstance(cand, dict) and "action" in cand:
                parsed = cand
        except Exception:
            pass
    if parsed is None:
        parsed = _ask_keyword(q)
    if parsed is None:
        return {"ok": False, "reason": "could not interpret", "provider": llm.provider()}

    act = AgentAction(
        ts=time.time(), action=parsed["action"], params=parsed.get("params", {}),
        rationale=parsed.get("rationale", q), auto=False,
    ).model_dump()
    hub.action_log.append(act)
    await hub.broadcast(act)
    return {"ok": True, "action": act, "provider": llm.provider() or "keyword"}


@app.post("/action")
async def action(act: AgentAction, x_token: Optional[str] = Header(None)) -> dict:
    """The agent pushes decisions here. The actuator executor (actuators/run.py)
    subscribes over /ws and drives the real devices (Spotify / IR / Telegram)."""
    _require_token(x_token)
    payload = act.model_dump()
    hub.action_log.append(payload)
    await hub.broadcast(payload)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Spotify OAuth — server-side token store so any desktop can use the SDK.
# One-time setup: visit  GET /spotify/auth  in a browser, click Allow.
# After that /spotify/token returns a fresh token to any dashboard client.
# ---------------------------------------------------------------------------
import base64 as _b64
import httpx as _httpx

_SP_SCOPE = "user-modify-playback-state user-read-playback-state streaming"
# Seed the refresh token from env so Spotify auth SURVIVES restarts/redeploys
# (in-memory alone is wiped every container restart). Authorize once, set
# SPOTIPY_REFRESH_TOKEN on Railway, and it stays connected forever.
_sp_refresh_tok: Optional[str] = os.environ.get("SPOTIPY_REFRESH_TOKEN") or None
_sp_access_tok:  Optional[str] = None
_sp_expires_at:  float = 0.0


def _sp_public_base() -> str:
    """Public base URL of this backend, for the OAuth redirect URI.
    Prefers BACKEND_URL, then Railway's injected public domain, then localhost."""
    base = os.environ.get("BACKEND_URL", "").rstrip("/")
    if base:
        return base
    dom = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").rstrip("/")
    if dom:
        return f"https://{dom}"
    return "http://127.0.0.1:8000"


def _sp_callback_uri() -> str:
    return f"{_sp_public_base()}/spotify/callback"


async def _sp_do_refresh(refresh_token: str) -> str | None:
    global _sp_access_tok, _sp_expires_at
    cid  = os.environ.get("SPOTIPY_CLIENT_ID", "")
    csec = os.environ.get("SPOTIPY_CLIENT_SECRET", "")
    if not (cid and csec):
        return None
    creds = _b64.b64encode(f"{cid}:{csec}".encode()).decode()
    try:
        async with _httpx.AsyncClient() as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {creds}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            )
        if r.status_code == 200:
            tok = r.json()
            _sp_access_tok = tok["access_token"]
            _sp_expires_at = time.time() + tok.get("expires_in", 3600) - 60
            return _sp_access_tok
    except Exception:
        pass
    return None


@app.get("/spotify/auth")
async def spotify_auth():
    """Redirect to Spotify OAuth. Visit once in any browser; token stored server-side
    so every dashboard client can call /spotify/token without their own auth."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import urlencode
    cid = os.environ.get("SPOTIPY_CLIENT_ID", "")
    if not cid:
        raise HTTPException(status_code=503, detail="SPOTIPY_CLIENT_ID not set — add it to .env / Railway vars")
    params = urlencode({
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": _sp_callback_uri(),
        "scope": _SP_SCOPE,
    })
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{params}")


@app.get("/spotify/callback")
async def spotify_callback(code: Optional[str] = None, error: Optional[str] = None) -> dict:
    """Spotify redirects here after the user clicks Allow. Exchanges the code for
    access + refresh tokens and stores them in memory for all subsequent requests."""
    global _sp_refresh_tok, _sp_access_tok, _sp_expires_at
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify auth denied: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code parameter")
    cid  = os.environ.get("SPOTIPY_CLIENT_ID", "")
    csec = os.environ.get("SPOTIPY_CLIENT_SECRET", "")
    if not (cid and csec):
        raise HTTPException(status_code=503, detail="Spotify credentials not configured")
    creds = _b64.b64encode(f"{cid}:{csec}".encode()).decode()
    async with _httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code",
                  "code": code,
                  "redirect_uri": _sp_callback_uri()},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {r.text}")
    tok = r.json()
    _sp_refresh_tok = tok.get("refresh_token")
    _sp_access_tok  = tok.get("access_token")
    _sp_expires_at  = time.time() + tok.get("expires_in", 3600) - 60
    return {"ok": True, "message": "Spotify connected — dashboard is ready on any device. You can close this tab."}


@app.get("/spotify/token")
async def spotify_token() -> dict:
    """Return a fresh Spotify access token for the Web Playback SDK.
    Returns {"error":...} (not 4xx) so the dashboard degrades gracefully."""
    global _sp_access_tok, _sp_expires_at
    # 1. In-memory tokens (set after /spotify/callback)
    if _sp_refresh_tok:
        if _sp_access_tok and time.time() < _sp_expires_at:
            return {"access_token": _sp_access_tok}
        refreshed = await _sp_do_refresh(_sp_refresh_tok)
        if refreshed:
            return {"access_token": refreshed}
    # 2. Fall back to local spotipy cache (dev machines that ran OAuth locally)
    cache = Path(".spotipy-cache")
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            if data.get("expires_at", 0) > time.time() + 60:
                return {"access_token": data["access_token"]}
            if data.get("refresh_token"):
                refreshed = await _sp_do_refresh(data["refresh_token"])
                if refreshed:
                    return {"access_token": refreshed}
        except Exception:
            pass
    return {"error": "not authenticated — visit /spotify/auth to connect Spotify"}


@app.get("/music/mode")
async def get_music_mode() -> dict:
    """Current music mode + source (for dashboard on load)."""
    return {"mode": hub.music_mode, **hub.music_source}


@app.post("/music/mode")
async def set_music_mode(event: MusicModeEvent) -> dict:
    """Frontend toggle: switch between auto and custom mode.

    Auto   — agent music model picks genre/mood from the room state.
    Custom — employee controls music (Spotify/YouTube connect or playlist URL).
             Agent silences all set_music / set_music_volume actions.
    """
    hub.music_mode = event.mode.value
    hub.music_source = {
        "source_kind": event.source_kind,
        "source_value": event.source_value,
    }
    payload = event.model_dump()
    await hub.broadcast(payload)
    return {"ok": True, "mode": hub.music_mode}


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
