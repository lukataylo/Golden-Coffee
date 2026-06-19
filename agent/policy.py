"""Deterministic, rule-based ops policy for Golden Coffee.

`decide(scene, state) -> list[AgentAction]` is a *pure-ish* function: given a
SceneEvent (as a dict) and a mutable `state` dict it owns for debouncing, it
returns zero or more `AgentAction`s with plain-English rationales. No network,
no Claude, no API key — this is what makes the MVP run anywhere.

The agent (`agent.agent`) calls this on every scene by default. If an
ANTHROPIC_API_KEY is present it *may* layer Claude's judgement on top, but the
shop still works fully without it.

Philosophy: every action helps the customer or the staff — never punishes them.
Golden Coffee is an "ambient autopilot + rush copilot": it tunes the atmosphere
and protects speed-of-service, privately.

Encoded rules (see constants for thresholds):
  * queue building / walk-offs rising -> alert staff to open a second till (rush copilot)
  * busy + warming up                 -> cool for COMFORT + soften the music (ambient)
  * lull / flat energy                -> lift the vibe with upbeat music (ambient)
  * quiet off-peak                    -> fill-the-trough discount (never surge)
  * seated guest unattended a while   -> prompt staff to check in / offer a refill

Run `python -m agent.policy` to exercise it offline against the synthetic
scenes in `shared.mock_events` (no backend, no key needed).
"""
from __future__ import annotations

import time

from shared.schemas import AgentAction

from agent.discounts import quiet_hour_discount, takeaway_discount

# --- thresholds (all named so they're easy to tune in a demo) -------------
LULL_OCCUPANCY = 3          # <= this many people => the room feels flat
LOW_ENERGY = 0.45           # aggregate movement below this => the vibe is flagging
HIGH_OCCUPANCY = 8          # >= this => the room is busy/full
LONG_DWELL_S = 600          # a seated guest over this has been there a while (10 min)
UNATTENDED_DWELL_S = 780    # seated + still for this long => likely wants service
LOW_ACTIVITY = 0.2          # track activity below this counts as "settled/seated"
MANY_LONG_DWELLERS = 2      # >= this many settled guests in a full room
HIGH_QUEUE = 3              # queue at/over this => service is slipping
ABANDON_DELTA = 1           # walk-offs rising by >= this since last scene => act

# music — ambient autopilot tunes energy both ways
MUSIC_LULL_VOLUME = 60      # lift the vibe in a flat room
MUSIC_LOW_ENERGY_VOLUME = 52  # gentler bump when the room just feels low-energy
MUSIC_BUSY_VOLUME = 38      # soften music when it's busy so it stays pleasant
# temperature — COMFORT, never eviction
COMFORT_COOL_DELTA_C = -1.5  # a full room warms up; cool slightly for comfort
# lighting (brightness 0-100, warmth) — bright+neutral when busy, dim+warm when cozy
LIGHT_BUSY = (90, "neutral")
LIGHT_COZY = (35, "warm")
# scent (intensity 0-100, scent) — freshen a crowded room, warm scent for a cozy lull
SCENT_BUSY = (60, "fresh citrus")
SCENT_COZY = (40, "warm vanilla")

