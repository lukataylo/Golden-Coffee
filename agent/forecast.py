"""Footfall forecast — next-hour occupancy estimate from rolling hourly history.

Keeps a per-clock-hour rolling window of observed occupancy values and returns
a simple mean forecast for the next hour. When the next hour looks significantly
busier than the current state, the agent can issue a staffing heads-up before
the rush hits.

No network, no model — pure in-process state. Accurate enough for a same-day
"expect a rush at 12:00" suggestion after the first few rounds of data.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Optional

# Number of readings to keep per clock hour. At 1 scene/s this fills in ~2 min;
# enough for a meaningful average within a single session.
WINDOW_PER_HOUR = 120

# Only emit a staffing suggestion when the predicted next-hour occupancy is
# this many people higher than the current observed occupancy.
SURGE_THRESHOLD = 3


class FootfallForecast:
    def __init__(self, window: int = WINDOW_PER_HOUR) -> None:
        self._history: dict[int, deque] = defaultdict(lambda: deque(maxlen=window))

    def update(self, hour: int, occupancy: float) -> None:
        """Record one occupancy reading for the given clock hour."""
        self._history[hour].append(occupancy)

    def predict(self, next_hour: int) -> Optional[float]:
        """Return the mean predicted occupancy for next_hour, or None if too few data points."""
        buf = self._history.get(next_hour % 24)
        if not buf or len(buf) < 5:
            return None
        return round(sum(buf) / len(buf), 1)

    def staffing_note(self, current_occ: int, current_hour: int) -> Optional[str]:
        """Return a plain-English staffing suggestion if the next hour looks busier,
        or None if there's nothing to say (too little data, or no significant change)."""
        next_hour = (current_hour + 1) % 24
        predicted = self.predict(next_hour)
        if predicted is None:
            return None
        delta = predicted - current_occ
        if delta < SURGE_THRESHOLD:
            return None
        return (
            f"Heads up: next hour ({next_hour:02d}:xx) forecast ~{int(predicted)} guests "
            f"(↑{int(delta)} from now) — worth having an extra pair of hands ready."
        )
