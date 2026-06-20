"""Coffee Steve × FLock (Layer 2) — federate the *music model's* softmax weights.

The first FLock port (`federated.flock_model`) shares three policy *ratios*. This
one federates something richer and more obviously "real ML": the weights of the
on-device **music model** (`agent.music_model`) — a softmax over scene features
that picks the café mood. Each venue trains the softmax on *its own* labelled
history and submits only the **weight vectors** (opaque bytes); the aggregator
FedAvg-averages them; the global weights pick better moods for everyone — and raw
footage never leaves a venue.

Why this is a better federated story than the ratios:
  * the payload is genuine model parameters (6 moods × 10 features), not 3 floats;
  * venues see different regimes (a morning café rarely sees an evening rush), so a
    venue that trains solo mislabels the moods it never observed — and **federation
    measurably fixes that** (see `evaluate` / the demo's solo-vs-federated table).

FlockModel interface (same ABC as flock_model.GoldenCoffeeModel):
    init_dataset(path)            load THIS venue's labelled (features, mood) history
    train(parameters[, dataset])  fit softmax weights on local data           → bytes
    aggregate(parameters_list)    scene-weighted element-wise mean of weights → bytes
    evaluate(parameters[, ...])   mood-label accuracy vs the oracle on held-out → float

`flock_sdk` is optional/lazy: the module imports and the demo runs without it.
Run the safe local demo:   python -m federated.music_flock_model
"""
from __future__ import annotations

import json
import time

from agent.music_model import (
    FEATURE_NAMES, MOOD_KEYS, _oracle, _softmax, features, fit,
)

try:
    from flock_sdk import FlockModel as _FlockModelBase  # type: ignore
    HAS_FLOCK_SDK = True
except Exception:  # pragma: no cover
    HAS_FLOCK_SDK = False

    class _FlockModelBase:  # minimal stand-in so the module imports without the SDK
        pass


_NFEAT = len(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# serialisation — a "model" is the {mood: [weights]} dict + the scene count used
# as its FedAvg weight. JSON bytes so it's inspectable on-chain.
# ---------------------------------------------------------------------------
def serialize_weights(weights: dict[str, list[float]], n_scenes: int) -> bytes:
    return json.dumps(
        {"weights": {k: [round(float(w), 5) for w in weights[k]] for k in MOOD_KEYS},
         "n_scenes": int(n_scenes)},
        separators=(",", ":"),
    ).encode("utf-8")


def deserialize_weights(parameters: bytes | None) -> dict:
    if not parameters:
        return {"weights": {k: [0.0] * _NFEAT for k in MOOD_KEYS}, "n_scenes": 0}
    if isinstance(parameters, str):
        parameters = parameters.encode("utf-8")
    d = json.loads(parameters.decode("utf-8"))
    w = d.get("weights", {})
    return {
        "weights": {k: [float(x) for x in w.get(k, [0.0] * _NFEAT)] for k in MOOD_KEYS},
        "n_scenes": int(d.get("n_scenes", 0)),
    }


def predict(weights: dict[str, list[float]], feats: list[float]) -> str:
    """argmax mood under a weight set — the model's call for a feature vector."""
    return max(MOOD_KEYS, key=lambda k: sum(weights[k][j] * feats[j] for j in range(_NFEAT)))


def accuracy(weights: dict[str, list[float]], data: list[tuple[list[float], str]]) -> float:
    if not data:
        return 0.0
    hit = sum(1 for feats, label in data if predict(weights, feats) == label)
    return round(hit / len(data), 3)


# ---------------------------------------------------------------------------
# per-venue labelled history — different venues see different regimes, which is
# exactly what makes federation worthwhile.
# ---------------------------------------------------------------------------
# Each profile is the slice of the day/room a venue actually observes.
VENUE_PROFILES = {
    "morning_cafe": {"hours": range(6, 11), "occ": range(0, 9), "queue": range(0, 3)},
    "midday_office": {"hours": range(11, 17), "occ": range(3, 14), "queue": range(0, 6)},
    "evening_bar": {"hours": range(17, 24), "occ": range(2, 13), "queue": range(0, 4)},
}


def venue_dataset(profile: dict) -> list[tuple[list[float], str]]:
    """Labelled (features, mood) rows for the scenes a venue with this profile sees."""
    rows: list[tuple[list[float], str]] = []
    base = time.mktime((2025, 1, 1, 0, 0, 0, 0, 0, -1))
    for hour in profile["hours"]:
        ts = base + hour * 3600
        for occ in profile["occ"]:
            for queue in profile["queue"]:
                for energy in (0.2, 0.4, 0.6, 0.8):
                    scene = {"ts": ts, "occupancy": occ, "queue_len": queue,
                             "staff_productivity": energy}
                    rows.append((features(scene), _oracle(scene)))
    return rows


def full_eval_set() -> list[tuple[list[float], str]]:
    """A held-out set spanning ALL hours/occupancies — the fair test every venue is
    scored on, including the regimes it never saw locally."""
    return venue_dataset({"hours": range(0, 24), "occ": range(0, 14), "queue": range(0, 6)})


# ---------------------------------------------------------------------------
# the FlockModel
# ---------------------------------------------------------------------------
class MusicFlockModel(_FlockModelBase):
    """Federated training of the café music model's softmax weights."""

    def __init__(self, profile: str | dict | None = None, epochs: int = 120) -> None:
        if isinstance(profile, str):
            profile = VENUE_PROFILES.get(profile)
        self.profile = profile or VENUE_PROFILES["midday_office"]
        self.epochs = epochs
        self.dataset: list[tuple[list[float], str]] = []

    # -- FlockModel interface ------------------------------------------------
    def init_dataset(self, dataset_path: str) -> None:
        """Load this venue's labelled history. FLock mounts a dataset file into the
        container; if absent we synthesise from this venue's profile so it runs
        anywhere. File shape: ``[[ [feat..], "mood" ], ...]`` or
        ``{"scenes": [{occupancy,queue_len,staff_productivity,ts}, ...]}``."""
        import os
        rows: list[tuple[list[float], str]] | None = None
        try:
            if dataset_path and os.path.exists(dataset_path):
                with open(dataset_path) as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict) and raw.get("scenes"):
                    rows = [(features(s), _oracle(s)) for s in raw["scenes"]]
                elif isinstance(raw, list):
                    rows = [(list(f), str(m)) for f, m in raw]
        except Exception as exc:
            print(f"[music-flock] init_dataset: {dataset_path!r} unreadable ({exc}); "
                  f"using synthetic profile history")
            rows = None
        self.dataset = rows if rows else venue_dataset(self.profile)

    def train(self, parameters: bytes | None = None,
              dataset: list | None = None) -> bytes:
        """Fit softmax weights on this venue's local data → bytes. Like the ratio
        port, the incoming global ``parameters`` is accepted for interface
        compatibility; each node re-fits on its OWN data and blending happens in
        aggregate()."""
        data = dataset if dataset is not None else self.dataset
        weights = fit(data, epochs=self.epochs)
        return serialize_weights(weights, n_scenes=len(data))

    def aggregate(self, parameters_list: list[bytes]) -> bytes:
        """Scene-weighted element-wise mean of the weight vectors (FedAvg)."""
        nodes = [deserialize_weights(p) for p in parameters_list]
        nodes = [n for n in nodes if n is not None]
        if not nodes:
            return serialize_weights({k: [0.0] * _NFEAT for k in MOOD_KEYS}, 0)
        total_w = sum(max(n["n_scenes"], 1) for n in nodes)
        out = {k: [0.0] * _NFEAT for k in MOOD_KEYS}
        for n in nodes:
            w = max(n["n_scenes"], 1)
            for k in MOOD_KEYS:
                for j in range(_NFEAT):
                    out[k][j] += n["weights"][k][j] * w
        for k in MOOD_KEYS:
            out[k] = [v / total_w for v in out[k]]
        return serialize_weights(out, n_scenes=total_w)

    def evaluate(self, parameters: bytes | None = None,
                 dataset: list | None = None) -> float:
        """Mood-label accuracy of the given weights vs the oracle on held-out data
        (defaults to the all-hours fair test set)."""
        weights = deserialize_weights(parameters)["weights"]
        data = dataset if dataset is not None else full_eval_set()
        return accuracy(weights, data)


