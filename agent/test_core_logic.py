"""Unit tests for the agent's pure-logic helpers: footfall forecast, the
time-aware discount engine, and the walk-off £-at-risk arithmetic in the policy.

Deterministic and offline (fixed clock), stdlib + the project only.
"""
from __future__ import annotations

import time

from agent.discounts import quiet_hour_discount, takeaway_discount
from agent.forecast import SURGE_THRESHOLD, FootfallForecast
from agent import policy


def ts_at(hour: int, minute: int = 0) -> float:
    return time.mktime((2026, 6, 20, hour, minute, 0, 0, 0, -1))


# ---- footfall forecast -----------------------------------------------------
def test_forecast_needs_minimum_data():
    fc = FootfallForecast()
    for _ in range(4):
        fc.update(12, 10)
    assert fc.predict(12) is None          # < 5 readings
    fc.update(12, 10)
    assert fc.predict(12) == 10.0          # 5th reading unlocks the mean


def test_forecast_predicts_rolling_mean():
    fc = FootfallForecast()
    for v in (4, 6, 8, 10, 12):
        fc.update(13, v)
    assert fc.predict(13) == 8.0


def test_staffing_note_fires_only_on_a_real_surge():
    fc = FootfallForecast()
    for _ in range(6):
        fc.update(13, 12)                  # next hour (13:00) historically busy
    # current hour 12, current occ 2 -> predicted 12 -> delta 10 >= threshold
    note = fc.staffing_note(current_occ=2, current_hour=12)
    assert note is not None and "next hour" in note
    # if we're already as busy as the forecast, no note
    assert fc.staffing_note(current_occ=12, current_hour=12) is None


def test_staffing_note_silent_below_threshold():
    fc = FootfallForecast()
    for _ in range(6):
        fc.update(13, 5)
    # predicted 5, current 5 -> delta 0 < SURGE_THRESHOLD
    assert SURGE_THRESHOLD > 0
    assert fc.staffing_note(current_occ=5, current_hour=12) is None


# ---- discount engine -------------------------------------------------------
def test_quiet_hour_discounts_are_daypart_aware():
    assert "Early bird" in quiet_hour_discount(ts_at(8)).text
    assert "Lunch" in quiet_hour_discount(ts_at(13)).text
    assert "Quiet hour" in quiet_hour_discount(ts_at(15)).text
    assert "Evening" in quiet_hour_discount(ts_at(19)).text


def test_discounts_are_typed():
    assert quiet_hour_discount(ts_at(8)).kind == "quiet"
    assert takeaway_discount(ts_at(8)).kind == "takeaway"


def test_takeaway_varies_by_daypart():
    assert "Grab & go" in takeaway_discount(ts_at(9)).text
    assert "to-go" in takeaway_discount(ts_at(15)).text


# ---- walk-off £-at-risk arithmetic ----------------------------------------
def test_walkoff_lost_gbp_is_abandons_times_ticket():
    st: dict = {}
    # first tick seeds the baseline (no alert), second tick rises -> alert + £
    policy.decide({"occupancy": 7, "queue_len": 1, "abandons": 4,
                   "avg_ticket_gbp": 5.0, "ts": ts_at(13)}, st)
    acts = policy.decide({"occupancy": 7, "queue_len": 1, "abandons": 10,
                          "avg_ticket_gbp": 5.0, "ts": ts_at(13, 5)}, st)
    wo = [a for a in acts if a.action == "notify_staff" and a.params.get("priority") == "urgent"]
    assert wo, "rising walk-offs should raise an urgent alert"
    assert wo[0].params["lost_gbp"] == 50.0          # 10 abandons x £5.00
    assert wo[0].params["abandons"] == 10
    assert st["lost_gbp_today"] == 50.0


def test_walkoff_silent_when_not_rising():
    st: dict = {}
    policy.decide({"occupancy": 7, "queue_len": 1, "abandons": 5,
                   "avg_ticket_gbp": 5.0, "ts": ts_at(13)}, st)
    acts = policy.decide({"occupancy": 7, "queue_len": 1, "abandons": 5,
                          "avg_ticket_gbp": 5.0, "ts": ts_at(13, 5)}, st)
    urgent = [a for a in acts if a.action == "notify_staff" and a.params.get("priority") == "urgent"]
    assert urgent == []                               # flat count -> no walk-off alert
