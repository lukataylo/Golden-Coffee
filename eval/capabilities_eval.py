"""Deep behavioral eval across ALL agent capabilities — no GPU, no video, no key.

The other eval (`eval/run_eval.py`) measures *perception* accuracy against vision
judges. This one measures *decision* behavior: it drives the policy, the local
music model (incl. the new controller-bias + Claude-inform wiring), the actuators,
and the schemas through crafted scenarios and asserts each capability behaves.

Fully deterministic and offline (fixed clock, stdlib only). Run:

    python -m eval.capabilities_eval          # summary report, exits non-zero on any fail
    python -m eval.capabilities_eval -v       # also print every passing check
"""
from __future__ import annotations

import os
import sys
import time

# Keep the actuators in their unconfigured (safe) branch for this eval.
for _k in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "ANTHROPIC_API_KEY"):
    os.environ.pop(_k, None)

from agent import policy
from agent.agent import Agent
from agent.forecast import FootfallForecast
from agent.music_model import (
    DEFAULT_WEIGHTS, FEATURE_NAMES, MOOD_KEYS, MOODS, MusicModel,
    bias_for_hint, features, _dataset, _oracle,
)
from shared.schemas import AgentAction, ActionName

# ---- tiny assert framework -------------------------------------------------
_RESULTS: list[tuple[str, str, bool, str]] = []  # (group, name, ok, detail)


