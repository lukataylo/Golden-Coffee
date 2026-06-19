"""Federation simulation — three virtual shops, no cameras or network needed.

Demonstrates how capacity-normalised ratio federation lets venues of different
sizes share policy knowledge without their raw numbers polluting each other.

Each shop has a distinct size and crowd pattern:
  A  City Espresso Bar    10 seats  — always busy, rarely empty
  B  Office Café          20 seats  — strong rush peaks, deep midday lulls
  C  Suburban Coffee Co.  40 seats  — moderate and steady, rarely packed

Without federation each shop tunes thresholds only from its own history.
After each federation round the global ratios are averaged (weighted by scene
count) and each shop re-derives its absolute thresholds from capacity × ratio.

The key insight printed at the end: the RATIOS converge across shops (shared
knowledge about "what fraction of capacity is a lull") while the ABSOLUTE
numbers stay different (a lull at shop A is 2 people; at shop C it is 9).

Run:  python -m federated.sim
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from federated.node import estimate_ratios, patch_policy

# ---------------------------------------------------------------------------
# Virtual shops
# ---------------------------------------------------------------------------

@dataclass
class Shop:
    name: str
    capacity: int
    # occupancy distribution parameters (as fraction of capacity)
    occ_mean: float      # average occupancy / capacity
    occ_amp: float       # sine-wave amplitude around mean
    queue_mean: float    # average queue / capacity

    # current absolute policy thresholds (start at defaults from agent.policy)
    lull_abs: int  = field(init=False)
    high_abs: int  = field(init=False)
    queue_abs: int = field(init=False)

    # latest ratio estimates
    lull_ratio:  float = field(init=False, default=0.0)
    high_ratio:  float = field(init=False, default=0.0)
    queue_ratio: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        # start from the hard-coded defaults in agent.policy
        from agent import policy
        self.lull_abs  = policy.LULL_OCCUPANCY
        self.high_abs  = policy.HIGH_OCCUPANCY
        self.queue_abs = policy.HIGH_QUEUE

    def generate_history(self, n: int = 120, seed: int = 0) -> tuple[list[float], list[float]]:
        """Synthetic occupancy + queue history for this shop."""
        rng = random.Random(seed)
        occ_hist, q_hist = [], []
        for t in range(n):
            wave = math.sin(t / 15.0)
            occ_frac = self.occ_mean + self.occ_amp * wave + rng.gauss(0, 0.05)
            occ_frac = max(0.0, min(1.0, occ_frac))
            q_frac = self.queue_mean * max(0.0, wave) + rng.gauss(0, 0.02)
            q_frac = max(0.0, min(0.5, q_frac))
            occ_hist.append(occ_frac * self.capacity)
            q_hist.append(q_frac * self.capacity)
        return occ_hist, q_hist

    def learn_local(self, seed: int = 0) -> None:
        """Estimate ratios from this shop's own history only."""
        occ_hist, q_hist = self.generate_history(seed=seed)
        ratios = estimate_ratios(occ_hist, q_hist, self.capacity)
        self.lull_ratio  = ratios["lull_ratio"]
        self.high_ratio  = ratios["high_ratio"]
        self.queue_ratio = ratios["queue_ratio"]
        self._apply_ratios(self.lull_ratio, self.high_ratio, self.queue_ratio)

    def apply_global(self, lull_ratio: float, high_ratio: float, queue_ratio: float) -> None:
        self._apply_ratios(lull_ratio, high_ratio, queue_ratio)

    def _apply_ratios(self, lull: float, high: float, queue: float) -> None:
        cap = self.capacity
        self.lull_abs  = max(1, int(lull  * cap))
        self.high_abs  = max(2, int(high  * cap))
        self.queue_abs = max(1, int(queue * cap))


# ---------------------------------------------------------------------------
# Federation round (pure functions, no network)
# ---------------------------------------------------------------------------

def fed_average(shops: list[Shop], scene_counts: list[int]) -> tuple[float, float, float]:
    """Weighted average of ratios across shops (weight = scenes observed)."""
    total_w = sum(max(c, 1) for c in scene_counts)
    lull  = sum(s.lull_ratio  * max(c, 1) for s, c in zip(shops, scene_counts)) / total_w
    high  = sum(s.high_ratio  * max(c, 1) for s, c in zip(shops, scene_counts)) / total_w
    queue = sum(s.queue_ratio * max(c, 1) for s, c in zip(shops, scene_counts)) / total_w
    return round(lull, 3), round(high, 3), round(queue, 3)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

