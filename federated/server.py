"""Federation server — dual-purpose aggregation hub for Caffe Steve.

1. Ratio federation (existing): collects P20/P80 occupancy/queue ratios from
   each venue and returns a capacity-weighted global average that the agent
   uses to tune its rule-based policy thresholds.

2. Model federation (new): implements FedAvg over CaféComfortNet weight deltas.
   Each venue submits a DP-sanitised gradient delta; the server accumulates them
   and returns the averaged global weights. This is the Flock.io-compatible path:
   when FLOCK_API_KEY is set, fl_node.py talks directly to Flock.io instead of
   this server — but this server acts as a local stand-in for development and
   single-venue demos.

UK Sovereign AI: this server can be self-hosted by a café chain on UK
infrastructure. No customer data flows through it — only gradient deltas
and anonymised ratios.

Run:  python -m federated.server             (default port 8001)
      python -m federated.server --port 9000

Each shop reports what fraction of its capacity triggers a lull / busy / long-queue
condition.  The server averages these ratios (weighted by how many scenes each node
has observed) so high-data shops have more influence than freshly-started ones.

Run:  python -m federated.server             (default port 8001)
      python -m federated.server --port 9000
"""
from __future__ import annotations

import argparse
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Caffe Steve Federation Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# node_id -> latest submission
_nodes: dict[str, dict] = {}


class RatioUpdate(BaseModel):
    node_id: str
    capacity: int          # total seats in this venue
    lull_ratio: float      # occupancy / capacity below which room feels empty
    high_ratio: float      # occupancy / capacity above which room is packed
    queue_ratio: float     # queue_len / capacity above which queue is long
    n_scenes: int = 0      # scenes observed — used as weight
    ts: float = 0.0


class GlobalRatios(BaseModel):
    lull_ratio: float
    high_ratio: float
    queue_ratio: float
    n_nodes: int
    ts: float


def _aggregate() -> GlobalRatios:
    nodes = list(_nodes.values())
    if not nodes:
        # sensible defaults before any node has checked in
        return GlobalRatios(lull_ratio=0.30, high_ratio=0.80, queue_ratio=0.15,
                            n_nodes=0, ts=time.time())
    total_w = sum(max(n.get("n_scenes", 1), 1) for n in nodes)
    lull  = sum(n["lull_ratio"]  * max(n.get("n_scenes", 1), 1) for n in nodes) / total_w
    high  = sum(n["high_ratio"]  * max(n.get("n_scenes", 1), 1) for n in nodes) / total_w
    queue = sum(n["queue_ratio"] * max(n.get("n_scenes", 1), 1) for n in nodes) / total_w
    return GlobalRatios(
        lull_ratio=round(lull, 3),
        high_ratio=round(high, 3),
        queue_ratio=round(queue, 3),
        n_nodes=len(nodes),
        ts=time.time(),
    )


@app.post("/update", response_model=GlobalRatios)
def update(payload: RatioUpdate) -> GlobalRatios:
    """Node submits its latest ratio estimates; returns the updated global average."""
    _nodes[payload.node_id] = payload.model_dump()
    g = _aggregate()
    print(
        f"[fed-server] {payload.node_id} (cap={payload.capacity}) "
        f"lull={payload.lull_ratio:.3f} high={payload.high_ratio:.3f} "
        f"queue={payload.queue_ratio:.3f} n_scenes={payload.n_scenes} "
        f"→ global lull={g.lull_ratio:.3f} high={g.high_ratio:.3f} "
        f"queue={g.queue_ratio:.3f} ({g.n_nodes} nodes)"
    )
    return g


@app.get("/status")
def status() -> dict:
    return {"nodes": _nodes, "global": _aggregate().model_dump()}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "n_nodes": len(_nodes), "fl_round": _fl_state["round"]}


# ---------------------------------------------------------------------------
# Model federation — FedAvg over CaféComfortNet weight deltas
# ---------------------------------------------------------------------------

import numpy as np
from pathlib import Path

_FL_MODEL_PATH = Path("data/fl_global_model.json")

# In-memory FL state
_fl_state: dict = {
    "round": 0,
    "pending_deltas": {},   # node_id -> {delta, n_samples, loss}
    "global_weights": None, # current FedAvg weights
}


def _fedavg(deltas: list[dict], weights: list[int]) -> dict:
    """Weighted average of weight deltas (FedAvg). Weights = n_samples per node."""
    total = sum(weights)
    if total == 0:
        return {}
    result = {}
    for k in deltas[0]:
        arrays = [np.array(d[k]) * w / total for d, w in zip(deltas, weights)]
        result[k] = np.sum(arrays, axis=0).tolist()
    return result


class FLUpdate(BaseModel):
    node_id:   str
    capacity:  int
    n_samples: int
    loss:      float
    delta:     dict      # DP-sanitised weight delta from this node


@app.post("/fl/update")
def fl_update(payload: FLUpdate) -> dict:
    """Receive a weight delta from a venue node; return current global model."""
    _fl_state["pending_deltas"][payload.node_id] = {
        "delta": payload.delta,
        "n_samples": payload.n_samples,
        "loss": payload.loss,
    }
    pending = _fl_state["pending_deltas"]
    n_nodes = len(pending)

    # Run FedAvg whenever we have at least 2 nodes (or 1 in solo mode)
    if n_nodes >= 1:
        deltas  = [v["delta"]     for v in pending.values()]
        samples = [v["n_samples"] for v in pending.values()]
        avg_delta = _fedavg(deltas, samples)

        # Apply delta to current global weights (or initialise from first delta)
        if _fl_state["global_weights"] is None:
            _fl_state["global_weights"] = avg_delta
        else:
            for k in avg_delta:
                gw = np.array(_fl_state["global_weights"][k])
                gw += np.array(avg_delta[k])
                _fl_state["global_weights"][k] = gw.tolist()

        _fl_state["round"] += 1
        _fl_state["pending_deltas"].clear()

        # Persist
        _FL_MODEL_PATH.parent.mkdir(exist_ok=True)
        _FL_MODEL_PATH.write_text(
            __import__("json").dumps(_fl_state["global_weights"], indent=2)
        )

        avg_loss = sum(v["loss"] * v["n_samples"] for v in pending.values()) / max(sum(samples), 1)
        print(
            f"[fed-server] FL round {_fl_state['round']}  "
            f"nodes={n_nodes}  avg_loss={avg_loss:.4f}  "
            f"global_model_updated=True"
        )

    return {"round": _fl_state["round"], "weights": _fl_state["global_weights"]}


@app.get("/fl/model")
def fl_model() -> dict:
    """Return the current global model weights (or empty if no rounds yet)."""
    if _fl_state["global_weights"] is not None:
        return {"round": _fl_state["round"], "weights": _fl_state["global_weights"]}
    if _FL_MODEL_PATH.exists():
        w = __import__("json").loads(_FL_MODEL_PATH.read_text())
        _fl_state["global_weights"] = w
        return {"round": _fl_state["round"], "weights": w}
    return {"round": 0, "weights": None}


@app.get("/fl/status")
def fl_status() -> dict:
    return {
        "round": _fl_state["round"],
        "pending_nodes": list(_fl_state["pending_deltas"].keys()),
        "has_global_model": _fl_state["global_weights"] is not None,
    }


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
