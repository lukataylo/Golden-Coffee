"""Xiaomi / Mijia smart-home control over the local miIO protocol (python-miio).

Preferred backend for the comfort autopilot's lamp + scent diffuser when you have
Mijia gear on the LAN. Local + token-based, exactly like the Hue and Broadlink
drivers — no cloud round-trip at demo time.

Each device needs its LAN IP and a 32-char hex token. The token is the only hard
part; pull every device's ip + token once with python-miio's cloud helper (uses
your Mi account, read-only):

    miiocli cloud            # prints name / model / ip / token for each device

Then paste them into .env (see keys below).

  * Lamp: most Mijia / Yeelight lamps speak the Yeelight miIO dialect, so we drive
    brightness + colour-temperature directly. White-only lamps just ignore the
    colour-temp call (we swallow that error).
  * Diffuser: newer Xiaomi diffusers are MIoT devices — set on/off (and an optional
    fan/level) by siid/piid. Older ones expose a plain `set_power`, which we fall
    back to when no siid/piid is configured.

Env:
  XIAOMI_LAMP_IP / XIAOMI_LAMP_TOKEN
  XIAOMI_DIFFUSER_IP / XIAOMI_DIFFUSER_TOKEN
  (optional, MIoT diffusers) XIAOMI_DIFFUSER_SIID, XIAOMI_DIFFUSER_PIID_ON,
  XIAOMI_DIFFUSER_PIID_LEVEL, XIAOMI_DIFFUSER_LEVEL_MAX (default 3)

Degrades gracefully (prints intent) when nothing is configured / reachable.
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

XIAOMI_LAMP_IP = os.environ.get("XIAOMI_LAMP_IP", "")
XIAOMI_LAMP_TOKEN = os.environ.get("XIAOMI_LAMP_TOKEN", "")
XIAOMI_DIFFUSER_IP = os.environ.get("XIAOMI_DIFFUSER_IP", "")
XIAOMI_DIFFUSER_TOKEN = os.environ.get("XIAOMI_DIFFUSER_TOKEN", "")

# Yeelight colour-temperature spans ~1700K (warm) .. 6500K (cool).
WARMTH_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6000}


def lamp_configured() -> bool:
    return bool(XIAOMI_LAMP_IP and XIAOMI_LAMP_TOKEN)


def diffuser_configured() -> bool:
    return bool(XIAOMI_DIFFUSER_IP and XIAOMI_DIFFUSER_TOKEN)


def lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    """Set a Mijia/Yeelight lamp's brightness (0-100) and warmth. >0 turns it on."""
    brightness = max(0, min(100, int(brightness)))
    kelvin = WARMTH_KELVIN.get(warmth, 4000)
    try:
        from miio import Yeelight

        dev = Yeelight(XIAOMI_LAMP_IP, XIAOMI_LAMP_TOKEN)
        if brightness <= 0:
            dev.off()
            print("[xiaomi] lamp off")
            return True
        dev.on()
        dev.set_brightness(brightness)
        try:
            dev.set_color_temp(kelvin)  # white-only lamps reject this — that's fine
        except Exception:
            pass
        print(f"[xiaomi] lamp brightness {brightness}% / {warmth} ({kelvin}K)")
        return True
    except Exception as exc:
        print(f"[xiaomi] lamp failed: {exc}")
        return False


def diffuser_set(intensity: int, scent: str = "fresh") -> bool:
    """Drive a Mijia scent diffuser. >0 turns it on; intensity maps to a fan/level
    on MIoT devices that expose one. `scent` is informational (a diffuser can't
    pick a fragrance — that's whatever cartridge is loaded)."""
    intensity = max(0, min(100, int(intensity)))
    on = intensity > 0

    siid = os.environ.get("XIAOMI_DIFFUSER_SIID", "")
    piid_on = os.environ.get("XIAOMI_DIFFUSER_PIID_ON", "")
    piid_level = os.environ.get("XIAOMI_DIFFUSER_PIID_LEVEL", "")
    level_max = int(os.environ.get("XIAOMI_DIFFUSER_LEVEL_MAX", "3"))

    try:
        if siid and piid_on:
            from miio import MiotDevice

            dev = MiotDevice(XIAOMI_DIFFUSER_IP, XIAOMI_DIFFUSER_TOKEN)
            dev.set_property_by(int(siid), int(piid_on), on)
            if on and piid_level:
                # Map 1-100% onto the device's 1..level_max discrete steps.
                level = max(1, min(level_max, round(intensity / 100 * level_max)))
                dev.set_property_by(int(siid), int(piid_level), level)
                print(f"[xiaomi] diffuser on level {level}/{level_max} ({scent})")
            else:
                print(f"[xiaomi] diffuser {'on' if on else 'off'} ({scent})")
            return True

        # Fallback: legacy miIO devices with a plain power switch.
        from miio import Device

        dev = Device(XIAOMI_DIFFUSER_IP, XIAOMI_DIFFUSER_TOKEN)
        dev.send("set_power", ["on" if on else "off"])
        print(f"[xiaomi] diffuser {'on' if on else 'off'} ({scent})")
        return True
    except Exception as exc:
        print(f"[xiaomi] diffuser failed: {exc}")
        return False


def _discover() -> None:
    """List Mijia devices on the LAN (gives IPs + device ids, NOT tokens).
    Run `miiocli cloud` to get the tokens."""
    try:
        from miio import Discovery

        Discovery.discover_mdns()
    except Exception as exc:
        print(f"[xiaomi] discovery failed ({exc}); try `miiocli discover` / `miiocli cloud`")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--discover"
    if arg == "--discover":
        _discover()
    elif arg == "lamp":
        bri = int(sys.argv[2]) if len(sys.argv) > 2 else 70
        warm = sys.argv[3] if len(sys.argv) > 3 else "warm"
        lamp_set(bri, warm)
    elif arg == "diffuser":
        inten = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        name = sys.argv[3] if len(sys.argv) > 3 else "fresh"
        diffuser_set(inten, name)
    else:
        print("usage: python -m actuators.xiaomi [--discover | lamp <bri> <warm> | diffuser <intensity> <scent>]")
