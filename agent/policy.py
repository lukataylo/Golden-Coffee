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
from agent.music_model import MusicModel

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
AVG_TICKET_GBP = 4.80       # average spend per customer (for walkaway £ metric)

# local music model — picks the *track/mood* (genre, BPM, playlist) from the data.
# Volume rules below still apply; this chooses *what's playing*.
_MUSIC_MODEL = MusicModel()

# music — ambient autopilot tunes energy both ways
MUSIC_LULL_VOLUME = 60      # lift the vibe in a flat room
MUSIC_LOW_ENERGY_VOLUME = 52  # gentler bump when the room just feels low-energy
MUSIC_BUSY_VOLUME = 38      # soften music when it's busy so it stays pleasant
# temperature — COMFORT, never eviction
COMFORT_COOL_DELTA_C = -1.5  # a full room warms up; cool slightly for comfort
# lighting (brightness 0-100, warmth) — busy stays bright+neutral; quiet is time-aware
LIGHT_BUSY = (90, "neutral")
# scent — busy room: fresh citrus to keep the air pleasant; quiet is time-aware
SCENT_BUSY = (60, "fresh citrus")


def _ambient_lighting(hour: int) -> tuple[int, str]:
    """Time-aware ambient lighting for a quiet room.
    Morning: bright + neutral (wake-up energy).
    Afternoon: warm-neutral (relaxed productivity).
    Evening: dim + warm (cosy wind-down).
    """
    if 6 <= hour < 11:
        return (80, "neutral")
    if 17 <= hour:
        return (30, "warm")
    return (55, "warm")


def _ambient_scent(hour: int) -> tuple[int, str]:
    """Time-aware scent for a quiet room.
    Morning: fresh citrus (energising).
    Afternoon/evening: warm vanilla (cosy and welcoming).
    """
    if 6 <= hour < 11:
        return (50, "fresh citrus")
    return (40, "warm vanilla")

# debounce windows, seconds — keyed per *rule* so distinct alerts don't mask
# each other (e.g. a queue alert won't suppress an unattended-guest nudge).
DEBOUNCE_S = {
    "music": 90,
    "music_mood": 120,  # switching the *track/mood* (vs. just volume) — a bit slower
    "discount_quiet": 600,
    "discount_togo": 600,
    "temperature": 300,
    "lighting": 300,
    "scent": 600,
    "notify_queue": 120,
    "notify_unattended": 600,
    "notify_table": 180,
    "notify_clean": 600,
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
    hour = time.localtime(now).tm_hour
    occupancy = int(scene.get("occupancy", 0))
    queue_len = int(scene.get("queue_len", 0))
    energy = float(scene.get("staff_productivity", 0.0))  # aggregate room movement/energy
    funnel = scene.get("funnel", {}) or {}
    abandoned = int(funnel.get("abandoned", 0))
    walkaway_gbp = float(scene.get("walkaway_gbp") or abandoned * AVG_TICKET_GBP)

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
            why = f"Walk-offs rising ({prev_abandoned}→{abandoned}) — customers leaving the line"
        gbp_note = f" (~£{walkaway_gbp:.0f} lost today to walk-offs)" if walkaway_gbp > 0 else ""
        _mark(state, "notify_queue", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": f"Queue building{gbp_note} — can someone open a second till?",
             "priority": "high"},
            f"{why}; open another till so we don't lose the sale.",
        ))

    # --- 1b. LOCAL MUSIC MODEL: pick the track/mood from the room's data ------
    # A small on-device softmax model maps occupancy/queue/energy/time-of-day to
    # a café "mood" (genre, BPM, playlist). It changes *what's playing* (the
    # volume rules below still tune loudness). Hysteresis avoids thrashing.
    current_mood = state.get("music_mood")
    directive, changed = _MUSIC_MODEL.recommend(scene, current_mood)
    if changed and _due(state, "music_mood", now):
        # Only advance the stored mood when we actually switch the track, so a
        # debounced switch is retried next tick rather than silently dropped.
        _mark(state, "music_mood", now)
        state["music_mood"] = directive.mood
        actions.append(_action(
            now, "set_music", directive.params(), directive.rationale,
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

    # --- 4. lull -> time-aware comfort (lighting + scent vary by time of day) --
    if is_lull and not busy:
        if _due(state, "lighting", now):
            bri, warmth = _ambient_lighting(hour)
            _mark(state, "lighting", now)
            tod = "morning" if hour < 11 else "evening" if hour >= 17 else "afternoon"
            actions.append(_action(
                now, "set_lighting", {"brightness": bri, "warmth": warmth},
                f"Quiet {tod} ({occupancy} in) — {warmth}, {bri}% lighting sets "
                f"the right mood for this time of day.",
            ))
        if _due(state, "scent", now):
            inten, sc = _ambient_scent(hour)
            _mark(state, "scent", now)
            actions.append(_action(
                now, "set_scent", {"intensity": inten, "scent": sc},
                f"A {sc} scent complements the {('morning energy' if hour < 11 else 'cosy atmosphere')}.",
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

    # --- 7. TABLE SERVICE: a table waiting too long -> alert staff -----------
    tables = scene.get("tables", []) or []
    overdue_tables = [t for t in tables if t.get("status") == "overdue"]
    if overdue_tables and _due(state, "notify_table", now):
        worst = max(overdue_tables, key=lambda t: t.get("wait_s", 0.0))
        mins = int(worst.get("wait_s", 0) // 60)
        _mark(state, "notify_table", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": f"Table {worst['id']} has been waiting ~{mins} min — please take their order.",
             "priority": "high"},
            f"Table {worst['id']} un-served for ~{mins} min; serve before they give up.",
        ))

    # --- 8. CLEANING: a zone overdue, or tables to buss -> alert staff -------
    clean_overdue = [c for c in (scene.get("cleaning", []) or []) if c.get("status") == "overdue"]
    dirty_tables = [t for t in tables if t.get("needs_cleaning")]
    if (clean_overdue or dirty_tables) and _due(state, "notify_clean", now):
        _mark(state, "notify_clean", now)
        if clean_overdue:
            z = clean_overdue[0]
            actions.append(_action(
                now, "notify_staff",
                {"text": f"{z['id'].title()} is due a clean ({z['uses_since_clean']} uses since last).",
                 "priority": "low"},
                f"{z['id']} hit {z['uses_since_clean']} uses since the last clean — time for a check.",
            ))
        else:
            ids = ", ".join(t["id"] for t in dirty_tables)
            actions.append(_action(
                now, "notify_staff",
                {"text": f"Tables to buss: {ids}.", "priority": "low"},
                f"{len(dirty_tables)} table(s) vacated and need bussing for the next guests.",
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
