"""Perception pipeline — YOLO11 + supervision, emitting SceneEvents.

Built on roboflow/supervision (MIT):
  YOLO('yolo11n.pt') -> sv.Detections.from_ultralytics -> filter person (class 0)
  -> sv.ByteTrack (stable ids) -> sv.PolygonZone per zone (occupancy)
  -> per-track dwell timers -> conversion-funnel state machine
  -> coarse dwell heatmap + movement-based staff-productivity proxy.

Privacy guarantees (all active by default; --privacy-mode tightens further):
  - MediaPipe face detection blurs actual detected faces (falls back to top-30%
    bbox proxy if MediaPipe is not installed).
  - Stale tracks are purged after TRACK_EXPIRY_S so dead IDs never accumulate.
  - --privacy-mode: strips all bboxes from emitted SceneEvents + adds Laplacian
    differential-privacy noise to the heatmap so individual paths cannot be
    reconstructed from the aggregate grid.
  - Federated emit thread posts only anonymised aggregate ratios (no tracks, no
    positions) to the federation server for cross-shop learning (Flock.io).

Run:
  python -m perception.run --source 0                       # webcam, POST to backend
  python -m perception.run --source clips/people-walking.mp4
  python -m perception.run --source clips/x.mp4 --dry-run --max-frames 60
  python -m perception.run --source 0 --privacy-mode        # full privacy demo

Env:
  BACKEND_URL        (default http://127.0.0.1:8000)
  PERCEPTION_EMIT_S  (default 1.0) — seconds of (video) time between emitted scenes
"""
from __future__ import annotations

import argparse
import json
import os
import time

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from shared.schemas import Funnel, Role, SceneEvent, Track, Zone

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
_TOKEN_HEADERS = {"X-Token": os.environ["INGEST_TOKEN"]} if os.environ.get("INGEST_TOKEN") else {}
EMIT_EVERY_S = float(os.environ.get("PERCEPTION_EMIT_S", "1.0"))

# --- Tunables ----------------------------------------------------------------
ORDER_DWELL_S = 4.0     # dwell at counter beyond this => "ordered" (purchase proxy)
STAFF_DWELL_S = 25.0    # a track living behind the counter this long looks like staff
ACTIVITY_FULL = 0.05    # per-frame normalized centroid displacement that maps to activity=1.0
HEATMAP_N = 8           # heatmap grid resolution (N x N)
TRACK_EXPIRY_S = 30.0   # purge a track if unseen for this many video-time seconds

# Default zones as fractions of the frame (x, y) — these vertical bands suit the
# people-walking demo clip. For a REAL camera, replace them with venue geometry:
#   python -m perception.run --preset counter_top --tables 6 --gen-zones zones.json
#   python -m perception.draw_zones --source <cam> --out zones.json   (GUI)
# then run with `--zones zones.json` (validated on load by perception.geometry).
# Each entry is a polygon of normalized (x, y) corners.
ZONE_POLYS_NORM = {
    Zone.ENTRY: [(0.0, 0.0), (0.25, 0.0), (0.25, 1.0), (0.0, 1.0)],
    Zone.QUEUE: [(0.25, 0.0), (0.5, 0.0), (0.5, 1.0), (0.25, 1.0)],
    Zone.COUNTER: [(0.5, 0.0), (0.75, 0.0), (0.75, 1.0), (0.5, 1.0)],
    Zone.SEATING: [(0.75, 0.0), (1.0, 0.0), (1.0, 1.0), (0.75, 1.0)],
}


_MP_MODEL_PATH = "face_detector.tflite"
_MP_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)


