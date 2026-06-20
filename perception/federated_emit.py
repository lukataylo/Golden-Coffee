"""Fix 6: privacy-preserving federated contribution from the perception process.

Posts only anonymised aggregate ratios (no tracks, no positions, no bboxes) to
the federation server every FED_ROUND_S seconds. This is the Flock.io bounty
hook: each venue contributes occupancy/queue behaviour patterns without sharing
any individual-level data. The federation server averages these ratios across
nodes and returns global thresholds that the agent uses to tune its policy.

Env:
  FED_SERVER_URL  (default http://127.0.0.1:8001)
  SHOP_CAPACITY   (default 20)
  SHOP_ID         (default hostname)
  FED_ROUND_S     (default 60)
"""
from __future__ import annotations

import os
import socket
import threading
import time
from collections import deque
from typing import Callable

FED_URL = os.environ.get("FED_SERVER_URL", "http://127.0.0.1:8001")
SHOP_CAPACITY = int(os.environ.get("SHOP_CAPACITY", "20"))
SHOP_ID = os.environ.get("SHOP_ID", socket.gethostname())
ROUND_S = float(os.environ.get("FED_ROUND_S", "60"))
_HISTORY = 120


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def start(get_stats: Callable[[], dict]) -> threading.Thread:
    """Launch a daemon thread that syncs aggregate ratios with the federation server.

    get_stats() is called each second and must return a dict with at least
    'occupancy' and 'queue_len' keys (a SceneEvent.model_dump() slice works).
    No individual track data or bboxes are ever included in the payload.
    """
    occ_hist: deque[float] = deque(maxlen=_HISTORY)
    queue_hist: deque[float] = deque(maxlen=_HISTORY)
    last_sync = [time.time()]

    def _loop() -> None:
        try:
            import httpx
        except ImportError:
            print("[fed-emit] httpx not installed — federated emit disabled")
            return

        print(
            f"[fed-emit] node={SHOP_ID} capacity={SHOP_CAPACITY} "
            f"server={FED_URL} round={ROUND_S}s"
        )
        while True:
            time.sleep(1.0)
            try:
                stats = get_stats()
            except Exception:
                continue
            if not stats:
                continue

            occ_hist.append(float(stats.get("occupancy", 0)))
            queue_hist.append(float(stats.get("queue_len", 0)))

            now = time.time()
            if now - last_sync[0] < ROUND_S or len(occ_hist) < 10:
                continue

            cap = max(SHOP_CAPACITY, 1)
            occ_list = list(occ_hist)
            q_list = list(queue_hist)
            payload = {
                "node_id": SHOP_ID,
                "capacity": cap,
                "n_scenes": len(occ_list),
                "ts": now,
                "lull_ratio": round(max(0.05, min(_percentile(occ_list, 20) / cap, 0.50)), 3),
                "high_ratio": round(max(0.50, min(_percentile(occ_list, 80) / cap, 0.98)), 3),
                "queue_ratio": round(max(0.05, min(_percentile(q_list, 80) / cap, 0.50)), 3),
            }
            try:
                r = httpx.post(f"{FED_URL}/update", json=payload, timeout=3.0)
                g = r.json()
                print(
                    f"[fed-emit] synced → global lull={g.get('lull_ratio','?')} "
                    f"high={g.get('high_ratio','?')} nodes={g.get('n_nodes','?')}"
                )
            except Exception as exc:
                print(f"[fed-emit] sync failed: {exc} — keeping current thresholds")
            last_sync[0] = now

    t = threading.Thread(target=_loop, daemon=True, name="fed-emit")
    t.start()
    return t
