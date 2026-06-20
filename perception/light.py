"""Light sensing for the Comfort Index — straight from the camera frame.

The camera the venue already has is also a light meter. We read each frame's
luminance and turn it into:

  * **light_level (0–100, perceptual)** — how bright the room reads to a person.
    We take mean luma, normalise to 0..1, then apply a mild gamma so the curve
    tracks perceived brightness rather than raw sensor counts.

  * **light_lux (approx)** — a rough lux estimate for the dashboard. Webcam
    auto-exposure makes true lux impossible, so this is an order-of-magnitude
    perceptual mapping (dim café ~80 lx, bright ~600 lx), not a calibrated read.

  * **state** — "gloom" / "dim" / "comfortable" / "bright" / "glare", plus an
    over/under-exposure flag from the share of blown-out / crushed pixels, so we
    can tell "genuinely bright" from "camera clipping".

Uses the centre 80% of the frame (ignores dark borders / vignetting). Pure
function of a BGR frame; numpy only.
"""
from __future__ import annotations

from typing import Optional

GAMMA = 0.75  # <1 lifts midtones so the score tracks perceived, not linear, brightness


def measure_light(frame) -> dict:
    """frame: HxWx3 BGR uint8 (OpenCV). Returns a light snapshot dict."""
    import numpy as np

    h, w = frame.shape[:2]
    # centre crop (drop a 10% border) to avoid vignetting / dark edges
    y0, y1 = int(h * 0.1), int(h * 0.9)
    x0, x1 = int(w * 0.1), int(w * 0.9)
    roi = frame[y0:y1, x0:x1]

    # Rec.601 luma from BGR without a full cvtColor
    b = roi[:, :, 0].astype(np.float32)
    g = roi[:, :, 1].astype(np.float32)
    r = roi[:, :, 2].astype(np.float32)
    luma = 0.114 * b + 0.587 * g + 0.299 * r  # 0..255

    mean = float(luma.mean())
    norm = (mean / 255.0) ** GAMMA
    level = max(0.0, min(100.0, norm * 100.0))

    # exposure clipping: share of near-black and near-white pixels
    n = luma.size
    blown = float((luma >= 250).sum()) / n
    crushed = float((luma <= 5).sum()) / n
    clipping = blown > 0.12 or crushed > 0.4

    # rough perceptual lux (NOT calibrated) — log-ish spread over a café range
    lux = round(20.0 * (1.6 ** (level / 10.0)))

    if level < 22:
        state = "gloom"
    elif level < 40:
        state = "dim"
    elif level <= 74:
        state = "comfortable"
    elif level <= 88:
        state = "bright"
    else:
        state = "glare"

    return {
        "light_level": round(level, 1),
        "light_lux": int(lux),
        "light_state": state,
        "light_clipping": clipping,
    }
