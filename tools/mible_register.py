"""Scratch: drive miauth's mible register/login state machine over bleak (macOS).

miauth ships a Linux-only bluepy BLE layer; this provides a bleak-backed BLEBase
with the SAME sync interface so MiClient.register()/login() work unchanged. The
lamp relocated the data channel from AVDTP 0x19 -> 0x16, so we monkeypatch that.

Run next to the lamp. On register it will beep — press the lamp's power button.
"""
import asyncio
import queue
import sys
import threading

from bleak import BleakClient, BleakScanner
from miauth.ble.base import BLEBase
from miauth.ble.uuid import UUID
from miauth.mi.miclient import MiClient

BASE = "-0000-1000-8000-00805f9b34fb"
# This lamp's fe95 data channel is 0x16, not the scooter's 0x19.
UUID.AVDTP = "00000016" + BASE          # data (read frames / send parcels)
UUID.UPNP = "00000010" + BASE           # control point
NOTIFY = ["00000010", "00000016", "00000017", "00000018",
          "0000001a", "0000001b", "0000001c", "00000005"]
NOTIFY = [u + BASE for u in NOTIFY]


class BleakBLE(BLEBase):
    def __init__(self, name, debug=False):
        self.name = name
        self.debug = debug
        self.handler = None
        self.listen = True
        self.client = None
        self._q: queue.Queue = queue.Queue()
        self._loop = asyncio.new_event_loop()
        self._thr = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thr.start()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=30)

    # --- BLEBase interface (sync, as MiClient expects) ---------------------
    def set_handler(self, handler):
        self.handler = handler

    def connect(self):
        async def _c():
            dev = await BleakScanner.find_device_by_name(self.name, timeout=12)
            if dev is None:
                raise RuntimeError(f"{self.name!r} not advertising")
            self.client = BleakClient(dev, timeout=25)
            await self.client.connect()
            for u in NOTIFY:
                try:
                    await self.client.start_notify(u, self._on_notify)
                except Exception:
                    pass
        self._run(_c())
        print(f"[ble] connected {self.name}")

    def _on_notify(self, _sender, data):
        b = bytes(data)
        if self.debug:
            print("  <-", b.hex(" "))
        self._q.put(b)

    def write(self, ch, data, resp=False):
        if self.debug:
            print("  ->", ch[:8], bytes(data).hex(" "))
        self._run(self.client.write_gatt_char(ch, bytes(data), response=resp))

    def write_chunked(self, ch, data, resp=False, chunk_size=20):
        for i in range(0, len(data), chunk_size):
            self.write(ch, data[i:i + chunk_size], resp)

    def write_parcel(self, ch, data, resp=False, chunk_size=18):
        for i in range(0, len(data), chunk_size):
            chunk = bytes([i // chunk_size + 1, 0]) + data[i:i + chunk_size]
            self.write(ch, chunk, resp)

    def wait_notify(self, secs=1.0):
        # Drain ALL notifications until a `secs` gap, like bluepy's waitForNotifications
        # loop — the mible state machine needs every queued frame processed per call.
        while True:
            try:
                data = self._q.get(timeout=secs)
            except queue.Empty:
                return
            if self.handler is not None and self.listen:
                self.handler(data)

    def pause_listening(self):
        self.listen = False

    def resume_listening(self):
        self.listen = True

    def disconnect(self):
        async def _d():
            if self.client:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
        self._run(_d())

    def read(self, ch):
        return self._run(self.client.read_gatt_char(ch))

    def enable_notify(self, uuid):
        pass

    def read_device_name(self):
        return self.name.encode()

    def has_channel(self, name):
        return True


if __name__ == "__main__":
    name = sys.argv[2] if len(sys.argv) > 2 else "hoto.light.lamp"
    ble = BleakBLE(name, debug=True)
    ble.connect()
    mc = MiClient(ble, debug=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "register"
    try:
        if mode == "register":
            print(">>> Registering. When the lamp BEEPS, PRESS its power button.")
            mc.register()
            mc.save_token(".xiaomi_mible_token.bin")
            print("token saved -> .xiaomi_mible_token.bin")
        elif mode == "login":
            mc.load_token(".xiaomi_mible_token.bin")
            mc.login()
    finally:
        ble.disconnect()
