"""Golden Coffee agent — turns scene metrics into real-world actions.

By default the agent runs a deterministic, rule-based policy (`agent.policy`):
it needs no API key and no model, so the MVP works anywhere. If an
ANTHROPIC_API_KEY is present, the (preserved) Claude tool-use path is layered on
top to add judgement; either way the resulting `AgentAction`s are POSTed to
`${BACKEND_URL}/action`. Actions are debounced inside the policy so we don't
thrash devices.

Run:
  python -m agent.agent            # live: subscribe to WS, act on each scene
  python -m agent.agent --once     # offline: replay synthetic scenes, print actions

Env:  BACKEND_URL, BACKEND_WS, ANTHROPIC_API_KEY, AGENT_MODEL
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Optional

import httpx
import websockets

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent import policy
from agent.forecast import FootfallForecast

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
BACKEND_WS  = os.environ.get("BACKEND_WS",  "ws://127.0.0.1:8000/ws")
MODEL       = os.environ.get("AGENT_MODEL", "claude-opus-4-8")
USE_CLAUDE  = bool(os.environ.get("ANTHROPIC_API_KEY"))
_TOKEN_HEADERS = {"X-Token": os.environ["INGEST_TOKEN"]} if os.environ.get("INGEST_TOKEN") else {}

SYSTEM = (
    "You are the ambient + service copilot for a coffee shop. You receive anonymized "
    "scene metrics (occupancy, queue, dwell times, room energy, funnel, tables, cleaning). "
    "Every action must help the CUSTOMER or the STAFF — tune the atmosphere (music, "
    "lighting, scent, comfort) and protect speed-of-service. "
    "Rules: no surge pricing, no discomfort to move people along, no individual tracking. "
    "Prefer the gentlest effective action. Always give a one-sentence customer-friendly "
    "rationale. If nothing needs doing, call no tool."
)

# Maps Claude tool names → policy debounce key so the same windows apply
# whether the rule engine or Claude fires an action.
_CLAUDE_DEBOUNCE: dict[str, str] = {
    "set_music_volume": "music",
    "set_music":        "music_mood",
    "set_temperature":  "temperature",
    "set_lighting":     "lighting",
    "set_scent":        "scent",
    "push_discount":    "discount_quiet",
    "notify_staff":     "notify_queue",
    "suggest_layout":   "suggest_layout",
}

TOOLS = [
    {
        "name": "set_music_volume",
        "description": "Set Spotify volume 0-100. Raise to lift the vibe in a lull; lower to keep a busy room pleasant.",
        "input_schema": {
            "type": "object",
            "properties": {"volume": {"type": "integer"}, "rationale": {"type": "string"}},
            "required": ["volume", "rationale"],
        },
    },
    {
        "name": "set_music",
        "description": (
            "Change WHAT music is playing (mood/genre/playlist), not just volume. "
            "Use the local music model's vibes: 'sunrise_acoustic' (quiet morning), "
            "'daytime_focus' (steady daytime), 'upbeat_lift' (flat/low-energy room), "
            "'rush_flow' (queue building — steady groove keeps the line moving), "
            "'busy_calm' (full room — soft so it stays talkable), 'evening_warm' (evening wind-down). "
            "Switch the mood when the room's state clearly calls for a different vibe."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["sunrise_acoustic", "daytime_focus", "upbeat_lift",
                             "rush_flow", "busy_calm", "evening_warm"],
                },
                "rationale": {"type": "string"},
            },
            "required": ["mood", "rationale"],
        },
    },
    {
        "name": "set_temperature",
        "description": "Adjust the AC/heater (IR blaster) for guest COMFORT. delta_c negative = cooler (e.g. a full, warming room).",
        "input_schema": {
            "type": "object",
            "properties": {"delta_c": {"type": "number"}, "rationale": {"type": "string"}},
            "required": ["delta_c", "rationale"],
        },
    },
    {
        "name": "set_lighting",
        "description": "Set smart-light brightness (0-100) and warmth for comfort/ambiance. Warm+dim = cozy lull/evening; brighter+neutral = busy/daytime.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brightness": {"type": "integer"},
                "warmth": {"type": "string", "enum": ["warm", "neutral", "cool"]},
                "rationale": {"type": "string"},
            },
            "required": ["brightness", "warmth", "rationale"],
        },
    },
    {
        "name": "set_scent",
        "description": "Set the scent diffuser intensity (0-100) and scent for comfort. Freshen the air when busy/stuffy; a warm scent for a cozy lull.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intensity": {"type": "integer"},
                "scent": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["intensity", "scent", "rationale"],
        },
    },
    {
        "name": "push_discount",
        "description": "Fire an off-peak/fill-the-trough promo to the in-store board to smooth demand. Never a surge/peak surcharge.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["text", "rationale"],
        },
    },
    {
        "name": "notify_staff",
        "description": "Send a Telegram alert to staff (queue building, or a seated guest who could use a check-in).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["text", "rationale"],
        },
    },
]


def _scene_summary(scene: dict) -> str:
    """Build a compact, complete scene description for Claude's context window."""
    f        = scene.get("funnel",   {}) or {}
    tables   = scene.get("tables",   []) or []
    cleaning = scene.get("cleaning", []) or []

    long_dwellers   = [t for t in scene.get("tracks", [])
                       if t.get("zone") == "seating" and t.get("dwell_s", 0) > 600]
    overdue_tables  = [t for t in tables if t.get("status") == "overdue"]
    dirty_tables    = [t for t in tables if t.get("needs_cleaning")]
    overdue_zones   = [c for c in cleaning if c.get("status") == "overdue"]

    hour = time.localtime(scene.get("ts") or time.time()).tm_hour

    parts = [
        f"time={hour:02d}:xx",
        f"occupancy={scene.get('occupancy')}  queue={scene.get('queue_len')}",
        f"room_energy={scene.get('staff_productivity', 0):.2f}",
        f"cups_made={scene.get('cups_made', 0)}",
        (f"funnel(entered={f.get('entered',0)} ordered={f.get('ordered',0)} "
         f"abandoned={f.get('abandoned',0)})"),
        f"long_dwellers={len(long_dwellers)}",
    ]
    if overdue_tables:
        worst = max(overdue_tables, key=lambda t: t.get("wait_s", 0))
        parts.append(
            f"overdue_tables={len(overdue_tables)} "
            f"worst={worst['id']}@{int(worst.get('wait_s',0)//60)}min"
        )
    if dirty_tables:
        parts.append(f"tables_need_bussing={len(dirty_tables)}")
    if overdue_zones:
        parts.append(f"cleaning_overdue=[{','.join(c['id'] for c in overdue_zones)}]")

    return "  ".join(parts)


