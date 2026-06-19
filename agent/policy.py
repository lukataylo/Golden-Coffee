"""Deterministic, rule-based ops policy for Golden Coffee.

`decide(scene, state) -> list[AgentAction]` is a *pure-ish* function: given a
SceneEvent (as a dict) and a mutable `state` dict it owns for debouncing, it
returns zero or more `AgentAction`s with plain-English rationales. No network,
no Claude, no API key — this is what makes the MVP run anywhere.

The agent (`agent.agent`) calls this on every scene by default. If an
ANTHROPIC_API_KEY is present it *may* layer Claude's judgement on top, but the
shop still works fully without it.

Encoded hospitality rules (see constants below for thresholds):
  * lull (low occupancy) or low staff activity -> raise music for energy
  * quiet room                                  -> push a quiet-hour discount
  * packed room w/ many long-dwellers           -> cool the room + push takeaway
  * queue building or abandons rising           -> alert staff to open a till
  * a seated "free rider" (very long dwell)      -> a gentle staff nudge

Run `python -m agent.policy` to exercise it offline against the synthetic
scenes in `shared.mock_events` (no backend, no key needed).
"""
from __future__ import annotations

import time

from shared.schemas import AgentAction

from agent.discounts import quiet_hour_discount, takeaway_discount

# --- thresholds (all named so they're easy to tune in a demo) -------------
LULL_OCCUPANCY = 3          # <= this many people => the room feels dead
LOW_PRODUCTIVITY = 0.45     # staff activity below this => energy is flagging
HIGH_OCCUPANCY = 8          # >= this => the room is packed
LONG_DWELL_S = 600          # a seated track over this is "camping" (10 min)
FREE_RIDE_DWELL_S = 780     # very long dwell + idle => likely a free rider
LOW_ACTIVITY = 0.2          # track activity below this counts as "idle/seated"
MANY_LONG_DWELLERS = 2      # >= this many campers in a full room => act
HIGH_QUEUE = 3              # queue at/over this => service is slipping
ABANDON_DELTA = 1           # abandons rising by >= this since last scene => act

# music
MUSIC_LULL_VOLUME = 60      # lift energy in a dead room
MUSIC_IDLE_VOLUME = 52      # gentler bump when staff activity is just low
# temperature
COOL_DELTA_C = -1.5         # cool a packed, slow-turnover room to nudge turnover

# debounce windows, seconds — keyed per *rule* so distinct alerts don't masking
# each other (e.g. a queue alert won't suppress a free-rider nudge).
DEBOUNCE_S = {
    "music": 90,
    "discount_quiet": 600,
    "discount_takeaway": 600,
    "temperature": 300,
    "notify_queue": 120,
    "notify_free_ride": 600,
}
DEFAULT_DEBOUNCE_S = 120


# --------------------------------------------------------------------------
# debounce helpers — `state` is owned by the caller and persists across calls.
# --------------------------------------------------------------------------
def _due(state: dict, key: str, now: float) -> bool:
    last = state.get("_last_fired", {}).get(key)
    window = DEBOUNCE_S.get(key, DEFAULT_DEBOUNCE_S)
    return last is None or (now - last) >= window


def _mark(state: dict, key: str, now: float) -> None:
    state.setdefault("_last_fired", {})[key] = now


def _action(now: float, name: str, params: dict, rationale: str,
            reversible: bool = True) -> AgentAction:
    return AgentAction(
        ts=now,
        action=name,
        params=params,
        rationale=rationale,
        reversible=reversible,
        auto=True,
    )


# --------------------------------------------------------------------------
# scene feature extraction
# --------------------------------------------------------------------------
def _seated_tracks(scene: dict) -> list[dict]:
    return [t for t in scene.get("tracks", []) if t.get("zone") == "seating"]


def _long_dwellers(scene: dict) -> list[dict]:
    return [t for t in _seated_tracks(scene) if t.get("dwell_s", 0.0) > LONG_DWELL_S]


def _free_riders(scene: dict) -> list[dict]:
    return [
        t for t in _seated_tracks(scene)
        if t.get("dwell_s", 0.0) > FREE_RIDE_DWELL_S
        and t.get("activity", 0.0) <= LOW_ACTIVITY
    ]


