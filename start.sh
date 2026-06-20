#!/bin/sh
# Container entrypoint for the Railway demo: run BOTH the backend hub and the
# actuator executor in one container so the deployed dashboard drives real devices.
#
# The executor (actuators/run.py) subscribes to the hub over the local WebSocket
# and, for set_lighting actions, drives the Xiaomi Wi-Fi light over the Mi cloud
# (XIAOMI_TRANSPORT=cloud — no Bluetooth/IR/Spotify hardware exists on Railway, and
# those actuators degrade gracefully). It retries the WS until uvicorn is up, so
# start order doesn't matter. It runs in the background; uvicorn is the foreground
# process (PID 1) that owns the port and signals — if the executor dies, the web
# app stays up.
set -e
PORT="${PORT:-8000}"

BACKEND_WS="ws://127.0.0.1:${PORT}/ws" python -m actuators.run &

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