class Agent:
    """Decides actions for a scene and posts them to the hub.

    Rule-based by default; Claude is opt-in via ANTHROPIC_API_KEY.
    """

    def __init__(self, use_claude: bool = USE_CLAUDE) -> None:
        self.state: dict = {}
        self.forecast = FootfallForecast()
        self._forecast_debounce: float = 0.0
        self.use_claude = use_claude
        self.client = None
        if self.use_claude:
            try:
                from anthropic import Anthropic  # lazy: module imports fine without a key
                self.client = Anthropic()
                print(f"[agent] Claude path enabled (model={MODEL})")
            except Exception as exc:
                print(f"[agent] Claude unavailable ({exc}); using rule-based policy only")
                self.use_claude = False
        if not self.use_claude:
            print("[agent] rule-based policy (no API key) — deterministic decisions")

    # --- footfall forecast -------------------------------------------------
    def _forecast_actions(self, scene: dict, now: float) -> list[dict]:
        """Update the forecast model and emit a staffing note if the next hour
        looks significantly busier. Debounced to once per 10 minutes."""
        hour = time.localtime(now).tm_hour
        self.forecast.update(hour, float(scene.get("occupancy", 0)))
        if now - self._forecast_debounce < 600:
            return []
        note = self.forecast.staffing_note(
            current_occ=int(scene.get("occupancy", 0)),
            current_hour=hour,
        )
        if not note:
            return []
        self._forecast_debounce = now
        return [{
            "type": "action", "ts": now,
            "action": "notify_staff",
            "params": {"text": note, "priority": "low"},
            "rationale": f"Footfall forecast: next hour predicted busier — early heads-up.",
            "reversible": True, "auto": True,
        }]

    # --- decision making ---------------------------------------------------
    def decide_actions(self, scene: dict) -> list[dict]:
        """Return a list of AgentAction dicts for this scene."""
        now = float(scene.get("ts") or time.time())
        if self.use_claude and self.client is not None:
            try:
                actions = self._decide_claude(scene)
            except Exception as exc:
                print(f"[agent] Claude decide failed ({exc}); falling back to rules")
                actions = [a.model_dump() for a in policy.decide(scene, self.state)]
        else:
            actions = [a.model_dump() for a in policy.decide(scene, self.state)]
        actions += self._forecast_actions(scene, now)
        return actions

    def _music_context(self, scene: dict) -> str:
        """A compact read from the local music model, fed to Claude so its
        set_music choice is an *informed* confirm/override — not a blind race
        against the on-device model. Shows the model's top moods + confidence,
        what's playing now, and any active controller bias."""
        from agent.music_model import MOODS
        probs = policy._MUSIC_MODEL.probabilities(scene, self.state.get("music_bias"))
        top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        ranked = ", ".join(f"{MOODS[k].label} {p*100:.0f}%" for k, p in top)
        now_playing = self.state.get("music_mood")
        now_label = MOODS[now_playing].label if now_playing in MOODS else "—"
        line = f"music_model(now={now_label}; suggests {ranked})"
        if self.state.get("music_bias"):
            line += f" bias={self.state['music_bias']}"
        return line

    def _decide_claude(self, scene: dict) -> list[dict]:
        msg = self.client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM,
            tools=TOOLS,
            messages=[{
                "role": "user",
                "content": (
                    f"Current scene: {_scene_summary(scene)}\n"
                    f"{self._music_context(scene)}\n"
                    "Act if warranted. Only call set_music to move OFF the model's "
                    "top suggestion when the room clearly calls for a different vibe."
                ),
            }],
        )
        now = time.time()
        out: list[dict] = []
        for block in msg.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            # Map tool name → policy debounce key so Claude respects the same
            # cooldown windows as the rule engine and can't thrash devices.
            debounce_key = _CLAUDE_DEBOUNCE.get(block.name, block.name)
            if not policy._due(self.state, debounce_key, now):
                print(f"[agent] Claude: {block.name} debounced ({debounce_key})")
                continue
            policy._mark(self.state, debounce_key, now)
            params = dict(block.input)
            rationale = params.pop("rationale", "")
            if block.name == "set_music":
                # Claude only chooses a mood; expand it to the full directive
                # (playlist/BPM/volume/descriptors) from the local music catalog.
                from agent.music_model import MOODS, playlist_for
                mood = params.get("mood", "")
                m = MOODS.get(mood)
                if m is not None:
                    params = {
                        "mood": m.key, "label": m.label,
                        "playlist_uri": playlist_for(m.key),
                        "descriptors": m.descriptors, "bpm": m.bpm,
                        "energy": round(m.energy, 2), "volume": m.volume,
                    }
                    self.state["music_mood"] = m.key
            out.append({
                "type": "action", "ts": now, "action": block.name,
                "params": params, "rationale": rationale,
                "reversible": True, "auto": True,
            })
        return out

    # --- output ------------------------------------------------------------
    async def act_on(self, scene: dict, http: Optional[httpx.AsyncClient]) -> list[dict]:
        actions = self.decide_actions(scene)
        for action in actions:
            print(f"[agent] {action['action']} {action['params']} — {action['rationale']}")
            if http is not None:
                try:
                    await http.post(f"{BACKEND_URL}/action", json=action, headers=_TOKEN_HEADERS)
                except Exception as exc:
                    print(f"[agent] post failed: {exc}")
        return actions


