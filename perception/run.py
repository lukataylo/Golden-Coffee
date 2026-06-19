"""Perception pipeline — YOLO11 + supervision, emitting SceneEvents.

Built on roboflow/supervision (MIT):
  YOLO('yolo11n.pt') -> sv.Detections.from_ultralytics -> filter person (class 0)
  -> sv.ByteTrack (stable ids) -> sv.PolygonZone per zone (occupancy)
  -> per-track dwell timers -> conversion-funnel state machine
  -> coarse dwell heatmap + movement-based staff-productivity proxy.

Faces are blurred (head region of each person box) before any bbox leaves this
process — the privacy/ethics requirement. No identities are ever stored; tracker
ids are ephemeral.

Run:
  python -m perception.run --source 0                       # webcam, POST to backend
  python -m perception.run --source clips/people-walking.mp4
  python -m perception.run --source clips/x.mp4 --dry-run --max-frames 60

Env:
  BACKEND_URL        (default http://127.0.0.1:8000)
  PERCEPTION_EMIT_S  (default 1.0) — seconds of (video) time between emitted scenes
"""
from __future__ import annotations

import argparse
import os
import time

from shared.schemas import Funnel, Role, SceneEvent, Track, Zone

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
EMIT_EVERY_S = float(os.environ.get("PERCEPTION_EMIT_S", "1.0"))

# --- Tunables ----------------------------------------------------------------
ORDER_DWELL_S = 4.0     # dwell at counter beyond this => "ordered" (purchase proxy)
STAFF_DWELL_S = 25.0    # a track living behind the counter this long looks like staff
ACTIVITY_FULL = 0.05    # per-frame normalized centroid displacement that maps to activity=1.0
HEATMAP_N = 8           # heatmap grid resolution (N x N)

# Placeholder zones as fractions of the frame (x, y) — replace with real geometry
# via a zone-drawing pass over the actual camera framing. Each is a polygon of
# normalized (x, y) corners. For the people-walking demo clip these just slice the
# frame into four vertical bands so the funnel/occupancy logic has something to chew.
ZONE_POLYS_NORM = {
    Zone.ENTRY: [(0.0, 0.0), (0.25, 0.0), (0.25, 1.0), (0.0, 1.0)],
    Zone.QUEUE: [(0.25, 0.0), (0.5, 0.0), (0.5, 1.0), (0.25, 1.0)],
    Zone.COUNTER: [(0.5, 0.0), (0.75, 0.0), (0.75, 1.0), (0.5, 1.0)],
    Zone.SEATING: [(0.75, 0.0), (1.0, 0.0), (1.0, 1.0), (0.75, 1.0)],
}


def _blur_faces_inplace(frame, det, w: int, h: int) -> None:
    """Ethics hook: blur the top ~30% (head region) of each detected person box so
    no recognizable face ever leaves this process. Cheap stand-in for a dedicated
    face detector — good enough for the privacy demo, and operates in-place."""
    import cv2

    if det.xyxy is None:
        return
    for x1, y1, x2, y2 in det.xyxy:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        head_h = int((y2 - y1) * 0.3)
        hx1, hy1 = max(0, x1), max(0, y1)
        hx2, hy2 = min(w, x2), min(h, y1 + head_h)
        if hx2 <= hx1 or hy2 <= hy1:
            continue
        roi = frame[hy1:hy2, hx1:hx2]
        if roi.size:
            frame[hy1:hy2, hx1:hx2] = cv2.GaussianBlur(roi, (0, 0), 12)


# Zone draw colors (BGR) — kept visually consistent with the dashboard palette.
ZONE_DRAW_COLORS = {
    Zone.ENTRY: (120, 120, 120),
    Zone.QUEUE: (224, 182, 111),   # cool blue-ish
    Zone.COUNTER: (65, 164, 217),  # gold
    Zone.SEATING: (160, 200, 120), # teal-green
}


