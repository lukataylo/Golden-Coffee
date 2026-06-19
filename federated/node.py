"""Federation node — watches the live scene stream, estimates capacity-normalised
policy ratios from recent history, and syncs with the federation server.

After each sync the node converts the global ratios back to ABSOLUTE thresholds
using THIS venue's capacity and patches agent.policy in-process so the running
agent benefits immediately from cross-shop learning.

Why ratios?  A "lull" at a 10-seat espresso bar (2 people = 20%) is very different
from a "lull" at a 40-seat café (2 people = 5%).  Sharing ratios instead of raw
counts means a busy city shop and a quiet suburb shop can teach each other without
the numbers being meaningless across venues.

Run:  python -m federated.node
Env:
  SHOP_CAPACITY   int   total seats in this venue (required — no sensible default)
  SHOP_ID         str   unique name for this shop (default: hostname)
  FED_SERVER_URL  str   http://host:8001 of the federation server
  BACKEND_WS      str   ws://host:8000/ws  of the scene stream
  ROUND_S         int   seconds between federation syncs (default 30)
  HISTORY         int   rolling scene window size (default 120)
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections import deque

import httpx
import websockets

import agent.policy as policy

SHOP_CAPACITY = int(os.environ.get("SHOP_CAPACITY", "20"))
SHOP_ID       = os.environ.get("SHOP_ID", socket.gethostname())
FED_URL       = os.environ.get("FED_SERVER_URL", "http://127.0.0.1:8001")
BACKEND_WS    = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8000/ws")
ROUND_S       = float(os.environ.get("ROUND_S", "30"))
HISTORY       = int(os.environ.get("HISTORY", "120"))


# ---------------------------------------------------------------------------
# Ratio estimation from scene history
# ---------------------------------------------------------------------------

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def estimate_ratios(occ_hist: list[float], queue_hist: list[float], capacity: int) -> dict:
    """Derive lull/high/queue ratios from observed occupancy distributions.

    We use percentiles rather than means because the distribution is skewed:
    - P20 of occupancy  → below this the room feels empty        (lull threshold)
    - P80 of occupancy  → above this the room is packed          (high threshold)
    - P80 of queue_len  → above this the queue is getting long   (queue threshold)

    All values are clamped to sensible ranges so one outlier-heavy venue can't
    corrupt the global average.
    """
    cap = max(capacity, 1)
    lull_ratio  = round(max(0.05, min(_percentile(occ_hist,   20) / cap, 0.50)), 3)
    high_ratio  = round(max(0.50, min(_percentile(occ_hist,   80) / cap, 0.98)), 3)
    queue_ratio = round(max(0.05, min(_percentile(queue_hist, 80) / cap, 0.50)), 3)
    return dict(lull_ratio=lull_ratio, high_ratio=high_ratio, queue_ratio=queue_ratio)


# ---------------------------------------------------------------------------
# Policy patching
# ---------------------------------------------------------------------------

def patch_policy(lull_ratio: float, high_ratio: float, queue_ratio: float,
                 capacity: int) -> None:
    """Convert global ratios → absolute thresholds for THIS venue and apply them."""
    cap = max(capacity, 1)
    old = (policy.LULL_OCCUPANCY, policy.HIGH_OCCUPANCY, policy.HIGH_QUEUE)
    policy.LULL_OCCUPANCY = max(1, int(lull_ratio  * cap))
    policy.HIGH_OCCUPANCY = max(2, int(high_ratio  * cap))
    policy.HIGH_QUEUE     = max(1, int(queue_ratio * cap))
    new = (policy.LULL_OCCUPANCY, policy.HIGH_OCCUPANCY, policy.HIGH_QUEUE)
    print(
        f"[fed] policy patched  "
        f"lull {old[0]}→{new[0]}  "
        f"high {old[1]}→{new[1]}  "
        f"queue {old[2]}→{new[2]}  "
        f"(ratios × capacity {cap})"
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run() -> None:
    occ_hist:   deque[float] = deque(maxlen=HISTORY)
    queue_hist: deque[float] = deque(maxlen=HISTORY)
    last_sync = time.time()

    print(
        f"[fed] node={SHOP_ID}  capacity={SHOP_CAPACITY}  "
        f"server={FED_URL}  ws={BACKEND_WS}  round={ROUND_S}s"
    )

    async for sock in _reconnect(BACKEND_WS):
        try:
            async for raw in sock:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") != "scene":
                    continue

                occ_hist.append(float(msg.get("occupancy", 0)))
                queue_hist.append(float(msg.get("queue_len", 0)))

                now = time.time()
                if now - last_sync >= ROUND_S and len(occ_hist) >= 10:
                    await _sync(occ_hist, queue_hist, now)
                    last_sync = now
        except websockets.ConnectionClosed:
            print("[fed] ws disconnected; reconnecting…")


async def _sync(occ_hist: deque, queue_hist: deque, now: float) -> None:
    ratios = estimate_ratios(list(occ_hist), list(queue_hist), SHOP_CAPACITY)
    payload = dict(
        node_id=SHOP_ID,
        capacity=SHOP_CAPACITY,
        n_scenes=len(occ_hist),
        ts=now,
        **ratios,
    )
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(f"{FED_URL}/update", json=payload)
        g = r.json()
        patch_policy(g["lull_ratio"], g["high_ratio"], g["queue_ratio"], SHOP_CAPACITY)
        print(
            f"[fed] global lull={g['lull_ratio']:.3f} "
            f"high={g['high_ratio']:.3f} "
            f"queue={g['queue_ratio']:.3f} "
            f"({g['n_nodes']} nodes)"
        )
    except Exception as exc:
        print(f"[fed] sync failed: {exc} — keeping current thresholds")


async def _reconnect(url: str):
    while True:
        try:
            async with websockets.connect(url) as sock:
                print("[fed] ws connected")
                yield sock
        except Exception as exc:
            print(f"[fed] ws connect failed ({exc}); retrying in 3s")
            await asyncio.sleep(3)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
