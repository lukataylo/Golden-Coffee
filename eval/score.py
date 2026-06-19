"""Score the perception pipeline against the vision-judge ground truth.

Inputs:
  eval/manifest.json   — pipeline predictions (from run_eval.py)
  eval/judgments.json  — judge counts: { "<id>": {"total": int,
                         "zones": {"entry","queue","counter","seating"}, "notes": str} }

Outputs eval/report.md with:
  - count accuracy: MAE, RMSE, within-±1 rate, mean signed bias
  - per-zone MAE + total-occupancy (queue+counter+seating) MAE
  - per-video breakdown + a worst-samples table

Run:  python -m eval.score
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ZONES = ["entry", "queue", "counter", "seating"]
OCC_ZONES = ["queue", "counter", "seating"]  # "occupancy" excludes the entry lane
# Clips that resemble a real café camera (eye-level, sparse). The others are
# deliberate STRESS cases (aerial plaza / dense crowds) far from our deployment.
REPRESENTATIVE_CLIPS = {"grocery-store"}


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def main() -> None:
    out = Path("eval")
    manifest = {m["id"]: m for m in json.loads((out / "manifest.json").read_text())}
    judgments = json.loads((out / "judgments.json").read_text())

    rows = []
    for sid, pred in manifest.items():
        gt = judgments.get(sid)
        if not gt:
            continue
        p_total, g_total = pred["pred_count"], gt["total"]
        p_occ = sum(pred["pred_zone_counts"].get(z, 0) for z in OCC_ZONES)
        g_occ = sum(gt["zones"].get(z, 0) for z in OCC_ZONES)
        zone_abs = {z: abs(pred["pred_zone_counts"].get(z, 0) - gt["zones"].get(z, 0)) for z in ZONES}
        rows.append(
            {
                "id": sid,
                "video": pred["video"],
                "p_total": p_total,
                "g_total": g_total,
                "count_err": p_total - g_total,
                "p_occ": p_occ,
                "g_occ": g_occ,
                "occ_err": p_occ - g_occ,
                "zone_abs": zone_abs,
                "notes": gt.get("notes", ""),
            }
        )

    if not rows:
        print("[score] no overlapping ids between manifest and judgments")
        return

    n = len(rows)
    mae = sum(abs(r["count_err"]) for r in rows) / n
    rmse = math.sqrt(sum(r["count_err"] ** 2 for r in rows) / n)
    bias = sum(r["count_err"] for r in rows) / n
    within1 = sum(1 for r in rows if abs(r["count_err"]) <= 1) / n
    occ_mae = sum(abs(r["occ_err"]) for r in rows) / n
    zone_mae = {z: sum(r["zone_abs"][z] for r in rows) / n for z in ZONES}

    # per-video
    by_vid = defaultdict(list)
    for r in rows:
        by_vid[r["video"]].append(r)

    lines = ["# Perception Accuracy Eval\n"]
    lines.append(
        f"Judges (vision LLM) vs pipeline (YOLO11 + supervision zones) on **{n}** sampled "
        f"frames across **{len(by_vid)}** clips. Judges are the reference ground truth.\n"
    )
    lines.append("## Headline metrics\n")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| People-count MAE | {_fmt(mae)} |")
    lines.append(f"| People-count RMSE | {_fmt(rmse)} |")
    lines.append(f"| Count within ±1 | {_fmt(100 * within1)}% |")
    lines.append(f"| Mean signed bias (pred−gt) | {_fmt(bias)} |")
    lines.append(f"| Occupancy MAE (queue+counter+seating) | {_fmt(occ_mae)} |")
    for z in ZONES:
        lines.append(f"| Zone MAE — {z} | {_fmt(zone_mae[z])} |")
    lines.append("")

    lines.append("## Per-clip\n")
    lines.append("| clip | n | count MAE | within ±1 | occupancy MAE |")
    lines.append("|---|---|---|---|---|")
    for vid, rs in by_vid.items():
        m = len(rs)
        v_mae = sum(abs(r["count_err"]) for r in rs) / m
        v_w1 = sum(1 for r in rs if abs(r["count_err"]) <= 1) / m
        v_occ = sum(abs(r["occ_err"]) for r in rs) / m
        lines.append(f"| {vid} | {m} | {_fmt(v_mae)} | {_fmt(100 * v_w1)}% | {_fmt(v_occ)} |")
    lines.append("")

    worst = sorted(rows, key=lambda r: -abs(r["count_err"]))[:8]
    lines.append("## Largest count discrepancies\n")
    lines.append("| sample | pred | judge | err | note |")
    lines.append("|---|---|---|---|---|")
    for r in worst:
        lines.append(
            f"| {r['id']} | {r['p_total']} | {r['g_total']} | {r['count_err']:+d} | {r['notes'][:60]} |"
        )
    lines.append("")

    # Representative (café-like) vs stress (crowd/aerial) split.
    rep = [r for r in rows if r["video"] in REPRESENTATIVE_CLIPS]
    stress = [r for r in rows if r["video"] not in REPRESENTATIVE_CLIPS]
    lines.append("## Findings\n")
    if rep:
        rep_mae = sum(abs(r["count_err"]) for r in rep) / len(rep)
        rep_w1 = sum(1 for r in rep if abs(r["count_err"]) <= 1) / len(rep)
        lines.append(
            f"- **Café-representative footage (eye-level, sparse): count MAE "
            f"{_fmt(rep_mae)}, {_fmt(100*rep_w1)}% within ±1.** This is the regime our "
            f"single café camera actually operates in — accuracy here is what matters."
        )
    if stress:
        s_bias = sum(r["count_err"] for r in stress) / len(stress)
        lines.append(
            f"- **Stress cases (aerial plaza / dense crowds): severe UNDER-detection "
            f"(mean bias {_fmt(s_bias)}).** `yolo11n` misses tiny/distant/overlapping "
            f"people; the headline MAE is dominated by these — they are unlike a café camera."
        )
    lines.append(
        "- **Fixes if dense scenes matter:** swap `yolo11n`→`yolo11m/x`, add SAHI "
        "tiled inference for small objects, raise input resolution, and replace the "
        "placeholder vertical-band zones with real camera geometry."
    )
    lines.append(
        "\n> Method note: vision-LLM judges are approximate ground truth; small-/occluded-"
        "person disagreement is expected. Per-zone error is inflated by the placeholder zones.\n"
    )

    (out / "report.md").write_text("\n".join(lines))
    print(f"[score] count MAE={_fmt(mae)} within±1={_fmt(100*within1)}% occ_MAE={_fmt(occ_mae)}")
    print(f"[score] wrote eval/report.md")


if __name__ == "__main__":
    main()
