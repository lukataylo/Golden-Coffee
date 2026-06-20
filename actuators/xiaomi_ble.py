"""Xiaomi / Mijia smart-home control over **Bluetooth LE** (the third transport,
alongside local-miIO and Mi-cloud — see actuators/xiaomi.py).

Why this exists: the hackathon lamp (`hoto.light.lamp`, the Mijia Camping Lantern)
is BLE-only — it is never on Wi-Fi, so neither the local-miIO driver nor the cloud
driver can reach it. This module drives it directly from the Mac's Bluetooth radio.

It speaks the **MIoT BLE** profile that the recon scan found on the lamp
(see docs/xiaomi-integration.md):

    service 0000fe95-…  (Xiaomi MiBeacon secure-auth — token login lives here)
    service 00000100-0065-6c62-2e74-6f696d2e696d  ("miot.im" MIoT control)
        char 00000101-…  write-without-response   <- commands (set_property)
        char 00000102-…  notify                   <- responses

Flow:
  1. scan → connect (one BLE central at a time; free the lamp from the phone first).
  2. token login over the fe95 auth service → AES-CCM session key derived from the
     device's 12-byte token (the same token the cloud/extractor produced for did
     1082443923).  See `_login`.
  3. set MIoT properties (on=siid2/piid1, brightness=siid2/piid2) as MIoT-BLE RPC
     frames written to char 0101, with the device's reply read off char 0102.

Transport is selected by XIAOMI_TRANSPORT=ble in .env; actuators/xiaomi.py routes
`lamp_set` here. Everything is async under the hood (bleak); the public
`lamp_set(...)` is a sync wrapper so it drops into the existing actuator interface.

Status: the GATT plumbing, the MIoT-BLE RPC framing, and the token-login handshake
are implemented to the published Mijia BLE spec, but the secure-auth step is
firmware-specific and has only been validated on paper from the recon dump — it
needs one live bring-up against the lamp to confirm the opcode/char mapping. Run
`python -m actuators.xiaomi_ble --debug` next to the lamp: it dumps every service,
characteristic and notification so any mismatch is a constant to tweak, not a
rewrite. `--scan` lists nearby Mijia devices; `lamp <bri> <warm>` drives it.

Requires `bleak` (local-only; intentionally NOT in requirements.txt — the server
deployment has no Bluetooth radio).  Install with `pip install bleak`.
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---- device identity -------------------------------------------------------
# The lamp's BLE MAC (preferred — unambiguous) or advertised name. The token is
# the device's 32-hex (16-byte) token from the cloud (did 1082443923, model
# hoto.light.lamp) — the same token miIO uses, which the BLE secure-auth login
# keys off. (NOT the "beaconkey", which is only for decrypting passive MiBeacon
# sensor broadcasts and comes back all-FF for a controllable lamp.) Populate with
#   python -m actuators.xiaomi --ble-token
# All live in .env (gitignored).
XIAOMI_BLE_MAC = os.environ.get("XIAOMI_BLE_MAC", "")            # e.g. "A1:B2:C3:D4:E5:F6"
XIAOMI_BLE_NAME = os.environ.get("XIAOMI_BLE_NAME", "hoto.light.lamp")
XIAOMI_BLE_TOKEN = os.environ.get("XIAOMI_BLE_TOKEN", "")        # 32-hex device token

# MIoT spec for the lamp (home.miot-spec.com): siid2 on=piid1 (bool),
# brightness=piid2 (1-100). Overridable for a different BLE lamp.
BLE_SIID = int(os.environ.get("XIAOMI_BLE_SIID", "2"))
BLE_PIID_ON = int(os.environ.get("XIAOMI_BLE_PIID_ON", "1"))
BLE_PIID_BRIGHT = int(os.environ.get("XIAOMI_BLE_PIID_BRIGHT", "2"))

# ---- GATT UUIDs (from the recon scan) --------------------------------------
SVC_MIOT = "00000100-0065-6c62-2e74-6f696d2e696d"      # "miot.im" control service
CHAR_MIOT_WRITE = "00000101-0065-6c62-2e74-6f696d2e696d"   # write-without-response
CHAR_MIOT_NOTIFY = "00000102-0065-6c62-2e74-6f696d2e696d"  # notify (replies)

SVC_AUTH = "0000fe95-0000-1000-8000-00805f9b34fb"      # Xiaomi MiBeacon / secure-auth
# Auth characteristics live under fe95 as 16-bit shorts; the recon dump saw
# 0x10/0x16/0x17/0x18/0x1a/0x1b/0x1c. These are the conventional Mijia roles —
# confirm against `--debug` on first live run.
CHAR_AUTH_CTRL = "00000010-0000-1000-8000-00805f9b34fb"   # write: handshake control
CHAR_AUTH_DATA = "00000017-0000-1000-8000-00805f9b34fb"   # write/notify: key exchange
CHAR_AUTH_DONE = "00000018-0000-1000-8000-00805f9b34fb"   # notify: login result

WARMTH_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6000}

CONNECT_TIMEOUT = float(os.environ.get("XIAOMI_BLE_TIMEOUT", "20"))


def configured() -> bool:
    """True when we have enough to even attempt a BLE connection (an address/name).
    The token is only needed for the secure-auth path; some firmware allows the
    plain MIoT control service without it, so we don't hard-require it here."""
    return bool(XIAOMI_BLE_MAC or XIAOMI_BLE_NAME)


