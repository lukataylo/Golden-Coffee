"""Caffe Steve × FLock — port of our homegrown federated sim onto FlockModel.

FLock (https://flock.io) runs federated learning *on-chain*: each participant
trains locally and only submits opaque ``bytes`` parameters, an aggregator
averages them, and proposers/voters score the global model — no raw data ever
leaves the node. That privacy story is exactly what our `federated/` sim already
does: raw café video never leaves a venue; nodes share only capacity-normalised
policy ratios {lull, high, queue} and the server returns a scene-weighted mean.

This module re-expresses that *same maths* (no new model) on FLock's
``FlockModel`` ABC so the work can be submitted to a FlockTask and claim the
bounty:

    init_dataset(path)            load THIS venue's recent occupancy/queue history
    train(parameters[, dataset])  estimate {lull,high,queue} ratios → bytes
    aggregate(parameters_list)    scene-weighted mean of ratio vectors → bytes
    evaluate(parameters[, ...])   how well the ratios predict lull/busy  → float

Call-path mapping back to the existing (untouched) sim:
    train()      ≈ federated.node.estimate_ratios  (P20/P80 percentile ratios)
    aggregate()  ≈ federated.server._aggregate / sim.fed_average (n_scenes-weighted)
    evaluate()   ≈ new held-out scoring consistent with those thresholds

The ``flock_sdk`` import is LAZY/optional: if the package is missing the module
still imports and the local demo below runs a full federated round WITHOUT the
FLock platform. With ``flock_sdk`` installed, ``GoldenCoffeeModel`` is a genuine
``FlockModel`` subclass ready to wrap in ``FlockSDK(model).run()``.

Run the safe local demo:   python -m federated.flock_model
"""
from __future__ import annotations

import json
import math
import os
import random

# --- ratio estimation: re-used verbatim from federated.node (raw video never
#     leaves the venue; we only ever serialise these three floats) ------------
from federated.node import estimate_ratios

# ---------------------------------------------------------------------------
# LAZY / optional flock_sdk import
# ---------------------------------------------------------------------------
# We want this module (and the local demo) to import and run even when the
# `flock_sdk` package is not installed. When it *is* present, GoldenCoffeeModel
# becomes a real FlockModel subclass that FlockSDK can serve.
try:
    from flock_sdk import FlockModel as _FlockModelBase  # type: ignore
    HAS_FLOCK_SDK = True
except Exception:  # pragma: no cover - exercised only when package absent
    HAS_FLOCK_SDK = False

    class _FlockModelBase:  # minimal stand-in with the same surface
        """Fallback base so the module imports without flock_sdk installed."""
        pass


# ---------------------------------------------------------------------------
# Serialisation helpers — a "model" here is just the {lull,high,queue} ratio
# vector plus the scene count used as its aggregation weight. We use JSON bytes
# so the payload is human-inspectable on-chain and framework-agnostic.
# ---------------------------------------------------------------------------

def serialize_params(lull_ratio: float, high_ratio: float, queue_ratio: float,
                     n_scenes: int) -> bytes:
    return json.dumps(
        {
            "lull_ratio": round(float(lull_ratio), 3),
            "high_ratio": round(float(high_ratio), 3),
            "queue_ratio": round(float(queue_ratio), 3),
            "n_scenes": int(n_scenes),
        },
        separators=(",", ":"),
    ).encode("utf-8")


def deserialize_params(parameters: bytes | None) -> dict:
    if not parameters:
        # sensible defaults — mirrors federated.server._aggregate's cold start
        return {"lull_ratio": 0.30, "high_ratio": 0.80, "queue_ratio": 0.15,
                "n_scenes": 0}
    if isinstance(parameters, str):
        parameters = parameters.encode("utf-8")
    d = json.loads(parameters.decode("utf-8"))
    return {
        "lull_ratio": float(d.get("lull_ratio", 0.30)),
        "high_ratio": float(d.get("high_ratio", 0.80)),
        "queue_ratio": float(d.get("queue_ratio", 0.15)),
        "n_scenes": int(d.get("n_scenes", 0)),
    }