def _build_face_detector():
    """Return a (kind, detector) tuple for face blurring.

    Priority:
      1. MediaPipe Tasks API (mediapipe >= 0.10.13) — most accurate. Downloads
         a ~700 KB tflite model on first run; cached as face_detector.tflite.
      2. OpenCV Haar cascade — ships with cv2, no download needed.
      3. None — falls back to blurring the top-30% of each person bbox.
    """
    # 1. MediaPipe Tasks API
    try:
        import urllib.request
        import mediapipe as mp
        from mediapipe.tasks import python as _mp_python
        from mediapipe.tasks.python import vision as _mp_vision

        if not os.path.exists(_MP_MODEL_PATH):
            print(f"[perception] downloading MediaPipe face model (~700 KB) -> {_MP_MODEL_PATH}")
            urllib.request.urlretrieve(_MP_MODEL_URL, _MP_MODEL_PATH)

        base_opts = _mp_python.BaseOptions(model_asset_path=_MP_MODEL_PATH)
        opts = _mp_vision.FaceDetectorOptions(
            base_options=base_opts, min_detection_confidence=0.4
        )
        detector = _mp_vision.FaceDetector.create_from_options(opts)
        print("[perception] MediaPipe Tasks face detector active")
        return ("mp_tasks", detector)
    except Exception as exc:
        print(f"[perception] MediaPipe Tasks unavailable ({exc})")

    # 2. OpenCV Haar cascade
    try:
        import cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if not cascade.empty():
            print("[perception] OpenCV Haar cascade face detector active")
            return ("haar", cascade)
    except Exception as exc:
        print(f"[perception] Haar cascade unavailable ({exc})")

    print("[perception] using bbox-top-30% face blur fallback")
    return (None, None)


def _blur_faces_inplace(frame, det, w: int, h: int, face_detector=None) -> None:
    """Blur faces before any pixel leaves this process.

    face_detector is a (kind, obj) tuple from _build_face_detector(), or None.
    """
    import cv2

    kind, obj = face_detector if face_detector else (None, None)

    if kind == "mp_tasks":
        import mediapipe as mp
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = obj.detect(mp_img)
        for detection in result.detections:
            bb = detection.bounding_box
            fx1 = max(0, bb.origin_x)
            fy1 = max(0, bb.origin_y)
            fx2 = min(w, bb.origin_x + bb.width)
            fy2 = min(h, bb.origin_y + bb.height)
            roi = frame[fy1:fy2, fx1:fx2]
            if roi.size:
                frame[fy1:fy2, fx1:fx2] = cv2.GaussianBlur(roi, (0, 0), 15)
        return

    if kind == "haar":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = obj.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))
        for (fx, fy, fw, fh) in faces:
            roi = frame[fy:fy + fh, fx:fx + fw]
            if roi.size:
                frame[fy:fy + fh, fx:fx + fw] = cv2.GaussianBlur(roi, (0, 0), 15)
        return

    # Fallback: blur the top ~30% (head region) of each person bbox.
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


# --- Tables & cleaning zones (placeholder geometry; tune to the real camera) ---
# Named tables inside the seating area (x ~0.75..1.0).
TABLE_POLYS_NORM = {
    "T1": [(0.76, 0.18), (0.87, 0.18), (0.87, 0.50), (0.76, 0.50)],
    "T2": [(0.88, 0.18), (0.99, 0.18), (0.99, 0.50), (0.88, 0.50)],
    "T3": [(0.76, 0.55), (0.93, 0.55), (0.93, 0.93), (0.76, 0.93)],
}
# Zones whose cleaning cadence is tracked by usage + time (e.g. restroom).
CLEAN_POLYS_NORM = {
    "restroom": [(0.0, 0.55), (0.15, 0.55), (0.15, 1.0), (0.0, 1.0)],
}
WAIT_WARN_S = 120.0      # seated this long un-served => "waiting"
WAIT_CRIT_S = 300.0      # => "overdue"
CLEAN_DUE_USES = 8       # uses since last clean => "due"
CLEAN_OVERDUE_USES = 15  # => "overdue"
CLEAN_DUE_S = 1800.0     # 30 min since clean => "due"
CLEAN_OVERDUE_S = 3600.0  # 60 min => "overdue"


