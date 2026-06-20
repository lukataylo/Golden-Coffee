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
  NOT on Wi-Fi, so neither cloud nor local-miIO can reach them. **A direct BLE
  driver for the lamp now exists** (`actuators/xiaomi_ble.py`,
  `XIAOMI_TRANSPORT=ble`); it needs one live confirm against the lamp (see "BLE
  lamp driver" below).

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

## BLE lamp driver — transport built, AUTH BLOCKED on newer secure-auth
`actuators/xiaomi_ble.py` is the third transport (`XIAOMI_TRANSPORT=ble`), wired
into `actuators/xiaomi.py`'s `lamp_set`. The connection + control plumbing is done
and validated, **but the lamp won't act on commands until its secure-auth is
solved** — see "ECDH register attempted" + the HCI-snoop plan below. What's built:
- GATT plumbing over the recon'd `miot.im` control service (write `0101` / notify
  `0102`) — connect, subscribe, write-without-response, match replies by txn id.
- MIoT-BLE RPC framing for `set_property` (on=siid2/piid1, brightness=siid2/piid2).
  ⚠️ Confirmed this does NOTHING without an authenticated session (see findings).
- CLI: `--scan` (find the MAC), `--debug [bri] [warm]` (dump every service/char/
  notification while driving — use this for the live bring-up), `lamp <bri> <warm>`.
- Env: `XIAOMI_BLE_MAC` / `_NAME` / `_TOKEN` / `_SIID` / `_PIID_ON` / `_PIID_BRIGHT`
  (see `.env.example`). Needs `pip install bleak` (local-only, not in
  requirements.txt — the server has no Bluetooth radio).

**Verified on this machine:** module imports, frame encoder (`set on` →
`0401020101`, `bright 70` → `0402020246`), router dispatch to the BLE path, and
graceful degrade (returns False, no crash) when no device is configured.

### Live bring-up findings (2026-06-20) — the auth is the hard ECDH "mible" path
Ran the driver + a probe against the physical lamp (it's in range, rssi ~-49,
advertises name `hoto.light.lamp`, CoreBluetooth UUID `84F8C993-…` — note macOS
addresses by that UUID, NOT the cloud MAC `D4:F0:EA:B8:2C:04`, so the driver
resolves by name on darwin). Established:
- **Plaintext MIoT writes to char `0101` do nothing** — the lamp ignores commands
  until an authenticated session exists (confirmed: no physical reaction).
- The lamp speaks Xiaomi's **"mible" auth** (cf. github.com/dnandha/miauth): write
  a command to control point **`0x10`**, device replies on data char **`0x16`**
  (the scooter variant uses `0x19`; this lamp relocated it to `0x16`). Verified:
  `GET_INFO` (`a2 00 00 00` → `0x10`) returned `00 00 00 00 01 00` on `0x16`.
- char `0x0004` reads the firmware string (`2.1.1_0027`); `0x0005` is empty.
- **The cloud beaconkey is all-`FF`** (`get_beaconkey` → no stored token). So there
  is NO token-login shortcut — the lamp needs the **ECDH `register` flow**
  (SECP256R1 + HKDF `mible-setup-info` + AES-CCM), which **requires physically
  pressing the lamp's power button within ~5 s of the pairing beep**. After that,
  `login` (HKDF `mible-login-info` over the 12-byte derived token) yields the
  session keys.

**ECDH register attempted (2026-06-20) — hit the newer-auth wall.** Ported
miauth's mible state machine onto bleak (`tools/mible_register.py`:
a `BleakBLE(BLEBase)` that bridges miauth's *sync* interface to async bleak via a
background event loop + a drained notification queue; `UUID.AVDTP` monkeypatched
`0x19 → 0x16`). Results:
- Transport + frame protocol **work**: `GET_INFO` (`a2000000 → 0x10`) round-trips —
  device replies `00 00 00 00 01 00` (1 frame), we ACK `RCV_RDY` on `0x16`, it sends
  the info frame. ECDH P-256 keypair gen + pubkey parcel framing all run.