async def run_live() -> None:
    agent = Agent()
    print(f"[agent] connecting to {BACKEND_WS}  (model={'Claude:'+MODEL if agent.use_claude else 'rule-based'})")
    async with httpx.AsyncClient(timeout=3.0) as http:
        while True:
            try:
                async with websockets.connect(BACKEND_WS) as sock:
                    print("[agent] ws connected")
                    async for raw in sock:
                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue
                        if data.get("type") == "scene":
                            try:
                                await agent.act_on(data, http)
                            except Exception as exc:
                                print(f"[agent] decide failed: {exc}")
            except websockets.ConnectionClosed:
                print("[agent] ws disconnected; reconnecting in 3s…")
            except Exception as exc:
                print(f"[agent] ws error ({exc}); reconnecting in 3s…")
            await asyncio.sleep(3)


def run_once(post: bool = False) -> None:
    """Offline replay: feed synthetic scenes to the policy and print actions.

    No websocket and no API key required — proves the policy end to end.
    """
    from shared.mock_events import _synthetic_scene

    agent = Agent(use_claude=False)
    print("[agent] --once replay over synthetic scenes (offline)\n")
    base = time.time()
    total = 0
    for t in range(0, 75, 3):
        scene = _synthetic_scene(t).model_dump()
        scene["ts"] = base + t * 20  # advancing clock so debouncing is realistic
        actions = agent.decide_actions(scene)
        for a in actions:
            total += 1
            print(f"t={t:>2} occ={scene['occupancy']:>2} q={scene['queue_len']} "
                  f"-> {a['action']} {a['params']} | {a['rationale']}")
            if post:
                try:
                    httpx.post(f"{BACKEND_URL}/action", json=a, headers=_TOKEN_HEADERS, timeout=2.0)
                except Exception as exc:
                    print(f"      (post failed: {exc})")
    print(f"\n[agent] replay complete — {total} action(s) produced")


