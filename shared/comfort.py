"""Coffee Steve — the Comfort Index, defined once, canonically.

The Comfort Index is the single number the product is built around: *how nice
does it feel to be in this room right now*, 0–100. It is a weighted blend of
four pillars, each itself 0–100:

    ┌─────────────┬────────┬───────────────────────────────────────────────┐
    │ Pillar      │ Weight │ Driven by (all measured from the room)         │
    ├─────────────┼────────┼───────────────────────────────────────────────┤
    │ Sound       │  0.40  │ mic loudness (dB SPL approx) + acoustic stress │
    │ Light       │  0.30  │ camera scene brightness (daypart-aware)        │
    │ Temperature │  0.30  │ the temperature we're holding the room at       │
    └─────────────┴────────┴───────────────────────────────────────────────┘

Why these weights: in hospitality research the *acoustic* environment is the
single biggest driver of how long guests stay and how they rate a room, so
Sound leads. Light and thermal comfort follow and are roughly equal.
(Scent was an earlier pillar; it's been retired — the index now tracks only
signals genuinely measured from the room. The `air` name is kept internally for
the Temperature pillar to avoid churning the schema.)

Each pillar uses a "comfort band": a plateau of 100 between an ideal low/high,
ramping linearly down to 0 at an outer low/high. A café isn't best at one exact
value — it's *comfortable across a band* and only degrades past the edges.

Missing signals never tank the score: the overall is re-normalised over the
weights of the pillars that actually have data, so a venue with no humidity
sensor or no mic still gets an honest index from what it can measure.

This module is pure-Python (no numpy / no heavy deps) so perception, the agent
and the backend can all import it. The dashboard mirrors the exact same
constants in JS — keep the two in sync (see COMFORT_SPEC at the bottom).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

NEUTRAL_TEMP_C = 20.5  # the thermal "comfort centre" the Air pillar measures against

# Pillar weights (must sum to 1.0). Three room-measured pillars:
#   Sound (mic), Light (camera), Temperature (the temp we hold the room at).
W_SOUND = 0.40
W_LIGHT = 0.30
W_AIR = 0.30   # "Temperature" pillar (kept the `air` name internally)
W_SCENT = 0.0  # scent retired from the index


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def band(x: float, lo: float, ideal_lo: float, ideal_hi: float, hi: float) -> float:
    """A trapezoidal comfort curve: 100 across [ideal_lo, ideal_hi], ramping
    linearly to 0 at `lo` (below) and `hi` (above). Outside [lo, hi] → 0."""
    if ideal_lo <= x <= ideal_hi:
        return 100.0
    if x < ideal_lo:
        if x <= lo:
            return 0.0
        return clamp(100.0 * (x - lo) / (ideal_lo - lo))
    # x > ideal_hi
    if x >= hi:
        return 0.0
    return clamp(100.0 * (hi - x) / (hi - ideal_hi))


# --- per-pillar scorers ----------------------------------------------------

def sound_score(db: Optional[float], stress: Optional[float]) -> Optional[float]:
    """Sound comfort from measured loudness (approx dB SPL) and acoustic stress
    (0–100). A lively-but-relaxed café sits ~52–66 dB; dead silence (<42) feels
    awkward and >80 is strained. Stress (choppiness / harshness / sustained
    over-loudness) subtracts up to ~45 pts on top of the raw loudness fit."""
    if db is None:
        return None
    loud = band(db, lo=42, ideal_lo=52, ideal_hi=66, hi=80)
    s = 0.0 if stress is None else clamp(stress)
    return clamp(loud - 0.45 * s)


def light_score(level: Optional[float], hour: Optional[int] = None) -> Optional[float]:
    """Light comfort from measured scene brightness (0–100, perceptual). The
    ideal band shifts with the daypart: brighter and crisp around midday, dim
    and cosy in the evening. Glare (>~90) and gloom (<~18) both read as
    uncomfortable."""
    if level is None:
        return None
    evening = hour is not None and (hour >= 18 or hour < 7)
    if evening:
        return band(level, lo=10, ideal_lo=30, ideal_hi=52, hi=82)
    return band(level, lo=18, ideal_lo=44, ideal_hi=70, hi=92)


def air_score(setpoint_c: Optional[float], humidity_rh: Optional[float] = None) -> Optional[float]:
    """Thermal/air comfort. Temperature is scored as deviation from the neutral
    centre (~20.5 °C; ±2 °C ≈ 82, ±4 °C ≈ 64). If an indoor humidity reading is
    present it's blended in (ideal ~38–56 % RH), weighted 30 %."""
    if setpoint_c is None and humidity_rh is None:
        return None
    parts: list[tuple[float, float]] = []
    if setpoint_c is not None:
        temp = clamp(100.0 - 9.0 * abs(setpoint_c - NEUTRAL_TEMP_C))
        parts.append((temp, 0.7))
    if humidity_rh is not None:
        hum = band(humidity_rh, lo=20, ideal_lo=38, ideal_hi=56, hi=75)
        parts.append((hum, 0.3))
    wsum = sum(w for _, w in parts)
    return sum(v * w for v, w in parts) / wsum if wsum else None


