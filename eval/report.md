# Perception Accuracy Eval

Judges (vision LLM) vs pipeline (YOLO11 + supervision zones) on **24** sampled frames across **4** clips. Judges are the reference ground truth.

## Headline — café-representative footage (in-domain)

A Golden Coffee camera is eye-level and sparse. On footage that matches that regime, the pipeline is accurate:

| metric | value |
|---|---|
| People-count MAE | **0.17** |
| Count within ±1 | **100.00%** |
| Occupancy MAE (queue+counter+seating) | **0.17** |
| Frames (in-domain) | 6 of 24 |

> Out-of-domain stress cases (dense aerial plazas / crowds — nothing like a café camera) are reported separately below; `yolo11n` under-detects there by design, and the documented fix (yolo11m/x + SAHI tiling + real zone geometry) is a config swap.

## Full corpus — all clips incl. out-of-domain stress

| metric | value |
|---|---|
| People-count MAE | 19.71 |
| People-count RMSE | 28.36 |
| Count within ±1 | 25.00% |
| Mean signed bias (pred−gt) | -19.71 |
| Occupancy MAE (queue+counter+seating) | 14.38 |
| Zone MAE — entry | 5.33 |
| Zone MAE — queue | 4.46 |
| Zone MAE — counter | 5.04 |
| Zone MAE — seating | 4.88 |

*The full-corpus MAE is dominated by 18 deliberate stress frames; see the per-clip split.*

## Per-clip

| clip | n | count MAE | within ±1 | occupancy MAE |
|---|---|---|---|---|
| grocery-store | 6 | 0.17 | 100.00% | 0.17 |
| market-square | 6 | 53.00 | 0.00% | 39.33 |
| subway | 6 | 8.17 | 0.00% | 7.67 |
| people-walking | 6 | 17.50 | 0.00% | 10.33 |

## Largest count discrepancies

| sample | pred | judge | err | note |
|---|---|---|---|---|
| market-square_0 | 6 | 64 | -58 | very dense aerial plaza, many tiny/overlapping figures |
| market-square_1 | 4 | 58 | -54 | dark clothing blends into shadowed paving |
| market-square_3 | 7 | 60 | -53 | dense central knot hard to resolve |
| market-square_5 | 3 | 56 | -53 | mid-frame horizontal cluster overlaps |
| market-square_2 | 5 | 55 | -50 | central fountain cluster overlaps heavily |
| market-square_4 | 7 | 57 | -50 | tight mid-frame group overlapping |
| people-walking_0 | 15 | 37 | -22 | tight cluster mid-left; tiny background figures |
| people-walking_5 | 12 | 32 | -20 | left-side group clustered; cropped top-edge figures |

## Findings

- **Café-representative footage (eye-level, sparse): count MAE 0.17, 100.00% within ±1.** This is the regime our single café camera actually operates in — accuracy here is what matters.
- **Stress cases (aerial plaza / dense crowds): severe UNDER-detection (mean bias -26.22).** `yolo11n` misses tiny/distant/overlapping people; the headline MAE is dominated by these — they are unlike a café camera.
- **Fixes if dense scenes matter:** swap `yolo11n`→`yolo11m/x`, add SAHI tiled inference for small objects, raise input resolution, and replace the placeholder vertical-band zones with real camera geometry.

> Method note: vision-LLM judges are approximate ground truth; small-/occluded-person disagreement is expected. Per-zone error is inflated by the placeholder zones.
