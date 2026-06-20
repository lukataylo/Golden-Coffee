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
HIGH_QUEUE = 5              # queue at/over this => service is slipping (3 can still wait)
ABANDON_DELTA = 1           # walk-offs rising by >= this since last scene => act
AVG_TICKET_GBP = 4.80       # average spend per customer (for walkaway £ metric)
LULL_SUSTAINED_S = 600      # lull must hold 10 min before markdown activates

# Table service SLA thresholds (sustained time before alert fires)
TABLE_DIRTY_SLA_S   = 180   # 7b: guest sitting with dirty table ≥ 3 min
TABLE_ORDER_SLA_S   = 360   # 7c: waiting_to_order ≥ 6 min
TABLE_BILL_SLA_S    = 240   # 7d: requested_bill ≥ 4 min
TABLE_SLA_COOLDOWN  = 300   # 5 min repeat-alert cooldown per table per rule

# Perishable items eligible for quiet-period markdown (never surge — prices only go down).
# In production these come from the POS/inventory API; mocked here for demo.
HIGH_DECAY_ITEMS = [
    {"id": "pastry_daily",   "name": "Today's Pastry",    "base_price": 3.50, "category": "bakery"},
    {"id": "sandwich_cblt",  "name": "Club Sandwich",      "base_price": 6.80, "category": "food"},
    {"id": "salad_greek",    "name": "Greek Salad",         "base_price": 5.90, "category": "food"},
    {"id": "quiche_slice",   "name": "Quiche Slice",        "base_price": 4.20, "category": "bakery"},
]

# Discount by occupancy — deeper the emptier the room. Minimum 10% at occ=3.
_MARKDOWN_BY_OCC = {0: 0.20, 1: 0.15, 2: 0.12, 3: 0.10}

# local music model — picks the *track/mood* (genre, BPM, playlist) from the data.
# Volume rules below still apply; this chooses *what's playing*.
_MUSIC_MODEL = MusicModel()

# music — ambient autopilot tunes energy both ways
MUSIC_LULL_VOLUME = 60      # lift the vibe in a flat room
MUSIC_LOW_ENERGY_VOLUME = 52  # gentler bump when the room just feels low-energy
MUSIC_BUSY_VOLUME = 38      # soften music when it's busy so it stays pleasant
# lighting (brightness 0-100, warmth) — busy stays bright+neutral; quiet is time-aware
LIGHT_BUSY = (90, "neutral")
# scent — busy room: fresh citrus to keep the air pleasant; quiet is time-aware
SCENT_BUSY = (60, "fresh citrus")

# thermal baselines (°C) by outdoor temperature
TEMP_BASELINE_WINTER = 23.0   # outdoor < 12°C
TEMP_BASELINE_SUMMER = 21.0   # outdoor > 24°C
TEMP_BASELINE_DEFAULT = 22.0  # transition / no sensor
TEMP_HYSTERESIS = 0.5         # only act if target moves > ±0.5°C from last setpoint
TEMP_HIGH_OCC_GATE_S = 240    # busy for 4 min before cooling kicks in
TEMP_RECOVERY_S = 600         # low occ for 10 min before resetting to baseline


