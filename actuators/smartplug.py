"""Smart-plug control (fan/heater) via python-kasa — the visible/audible 'temperature' action.

Pre-hackathon: buy a TP-Link Kasa plug (EP10/KP115/HS103), put it on the same LAN,
discover its IP with `kasa discover`, set KASA_PLUG_IP. Newer firmware also needs
your TP-Link cloud user/pass (KASA_USER / KASA_PASS).

We map "cool the room" -> turn the fan ON, "warm" -> turn it OFF. Simple and demo-friendly.
"""
from __future__ import annotations

import asyncio
import os

KASA_PLUG_IP = os.environ.get("KASA_PLUG_IP", "")
KASA_USER = os.environ.get("KASA_USER", "")
KASA_PASS = os.environ.get("KASA_PASS", "")


async def _set_plug(on: bool) -> bool:
    if not KASA_PLUG_IP:
        print(f"[plug] (no KASA_PLUG_IP) would turn {'ON' if on else 'OFF'}")
        return False
    try:
        from kasa import Discover

        kwargs = {}
        if KASA_USER and KASA_PASS:
            kwargs = {"username": KASA_USER, "password": KASA_PASS}
        dev = await Discover.discover_single(KASA_PLUG_IP, **kwargs)
        await (dev.turn_on() if on else dev.turn_off())
        await dev.update()
        print(f"[plug] {'ON' if on else 'OFF'}")
        return True
    except Exception as exc:
        print(f"[plug] failed: {exc}")
        return False


def set_temperature(delta_c: float) -> bool:
    """Negative delta = cooler => fan ON. Positive => fan OFF."""
    return asyncio.run(_set_plug(on=delta_c < 0))


if __name__ == "__main__":
    set_temperature(-2)