# ---------------------------------------------------------------------------
# Synthetic venue history — same generative model as federated.sim.Shop so the
# demo is self-contained. In production init_dataset reads a real dataset.json
# (the path FLock mounts into the training container).
# ---------------------------------------------------------------------------

def synth_history(capacity: int, occ_mean: float, occ_amp: float,
                  queue_mean: float, n: int = 120, seed: int = 0) -> list[dict]:
    """Produce a venue's recent scene history as a list of {occupancy, queue_len}.

    Faithful to federated.sim.Shop.generate_history (sine ebb/flow + gaussian
    noise, expressed in *absolute* people counts), wrapped in the per-scene dict
    shape FLock hands to train()/evaluate().
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    for t in range(n):
        wave = math.sin(t / 15.0)
        occ_frac = max(0.0, min(1.0, occ_mean + occ_amp * wave + rng.gauss(0, 0.05)))
        q_frac = max(0.0, min(0.5, queue_mean * max(0.0, wave) + rng.gauss(0, 0.02)))
        rows.append({
            "occupancy": occ_frac * capacity,
            "queue_len": q_frac * capacity,
        })
    return rows


# ---------------------------------------------------------------------------
# The FlockModel
# ---------------------------------------------------------------------------

class GoldenCoffeeModel(_FlockModelBase):
    """Capacity-normalised policy-ratio federation, expressed as a FlockModel.

    A node's local "training" is estimating what fraction of its capacity counts
    as a lull / busy room / long queue. Aggregation is the scene-weighted mean of
    those fractions across venues. Because we share ratios (not raw counts) a
    10-seat espresso bar and a 40-seat café can teach each other meaningfully.
    """

    def __init__(self, capacity: int | None = None,
                 occ_mean: float = 0.55, occ_amp: float = 0.40,
                 queue_mean: float = 0.15, seed: int = 0) -> None:
        # capacity is the per-venue normaliser (seats). Defaults from env so the
        # same image can run for any venue without code changes.
        self.capacity = int(capacity if capacity is not None
                            else os.environ.get("SHOP_CAPACITY", "20"))
        self.occ_mean = occ_mean
        self.occ_amp = occ_amp
        self.queue_mean = queue_mean
        self.seed = seed
        self.dataset: list[dict] = []

    # -- FlockModel interface ------------------------------------------------

    def init_dataset(self, dataset_path: str) -> None:
        """Load this venue's recent occupancy/queue history.

        FLock mounts a dataset file into the container (e.g. /dataset.json). We
        read it if present; otherwise we fall back to the synthetic generator so
        the model runs anywhere (CI, the local demo, a fresh node with no data).

        Accepted file shapes:
          * ``[{"occupancy": .., "queue_len": ..}, ...]``
          * ``{"capacity": N, "scenes": [ {...}, ... ]}``
        """
        rows: list[dict] | None = None
        try:
            if dataset_path and os.path.exists(dataset_path):
                with open(dataset_path, "r") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    self.capacity = int(raw.get("capacity", self.capacity))
                    rows = raw.get("scenes") or raw.get("data")
                elif isinstance(raw, list):
                    rows = raw
        except Exception as exc:  # corrupt/missing → synthetic fallback
            print(f"[flock] init_dataset: could not read {dataset_path!r} ({exc}); "
                  f"using synthetic history")
            rows = None

        if not rows:
            rows = synth_history(self.capacity, self.occ_mean, self.occ_amp,
                                 self.queue_mean, n=120, seed=self.seed)

        # normalise each row to {occupancy, queue_len} floats
        self.dataset = [
            {
                "occupancy": float(r.get("occupancy", 0.0)),
                "queue_len": float(r.get("queue_len", r.get("queue", 0.0))),
            }
            for r in rows
        ]

    def train(self, parameters: bytes | None = None,
              dataset: list[dict] | None = None) -> bytes:
        """Estimate {lull,high,queue} ratios from local history → bytes.

        ``parameters`` (the incoming global model) is accepted for interface
        compatibility but, exactly like federated.sim.Shop.learn_local, each node
        re-estimates its ratios from its OWN data every round — the cross-venue
        blending happens in aggregate(), not here. ``dataset`` defaults to the
        history loaded by init_dataset (the real SDK only passes ``parameters``).
        """
        data = dataset if dataset is not None else self.dataset
        occ_hist = [float(r["occupancy"]) for r in data]
        queue_hist = [float(r["queue_len"]) for r in data]
        # *** identical maths to federated.node.estimate_ratios ***
        ratios = estimate_ratios(occ_hist, queue_hist, self.capacity)
        return serialize_params(
            ratios["lull_ratio"], ratios["high_ratio"], ratios["queue_ratio"],
            n_scenes=len(occ_hist),
        )

    def aggregate(self, parameters_list: list[bytes]) -> bytes:
        """Scene-weighted mean of ratio vectors → bytes.

        Re-implements federated.server._aggregate / federated.sim.fed_average:
        each node's ratios are weighted by how many scenes it observed, so
        high-data venues have more say than freshly-started ones.
        """
        nodes = [deserialize_params(p) for p in parameters_list]
        nodes = [n for n in nodes if n is not None]
        if not nodes:
            return serialize_params(0.30, 0.80, 0.15, n_scenes=0)

        total_w = sum(max(n["n_scenes"], 1) for n in nodes)
        lull = sum(n["lull_ratio"] * max(n["n_scenes"], 1) for n in nodes) / total_w
        high = sum(n["high_ratio"] * max(n["n_scenes"], 1) for n in nodes) / total_w
        queue = sum(n["queue_ratio"] * max(n["n_scenes"], 1) for n in nodes) / total_w
        # global weight = total scenes seen across the federation
        return serialize_params(lull, high, queue, n_scenes=total_w)

    def evaluate(self, parameters: bytes | None = None,
                 dataset: list[dict] | None = None) -> float:
        """Score how well the global ratios predict lull/busy on held-out scenes.

        The federated-learning question is: *does the shared global model still
        make the right lull/busy calls for THIS venue?* So we use the venue's own
        locally-optimal thresholds — the P20/P80 ratios it would derive from its
        full history alone (federated.node.estimate_ratios), i.e. the gold-standard
        policy if it never federated — as ground truth on a held-out window, then
        check whether the GLOBAL ratios reproduce the same lull/busy/normal label.

        Both label a held-out scene as:
            occ/cap < lull_ratio ⇒ "lull",  occ/cap > high_ratio ⇒ "busy", else "normal"
        Returns agreement in [0,1]: 1.0 means federation cost this venue nothing;
        lower means the global compromise mislabels some of its scenes.
        """
        g = deserialize_params(parameters)
        data = dataset if dataset is not None else self.dataset
        if not data:
            return 0.0

        cap = max(self.capacity, 1)
        split = max(1, int(len(data) * 0.8))
        train_rows = data[:split]
        held = data[split:] or data[-max(1, len(data) // 5):]

        # local "gold-standard" thresholds from this venue's own (non-held-out)
        # history — identical maths to what train()/the node would pick solo.
        local = estimate_ratios(
            [r["occupancy"] for r in train_rows],
            [r["queue_len"] for r in train_rows],
            cap,
        )

        def label(o: float, lull_r: float, high_r: float) -> str:
            frac = o / cap
            if frac < lull_r:
                return "lull"
            if frac > high_r:
                return "busy"
            return "normal"

        agree = sum(
            1 for r in held
            if label(r["occupancy"], local["lull_ratio"], local["high_ratio"])
            == label(r["occupancy"], g["lull_ratio"], g["high_ratio"])
        )
        return round(agree / len(held), 3)


# ---------------------------------------------------------------------------
# Local demo — one full federated round end-to-end, NO FLock platform needed.
# ---------------------------------------------------------------------------

def _run_local_demo() -> dict:
    """Instantiate the model for 2-3 venues, run train → aggregate → evaluate
    entirely in-process and print everything. This is our safe fallback demo if
    the on-chain path stalls."""
    bar = "═" * 70

    print("\n" + bar)
    print("  ☕  Caffe Steve × FLock — local federated round (no platform)")
    print(bar)
    print(f"  flock_sdk installed: {HAS_FLOCK_SDK}"
          f"   (GoldenCoffeeModel is a "
          f"{'real FlockModel subclass' if HAS_FLOCK_SDK else 'standalone class'})")

    # Same three venues as federated.sim — different sizes & crowd patterns.
    venues = [
        ("City Espresso Bar",   dict(capacity=10, occ_mean=0.80, occ_amp=0.15, queue_mean=0.20)),
        ("Office Café",         dict(capacity=20, occ_mean=0.55, occ_amp=0.40, queue_mean=0.15)),
        ("Suburban Coffee Co.", dict(capacity=40, occ_mean=0.35, occ_amp=0.20, queue_mean=0.08)),
    ]

    print(f"\n  {len(venues)} venues each train() locally on their own history")
    print("  (raw scene data never leaves the venue — only the 3 ratios are shared)\n")

    print(f"  {'Venue':<22} {'cap':>4}  {'lull_r':>7} {'high_r':>7} {'queue_r':>8} {'n_scenes':>9}")
    print(f"  {'-'*22} {'-'*4}  {'-'*7} {'-'*7} {'-'*8} {'-'*9}")

    models: list[GoldenCoffeeModel] = []
    params_list: list[bytes] = []
    for i, (name, cfg) in enumerate(venues):
        m = GoldenCoffeeModel(seed=i * 42, **cfg)
        m.init_dataset("/dataset.json")  # path absent → synthetic fallback
        p = m.train(parameters=None)      # incoming global is None on round 1
        d = deserialize_params(p)
        models.append(m)
        params_list.append(p)
        print(f"  {name:<22} {cfg['capacity']:>4}  "
              f"{d['lull_ratio']:>7.3f} {d['high_ratio']:>7.3f} "
              f"{d['queue_ratio']:>8.3f} {d['n_scenes']:>9}")

    # --- aggregate (scene-weighted mean) on any node / the FLock aggregator ---
    global_bytes = models[0].aggregate(params_list)
    g = deserialize_params(global_bytes)
    print(f"\n  aggregate() → global params (scene-weighted mean):")
    print(f"    lull_ratio={g['lull_ratio']:.3f}  high_ratio={g['high_ratio']:.3f}  "
          f"queue_ratio={g['queue_ratio']:.3f}  (n_scenes={g['n_scenes']})")
    print(f"    raw bytes: {global_bytes!r}")

    # --- evaluate the global params on each venue's held-out window ----------
    print(f"\n  evaluate() global params on each venue's held-out scenes:")
    scores = []
    for (name, _cfg), m in zip(venues, models):
        score = m.evaluate(parameters=global_bytes)
        scores.append(score)
        print(f"    {name:<22}  accuracy={score:.3f}")
    mean_score = round(sum(scores) / len(scores), 3)

    print(f"\n  {bar[:70]}")
    print(f"  Federated round complete.  mean eval accuracy = {mean_score:.3f}")
    print("  Shared ratios, per-venue absolute thresholds — privacy-preserving"
          " cross-shop learning.")
    print(bar + "\n")

    return {"global": g, "global_bytes": global_bytes,
            "scores": scores, "mean_score": mean_score}


if __name__ == "__main__":
    _run_local_demo()
