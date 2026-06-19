"""Federation server — collects capacity-normalised ratio proposals from shop nodes
and returns the weighted-average global ratios.

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

app = FastAPI(title="Golden Coffee Federation Server")
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
    return {"ok": True, "n_nodes": len(_nodes)}


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