- **But** the lamp's `GET_INFO` payload is just `00*10 01 02` → `remote_info[4:]`
  is **8 bytes, not the 20-byte device-id** mible `register` needs to compute the
  ECDH binding (`calc_did`). So `register` can't proceed, and `login` needs a token
  we don't have (beaconkey = FF). This is Xiaomi's *newer* BLE secure-auth, which
  doesn't match the public miauth register/login flows.

**Remaining work is real RE, not a tweak.** To crack control you'd need to:
1. Capture the **Mi Home app's BLE pairing handshake** with an Android HCI snoop
   log, then decode it. **Step-by-step guide: `docs/xiaomi-ble-hcisnoop.md`;
   decoder: `tools/parse_mible_btsnoop.py`** (pure-Python btsnoop→ATT, labels the
   fe95 + miot.im chars). This reveals this firmware's real auth/key-exchange and
   how it presents the 20-byte did our direct connect never got.
2. Then reverse the post-auth **command channel** on the `miot.im` service (`0101`
   write / `0102` notify) — session-encrypted MIoT-spec frames, not covered by any
   reference impl (miauth drives scooters over a Nordic-UART service this lamp
   lacks).

Net: BLE control of THIS lamp is a multi-session reverse-engineering project. What
exists now is a solid foundation — working BLE transport, scan/probe/register
tooling, the confirmed auth fingerprint, and the cloud token plumbing.
**Guaranteed-demo fallback: drive a Wi-Fi light over the already-working cloud
transport** — the account has many (Yeelight bulbs, the "Livingroom group" that
returns `code:0`).

### HCI capture done (2026-06-20) — it's Mijia CERTIFICATE mutual-auth (MJAC)
Captured the Mi Home app pairing the lamp (Pixel 10 `adb bugreport` →
`btsnoop_hci.log.last` → `tools/parse_mible_btsnoop.py`; raw kept in `.tools/bt/`,
gitignored — contains device certs). The app does NOT use the simple mible
register/login at all. It runs Xiaomi's **certificate-based mutual authentication**:
- Control-point (`0x10`) opcode sequence: `a4` → `50` →(dev)`51` → `a4` → `40` →
  `43` →(dev)**`41`** (= auth OK). Cf. miauth's `0x21/0x24`; the `0x40/0x41/0x43`
  family is the *cert* flow.
- Over data char `0x16` (framed `00 00 <seq> <chan> <len16>` + `<idx16><payload>`),
  both sides exchange **X.509 cert chains + ECDH P-256 keys + ECDSA signatures**:
  device sends its **`Mijia Device`** cert (issuer `Mijia Mesh`, OEM `fulian` =
  Foxconn) and the app sends a **`Mijia Cloud`** cert (issuer `Mijia Root`). Mutual
  verify, then a session key.
- Re-pairing **rotated the miIO token** (proves the bind succeeded) but the cloud
  **beaconkey is still all-`FF`** → confirmed: no token shortcut, this device does
  the cert handshake every connect.
- The post-auth **command frames were NOT captured** (the snoop rotated right after
  `0x41`; the current `btsnoop_hci.log` held only HCI events, no ACL). Moot until
  auth is solved anyway.

**The real wall:** to impersonate the app we'd need the **`Mijia Cloud` cert's
private key** to produce the ECDSA signature the lamp verifies. That key is
issued/embedded by Xiaomi (app binary keystore, or a per-device cloud-issued
binding credential) — getting it is app-RE / keystore extraction or finding the
cloud "bind credential" endpoint. That's a genuine research project, not a coding
tweak. The full decoded transcript is preserved at `.tools/bt/decoded.txt` for
whoever picks it up. **For a working demo now, use the Wi-Fi cloud fallback above.**

### Original recon (for reference)
The camping lamp `hoto.light.lamp` is reachable over BLE from the Mac. From the
scan (now `python -m actuators.xiaomi_ble --scan`):
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
