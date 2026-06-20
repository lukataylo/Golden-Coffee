# 📱 Phone camera over USB (DroidCam) — setup & restart guide

Run the perception pipeline on a live **phone camera** instead of a webcam or
clip. We route the phone over the **USB cable** (not Wi‑Fi) so it works on
locked‑down / guest networks (hackathons, hotels) where devices can't reach each
other — zero network dependency.

> TL;DR once it's set up: **`scripts/phone_cam.sh`** — it re‑arms the tunnel,
> waits for the stream, and starts perception with low‑latency settings.

---

## One‑time setup

1. **Install adb** (Android platform tools) on the Mac:
   ```bash
   brew install android-platform-tools
   ```
2. **Install a DroidCam app** on the phone. Two variants exist:
   - **DroidCam** (classic) — serves a steady MJPEG at `:4747/video`. **Preferred.**
   - **DroidCam OBS** — works too, but its MJPEG serving is flakier (it's built for
     the OBS plugin). If frames stall, prefer the classic app.
3. On the phone, enable **Developer options → USB debugging**
   (Settings → About phone → tap *Build number* 7×, then back → System → Developer options).

## Each time you want the live feed

1. **Plug the phone in** via USB and **unlock** it.
2. The first time per machine, tap **"Allow"** on the **"Allow USB debugging?"** prompt
   (tick *Always allow from this computer*).
3. **Open the DroidCam app** and keep it in the **foreground, screen on**.
4. Start it:
   ```bash
   scripts/phone_cam.sh
   ```
   The script confirms the phone is authorized, re‑arms the USB tunnel, waits for
   DroidCam to serve frames, then launches perception. Open
   **http://127.0.0.1:8000/** to see the feed (start the backend first if needed —
   see README).

### What the script runs (if you prefer to do it by hand)
```bash
adb devices                                   # phone must show "device" (not "unauthorized")
adb forward tcp:4747 tcp:4747                  # tunnel DroidCam's port over USB
curl -m3 -o/dev/null -w "%{http_code}\n" http://127.0.0.1:4747/video   # expect 200
python3 -m perception.run --source "http://127.0.0.1:4747/video" --imgsz 480
```

---

## Restarting / troubleshooting

DroidCam serves **one client at a time** and tears its server down when
backgrounded — so a stalled or wedged feed is the usual hiccup. Symptoms & fixes:

| Symptom | Cause | Fix |
|---|---|---|
| `:4747/video` returns **`000`** / `phone_cam.sh` says "not serving" | App backgrounded, screen locked, or the stream isn't started | Open DroidCam, make sure the **camera preview is running**, keep it **foreground + screen on**, re‑run the script |
| Feed **freezes** after it was working | Perception was killed mid‑stream and the single connection wedged | Stop perception (`Ctrl‑C`), in the app stop/start the camera, re‑run `scripts/phone_cam.sh` |
| `adb devices` shows **`unauthorized`** | Debugging prompt not accepted | Unlock phone, tap **Allow** on the prompt (`adb kill-server && adb devices` re‑triggers it) |
| `adb` lists **no device** | Cable/debugging | Try a data‑capable cable/port; toggle USB debugging off/on |
| Stream is **laggy / high latency** | Resolution too high for USB throughput | **Lower the in‑app resolution to 480p** — this is the #1 latency lever. Also pass `--imgsz 384` |
| Wake a locked screen from the Mac | — | `adb shell input keyevent KEYCODE_WAKEUP` |

### Latency notes
The AI side is fast (YOLO ≈ 17–46 ms/frame; runs on the **GPU/MPS by default**).
Latency you see is almost always the **DroidCam feed**, not the pipeline:
- **Lower the in‑app resolution** (480p) — biggest win.
- Keep the DroidCam app **foreground**; it throttles/stops in the background.
- Perception flags for extra headroom: `--imgsz 384` (smaller = faster),
  `--face-blur off` (skip privacy blur for a pure‑speed test),
  `--stream-fps 15` (annotated‑frame rate to the dashboard).

### Real venue zones
The default zones are demo bands. For your camera framing, generate proper zones
(no GUI needed) and pass them in:
```bash
python3 -m perception.run --preset counter_top --tables 6 --gen-zones zones.json
scripts/phone_cam.sh --zones zones.json
```

---

## Wi‑Fi instead of USB?
Only if both devices are on the **same LAN** with no client isolation. Get the IP
DroidCam shows (e.g. `192.168.x.x:4747`) and use it directly — no adb:
```bash
python3 -m perception.run --source "http://192.168.x.x:4747/video" --imgsz 480
```
On guest/hackathon Wi‑Fi this usually fails (client isolation) — use USB.
