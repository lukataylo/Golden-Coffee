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

import httpx
import websockets

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent import policy

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
BACKEND_WS = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8000/ws")
MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-8")
USE_CLAUDE = bool(os.environ.get("ANTHROPIC_API_KEY"))
DEBOUNCE_S = float(os.environ.get("AGENT_DEBOUNCE_S", "15"))

SYSTEM = (
    "You are the ambient + service copilot for a coffee shop. You receive anonymized "
    "scene metrics (occupancy, queue length, dwell times, room energy, conversion funnel). "
    "Every action must help the CUSTOMER or the STAFF — tune the atmosphere (music, "
    "comfort) and protect speed-of-service. Never punish customers or staff: no surge "
    "pricing, no using discomfort to move people along, no individual tracking. Prefer the "
    "gentlest effective action and always give a one-sentence, customer-friendly rationale. "
    "If nothing needs doing, call no tool."
)

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


def _summarize(scene: dict) -> str:
    f = scene.get("funnel", {})
    long_dwellers = [t for t in scene.get("tracks", []) if t.get("zone") == "seating" and t.get("dwell_s", 0) > 600]
    return (
        f"occupancy={scene.get('occupancy')} queue_len={scene.get('queue_len')} "
        f"staff_productivity={scene.get('staff_productivity')} cups_made={scene.get('cups_made')} "
        f"funnel(entered={f.get('entered')},ordered={f.get('ordered')},abandoned={f.get('abandoned')}) "
        f"long_dwellers={len(long_dwellers)}"
    )


class Agent:
    """Decides actions for a scene and posts them to the hub.

    Rule-based by default; Claude is opt-in via ANTHROPIC_API_KEY.
    """

    def __init__(self, use_claude: bool = USE_CLAUDE) -> None:
        # Policy owns its own debounce state across the whole run.
        self.state: dict = {}
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

    # --- decision making ---------------------------------------------------
    def decide_actions(self, scene: dict) -> list[dict]:
        """Return a list of AgentAction dicts for this scene."""
        if self.use_claude and self.client is not None:
            try:
                return self._decide_claude(scene)
            except Exception as exc:
                print(f"[agent] Claude decide failed ({exc}); falling back to rules")
        return [a.model_dump() for a in policy.decide(scene, self.state)]

    def _decide_claude(self, scene: dict) -> list[dict]:
        msg = self.client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=SYSTEM,
            tools=TOOLS,
            messages=[{"role": "user", "content": f"Current scene: {_summarize(scene)}. Act if warranted."}],
        )
        now = time.time()
        out: list[dict] = []
        for block in msg.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            # Reuse the policy's debounce bookkeeping so Claude can't thrash devices.
            if not policy._due(self.state, block.name, now):
                continue
            policy._mark(self.state, block.name, now)
            params = dict(block.input)
            rationale = params.pop("rationale", "")
            out.append({
                "type": "action", "ts": now, "action": block.name,
                "params": params, "rationale": rationale,
                "reversible": True, "auto": True,
            })
        return out

    # --- output ------------------------------------------------------------
    async def act_on(self, scene: dict, http: httpx.AsyncClient | None) -> list[dict]:
        actions = self.decide_actions(scene)
        for action in actions:
            print(f"[agent] {action['action']} {action['params']} — {action['rationale']}")
            if http is not None:
                try:
                    await http.post(f"{BACKEND_URL}/action", json=action)
                except Exception as exc:
                    print(f"[agent] post failed: {exc}")
        return actions


async def run_live() -> None:
    agent = Agent()
    print(f"[agent] connecting to {BACKEND_WS}")
    async with websockets.connect(BACKEND_WS) as sock, httpx.AsyncClient(timeout=3.0) as http:
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
        actions = [a.model_dump() for a in policy.decide(scene, agent.state)]
        for a in actions:
            total += 1
            print(f"t={t:>2} occ={scene['occupancy']:>2} q={scene['queue_len']} "
                  f"-> {a['action']} {a['params']} | {a['rationale']}")
            if post:
                try:
                    httpx.post(f"{BACKEND_URL}/action", json=a, timeout=2.0)
                except Exception as exc:
                    print(f"      (post failed: {exc})")
    print(f"\n[agent] replay complete — {total} action(s) produced")


def main() -> None:
    args = sys.argv[1:]
    if "--once" in args:
        run_once(post="--post" in args)
        return
    asyncio.run(run_live())


if __name__ == "__main__":
    main()