def _thermal_target(scene: dict, state: dict, now: float) -> tuple[float | None, str]:
    """Compute the HVAC absolute target (°C) using the 4-component model.

    Returns (target_c, rationale) or (None, "") when no change is warranted.
    Priority chain: baseline → occupancy load (sustained) → humidity → psychological.
    Hysteresis prevents thrashing; recovery resets baseline when the room empties.
    """
    outdoor_temp = scene.get("outdoor_temp_c")
    indoor_rh    = scene.get("indoor_humidity_rh")
    occupancy    = int(scene.get("occupancy", 0))

    # 1. Seasonal baseline
    if outdoor_temp is None:
        baseline = TEMP_BASELINE_DEFAULT
    elif outdoor_temp < 12:
        baseline = TEMP_BASELINE_WINTER
    elif outdoor_temp > 24:
        baseline = TEMP_BASELINE_SUMMER
    else:
        baseline = TEMP_BASELINE_DEFAULT

    # 2. Occupancy load — with sustained gate so a brief spike doesn't blast the AC
    if occupancy >= HIGH_OCCUPANCY:
        if state.get("high_occ_since") is None:
            state["high_occ_since"] = now
        sustained = now - state["high_occ_since"]
        occ_offset = -1.5 if sustained >= TEMP_HIGH_OCC_GATE_S else 0.0
        state["low_occ_since"] = None
    elif occupancy < 5:
        occ_offset = +0.5
        if state.get("low_occ_since") is None:
            state["low_occ_since"] = now
        state["high_occ_since"] = None
    else:
        occ_offset = 0.0
        state["high_occ_since"] = None
        state["low_occ_since"] = None

    # Recovery: room has been quiet for 10+ min → silently drift back to baseline
    low_since = state.get("low_occ_since")
    if low_since and (now - low_since) >= TEMP_RECOVERY_S:
        last = state.get("temp_target")
        if last is None or abs(baseline - last) <= TEMP_HYSTERESIS:
            return None, ""
        state["temp_target"] = baseline
        return baseline, (
            f"Room has been quiet for 10+ min — resetting to baseline {baseline:.1f}°C."
        )

    # 3. Humidity factor
    if indoor_rh is not None:
        if indoor_rh > 60:
            hum_offset = -0.5
        elif indoor_rh < 35:
            hum_offset = +0.5
        else:
            hum_offset = 0.0
    else:
        hum_offset = 0.0

    # 4. Psychological offset (winter only) — warm vanilla + dim warm lighting makes
    # the room feel warmer than it is; lower the heating setpoint to save energy.
    psych_offset = 0.0
    if baseline >= TEMP_BASELINE_WINTER:
        if (state.get("lighting_warmth") == "warm"
                and state.get("lighting_brightness", 100) <= 40
                and "vanilla" in state.get("scent_name", "")):
            psych_offset = -0.5

    final_target = round(baseline + occ_offset + hum_offset + psych_offset, 1)

    # Hysteresis: skip if within ±0.5°C of last setpoint
    last = state.get("temp_target")
    if last is not None and abs(final_target - last) <= TEMP_HYSTERESIS:
        return None, ""

    # Build rationale
    parts: list[str] = []
    if outdoor_temp is not None:
        parts.append(f"outdoor {outdoor_temp:.0f}°C → baseline {baseline:.0f}°C")
    else:
        parts.append(f"baseline {baseline:.0f}°C")
    if occ_offset:
        parts.append(f"occupancy {occ_offset:+.1f}")
    if hum_offset and indoor_rh is not None:
        parts.append(f"humidity {indoor_rh:.0f}%RH {hum_offset:+.1f}")
    if psych_offset:
        parts.append(f"warm-dim ambiance {psych_offset:+.1f}")

    state["temp_target"] = final_target
    return final_target, f"{', '.join(parts)} → target {final_target:.1f}°C."


def _ambient_lighting(hour: int) -> tuple[int, str]:
    """Time-aware ambient lighting aligned to the music time slots (7/11/15).
    Morning Rush  (07–10): bright + neutral (wake-up energy).
    Midday Dwell  (11–14): warm-neutral (relaxed productivity).
    Afternoon Lounge (15+): dim + warm (cosy wind-down).
    """
    if 7 <= hour < 11:
        return (80, "neutral")
    if 11 <= hour < 15:
        return (55, "warm")
    return (30, "warm")


def _ambient_scent(hour: int) -> tuple[int, str]:
    """Time-aware scent aligned to music slots.
    Morning: fresh citrus (energising).
    Midday/Afternoon: warm vanilla (cosy and welcoming).
    """
    if 7 <= hour < 11:
        return (50, "fresh citrus")
    return (40, "warm vanilla")