def load_geometry(path: str) -> None:
    """Override zone/table/cleaning polygons (normalized 0..1) from a JSON file,
    in place. Lets a track tune real camera geometry without touching code.
    Format: {"zones": {"entry": [[x,y],...]}, "tables": {"T1": [...]}, "cleaning": {...}}.
    """
    from perception.geometry import geometry_summary

    with open(path) as f:
        cfg = json.load(f)
    _apply_geometry(cfg)
    print(f"[perception] geometry from {path}: {geometry_summary(cfg)}", flush=True)


def _apply_geometry(cfg: dict) -> None:
    """Validate a geometry config and apply it to the module globals in place.

    Validates BEFORE mutating anything — bad geometry (out-of-frame coords,
    degenerate polygons, a missing zone) silently breaks every downstream metric,
    so fail loudly here. Warnings (e.g. a table outside seating) are printed.
    """
    from perception.geometry import assert_valid

    for w in assert_valid(cfg):
        print(f"[perception] geometry warning: {w}", flush=True)
    if "zones" in cfg:
        ZONE_POLYS_NORM.clear()
        for name, poly in cfg["zones"].items():
            ZONE_POLYS_NORM[Zone(name)] = [tuple(p) for p in poly]
    if "tables" in cfg:
        TABLE_POLYS_NORM.clear()
        TABLE_POLYS_NORM.update({k: [tuple(p) for p in v] for k, v in cfg["tables"].items()})
    if "cleaning" in cfg:
        CLEAN_POLYS_NORM.clear()
        CLEAN_POLYS_NORM.update({k: [tuple(p) for p in v] for k, v in cfg["cleaning"].items()})


def dump_geometry(path: str) -> None:
    """Write the current (default) geometry to JSON as a starting point to edit."""
    cfg = {
        "zones": {z.value: [list(p) for p in poly] for z, poly in ZONE_POLYS_NORM.items()},
        "tables": {k: [list(p) for p in v] for k, v in TABLE_POLYS_NORM.items()},
        "cleaning": {k: [list(p) for p in v] for k, v in CLEAN_POLYS_NORM.items()},
    }
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"[perception] wrote default geometry -> {path} (edit the normalized coords)")


def _point_in_poly(pt, poly) -> bool:
    """Ray-casting point-in-polygon on normalized (0..1) coords."""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _foot(track) -> tuple[float, float]:
    """Bottom-center of a track's normalized bbox (the floor contact point)."""
    b = track.bbox or [0, 0, 0, 0]
    return ((b[0] + b[2]) / 2.0, b[3])


