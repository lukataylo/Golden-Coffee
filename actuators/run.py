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

from actuators import discount, infrared, lights, notify, scent, spotify

BACKEND_WS = os.environ.get("BACKEND_WS", "ws://127.0.0.1:8000/ws")

# Strong refs to in-flight dispatch tasks so they aren't garbage-collected
# before completion (which would silently drop an action under load).
_pending: set[asyncio.Task] = set()


def dispatch(action: dict) -> None:
    """Route one AgentAction to the right device."""
    name = action.get("action")
    p = action.get("params", {})
    tag = "manual" if action.get("auto") is False else "auto"
    print(f"[actuators] ({tag}) {name} {p}")
    try:
        if name == "set_music_volume":
            spotify.set_volume(int(p.get("volume", 50)))
        elif name == "set_music":
            vol = p.get("volume")
            spotify.set_music(
                playlist_uri=str(p.get("playlist_uri", "")),
                descriptors=str(p.get("descriptors", "")),
                volume=int(vol) if vol is not None else None,
                mood=str(p.get("mood", "")),
            )
        elif name == "set_temperature":
            tc = p.get("target_c")
            infrared.set_temperature(
                target_c=float(tc) if tc is not None else None,
                delta_c=float(p["delta_c"]) if p.get("delta_c") is not None else None,
            )
        elif name == "set_lighting":
            lights.set_lighting(int(p.get("brightness", 70)), str(p.get("warmth", "neutral")))
        elif name == "set_scent":
            scent.set_scent(int(p.get("intensity", 50)), str(p.get("scent", "fresh")))
        elif name == "push_discount":
            discount.push_discount(p.get("text", ""))
        elif name == "notify_staff":
            channel = p.get("channel", "default")
            text = p.get("text", "")
            priority = p.get("priority", "low")
            # Channel routing: wearables / pos_and_wearables get a prefix so
            # the recipient knows which device should receive it.
            if channel == "wearables":
                text = f"[WEARABLE] {text}"
            elif channel == "pos_and_wearables":
                text = f"[POS + WEARABLE] {text}"
            print(f"[actuators] notify → ch={channel} priority={priority}: {text}")
            notify.notify_staff(text)
        elif name == "update_menu_price":
            item = p.get("item_id", "?")
            new_p = p.get("display_price", "?")
            base_p = p.get("base_price", "?")
            pct = p.get("discount_pct", "?")
            print(
                f"[actuators] menu board: {item} £{base_p} → £{new_p} "
                f"({pct}% off) [never_surge={p.get('never_surge', True)}]"
            )
            notify.notify_staff(
                f"Menu updated: {item} now £{new_p} ({pct}% quiet-period discount)"
            )
        elif name == "suggest_layout":
            print(f"[actuators] layout suggestion: {p.get('text', '')}")
        elif name == "tune_policy":
            print(f"[actuators] policy tuned by federation: lull={p.get('lull')} "
                  f"high={p.get('high')} queue={p.get('queue')} ({p.get('n_nodes')} cafés)")
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
                    # Skip actions replayed by the backend on (re)connect so a
                    # reconnect can't re-fire devices; only dispatch live ones.
                    if msg.get("replayed"):
                        print("[actuators] skipping replayed action")
                        continue
                    # Actuators are blocking I/O (spotipy, broadlink, requests);
                    # run off the event loop so a slow device can't stall reception.
                    task = asyncio.create_task(asyncio.to_thread(dispatch, msg))
                    _pending.add(task)
                    task.add_done_callback(_pending.discard)
        except websockets.ConnectionClosed:
            print("[actuators] disconnected; reconnecting…")
        except Exception as e:
            # Any other error during reception must NOT kill the executor;
            # log and fall through to reconnect with the usual backoff.
            print(f"[actuators] receive loop error ({e!r}); reconnecting…")


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