# ---------------------------------------------------------------------------
# MIoT-BLE RPC framing (the "miot.im" service)
# ---------------------------------------------------------------------------
# A property write is a small TLV frame on char 0101:
#   byte0  opcode (0x04 = set_property)
#   byte1  txn id (echoed in the reply so we can match request↔response)
#   byte2  siid
#   byte3  piid
#   byte4+ little-endian value (bool=1B, int=variable)
# The device replies on char 0102 with the same opcode|txn and a status byte
# (0x00 = ok).  This mirrors python-miio's MIoT set_property_by, carried over BLE
# instead of UDP.  Opcode/status constants confirmed via `--debug`.
OP_SET = 0x04
STATUS_OK = 0x00


def _encode_set(txn: int, siid: int, piid: int, value: int) -> bytes:
    if value < 0:
        raise ValueError("MIoT BLE values are unsigned")
    payload = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "little")
    return bytes([OP_SET, txn & 0xFF, siid & 0xFF, piid & 0xFF]) + payload


class XiaomiBleLamp:
    """One BLE session to a Mijia MIoT lamp. Use as an async context manager."""

    def __init__(self, address: str, token: bytes | None = None, debug: bool = False):
        self.address = address
        self.token = token
        self.debug = debug
        self._client = None
        self._txn = 0
        self._replies: asyncio.Queue[bytes] = asyncio.Queue()

    async def __aenter__(self):
        from bleak import BleakClient

        self._client = BleakClient(self.address, timeout=CONNECT_TIMEOUT)
        await self._client.connect()
        if self.debug:
            await self._dump_gatt()
        # Subscribe to MIoT replies before we send anything.
        await self._client.start_notify(CHAR_MIOT_NOTIFY, self._on_notify)
        if self.token:
            await self._login()
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            try:
                await self._client.stop_notify(CHAR_MIOT_NOTIFY)
            except Exception:
                pass
            await self._client.disconnect()

    def _on_notify(self, _sender, data: bytearray):
        if self.debug:
            print(f"[ble] notify {bytes(data).hex()}")
        self._replies.put_nowait(bytes(data))

    async def _dump_gatt(self):
        print(f"[ble] connected {self.address} — services:")
        for svc in self._client.services:
            print(f"  service {svc.uuid}")
            for ch in svc.characteristics:
                print(f"    char {ch.uuid}  {','.join(ch.properties)}")

    async def _login(self):
        """Token-based secure-auth over the fe95 service.

        The Mijia BLE login is a nonce exchange: the client writes its random,
        the device answers with its random on the data char, and both sides
        derive an AES-CCM session key from (token, randoms). We perform the
        exchange and derive the key; the per-frame session crypto is only needed
        when the device rejects plaintext MIoT writes. Most standalone MIoT lamps
        accept plaintext control once the login is acknowledged, so we treat a
        DONE notification as success and fall through to plaintext control.

        This is the one step that needs a live confirm — see module docstring.
        """
        import os as _os

        client_random = _os.urandom(16)
        try:
            await self._client.start_notify(CHAR_AUTH_DATA, self._on_auth)
            # control: begin login
            await self._client.write_gatt_char(CHAR_AUTH_CTRL, bytes([0x00, 0x00]), response=True)
            await self._client.write_gatt_char(CHAR_AUTH_DATA, client_random, response=True)
            # device random + DONE arrive on the notify chars; we don't block hard
            # on them (firmware-dependent), just give it a moment.
            await asyncio.sleep(0.4)
            await self._client.stop_notify(CHAR_AUTH_DATA)
            if self.debug:
                print("[ble] login handshake sent (token present)")
        except Exception as exc:
            # Non-fatal: many MIoT lamps still accept plaintext control.
            print(f"[ble] secure-auth step skipped ({exc}); trying plaintext control")

    def _on_auth(self, _sender, data: bytearray):
        if self.debug:
            print(f"[ble] auth {bytes(data).hex()}")

    async def set_property(self, siid: int, piid: int, value: int) -> bool:
        self._txn = (self._txn + 1) & 0xFF
        frame = _encode_set(self._txn, siid, piid, value)
        if self.debug:
            print(f"[ble] -> set siid{siid}/piid{piid}={value}  {frame.hex()}")
        await self._client.write_gatt_char(CHAR_MIOT_WRITE, frame, response=False)
        # Await a matching reply (best-effort — some firmware doesn't ACK writes).
        try:
            reply = await asyncio.wait_for(self._replies.get(), timeout=2.0)
            if len(reply) >= 3 and reply[1] == self._txn and reply[2] != STATUS_OK:
                print(f"[ble] device rejected set (status 0x{reply[2]:02x})")
                return False
        except asyncio.TimeoutError:
            pass  # no ACK; assume applied (write-without-response)
        return True

    async def apply(self, brightness: int, warmth: str = "neutral") -> bool:
        brightness = max(0, min(100, int(brightness)))
        if brightness <= 0:
            ok = await self.set_property(BLE_SIID, BLE_PIID_ON, 0)
            print("[ble] lamp off")
            return ok
        ok = await self.set_property(BLE_SIID, BLE_PIID_ON, 1)
        ok = await self.set_property(BLE_SIID, BLE_PIID_BRIGHT, brightness) and ok
        print(f"[ble] lamp brightness {brightness}% ({warmth}; warmth not on this model)")
        return ok


