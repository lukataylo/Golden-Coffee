"""The dashboard command bar (/ask) falls back to a keyword parser when no LLM
key is set — which is exactly the state of a live demo. Guard the common
phrasings so the command bar never silently no-ops on stage.
"""
from __future__ import annotations

import pytest

from backend.main import _ask_keyword

CASES = {
    # music volume — the words up/down/lower only mean volume with a music word
    "turn the music down": "set_music_volume",
    "turn the music up": "set_music_volume",
    "lower the music": "set_music_volume",
    "make it quieter": "set_music_volume",
    # lighting — light-aware up/down, plus the classic verbs
    "lower the lights": "set_lighting",
    "dim the lights": "set_lighting",
    "brighten up": "set_lighting",
    "lights up": "set_lighting",
    # temperature
    "make it warmer": "set_temperature",
    "turn down the heat": "set_temperature",
    "cool it down": "set_temperature",
    "it's stuffy in here": "set_temperature",
    # scent / staff / discount
    "freshen the air": "set_scent",
    "open a second till": "notify_staff",
    "give them a treat": "push_discount",
}


@pytest.mark.parametrize("query,expected", CASES.items())
def test_keyword_parser_resolves_common_commands(query: str, expected: str) -> None:
    parsed = _ask_keyword(query)
    assert parsed is not None, f"command bar no-opped on {query!r}"
    assert parsed["action"] == expected, f"{query!r} -> {parsed['action']} (want {expected})"


def test_keyword_parser_returns_none_on_gibberish() -> None:
    assert _ask_keyword("zzz qwerty nonsense") is None


def test_lights_and_music_dont_cross_wires() -> None:
    # "lower the lights" must not be hijacked by the volume branch, and
    # "lower the music" must not be hijacked by the lighting branch.
    assert _ask_keyword("lower the lights")["action"] == "set_lighting"
    assert _ask_keyword("lower the music")["action"] == "set_music_volume"
