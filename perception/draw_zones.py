"""Interactive zone-drawing tool — define real camera geometry in ~2 minutes.

Grabs one frame from any source (webcam / file / YouTube), lets you click polygon
points for each named region, and writes a `zones.json` that `perception.run --zones`
loads. This is the "real camera geometry" setup step (the biggest accuracy win in
the eval): replace the placeholder vertical bands with regions that match the venue.

Run:  python -m perception.draw_zones --source 0 --out zones.json
      python -m perception.draw_zones --source clips/grocery-store.mp4 --tables 6
      python -m perception.draw_zones --source 0 --load zones.json   # edit existing

No display? Skip this and generate geometry headlessly instead:
      python -m perception.run --preset counter_top --tables 6 --gen-zones zones.json

Controls (in the window):
  left-click  add a point to the current region
  n / p       next / previous region
  c           clear the current region's points
  u           undo last point
  s           save -> --out and quit (only if it passes validation)
  q / Esc     quit without saving

Regions are drawn in this order (categorised automatically on save):
  entry, queue, counter, seating  -> "zones"
  T1..Tn (--tables n)             -> "tables"
  restroom                        -> "cleaning"
Saving runs the geometry validator, so a bad layout is caught before it ships.
"""
from __future__ import annotations

import argparse
import json

from perception.run import _resolve_source


def build_slots(n_tables: int = 3, extra: list[str] | None = None) -> list[tuple[str, str]]:
    """The ordered (label, category) regions to draw. `n_tables` controls how many
    tables (T1..Tn); `extra` adds any labels found in a loaded file so editing an
    existing zones.json never drops regions it didn't know about."""
    slots = [("entry", "zones"), ("queue", "zones"), ("counter", "zones"), ("seating", "zones")]
    slots += [(f"T{i}", "tables") for i in range(1, max(0, n_tables) + 1)]
    slots += [("restroom", "cleaning")]
    known = {s[0] for s in slots}
    cat_for = {"zones": "zones", "tables": "tables", "cleaning": "cleaning"}
    for label, cat in (extra or []):
        if label not in known:
            slots.append((label, cat_for.get(cat, "zones")))
            known.add(label)
    return slots


def build_geometry(points_by_label: dict[str, list[tuple[int, int]]], w: int, h: int,
                   slots: list[tuple[str, str]] | None = None) -> dict:
    """Turn pixel polygons into the normalized {zones,tables,cleaning} JSON shape.
    Only regions with >= 3 points are included."""
    out: dict[str, dict] = {"zones": {}, "tables": {}, "cleaning": {}}
    cat = dict(slots or build_slots())
    for label, pts in points_by_label.items():
        if len(pts) < 3:
            continue
        norm = [[round(x / w, 4), round(y / h, 4)] for (x, y) in pts]
        out[cat.get(label, "zones")][label] = norm
    return out


def save_geometry(points_by_label: dict, w: int, h: int, path: str,
                  slots: list[tuple[str, str]] | None = None) -> dict:
    from perception.geometry import validate_geometry

    geo = build_geometry(points_by_label, w, h, slots)
    # Validate what we're about to write so mistakes surface here, not at runtime.
    errors, warnings = validate_geometry(geo)
    for w_ in warnings:
        print(f"[draw_zones] warning: {w_}")
    if errors:
        print(f"[draw_zones] NOT saved — {len(errors)} problem(s) to fix first:")
        for e in errors:
            print(f"   - {e}")
        return None
    with open(path, "w") as f:
        json.dump(geo, f, indent=2)
    n = sum(len(v) for v in geo.values())
    print(f"[draw_zones] wrote {n} regions -> {path} "
          f"(load with: python -m perception.run --zones {path})")
    return geo


def _load_points(path: str, w: int, h: int) -> tuple[dict[str, list], list[tuple[str, str]]]:
    """Read an existing zones.json into pixel points (to edit), plus its label slots."""
    with open(path) as f:
        cfg = json.load(f)
    pts: dict[str, list] = {}
    extra: list[tuple[str, str]] = []
    for cat in ("zones", "tables", "cleaning"):
        for label, poly in (cfg.get(cat) or {}).items():
            pts[label] = [(int(x * w), int(y * h)) for x, y in poly]
            extra.append((label, cat))
    return pts, extra


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw zone/table/cleaning geometry")
    parser.add_argument("--source", default="0", help="webcam index / file / stream URL")
    parser.add_argument("--out", default="zones.json", help="output JSON path")
    parser.add_argument("--tables", type=int, default=3, help="number of tables to draw (T1..Tn)")
    parser.add_argument("--load", help="prefill from an existing zones.json to edit it")
    args = parser.parse_args()

    import cv2

    src = _resolve_source(args.source)
    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG) if isinstance(src, str) and src.startswith("http") else cv2.VideoCapture(src)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"[draw_zones] could not read a frame from {args.source!r}")
    h, w = frame.shape[:2]

    loaded_pts: dict[str, list] = {}
    extra: list[tuple[str, str]] = []
    if args.load:
        loaded_pts, extra = _load_points(args.load, w, h)
        print(f"[draw_zones] editing {len(loaded_pts)} region(s) from {args.load}")
    slots = build_slots(args.tables, extra)

    points: dict[str, list] = {label: loaded_pts.get(label, []) for label, _ in slots}
    idx = {"i": 0}

    def cur() -> str:
        return slots[idx["i"]][0]

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points[cur()].append((x, y))

    win = "Coffee Steve — draw zones"
    try:
        cv2.namedWindow(win)
        cv2.setMouseCallback(win, on_mouse)
    except Exception as exc:
        raise SystemExit(f"[draw_zones] no display available ({exc}); run on a machine with a GUI")

    import numpy as np

    print("[draw_zones] click points; n/p switch region, c clear, u undo, s save, q quit")
    while True:
        disp = frame.copy()
        for label, _ in slots:
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
            idx["i"] = (idx["i"] + 1) % len(slots)
        elif k == ord("p"):
            idx["i"] = (idx["i"] - 1) % len(slots)
        elif k == ord("c"):
            points[cur()].clear()
        elif k == ord("u") and points[cur()]:
            points[cur()].pop()
        elif k == ord("s"):
            if save_geometry(points, w, h, args.out, slots) is not None:
                break  # only exit once it actually saved (passed validation)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
