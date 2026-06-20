# Capturing the Mi Home BLE pairing handshake (to crack the lamp's secure-auth)

The HOTO camping lamp (`hoto.light.lamp`) uses Xiaomi's *newer* BLE secure-auth:
its `GET_INFO` doesn't return the 20-byte device-id the public `miauth` register
flow needs, and the cloud beaconkey is all-`FF` (no token login). See
`docs/xiaomi-integration.md` for the full dead-reckoning. The only reliable way
forward is to **watch the official Mi Home app authenticate**, then replay that
flow from `actuators/xiaomi_ble.py`.

This is a one-time capture on an **Android** phone (iOS can't export HCI logs).

## 1. Put the lamp into a pairing-able state
The app does the full key exchange when it **adds** a device. Easiest clean
capture: in Mi Home, **remove** the lamp (long-press → delete), then re-add it
while logging. (You'll re-add it — that's fine; it goes back on your account.)
Keep the phone close to the lamp; close other BLE apps to cut noise.

## 2. Turn on the Bluetooth HCI snoop log
On the Android phone:
1. Settings → About phone → tap **Build number** 7× to unlock Developer options.
2. Settings → System → **Developer options** → enable **Enable Bluetooth HCI snoop
   log** (some phones: set it to "Enabled" / "Filtered" → choose **Enabled**).
3. **Toggle Bluetooth off and on** so the new log file starts cleanly.

## 3. Do the pairing
In Mi Home: add the lamp (scan → it finds `hoto.light.lamp` → complete pairing).
Wait for it to finish (the lamp confirms / beeps). Then, for good measure, toggle
the lamp on/off a couple of times from the app — that captures the **post-auth
command frames** on the `miot.im` service too (the second thing we need).

## 4. Pull the log to this machine
The file is usually `/data/misc/bluetooth/logs/btsnoop_hci.log` (older phones:
`/sdcard/btsnoop_hci.log`). With `adb` (USB debugging on):

```bash
adb bugreport mibt.zip      # most reliable: snoop log is inside FS/data/misc/bluetooth/logs/
#   ...or, if accessible directly:
adb pull /sdcard/btsnoop_hci.log .
```
If it's only in the bugreport zip, unzip and find `btsnoop_hci.log` under
`FS/data/misc/bluetooth/logs/`.

## 5. Decode it
```bash
python tools/parse_mible_btsnoop.py btsnoop_hci.log
```
You'll get an ordered transcript of every GATT write/notification with the
characteristic UUID resolved and Xiaomi services labelled, e.g.:

```
-> WriteCmd  0x0010 (AUTH/UPNP control-point)   a2 00 00 00
<- Notify    0x0016 (AUTH data ...)             00 00 00 00 0a 00     <- 10 frames!
<- Notify    0x0016 (AUTH data ...)             01 00 <20-byte did…>
-> WriteReq  0x0010 (AUTH/UPNP control-point)   15 00 00 00           (SET_KEY)
-> WriteCmd  0x0016 (AUTH data ...)             <our pubkey parcels…>
...
-> WriteCmd  0x0101 (miot.im WRITE)             <encrypted on/off frame>
```
(Filter to the lamp's connection if multiple devices are present — the fe95 +
`miot.im` UUIDs make it obvious.)

## 6. What to extract (this is the payoff)
- **The real `GET_INFO` response** — how many frames, and the 20-byte device-id the
  app gets (our direct connect only saw `00*10 01 02`; the app likely gets the full
  id, possibly because it writes something to `0x10`/`0x17` first, or reads a
  different char). Note any **write the app does *before* `GET_INFO`**.
- **The register/login sequence** — which opcodes (`a2/15/24/13…`) on `0x10`, which
  data on `0x16`, and whether it matches `miauth` (then it's just our `GET_INFO`
  precondition that's wrong) or differs (new key exchange to implement).
- **The command frames** on `miot.im` `0101` for on/off + brightness, and the
  session keying — so we can encode our own after login.

Drop the transcript back into a session and we resume `actuators/xiaomi_ble.py`
from real data instead of guesswork. The `miauth`→bleak port that already works
(`tools/mible_register.py`, control `0x10` / data `0x16`) is the harness to plug
the corrected sequence into.