def scent_score(intensity: Optional[float]) -> Optional[float]:
    """Scent comfort from diffuser intensity (0–100). No sensor exists for
    ambient scent, so this reflects the set-point: a light, present aroma
    (~40–62 %) is ideal; off is merely fine, overpowering is not."""
    if intensity is None:
        return None
    return band(intensity, lo=0, ideal_lo=40, ideal_hi=62, hi=100)


# --- aggregate -------------------------------------------------------------

@dataclass
class ComfortBreakdown:
    overall: int
    sound: Optional[int]
    light: Optional[int]
    air: Optional[int]
    scent: Optional[int]
    label: str
    sound_db: Optional[float] = None
    sound_stress: Optional[float] = None
    light_level: Optional[float] = None
    daypart: str = "day"
    weights: dict = field(default_factory=lambda: {
        "sound": W_SOUND, "light": W_LIGHT, "air": W_AIR, "scent": W_SCENT,
    })

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "sound": self.sound,
            "light": self.light,
            "air": self.air,
            "scent": self.scent,
            "label": self.label,
            "sound_db": self.sound_db,
            "sound_stress": self.sound_stress,
            "light_level": self.light_level,
            "daypart": self.daypart,
            "weights": self.weights,
        }


def label_for(overall: float) -> str:
    if overall >= 85:
        return "Feels great"
    if overall >= 70:
        return "Comfortable"
    if overall >= 55:
        return "A little off"
    return "Could be cosier"


def comfort_index(
    *,
    sound_db: Optional[float] = None,
    sound_stress: Optional[float] = None,
    light_level: Optional[float] = None,
    setpoint_c: Optional[float] = None,
    humidity_rh: Optional[float] = None,
    scent_intensity: Optional[float] = None,
    hour: Optional[int] = None,
) -> ComfortBreakdown:
    """Compute the full Comfort Index from whatever signals are available.

    All inputs optional; the overall is re-normalised over the pillars that have
    data, so partial sensing still yields an honest number.
    """
    snd = sound_score(sound_db, sound_stress)
    lit = light_score(light_level, hour)
    air = air_score(setpoint_c, humidity_rh)
    scn = scent_score(scent_intensity)

    pillars = [(snd, W_SOUND), (lit, W_LIGHT), (air, W_AIR)]  # scent retired from the index
    present = [(v, w) for v, w in pillars if v is not None]
    wsum = sum(w for _, w in present)
    overall = round(sum(v * w for v, w in present) / wsum) if wsum else 0

    evening = hour is not None and (hour >= 18 or hour < 7)
    return ComfortBreakdown(
        overall=overall,
        sound=None if snd is None else round(snd),
        light=None if lit is None else round(lit),
        air=None if air is None else round(air),
        scent=None if scn is None else round(scn),
        label=label_for(overall),
        sound_db=None if sound_db is None else round(sound_db, 1),
        sound_stress=None if sound_stress is None else round(sound_stress, 1),
        light_level=None if light_level is None else round(light_level, 1),
        daypart="evening" if evening else "day",
    )


# A machine-readable mirror of the spec, so the dashboard JS and the docs can be
# checked against this one source of truth.
COMFORT_SPEC = {
    "weights": {"sound": W_SOUND, "light": W_LIGHT, "air": W_AIR},  # air == Temperature pillar
    "neutral_temp_c": NEUTRAL_TEMP_C,
    "bands": {
        "sound_db": {"lo": 42, "ideal_lo": 52, "ideal_hi": 66, "hi": 80, "stress_weight": 0.45},
        "light_day": {"lo": 18, "ideal_lo": 44, "ideal_hi": 70, "hi": 92},
        "light_evening": {"lo": 10, "ideal_lo": 30, "ideal_hi": 52, "hi": 82},
        "humidity_rh": {"lo": 20, "ideal_lo": 38, "ideal_hi": 56, "hi": 75},
        "scent_intensity": {"lo": 0, "ideal_lo": 40, "ideal_hi": 62, "hi": 100},
        "temp_falloff_per_c": 9.0,
    },
}