def test_claude() -> None:
    """Offline smoke-test for the Claude path — no WS or backend needed.

    Feeds a handful of synthetic scenes through the Claude tool-use path and
    prints the resulting actions + rationales so you can verify the model is
    reasoning correctly before pointing it at a live stream.

    Requires ANTHROPIC_API_KEY to be set.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[agent] set ANTHROPIC_API_KEY first")
        return

    from shared.mock_events import _synthetic_scene

    agent = Agent(use_claude=True)
    if not agent.use_claude:
        print("[agent] Claude unavailable — check ANTHROPIC_API_KEY")
        return

    print(f"[agent] Claude smoke-test (model={MODEL})\n")
    base = time.time()
    # sample a lull (t=0), medium (t=18), busy peak (t=36)
    for label, t in [("lull", 0), ("medium", 18), ("busy peak", 36)]:
        scene = _synthetic_scene(t).model_dump()
        scene["ts"] = base + t * 30
        print(f"── {label}  occ={scene['occupancy']}  queue={scene['queue_len']} ──")
        print(f"   summary: {_scene_summary(scene)}")
        actions = agent._decide_claude(scene)
        if actions:
            for a in actions:
                print(f"   → {a['action']} {a['params']}")
                print(f"     {a['rationale']}")
        else:
            print("   → (no action)")
        print()


def main() -> None:
    args = sys.argv[1:]
    if "--once" in args:
        run_once(post="--post" in args)
        return
    if "--test-claude" in args:
        test_claude()
        return
    asyncio.run(run_live())


if __name__ == "__main__":
    main()