def _annotate_frame(frame, det, w: int, h: int):
    """Draw translucent zone polygons + person boxes/ids onto a COPY of the frame,
    so the streamed video carries the CCTV-style overlay (the dashboard just
    displays it). Returns the annotated frame."""
    import cv2
    import numpy as np

    out = frame.copy()
    overlay = out.copy()
    for z, poly in ZONE_POLYS_NORM.items():
        pts = np.array([(int(x * w), int(y * h)) for x, y in poly], dtype=np.int32)
        color = ZONE_DRAW_COLORS.get(z, (120, 120, 120))
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(out, [pts], True, color, 2)
        cx = int(min(p[0] for p in poly) * w) + 8
        cy = int(min(p[1] for p in poly) * h) + 22
        cv2.putText(out, z.value.upper(), (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.addWeighted(overlay, 0.18, out, 0.82, 0, out)

    if det.xyxy is not None:
        for i in range(len(det)):
            x1, y1, x2, y2 = (int(v) for v in det.xyxy[i])
            tid = int(det.tracker_id[i]) if det.tracker_id is not None else -1
            cv2.rectangle(out, (x1, y1), (x2, y2), (90, 220, 120), 2)
            label = f"#{tid}"
            cv2.putText(out, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 220, 120), 2)
    return out


class TrackState:
    """Per-tracker funnel/dwell/activity bookkeeping. tracker_id is ephemeral."""

    __slots__ = (
        "first_t", "zone", "zone_since", "counter_dwell", "last_center",
        "visited", "entered", "approached", "ordered", "seated", "abandoned",
        "role",
    )

    def __init__(self, t: float, center):
        self.first_t = t
        self.zone = Zone.OFF
        self.zone_since = t
        self.counter_dwell = 0.0
        self.last_center = center
        self.visited: set[Zone] = set()
        # funnel flags (each customer counted at most once per stage)
        self.entered = False
        self.approached = False
        self.ordered = False
        self.seated = False
        self.abandoned = False
        self.role = Role.UNKNOWN


class Pipeline:
    """Stateful scene processor: zones, dwell, funnel state machine, heatmap."""

    def __init__(self, w: int, h: int):
        import numpy as np
        import supervision as sv

        self.w, self.h = w, h
        self.zones = {
            z: sv.PolygonZone(
                polygon=np.array([(int(x * w), int(y * h)) for x, y in poly]),
                triggering_anchors=[sv.Position.BOTTOM_CENTER],
            )
            for z, poly in ZONE_POLYS_NORM.items()
        }
        self.tracks: dict[int, TrackState] = {}
        self.funnel = Funnel()
        # cumulative dwell-density heatmap (seconds spent per cell)
        self.heat = [[0.0] * HEATMAP_N for _ in range(HEATMAP_N)]

    def _zone_of(self, single) -> Zone:
        for z, pz in self.zones.items():
            if pz.trigger(single).any():
                return z
        return Zone.OFF

    def _on_zone_change(self, st: TrackState, new_zone: Zone, t: float) -> None:
        """Advance the conversion funnel on a zone transition."""
        old = st.zone
        # abandoned: was queueing, leaves to anywhere but the counter, never ordered
        if (
            old == Zone.QUEUE
            and new_zone not in (Zone.COUNTER, Zone.QUEUE)
            and Zone.COUNTER not in st.visited
            and not st.ordered
            and not st.abandoned
        ):
            st.abandoned = True
            self.funnel.abandoned += 1
        st.zone = new_zone
        st.zone_since = t
        st.visited.add(new_zone)
        # approached: reached the queue or counter
        if new_zone in (Zone.QUEUE, Zone.COUNTER) and not st.approached:
            st.approached = True
            self.funnel.approached += 1
        # seated
        if new_zone == Zone.SEATING and not st.seated:
            st.seated = True
            self.funnel.seated += 1

    def process(self, det, t: float, dt: float):
        """Update state from one tracked-detection set; return SceneEvent fields."""
        import numpy as np

        tracks: list[Track] = []
        occupancy = 0
        activities: list[float] = []
        n = len(det)
        for i in range(n):
            tid = int(det.tracker_id[i]) if det.tracker_id is not None else -(i + 1)
            x1, y1, x2, y2 = (float(v) for v in det.xyxy[i])
            cx = (x1 + x2) / 2.0
            by = y2  # bottom-center y (feet) — the anchor we trigger zones on
            center = (cx, by)

            st = self.tracks.get(tid)
            if st is None:
                st = TrackState(t, center)
                self.tracks[tid] = st
                if not st.entered:
                    st.entered = True
                    self.funnel.entered += 1

            zone = self._zone_of(det[i : i + 1])
            if zone != st.zone:
                self._on_zone_change(st, zone, t)

            # counter dwell -> ordered (purchase proxy)
            if zone == Zone.COUNTER:
                st.counter_dwell += dt
                if st.counter_dwell >= ORDER_DWELL_S and not st.ordered:
                    st.ordered = True
                    self.funnel.ordered += 1
                # someone living behind the counter looks like staff, not a customer
                if st.counter_dwell >= STAFF_DWELL_S:
                    st.role = Role.STAFF
                elif st.role == Role.UNKNOWN:
                    st.role = Role.CUSTOMER
            elif st.role == Role.UNKNOWN and st.entered:
                st.role = Role.CUSTOMER

            # movement-based activity score (0..1)
            dx = (center[0] - st.last_center[0]) / self.w
            dy = (center[1] - st.last_center[1]) / self.h
            disp = (dx * dx + dy * dy) ** 0.5
            activity = min(1.0, disp / ACTIVITY_FULL) if dt > 0 else 0.0
            st.last_center = center
            activities.append(activity)

            # heatmap accumulation at the feet position
            gc = min(HEATMAP_N - 1, max(0, int((cx / self.w) * HEATMAP_N)))
            gr = min(HEATMAP_N - 1, max(0, int((by / self.h) * HEATMAP_N)))
            self.heat[gr][gc] += dt

            if zone in (Zone.QUEUE, Zone.COUNTER, Zone.SEATING):
                occupancy += 1

            tracks.append(
                Track(
                    id=tid,
                    role=st.role,
                    zone=zone,
                    dwell_s=round(t - st.zone_since, 1),
                    activity=round(activity, 2),
                    bbox=[x1 / self.w, y1 / self.h, x2 / self.w, y2 / self.h],
                )
            )

        # staff_productivity: anonymized aggregate movement of staff if any, else all
        staff_act = [
            a for a, tr in zip(activities, tracks) if tr.role == Role.STAFF
        ]
        pool = staff_act if staff_act else activities
        productivity = round(sum(pool) / len(pool), 2) if pool else 0.0

        # emit a normalized 0..1 heatmap snapshot (peak cell = 1.0)
        peak = max((c for row in self.heat for c in row), default=0.0)
        if peak > 0:
            grid = [[round(c / peak, 3) for c in row] for row in self.heat]
        else:
            grid = [[0.0] * HEATMAP_N for _ in range(HEATMAP_N)]

        return tracks, occupancy, productivity, grid


def _resolve_source(source: str):
    """Turn --source into something cv2.VideoCapture can open.

    - digit            -> webcam index (int)
    - youtube/page URL -> direct stream URL via yt-dlp (live HLS or VOD)
    - file path / direct media URL -> returned unchanged
    """
    if str(source).isdigit():
        return int(source)
    s = str(source)
    is_url = s.startswith(("http://", "https://"))
    is_direct = s.endswith((".m3u8", ".mp4", ".mov", ".mkv", ".webm"))
    if is_url and not is_direct:
        try:
            import yt_dlp

            opts = {"quiet": True, "skip_download": True, "format": "best[height<=720]/best"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(s, download=False)
            stream = info.get("url")
            if stream:
                print(f"[perception] resolved stream via yt-dlp (live={info.get('is_live')})")
                return stream
        except Exception as exc:
            print(f"[perception] yt-dlp resolve failed ({exc}); passing source as-is")
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Coffee perception pipeline")
    parser.add_argument(
        "--source",
        default="0",
        help="webcam index, video path, direct stream URL, or YouTube/livestream page URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print emitted SceneEvents as JSON to stdout instead of POSTing",
    )
    parser.add_argument(
        "--max-frames", type=int, default=0, help="stop after N frames (0 = no cap)"
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="do not POST annotated MJPEG frames to the backend (events only)",
    )
    parser.add_argument(
        "--stream-fps", type=float, default=10.0, help="annotated frame POST rate"
    )
    args = parser.parse_args()

    import cv2
    import supervision as sv
    from ultralytics import YOLO

    source = _resolve_source(args.source)
    model = YOLO("yolo11n.pt")
    tracker = sv.ByteTrack()

    # Use the FFMPEG backend for network streams (HLS/RTSP); default otherwise.
    cap = (
        cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        if isinstance(source, str) and source.startswith("http")
        else cv2.VideoCapture(source)
    )
    if not cap.isOpened():
        raise SystemExit(f"[perception] could not open source: {source!r}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 0:
        fps = 30.0

    pipe = Pipeline(w, h)

    client = None
    if not args.dry_run:
        import httpx

        client = httpx.Client(timeout=2.0)

    mode = "dry-run (stdout)" if args.dry_run else f"POST {BACKEND_URL}/ingest"
    print(
        f"[perception] source={source} {w}x{h}@{fps:.0f}fps emit/{EMIT_EVERY_S}s -> {mode}",
        flush=True,
    )

    stream_on = not args.dry_run and not args.no_stream
    stream_w = 720 if w > 720 else w  # downscale wide frames for a light payload
    frame_interval = 1.0 / args.stream_fps if args.stream_fps > 0 else 0.1

    frame_idx = 0
    last_emit_t = -1e9
    last_frame_t = -1e9
    wall_start = time.time()
    emitted = 0
    frames_sent = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        # video-relative timeline so dwell/funnel timing is realistic on a clip
        video_t = frame_idx / fps
        dt = 1.0 / fps

        result = model(frame, verbose=False)[0]
        det = sv.Detections.from_ultralytics(result)
        det = det[det.class_id == 0]  # person only
        det = tracker.update_with_detections(det)

        _blur_faces_inplace(frame, det, w, h)  # privacy: blur heads before bbox leaves

        tracks, occupancy, productivity, grid = pipe.process(det, video_t, dt)

        # Stream the annotated frame (zones + boxes baked in) to the backend.
        if stream_on and video_t - last_frame_t >= frame_interval:
            annotated = _annotate_frame(frame, det, w, h)
            if stream_w != w:
                annotated = cv2.resize(annotated, (stream_w, int(h * stream_w / w)))
            okj, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if okj:
                try:
                    client.post(
                        f"{BACKEND_URL}/frame",
                        content=buf.tobytes(),
                        headers={"Content-Type": "image/jpeg"},
                    )
                    frames_sent += 1
                except Exception:
                    pass  # don't let a dropped frame kill the pipeline
            last_frame_t = video_t

        if video_t - last_emit_t >= EMIT_EVERY_S:
            event = SceneEvent(
                ts=time.time(),
                tracks=tracks,
                occupancy=occupancy,
                queue_len=sum(1 for t in tracks if t.zone == Zone.QUEUE),
                funnel=pipe.funnel,
                cups_made=pipe.funnel.ordered,  # ordered == drinks proxy at counter
                heatmap_grid=grid,
                staff_productivity=productivity,
                source="perception",
            )
            if args.dry_run:
                print(event.model_dump_json(), flush=True)
            else:
                try:
                    client.post(f"{BACKEND_URL}/ingest", json=event.model_dump())
                except Exception as exc:
                    print(f"[perception] backend unreachable: {exc}", flush=True)
            last_emit_t = video_t
            emitted += 1

        if args.max_frames and frame_idx >= args.max_frames:
            break

    cap.release()
    if client is not None:
        client.close()
    elapsed = time.time() - wall_start
    eff_fps = frame_idx / elapsed if elapsed > 0 else 0.0
    print(
        f"[perception] done: {frame_idx} frames, {emitted} events, "
        f"{frames_sent} frames streamed, {eff_fps:.1f} fps effective",
        flush=True,
    )


if __name__ == "__main__":
    main()
