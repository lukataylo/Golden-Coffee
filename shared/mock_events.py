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

from shared.schemas import CleaningZone, Funnel, Role, SceneEvent, Table, Track, Zone

BACKEND_URL    = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
TICK_S         = float(os.environ.get("MOCK_TICK_S", "1.0"))
AVG_TICKET_GBP = float(os.environ.get("AVG_TICKET_GBP", "4.80"))

ZONES = [Zone.QUEUE, Zone.COUNTER, Zone.SEATING, Zone.SEATING, Zone.ENTRY]

# Mirror what perception sends: if INGEST_TOKEN is set, the backend requires it
# as X-Token on /ingest, so include it on every POST (empty when unset in dev).
_TOKEN_HEADERS = {"X-Token": os.environ["INGEST_TOKEN"]} if os.environ.get("INGEST_TOKEN") else {}


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

    # Three tables cycling through seated/waiting/overdue + a cleaning flag.
    tables = []
    for k, tid in enumerate(["T1", "T2", "T3"]):
        wait = max(0, ((t * 17 + k * 90) % 420) - 40)  # 0..380s, varies per table
        occupied = wait > 0
        status = (
            "empty" if not occupied
            else "overdue" if wait >= 300
            else "waiting" if wait >= 120
            else "seated"
        )
        tables.append(Table(
            id=tid, occupied=occupied, party_size=(2 if occupied else 0),
            occupied_s=float(wait), wait_s=float(wait), status=status,
            needs_cleaning=(not occupied and (t + k) % 5 == 0),
            since_clean_s=float((t * 11 + k * 50) % 2400), uses_since_clean=(t + k) % 12,
        ))

    # Restroom cleaning cadence ramps with usage.
    uses = (t // 2) % 20
    clean_status = "overdue" if uses >= 15 else "due" if uses >= 8 else "ok"
    cleaning = [CleaningZone(
        id="restroom", uses_since_clean=int(uses),
        since_clean_s=float((t * 30) % 4000), status=clean_status,
    )]

    walkaway_gbp = round(funnel.abandoned * AVG_TICKET_GBP, 2)

    hour = time.localtime().tm_hour

    # Outdoor temp: day curve 10°C dawn → 20°C midday → 14°C evening.
    outdoor_temp_c = round(10.0 + 10.0 * math.sin((hour - 6) * math.pi / 12), 1)

    # Simulated indoor sensors (mock only — replaced by real hardware readings in prod).
    indoor_temp_c = round(21.0 + occupancy * 0.25
                          + (1.0 if 13 <= hour <= 16 else 0.0)
                          + math.sin(t * 0.17) * 0.3, 1)
    indoor_humidity_rh = round(45.0 + 20.0 * wave, 1)           # 45–65 %RH
    indoor_sound_db = round(45.0 + (occupancy / 2) * 2.0
                            + queue_len * 1.5 + math.sin(t * 0.3) * 1.5, 1)
    natural_lux = max(0.0, 350.0 * math.sin((hour - 6) * math.pi / 14))
    indoor_lux = round(natural_lux + 150.0 + math.sin(t * 0.11) * 10.0, 1)

    return SceneEvent(
        ts=time.time(),
        tracks=tracks,
        occupancy=occupancy,
        queue_len=queue_len,
        funnel=funnel,
        cups_made=6 + t // 8,
        heatmap_grid=grid,
        staff_productivity=productivity,
        tables=tables,
        cleaning=cleaning,
        walkaway_gbp=walkaway_gbp,
        outdoor_temp_c=outdoor_temp_c,
        indoor_temp_c=indoor_temp_c,
        indoor_humidity_rh=indoor_humidity_rh,
        indoor_sound_db=indoor_sound_db,
        indoor_lux=indoor_lux,
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
                client.post(url, json=event.model_dump(), headers=_TOKEN_HEADERS)
            except Exception as exc:  # backend not up yet — keep trying
                print(f"[mock] backend not reachable ({exc}); retrying…")
            t += 1
            time.sleep(TICK_S)


if __name__ == "__main__":
    main()
