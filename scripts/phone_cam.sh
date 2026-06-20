#!/usr/bin/env bash
# Golden Coffee — run the perception pipeline from a phone camera over USB (DroidCam).
# Re-arms the adb port-forward, waits for DroidCam to actually serve the stream,
# then starts perception with low-latency defaults.
#
#   scripts/phone_cam.sh                  # 480p inference, fast face-blur (defaults)
#   scripts/phone_cam.sh --imgsz 384      # even snappier
#   scripts/phone_cam.sh --zones zones.json
#
# Full guide + troubleshooting: DROIDCAM.md
set -uo pipefail

PORT="${DROIDCAM_PORT:-4747}"
URL="http://127.0.0.1:${PORT}/video"
ADB="$(command -v adb || echo "$HOME/Library/Android/sdk/platform-tools/adb")"

echo "▶ Golden Coffee — phone camera over USB (DroidCam)"

# 1) adb installed?
if ! "$ADB" version >/dev/null 2>&1; then
  echo "✗ adb not found. Install it once:  brew install android-platform-tools"
  exit 1
fi

# 2) phone connected AND authorized for debugging?
state="$("$ADB" get-state 2>/dev/null || true)"
if [ "$state" != "device" ]; then
  echo "✗ No authorized phone over USB. Check:"
  echo "    - cable plugged in; phone unlocked"
  echo "    - Settings > Developer options > USB debugging ON"
  echo "    - tap 'Allow' on the 'Allow USB debugging?' prompt"
  "$ADB" devices
  exit 1
fi

# 3) (re)arm the USB tunnel for the DroidCam port
"$ADB" forward --remove "tcp:${PORT}" >/dev/null 2>&1 || true
"$ADB" forward "tcp:${PORT}" "tcp:${PORT}" >/dev/null
echo "✓ USB tunnel :${PORT} ready"

# 4) wait for DroidCam to actually serve frames (the app must be in the FOREGROUND)
echo "… open the DroidCam app and keep it in the foreground (screen on)"
ok=""
for i in $(seq 1 30); do
  code="$(curl -s -m 2 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then ok=1; echo "✓ stream live → ${URL}"; break; fi
  printf '  waiting (%2ss)…\r' "$i"
  sleep 1
done
if [ -z "$ok" ]; then
  echo ""
  echo "✗ DroidCam isn't serving on :${PORT} (HTTP ${code:-000})."
  echo "  Fix on the phone, then re-run this script:"
  echo "    - open the DroidCam app and make sure the camera preview is RUNNING"
  echo "    - keep it FOREGROUND + screen on (it drops :${PORT} when backgrounded/locked)"
  echo "    - lower the in-app resolution to 480p for low latency"
  exit 1
fi

# 5) launch perception with low-latency defaults (GPU + 480 + fast head-blur)
echo "▶ starting perception — Ctrl-C to stop"
exec python3 -m perception.run --source "$URL" --imgsz 480 "$@"
