"""Walrus (Sui ecosystem) decentralized blob storage — tamper-proof ops evidence.

Caffe Steve anchors its anonymized metrics history + the agent ACTION audit trail
to Walrus so a café's AI decisions are independently, verifiably stored — privacy-
first (aggregate numbers + hashes, never faces). Uses the PUBLIC testnet
publisher/aggregator: a pure-HTTP path with no wallet or Move needed, so it works
in a demo immediately.

Store:  PUT  {PUBLISHER}/v1/blobs?epochs=N   (body = bytes)  -> blobId
Read:   GET  {AGGREGATOR}/v1/blobs/{blobId}

CLI:  python -m onchain.walrus store data/metrics.jsonl
      python -m onchain.walrus read <blobId>
"""
from __future__ import annotations

import os
import sys

import httpx

PUBLISHER = os.environ.get("WALRUS_PUBLISHER", "https://publisher.walrus-testnet.walrus.space")
AGGREGATOR = os.environ.get("WALRUS_AGGREGATOR", "https://aggregator.walrus-testnet.walrus.space")


def store_blob(data: bytes, epochs: int = 5, timeout: float = 30.0) -> dict:
    """Store bytes on Walrus testnet. Returns {blob_id, size, end_epoch, read_url}."""
    r = httpx.put(f"{PUBLISHER}/v1/blobs", params={"epochs": epochs}, content=data, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    # Response is either newlyCreated (first time) or alreadyCertified (dedup).
    info = j.get("newlyCreated") or j.get("alreadyCertified") or {}
    obj = info.get("blobObject") or info
    blob_id = obj.get("blobId") or info.get("blobId") or j.get("blobId")
    if not blob_id:
        raise RuntimeError(f"no blobId in Walrus response: {j}")
    return {
        "blob_id": blob_id,
        "size": obj.get("size", len(data)),
        "end_epoch": (obj.get("storage") or {}).get("endEpoch") or info.get("endEpoch"),
        "read_url": f"{AGGREGATOR}/v1/blobs/{blob_id}",
    }


def read_blob(blob_id: str, timeout: float = 30.0) -> bytes:
    r = httpx.get(f"{AGGREGATOR}/v1/blobs/{blob_id}", timeout=timeout)
    r.raise_for_status()
    return r.content


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "store":
        with open(sys.argv[2], "rb") as f:
            res = store_blob(f.read())
        print(res)
    elif len(sys.argv) >= 3 and sys.argv[1] == "read":
        sys.stdout.buffer.write(read_blob(sys.argv[2]))
    else:
        print("usage: python -m onchain.walrus store <file> | read <blobId>")
