"""Xiaomi / Mijia smart-home control over the local miIO protocol (python-miio).

Preferred backend for the comfort autopilot's lamp + scent diffuser when you have
Mijia gear on the LAN. Local + token-based, exactly like the Hue and Broadlink
drivers — no cloud round-trip at demo time.

Each device needs its LAN IP and a 32-char hex token. The token is the only hard
part; pull every device's ip + token once from the cloud (read-only). Set your
Mi account region first — devices added in mainland China live on the "cn" server
(XIAOMI_REGION, default "cn"):

    python -m actuators.xiaomi --cloud           # uses XIAOMI_MI_USER / _PASS
    # or:  miiocli cloud --server cn

Then paste each device's ip + token into .env (see keys below).

  * Lamp: most Mijia / Yeelight lamps speak the Yeelight miIO dialect, so we drive
    brightness + colour-temperature directly. White-only lamps just ignore the
    colour-temp call (we swallow that error).
  * Diffuser: newer Xiaomi diffusers are MIoT devices — set on/off (and an optional
    fan/level) by siid/piid. Older ones expose a plain `set_power`, which we fall
    back to when no siid/piid is configured.

Transport (XIAOMI_TRANSPORT): "local" speaks miIO on the LAN; "cloud" routes
commands through the Mi cloud (use this when the gear is in China and this machine
is elsewhere — see actuators/xiaomi_cloud.py); "auto" (default) uses local when
it's configured, else cloud.

Env (local):
  XIAOMI_LAMP_IP / XIAOMI_LAMP_TOKEN
  XIAOMI_DIFFUSER_IP / XIAOMI_DIFFUSER_TOKEN
  (optional, MIoT diffusers) XIAOMI_DIFFUSER_SIID, XIAOMI_DIFFUSER_PIID_ON,
  XIAOMI_DIFFUSER_PIID_LEVEL, XIAOMI_DIFFUSER_LEVEL_MAX (default 3)
Env (cloud): XIAOMI_REGION, XIAOMI_LAMP_DID / XIAOMI_DIFFUSER_DID and their MIoT
  piids — full list in .env.example. Auth is a cached QR-login session, set up once
  with `python -m actuators.xiaomi --login` (see actuators/xiaomi_cloud.py).

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

# Mi-Home account region. Devices registered in mainland China live on the "cn"
# server, so token extraction must target it (the lib defaults to non-CN regions).
XIAOMI_REGION = os.environ.get("XIAOMI_REGION", "cn")

# Yeelight colour-temperature spans ~1700K (warm) .. 6500K (cool).
WARMTH_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6000}

# How to reach the devices:
#   local — miIO on the LAN (fast, same network required)
#   cloud — via the Mi cloud (works across networks, e.g. gear in China)
#   ble   — direct Bluetooth LE (for BLE-only gear like the camping lamp that's
#           never on Wi-Fi — see actuators/xiaomi_ble.py)
#   auto  — local when it's configured, otherwise cloud
XIAOMI_TRANSPORT = os.environ.get("XIAOMI_TRANSPORT", "auto").lower()


def _local_lamp_configured() -> bool:
    return bool(XIAOMI_LAMP_IP and XIAOMI_LAMP_TOKEN)


def _local_diffuser_configured() -> bool:
    return bool(XIAOMI_DIFFUSER_IP and XIAOMI_DIFFUSER_TOKEN)


def _use_cloud(local_ok: bool) -> bool:
    """Decide whether this call should go via the cloud transport."""
    if XIAOMI_TRANSPORT == "cloud":
        return True
    if XIAOMI_TRANSPORT == "local":
        return False
    return not local_ok  # auto: cloud only when local isn't set up


def lamp_configured() -> bool:
    from actuators import xiaomi_cloud

    if XIAOMI_TRANSPORT == "local":
        return _local_lamp_configured()
    if XIAOMI_TRANSPORT == "cloud":
        return xiaomi_cloud.lamp_configured()
    if XIAOMI_TRANSPORT == "ble":
        from actuators import xiaomi_ble

        return xiaomi_ble.configured()
    return _local_lamp_configured() or xiaomi_cloud.lamp_configured()


def diffuser_configured() -> bool:
    from actuators import xiaomi_cloud

    if XIAOMI_TRANSPORT == "local":
        return _local_diffuser_configured()
    if XIAOMI_TRANSPORT == "cloud":
        return xiaomi_cloud.diffuser_configured()
    return _local_diffuser_configured() or xiaomi_cloud.diffuser_configured()


def lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    """Set a Mijia/Yeelight lamp's brightness (0-100) and warmth. >0 turns it on.
    Routes by XIAOMI_TRANSPORT: ble drives a BLE-only lamp over Bluetooth, cloud
    goes via the Mi cloud, otherwise local miIO on the LAN."""
    if XIAOMI_TRANSPORT == "ble":
        from actuators import xiaomi_ble

        return xiaomi_ble.lamp_set(brightness, warmth)
    if _use_cloud(_local_lamp_configured()):
        from actuators import xiaomi_cloud

        return xiaomi_cloud.lamp_set(brightness, warmth)
    return _local_lamp_set(brightness, warmth)


def _local_lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    """Drive the lamp locally over miIO (same-LAN)."""
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
    pick a fragrance — that's whatever cartridge is loaded).
    Routes to the cloud transport when configured for it (see XIAOMI_TRANSPORT)."""
    if _use_cloud(_local_diffuser_configured()):
        from actuators import xiaomi_cloud

        return xiaomi_cloud.diffuser_set(intensity, scent)
    return _local_diffuser_set(intensity, scent)


