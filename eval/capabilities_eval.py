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
# report
# ===========================================================================
def main() -> int:
    verbose = "-v" in sys.argv
    for fn in (eval_music_model, eval_policy, eval_agent, eval_schemas, eval_actuators):
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
