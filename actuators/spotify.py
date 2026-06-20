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


def set_music(
    playlist_uri: str = "",
    descriptors: str = "",
    volume: int | None = None,
    mood: str = "",
) -> bool:
    """Switch what's playing to match a mood chosen by the local music model.

    Starts playback of `playlist_uri` on the active device (and optionally sets
    `volume`). If no URI is given, falls back to searching Spotify for a playlist
    matching `descriptors`. Degrades gracefully (returns False) when creds or an
    active device are missing, so the demo never crashes on music.
    """
    if not os.environ.get("SPOTIPY_CLIENT_ID"):
        print(f"[spotify] (not configured) would play mood={mood!r} "
              f"uri={playlist_uri or '(search: '+descriptors+')'} vol={volume}")
        return False
    try:
        sp = _client()
        devices = sp.devices().get("devices", [])
        if not devices:
            print("[spotify] no active device — open Spotify and press play")
            return False
        device_id = next((d["id"] for d in devices if d.get("is_active")), devices[0]["id"])

        uri = playlist_uri
        if not uri and descriptors:
            res = sp.search(q=descriptors, type="playlist", limit=1)
            items = (res.get("playlists", {}) or {}).get("items", []) or []
            if items:
                uri = items[0]["uri"]
        if not uri:
            print(f"[spotify] no playlist for mood={mood!r}; leaving playback as-is")
            return False

        sp.start_playback(device_id=device_id, context_uri=uri)
        if volume is not None:
            sp.volume(max(0, min(100, int(volume))), device_id=device_id)
        print(f"[spotify] mood={mood!r} -> {uri}" + (f" @ vol {volume}" if volume is not None else ""))
        return True
    except Exception as exc:
        print(f"[spotify] set_music failed: {exc}")
        return False


def verify_playlists() -> None:
    """Check every mood playlist URI resolves on Spotify. Run after OAuth setup."""
    from agent.music_model import MOODS
    try:
        sp = _client()
    except Exception as exc:
        print(f"[spotify] auth failed: {exc}")
        return
    ok = 0
    for key, mood in MOODS.items():
        uri = mood.playlist
        try:
            pid = uri.split(":")[-1]
            info = sp.playlist(pid, fields="name,tracks.total")
            print(f"  ✓ {key:20s}  '{info['name']}'  ({info['tracks']['total']} tracks)  {uri}")
            ok += 1
        except Exception as exc:
            print(f"  ✗ {key:20s}  FAILED: {exc}  {uri}")
    print(f"\n{ok}/{len(MOODS)} playlists verified.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        verify_playlists()
    else:
        set_volume(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