# ---------------------------------------------------------------------------
# local demo — solo-trained vs federated weights, no FLock platform needed.
# ---------------------------------------------------------------------------
def _run_local_demo() -> dict:
    bar = "═" * 72
    print("\n" + bar)
    print("  🎵  Coffee Steve × FLock — federated music model (no platform)")
    print(bar)
    print(f"  flock_sdk installed: {HAS_FLOCK_SDK}  "
          f"(MusicFlockModel is a {'real FlockModel subclass' if HAS_FLOCK_SDK else 'standalone class'})")

    test = full_eval_set()
    models, params = [], []
    print(f"\n  Each venue trains the music softmax on ONLY the regime it sees:")
    print(f"  {'Venue':<16} {'rows':>6}  {'solo acc (all-hours test)':>26}")
    print(f"  {'-'*16} {'-'*6}  {'-'*26}")
    for name in VENUE_PROFILES:
        m = MusicFlockModel(profile=name)
        m.init_dataset("")
        p = m.train()
        solo = m.evaluate(p, test)
        models.append(m); params.append(p)
        print(f"  {name:<16} {len(m.dataset):>6}  {solo:>26.3f}")

    global_bytes = models[0].aggregate(params)
    fed = models[0].evaluate(global_bytes, test)
    solo_mean = round(sum(models[i].evaluate(params[i], test) for i in range(len(models))) / len(models), 3)

    print(f"\n  aggregate() → global weights (scene-weighted FedAvg)")
    print(f"    mean solo accuracy : {solo_mean:.3f}")
    print(f"    federated accuracy : {fed:.3f}   "
          f"({'+' if fed >= solo_mean else ''}{round(fed - solo_mean, 3)} vs mean solo)")
    print(f"\n  Federation lets venues that never saw a regime still pick the right")
    print(f"  mood there — sharing weights, never footage.")
    print(bar + "\n")
    return {"solo_mean": solo_mean, "federated": fed, "global_bytes": global_bytes}


if __name__ == "__main__":
    _run_local_demo()
