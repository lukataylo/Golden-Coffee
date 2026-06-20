"""Unit tests for the Comfort Index — the headline 0-100 'how it feels' number.

Pure, deterministic, stdlib-only. Guards the trapezoidal band curve, each pillar
scorer, partial-sensing renormalisation, the label thresholds, and that the
machine-readable COMFORT_SPEC stays in sync with the code that uses it.
"""
from __future__ import annotations

from shared import comfort as C


# ---- band: the trapezoidal comfort curve ----------------------------------
def test_band_plateaus_at_100_in_ideal_window():
    assert C.band(60, 42, 52, 66, 80) == 100.0
    assert C.band(52, 42, 52, 66, 80) == 100.0  # inclusive lower ideal
    assert C.band(66, 42, 52, 66, 80) == 100.0  # inclusive upper ideal


def test_band_zero_outside_hard_bounds():
    assert C.band(42, 42, 52, 66, 80) == 0.0
    assert C.band(80, 42, 52, 66, 80) == 0.0
    assert C.band(10, 42, 52, 66, 80) == 0.0
    assert C.band(200, 42, 52, 66, 80) == 0.0


def test_band_ramps_linearly_at_midpoints():
    # halfway up the lower ramp (47 is midway 42->52) => 50
    assert C.band(47, 42, 52, 66, 80) == 50.0
    # halfway down the upper ramp (73 is midway 66->80) => 50
    assert C.band(73, 42, 52, 66, 80) == 50.0


# ---- per-pillar scorers ----------------------------------------------------
def test_sound_none_without_reading():
    assert C.sound_score(None, None) is None


def test_sound_stress_subtracts():
    quiet_lively = C.sound_score(60, 0)       # perfect loudness, no stress
    stressed = C.sound_score(60, 100)         # same loudness, max stress
    assert quiet_lively == 100.0
    assert stressed == C.clamp(100 - 0.45 * 100)  # 55
    assert stressed < quiet_lively


def test_light_band_shifts_for_evening():
    # 40 is below the daytime ideal (44) but inside the evening ideal (30-52)
    assert C.light_score(40, hour=20) == 100.0
    assert C.light_score(40, hour=13) < 100.0


def test_air_blends_temp_and_humidity():
    # neutral temp alone => ~100
    assert round(C.air_score(C.NEUTRAL_TEMP_C)) == 100
    # adding bad humidity drags it down but not below the temp-only value's floor
    blended = C.air_score(C.NEUTRAL_TEMP_C, humidity_rh=90)
    assert blended < 100


# ---- aggregate: partial sensing renormalises -------------------------------
def test_partial_sensing_renormalises_over_present_pillars():
    # only sound present => overall equals the sound score (weights renormalise)
    b = C.comfort_index(sound_db=60, sound_stress=0)
    assert b.sound == 100 and b.overall == 100
    assert b.light is None and b.air is None


def test_no_signals_yields_zero_overall():
    b = C.comfort_index()
    assert b.overall == 0


def test_scent_excluded_from_overall_but_still_reported():
    # scent is retired from the weighted overall, but the pillar is still scored
    b = C.comfort_index(sound_db=60, sound_stress=0, scent_intensity=50)
    assert b.scent == 100        # reported
    assert b.overall == 100      # but did not change the sound-only overall


def test_labels_match_thresholds():
    assert C.label_for(90) == "Feels great"
    assert C.label_for(70) == "Comfortable"
    assert C.label_for(55) == "A little off"
    assert C.label_for(40) == "Could be cosier"


def test_daypart_flag():
    assert C.comfort_index(light_level=50, hour=20).daypart == "evening"
    assert C.comfort_index(light_level=50, hour=13).daypart == "day"


# ---- spec stays in sync with the implementation ----------------------------
def test_comfort_spec_matches_code():
    s = C.COMFORT_SPEC
    assert s["neutral_temp_c"] == C.NEUTRAL_TEMP_C
    assert s["weights"] == {"sound": C.W_SOUND, "light": C.W_LIGHT, "air": C.W_AIR}
    assert s["bands"]["sound_db"]["stress_weight"] == 0.45