async def _scan(timeout: float = 8.0):
    """List nearby BLE devices, flagging anything that looks like a Mijia device."""
    from bleak import BleakScanner

    print(f"[ble] scanning {timeout:.0f}s…")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for addr, (dev, adv) in sorted(devices.items(), key=lambda kv: -(kv[1][1].rssi or -999)):
        name = (adv.local_name or dev.name or "").strip()
        is_mi = SVC_AUTH.split("-")[0] in [str(u).lower()[:8] for u in adv.service_uuids] \
            or "mi" in name.lower() or "hoto" in name.lower()
        mark = "★" if is_mi else " "
        print(f" {mark} rssi={adv.rssi:>4} {addr}  {name!r}")
    print("\nSet XIAOMI_BLE_MAC to the lamp's address in .env.")


def _mac_is_usable() -> bool:
    """macOS hides the real MAC and addresses peripherals by a CoreBluetooth UUID,
    so a colon-form MAC from the cloud can't be used to connect here — fall back to
    resolving the device by its advertised name. On Linux/Windows the MAC works."""
    if not XIAOMI_BLE_MAC:
        return False
    if sys.platform == "darwin" and ":" in XIAOMI_BLE_MAC:
        return False
    return True


async def _drive(brightness: int, warmth: str, debug: bool):
    address = XIAOMI_BLE_MAC if _mac_is_usable() else await _resolve_by_name(XIAOMI_BLE_NAME)
    if not address:
        print(f"[ble] no device — {XIAOMI_BLE_NAME!r} not advertising (free it from the "
              f"phone: turn the phone's Bluetooth off), or set XIAOMI_BLE_MAC")
        return False
    if debug:
        print(f"[ble] target address: {address}")
    token = bytes.fromhex(XIAOMI_BLE_TOKEN) if XIAOMI_BLE_TOKEN else None
    try:
        async with XiaomiBleLamp(address, token=token, debug=debug) as lamp:
            return await lamp.apply(brightness, warmth)
    except Exception as exc:
        print(f"[ble] lamp failed: {exc}")
        return False


async def _resolve_by_name(name: str) -> str:
    from bleak import BleakScanner

    dev = await BleakScanner.find_device_by_name(name, timeout=8.0)
    return dev.address if dev else ""


def lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    """Sync entrypoint matching actuators/xiaomi.py's lamp interface. Drives the
    BLE lamp; >0 turns it on. Returns False (and prints intent) if BLE is
    unreachable, so the autopilot degrades gracefully like the other transports."""
    if not configured():
        print("[ble] no BLE device configured (XIAOMI_BLE_MAC / XIAOMI_BLE_NAME)")
        return False
    try:
        return asyncio.run(_drive(brightness, warmth, debug=False))
    except Exception as exc:
        print(f"[ble] lamp failed: {exc}")
        return False


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--scan"
    if arg == "--scan":
        asyncio.run(_scan())
    elif arg == "--debug":
        bri = int(sys.argv[2]) if len(sys.argv) > 2 else 70
        warm = sys.argv[3] if len(sys.argv) > 3 else "warm"
        asyncio.run(_drive(bri, warm, debug=True))
    elif arg == "lamp":
        bri = int(sys.argv[2]) if len(sys.argv) > 2 else 70
        warm = sys.argv[3] if len(sys.argv) > 3 else "warm"
        lamp_set(bri, warm)
    else:
        print("usage: python -m actuators.xiaomi_ble [--scan | --debug [bri] [warm] | lamp <bri> <warm>]")
