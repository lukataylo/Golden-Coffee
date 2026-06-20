# Golden Coffee × FLock

Port of our homegrown federated-learning sim (`federated/`) onto FLock's
`FlockModel` interface so the work can be submitted to a FlockTask and claim the
FLock bounty. Lives in `federated/flock_model.py`. The other sim files
(`node.py`, `server.py`, `sim.py`) are untouched — this is a faithful re-port,
not a rewrite.

## What FLock is

[FLock.io](https://flock.io) is a decentralised / on-chain **federated learning**
network. A *FlockTask* coordinates many participants who each:

1. **train** a model locally on their own private data and submit only the
   resulting model parameters (opaque `bytes`) — raw data never leaves the node;
2. an **aggregator** averages the submitted parameters into a global model;
3. **proposers / voters** **evaluate** the global model and stake on its quality.

Participants run their training code as a Docker image (built against the
`flock-sdk` package) whose image hash is registered on-chain via IPFS. The SDK
(`FlockSDK(model).run()`) exposes the model over a tiny Flask `/call` endpoint
that the FLock client drives with `method ∈ {train, evaluate, aggregate}`.

## Why our sim maps onto this cleanly

Our café sim already *is* federated learning with the same privacy guarantee:
raw venue video never leaves the shop; nodes share only three
capacity-normalised policy ratios `{lull, high, queue}`, and the server returns a
**scene-weighted mean**. Sharing *ratios* (fractions of capacity) instead of raw
counts lets a 10-seat espresso bar and a 40-seat café teach each other
meaningfully. That is exactly FLock's train → aggregate → evaluate loop.

## Call-path mapping (FlockModel → existing untouched sim)

| `FlockModel` method            | Backed by                                                   | What it does |
|--------------------------------|-------------------------------------------------------------|--------------|
| `init_dataset(path)`           | reads FLock's mounted `dataset.json`; synthetic fallback mirrors `sim.Shop.generate_history` | load this venue's recent `{occupancy, queue_len}` history |
| `train(parameters[, dataset])` | **`federated.node.estimate_ratios`** (P20/P80 percentile ratios) | estimate `{lull,high,queue}` ratios from local history → JSON `bytes` |
| `aggregate(parameters_list)`   | **`federated.server._aggregate` / `sim.fed_average`**       | scene-weighted mean of the ratio vectors → `bytes` |
| `evaluate(parameters[, dataset])` | new held-out scorer, reusing `estimate_ratios` for the local gold standard | agreement between the global ratios and the venue's own locally-optimal lull/busy labelling on a held-out window → float `[0,1]` |

Serialisation is human-inspectable JSON bytes:
`{"lull_ratio":..,"high_ratio":..,"queue_ratio":..,"n_scenes":..}`. `n_scenes`
is the aggregation weight, so high-data venues carry more influence — identical
to the server's weighting.

`train()` deliberately ignores the incoming global `parameters` (like
`sim.Shop.learn_local`, each node re-estimates from its own data every round);
the cross-venue blending lives entirely in `aggregate()`.

### Interface note

The installed `flock-sdk` (v0.0.3) calls `train(parameters)` /
`evaluate(parameters)` with parameters only (the dataset comes from
`init_dataset`). Our methods take an optional second `dataset` arg defaulting to
the loaded history, so they satisfy both the SDK's real signature and the
bounty-brief signature.

### flock-sdk install status

`flock-sdk==0.0.3` installs **cleanly** on Python 3.11 / macOS — it pulls only
`flask`, `werkzeug`, `loguru`, `blinker`, `itsdangerous` (**no torch**, light).
Even so, the `flock_sdk` import in `flock_model.py` is **lazy/optional**: if the
package is absent the module still imports and the local demo still runs, falling
back to a minimal base class. With the package present, `GoldenCoffeeModel` is a
genuine `FlockModel` subclass (verified) ready for `FlockSDK(model).run()`.

## Run the local demo (safe fallback, no platform / no port)

```bash
.venv/bin/python -m federated.flock_model
```

This instantiates the model for 3 venues, has each `train()` locally, runs
`aggregate()` into a global model, then `evaluate()`s it per venue — printing the
per-venue params, the aggregated global ratios, and per-venue + mean eval scores.
No network, no FLock platform, no bound port. Example output: global
`lull≈0.33 high≈0.78 queue≈0.12`, mean eval accuracy ≈ 0.63 (the always-busy
espresso-bar outlier scores lowest, an honest signal of where the global
compromise diverges).

## Remaining steps for the full on-chain claim

The model is platform-ready; what's left is packaging and registering it. None of
this is done here (no Docker build, no network, no on-chain tx):

1. **Entry point** — add a thin runner that serves the model:
   ```python
   # federated/flock_run.py
   from flock_sdk import FlockSDK
   from federated.flock_model import GoldenCoffeeModel
   if __name__ == "__main__":
       FlockSDK(GoldenCoffeeModel()).run()   # binds 0.0.0.0:5000 — container only
   ```
2. **Dockerfile** (separate from the repo's backend Dockerfile) —
   `FROM python:3.11-slim`, `pip install flock-sdk`, copy `federated/` + `shared/`
   + `agent/policy.py`, `CMD ["python","-m","federated.flock_run"]`, `EXPOSE 5000`.
   The FLock client mounts the participant's private dataset at `/dataset.json`,
   which `init_dataset` already reads.
3. **Build & push the image** — `docker build -t <user>/golden-coffee-flock .`
   then push to a registry (or use FLock's `upload_image.sh` helper from the
   `flock-sdk` examples) to get the image digest.
4. **Pin to IPFS** — upload the image manifest / metadata to IPFS via
   **Pinata** (`pinata.cloud`) and capture the CID.
5. **Create the FlockTask on-chain** — register the task pointing at the IPFS CID,
   set rounds / staking, then join as a participant (and/or proposer/voter). The
   FLock client pulls the image and drives `/call` with train/evaluate/aggregate.
6. **Submit for the bounty** — link the FlockTask + repo `federated/flock_model.py`.

Until steps 1-5 are wired, `python -m federated.flock_model` is the demonstrable,
self-contained proof that the port works end-to-end.
