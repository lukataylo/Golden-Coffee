"""Accuracy eval harness for the Golden Coffee perception pipeline.

Strategy: there is no ground-truth label set for café footage, so we use
**vision LLM judges as the reference**. This script does the deterministic half:
for each video it samples N frames, runs the SAME detector + zone logic the live
pipeline uses (YOLO11 person detection + supervision PolygonZones on BOTTOM_CENTER),
and records the pipeline's prediction (total people + per-zone counts). It writes:

  eval/frames/<id>_raw.jpg   — clean frame (handed to the judge subagents)
  eval/frames/<id>_pred.jpg  — annotated frame (zones + boxes; for the report)
  eval/manifest.json         — predictions per sample

Then judge subagents independently count people per zone on the *raw* frames, and
eval/score.py compares their counts (ground truth) against the predictions.

Run:  python -m eval.run_eval
"""
from __future__ import annotations

import json
from pathlib import Path

VIDEOS = [
    "clips/grocery-store.mp4",
    "clips/market-square.mp4",
    "clips/subway.mp4",
    "clips/people-walking.mp4",
]
SAMPLE_FRACTIONS = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85)  # spread across each clip
CONF = 0.30
JUDGE_W = 960  # downscale width for the frames handed to judges (token budget)


def main() -> None:
    import cv2
    import numpy as np
    import supervision as sv
    from ultralytics import YOLO

    from perception.run import ZONE_POLYS_NORM, _annotate_frame

    out = Path("eval")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    model = YOLO("yolo11n.pt")
    manifest = []

    for vid in VIDEOS:
        cap = cv2.VideoCapture(vid)
        if not cap.isOpened():
            print(f"[eval] skip (cannot open) {vid}")
            continue
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        zones = {
            z: sv.PolygonZone(
                polygon=np.array([(int(x * w), int(y * h)) for x, y in poly]),
                triggering_anchors=[sv.Position.BOTTOM_CENTER],
            )
            for z, poly in ZONE_POLYS_NORM.items()
        }
        name = Path(vid).stem
        idxs = (
            [max(0, int(total * f)) for f in SAMPLE_FRACTIONS]
            if total > 0
            else [i * 30 for i in range(len(SAMPLE_FRACTIONS))]
        )
        scale = JUDGE_W / w if w > JUDGE_W else 1.0
        for i, fidx in enumerate(idxs):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            ok, frame = cap.read()
            if not ok:
                continue
            det = sv.Detections.from_ultralytics(model(frame, verbose=False, conf=CONF)[0])
            det = det[det.class_id == 0]
            zone_counts = {z.value: int(pz.trigger(det).sum()) for z, pz in zones.items()}

            sid = f"{name}_{i}"
            raw_p = out / "frames" / f"{sid}_raw.jpg"
            ann_p = out / "frames" / f"{sid}_pred.jpg"
            disp = (
                cv2.resize(frame, (JUDGE_W, int(h * scale))) if scale != 1.0 else frame
            )
            cv2.imwrite(str(raw_p), disp, [cv2.IMWRITE_JPEG_QUALITY, 80])
            ann = _annotate_frame(frame, det, w, h)
            if scale != 1.0:
                ann = cv2.resize(ann, (JUDGE_W, int(h * scale)))
            cv2.imwrite(str(ann_p), ann, [cv2.IMWRITE_JPEG_QUALITY, 80])

            manifest.append(
                {
                    "id": sid,
                    "video": name,
                    "frame": fidx,
                    "raw": str(raw_p),
                    "annotated": str(ann_p),
                    "pred_count": int(len(det)),
                    "pred_zone_counts": zone_counts,
                }
            )
            print(f"[eval] {sid}: pred {len(det)} people {zone_counts}")
        cap.release()

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[eval] wrote {len(manifest)} samples -> eval/manifest.json")


if __name__ == "__main__":
    main()