HEADER = (
    f"{'Shop':<28} {'Cap':>4}  "
    f"{'lull_r':>7} {'high_r':>7} {'queue_r':>8}  "
    f"{'lull_abs':>9} {'high_abs':>9} {'queue_abs':>10}"
)
SEP = "─" * len(HEADER)


def _row(s: Shop, prefix: str = "") -> str:
    return (
        f"  {prefix}{s.name:<26} {s.capacity:>4}  "
        f"{s.lull_ratio:>7.3f} {s.high_ratio:>7.3f} {s.queue_ratio:>8.3f}  "
        f"{s.lull_abs:>9} {s.high_abs:>9} {s.queue_abs:>10}"
    )


# ---------------------------------------------------------------------------
# Simulation entry point
# ---------------------------------------------------------------------------

def main(rounds: int = 5, history: int = 120) -> None:
    shops = [
        Shop("City Espresso Bar",    capacity=10, occ_mean=0.80, occ_amp=0.15, queue_mean=0.20),
        Shop("Office Café",          capacity=20, occ_mean=0.55, occ_amp=0.40, queue_mean=0.15),
        Shop("Suburban Coffee Co.",  capacity=40, occ_mean=0.35, occ_amp=0.20, queue_mean=0.08),
    ]

    print("\n" + "═" * len(HEADER))
    print("  ☕  Golden Coffee — Federated Policy Simulation")
    print("═" * len(HEADER))
    print(f"\n  {len(shops)} shops  ·  {history} scenes/round  ·  {rounds} federation rounds")
    print(f"\n  Venues:")
    for s in shops:
        print(f"    {s.name:<28}  {s.capacity} seats  "
              f"avg occ {s.occ_mean*100:.0f}%  peak queue {s.queue_mean*100:.0f}%")

    # --- Round 0: local learning only ---
    print(f"\n{'─'*len(HEADER)}")
    print("  Round 0 — local estimates only (no federation yet)")
    print(f"{'─'*len(HEADER)}")
    print(f"  {HEADER}")
    for i, s in enumerate(shops):
        s.learn_local(seed=i * 42)
        print(_row(s))

    # --- Rounds 1..N: federated ---
    prev_global = (None, None, None)
    for rnd in range(1, rounds + 1):
        # each shop accumulates more history each round
        scene_counts = [history * rnd] * len(shops)
        for i, s in enumerate(shops):
            s.learn_local(seed=i * 42 + rnd)  # slightly varying data each round

        g_lull, g_high, g_queue = fed_average(shops, scene_counts)

        print(f"\n{'─'*len(HEADER)}")
        print(f"  Round {rnd} — after federation  "
              f"(global lull={g_lull:.3f}  high={g_high:.3f}  queue={g_queue:.3f})")
        if prev_global[0] is not None:
            dl = g_lull - prev_global[0]
            dh = g_high - prev_global[1]
            dq = g_queue - prev_global[2]
            print(f"              Δ from last round: "
                  f"lull {dl:+.3f}  high {dh:+.3f}  queue {dq:+.3f}")
        print(f"{'─'*len(HEADER)}")
        print(f"  {HEADER}")

        for s in shops:
            s.apply_global(g_lull, g_high, g_queue)
            print(_row(s))

        prev_global = (g_lull, g_high, g_queue)

    # --- Summary ---
    print(f"\n{'═'*len(HEADER)}")
    print("  Key insight")
    print(f"{'═'*len(HEADER)}")
    print(f"\n  Global ratios converged to: "
          f"lull={prev_global[0]:.3f}  high={prev_global[1]:.3f}  queue={prev_global[2]:.3f}")
    print()
    print(f"  {'Shop':<28}  {'capacity':>8}  {'lull_abs':>9}  {'high_abs':>9}  {'queue_abs':>10}")
    print(f"  {'─'*28}  {'─'*8}  {'─'*9}  {'─'*9}  {'─'*10}")
    for s in shops:
        print(f"  {s.name:<28}  {s.capacity:>8}  {s.lull_abs:>9}  {s.high_abs:>9}  {s.queue_abs:>10}")
    print()
    print("  Same ratio, different absolute numbers —")
    print("  shared knowledge about *what fraction* is a lull,")
    print("  each shop applies it to *their own* capacity.\n")


if __name__ == "__main__":
    main()
