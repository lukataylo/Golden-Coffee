"""Actuator executor — subscribes to the backend WS and drives REAL devices.

This is the last link in the loop: perception -> agent -> /action -> [this] -> devices.
It runs on the machine that has LAN/credentials for the devices (the demo laptop),
NOT on Railway. The agent POSTs decisions to the backend; this process receives them
over the websocket and calls the matching actuator. Every actuator degrades
gracefully when its keys/hardware are absent, so this is safe to run unconfigured.

Run:  python -m actuators.run
Env:  BACKEND_WS (default ws://127.0.0.1:8000/ws), plus per-actuator keys (.env)
"""
from __future__ import annotations

import asyncio
import json
import os

import websockets

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from actuators import discount, infrared, notify, spotify

BACKEND_WS = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8000/ws")


def dispatch(action: dict) -> None:
    """Route one AgentAction to the right device."""
    name = action.get("action")
    p = action.get("params", {})
    tag = "manual" if action.get("auto") is False else "auto"
    print(f"[actuators] ({tag}) {name} {p}")
    try:
        if name == "set_music_volume":
            spotify.set_volume(int(p.get("volume", 50)))
        elif name == "set_temperature":
            infrared.set_temperature(float(p.get("delta_c", 0)))
        elif name == "push_discount":
            discount.push_discount(p.get("text", ""))
        elif name == "notify_staff":
            notify.notify_staff(p.get("text", ""))
        elif name == "suggest_layout":
            print(f"[actuators] layout suggestion: {p.get('text', '')}")
        else:
            print(f"[actuators] no handler for {name!r}")
    except Exception as exc:
        print(f"[actuators] {name} failed: {exc}")


async def main() -> None:
    print(f"[actuators] connecting to {BACKEND_WS}")
    async for sock in _reconnect(BACKEND_WS):
        try:
            async for raw in sock:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") == "action":
                    # Actuators are blocking I/O (spotipy, broadlink, requests);
                    # run off the event loop so a slow device can't stall reception.
                    asyncio.create_task(asyncio.to_thread(dispatch, msg))
        except websockets.ConnectionClosed:
            print("[actuators] disconnected; reconnecting…")


async def _reconnect(url):
    """Yield a fresh connection, retrying forever with a short backoff."""
    while True:
        try:
            async with websockets.connect(url) as sock:
                print("[actuators] connected")
                yield sock
        except Exception as exc:
            print(f"[actuators] connect failed ({exc}); retrying in 3s")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
