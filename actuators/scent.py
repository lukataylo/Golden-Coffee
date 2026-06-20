"""Scent diffuser control for comfort/ambiance.

Smart diffusers rarely have a clean public API, so this driver supports the
setups that actually work at a hackathon, in priority order:

  1. Xiaomi/Mijia  — a Mijia scent diffuser driven locally over miIO. Configure
     XIAOMI_DIFFUSER_IP / _TOKEN (see actuators/xiaomi.py).
  2. HTTP webhook  — SCENT_WEBHOOK_URL: we POST {"intensity":N,"scent":"..."} to it.
     Works with Home Assistant webhooks, a Shelly/ESP relay, IFTTT, etc.
  3. Broadlink IR  — reuse the same RM4 blaster as the AC: learn the diffuser's
     remote codes (on/off/boost) and replay. Set SCENT_IR_ON / SCENT_IR_OFF (hex),
     learn via `python -m actuators.infrared --learn` style capture.

Env: XIAOMI_DIFFUSER_IP/_TOKEN  OR  SCENT_WEBHOOK_URL  OR  SCENT_IR_ON / SCENT_IR_OFF
Degrades gracefully (prints intent) when nothing is configured.
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SCENT_WEBHOOK_URL = os.environ.get("SCENT_WEBHOOK_URL", "")
SCENT_IR_ON = os.environ.get("SCENT_IR_ON", "")
SCENT_IR_OFF = os.environ.get("SCENT_IR_OFF", "")


def set_scent(intensity: int, scent: str = "fresh") -> bool:
    """Set diffuser intensity (0-100) and scent name. >0 turns it on.

    Backends in priority order: Xiaomi/Mijia diffuser (local miIO) -> HTTP webhook
    -> Broadlink IR."""
    intensity = max(0, min(100, int(intensity)))

    # Xiaomi/Mijia diffuser first (local miIO) — see actuators/xiaomi.py.
    from actuators import xiaomi

    if xiaomi.diffuser_configured():
        return xiaomi.diffuser_set(intensity, scent)

    if SCENT_WEBHOOK_URL:
        try:
            import requests

            requests.post(SCENT_WEBHOOK_URL, json={"intensity": intensity, "scent": scent}, timeout=3)
            print(f"[scent] webhook -> intensity {intensity}% ({scent})")
            return True
        except Exception as exc:
            print(f"[scent] webhook failed: {exc}")
            return False

    if SCENT_IR_ON or SCENT_IR_OFF:
        code = SCENT_IR_ON if intensity > 0 else SCENT_IR_OFF
        if not code:
            print(f"[scent] (no IR code for {'on' if intensity > 0 else 'off'})")
            return False
        try:
            from actuators.infrared import _send

            _send(code)
            print(f"[scent] IR {'on' if intensity > 0 else 'off'} ({scent})")
            return True
        except Exception as exc:
            print(f"[scent] IR failed: {exc}")
            return False

    print(f"[scent] (not configured) would set intensity {intensity}% ({scent})")
    return False


if __name__ == "__main__":
    inten = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    name = sys.argv[2] if len(sys.argv) > 2 else "fresh citrus"
    set_scent(inten, name)
