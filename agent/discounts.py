"""Tiny time / occupancy-aware discount engine for Golden Coffee.

Given the wall-clock hour and the current room conditions, pick a promo line to
push to the in-store board. The goal is to smooth demand: lift conversion during
quiet hours, and steer busy-room long-dwellers toward takeaway to free up seats.

Pure functions only — no network, no model. Imported by `agent.policy`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


# --- tunables -------------------------------------------------------------
MORNING_END = 11        # < 11:00 is the morning rush window
LUNCH_START, LUNCH_END = 12, 14   # midday food window
AFTERNOON_LULL = 16     # 14:00-17:00 is the classic mid-afternoon trough
EVENING_START = 17


@dataclass(frozen=True)
class Discount:
    text: str
    kind: str          # "quiet" | "takeaway" | "generic"


def _hour(now: float | None) -> int:
    return time.localtime(now if now is not None else time.time()).tm_hour


def quiet_hour_discount(now: float | None = None) -> Discount:
    """Promo to lift conversion when the room is empty. Tailored to the daypart."""
    h = _hour(now)
    if h < MORNING_END:
        return Discount("Early bird: 20% off any pastry with a coffee", "quiet")
    if LUNCH_START <= h <= LUNCH_END:
        return Discount("Lunch lull: free cookie with any sandwich", "quiet")
    if LUNCH_END < h <= AFTERNOON_LULL:
        return Discount("Quiet hour: 2-for-1 filter coffee till 5pm", "quiet")
    if h >= EVENING_START:
        return Discount("Evening wind-down: 25% off cakes & pastries", "quiet")
    return Discount("Quiet hour: 20% off pastries", "quiet")


def takeaway_discount(now: float | None = None) -> Discount:
    """Promo to nudge a packed room's long-dwellers toward takeaway / turnover."""
    h = _hour(now)
    if h < MORNING_END:
        return Discount("Grab & go: 10% off any takeaway coffee", "takeaway")
    return Discount("On the move? 15% off your order to-go", "takeaway")
