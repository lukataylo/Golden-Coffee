"""Xiaomi cloud transport — drive MIoT devices through the Mi cloud (no LAN).

Used when the machine running actuators/run.py is NOT on the same network as the
devices — e.g. the Mijia lamp + diffuser live in mainland China and the comfort
autopilot runs elsewhere. We log in to the Mi cloud for your account's region
(XIAOMI_REGION, "cn" for mainland China) and send MIoT property writes addressed
by the device's `did`.

Identify each device by:
  * its `did`  — printed by `python -m actuators.xiaomi --cloud`
  * the siid/piid of each property — from the device's spec at home.miot-spec.com

The defaults below match the common Mijia light + diffuser MIoT services, but
specs vary per model — override the piids in .env if a write does nothing.

Needs `micloud` + Mi account creds (XIAOMI_MI_USER / XIAOMI_MI_PASS).
Degrades gracefully (prints intent) when unconfigured / unreachable.
"""
from __future__ import annotations

import json
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

REGION = os.environ.get("XIAOMI_REGION", "cn")
MI_USER = os.environ.get("XIAOMI_MI_USER", "")
MI_PASS = os.environ.get("XIAOMI_MI_PASS", "")

WARMTH_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6000}

# Lamp MIoT props (Mijia/Yeelight light service). Override per model if needed.
LAMP_DID = os.environ.get("XIAOMI_LAMP_DID", "")
LAMP_SIID = int(os.environ.get("XIAOMI_LAMP_SIID", "2"))
LAMP_PIID_ON = int(os.environ.get("XIAOMI_LAMP_PIID_ON", "1"))
LAMP_PIID_BRIGHT = int(os.environ.get("XIAOMI_LAMP_PIID_BRIGHT", "2"))
LAMP_PIID_CT = os.environ.get("XIAOMI_LAMP_PIID_CT", "")  # blank => skip colour temp

# Diffuser MIoT props.
DIFF_DID = os.environ.get("XIAOMI_DIFFUSER_DID", "")
DIFF_SIID = os.environ.get("XIAOMI_DIFFUSER_SIID", "2")
DIFF_PIID_ON = os.environ.get("XIAOMI_DIFFUSER_PIID_ON", "1")
DIFF_PIID_LEVEL = os.environ.get("XIAOMI_DIFFUSER_PIID_LEVEL", "")
DIFF_LEVEL_MAX = int(os.environ.get("XIAOMI_DIFFUSER_LEVEL_MAX", "3"))


def _creds() -> bool:
    return bool(MI_USER and MI_PASS)


def lamp_configured() -> bool:
    return bool(_creds() and LAMP_DID)


def diffuser_configured() -> bool:
    return bool(_creds() and DIFF_DID)


def _api_base() -> str:
    """Mi IO app endpoint for the account region ('' prefix for cn)."""
    region = REGION.lower()
    prefix = "" if region == "cn" else f"{region}."
    return f"https://{prefix}api.io.mi.com/app"


# One cached, logged-in session for the life of the process.
_mc = None


def _session():
    global _mc
    if _mc is None:
        from micloud import MiCloud

        mc = MiCloud(MI_USER, MI_PASS)
        mc.login()
        _mc = mc
    return _mc


def _miot_set(did: str, props: list[dict]) -> None:
    """Write one or more MIoT properties: props = [{siid, piid, value}, ...]."""
    mc = _session()
    params = [{"did": str(did), **p} for p in props]
    payload = {"params": params}
    mc.request(_api_base() + "/miotspec/prop/set", {"data": json.dumps(payload)})


def lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    brightness = max(0, min(100, int(brightness)))
    if not lamp_configured():
        print(f"[xiaomi-cloud] (lamp unconfigured) would set {brightness}% / {warmth}")
        return False
    try:
        if brightness <= 0:
            _miot_set(LAMP_DID, [{"siid": LAMP_SIID, "piid": LAMP_PIID_ON, "value": False}])
            print("[xiaomi-cloud] lamp off")
            return True
        props = [
            {"siid": LAMP_SIID, "piid": LAMP_PIID_ON, "value": True},
            {"siid": LAMP_SIID, "piid": LAMP_PIID_BRIGHT, "value": brightness},
        ]
        if LAMP_PIID_CT:
            props.append({"siid": LAMP_SIID, "piid": int(LAMP_PIID_CT),
                          "value": WARMTH_KELVIN.get(warmth, 4000)})
        _miot_set(LAMP_DID, props)
        print(f"[xiaomi-cloud] lamp brightness {brightness}% / {warmth}")
        return True
    except Exception as exc:
        print(f"[xiaomi-cloud] lamp failed: {exc}")
        return False


def diffuser_set(intensity: int, scent: str = "fresh") -> bool:
    intensity = max(0, min(100, int(intensity)))
    on = intensity > 0
    if not diffuser_configured():
        print(f"[xiaomi-cloud] (diffuser unconfigured) would set {intensity}% ({scent})")
        return False
    try:
        props = [{"siid": int(DIFF_SIID), "piid": int(DIFF_PIID_ON), "value": on}]
        if on and DIFF_PIID_LEVEL:
            level = max(1, min(DIFF_LEVEL_MAX, round(intensity / 100 * DIFF_LEVEL_MAX)))
            props.append({"siid": int(DIFF_SIID), "piid": int(DIFF_PIID_LEVEL), "value": level})
            _miot_set(DIFF_DID, props)
            print(f"[xiaomi-cloud] diffuser on level {level}/{DIFF_LEVEL_MAX} ({scent})")
        else:
            _miot_set(DIFF_DID, props)
            print(f"[xiaomi-cloud] diffuser {'on' if on else 'off'} ({scent})")
        return True
    except Exception as exc:
        print(f"[xiaomi-cloud] diffuser failed: {exc}")
        return False
