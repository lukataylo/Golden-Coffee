#!/usr/bin/env python3
"""Golden Coffee — single-command launcher.

Starts all services in the correct order and keeps them alive.
Camera source is read from (in priority order):
  1. data/config.json  (saved by the dashboard setup wizard)
  2. CAMERA_SOURCE env var
  3. command-line argument  --source <value>
  4. default: "0"  (built-in webcam)

Usage:
  python start.py                   # use saved/default camera
  python start.py --source 0        # force webcam
  python start.py --source rtsp://user:pass@192.168.1.x:554/stream1
  python start.py --mock            # use synthetic data instead of a camera
  python start.py --no-fl           # skip federated learning node
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG_PATH = DATA / "config.json"
PY = sys.executable  # same Python interpreter that launched this script


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def _resolve_camera(args) -> str:
    """Camera source priority: CLI arg > config.json > env var > "0"."""
    if args.source:
        return args.source
    cfg = _read_config()
    if cfg.get("camera_source"):
        return str(cfg["camera_source"])
    if os.environ.get("CAMERA_SOURCE"):
        return os.environ["CAMERA_SOURCE"]
    return "0"


def _wait_for_backend(timeout: int = 30) -> bool:
    """Block until the backend is accepting connections (or timeout)."""
    import urllib.request, urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_for_fed_server(timeout: int = 10) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ── process management ────────────────────────────────────────────────────────

_procs: list[subprocess.Popen] = []


def _spawn(label: str, cmd: list[str], **kwargs) -> subprocess.Popen:
    print(f"[start] ▶ {label}")
    p = subprocess.Popen(cmd, **kwargs)
    _procs.append(p)
    return p


def _stop_all() -> None:
    print("\n[start] shutting down…")
    for p in reversed(_procs):
        try:
            p.terminate()
        except Exception:
            pass
    for p in _procs:
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print("[start] all processes stopped.")


def _handle_signal(sig, frame) -> None:
    _stop_all()
    sys.exit(0)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Coffee — start all services")
    parser.add_argument("--source",  help="Camera source (overrides config.json)")
    parser.add_argument("--mock",    action="store_true", help="Use synthetic mock data instead of camera")
    parser.add_argument("--no-fl",   action="store_true", help="Skip federated learning node")
    parser.add_argument("--privacy", action="store_true", help="Run perception in --privacy-mode")
    args = parser.parse_args()

    camera = _resolve_camera(args)
    cfg = _read_config()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("=" * 58)
    print("  ☕  Golden Coffee — starting all services")
    print("=" * 58)
    print(f"  Camera source : {camera}" + (" (mock override)" if args.mock else ""))
    print(f"  Privacy mode  : {'on' if args.privacy else 'off'}")
    print(f"  FL node       : {'off' if args.no_fl else 'on'}")
    if cfg:
        zones = cfg.get("zones", {})
        if zones:
            print(f"  Saved zones   : {list(zones.keys())}")
    print()

    # 1 ── Backend hub (everything connects here first)
    _spawn("Backend hub", [
        PY, "-m", "uvicorn", "backend.main:app",
        "--host", "0.0.0.0", "--port", "8000",
    ])
    print("[start] waiting for backend…", end=" ", flush=True)
    if not _wait_for_backend():
        print("TIMEOUT — is port 8000 free?")
        _stop_all(); sys.exit(1)
    print("ready ✓")

    # 2 ── Federation server (local Flock.io stand-in)
    _spawn("Federation server", [PY, "-m", "federated.server"])
    _wait_for_fed_server(timeout=8)  # best-effort, fl_node retries anyway

    # 3 ── Data source: real camera or mock events
    if args.mock:
        _spawn("Mock events", [PY, "-m", "shared.mock_events"])
    else:
        perception_cmd = [PY, "-m", "perception.run", "--source", camera]
        if cfg.get("geometry_path") or (DATA / "geometry.json").exists():
            perception_cmd += ["--zones", "data/geometry.json"]
        if args.privacy:
            perception_cmd.append("--privacy-mode")
        _spawn(f"Perception  (source={camera})", perception_cmd)

    # 4 ── Agent (rule-based + Claude if ANTHROPIC_API_KEY set + FL model)
    _spawn("Agent", [PY, "-m", "agent.agent"])

    # 5 ── FL node (federated training — runs as background daemon)
    if not args.no_fl:
        _spawn("FL node", [PY, "-m", "federated.fl_node"])

    print()
    print("=" * 58)
    print("  All services running.")
    print("  Dashboard → http://localhost:8000")
    print("  Press Ctrl+C to stop everything.")
    print("=" * 58)
    print()

    # Monitor processes — restart any that crash unexpectedly
    restart_counts: dict[int, int] = {}
    while True:
        time.sleep(3)
        for p in list(_procs):
            if p.poll() is not None:  # process exited
                rc = p.returncode
                idx = _procs.index(p)
                restarts = restart_counts.get(idx, 0)
                if restarts < 3:
                    print(f"[start] process exited (rc={rc}), restarting… (attempt {restarts+1}/3)")
                    new_p = subprocess.Popen(p.args)
                    _procs[idx] = new_p
                    restart_counts[idx] = restarts + 1
                else:
                    print(f"[start] process failed 3 times — giving up on: {p.args[2] if len(p.args) > 2 else p.args}")


if __name__ == "__main__":
    main()