def _local_diffuser_set(intensity: int, scent: str = "fresh") -> bool:
    """Drive the diffuser locally over miIO (same-LAN)."""
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


def _dev_field(d: dict, *keys: str) -> str:
    for k in keys:
        if d.get(k):
            return str(d[k])
    return ""


def _set_env(updates: dict[str, str]) -> None:
    """Update/insert KEY=value lines in the project .env (creating it if absent)."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    seen, out = set(), []
    for line in lines:
        m = re.match(r"\s*([A-Za-z0-9_]+)=", line)
        if m and m.group(1) in updates:
            out.append(f"{m.group(1)}={updates[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n")
    print(f"[xiaomi] wrote {', '.join(updates)} to {path}")


def _login(map_devices: bool = True) -> None:
    """QR-code Mi-Home login for the CLOUD transport. Scan the code in your Mi Home
    app; the session is cached so the autopilot can drive devices without a password
    (mainland-China accounts captcha-block scripted password logins). Optionally
    maps a lamp + diffuser into .env."""
    from actuators import xiaomi_cloud

    print(f"[xiaomi] Mi-Home QR login — region '{XIAOMI_REGION}'.")
    cloud = xiaomi_cloud.login_qr(server=XIAOMI_REGION)
    if cloud is None:
        return
    if not map_devices:
        return
    try:
        devices = cloud.list_devices()
    except Exception as exc:
        print(f"[xiaomi] logged in; device list unavailable ({exc}). "
              f"Set XIAOMI_LAMP_DID / XIAOMI_DIFFUSER_DID in .env manually.")
        return
    if not devices:
        print("[xiaomi] logged in, but no devices returned.")
        return
    print(f"\n[xiaomi] {len(devices)} device(s):")
    for i, d in enumerate(devices):
        print(f"  [{i}] {_dev_field(d, 'name')!r:28} model={_dev_field(d, 'model')}  did={_dev_field(d, 'did')}")

    def _pick(label, lamp=False):
        raw = input(f"  Which # is your {label}? (Enter = keep current .env): ").strip()
        if not raw:
            return
        try:
            d = devices[int(raw)]
        except (ValueError, IndexError):
            print(f"  skipped {label} (invalid choice)")
            return
        pfx = "XIAOMI_LAMP" if lamp else "XIAOMI_DIFFUSER"
        _set_env({f"{pfx}_DID": _dev_field(d, "did")})

    _pick("lamp", lamp=True)
    _pick("scent diffuser")
    print("\n[xiaomi] done. Test with:  python -m actuators.xiaomi lamp 70 warm")


def _ble_token() -> None:
    """Extract the BLE lamp's bind-key for the Bluetooth transport (xiaomi_ble.py).

    Reuses a cached Mi-Home session if present, else runs the QR login (scan in Mi
    Home). Then finds the BLE lamp in the account, fetches its beaconkey + MAC, and
    writes XIAOMI_BLE_MAC / XIAOMI_BLE_TOKEN / XIAOMI_BLE_NAME to .env so
    `XIAOMI_TRANSPORT=ble` can drive it."""
    from actuators import xiaomi_cloud

    cloud = xiaomi_cloud.load_session()
    if cloud is None:
        print(f"[xiaomi] no cached session — QR login first (region '{XIAOMI_REGION}').")
        cloud = xiaomi_cloud.login_qr(server=XIAOMI_REGION)
        if cloud is None:
            return
    try:
        devices = cloud.list_devices()
    except Exception as exc:
        print(f"[xiaomi] could not list devices ({exc}); session may have expired — "
              f"re-run `python -m actuators.xiaomi --login`.")
        return
    if not devices:
        print("[xiaomi] no devices in the account.")
        return

    # Auto-find the BLE lamp by model; fall back to letting the user pick. The
    # hackathon target is the HOTO camping lantern (hoto.light.lamp); match HOTO
    # light models, not every yeelink *.light.lamp* on the account.
    def _is_ble_lamp(d):
        model = _dev_field(d, "model").lower()
        return "hoto" in model and "light" in model

    print(f"\n[xiaomi] {len(devices)} device(s):")
    for i, d in enumerate(devices):
        flag = "  <- BLE lamp?" if _is_ble_lamp(d) else ""
        print(f"  [{i}] {_dev_field(d, 'name')!r:28} model={_dev_field(d, 'model')}  "
              f"did={_dev_field(d, 'did')}{flag}")

    matches = [i for i, d in enumerate(devices) if _is_ble_lamp(d)]
    if len(matches) == 1:
        # Unambiguous — pick it without prompting so the flow runs unattended.
        idx = matches[0]
        print(f"  auto-selected [{idx}] {_dev_field(devices[idx], 'name')!r} (only BLE lamp found)")
    else:
        try:
            raw = input("  Which # is the BLE lamp? ").strip()
            idx = int(raw)
            devices[idx]
        except (ValueError, IndexError):
            print("  invalid choice — aborted.")
            return
        except EOFError:
            print(f"  {len(matches)} candidates and no input — re-run in a terminal: "
                  f"  ! python -m actuators.xiaomi --ble-token")
            return

    d = devices[idx]
    did = _dev_field(d, "did")
    mac = _dev_field(d, "mac", "bssid")
    # The token for BLE *active control* is the device's own 32-hex token (same one
    # miIO uses). The "beaconkey" endpoint is only for decrypting passive MiBeacon
    # sensor broadcasts and comes back all-FF for a controllable lamp — so prefer
    # the device token, falling back to a non-empty beaconkey just in case.
    token = _dev_field(d, "token")
    if not token:
        try:
            bk = cloud.get_beaconkey(did)
        except Exception as exc:
            bk = ""
            print(f"[xiaomi] beaconkey lookup failed ({exc}).")
        token = bk if (bk and set(bk.upper()) != {"F"}) else ""
    if not token:
        print(f"[xiaomi] {_dev_field(d, 'name')!r} has no usable token — can't drive "
              f"it over BLE. (Is it actually a Bluetooth device on your account?)")
        return

    updates = {"XIAOMI_BLE_TOKEN": token, "XIAOMI_BLE_NAME": _dev_field(d, "model"),
               "XIAOMI_TRANSPORT": "ble"}
    if mac:
        updates["XIAOMI_BLE_MAC"] = mac
    _set_env(updates)
    print(f"\n[xiaomi] BLE lamp ready: model={_dev_field(d, 'model')} mac={mac or '(unknown — use --scan)'}")
    print("[xiaomi] set XIAOMI_TRANSPORT=ble, then test:  python -m actuators.xiaomi_ble lamp 70 warm")
    if not mac:
        print("[xiaomi] no MAC from cloud — find it with: python -m actuators.xiaomi_ble --scan")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--login"
    if arg == "--login":
        _login(map_devices="--no-map" not in sys.argv)
    elif arg == "--ble-token":
        _ble_token()
    elif arg == "lamp":
        bri = int(sys.argv[2]) if len(sys.argv) > 2 else 70
        warm = sys.argv[3] if len(sys.argv) > 3 else "warm"
        lamp_set(bri, warm)
    elif arg == "diffuser":
        inten = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        name = sys.argv[3] if len(sys.argv) > 3 else "fresh"
        diffuser_set(inten, name)
    else:
        print("usage: python -m actuators.xiaomi [--login [--no-map] | --ble-token | "
              "lamp <bri> <warm> | diffuser <intensity> <scent>]")
