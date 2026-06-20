# Test feeds for the perception pipeline

`perception/run.py` accepts `--source` as a webcam index, a file path, a direct
stream URL (`.m3u8`/`.mp4`), **or a YouTube/livestream page URL** (auto-resolved
via `yt-dlp` to a direct stream and opened with OpenCV's FFMPEG backend).

```bash
# Live café (real people) — verified working, ~4-5 people/frame
python -m perception.run --source "https://www.youtube.com/watch?v=6PsWcInZdnk" --dry-run --max-frames 40

# Local sample clip (offline fallback, in clips/)
python -m perception.run --source clips/people-walking.mp4 --dry-run --max-frames 60

# Venue webcam on demo day
python -m perception.run --source 0

# Aqara G100 (or any RTSP/IP CCTV camera) — USB-C is power only, video is over Wi-Fi
python -m perception.run --source "rtsp://<CAMERA_IP>:554/live/ch00_1?token=<TOKEN>"
```

## RTSP / IP cameras (Aqara G100)
The Aqara G100 does **not** expose video over USB-C (that port is power only). It
streams over Wi-Fi via **RTSP**:

1. In the **Aqara Home app**, open the G100 → Settings → enable **RTSP / local stream**.
2. Copy the generated URL. Aqara uses a **token in the URL**, not user/pass:
   `rtsp://<CAMERA_IP>:554/live/ch00_1?token=<TOKEN>`
3. Pass it to `--source`. `perception/run.py` routes `rtsp://` through the FFMPEG
   backend and forces **TCP transport** (`rtsp_transport;tcp`) so the stream
   survives Wi-Fi packet loss.

Notes: the Mac and the camera must be on the **same network**; the token can
expire/rotate (re-copy from the app if the stream stops opening). Sanity-check the
URL first with `ffplay "<rtsp_url>"` or VLC before running the pipeline.

## Phone as camera over USB (DroidCam / IP Webcam) — best for locked-down Wi-Fi
On guest/captive-portal networks (hackathons, hotels) the AP isolates clients, so
a phone IP camera is unreachable over Wi-Fi. Route it over the **USB cable** with
adb port-forwarding instead — zero network dependency:

```bash
ADB=~/Library/Android/sdk/platform-tools/adb        # Android SDK platform-tools
$ADB devices                                         # confirm the phone shows up
$ADB -s <SERIAL> forward tcp:4747 tcp:4747           # DroidCam (IP Webcam: 8080)
python -m perception.run --source "http://127.0.0.1:4747/video"
```

- **DroidCam** MJPEG endpoint is `:4747/video`; **IP Webcam** is `:8080/video`.
- Keep the phone app in the **foreground** — DroidCam tears down its `:4747` web
  server when backgrounded/locked. (`adb shell input keyevent KEYCODE_WAKEUP`
  wakes the screen.) With two phones connected, target the right one via `-s <SERIAL>`.
- OpenCV's FFMPEG backend can't open these multipart-MJPEG streams, so `run.py`
  auto-falls back to its built-in `MJPEGCapture` reader (persistent connection,
  auto-reconnect). Raw-IP URLs also skip the yt-dlp resolve step.
- Verified working: DroidCam over USB → `1280x720@25fps`, ~9 fps through YOLO.

## Reality check on "live coffee shop" feeds
Genuine 24/7 livestreams of a **real café interior with a counter** are scarce —
most YouTube "coffee shop" streams are 3D-rendered or looped ambience with **no
real people** (useless for detection). The usable options:

### 1. Real café, real people (best for actual testing) — RECORDED
- **"People Watching at Real Cafe" — `6PsWcInZdnk`** (YouTube). Near-static camera,
  real customers, no loops/edits. **Verified: YOLO11 detects 4-5 people/frame.**
  This is our default test feed (works via the `--source <url>` path above).
- **"Busy cafe / Big Rush" barista vlog — `OKPt2-jW4EM`** — real busy café, moving camera.

### 2. CAFE dataset — best for ACCURACY validation (ground truth)
- https://dk-kim.github.io/CAFE/ · code https://github.com/dk-kim/CAFE_codebase · ECCV 2024.
- 6 real cafés × 4 fixed camera angles, 1080p, with **person boxes + tracks** and
  activity labels (queueing, ordering, eating, working). ~150 GB — download the
  Drive archive linked on the project page. Use it to measure dwell/occupancy/funnel
  accuracy, not just eyeball frames.

### 3. Live public webcams (live, but rarely a clean counter angle)
- **Cat Café San Diego (HDOnTap)** — live real interior with people; HLS `.m3u8`
  must be pulled from browser devtools (not yt-dlp friendly).
- **News Café Miami (EarthCam)** — live sidewalk-café seating; try `yt-dlp -g <url>`.
- Directories to browse for an interior with a counter: worldcams.tv/bars,
  webcamtaxi.com/en/restaurant.html, webcamera24.com/categories/bars-and-restaurants.

## yt-dlp → OpenCV (what `_resolve_source` does under the hood)
```bash
yt-dlp -f "best[height<=720]" -g "https://www.youtube.com/watch?v=VIDEO_ID"  # prints direct .m3u8
```
For long-running live streams the `.m3u8` URL expires — re-resolve periodically if a
stream drops. Requires `yt-dlp` (in requirements.txt) and `ffmpeg` on PATH.
