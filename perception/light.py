"""Light sensing for the Comfort Index — from the camera, made AE-robust.

The hard problem: consumer cameras (webcams, DroidCam) run **auto-exposure** and
**auto-gain**. They continuously push the average frame brightness toward mid-grey,
so raw mean luma barely moves with the actual room light — a genuinely dim room
gets brightened back up to ~50%, and a bright room gets pulled down. Mean luma
alone is therefore a poor light meter (this is why a dark room read "comfortable"
before).

We can't recover true lux without exposure metadata, but several cues *survive*
auto-exposure and let us infer the real light level much better:

  1. **Highlights** — real light sources and windows clip to white even after AE.
     A bright room has highlights; a dark room almost never does.
  2. **Contrast / dynamic range** — well-lit scenes keep a wide tonal range; a
     dark room that AE has lifted is flat (compressed range).
  3. **Sensor-gain noise** — to brighten a dark room the camera raises ISO/gain,
     which injects high-frequency noise. High noise in flat areas ⇒ low light.

So we start from a perceptual brightness (robust **median**, not mean, so a few
blown-out windows don't dominate), then *correct downward* when the contrast-collapse
+ noise signature says "this is an AE-lifted dark room", and *up* a little when
genuine highlights are present. Finally we smooth over time (EWMA) so AE hunting
doesn't make the reading flicker.

This is a **relative perceived-brightness index (0–100), not calibrated lux.**
For a given venue+camera it's stable and monotonic, which is what the Comfort
Index needs. A per-venue gain/bias can be set via env (GC_LIGHT_GAIN/GC_LIGHT_BIAS)
if you want to anchor it to a lux meter once.
"""
from __future__ import annotations

import os
from typing import Optional

GAMMA = 0.80          # <1 lifts midtones so the score tracks perceived brightness
_GAIN = float(os.environ.get("GC_LIGHT_GAIN", "1.0"))   # per-venue calibration
_BIAS = float(os.environ.get("GC_LIGHT_BIAS", "0.0"))


def _stats(frame) -> dict:
    """Per-frame luma statistics on a downsampled centre crop. Pure function."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.1), int(h * 0.9)
    x0, x1 = int(w * 0.1), int(w * 0.9)
    roi = frame[y0:y1, x0:x1]
    # downsample to ~320px wide with NEAREST so we PRESERVE sensor noise (AREA would
    # average it away — and gain-noise is one of our key low-light cues).
    rh, rw = roi.shape[:2]
    if rw > 320:
        scale = 320.0 / rw
        roi = cv2.resize(roi, (320, max(1, int(rh * scale))), interpolation=cv2.INTER_NEAREST)

    b = roi[:, :, 0].astype(np.float32)
    g = roi[:, :, 1].astype(np.float32)
    r = roi[:, :, 2].astype(np.float32)
    luma = 0.114 * b + 0.587 * g + 0.299 * r          # 0..255 (noisy)

    # Separate the two signals: blur = the true (denoised) scene; residual = gain noise.
    blur = cv2.GaussianBlur(luma, (0, 0), 1.6)
    noise = float(np.mean(np.abs(luma - blur))) / 255.0   # gain-noise proxy (rises in low light)

    # Scene structure is measured on the DENOISED image so noise doesn't inflate it.
    median = float(np.median(blur))
    p05, p95 = np.percentile(blur, [5, 95])
    contrast = float(p95 - p05) / 255.0                # 0..1 true dynamic range
    n = blur.size
    highlight = float((blur >= 235).sum()) / n         # windows / lamps (survive AE)
    shadow = float((blur <= 12).sum()) / n
    blown = float((blur >= 250).sum()) / n

    return {"median": median, "contrast": contrast, "highlight": highlight,
            "shadow": shadow, "blown": blown, "noise": noise}


def _score(st: dict) -> float:
    """Turn per-frame stats into an AE-robust 0–100 brightness."""

    def clip(x, lo=0.0, hi=1.0):
        return max(lo, min(hi, x))

    # 1) perceptual baseline from the robust median (not mean).
    percep = (st["median"] / 255.0) ** GAMMA * 100.0
    # 2) AE-lifted-dark signature: high gain noise AND collapsed contrast.
    ae_dark = clip(st["noise"] * 9.0) * clip(1.5 - st["contrast"] * 2.4)
    # 3) genuine brightness evidence: real highlights present.
    bright_ev = clip(st["highlight"] * 5.0)
    level = percep * (1.0 - 0.5 * ae_dark) + 16.0 * bright_ev
    level = level * _GAIN + _BIAS
    return max(0.0, min(100.0, level))


def _label(level: float, blown: float) -> tuple[str, bool]:
    clipping = blown > 0.12
    if level < 22:
        return "gloom", clipping
    if level < 40:
        return "dim", clipping
    if level <= 74:
        return "comfortable", clipping
    if level <= 88:
        return "bright", clipping
    return "glare", clipping


def measure_light(frame) -> dict:
    """Stateless one-shot light reading from a BGR frame (used for tests/dry-run).
    Prefer LightMeter for live use — it adds temporal smoothing."""
    st = _stats(frame)
    level = _score(st)
    state, clipping = _label(level, st["blown"])
    lux = round(20.0 * (1.6 ** (level / 10.0)))   # rough perceptual lux (uncalibrated)
    return {
        "light_level": round(level, 1),
        "light_lux": int(lux),
        "light_state": state,
        "light_clipping": clipping,
        "light_contrast": round(st["contrast"], 3),
        "light_noise": round(st["noise"], 4),
    }


class LightMeter:
    """Stateful light meter: EWMA-smooths the per-frame brightness so auto-exposure
    hunting doesn't make the Comfort Index flicker. `update(frame)` each tick."""

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha = alpha
        self._level: Optional[float] = None

    def update(self, frame) -> dict:
        st = _stats(frame)
        raw = _score(st)
        self._level = raw if self._level is None else (
            self.alpha * raw + (1.0 - self.alpha) * self._level
        )
        level = self._level
        state, clipping = _label(level, st["blown"])
        lux = round(20.0 * (1.6 ** (level / 10.0)))
        return {
            "light_level": round(level, 1),
            "light_lux": int(lux),
            "light_state": state,
            "light_clipping": clipping,
            "light_contrast": round(st["contrast"], 3),
            "light_noise": round(st["noise"], 4),
        }
