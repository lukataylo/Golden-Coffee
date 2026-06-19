"""Infrared climate control via a Broadlink IR blaster (RM4 mini / RM4 Pro etc.).

This replaces the smart-plug approach: instead of switching a fan on/off, we send
the actual AC/heater's IR remote codes, so the agent can genuinely nudge the room
temperature ("cool the room to encourage turnover", "warm it to keep people cosy").

Pre-hackathon setup (do once):
  1. Put a Broadlink RM4 mini on the same LAN, pointed at the AC/heater.
  2. Discover it:  `python -m actuators.infrared --discover`  -> set BROADLINK_HOST.
  3. Learn each remote button (point the AC remote at the blaster when prompted):
        python -m actuators.infrared --learn cool
        python -m actuators.infrared --learn warm
     Each prints a hex code — paste into BROADLINK_IR_COOL / BROADLINK_IR_WARM in .env
     (it also caches to actuators/ir_codes/<name>.hex).
  4. Test:  `python -m actuators.infrared -2`   (negative = cool)

Env: BROADLINK_HOST, BROADLINK_IR_COOL, BROADLINK_IR_WARM  (codes are hex strings)
Degrades gracefully (prints intent) when no device / codes are configured.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BROADLINK_HOST = os.environ.get("BROADLINK_HOST", "")
CODE_DIR = Path(__file__).resolve().parent / "ir_codes"


def _load_code(kind: str) -> str:
    """IR code (hex) for 'cool' or 'warm': env var first, then cached file."""
    env = os.environ.get(f"BROADLINK_IR_{kind.upper()}", "")
    if env:
        return env.strip()
    f = CODE_DIR / f"{kind}.hex"
    return f.read_text().strip() if f.exists() else ""


def _device():
    """Connect + auth to the configured Broadlink device (or discover one)."""
    import broadlink

    dev = broadlink.hello(BROADLINK_HOST) if BROADLINK_HOST else (broadlink.discover(timeout=4) or [None])[0]
    if dev is None:
        raise RuntimeError("no Broadlink device found (set BROADLINK_HOST or check the LAN)")
    dev.auth()
    return dev


def _send(code_hex: str) -> bool:
    dev = _device()
    dev.send_data(bytes.fromhex(code_hex))
    return True


def set_temperature(delta_c: float) -> bool:
    """Negative delta => send the AC 'cool' code; positive => 'warm'. Returns False
    (after printing intent) if the device or the relevant code is unavailable."""
    kind = "cool" if delta_c < 0 else "warm"
    code = _load_code(kind)
    if not code:
        print(f"[ir] (no {kind} code configured) would send AC '{kind}' (delta {delta_c:+.1f}C)")
        return False
    try:
        _send(code)
        print(f"[ir] sent AC '{kind}' code (delta {delta_c:+.1f}C)")
        return True
    except Exception as exc:
        print(f"[ir] failed to send '{kind}': {exc}")
        return False


def _discover() -> None:
    import broadlink

    devs = broadlink.discover(timeout=4)
    if not devs:
        print("[ir] no devices found")
        return
    for d in devs:
        print(f"[ir] {d.type} @ {d.host[0]}  (set BROADLINK_HOST={d.host[0]})")


def _learn(kind: str) -> None:
    """Capture one IR code and cache it; paste the printed hex into .env."""
    import time

    dev = _device()
    dev.enter_learning()
    print(f"[ir] point the AC remote at the blaster and press the '{kind}' button…")
    code = None
    for _ in range(15):
        time.sleep(1)
        try:
            code = dev.check_data()
            break
        except Exception:
            continue
    if not code:
        print("[ir] no code captured (timed out)")
        return
    hexcode = code.hex()
    CODE_DIR.mkdir(exist_ok=True)
    (CODE_DIR / f"{kind}.hex").write_text(hexcode)
    print(f"[ir] learned '{kind}':\nBROADLINK_IR_{kind.upper()}={hexcode}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "-2"
    if arg == "--discover":
        _discover()
    elif arg == "--learn":
        _learn(sys.argv[2] if len(sys.argv) > 2 else "cool")
    else:
        set_temperature(float(arg))
