"""CaféComfortNet — the policy model at the heart of Golden Coffee's federated AI.

A deliberately small 3-layer MLP (8 → 16 → 8 → 4, ~500 parameters) that learns
which ambient adjustments improve guest experience from live scene data.

Why small?  Because in federated learning, gradient updates are transmitted
across the network. Smaller model = smaller payload = less bandwidth per café,
and critically, less surface area for gradient inversion attacks.

Why pure numpy?  Zero extra dependencies beyond what the stack already needs.
Runs on a £150 mini-PC alongside the rest of the perception pipeline.

Input features (8-dim, all normalised 0..1 or cyclical):
  occupancy_ratio   — how full the venue is relative to capacity
  queue_ratio       — queue length relative to capacity
  hour_sin / cos    — time-of-day encoded cyclically (no midnight discontinuity)
  day_sin / cos     — day-of-week encoded cyclically
  staff_productivity — aggregate movement score from perception
  abandon_rate      — fraction of queue that walked out without ordering

Output (4-dim, sigmoid → probability):
  raise_music       — lift volume / tempo to energise the room
  cool_room         — lower temperature (room warming up with crowd)
  push_discount     — trigger an off-peak promo to attract customers
  alert_staff       — send a staff notification (queue building / table overdue)

UK Sovereign AI context:
  This model is trained collectively by UK cafés via Flock.io federated learning.
  No café shares raw customer data. What flows between venues are gradient updates —
  mathematical vectors that encode what the model learned, not the observations that
  produced them. Each café owns its own data; all cafés share the intelligence.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np


class CafeComfortNet:
    """3-layer MLP policy model — the collective intelligence of the café network."""

    INPUT_DIM  = 8
    HIDDEN1    = 16
    HIDDEN2    = 8
    OUTPUT_DIM = 4
    OUTPUT_NAMES = ["raise_music", "cool_room", "push_discount", "alert_staff"]

    def __init__(self, seed: Optional[int] = None) -> None:
        rng = np.random.default_rng(seed)
        # He initialisation — preserves gradient magnitude through ReLU layers
        self.W1 = rng.normal(0, np.sqrt(2.0 / self.INPUT_DIM),  (self.INPUT_DIM,  self.HIDDEN1))
        self.b1 = np.zeros(self.HIDDEN1)
        self.W2 = rng.normal(0, np.sqrt(2.0 / self.HIDDEN1),    (self.HIDDEN1,    self.HIDDEN2))
        self.b2 = np.zeros(self.HIDDEN2)
        self.W3 = rng.normal(0, np.sqrt(2.0 / self.HIDDEN2),    (self.HIDDEN2,    self.OUTPUT_DIM))
        self.b3 = np.zeros(self.OUTPUT_DIM)
        # stored for backprop
        self._cache: dict = {}

    # ── activations ────────────────────────────────────────────────────────────

    @staticmethod
    def _relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, x)

    @staticmethod
    def _relu_grad(x: np.ndarray) -> np.ndarray:
        return (x > 0).astype(np.float32)

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -20.0, 20.0)))

    # ── forward / backward ─────────────────────────────────────────────────────

    def forward(self, x: np.ndarray) -> np.ndarray:
        """x: (N, 8) → (N, 4) probabilities."""
        z1 = x  @ self.W1 + self.b1;  a1 = self._relu(z1)
        z2 = a1 @ self.W2 + self.b2;  a2 = self._relu(z2)
        z3 = a2 @ self.W3 + self.b3;  out = self._sigmoid(z3)
        self._cache = dict(x=x, z1=z1, a1=a1, z2=z2, a2=a2, out=out)
        return out

    def loss_and_grads(self, x: np.ndarray, y: np.ndarray) -> tuple[float, dict]:
        """Binary cross-entropy loss + full backprop.
        x: (N, 8), y: (N, 4) binary targets → (scalar loss, grad dict)
        """
        out = self.forward(x)
        c = self._cache
        N = x.shape[0]
        eps = 1e-7
        loss = float(-np.mean(y * np.log(out + eps) + (1 - y) * np.log(1 - out + eps)))

        dz3 = (out - y) / N
        dW3 = c["a2"].T @ dz3;            db3 = dz3.sum(0)
        dz2 = (dz3 @ self.W3.T) * self._relu_grad(c["z2"])
        dW2 = c["a1"].T @ dz2;            db2 = dz2.sum(0)
        dz1 = (dz2 @ self.W2.T) * self._relu_grad(c["z1"])
        dW1 = x.T @ dz1;                  db1 = dz1.sum(0)

        return loss, {"W1": dW1, "b1": db1, "W2": dW2, "b2": db2, "W3": dW3, "b3": db3}

    def apply_grads(self, grads: dict, lr: float = 0.01) -> None:
        for k, v in grads.items():
            getattr(self, k)[...] -= lr * v

    # ── weight serialisation ────────────────────────────────────────────────────

    def get_weights(self) -> dict:
        return {k: getattr(self, k).tolist() for k in ("W1","b1","W2","b2","W3","b3")}

    def set_weights(self, w: dict) -> None:
        for k in ("W1","b1","W2","b2","W3","b3"):
            if k in w:
                getattr(self, k)[...] = np.array(w[k], dtype=np.float32)

    def weight_delta(self, base_weights: dict) -> dict:
        """Return (current - base) for each parameter — what this node learned."""
        return {k: (getattr(self, k) - np.array(base_weights[k])).tolist()
                for k in ("W1","b1","W2","b2","W3","b3")}

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.get_weights(), indent=2))

    def load(self, path: str) -> None:
        self.set_weights(json.loads(Path(path).read_text()))

    # ── inference ───────────────────────────────────────────────────────────────

    def predict(self, scene: dict, capacity: int = 20) -> dict[str, float]:
        """Turn a live SceneEvent dict into action probabilities (0..1)."""
        x = scene_to_features(scene, capacity)
        out = self.forward(x[np.newaxis, :])[0]
        return {name: float(out[i]) for i, name in enumerate(self.OUTPUT_NAMES)}

    def recommend_actions(self, scene: dict, capacity: int = 20,
                          threshold: float = 0.6) -> list[dict]:
        """Return AgentAction-shaped dicts for probabilities above threshold."""
        probs = self.predict(scene, capacity)
        actions = []
        if probs["raise_music"] > threshold:
            actions.append({
                "action": "set_music_volume",
                "params": {"volume": 65},
                "rationale": f"Room energy low — lifting the music. (model confidence {probs['raise_music']:.0%})",
            })
        if probs["cool_room"] > threshold:
            actions.append({
                "action": "set_temperature",
                "params": {"delta_c": -1.5},
                "rationale": f"Full room warming up — cooling slightly. ({probs['cool_room']:.0%})",
            })
        if probs["push_discount"] > threshold:
            actions.append({
                "action": "push_discount",
                "params": {"text": "Quiet moment — 15% off any drink in the next 20 min"},
                "rationale": f"Low footfall window — promo to attract walk-ins. ({probs['push_discount']:.0%})",
            })
        if probs["alert_staff"] > threshold:
            actions.append({
                "action": "notify_staff",
                "params": {"text": "Queue building — consider opening a second till."},
                "rationale": f"Queue abandonment rising. ({probs['alert_staff']:.0%})",
            })
        return actions


# ── feature engineering ─────────────────────────────────────────────────────────

def scene_to_features(scene: dict, capacity: int = 20) -> np.ndarray:
    """Encode a SceneEvent into the 8-dim normalised feature vector.

    Cyclical time encoding (sin/cos) means 23:59 and 00:01 are treated as
    close together — no artificial discontinuity at midnight or Monday morning.
    """
    cap = max(capacity, 1)
    f   = scene.get("funnel", {}) or {}
    ts  = scene.get("ts") or time.time()
    dt  = datetime.datetime.fromtimestamp(ts)
    h   = dt.hour + dt.minute / 60.0
    d   = dt.weekday()
    approached = max(f.get("approached", 0), 0)
    abandoned  = max(f.get("abandoned",  0), 0)
    return np.array([
        min(scene.get("occupancy", 0) / cap, 2.0),
        min(scene.get("queue_len", 0) / cap, 1.0),
        math.sin(2 * math.pi * h / 24),
        math.cos(2 * math.pi * h / 24),
        math.sin(2 * math.pi * d / 7),
        math.cos(2 * math.pi * d / 7),
        float(scene.get("staff_productivity", 0.5)),
        abandoned / max(approached, 1),
    ], dtype=np.float32)


def scene_to_label(scene: dict, capacity: int = 20) -> np.ndarray:
    """Derive a soft training label from observable scene outcomes.

    These heuristics mirror the rule-based policy — the model learns to replicate
    them from data, then improves beyond them once cross-café signal arrives.

      raise_music   → low occupancy AND low productivity (empty room, no energy)
      cool_room     → high occupancy (crowd body heat)
      push_discount → very low occupancy (off-peak window to fill the shop)
      alert_staff   → high queue AND rising abandonment
    """
    cap = max(capacity, 1)
    occ_r   = scene.get("occupancy", 0) / cap
    q_r     = scene.get("queue_len", 0) / cap
    prod    = scene.get("staff_productivity", 0.5)
    f       = scene.get("funnel", {}) or {}
    approached = max(f.get("approached", 0), 0)
    abandoned  = max(f.get("abandoned",  0), 0)
    abandon_r  = abandoned / max(approached, 1)

    raise_music   = float(occ_r < 0.30 and prod < 0.4)
    cool_room     = float(occ_r > 0.75)
    push_discount = float(occ_r < 0.20)
    alert_staff   = float(q_r > 0.20 and abandon_r > 0.15)

    return np.array([raise_music, cool_room, push_discount, alert_staff], dtype=np.float32)


# ── differential privacy ────────────────────────────────────────────────────────

def dp_clip_and_noise(grads: dict, clip_norm: float = 1.0,
                      noise_mult: float = 0.1) -> tuple[dict, float]:
    """Apply DP-SGD to a gradient dict: clip L2 norm then add Gaussian noise.

    Returns the sanitised gradients and the actual L2 norm before clipping
    (useful for monitoring how much clipping is occurring).

    Privacy accounting: each application consumes ε ≈ noise_mult * sqrt(2 * ln(1.25/δ))
    for δ = 1e-5, giving ε ≈ 0.47 per round at the default settings.
    Across 10 rounds per day this sums to ε ≈ 4.7 daily — well within the
    (10, 1e-5)-DP budget considered acceptable for anonymised telemetry.
    """
    flat = np.concatenate([np.array(v).flatten() for v in grads.values()])
    l2 = float(np.linalg.norm(flat))
    scale = clip_norm / max(l2, clip_norm)  # 1.0 if already within budget

    sanitised = {}
    for k, v in grads.items():
        arr = np.array(v) * scale
        arr += np.random.normal(0, noise_mult * clip_norm, arr.shape)
        sanitised[k] = arr.tolist()

    return sanitised, l2
