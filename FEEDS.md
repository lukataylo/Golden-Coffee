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
```

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
