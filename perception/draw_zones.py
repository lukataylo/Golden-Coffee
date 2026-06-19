"""Interactive zone-drawing tool — define real camera geometry in ~2 minutes.

Grabs one frame from any source (webcam / file / YouTube), lets you click polygon
points for each named region, and writes a `zones.json` that `perception.run --zones`
loads. This is the "real camera geometry" setup step (the biggest accuracy win in
the eval): replace the placeholder vertical bands with regions that match the venue.

Run:  python -m perception.draw_zones --source 0 --out zones.json
      python -m perception.draw_zones --source clips/grocery-store.mp4

Controls (in the window):
  left-click  add a point to the current region
  n / p       next / previous region
  c           clear the current region's points
  u           undo last point
  s           save -> --out and quit
  q / Esc     quit without saving

Regions are drawn in this order (categorised automatically on save):
  entry, queue, counter, seating  -> "zones"
  T1, T2, T3                      -> "tables"
  restroom                        -> "cleaning"
"""
from __future__ import annotations

import argparse
import json

from perception.run import _resolve_source

# (label, category) — category maps into the zones.json structure load_geometry reads.
SLOTS = [
    ("entry", "zones"), ("queue", "zones"), ("counter", "zones"), ("seating", "zones"),
    ("T1", "tables"), ("T2", "tables"), ("T3", "tables"),
    ("restroom", "cleaning"),
]


def build_geometry(points_by_label: dict[str, list[tuple[int, int]]], w: int, h: int) -> dict:
    """Turn pixel polygons into the normalized {zones,tables,cleaning} JSON shape.
    Only regions with >= 3 points are included."""
    out: dict[str, dict] = {"zones": {}, "tables": {}, "cleaning": {}}
    cat = dict(SLOTS)
    for label, pts in points_by_label.items():
        if len(pts) < 3:
            continue
        norm = [[round(x / w, 4), round(y / h, 4)] for (x, y) in pts]
        out[cat.get(label, "zones")][label] = norm
    return out


def save_geometry(points_by_label: dict, w: int, h: int, path: str) -> dict:
    geo = build_geometry(points_by_label, w, h)
    with open(path, "w") as f:
        json.dump(geo, f, indent=2)
    n = sum(len(v) for v in geo.values())
    print(f"[draw_zones] wrote {n} regions -> {path} "
          f"(load with: python -m perception.run --zones {path})")
    return geo


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw zone/table/cleaning geometry")
    parser.add_argument("--source", default="0", help="webcam index / file / stream URL")
    parser.add_argument("--out", default="zones.json", help="output JSON path")
    args = parser.parse_args()

    import cv2

    src = _resolve_source(args.source)
    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG) if isinstance(src, str) and src.startswith("http") else cv2.VideoCapture(src)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"[draw_zones] could not read a frame from {args.source!r}")
    h, w = frame.shape[:2]

    points: dict[str, list] = {label: [] for label, _ in SLOTS}
    idx = {"i": 0}

    def cur() -> str:
        return SLOTS[idx["i"]][0]

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points[cur()].append((x, y))

    win = "Golden Coffee — draw zones"
    try:
        cv2.namedWindow(win)
        cv2.setMouseCallback(win, on_mouse)
    except Exception as exc:
        raise SystemExit(f"[draw_zones] no display available ({exc}); run on a machine with a GUI")

    import numpy as np

    print("[draw_zones] click points; n/p switch region, c clear, u undo, s save, q quit")
    while True:
        disp = frame.copy()
        for label, _ in SLOTS:
            pts = points[label]
            color = (90, 220, 120) if label == cur() else (120, 120, 120)
            for p in pts:
                cv2.circle(disp, p, 4, color, -1)
            if len(pts) >= 2:
                cv2.polylines(disp, [np.array(pts, np.int32)], len(pts) >= 3, color, 2)
        cv2.putText(disp, f"region: {cur()}  ({len(points[cur()])} pts)", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (65, 164, 217), 2)
        cv2.imshow(win, disp)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord("q"), 27):
            break
        elif k == ord("n"):
            idx["i"] = (idx["i"] + 1) % len(SLOTS)
        elif k == ord("p"):
            idx["i"] = (idx["i"] - 1) % len(SLOTS)
        elif k == ord("c"):
            points[cur()].clear()
        elif k == ord("u") and points[cur()]:
            points[cur()].pop()
        elif k == ord("s"):
            save_geometry(points, w, h, args.out)
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
