# Xiaomi / Mijia integration — status & handoff

Integrates Xiaomi smart-home devices (a lamp + a scent source) into the comfort
autopilot, reusing the agent's existing `set_lighting` / `set_scent` actions — no
new action types, so agent / policy / dashboard are unchanged.

## TL;DR status (2026-06-20)
- **Cloud transport works.** Driving the user's **home** "Livingroom group"
  (`mijia.light.group2`) over the Mi cloud returned `code: 0` (verified live).
- **Auth is QR-session based**, not password — a mainland-China (`cn`) account
  captcha-blocks scripted password logins from a non-China IP (`登录验证失败`).
- **The hackathon devices are Bluetooth-only.** The lamp the user physically has
  (`hoto.light.lamp`) and the humidifier (`xiaomi.humidifier.czjsq`, BLE-mesh) are
  NOT on Wi-Fi, so neither cloud nor local-miIO can reach them. **Next step is a
  direct BLE driver for the lamp** (see "Resume here").

## Architecture
- `actuators/xiaomi.py` — transport router + **local miIO** driver (python-miio:
  Yeelight / MiotDevice). `lamp_set` / `diffuser_set` dispatch local vs cloud by
  `XIAOMI_TRANSPORT` (`auto|local|cloud`). Also `--login` (QR) + device mapping.
- `actuators/xiaomi_cloud.py` — **cloud** driver. QR login → cached session →
  signs each `/miotspec/prop/set` itself (RC4 + HMAC). `miot_set` inspects
  per-property result codes and raises on device-side failure (e.g. `-704042011`
  = device offline) so the actuator never reports false success.
- Wired as the priority backend inside `actuators/lights.py` (`set_lighting`) and
  `actuators/scent.py` (`set_scent`).
- Config: `.env` (gitignored) — see `.env.example` for every key.

## Auth / transports
- **Cloud (default here):** `XIAOMI_REGION=cn`, `XIAOMI_TRANSPORT=cloud`.
  `python -m actuators.xiaomi --login` → scan QR in Mi Home → session cached to
  `.xiaomi_session.json` (gitignored, contains a service token). Re-run if it
  expires. No password is stored.
- **Local miIO:** only works when this machine shares the LAN with the devices
  (needs each device's ip + 32-char token). Not usable for the China home gear or
  the BLE-only hackathon gear.

## Device inventory (dids only — tokens are NOT committed; they live in `.env` /
## the extractor output `.tools/xiaomi-tokens/out.json`, both gitignored)
| Role | Name | Model | did | Reach |
|---|---|---|---|---|
| Lamp (configured) | Livingroom group | `mijia.light.group2` | `group.1915468944337686528` | cloud ✅ (home, Wi-Fi) |
| Scent (configured) | Humidifier | `xiaomi.humidifier.czjsq` | `1200250022` | ✗ BLE-mesh, offline to cloud |
| **Hackathon lamp** | Mijia Camping Lantern | `hoto.light.lamp` | `1082443923` | **BLE only** — target of next step |

MIoT specs used (home.miot-spec.com):
- `mijia.light.group2`: siid2 on=piid1 (bool), brightness=piid2 (1-100). No colour-temp.
- `xiaomi.humidifier.czjsq`: siid2 on=piid1 (bool), fan-level=piid2 (gears 1-2).

## How to resume on another device
1. `git clone` + `git checkout main` (this work is on main).
2. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. Recreate `.env` from `.env.example` (copy the real one across — it has the
   device dids + tokens and is gitignored, so it is NOT in the repo).
4. Cloud session: `python -m actuators.xiaomi --login` (scan QR). Then test a
   Wi-Fi/cloud device, e.g. `python -m actuators.xiaomi lamp 70 warm`.
5. Re-extract tokens if needed: the QR token extractor is cloned in
   `.tools/xiaomi-tokens/` (gitignored). Run `python token_extractor.py --server cn`.

## Resume here — BLE lamp driver (the chosen next task)
The camping lamp `hoto.light.lamp` is reachable over BLE from the Mac. From the
scan (`.tools/ble_scan.py`):
```
★ rssi=-49 'hoto.light.lamp'
  service 0000fe95-…            (Xiaomi MiBeacon secure-auth)
    chars 0x10/0x16/0x17/0x18/0x1a/0x1b/0x1c = write / write-without-response
  service 00000100-0065-6c62-2e74-6f696d2e696d   (Mijia "miot.im" BLE control)
    char 00000101-… = write-without-response
    char 00000102-… = notify
```
Plan:
1. Implement the Xiaomi **token-based BLE login** over the `0xfe95` service
   (random exchange on the auth chars → key derivation from the lamp's token →
   AES session). Token for this lamp is in `.env` / extractor output (model
   `hoto.light.lamp`, did `1082443923`).
2. After login, send MIoT `set_property` frames (on/off, brightness) on char
   `00000101`, read responses on `00000102`.
3. Expose it behind the existing `set_lighting` action as a new `XIAOMI_TRANSPORT=ble`
   path so the autopilot can drive it.

Prereqs already done: `bleak` installed (NOT in requirements.txt — local-only),
Mac Bluetooth turned on via `blueutil`. BLE needs to run from a Terminal granted
Bluetooth permission (Privacy & Security → Bluetooth). Free the device from the
phone first (phone Bluetooth off) — BLE allows one central connection.

Caveat: the humidifier is BLE-**mesh** (encrypted, provisioned into the account
mesh) — not realistically controllable from a Mac. For a guaranteed demo, a
Wi-Fi actuator (any smart bulb/plug, or the home devices over cloud) is the
fallback.
