"""Discount board — the in-store promo surface the agent's push_discount() drives.

For the MVP this just records the active promo (the dashboard renders it from the
action feed). At the venue, point a spare screen/tablet at the dashboard's discount
panel, or extend this to hit a real digital-signage / POS / loyalty API.
"""
from __future__ import annotations

_active: dict | None = None


def push_discount(text: str) -> dict:
    global _active
    _active = {"text": text}
    print(f"[discount] now showing: {text}")
    return _active


def current() -> dict | None:
    return _active
