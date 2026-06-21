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

# Optional: replay a recorded live session so judges see a working model "in
# progress" (live occupancy / comfort / £ walked away / action feed) even with no
# camera attached. Gated on SAMPLE_REPLAY so local dev with a real camera is
# unaffected. Like the actuator it retries the local backend until uvicorn is up.
case "${SAMPLE_REPLAY:-}" in
  1|true|TRUE|yes|on)
    # The /app/data volume shadows any recording baked into the image there, and
    # data/ is excluded from the `railway up` upload, so on Railway the recording
    # ships under samples/ (outside the volume). Prefer an explicit REPLAY_FILE,
    # then the local data/ copy, then the baked samples/ copy.
    REPLAY_FILE="${REPLAY_FILE:-data/sample_session.jsonl}"
    [ -s "$REPLAY_FILE" ] || REPLAY_FILE="samples/sample_session.jsonl"
    BACKEND_URL="http://127.0.0.1:${PORT}" REPLAY_FILE="$REPLAY_FILE" python -m shared.replay &
    ;;
esac

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