class TableMonitor:
    """Per-table wait + cleaning state, and per-zone cleaning cadence.

    Wait: time a seated party has been un-served (since seated, or since a staff
    member was last seen at the table). Cleaning: a table goes dirty when a party
    leaves and is "bussed" when staff next visits; cleaning zones (restroom) track
    uses-since-clean + time-since-clean, reset when staff is seen there.
    """

    def __init__(self) -> None:
        self.t_state = {
            tid: {"occ_since": None, "staff_t": None, "clean_t": 0.0,
                  "uses": 0, "was_occ": False, "dirty": False}
            for tid in TABLE_POLYS_NORM
        }
        self.c_state = {
            cid: {"inside": set(), "uses": 0, "clean_t": 0.0}
            for cid in CLEAN_POLYS_NORM
        }

    def update(self, tracks, t: float):
        from shared.schemas import CleaningZone, Table

        tables = []
        for tid, poly in TABLE_POLYS_NORM.items():
            s = self.t_state[tid]
            party, staff_in = 0, False
            for tr in tracks:
                if tr.bbox and _point_in_poly(_foot(tr), poly):
                    if tr.role == Role.STAFF:
                        staff_in = True
                    else:
                        party += 1
            occupied = party > 0
            if occupied and not s["was_occ"]:        # new party seated
                s["occ_since"] = t
                s["uses"] += 1
                if s["dirty"]:                       # table reused -> treat as turned over
                    s["dirty"] = False
                    s["clean_t"] = t
            if not occupied and s["was_occ"]:        # party left -> needs bussing
                s["dirty"] = True
            s["was_occ"] = occupied
            if staff_in:                              # staff visit = served (+ bussed)
                s["staff_t"] = t
                if s["dirty"]:
                    s["dirty"] = False
                    s["clean_t"] = t
                    s["uses"] = 0
            if occupied and s["occ_since"] is not None:
                base = max(x for x in (s["occ_since"], s["staff_t"]) if x is not None)
                wait_s = t - base
                occ_s = t - s["occ_since"]
            else:
                wait_s = occ_s = 0.0
            status = (
                "empty" if not occupied
                else "overdue" if wait_s >= WAIT_CRIT_S
                else "waiting" if wait_s >= WAIT_WARN_S
                else "seated"
            )
            tables.append(Table(
                id=tid, occupied=occupied, party_size=party,
                occupied_s=round(occ_s, 1), wait_s=round(wait_s, 1), status=status,
                needs_cleaning=s["dirty"], since_clean_s=round(t - s["clean_t"], 1),
                uses_since_clean=s["uses"],
            ))

        cleaning = []
        for cid, poly in CLEAN_POLYS_NORM.items():
            s = self.c_state[cid]
            now_inside, staff_in = set(), False
            for tr in tracks:
                if tr.bbox and _point_in_poly(_foot(tr), poly):
                    now_inside.add(tr.id)
                    if tr.role == Role.STAFF:
                        staff_in = True
            s["uses"] += len(now_inside - s["inside"])  # new entries since last frame
            s["inside"] = now_inside
            if staff_in:                                 # staff present = cleaned
                s["uses"] = 0
                s["clean_t"] = t
            since = t - s["clean_t"]
            status = (
                "overdue" if (s["uses"] >= CLEAN_OVERDUE_USES or since >= CLEAN_OVERDUE_S)
                else "due" if (s["uses"] >= CLEAN_DUE_USES or since >= CLEAN_DUE_S)
                else "ok"
            )
            cleaning.append(CleaningZone(
                id=cid, uses_since_clean=s["uses"], since_clean_s=round(since, 1), status=status,
            ))
        return tables, cleaning