# debounce windows, seconds — keyed per *rule* so distinct alerts don't mask
# each other (e.g. a queue alert won't suppress an unattended-guest nudge).
DEBOUNCE_S = {
    "music": 90,
    "discount_quiet": 600,
    "discount_togo": 600,
    "temperature": 300,
    "lighting": 300,
    "scent": 600,
    "notify_queue": 120,
    "notify_unattended": 600,
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


def _unattended_guests(scene: dict) -> list[dict]:
    """Seated, settled, and there a long while — a hospitality opportunity
    (offer a refill / check in), NOT someone to move along."""
    return [
        t for t in _seated_tracks(scene)
        if t.get("dwell_s", 0.0) > UNATTENDED_DWELL_S
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
    energy = float(scene.get("staff_productivity", 0.0))  # aggregate room movement/energy
    funnel = scene.get("funnel", {}) or {}
    abandoned = int(funnel.get("abandoned", 0))

    long_dwellers = _long_dwellers(scene)
    unattended = _unattended_guests(scene)
    busy = occupancy >= HIGH_OCCUPANCY

    actions: list[AgentAction] = []

    # --- 1. RUSH COPILOT: queue building / walk-offs rising -> pull staff ----
    prev_abandoned = state.get("last_abandoned")
    walkoffs_rising = prev_abandoned is not None and (abandoned - prev_abandoned) >= ABANDON_DELTA
    state["last_abandoned"] = abandoned
    if (queue_len >= HIGH_QUEUE or walkoffs_rising) and _due(state, "notify_queue", now):
        if queue_len >= HIGH_QUEUE and walkoffs_rising:
            why = f"Queue at {queue_len} and {abandoned - prev_abandoned} just walked off"
        elif queue_len >= HIGH_QUEUE:
            why = f"Queue length {queue_len} is over threshold {HIGH_QUEUE}"
        else:
            why = f"Walk-offs rising ({prev_abandoned}->{abandoned}) — customers leaving the line"
        _mark(state, "notify_queue", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": "Queue building — can someone open a second till?", "priority": "high"},
            f"{why}; open another till so we don't lose the sale.",
        ))

    # --- 2. AMBIENT: busy room -> cool for comfort + soften the music --------
    if busy and len(long_dwellers) >= MANY_LONG_DWELLERS:
        if _due(state, "temperature", now):
            _mark(state, "temperature", now)
            actions.append(_action(
                now, "set_temperature",
                {"delta_c": COMFORT_COOL_DELTA_C},
                f"Room is full ({occupancy}) and will be warming up; a slight "
                f"cool-down keeps it comfortable.",
            ))
        if _due(state, "music", now):
            _mark(state, "music", now)
            actions.append(_action(
                now, "set_music_volume", {"volume": MUSIC_BUSY_VOLUME},
                f"Busy and buzzy ({occupancy} in); soften the music so the room "
                f"stays pleasant to talk in.",
            ))
        if _due(state, "lighting", now):
            bri, warmth = LIGHT_BUSY
            _mark(state, "lighting", now)
            actions.append(_action(
                now, "set_lighting", {"brightness": bri, "warmth": warmth},
                f"Busy room — brighten the lights to a clean, neutral level so it "
                f"feels alert and easy to move around.",
            ))
        if _due(state, "scent", now):
            inten, sc = SCENT_BUSY
            _mark(state, "scent", now)
            actions.append(_action(
                now, "set_scent", {"intensity": inten, "scent": sc},
                f"A full room gets stuffy; freshen the air with a light {sc} scent "
                f"to keep it pleasant.",
            ))
        # A gentle grab-and-go offer for guests in a hurry during the rush
        # (convenience, not eviction).
        if _due(state, "discount_togo", now):
            promo = takeaway_discount(now)
            _mark(state, "discount_togo", now)
            actions.append(_action(
                now, "push_discount",
                {"text": promo.text, "kind": promo.kind},
                f"Peak demand ({occupancy} in); a grab-and-go offer helps anyone "
                f"in a hurry get served faster.",
            ))

    # --- 3. AMBIENT: lull / flat energy -> lift the vibe with music ----------
    is_lull = occupancy <= LULL_OCCUPANCY
    low_energy = energy < LOW_ENERGY
    if (is_lull or low_energy) and not busy and _due(state, "music", now):
        if is_lull:
            vol, why = MUSIC_LULL_VOLUME, f"Only {occupancy} in — lift the vibe with brighter music."
        else:
            vol, why = MUSIC_LOW_ENERGY_VOLUME, f"Room feels flat (energy {energy:.2f}) — a lift in the music."
        _mark(state, "music", now)
        actions.append(_action(
            now, "set_music_volume", {"volume": vol}, why,
        ))

    # --- 4. lull -> cozy comfort (warm dim light + warm scent) ---------------
    if is_lull and not busy:
        if _due(state, "lighting", now):
            bri, warmth = LIGHT_COZY
            _mark(state, "lighting", now)
            actions.append(_action(
                now, "set_lighting", {"brightness": bri, "warmth": warmth},
                f"Quiet room ({occupancy} in) — dim, warm lighting makes it feel "
                f"cosy and inviting.",
            ))
        if _due(state, "scent", now):
            inten, sc = SCENT_COZY
            _mark(state, "scent", now)
            actions.append(_action(
                now, "set_scent", {"intensity": inten, "scent": sc},
                f"A gentle {sc} scent adds to the cosy atmosphere during the lull.",
            ))

    # --- 5. fill-the-trough off-peak discount (never surge) ------------------
    if is_lull and _due(state, "discount_quiet", now):
        promo = quiet_hour_discount(now)
        _mark(state, "discount_quiet", now)
        actions.append(_action(
            now, "push_discount",
            {"text": promo.text, "kind": promo.kind},
            f"Quiet off-peak ({occupancy} in) — a small offer fills the dead time "
            f"and pulls walk-ins in.",
        ))

    # --- 6. HOSPITALITY: seated guest unattended a while -> offer service -----
    # Skip if the room is empty (a lone guest relaxing in a quiet café is fine).
    if unattended and not is_lull and _due(state, "notify_unattended", now):
        worst = max(unattended, key=lambda t: t.get("dwell_s", 0.0))
        mins = int(worst.get("dwell_s", 0) // 60)
        _mark(state, "notify_unattended", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": f"A seated guest has been settled ~{mins} min — swing by and "
                     f"offer a refill?", "priority": "low"},
            f"{len(unattended)} guest(s) seated a while; a friendly check-in is good "
            f"hospitality and often prompts another order.",
        ))

    return actions


