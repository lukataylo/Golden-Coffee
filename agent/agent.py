"""Golden Coffee agent — thin Claude tool-use loop over scene events.

Subscribes to the backend websocket, maintains a short rolling state, and on each
tick asks Claude (with tool definitions = our real-world actions) whether to act.
Decisions are POSTed back to /action. Actions are debounced so the agent doesn't
thrash devices.

This is deliberately small and fully ours (vs. adopting a heavyweight framework).
P2 extends the policy / discount engine here.

Run:  python -m agent.agent
Env:  BACKEND_URL, BACKEND_WS, ANTHROPIC_API_KEY, AGENT_MODEL
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import websockets

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
BACKEND_WS = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8000/ws")
MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-8")
DEBOUNCE_S = float(os.environ.get("AGENT_DEBOUNCE_S", "15"))

SYSTEM = (
    "You are the operations copilot for a coffee shop. You receive anonymized scene "
    "metrics (occupancy, queue length, dwell times, staff activity, conversion funnel). "
    "Act ONLY when it clearly helps service, turnover, or conversion. Prefer the gentlest "
    "effective action. Never identify individuals. Always give a one-sentence rationale. "
    "If nothing needs doing, call no tool."
)

TOOLS = [
    {
        "name": "set_music_volume",
        "description": "Set Spotify volume 0-100. Raise to lift energy during lulls.",
        "input_schema": {
            "type": "object",
            "properties": {"volume": {"type": "integer"}, "rationale": {"type": "string"}},
            "required": ["volume", "rationale"],
        },
    },
    {
        "name": "set_temperature",
        "description": "Nudge ambient temperature via smart-plug fan/heater. delta_c negative = cooler (encourages turnover).",
        "input_schema": {
            "type": "object",
            "properties": {"delta_c": {"type": "number"}, "rationale": {"type": "string"}},
            "required": ["delta_c", "rationale"],
        },
    },
    {
        "name": "push_discount",
        "description": "Fire a time/occupancy-based promo to the in-store board to smooth demand.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["text", "rationale"],
        },
    },
    {
        "name": "notify_staff",
        "description": "Send a Slack/Telegram alert to staff (queue build-up, free-ride, idle flag).",
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
    def __init__(self) -> None:
        self.last_action_at: dict[str, float] = {}
        from anthropic import Anthropic  # imported lazily so the module loads without a key

        self.client = Anthropic()

    def _debounced(self, name: str) -> bool:
        return (time.time() - self.last_action_at.get(name, 0)) < DEBOUNCE_S

    async def decide(self, scene: dict) -> None:
        msg = self.client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=SYSTEM,
            tools=TOOLS,
            messages=[{"role": "user", "content": f"Current scene: {_summarize(scene)}. Act if warranted."}],
        )
        for block in msg.content:
            if block.type != "tool_use" or self._debounced(block.name):
                continue
            self.last_action_at[block.name] = time.time()
            params = dict(block.input)
            rationale = params.pop("rationale", "")
            action = {
                "type": "action",
                "ts": time.time(),
                "action": block.name,
                "params": params,
                "rationale": rationale,
                "reversible": True,
                "auto": True,
            }
            async with httpx.AsyncClient(timeout=3.0) as http:
                await http.post(f"{BACKEND_URL}/action", json=action)
            print(f"[agent] {block.name} {params} — {rationale}")


async def main() -> None:
    agent = Agent()
    print(f"[agent] connecting to {BACKEND_WS} (model={MODEL})")
    async with websockets.connect(BACKEND_WS) as sock:
        async for raw in sock:
            data = json.loads(raw)
            if data.get("type") == "scene":
                try:
                    await agent.decide(data)
                except Exception as exc:
                    print(f"[agent] decide failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
