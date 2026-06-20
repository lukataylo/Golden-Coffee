"""Federated learning node — the per-venue intelligence contributor.

Each Golden Coffee venue runs one of these. It:
  1. Listens to the local scene stream (WS /ws) to collect training examples
  2. Every FL_ROUND_S seconds: trains CaféComfortNet locally with DP-SGD
  3. Submits the sanitised gradient delta to Flock.io for global aggregation
  4. Pulls the updated global model back and uses it for live inference

Privacy guarantee: (ε, δ)-DP with configurable budget. Raw video, track
positions, and individual SceneEvents never leave the building. The only
thing transmitted is a noisy gradient vector — a mathematical direction,
not a data record.

UK Sovereign AI narrative:
  A small independent café on any UK high street gets the same quality of
  AI recommendations as a major chain with 500 locations — because it is
  training alongside them, contributing to a collectively-owned model that
  no single company controls. British businesses, British data, British AI.

Run:
  python -m federated.fl_node

Env:
  BACKEND_WS       ws://127.0.0.1:8000/ws
  SHOP_ID          unique venue name (default: hostname)
  SHOP_CAPACITY    total seats (default: 20)
  FLOCK_API_URL    https://api.flock.io/v1  (set for real Flock.io)
  FLOCK_API_KEY    your Flock.io API key
  FLOCK_TASK_ID    federated training task ID
  FED_SERVER_URL   http://127.0.0.1:8001   (local fallback if no Flock key)
  FL_ROUND_S       60    seconds between federation rounds
  FL_HISTORY       300   max training examples to buffer
  FL_LOCAL_EPOCHS  5     local SGD passes per round
  FL_LR            0.01  local learning rate
  FL_CLIP_NORM     1.0   DP gradient clipping threshold
  FL_NOISE_MULT    0.1   DP Gaussian noise multiplier
  FL_MODEL_PATH    data/fl_model.json  where to persist the model
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections import deque
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import websockets

from federated.fl_model import CafeComfortNet, dp_clip_and_noise, scene_to_features, scene_to_label

# ── config ────────────────────────────────────────────────────────────────────
SHOP_ID       = os.environ.get("SHOP_ID", socket.gethostname())
SHOP_CAPACITY = int(os.environ.get("SHOP_CAPACITY", "20"))
BACKEND_WS    = os.environ.get("BACKEND_WS",   "ws://127.0.0.1:8000/ws")
FLOCK_URL     = os.environ.get("FLOCK_API_URL", "https://api.flock.io/v1").rstrip("/")
FLOCK_KEY     = os.environ.get("FLOCK_API_KEY", "")
FLOCK_TASK    = os.environ.get("FLOCK_TASK_ID", "")
LOCAL_FED     = os.environ.get("FED_SERVER_URL", "http://127.0.0.1:8001")
MODEL_PATH    = os.environ.get("FL_MODEL_PATH",  "data/fl_model.json")

ROUND_S       = float(os.environ.get("FL_ROUND_S",        "60"))
HISTORY       = int(os.environ.get("FL_HISTORY",          "300"))
LOCAL_EPOCHS  = int(os.environ.get("FL_LOCAL_EPOCHS",     "5"))
LR            = float(os.environ.get("FL_LR",             "0.01"))
CLIP_NORM     = float(os.environ.get("FL_CLIP_NORM",      "1.0"))
NOISE_MULT    = float(os.environ.get("FL_NOISE_MULT",     "0.1"))


# ── Flock.io client ───────────────────────────────────────────────────────────

class FlockClient:
    """Thin async wrapper around the Flock.io federated training REST API.

    Falls back to the local federation server if FLOCK_API_KEY is not set —
    so development and single-venue demos work without Flock credentials.
    """

    def __init__(self) -> None:
        self.use_flock = bool(FLOCK_KEY and FLOCK_TASK)
        self._round = 0
        if self.use_flock:
            print(f"[fl-node] Flock.io enabled — task={FLOCK_TASK}")
        else:
            print(f"[fl-node] Flock.io not configured — using local federation server ({LOCAL_FED})")

    async def get_global_model(self) -> Optional[dict]:
        """Pull the current global model weights from Flock.io (or local server)."""
        if self.use_flock:
            return await self._flock_get_model()
        return await self._local_get_model()

    async def submit_update(self, delta: dict, n_samples: int,
                            loss: float, epsilon_spent: float) -> dict:
        """Submit a DP-sanitised weight delta; returns the new global model."""
        if self.use_flock:
            return await self._flock_submit(delta, n_samples, loss, epsilon_spent)
        return await self._local_submit(delta, n_samples, loss)

    # ── Flock.io paths ────────────────────────────────────────────────────────

    async def _flock_get_model(self) -> Optional[dict]:
        headers = {"Authorization": f"Bearer {FLOCK_KEY}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{FLOCK_URL}/tasks/{FLOCK_TASK}/model",
                    headers=headers,
                )
                if r.status_code == 200:
                    data = r.json()
                    self._round = data.get("round", self._round)
                    return data.get("weights") or data.get("model_weights")
        except Exception as exc:
            print(f"[fl-node] Flock.io get_model failed ({exc})")
        return None

    async def _flock_submit(self, delta: dict, n_samples: int,
                            loss: float, epsilon_spent: float) -> dict:
        headers = {"Authorization": f"Bearer {FLOCK_KEY}", "Content-Type": "application/json"}
        payload = {
            "trainer_id":    SHOP_ID,
            "round":         self._round,
            "weight_delta":  delta,
            "n_samples":     n_samples,
            "metrics":       {"loss": round(loss, 4), "epsilon_spent": round(epsilon_spent, 3)},
            "privacy": {
                "mechanism":      "DP-SGD",
                "clip_norm":      CLIP_NORM,
                "noise_mult":     NOISE_MULT,
                "epsilon_round":  epsilon_spent,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    f"{FLOCK_URL}/tasks/{FLOCK_TASK}/rounds/{self._round}/submit",
                    headers=headers,
                    json=payload,
                )
                if r.status_code in (200, 201):
                    data = r.json()
                    self._round = data.get("round", self._round + 1)
                    weights = data.get("global_weights") or data.get("model_weights")
                    if weights:
                        return weights
        except Exception as exc:
            print(f"[fl-node] Flock.io submit failed ({exc})")
        return {}

    # ── local federation server paths ─────────────────────────────────────────

    async def _local_get_model(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{LOCAL_FED}/fl/model")
                if r.status_code == 200:
                    return r.json().get("weights")
        except Exception:
            pass
        return None

    async def _local_submit(self, delta: dict, n_samples: int, loss: float) -> dict:
        payload = {
            "node_id":   SHOP_ID,
            "capacity":  SHOP_CAPACITY,
            "n_samples": n_samples,
            "loss":      round(loss, 4),
            "delta":     delta,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{LOCAL_FED}/fl/update", json=payload)
                if r.status_code == 200:
                    return r.json().get("weights", {})
        except Exception as exc:
            print(f"[fl-node] local submit failed ({exc})")
        return {}


# ── training loop ─────────────────────────────────────────────────────────────

class FLNode:
    """One venue's federated learning participant.

    Collects scene observations, trains locally, contributes to the global model.
    """

    def __init__(self) -> None:
        self.model = CafeComfortNet(seed=42)
        self.client = FlockClient()
        self._buffer: deque[tuple[np.ndarray, np.ndarray]] = deque(maxlen=HISTORY)
        self._last_round = time.time()
        self._round_num = 0
        self._total_eps = 0.0  # cumulative DP budget consumed

        # Load persisted model if available
        mp = Path(MODEL_PATH)
        if mp.exists():
            try:
                self.model.load(str(mp))
                print(f"[fl-node] loaded model from {MODEL_PATH}")
            except Exception as exc:
                print(f"[fl-node] could not load model ({exc}) — starting fresh")

    def ingest_scene(self, scene: dict) -> None:
        """Add a scene observation to the local training buffer."""
        x = scene_to_features(scene, SHOP_CAPACITY)
        y = scene_to_label(scene, SHOP_CAPACITY)
        self._buffer.append((x, y))

    def ingest_override(self, action_name: str, scene: dict) -> None:
        """Staff override = strong training signal.

        When a human overrides the AI's suggestion, we treat the override action
        as the correct label for this scene — a direct imitation learning example.
        This is the highest-quality signal: a domain expert saying 'no, do this instead'.
        """
        x = scene_to_features(scene, SHOP_CAPACITY)
        y = scene_to_label(scene, SHOP_CAPACITY).copy()
        # Amplify the overridden output channel — it's demonstrably what was needed
        action_map = {
            "set_music_volume": 0, "set_temperature": 1,
            "push_discount": 2,    "notify_staff": 3,
        }
        if action_name in action_map:
            y[action_map[action_name]] = 1.0
        self._buffer.append((x, y))

    def _train_local(self) -> tuple[float, dict]:
        """Run LOCAL_EPOCHS of SGD on the buffered examples. Returns (loss, grads)."""
        if len(self._buffer) < 8:
            return 0.0, {}

        xs = np.stack([x for x, _ in self._buffer])
        ys = np.stack([y for _, y in self._buffer])

        # Mini-batch SGD
        idx = np.arange(len(xs))
        np.random.shuffle(idx)
        batch = idx[:min(len(idx), 64)]
        xb, yb = xs[batch], ys[batch]

        total_loss = 0.0
        last_grads: dict = {}
        for _ in range(LOCAL_EPOCHS):
            loss, grads = self.model.loss_and_grads(xb, yb)
            total_loss += loss
            self.model.apply_grads(grads, lr=LR)
            last_grads = grads

        return total_loss / LOCAL_EPOCHS, last_grads

    async def run_round(self) -> None:
        """One federation round: train → DP-sanitise → submit → update."""
        n = len(self._buffer)
        if n < 8:
            print(f"[fl-node] round {self._round_num}: only {n} examples — skipping")
            return

        # Snapshot weights before local training (we send the delta, not the full weights)
        base_weights = self.model.get_weights()

        # Pull latest global model first
        global_w = await self.client.get_global_model()
        if global_w:
            self.model.set_weights(global_w)
            base_weights = global_w
            print(f"[fl-node] pulled global model (round {self._round_num})")

        # Local training
        loss, _ = self._train_local()

        # Compute weight delta (what this venue learned this round)
        delta = self.model.weight_delta(base_weights)

        # DP-SGD: clip L2 norm + add Gaussian noise
        safe_delta, l2_before = dp_clip_and_noise(delta, CLIP_NORM, NOISE_MULT)

        # Privacy budget accounting (approximate, Gaussian mechanism)
        import math as _math
        eps_round = NOISE_MULT * _math.sqrt(2 * _math.log(1.25 / 1e-5))
        self._total_eps += eps_round

        print(
            f"[fl-node] round {self._round_num}  n={n}  loss={loss:.4f}  "
            f"grad_l2={l2_before:.3f}→clipped  ε_round={eps_round:.2f}  "
            f"ε_total={self._total_eps:.2f}  "
            f"{'→ Flock.io' if self.client.use_flock else '→ local server'}"
        )

        # Submit to Flock.io (or local server)
        new_weights = await self.client.submit_update(safe_delta, n, loss, eps_round)
        if new_weights:
            self.model.set_weights(new_weights)
            print(f"[fl-node] global model applied")

        # Persist locally
        mp = Path(MODEL_PATH)
        mp.parent.mkdir(exist_ok=True)
        self.model.save(str(mp))

        self._round_num += 1


# ── WebSocket listener ────────────────────────────────────────────────────────

async def run() -> None:
    node = FLNode()
    last_round = time.time()

    print(
        f"[fl-node] venue={SHOP_ID}  capacity={SHOP_CAPACITY}  "
        f"ws={BACKEND_WS}  round_every={ROUND_S}s"
    )

    async for sock in _reconnect(BACKEND_WS):
        try:
            async for raw in sock:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") == "scene":
                    node.ingest_scene(msg)

                elif msg.get("type") == "action" and not msg.get("auto", True):
                    # Human override → strongest training signal
                    node.ingest_override(msg.get("action", ""), msg)

                now = time.time()
                if now - last_round >= ROUND_S:
                    await node.run_round()
                    last_round = now

        except websockets.ConnectionClosed:
            print("[fl-node] ws disconnected; reconnecting…")


async def _reconnect(url: str):
    while True:
        try:
            async with websockets.connect(url) as sock:
                print("[fl-node] ws connected")
                yield sock
        except Exception as exc:
            print(f"[fl-node] connect failed ({exc}); retry in 5s")
            await asyncio.sleep(5)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
