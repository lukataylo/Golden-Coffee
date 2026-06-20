"""Smart lighting control for comfort/ambiance — Xiaomi/Mijia or Philips Hue.

Comfort autopilot uses this to set a warm, dim, cozy room in a lull and a brighter
neutral room when it's busy/daytime. A Xiaomi/Mijia lamp (local miIO, see
actuators/xiaomi.py) takes priority when configured; otherwise we use Philips Hue
(via `phue`).

Pre-hackathon setup (do once) — Hue:
  1. Find the Hue Bridge IP (router admin, the Hue app, or https://discovery.meethue.com).
     Set HUE_BRIDGE_IP.
  2. Press the round button on the Hue Bridge, then within 30s run
     `python -m actuators.lights 70 warm`  — first run registers this app on the bridge.

Env: HUE_BRIDGE_IP  (optional HUE_GROUP to target one room/group by name)
Degrades gracefully (prints intent) when no bridge is configured/reachable.
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

HUE_BRIDGE_IP = os.environ.get("HUE_BRIDGE_IP", "")
HUE_GROUP = os.environ.get("HUE_GROUP", "")  # empty => all lights

# Hue color temperature is "mired" (153=cool/6500K .. 500=warm/2000K).
WARMTH_MIRED = {"warm": 450, "neutral": 320, "cool": 200}


def set_lighting(brightness: int, warmth: str = "neutral") -> bool:
    """Set brightness (0-100) and warmth (warm|neutral|cool) on the smart lights.

    A Xiaomi/Mijia lamp on the LAN takes priority when configured; otherwise we
    fall through to a Philips Hue bridge."""
    brightness = max(0, min(100, int(brightness)))
    mired = WARMTH_MIRED.get(warmth, 320)

    # Xiaomi/Mijia lamp first (local miIO) — see actuators/xiaomi.py.
    from actuators import xiaomi

    if xiaomi.lamp_configured():
        return xiaomi.lamp_set(brightness, warmth)

    if not HUE_BRIDGE_IP:
        print(f"[lights] (no HUE_BRIDGE_IP) would set brightness {brightness}% / {warmth}")
        return False
    try:
        from phue import Bridge

        b = Bridge(HUE_BRIDGE_IP)
        b.connect()  # uses cached whitelist user after first button-press pairing
        cmd = {"on": brightness > 0, "bri": int(brightness * 254 / 100), "ct": mired, "transitiontime": 20}
        if HUE_GROUP:
            b.set_group(HUE_GROUP, cmd)
        else:
            for light_id in b.get_light_objects("id"):
                b.set_light(light_id, cmd)
        print(f"[lights] brightness {brightness}% / {warmth} (ct={mired})")
        return True
    except Exception as exc:
        print(f"[lights] failed: {exc}")
        return False


if __name__ == "__main__":
    bri = int(sys.argv[1]) if len(sys.argv) > 1 else 70
    warm = sys.argv[2] if len(sys.argv) > 2 else "warm"
    set_lighting(bri, warm)
