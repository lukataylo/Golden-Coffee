"""Mock event generator — the thing that unblocks P2/P3/P4 immediately.

Produces realistic-looking SceneEvents and POSTs them to the backend's /ingest
endpoint on a timer, so the dashboard, agent, and actuators can all be built and
tested BEFORE the real perception pipeline exists. Swap this out for
`perception/run.py` once P1 ships real events — they emit the same SceneEvent shape.

Run:  python -m shared.mock_events
Env:  BACKEND_URL (default http://127.0.0.1:8000)
"""
from __future__ import annotations

import math
import os
import time

import httpx

from shared.schemas import Funnel, Role, SceneEvent, Track, Zone

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
TICK_S = float(os.environ.get("MOCK_TICK_S", "1.0"))

ZONES = [Zone.QUEUE, Zone.COUNTER, Zone.SEATING, Zone.SEATING, Zone.ENTRY]


def _synthetic_scene(t: int) -> SceneEvent:
    """Build one believable scene. Occupancy/activity ebb and flow on a sine wave
    so the agent and dashboard see changing conditions (lulls, rushes)."""
    wave = (math.sin(t / 12.0) + 1) / 2  # 0..1 slow oscillation
    occupancy = int(2 + wave * 8)
    queue_len = int(wave * 4)
    productivity = round(0.4 + 0.5 * (1 - wave), 2)  # busy => higher activity

    tracks: list[Track] = []
    for i in range(occupancy):
        zone = ZONES[i % len(ZONES)]
        role = Role.STAFF if i < 2 else Role.CUSTOMER
        tracks.append(
            Track(
                id=1000 + i,
                role=role,
                zone=zone,
                dwell_s=round((i * 37 + t) % 900, 1),  # some long dwellers => "free rides"
                activity=round(productivity if role == Role.STAFF else 0.1, 2),
                bbox=[0.1 + 0.08 * i, 0.2, 0.18 + 0.08 * i, 0.6],
            )
        )

    funnel = Funnel(
        entered=10 + t // 5,
        approached=8 + t // 6,
        ordered=6 + t // 8,
        seated=5 + t // 9,
        abandoned=t // 20,
    )

    # 8x8 coarse heatmap with a hot spot near the counter.
    grid = [[round(wave * math.exp(-((r - 2) ** 2 + (c - 5) ** 2) / 6), 3) for c in range(8)] for r in range(8)]

    return SceneEvent(
        ts=time.time(),
        tracks=tracks,
        occupancy=occupancy,
        queue_len=queue_len,
        funnel=funnel,
        cups_made=6 + t // 8,
        heatmap_grid=grid,
        staff_productivity=productivity,
        source="mock",
    )


def main() -> None:
    url = f"{BACKEND_URL}/ingest"
    print(f"[mock] POSTing synthetic scenes to {url} every {TICK_S}s — Ctrl-C to stop")
    t = 0
    with httpx.Client(timeout=2.0) as client:
        while True:
            event = _synthetic_scene(t)
            try:
                client.post(url, json=event.model_dump())
            except Exception as exc:  # backend not up yet — keep trying
                print(f"[mock] backend not reachable ({exc}); retrying…")
            t += 1
            time.sleep(TICK_S)


if __name__ == "__main__":
    main()
