"""Spotify volume control — the easiest real-device wow.

Pre-hackathon checklist (do this BEFORE the event):
  - Spotify PREMIUM account (required for any playback control).
  - Create an app at developer.spotify.com → get client id/secret.
  - Set redirect URI to  http://127.0.0.1:8888/callback   (NOT localhost).
  - Run `python -m actuators.spotify 40` once to do the OAuth consent; the token
    is cached in `.spotipy-cache` so later runs are non-interactive.
  - Open Spotify on a real device (desktop/phone/speaker) and press play so there
    is an ACTIVE device — volume control fails with no active device.

Env: SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
"""
from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

REDIRECT = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
SCOPE = "user-modify-playback-state user-read-playback-state"


def _client():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(redirect_uri=REDIRECT, scope=SCOPE, cache_path=".spotipy-cache")
    )


def set_volume(percent: int) -> bool:
    """Set the active device volume (0-100). Returns False on any failure so the
    demo degrades gracefully instead of crashing."""
    percent = max(0, min(100, int(percent)))
    if not os.environ.get("SPOTIPY_CLIENT_ID"):
        # No creds: don't construct SpotifyOAuth (it would try interactive auth).
        print(f"[spotify] (not configured) would set volume -> {percent}")
        return False
    try:
        sp = _client()
        devices = sp.devices().get("devices", [])
        if not devices:
            print("[spotify] no active device — open Spotify and press play")
            return False
        sp.volume(percent)
        print(f"[spotify] volume -> {percent}")
        return True
    except Exception as exc:
        print(f"[spotify] failed: {exc}")
        return False


if __name__ == "__main__":
    set_volume(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
