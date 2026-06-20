"""FLock entry point — serves GoldenCoffeeModel via FlockSDK.

The FLock client mounts the participant's private dataset at /dataset.json,
which GoldenCoffeeModel.init_dataset() already reads.

Run in the FLock Docker container:
    python -m federated.flock_run

Local sanity check (no SDK, no port):
    python -m federated.flock_model
    python -m federated.music_flock_model
"""
from __future__ import annotations

from federated.flock_model import GoldenCoffeeModel

try:
    from flock_sdk import FlockSDK  # type: ignore
    print("[flock] flock_sdk found — starting FlockSDK server on :5000")
    FlockSDK(GoldenCoffeeModel()).run()
except ImportError:
    print("[flock] flock_sdk not installed.")
    print("  Install:    pip install flock-sdk")
    print("  Local demo: python -m federated.flock_model")