# debounce windows, seconds — keyed per *rule* so distinct alerts don't mask
# each other (e.g. a queue alert won't suppress an unattended-guest nudge).
DEBOUNCE_S = {
    "music": 90,
    "music_mood": 120,  # switching the *track/mood* (vs. just volume) — a bit slower
    "discount_quiet": 600,
    "discount_togo": 600,
    "menu_markdown": 900,   # 15 min between perishable repricing rounds
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
def _due(state: dict, key: str, now: float, window_s: float | None = None) -> bool:
    last = state.get("_last_fired", {}).get(key)
    window = window_s if window_s is not None else DEBOUNCE_S.get(key, DEFAULT_DEBOUNCE_S)
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


def _quiet_price(base_price: float, occupancy: int) -> float:
    """Return the markdown price for a perishable item during a quiet lull.
    Discount scales with emptiness; never surges above base_price."""
    pct = _MARKDOWN_BY_OCC.get(min(occupancy, 3), 0.10)
    return round(base_price * (1 - pct), 2)


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
    music_auto = state.get("music_mode", "auto") == "auto"

    actions: list[AgentAction] = []

    # --- 1. RUSH COPILOT: queue too long -> pull staff; walk-offs escalate if queue is already bad --
    # Walk-offs alone don't trigger — people leave for personal reasons.
    # We only care about walk-offs when the queue is already long enough to be the cause.
    prev_abandoned = state.get("last_abandoned")
    walkoffs_rising = prev_abandoned is not None and (abandoned - prev_abandoned) >= ABANDON_DELTA
    state["last_abandoned"] = abandoned
    if queue_len >= HIGH_QUEUE and _due(state, "notify_queue", now):
        gbp_note = f" (~£{walkaway_gbp:.0f} lost today)" if walkaway_gbp > 0 else ""
        if walkoffs_rising:
            delta = abandoned - prev_abandoned
            text = f"Queue at {queue_len} and {delta} just walked off{gbp_note} — open a second till now."
            why = f"Queue at {queue_len} with walk-offs rising ({prev_abandoned}→{abandoned}); likely losing sales to the wait."
            priority = "urgent"
        else:
            text = f"Queue at {queue_len}{gbp_note} — can someone open a second till?"
            why = f"Queue length {queue_len} is over threshold {HIGH_QUEUE}; act before customers start leaving."
            priority = "high"
        _mark(state, "notify_queue", now)
        actions.append(_action(
            now, "notify_staff",
            {"text": text, "priority": priority},
            why,
        ))

    # --- 1b. LOCAL MUSIC MODEL: pick the track/mood from the room's data ------
    # Only runs in auto mode — custom mode means the employee is in control.
    if music_auto:
        current_mood = state.get("music_mood")
        directive, changed = _MUSIC_MODEL.recommend(
            scene, current_mood, bias=state.get("music_bias"),
        )
        if changed and _due(state, "music_mood", now):
            _mark(state, "music_mood", now)
            state["music_mood"] = directive.mood
            actions.append(_action(
                now, "set_music", directive.params(), directive.rationale,
            ))

    # --- 2. AMBIENT: thermal comfort (absolute target, 4-component model) ------
    # Runs for all occupancy levels — thermal_target handles the logic internally.
    if _due(state, "temperature", now):
        target_c, temp_rationale = _thermal_target(scene, state, now)
        if target_c is not None:
            _mark(state, "temperature", now)
            actions.append(_action(
                now, "set_temperature",
                {"target_c": target_c},
                temp_rationale,
            ))

    # --- 2b. AMBIENT: busy room -> soften music + boost lighting + freshen scent --
    if busy and len(long_dwellers) >= MANY_LONG_DWELLERS:
        if music_auto and _due(state, "music", now):
            _mark(state, "music", now)
            actions.append(_action(
                now, "set_music_volume", {"volume": MUSIC_BUSY_VOLUME},
                f"Busy and buzzy ({occupancy} in); soften the music so the room "
                f"stays pleasant to talk in.",
            ))
        if _due(state, "lighting", now):
            bri, warmth = LIGHT_BUSY
            _mark(state, "lighting", now)
            state["lighting_brightness"] = bri
            state["lighting_warmth"] = warmth
            actions.append(_action(
                now, "set_lighting", {"brightness": bri, "warmth": warmth},
                f"Busy room — brighten the lights to a clean, neutral level so it "
                f"feels alert and easy to move around.",
            ))
        if _due(state, "scent", now):
            inten, sc = SCENT_BUSY
            _mark(state, "scent", now)
            state["scent_name"] = sc
            actions.append(_action(
                now, "set_scent", {"intensity": inten, "scent": sc},
                f"A full room gets stuffy; freshen the air with a light {sc} scent "
                f"to keep it pleasant.",
            ))
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

    # Track how long the room has been in a lull (for the sustained-gate rules below).
    if is_lull:
        if state.get("lull_since") is None:
            state["lull_since"] = now
        lull_sustained_s = now - state["lull_since"]
    else:
        state["lull_since"] = None
        lull_sustained_s = 0.0
    if music_auto and (is_lull or low_energy) and not busy and _due(state, "music", now):
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
            state["lighting_brightness"] = bri
            state["lighting_warmth"] = warmth
            slot = "morning" if hour < 11 else "afternoon lounge" if hour >= 15 else "midday"
            actions.append(_action(
                now, "set_lighting", {"brightness": bri, "warmth": warmth},
                f"Quiet {slot} ({occupancy} in) — {warmth}, {bri}% lighting sets "
                f"the right mood for this time of day.",
            ))
        if _due(state, "scent", now):
            inten, sc = _ambient_scent(hour)
            _mark(state, "scent", now)
            state["scent_name"] = sc
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

    # --- 5b. QUIET MARKDOWN: reprice perishables after a 10-min sustained lull --
    # Prices only go DOWN (never_surge=True enforced per item). Fires at most once
    # every 15 min. One update_menu_price action per item + a single POS ping.
    if is_lull and lull_sustained_s >= LULL_SUSTAINED_S and _due(state, "menu_markdown", now):
        _mark(state, "menu_markdown", now)
        discount_pct = int(_MARKDOWN_BY_OCC.get(min(occupancy, 3), 0.10) * 100)
        marked: list[dict] = []
        for item in HIGH_DECAY_ITEMS:
            new_price = _quiet_price(item["base_price"], occupancy)
            if new_price < item["base_price"]:
                marked.append({**item, "display_price": new_price})
                actions.append(_action(
                    now, "update_menu_price",
                    {
                        "item_id": item["id"],
                        "display_price": new_price,
                        "base_price": item["base_price"],
                        "discount_pct": discount_pct,
                        "never_surge": True,
                    },
                    f"Quiet lull ({occupancy} in, {int(lull_sustained_s // 60)}+ min) — "
                    f"{item['name']} marked to £{new_price:.2f} ({discount_pct}% off). "
                    f"Resets to base price when the room fills again.",
                ))
        if marked:
            names = ", ".join(i["name"] for i in marked[:2])
            if len(marked) > 2:
                names += f" +{len(marked) - 2} more"
            actions.append(_action(
                now, "notify_staff",
                {
                    "text": f"POS update: {names} marked down {discount_pct}% — quiet-period pricing active.",
                    "priority": "low",
                },
                f"{len(marked)} perishable item(s) repriced on the menu board; "
                f"POS synced so staff ring the correct price.",
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

    # --- 7. TABLE SERVICE SLAs (per-table, per-rule debounce) ----------------
    tables = scene.get("tables", []) or []
    for t in tables:
        tid        = t.get("id", "?")
        occupied   = t.get("occupied", False)
        status     = t.get("status", "empty")
        occupied_s = float(t.get("occupied_s", 0.0))
        wait_s     = float(t.get("wait_s", 0.0))
        dirty      = t.get("needs_cleaning", False)

        # 7b: Guest sitting at an uncleared table for ≥ 3 min — hygiene SLA
        if (occupied and dirty and occupied_s >= TABLE_DIRTY_SLA_S
                and _due(state, f"table_dirty_{tid}", now, TABLE_SLA_COOLDOWN)):
            _mark(state, f"table_dirty_{tid}", now)
            actions.append(_action(
                now, "notify_staff",
                {
                    "text": f"URGENT: Clear Table {tid}. Guest is sitting with trash.",
                    "priority": "high",
                    "channel": "wearables",
                },
                f"Table {tid} occupied but not cleared; guest sitting with dirty dishes "
                f"for {int(occupied_s // 60)}+ min.",
            ))

        # 7c: Order-taking SLA — waiting_to_order for ≥ 6 min
        if (occupied and status == "waiting_to_order" and wait_s >= TABLE_ORDER_SLA_S
                and _due(state, f"table_order_{tid}", now, TABLE_SLA_COOLDOWN)):
            _mark(state, f"table_order_{tid}", now)
            actions.append(_action(
                now, "notify_staff",
                {
                    "text": f"ALERT: Table {tid} has been waiting {int(wait_s // 60)} mins to order!",
                    "priority": "high",
                    "channel": "wearables",
                },
                f"Table {tid} hasn't been served in {int(wait_s // 60)} min — order-taking SLA breach.",
            ))

        # 7d: Bill request SLA — requested_bill for ≥ 4 min
        if (status == "requested_bill" and wait_s >= TABLE_BILL_SLA_S
                and _due(state, f"table_bill_{tid}", now, TABLE_SLA_COOLDOWN)):
            _mark(state, f"table_bill_{tid}", now)
            actions.append(_action(
                now, "notify_staff",
                {
                    "text": f"CRITICAL: Bring bill to Table {tid} immediately.",
                    "priority": "urgent",
                    "channel": "pos_and_wearables",
                },
                f"Table {tid} requested the bill {int(wait_s // 60)}+ min ago — "
                f"guest is waiting to leave.",
            ))

    # 7-catch-all: "overdue" status (generic un-served table, from POS or mock)
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