def check(group: str, name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((group, name, bool(ok), detail))
    return bool(ok)


# ---- deterministic clock helpers -------------------------------------------
def ts_at(hour: int, minute: int = 0) -> float:
    """A fixed timestamp on 2026-06-20 at the given local hour."""
    return time.mktime((2026, 6, 20, hour, minute, 0, 0, 0, -1))


def names(actions) -> list[str]:
    return [a.action if isinstance(a, AgentAction) else a["action"] for a in actions]


def seated(i, dwell, activity=0.05):
    return {"id": i, "zone": "seating", "dwell_s": dwell, "activity": activity}


# ===========================================================================
# 1. LOCAL MUSIC MODEL
# ===========================================================================
def eval_music_model() -> None:
    g = "music_model"
    m = MusicModel()

    # feature vector contract
    feats = features({"occupancy": 6, "queue_len": 2, "staff_productivity": 0.5, "ts": ts_at(14)})
    check(g, "feature vector length matches FEATURE_NAMES",
          len(feats) == len(FEATURE_NAMES) == 10, f"len={len(feats)}")
    check(g, "bias feature is 1.0", feats[0] == 1.0)
    check(g, "weights cover every mood",
          all(k in DEFAULT_WEIGHTS and len(DEFAULT_WEIGHTS[k]) == len(FEATURE_NAMES) for k in MOOD_KEYS))

    # probabilities are a proper distribution
    probs = m.probabilities({"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(14)})
    check(g, "probabilities sum to 1", abs(sum(probs.values()) - 1.0) < 1e-9, f"sum={sum(probs.values()):.6f}")
    check(g, "probabilities all non-negative", all(p >= 0 for p in probs.values()))

    # the learned model agrees with its labelling oracle (generalisation sanity)
    rows = _dataset()
    agree = sum(1 for feats_row, label in rows
                if max(MOOD_KEYS, key=lambda k: sum(w * f for w, f in zip(m.weights[k], feats_row))) == label)
    acc = agree / len(rows)
    check(g, "oracle agreement >= 0.95", acc >= 0.95, f"acc={acc:.3f} over {len(rows)} rows")

    # every mood is reachable from a representative scene
    reach = {
        "rush_flow":         {"occupancy": 9, "queue_len": 4, "staff_productivity": 0.5, "ts": ts_at(13)},
        "busy_calm":         {"occupancy": 11, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(13)},
        "upbeat_lift":       {"occupancy": 2, "queue_len": 0, "staff_productivity": 0.25, "ts": ts_at(14)},
        "sunrise_acoustic":  {"occupancy": 5, "queue_len": 1, "staff_productivity": 0.6, "ts": ts_at(8)},
        "daytime_focus":     {"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(14)},
        "evening_warm":      {"occupancy": 5, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(20)},
    }
    for mood, scene in reach.items():
        p = m.probabilities(scene)
        top = max(p, key=p.get)
        check(g, f"mood reachable: {mood}", top == mood, f"got {top} ({p[top]:.2f})")

    # hysteresis: a tiny change holds, a clear change switches
    quiet_morning = {"occupancy": 5, "queue_len": 1, "staff_productivity": 0.6, "ts": ts_at(8)}
    d0, ch0 = m.recommend(quiet_morning, current=None)
    check(g, "first recommend marks a change", ch0 and d0.mood == "sunrise_acoustic", d0.mood)
    _, ch_hold = m.recommend({"occupancy": 6, "queue_len": 1, "staff_productivity": 0.55, "ts": ts_at(9)},
                             current="sunrise_acoustic")
    check(g, "hysteresis holds on a small change", ch_hold is False)
    d_sw, ch_sw = m.recommend({"occupancy": 9, "queue_len": 4, "staff_productivity": 0.5, "ts": ts_at(9)},
                              current="sunrise_acoustic")
    check(g, "switches on a clear change", ch_sw and d_sw.mood == "rush_flow", d_sw.mood)

    # controller bias (#1): a soft lean raises the hinted mood's probability...
    toss = {"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(14)}
    base = m.probabilities(toss)
    leaned = m.probabilities(toss, bias_for_hint("upbeat_lift"))
    check(g, "bias raises hinted mood probability",
          leaned["upbeat_lift"] > base["upbeat_lift"],
          f"{base['upbeat_lift']:.2f} -> {leaned['upbeat_lift']:.2f}")
    # ...but a clear scene signal still overrides a soft bias (lean, not lock)
    rush = {"occupancy": 10, "queue_len": 5, "staff_productivity": 0.5, "ts": ts_at(14)}
    rp = m.probabilities(rush, bias_for_hint("evening_warm"))
    check(g, "scene overrides a soft contrary bias", max(rp, key=rp.get) == "rush_flow",
          f"got {max(rp, key=rp.get)}")
    # a strong bias CAN flip a toss-up
    strong = m.probabilities(toss, {"upbeat_lift": 5.0})
    check(g, "strong bias flips a toss-up", max(strong, key=strong.get) == "upbeat_lift",
          f"got {max(strong, key=strong.get)}")
    # bias_for_hint contract
    from agent.music_model import HINT_STRENGTH
    check(g, "bias_for_hint(valid) -> nudge", bias_for_hint("rush_flow") == {"rush_flow": HINT_STRENGTH})
    check(g, "bias_for_hint(unknown) -> {}", bias_for_hint("nonsense") == {} and bias_for_hint(None) == {})


# ===========================================================================
# 2. POLICY (rule engine) — every action branch
# ===========================================================================
def eval_policy() -> None:
    g = "policy"

    # rush copilot: queue building -> staff alert + music shifts to rush_flow
    st = {}
    acts = policy.decide({"occupancy": 9, "queue_len": 4, "staff_productivity": 0.5,
                          "funnel": {"abandoned": 0}, "ts": ts_at(13)}, st)
    check(g, "rush -> notify_staff (open till)", "notify_staff" in names(acts))
    sm = [a for a in acts if a.action == "set_music"]
    check(g, "rush -> set_music rush_flow", bool(sm) and sm[0].params["mood"] == "rush_flow",
          sm[0].params.get("mood") if sm else "none")

    # busy room with settled guests -> full comfort suite
    busy = {"occupancy": 10, "queue_len": 1, "staff_productivity": 0.4, "funnel": {"abandoned": 0},
            "ts": ts_at(13), "tracks": [seated(i, 700 + i * 20) for i in range(3)]}
    acts = policy.decide(busy, {})
    for want in ("set_temperature", "set_music_volume", "set_lighting", "set_scent", "push_discount"):
        check(g, f"busy -> {want}", want in names(acts))

    # lull -> lift music + time-aware comfort + quiet-hour discount
    lull = {"occupancy": 2, "queue_len": 0, "staff_productivity": 0.7, "funnel": {"abandoned": 0},
            "ts": ts_at(15)}
    acts = policy.decide(lull, {})
    smv = [a for a in acts if a.action == "set_music_volume"]
    check(g, "lull -> set_music_volume lift (60)", bool(smv) and smv[0].params["volume"] == policy.MUSIC_LULL_VOLUME,
          smv[0].params.get("volume") if smv else "none")
    check(g, "lull -> set_lighting", "set_lighting" in names(acts))
    check(g, "lull -> set_scent", "set_scent" in names(acts))
    check(g, "lull -> push_discount (quiet hour)", "push_discount" in names(acts))

    # low energy (not lull, not busy) -> gentle music lift
    low = {"occupancy": 5, "queue_len": 0, "staff_productivity": 0.30, "funnel": {"abandoned": 0},
           "ts": ts_at(14)}
    acts = policy.decide(low, {})
    smv = [a for a in acts if a.action == "set_music_volume"]
    check(g, "low-energy -> music lift (52)", bool(smv) and smv[0].params["volume"] == policy.MUSIC_LOW_ENERGY_VOLUME,
          smv[0].params.get("volume") if smv else "none")

    # unattended seated guest -> hospitality nudge
    un = {"occupancy": 6, "queue_len": 0, "staff_productivity": 0.6, "funnel": {"abandoned": 0},
          "ts": ts_at(14), "tracks": [seated(1, 820, activity=0.05)]}
    check(g, "unattended guest -> notify_staff", "notify_staff" in names(policy.decide(un, {})))

    # overdue table -> high-priority alert
    tbl = {"occupancy": 6, "queue_len": 0, "staff_productivity": 0.6, "funnel": {"abandoned": 0},
           "ts": ts_at(14), "tables": [{"id": "T3", "status": "overdue", "wait_s": 540}]}
    acts = policy.decide(tbl, {})
    ns = [a for a in acts if a.action == "notify_staff"]
    check(g, "overdue table -> notify_staff high",
          any(a.params.get("priority") == "high" for a in ns), names(acts))

    # cleaning overdue / dirty tables -> alert
    cl = {"occupancy": 4, "queue_len": 0, "staff_productivity": 0.6, "funnel": {"abandoned": 0},
          "ts": ts_at(14), "cleaning": [{"id": "restroom", "status": "overdue", "uses_since_clean": 30}]}
    check(g, "cleaning overdue -> notify_staff", "notify_staff" in names(policy.decide(cl, {})))
    dt = {"occupancy": 4, "queue_len": 0, "staff_productivity": 0.6, "funnel": {"abandoned": 0},
          "ts": ts_at(14), "tables": [{"id": "T1", "status": "free", "needs_cleaning": True}]}
    check(g, "dirty table -> notify_staff (buss)", "notify_staff" in names(policy.decide(dt, {})))

    # walk-offs rising across two scenes -> alert on the rise
    stw = {}
    policy.decide({"occupancy": 7, "queue_len": 1, "staff_productivity": 0.5,
                   "funnel": {"abandoned": 2}, "ts": ts_at(13)}, stw)
    a2 = policy.decide({"occupancy": 7, "queue_len": 1, "staff_productivity": 0.5,
                        "funnel": {"abandoned": 4}, "ts": ts_at(13, 5)}, stw)
    check(g, "walk-offs rising -> notify_staff", "notify_staff" in names(a2))

    # debounce: identical busy scene fired twice in quick succession is suppressed
    std = {}
    s1 = {"occupancy": 10, "queue_len": 1, "staff_productivity": 0.4, "funnel": {"abandoned": 0},
          "ts": ts_at(13), "tracks": [seated(i, 700 + i * 20) for i in range(3)]}
    first = policy.decide(s1, std)
    s2 = dict(s1); s2["ts"] = ts_at(13, 0) + 5  # +5s, inside every window
    second = policy.decide(s2, std)
    check(g, "debounce suppresses repeats", len(second) == 0, f"first={len(first)} second={len(second)}")

    # controller bias via state['music_bias'] influences the emitted mood (#1 e2e)
    stb = {"music_mood": "daytime_focus", "music_bias": {"upbeat_lift": 5.0}}
    # advance the clock past the music_mood debounce by using fresh state for timing
    acts = policy.decide({"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5,
                          "funnel": {"abandoned": 0}, "ts": ts_at(14)}, stb)
    sm = [a for a in acts if a.action == "set_music"]
    check(g, "state bias steers emitted mood", bool(sm) and sm[0].params["mood"] == "upbeat_lift",
          sm[0].params.get("mood") if sm else "none (held)")


# ===========================================================================
# 3. AGENT / CLAUDE PATH (rule fallback + music inform)
# ===========================================================================
def eval_agent() -> None:
    g = "agent"
    ag = Agent(use_claude=False)
    check(g, "no API key -> rule-based path", ag.use_claude is False)

    scene = {"occupancy": 9, "queue_len": 4, "staff_productivity": 0.5, "funnel": {"abandoned": 0},
             "ts": ts_at(13)}
    out = ag.decide_actions(scene)
    check(g, "decide_actions returns dicts", bool(out) and all(isinstance(a, dict) for a in out))
    check(g, "emitted actions carry rationale", all("rationale" in a for a in out))

    # #3: the music-inform context string the Claude path injects
    ag.state["music_mood"] = "daytime_focus"
    ctx = ag._music_context({"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(14)})
    check(g, "music context names current mood", "music_model(now=" in ctx and "Daytime focus" in ctx, ctx)
    check(g, "music context lists suggestions with %", "%" in ctx, ctx)
    ag.state["music_bias"] = {"upbeat_lift": 1.5}
    ctx_b = ag._music_context({"occupancy": 6, "queue_len": 1, "staff_productivity": 0.5, "ts": ts_at(14)})
    check(g, "music context surfaces active bias", "bias=" in ctx_b, ctx_b)

    # set_music mood expansion the Claude path performs (mood -> full directive)
    for key, mood in MOODS.items():
        from agent.music_model import playlist_for
        expanded = {"mood": mood.key, "playlist_uri": playlist_for(mood.key),
                    "descriptors": mood.descriptors, "bpm": mood.bpm, "volume": mood.volume}
        ok = expanded["playlist_uri"].startswith("spotify:") and expanded["bpm"] > 0 and 0 <= expanded["volume"] <= 100
        check(g, f"mood expands to full directive: {key}", ok)

    # footfall forecast: feeds history, produces a usable note type without crashing
    fc = FootfallForecast()
    for day_hour, occ in [(9, 4), (10, 8), (11, 12)]:
        fc.update(day_hour, occ)
    note = fc.staffing_note(current_occ=12, current_hour=11)
    check(g, "forecast staffing_note returns str|None", note is None or isinstance(note, str), repr(note))


# ===========================================================================
# 4. SCHEMAS — everything emitted is a valid AgentAction with a known name
# ===========================================================================
def eval_schemas() -> None:
    g = "schemas"
    valid_names = set(ActionName.__args__)

    # gather a broad set of emitted actions across scenarios
    scenarios = [
        {"occupancy": 9, "queue_len": 4, "staff_productivity": 0.5, "funnel": {"abandoned": 0}, "ts": ts_at(13)},
        {"occupancy": 10, "queue_len": 1, "staff_productivity": 0.4, "funnel": {"abandoned": 0},
         "ts": ts_at(13), "tracks": [seated(i, 700 + i * 20) for i in range(3)]},
        {"occupancy": 2, "queue_len": 0, "staff_productivity": 0.7, "funnel": {"abandoned": 0}, "ts": ts_at(20)},
    ]
    all_actions = []
    for sc in scenarios:
        all_actions += policy.decide(sc, {})
    check(g, "policy emitted some actions", len(all_actions) > 0, f"n={len(all_actions)}")
    check(g, "all actions are AgentAction", all(isinstance(a, AgentAction) for a in all_actions))
    check(g, "all action names in ActionName", all(a.action in valid_names for a in all_actions),
          sorted({a.action for a in all_actions} - valid_names))

    # set_music params carry the full directive contract
    sm = next((a for a in all_actions if a.action == "set_music"), None)
    if sm:
        need = {"mood", "label", "playlist_uri", "descriptors", "bpm", "energy", "volume"}
        check(g, "set_music params complete", need <= set(sm.params), sorted(need - set(sm.params)))

    # round-trip dicts back through the model (agent path emits dicts)
    dumped = [a.model_dump() for a in all_actions]
    ok = True
    try:
        for d in dumped:
            AgentAction(**d)
    except Exception as exc:  # noqa: BLE001
        ok = False; detail = str(exc)
    check(g, "action dicts re-validate as AgentAction", ok, "" if ok else detail)


# ===========================================================================
# 5. ACTUATORS — graceful degradation with no creds + dispatch routing
# ===========================================================================
def eval_actuators() -> None:
    g = "actuators"
    from actuators import spotify, run

    check(g, "spotify.set_volume() no creds -> False, no crash",
          spotify.set_volume(40) is False)
    check(g, "spotify.set_music() no creds -> False, no crash",
          spotify.set_music(playlist_uri="spotify:playlist:x", mood="rush_flow", volume=46) is False)
    check(g, "spotify.set_music() search path no creds -> False",
          spotify.set_music(descriptors="warm jazz", mood="evening_warm") is False)

    # dispatch routes both music actions without raising
    ok = True
    try:
        run.dispatch({"action": "set_music_volume", "params": {"volume": 50}, "auto": True})
        run.dispatch({"action": "set_music", "params": {
            "mood": "rush_flow", "playlist_uri": "spotify:playlist:x",
            "descriptors": "groove", "bpm": 104, "volume": 46}, "auto": True})
    except Exception as exc:  # noqa: BLE001
        ok = False; detail = str(exc)
    check(g, "run.dispatch routes set_music* without error", ok, "" if ok else detail)


# ===========================================================================
# 6. PERCEPTION GEOMETRY — validation, presets, auto-tables, load round-trip
# ===========================================================================
def eval_perception_geometry() -> None:
    g = "perception_geometry"
    from perception.geometry import (
        PRESETS, REQUIRED_ZONES, GeometryError, assert_valid, auto_tables,
        centroid, point_in_poly, polygon_area, preset, validate_geometry,
    )

    # geometry primitives
    unit = [[0, 0], [1, 0], [1, 1], [0, 1]]
    check(g, "polygon_area(unit square) == 1", abs(polygon_area(unit) - 1.0) < 1e-9)
    cx, cy = centroid(unit)
    check(g, "centroid(unit square) == (0.5, 0.5)", abs(cx - 0.5) < 1e-9 and abs(cy - 0.5) < 1e-9)
    check(g, "point_in_poly inside", point_in_poly((0.5, 0.5), unit))
    check(g, "point_in_poly outside", not point_in_poly((1.5, 0.5), unit))

    # every preset is valid, complete, and warning-free
    for name in PRESETS:
        cfg = preset(name, tables=5)
        errs, warns = validate_geometry(cfg)
        check(g, f"preset '{name}' has no errors", errs == [], errs[:1])
        check(g, f"preset '{name}' has all required zones",
              all(z in cfg["zones"] for z in REQUIRED_ZONES))
        check(g, f"preset '{name}' placed tables", len(cfg["tables"]) > 0, f"n={len(cfg['tables'])}")
        check(g, f"preset '{name}' warning-free (tables in seating, queue meets counter)",
              warns == [], warns[:1])

    # auto_tables: count respected and all tables sit inside the seating polygon
    seating = preset("counter_top")["zones"]["seating"]
    tabs = auto_tables(seating, 6)
    check(g, "auto_tables respects count", 0 < len(tabs) <= 6, f"n={len(tabs)}")
    check(g, "auto_tables all inside seating",
          all(point_in_poly(centroid(p), seating) for p in tabs.values()))
    check(g, "auto_tables coords in 0..1",
          all(0 <= c <= 1 for p in tabs.values() for pt in p for c in pt))

    # validation catches each failure mode
    good = preset("counter_top")
    cases = {
        "missing required zone": {**good, "zones": {k: v for k, v in good["zones"].items() if k != "counter"}},
        "out-of-frame coords": {**good, "zones": {**good["zones"], "entry": [[0, 0], [1.4, 0], [1.4, 1], [0, 1]]}},
        "degenerate polygon": {**good, "zones": {**good["zones"], "entry": [[0, 0], [0.1, 0], [0.2, 0]]}},
        "too few points": {**good, "zones": {**good["zones"], "entry": [[0, 0], [0.1, 0.1]]}},
        "unknown zone name": {**good, "zones": {**good["zones"], "lounge": [[0, 0], [0.1, 0], [0.1, 0.1]]}},
    }
    for label, bad in cases.items():
        errs, _ = validate_geometry(bad)
        check(g, f"rejects: {label}", len(errs) > 0, "no error raised")

    # assert_valid raises on bad, returns warnings on good
    raised = False
    try:
        assert_valid(cases["missing required zone"])
    except GeometryError:
        raised = True
    check(g, "assert_valid raises GeometryError on bad geometry", raised)
    check(g, "assert_valid returns warnings list on good geometry",
          isinstance(assert_valid(good), list))

    # end-to-end: a preset loads into perception.run globals and matches
    import json as _json
    from perception import run as prun
    tmp = "eval/_geom_tmp.json"
    with open(tmp, "w") as f:
        _json.dump(preset("counter_left", tables=4), f)
    try:
        prun.load_geometry(tmp)
        from shared.schemas import Zone
        check(g, "load_geometry applies all zones",
              all(z in prun.ZONE_POLYS_NORM for z in (Zone.ENTRY, Zone.QUEUE, Zone.COUNTER, Zone.SEATING)))
        check(g, "load_geometry applies tables", len(prun.TABLE_POLYS_NORM) == 4, f"n={len(prun.TABLE_POLYS_NORM)}")
        # a malformed file is rejected, not silently loaded
        with open(tmp, "w") as f:
            _json.dump({"zones": {"entry": [[0, 0], [2, 0], [0, 1]]}}, f)
        rejected = False
        try:
            prun.load_geometry(tmp)
        except GeometryError:
            rejected = True
        check(g, "load_geometry rejects malformed file", rejected)
    finally:
        os.path.exists(tmp) and os.remove(tmp)


# ===========================================================================
# 7. FEDERATED LEARNING — agent federation (Layer 1) + music FlockModel (Layer 2)
# ===========================================================================
def eval_federated() -> None:
    g = "federated"

    # --- Layer 2: federated music model (softmax weight FedAvg) -------------
    from federated.music_flock_model import (
        MusicFlockModel, VENUE_PROFILES, deserialize_weights, serialize_weights,
        full_eval_set, accuracy,
    )
    from agent.music_model import MOOD_KEYS, FEATURE_NAMES

    test = full_eval_set()
    models, params = [], []
    for name in VENUE_PROFILES:
        m = MusicFlockModel(profile=name)
        m.init_dataset("")
        p = m.train()
        models.append(m); params.append(p)

    check(g, "FlockModel.train returns non-empty bytes", all(isinstance(p, bytes) and p for p in params))
    w0 = deserialize_weights(params[0])["weights"]
    check(g, "weights have full shape (6 moods × 10 feats)",
          set(w0) == set(MOOD_KEYS) and all(len(w0[k]) == len(FEATURE_NAMES) for k in MOOD_KEYS))

    # serialize/deserialize round-trips
    rt = deserialize_weights(serialize_weights(w0, 99))
    check(g, "weight serialize round-trips", rt["n_scenes"] == 99 and rt["weights"]["rush_flow"] == w0["rush_flow"])

    global_bytes = models[0].aggregate(params)
    gw = deserialize_weights(global_bytes)
    check(g, "aggregate returns valid global weights",
          set(gw["weights"]) == set(MOOD_KEYS) and gw["n_scenes"] > 0)

    fed_acc = models[0].evaluate(global_bytes, test)
    solo_mean = sum(models[i].evaluate(params[i], test) for i in range(len(models))) / len(models)
    check(g, "federated beats mean-solo accuracy (the FL win)", fed_acc >= solo_mean,
          f"fed={fed_acc:.3f} solo_mean={solo_mean:.3f}")
    check(g, "federated accuracy is reasonable (>=0.7)", fed_acc >= 0.70, f"fed={fed_acc:.3f}")
    # a data-poor venue (morning only) is lifted by federation
    morning_idx = list(VENUE_PROFILES).index("morning_cafe")
    morning_solo = models[morning_idx].evaluate(params[morning_idx], test)
    check(g, "federation lifts the data-poor venue", fed_acc > morning_solo,
          f"fed={fed_acc:.3f} morning_solo={morning_solo:.3f}")

    # --- Layer 1 + live Layer 2: agent runs a federation round, patches policy
    #     thresholds AND the live music-model weights ---------------------------
    import copy as _copy
    import agent.policy as _pol
    snap = (_pol.LULL_OCCUPANCY, _pol.HIGH_OCCUPANCY, _pol.HIGH_QUEUE)
    snap_w = _copy.deepcopy(_pol._MUSIC_MODEL.weights)
    try:
        from agent.agent import Agent
        ag = Agent(use_claude=False)
        ag._fed_round_s = 1.0
        base = ts_at(13)
        fired = None
        for i in range(14):
            scene = {"occupancy": 5 + (i % 4), "queue_len": i % 3, "staff_productivity": 0.5,
                     "funnel": {"abandoned": 0}, "ts": base + i * 1.0}
            for a in ag.decide_actions(scene):
                if a["action"] == "tune_policy" and fired is None:
                    fired = a
        check(g, "agent fires a tune_policy federation round", fired is not None)
        if fired:
            need = {"lull", "high", "queue", "n_nodes", "music_synced"}
            check(g, "tune_policy params complete", need <= set(fired["params"]), sorted(need - set(fired["params"])))
            check(g, "tune_policy is a valid AgentAction", isinstance(AgentAction(**fired), AgentAction))
            check(g, "federation includes peer cafés (n_nodes>1)", fired["params"]["n_nodes"] > 1,
                  fired["params"].get("n_nodes"))
            check(g, "federation patched live policy thresholds",
                  (_pol.LULL_OCCUPANCY, _pol.HIGH_OCCUPANCY, _pol.HIGH_QUEUE) != snap)
        check(g, "tune_policy is a known ActionName", "tune_policy" in set(ActionName.__args__))
        # Live Layer 2: the running music model's weights were federated in place
        check(g, "federation patched live music-model weights", ag._fed_music_synced and
              _pol._MUSIC_MODEL.weights != snap_w)
        check(g, "music weights keep valid shape after federation",
              all(len(_pol._MUSIC_MODEL.weights[k]) == len(FEATURE_NAMES) for k in MOOD_KEYS))
    finally:
        _pol.LULL_OCCUPANCY, _pol.HIGH_OCCUPANCY, _pol.HIGH_QUEUE = snap  # restore globals
        _pol._MUSIC_MODEL.weights = snap_w


# ===========================================================================
# report
# ===========================================================================
def main() -> int:
    verbose = "-v" in sys.argv
    for fn in (eval_music_model, eval_policy, eval_agent, eval_schemas, eval_actuators,
               eval_perception_geometry, eval_federated):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — a crashing capability is a failure, not a stop
            check(fn.__name__, "did not crash", False, f"{type(exc).__name__}: {exc}")

    groups: dict[str, list] = {}
    for grp, name, ok, detail in _RESULTS:
        groups.setdefault(grp, []).append((name, ok, detail))

    print("=" * 68)
    print("  GOLDEN COFFEE — DEEP CAPABILITIES EVAL")
    print("=" * 68)
    total = passed = 0
    for grp, items in groups.items():
        gp = sum(1 for _, ok, _ in items if ok)
        print(f"\n[{grp}]  {gp}/{len(items)} passed")
        for name, ok, detail in items:
            total += 1; passed += ok
            if not ok:
                print(f"   ✗ FAIL  {name}" + (f"  ({detail})" if detail else ""))
            elif verbose:
                print(f"   ✓ {name}" + (f"  ({detail})" if detail else ""))
    print("\n" + "-" * 68)
    print(f"  TOTAL: {passed}/{total} checks passed"
          f"  ({'ALL PASS ✅' if passed == total else f'{total - passed} FAILED ❌'})")
    print("-" * 68)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