# --------------------------------------------------------------------------
# offline self-test: exercise the policy on synthetic scenes, no net / no key
# --------------------------------------------------------------------------
def _selftest() -> None:
    from shared.mock_events import _synthetic_scene

    print("=== policy self-test on synthetic scenes (offline) ===\n")
    state: dict = {}
    base = time.time()
    for t in [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60]:
        scene = _synthetic_scene(t).model_dump()
        scene["ts"] = base + t * 30  # deterministic advancing clock for debounce
        actions = decide(scene, state)
        f = scene["funnel"]
        print(
            f"t={t:>2} occ={scene['occupancy']:>2} q={scene['queue_len']} "
            f"energy={scene['staff_productivity']:.2f} "
            f"long_dwell={len(_long_dwellers(scene))} "
            f"walkoffs={f['abandoned']} -> {len(actions)} action(s)"
        )
        for a in actions:
            print(f"      • {a.action} {a.params}")
            print(f"        ↳ {a.rationale}")
        if not actions:
            print("      (no action)")

    print("\n=== crafted stress scenes (busy room w/ settled guests, then unattended) ===")
    st3: dict = {}
    busy_scene = {
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
    for a in decide(busy_scene, st3):
        print(f"      • {a.action} {a.params}")
        print(f"        ↳ {a.rationale}")

    unattended_scene = {
        "ts": base + 1000,
        "occupancy": 6,
        "queue_len": 0,
        "staff_productivity": 0.6,
        "funnel": {"abandoned": 0},
        "tracks": [{"id": 1, "zone": "seating", "dwell_s": 820, "activity": 0.05}],
    }
    print("    --- unattended guest ---")
    for a in decide(unattended_scene, {}):
        print(f"      • {a.action} {a.params}")
        print(f"        ↳ {a.rationale}")

    print("\n=== debounce check: same busy scene fired twice in quick succession ===")
    st2: dict = {}
    busy = _synthetic_scene(18).model_dump()
    busy["ts"] = base
    first = decide(busy, st2)
    busy2 = _synthetic_scene(18).model_dump()
    busy2["ts"] = base + 5  # inside every debounce window
    second = decide(busy2, st2)
    print(f"first call: {[a.action for a in first]}")
    print(f"+5s later : {[a.action for a in second]}  (expected empty — debounced)")


if __name__ == "__main__":
    _selftest()
