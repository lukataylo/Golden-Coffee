"""Perception spike — YOLO11 + supervision, emitting SceneEvents to the backend.

Starting point for P1. Built on roboflow/supervision (MIT): ByteTrack for stable
ids, PolygonZone for per-zone occupancy, a dwell timer per track id. Mirrors the
pattern in supervision's `examples/time_in_zone`.

Run:  python -m perception.run --source 0            # webcam
      python -m perception.run --source clips/cafe.mp4
Env:  BACKEND_URL

NOTE: zones below are placeholder normalized polygons — P1 should replace them with
a zone-drawing pass over the actual camera framing. Faces should be blurred before
any bbox leaves this process (ethics requirement).
"""
from __future__ import annotations

import argparse
import os
import time

import httpx

from shared.schemas import Funnel, Role, SceneEvent, Track, Zone

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
EMIT_EVERY_S = float(os.environ.get("PERCEPTION_EMIT_S", "1.0"))

# Placeholder zones as fractions of the frame (x, y) — replace with real geometry.
ZONE_POLYS_NORM = {
    Zone.ENTRY: [(0.0, 0.0), (0.25, 0.0), (0.25, 1.0), (0.0, 1.0)],
    Zone.QUEUE: [(0.25, 0.0), (0.5, 0.0), (0.5, 1.0), (0.25, 1.0)],
    Zone.COUNTER: [(0.5, 0.0), (0.75, 0.0), (0.75, 1.0), (0.5, 1.0)],
    Zone.SEATING: [(0.75, 0.0), (1.0, 0.0), (1.0, 1.0), (0.75, 1.0)],
}


def _blur_faces_inplace(frame):
    """Ethics: blur the top ~30% of each detected person box (head region).
    Cheap stand-in for a face detector — good enough for the privacy demo."""
    import cv2  # noqa

    # Real implementation lives in P1; kept as a hook so the contract is visible.
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="webcam index or video path")
    args = parser.parse_args()

    import cv2
    import numpy as np
    import supervision as sv
    from ultralytics import YOLO

    source = int(args.source) if args.source.isdigit() else args.source
    model = YOLO("yolo11n.pt")
    tracker = sv.ByteTrack()

    cap = cv2.VideoCapture(source)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720

    zones = {
        z: sv.PolygonZone(
            polygon=np.array([(int(x * w), int(y * h)) for x, y in poly]),
            triggering_anchors=[sv.Position.BOTTOM_CENTER],
        )
        for z, poly in ZONE_POLYS_NORM.items()
    }
    first_seen: dict[int, float] = {}  # tracker_id -> ts of first sight (dwell proxy)

    print(f"[perception] source={source} {w}x{h} — emitting every {EMIT_EVERY_S}s")
    last_emit = 0.0
    client = httpx.Client(timeout=2.0)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        _blur_faces_inplace(frame)

        result = model(frame, verbose=False)[0]
        det = sv.Detections.from_ultralytics(result)
        det = det[det.class_id == 0]  # person
        det = tracker.update_with_detections(det)

        now = time.time()
        tracks: list[Track] = []
        occupancy = 0
        for i in range(len(det)):
            tid = int(det.tracker_id[i]) if det.tracker_id is not None else -1
            first_seen.setdefault(tid, now)
            # which zone is this detection in?
            in_zone = Zone.OFF
            single = det[i : i + 1]
            for z, pz in zones.items():
                if pz.trigger(single).any():
                    in_zone = z
                    break
            if in_zone in (Zone.QUEUE, Zone.COUNTER, Zone.SEATING):
                occupancy += 1
            x1, y1, x2, y2 = det.xyxy[i]
            tracks.append(
                Track(
                    id=tid,
                    role=Role.UNKNOWN,
                    zone=in_zone,
                    dwell_s=round(now - first_seen[tid], 1),
                    bbox=[float(x1 / w), float(y1 / h), float(x2 / w), float(y2 / h)],
                )
            )

        if now - last_emit >= EMIT_EVERY_S:
            event = SceneEvent(
                ts=now,
                tracks=tracks,
                occupancy=occupancy,
                queue_len=sum(1 for t in tracks if t.zone == Zone.QUEUE),
                funnel=Funnel(),  # P1: derive from zone-transition history
                source="perception",
            )
            try:
                client.post(f"{BACKEND_URL}/ingest", json=event.model_dump())
            except Exception as exc:
                print(f"[perception] backend unreachable: {exc}")
            last_emit = now

    cap.release()


if __name__ == "__main__":
    main()
