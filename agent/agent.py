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
FED_HISTORY = int(os.environ.get("FED_HISTORY", "60"))  # rolling scene window for ratio estimation
FED_MIN_SCENES = 10  # need at least this much history before the first federation sync
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
            "Time-slot moods: 'morning_rush' (07:00-11:00, upbeat acoustic pop/indie rock), "
            "'midday_dwell' (11:00-15:00, neo-soul/lo-fi hip hop for focus), "
            "'afternoon_lounge' (15:00-close, bossa nova/jazz soul wind-down). "
            "Operational overrides: 'rush_flow' (queue building — steady groove), "
            "'busy_calm' (full room — soft so it stays talkable), "
            "'upbeat_lift' (flat/low-energy room — lift the vibe). "
            "Switch the mood when the room's state clearly calls for a different vibe."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["morning_rush", "midday_dwell", "afternoon_lounge",
                             "rush_flow", "busy_calm", "upbeat_lift"],
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
        # Federated ML model (CaféComfortNet) — loaded if available, silent if not.
        self._fl_model = None
        try:
            from federated.fl_model import CafeComfortNet
            import os as _os
            mp = _os.environ.get("FL_MODEL_PATH", "data/fl_model.json")
            m = CafeComfortNet(seed=42)
            from pathlib import Path as _Path
            if _Path(mp).exists():
                m.load(mp)
                print(f"[agent] CaféComfortNet loaded from {mp} — FL recommendations active")
            else:
                print("[agent] CaféComfortNet initialised (no saved weights yet — run fl_node to train)")
            self._fl_model = m
        except Exception as exc:
            print(f"[agent] FL model unavailable ({exc})")
        self._forecast_debounce: float = 0.0
        # --- federated learning (Layer 1): this venue is a live node in a café
        # federation. Each round it estimates its own {lull,high,queue} capacity
        # ratios from recent scenes, aggregates them with the network (peers), and
        # patches its own absolute thresholds — privacy-preserving (only ratios
        # leave the venue, never footage). Surfaced as a `tune_policy` action.
        from collections import deque
        self._fed_enabled = os.environ.get("AGENT_FEDERATION", "1") != "0"
        self._fed_capacity = int(os.environ.get("SHOP_CAPACITY", "12"))
        self._fed_round_s = float(os.environ.get("FED_ROUND_S", "20"))
        self._fed_occ: deque = deque(maxlen=FED_HISTORY)
        self._fed_queue: deque = deque(maxlen=FED_HISTORY)
        self._fed_last_sync = 0.0
        self._fed_peers: Optional[list] = None  # lazily-built simulated network
        # Layer 2 wired live: each round also FedAvgs this venue's local music-model
        # fit into the running global weights (policy._MUSIC_MODEL), so federation
        # tunes *which moods play*, not just the occupancy thresholds.
        self._fed_scene_hist: deque = deque(maxlen=FED_HISTORY)
        self._fed_music_synced = False
        self._fed_music_rounds = 0
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

    # --- federated learning (Layer 1) --------------------------------------
    def _simulated_peers(self) -> list:
        """Build the federation's *other* café nodes once (their submitted params).

        Stands in for real peer venues so a single-camera demo still shows genuine
        cross-shop learning: three differently-sized cafés (city bar, office café,
        suburban) each train() their ratios on their own history. In a real
        deployment these `bytes` arrive from the FLock aggregator instead."""
        from federated.flock_model import GoldenCoffeeModel
        venues = [
            dict(capacity=10, occ_mean=0.80, occ_amp=0.15, queue_mean=0.20),
            dict(capacity=20, occ_mean=0.55, occ_amp=0.40, queue_mean=0.15),
            dict(capacity=40, occ_mean=0.35, occ_amp=0.20, queue_mean=0.08),
        ]
        peers = []
        for i, cfg in enumerate(venues):
            m = GoldenCoffeeModel(seed=i * 42, **cfg)
            m.init_dataset("")          # no file → synthetic history
            peers.append(m.train())     # this venue's submitted ratio params (bytes)
        return peers

    def _federation_actions(self, scene: dict, now: float) -> list[dict]:
        """Run one federation round if due: estimate this venue's ratios from recent
        scenes, aggregate with the network, and patch the live policy thresholds.
        Emits a `tune_policy` action only when a threshold actually moves."""
        if not self._fed_enabled:
            return []
        self._fed_occ.append(float(scene.get("occupancy", 0) or 0))
        self._fed_queue.append(float(scene.get("queue_len", 0) or 0))
        self._fed_scene_hist.append({
            "occupancy": scene.get("occupancy", 0), "queue_len": scene.get("queue_len", 0),
            "staff_productivity": scene.get("staff_productivity", 0.0), "ts": scene.get("ts"),
        })
        if now - self._fed_last_sync < self._fed_round_s or len(self._fed_occ) < FED_MIN_SCENES:
            return []
        self._fed_last_sync = now

        from federated.node import estimate_ratios, patch_policy
        from federated.flock_model import (
            GoldenCoffeeModel, serialize_params, deserialize_params,
        )
        cap = self._fed_capacity
        local = estimate_ratios(list(self._fed_occ), list(self._fed_queue), cap)
        local_params = serialize_params(
            local["lull_ratio"], local["high_ratio"], local["queue_ratio"], len(self._fed_occ))
        if self._fed_peers is None:
            self._fed_peers = self._simulated_peers()

        g = deserialize_params(GoldenCoffeeModel().aggregate([local_params, *self._fed_peers]))
        old = (policy.LULL_OCCUPANCY, policy.HIGH_OCCUPANCY, policy.HIGH_QUEUE)
        patch_policy(g["lull_ratio"], g["high_ratio"], g["queue_ratio"], cap)
        new = (policy.LULL_OCCUPANCY, policy.HIGH_OCCUPANCY, policy.HIGH_QUEUE)

        # Layer 2: also FedAvg this venue's music-model fit into the live weights.
        music_first = self._federate_music()

        if new == old and not music_first:
            return []  # network agreed with us, music already federated — nothing new
        n_nodes = 1 + len(self._fed_peers)
        bits = []
        if new != old:
            bits.append(f"busy threshold {old[1]}→{new[1]}, lull {old[0]}→{new[0]}, queue {old[2]}→{new[2]}")
        if music_first:
            bits.append("music model now uses federated weights (which moods play)")
        return [{
            "type": "action", "ts": now, "action": "tune_policy",
            "params": {
                "lull": new[0], "high": new[1], "queue": new[2], "n_nodes": n_nodes,
                "lull_ratio": round(g["lull_ratio"], 3), "high_ratio": round(g["high_ratio"], 3),
                "queue_ratio": round(g["queue_ratio"], 3),
                "music_synced": self._fed_music_synced, "music_rounds": self._fed_music_rounds,
            },
            "rationale": (
                f"Network learning ({n_nodes} cafés): " + "; ".join(bits) +
                ". Only ratios + model weights were shared — no footage ever leaves a venue."),
            "reversible": True, "auto": True,
        }]

    def _federate_music(self) -> bool:
        """FedAvg this venue's local music-model fit into the running global weights.

        Trains the softmax on the venue's recent scene history (small/fast), then
        averages it — weighted by scene counts — with the current global weights via
        the Layer-2 `MusicFlockModel.aggregate`, and patches `policy._MUSIC_MODEL`
        in place. So the federation round also tunes *what music plays*, not just
        the occupancy thresholds. Returns True only on the FIRST sync (for the feed).
        """
        try:
            import agent.music_model as mm
            from federated.music_flock_model import (
                MusicFlockModel, serialize_weights, deserialize_weights,
            )
            data = [(mm.features(s), mm._oracle(s)) for s in self._fed_scene_hist]
            if len(data) < FED_MIN_SCENES:
                return False
            local_w = mm.fit(data, epochs=80)
            # Treat the current global as a heavily-weighted prior so a single venue
            # nudges — not hijacks — the shared model (real FedAvg by scene count).
            global_params = serialize_weights(policy._MUSIC_MODEL.weights, n_scenes=2000)
            local_params = serialize_weights(local_w, n_scenes=len(data))
            new_global = deserialize_weights(
                MusicFlockModel().aggregate([global_params, local_params]))["weights"]
            policy._MUSIC_MODEL.weights = {k: list(v) for k, v in new_global.items()}
            self._fed_music_rounds += 1
            first = not self._fed_music_synced
            self._fed_music_synced = True
            return first
        except Exception as exc:
            print(f"[agent] music federation skipped: {exc}")
            return False

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
        actions += self._federation_actions(scene, now)
        actions += self._fl_actions(scene, now)
        return actions

    def _fl_actions(self, scene: dict, now: float) -> list[dict]:
        """CaféComfortNet recommendations — the federally-trained ML layer.

        Runs the local model on the current scene. Only fires if confidence
        exceeds 0.65 AND the same action isn't already being triggered by the
        rule engine (avoids duplicates). Debounced per-action via the same
        policy state windows so the ML layer can't thrash devices.
        """
        if self._fl_model is None:
            return []
        try:
            capacity = int(os.environ.get("SHOP_CAPACITY", "20"))
            recs = self._fl_model.recommend_actions(scene, capacity, threshold=0.65)
            out = []
            debounce_map = {
                "set_music_volume": "music",
                "set_temperature":  "temperature",
                "push_discount":    "discount_quiet",
                "notify_staff":     "notify_queue",
            }
            for r in recs:
                key = debounce_map.get(r["action"], r["action"])
                if not policy._due(self.state, key, now):
                    continue
                policy._mark(self.state, key, now)
                out.append({
                    "type": "action", "ts": now,
                    "action": r["action"],
                    "params": r["params"],
                    "rationale": r["rationale"] + " [CaféComfortNet · federated]",
                    "reversible": True, "auto": True,
                })
            return out
        except Exception as exc:
            print(f"[agent] FL inference failed ({exc})")
            return []

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
                        if data.get("type") == "music_mode":
                            mode = data.get("mode", "auto")
                            agent.state["music_mode"] = mode
                            if mode == "custom":
                                agent.state.pop("music_mood", None)
                            print(f"[agent] music mode → {mode}")
                        elif data.get("type") == "scene":
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