def _draw_tables(frame, tables, w: int, h: int):
    """Overlay table boxes colored by status, with the wait clock + cleaning flag."""
    import cv2
    import numpy as np

    color = {"empty": (120, 120, 120), "seated": (120, 200, 120),
             "waiting": (80, 180, 235), "overdue": (70, 70, 230)}
    by_id = {t.id: t for t in tables}
    for tid, poly in TABLE_POLYS_NORM.items():
        t = by_id.get(tid)
        status = t.status if t else "empty"
        col = color.get(status, (120, 120, 120))
        pts = np.array([(int(x * w), int(y * h)) for x, y in poly], dtype=np.int32)
        cv2.polylines(frame, [pts], True, col, 2)
        x0 = int(min(p[0] for p in poly) * w) + 4
        y0 = int(min(p[1] for p in poly) * h) + 18
        if t and t.occupied:
            label = f"{tid} {int(t.wait_s // 60)}:{int(t.wait_s % 60):02d}"
            if t.needs_cleaning:
                label += " !buss"
        else:
            label = f"{tid} empty"
        cv2.putText(frame, label, (x0, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
    return frame


class TrackState:
    """Per-tracker funnel/dwell/activity bookkeeping. tracker_id is ephemeral."""

    __slots__ = (
        "first_t", "zone", "zone_since", "counter_dwell", "last_center",
        "visited", "entered", "approached", "ordered", "seated", "abandoned",
        "role", "last_seen_t",
    )

    def __init__(self, t: float, center):
        self.first_t = t
        self.zone = Zone.OFF
        self.zone_since = t
        self.counter_dwell = 0.0
        self.last_center = center
        self.last_seen_t = t
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

    def __init__(self, w: int, h: int, privacy_mode: bool = False):
        import numpy as np
        import supervision as sv

        self.w, self.h = w, h
        self.privacy_mode = privacy_mode
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
        self.tablemon = TableMonitor()

    def _zone_of(self, single) -> Zone:
        for z, pz in self.zones.items():
            if pz.trigger(single).any():
                return z
        return Zone.OFF

    def _on_zone_change(self, st: TrackState, new_zone: Zone, t: float) -> None:
        """Advance the conversion funnel on a zone transition."""
        old = st.zone
        # abandoned: was queueing, leaves the line entirely (not to counter/queue
        # and not to a seat) without ever ordering. SEATING is excluded so a guest
        # who queues then sits isn't double-counted as abandoned + seated.
        if (
            old == Zone.QUEUE
            and new_zone not in (Zone.COUNTER, Zone.QUEUE, Zone.SEATING)
            and Zone.COUNTER not in st.visited
            and not st.ordered
            and not st.abandoned
        ):
            st.abandoned = True
            self.funnel.abandoned += 1
        # counter dwell is only a purchase proxy when CONTIGUOUS — reset on leaving.
        if old == Zone.COUNTER and new_zone != Zone.COUNTER:
            st.counter_dwell = 0.0
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
            st.last_seen_t = t

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
                    if st.role != Role.STAFF:
                        st.role = Role.STAFF
                        # Roll back this track's customer-funnel contributions — a
                        # barista parked at the counter must not inflate
                        # entered/approached/ordered (and thus cups_made).
                        if st.entered:
                            self.funnel.entered -= 1
                            st.entered = False
                        if st.approached:
                            self.funnel.approached -= 1
                            st.approached = False
                        if st.ordered:
                            self.funnel.ordered -= 1
                            st.ordered = False
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
                    # Fix 1: strip bbox in privacy mode — coordinates reveal
                    # individual positions even when video faces are blurred.
                    bbox=None if self.privacy_mode else [x1 / self.w, y1 / self.h, x2 / self.w, y2 / self.h],
                )
            )

        # Fix 3: purge tracks that haven't been seen for TRACK_EXPIRY_S so the
        # dict doesn't grow without bound across a long session.
        stale = [tid for tid, st in self.tracks.items() if t - st.last_seen_t > TRACK_EXPIRY_S]
        for tid in stale:
            del self.tracks[tid]

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

        # Fix 2: Laplacian differential-privacy noise on the heatmap in privacy
        # mode so individual movement paths can't be reconstructed from the grid.
        if self.privacy_mode and peak > 0:
            sensitivity = 1.0 / (HEATMAP_N * HEATMAP_N)
            noise = np.random.laplace(0.0, sensitivity, (HEATMAP_N, HEATMAP_N))
            grid = [
                [max(0.0, min(1.0, round(grid[r][c] + float(noise[r, c]), 3)))
                 for c in range(HEATMAP_N)]
                for r in range(HEATMAP_N)
            ]

        tables, cleaning = self.tablemon.update(tracks, t)

        return tracks, occupancy, productivity, grid, tables, cleaning


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
    parser.add_argument(
        "--model", default="yolo11n.pt",
        help="YOLO weights: yolo11n (fast) .. yolo11m/x (more accurate on small/dense people)",
    )
    parser.add_argument("--zones", help="load zone/table/cleaning geometry from a JSON file")
    parser.add_argument("--dump-zones", help="write the default geometry to this JSON path and exit")
    parser.add_argument(
        "--preset", help="generate realistic café geometry headlessly (no GUI): "
        "counter_top | counter_left | bands. Use with --gen-zones to save, or alone to run with it.")
    parser.add_argument("--gen-zones", help="with --preset: write the generated geometry here and exit")
    parser.add_argument("--tables", type=int, default=4, help="table count for --preset (default 4)")
    parser.add_argument(
        "--privacy-mode",
        action="store_true",
        help="strip bboxes from events, add DP noise to heatmap, skip video stream (Flock.io demo)",
    )
    args = parser.parse_args()

    if args.dump_zones:
        dump_geometry(args.dump_zones)
        return
    # Headless geometry authoring: --preset builds a believable layout with no camera
    # and no display. With --gen-zones we just write it and exit; otherwise we load it
    # into the running pipeline (still overridable by an explicit --zones file below).
    if args.preset:
        from perception.geometry import geometry_summary, preset as gen_preset
        cfg = gen_preset(args.preset, tables=args.tables)
        if args.gen_zones:
            with open(args.gen_zones, "w") as f:
                json.dump(cfg, f, indent=2)
            print(f"[perception] preset '{args.preset}': {geometry_summary(cfg)} -> {args.gen_zones} "
                  f"(load with: python -m perception.run --zones {args.gen_zones})")
            return
        _apply_geometry(cfg)
        print(f"[perception] preset '{args.preset}': {geometry_summary(cfg)} (in-memory)", flush=True)
    if args.zones:
        load_geometry(args.zones)

    import cv2
    import supervision as sv
    from ultralytics import YOLO

    source = _resolve_source(args.source)
    model = YOLO(args.model)
    tracker = sv.ByteTrack()

    # Fix 5: MediaPipe face detector (always attempted; falls back to bbox proxy).
    face_detector = _build_face_detector()

    # Use the FFMPEG backend for network streams (HLS/RTSP/RTMP); default otherwise.
    is_network = isinstance(source, str) and source.startswith(("http", "rtsp", "rtmp"))
    if is_network and source.startswith("rtsp"):
        # Force TCP transport so RTSP (e.g. Aqara G100) survives Wi-Fi packet loss
        # instead of tearing down the stream. Must be set before VideoCapture opens.
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000"
        )
    cap = (
        cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        if is_network
        else cv2.VideoCapture(source)
    )
    if not cap.isOpened():
        raise SystemExit(f"[perception] could not open source: {source!r}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 0:
        fps = 30.0

    pipe = Pipeline(w, h, privacy_mode=args.privacy_mode)
    if args.privacy_mode:
        print("[perception] --privacy-mode: bboxes stripped, heatmap DP-noised, video stream disabled")

    client = None
    if not args.dry_run:
        import httpx

        client = httpx.Client(timeout=2.0)

    # Fix 6: federated emit thread — posts aggregate ratios only (no tracks/bboxes)
    # to the federation server so cross-shop learning works without sharing raw data.
    if not args.dry_run:
        from perception.federated_emit import start as _fed_start
        _latest_scene: dict = {}
        _fed_start(lambda: _latest_scene)
    else:
        _latest_scene = {}

    mode = "dry-run (stdout)" if args.dry_run else f"POST {BACKEND_URL}/ingest"
    print(
        f"[perception] source={source} {w}x{h}@{fps:.0f}fps emit/{EMIT_EVERY_S}s -> {mode}",
        flush=True,
    )

    # In privacy mode, never stream annotated video — aggregate events only.
    stream_on = not args.dry_run and not args.no_stream and not args.privacy_mode
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

        _blur_faces_inplace(frame, det, w, h, face_detector)  # privacy: blur faces

        tracks, occupancy, productivity, grid, tables, cleaning = pipe.process(det, video_t, dt)

        # Stream face-blurred frame with person boxes only (no zone/table overlays).
        if stream_on and video_t - last_frame_t >= frame_interval:
            out = frame.copy()
            if det.xyxy is not None:
                for i in range(len(det)):
                    x1, y1, x2, y2 = (int(v) for v in det.xyxy[i])
                    tid = int(det.tracker_id[i]) if det.tracker_id is not None else -1
                    cv2.rectangle(out, (x1, y1), (x2, y2), (90, 220, 120), 2)
                    cv2.putText(out, f"#{tid}", (x1, max(14, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 220, 120), 2)
            if stream_w != w:
                out = cv2.resize(out, (stream_w, int(h * stream_w / w)))
            okj, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if okj:
                try:
                    client.post(
                        f"{BACKEND_URL}/frame",
                        content=buf.tobytes(),
                        headers={"Content-Type": "image/jpeg", **_TOKEN_HEADERS},
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
                tables=tables,
                cleaning=cleaning,
                source="perception",
            )
            if args.dry_run:
                print(event.model_dump_json(), flush=True)
            else:
                payload = event.model_dump()
                _latest_scene.update(payload)  # feed the federated emit thread
                try:
                    client.post(f"{BACKEND_URL}/ingest", json=payload, headers=_TOKEN_HEADERS)
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