# --------------------------------------------------------------------------
# the policy
# --------------------------------------------------------------------------
def decide(scene: dict, state: dict) -> list[AgentAction]:
    """Inspect a scene and return the actions to take right now (possibly none)."""
    now = float(scene.get("ts") or time.time())
    occupancy = int(scene.get("occupancy", 0))
    queue_len = int(scene.get("queue_len", 0))
    productivity = float(scene.get("staff_productivity", 0.0))
    funnel = scene.get("funnel", {}) or {}
    abandoned = int(funnel.get("abandoned", 0))

    long_dwellers = _long_dwellers(scene)
    free_riders = _free_riders(scene)
    packed = occupancy >= HIGH_OCCUPANCY

    actions: list[AgentAction] = []

    # --- 1. queue building / abandons rising -> alert staff -----------------
    prev_abandoned = state.get("last_abandoned")
    abandons_rising = prev_abandoned is not None and (abandoned - prev_abandoned) >= ABANDON_DELTA
    state["last_abandoned"] = abandoned
    if (queue_len >= HIGH_QUEUE or abandons_rising) and _due(state, "notify_queue", now):
        if queue_len >= HIGH_QUEUE and abandons_rising:
            why = f"Queue at {queue_len} and {abandoned - prev_abandoned} just walked off"
        elif queue_len >= HIGH_QUEUE:
            why = f"Queue length {queue_len} is over threshold {HIGH_QUEUE}"
        else:
            why = f"Abandons rising ({prev_abandoned}->{abandoned}) — customers giving up"
        _mark(state, "notify_queue", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": "Queue building — can someone open a second till?", "priority": "high"},
            f"{why}; open another till to protect conversion.",
        ))

    # --- 2. packed + many campers -> cool room + nudge takeaway -------------
    if packed and len(long_dwellers) >= MANY_LONG_DWELLERS:
        if _due(state, "temperature", now):
            _mark(state, "temperature", now)
            actions.append(_action(
                now, "set_temperature",
                {"delta_c": COOL_DELTA_C},
                f"Room is full ({occupancy}) with {len(long_dwellers)} long-dwellers; "
                f"a slight cool-down gently encourages table turnover.",
            ))
        if _due(state, "discount_takeaway", now):
            promo = takeaway_discount(now)
            _mark(state, "discount_takeaway", now)
            actions.append(_action(
                now, "push_discount",
                {"text": promo.text, "kind": promo.kind},
                f"Seats scarce ({occupancy} in, {len(long_dwellers)} camping); "
                f"steer demand to takeaway to free tables.",
            ))

    # --- 3. lull / low energy -> raise music -------------------------------
    is_lull = occupancy <= LULL_OCCUPANCY
    low_energy = productivity < LOW_PRODUCTIVITY
    if (is_lull or low_energy) and not packed and _due(state, "music", now):
        if is_lull:
            vol, why = MUSIC_LULL_VOLUME, f"Only {occupancy} in — lift energy with louder music."
        else:
            vol, why = MUSIC_IDLE_VOLUME, f"Staff activity low ({productivity:.2f}) — a nudge of energy."
        _mark(state, "music", now)
        actions.append(_action(
            now, "set_music_volume", {"volume": vol}, why,
        ))

    # --- 4. quiet room -> push a quiet-hour discount -----------------------
    if is_lull and _due(state, "discount_quiet", now):
        promo = quiet_hour_discount(now)
        _mark(state, "discount_quiet", now)
        actions.append(_action(
            now, "push_discount",
            {"text": promo.text, "kind": promo.kind},
            f"Quiet room ({occupancy} in) — a promo lifts conversion during the lull.",
        ))

    # --- 5. free rider -> gentle staff nudge -------------------------------
    # Skip if the room is empty (a lone long-dweller in a dead room is fine).
    if free_riders and not is_lull and _due(state, "notify_free_ride", now):
        worst = max(free_riders, key=lambda t: t.get("dwell_s", 0.0))
        mins = int(worst.get("dwell_s", 0) // 60)
        _mark(state, "notify_free_ride", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": f"Heads up: a seated guest has been idle ~{mins} min — "
                     f"maybe offer a refill?", "priority": "low"},
            f"{len(free_riders)} long-idle seated guest(s); a friendly check-in "
            f"can prompt another order without being pushy.",
        ))

    return actions


# --------------------------------------------------------------------------
# offline self-test: exercise the policy on synthetic scenes, no net / no key
# --------------------------------------------------------------------------
def _selftest() -> None:
    from shared.mock_events import _synthetic_scene

    print("=== policy self-test on synthetic scenes (offline) ===\n")
    state: dict = {}
    # t values chosen to span busy (high wave) and quiet (low wave) conditions.
    base = time.time()
    for t in [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60]:
        scene = _synthetic_scene(t).model_dump()
        # Pin ts to a deterministic, advancing clock so debouncing is observable.
        scene["ts"] = base + t * 30
        actions = decide(scene, state)
        f = scene["funnel"]
        print(
            f"t={t:>2} occ={scene['occupancy']:>2} q={scene['queue_len']} "
            f"prod={scene['staff_productivity']:.2f} "
            f"long_dwell={len(_long_dwellers(scene))} "
            f"abandoned={f['abandoned']} -> {len(actions)} action(s)"
        )
        for a in actions:
            print(f"      • {a.action} {a.params}")
            print(f"        ↳ {a.rationale}")
        if not actions:
            print("      (no action)")
    # The mock's dwell_s never exceeds ~350 at realistic occupancy, so craft two
    # scenes to exercise the packed-room (cool + takeaway) and free-rider rules.
    print("\n=== crafted stress scenes (packed room w/ campers, then a free rider) ===")
    st3: dict = {}
    packed_scene = {
        "ts": base,
        "occupancy": 10,
        "queue_len": 1,
        "staff_productivity": 0.4,
        "funnel": {"abandoned": 0},
        "tracks": [
            {"id": i, "zone": "seating", "dwell_s": 700 + i * 20, "activity": 0.05}
            for i in range(4)
        ],
    }
    for a in decide(packed_scene, st3):
        print(f"      • {a.action} {a.params}")
        print(f"        ↳ {a.rationale}")

    free_rider_scene = {
        "ts": base + 1000,
        "occupancy": 6,
        "queue_len": 0,
        "staff_productivity": 0.6,
        "funnel": {"abandoned": 0},
        "tracks": [{"id": 1, "zone": "seating", "dwell_s": 820, "activity": 0.05}],
    }
    print("    --- free rider ---")
    for a in decide(free_rider_scene, {}):
        print(f"      • {a.action} {a.params}")
        print(f"        ↳ {a.rationale}")

    print("\n=== debounce check: same busy scene fired twice in quick succession ===")
    st2: dict = {}
    busy = _synthetic_scene(18).model_dump()
    busy["ts"] = base
    first = decide(busy, st2)
    busy2 = _synthetic_scene(18).model_dump()
    busy2["ts"] = base + 5  # 5s later — inside every debounce window
    second = decide(busy2, st2)
    print(f"first call: {[a.action for a in first]}")
    print(f"+5s later : {[a.action for a in second]}  (expected empty — debounced)")


if __name__ == "__main__":
    _selftest()
