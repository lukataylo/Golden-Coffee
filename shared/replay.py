"""Replay a recorded live session as if the model were running right now.

Reads a recording produced from the hub's WebSocket (data/sample_session.jsonl,
one JSON object per line: {"t": <seconds-since-record-start>, "msg": <raw ws msg>})
and re-plays it against a running backend, preserving the original inter-message
timing. Scene messages are re-stamped with the current time and POSTed to
/ingest (so occupancy / comfort / "£ walked away" keep moving); action messages
are POSTed to /override (so the agent action feed replays too). At end-of-file it
loops back to the start seamlessly, forever.

This is what lets the Railway-deployed demo show a working model "in progress"
with no camera attached. It is a drop-in sibling of shared/mock_events.py, but it
replays REAL recorded model output instead of synthesising it.

Run:  python -m shared.replay
Env:  BACKEND_URL   (default http://127.0.0.1:8000)
      REPLAY_FILE   (default data/sample_session.jsonl)
      REPLAY_SPEED  (default 1.0 — >1 plays faster, <1 slower)
"""
from __future__ import annotations

import json
import os
import time

import httpx

BACKEND_URL  = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
REPLAY_FILE  = os.environ.get("REPLAY_FILE", "data/sample_session.jsonl")
REPLAY_SPEED = float(os.environ.get("REPLAY_SPEED", "1.0") or "1.0")

# Mirror perception/mock_events: when INGEST_TOKEN is set the backend requires it
# as X-Token on /ingest, so include it on every scene POST (empty when unset).
_TOKEN_HEADERS = {"X-Token": os.environ["INGEST_TOKEN"]} if os.environ.get("INGEST_TOKEN") else {}


def _load(path: str) -> list[dict]:
    """Read the recording, keeping only well-formed {t, msg} rows, sorted by t."""
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                t = float(rec["t"])
                msg = rec["msg"]
            except Exception:
                continue  # skip malformed lines, keep going
            if isinstance(msg, dict) and msg.get("type"):
                rows.append({"t": t, "msg": msg})
    rows.sort(key=lambda r: r["t"])
    return rows


def _send(client: httpx.Client, msg: dict) -> None:
    """Re-inject one recorded message so the live dashboard/actuators react."""
    mtype = msg.get("type")
    if mtype == "scene":
        # Re-stamp so the dashboard sees a fresh, advancing clock. Keep the
        # recorded `source` ('perception') — /ingest only accepts mock|perception.
        scene = dict(msg)
        scene["ts"] = time.time()
        client.post(f"{BACKEND_URL}/ingest", json=scene, headers=_TOKEN_HEADERS)
    elif mtype == "action":
        # Preserve action + params; /override re-stamps ts and marks it manual.
        act = {
            "type": "action",
            "ts": time.time(),
            "action": msg.get("action"),
            "params": msg.get("params", {}),
            "rationale": msg.get("rationale", ""),
            "reversible": bool(msg.get("reversible", True)),
        }
        if not act["action"]:
            return
        client.post(f"{BACKEND_URL}/override", json=act)
    # music_mode/geometry and anything else are skipped — the backend owns those.


def main() -> None:
    rows = _load(REPLAY_FILE)
    if not rows:
        print(f"[replay] no usable rows in {REPLAY_FILE}; nothing to replay")
        return
    span = rows[-1]["t"] - rows[0]["t"]
    print(f"[replay] {len(rows)} msgs ({span:.0f}s span) from {REPLAY_FILE} "
          f"-> {BACKEND_URL} at {REPLAY_SPEED}x — looping forever")

    with httpx.Client(timeout=3.0) as client:
        while True:  # loop the recording forever
            prev_t = rows[0]["t"]
            for row in rows:
                delay = (row["t"] - prev_t) / REPLAY_SPEED
                if delay > 0:
                    time.sleep(min(delay, 30.0))  # cap any accidental huge gap
                prev_t = row["t"]
                try:
                    _send(client, row["msg"])
                except Exception as exc:  # backend blip — keep the stream alive
                    print(f"[replay] send failed ({exc}); continuing")
            # Seamless wrap: small beat so we don't double-fire at the seam.
            time.sleep(0.5 / REPLAY_SPEED)


if __name__ == "__main__":
    main()
