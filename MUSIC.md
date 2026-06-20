# 🎵 Local music model — the room picks the playlist

Coffee Steve already tunes music **volume** from the scene. The **local music
model** (`agent/music_model.py`) goes a step further: it chooses *what's
actually playing* — the mood/genre, tempo (BPM) and the Spotify playlist — from
the same anonymized scene data, entirely **on-device**.

> Privacy-first, like the rest of the system: the model only ever sees aggregate
> counts and room energy — never identities. It runs with **no network and no
> API key**, so the MVP keeps working offline.

## 🔊 The player: a self-hosted sound library (default), Spotify optional

The **on-device model below decides *what mood* should play**; the **player that
actually makes sound** is our own hosted, royalty-free library — so music works
with **zero setup and no account**. Spotify is an optional fallback.

- **Tier-1 = Coffee Steve Sound Library.** Six café tracks (Kevin MacLeod,
  CC-BY 4.0) re-encoded to 112 kbps live in `dashboard/audio/`, catalogued in
  `dashboard/audio/manifest.json` and served by `GET /music/library`. Each track's
  `mood` maps 1:1 to the model's moods, so Auto mode can pick the matching track.
- **The dashboard player** (Music tile → **Custom**) defaults to the library:
  in-browser `<audio>`, 6 mood presets, transport + volume. A **Source dropdown**
  toggles to **Spotify** (Web Playback SDK, lazy-loaded — only connects when chosen).
- The player lives in its **own isolated `<script>`** so an unrelated dashboard
  error can never take down music streaming.
- Attribution shows in the player UI and in [`dashboard/audio/CREDITS.md`](dashboard/audio/CREDITS.md).

## What it is

A small **softmax (multinomial-logistic) classifier** over a handful of
interpretable scene features:

| feature | meaning |
|---|---|
| `occ`, `busy`, `lull` | occupancy (normalized + busy/quiet flags) |
| `queue`, `rush` | queue length + "queue building" flag (≥ 3) |
| `energy` | aggregate room movement (0–1) |
| `morning` / `afternoon` / `evening` | time-of-day (covers all 24h; 23:00–05:00 reads as evening) |

It scores six café **moods** and (with hysteresis) recommends one:

| mood | when | vibe | ~BPM | vol |
|---|---|---|---|---|
| `sunrise_acoustic` | quiet morning | warm acoustic / coffeehouse | 84 | 52 |
| `daytime_focus` | steady daytime | mellow indie / lofi | 94 | 48 |
| `upbeat_lift` | flat / low-energy room | bright, feel-good | 116 | 60 |
| `rush_flow` | queue building | steady groove, keeps the line moving | 104 | 46 |
| `busy_calm` | full room | soft downtempo, stays talkable | 80 | 38 |
| `evening_warm` | evening / late night | warm jazz & soul wind-down | 76 | 44 |

**Hysteresis** (`SWITCH_MARGIN`) means a new mood has to *clearly* beat the
current one before the track changes, so the music doesn't flap on every tick.

## It's trained locally (no cloud)

The weights are learned by pure-Python softmax gradient descent on a
labelled dataset synthesized across occupancy / queue / energy / hour
(`train()` in the module — no numpy, no API). The learned weights are baked into
`DEFAULT_WEIGHTS` so import is instant and deterministic; ~98% agreement with the
labelling oracle.

```bash
python -m agent.music_model            # demo: roll moods over mock scenes
python -m agent.music_model --train    # refit weights -> agent/music_weights.json (+ prints them)
```

If `agent/music_weights.json` exists it's loaded in preference to the baked
defaults — so you can re-train on **real café data** without touching code.

## How it flows through the system

```
SceneEvent ──> MusicModel.recommend() ──> agent/policy.py emits
   set_music {mood, playlist_uri, descriptors, bpm, energy, volume}
        ──> backend /action ──> /ws ──> actuators/spotify.set_music()
                                         └─> dashboard shows the live mood
```

* **Contract:** a new `set_music` action in `shared/schemas.py` (alongside the
  existing `set_music_volume`, which still handles loudness).
* **Policy:** `agent/policy.py` runs the model every scene and fires `set_music`
  only when the mood *switches* (debounced on `music_mood`, 120 s).
* **Claude path:** `set_music` is also a Claude tool — Claude picks a `mood` and
  the agent expands it to the full directive from the catalogue.
* **Actuator:** `actuators/spotify.set_music()` starts the playlist on the active
  device (and sets volume). With no `playlist_uri`, it searches Spotify using the
  mood `descriptors`. Degrades gracefully with no creds / no active device.
* **Dashboard:** the Comfort → Music tile shows the current mood + BPM, and the
  action feed logs each switch with its rationale.

## Configuring playlists

Each mood ships with a sensible default public Spotify playlist URI. Override any
of them per deploy — e.g. for the demo venue's own playlists:

```bash
MUSIC_PLAYLIST_RUSH_FLOW=spotify:playlist:xxxxxxxxxxxx
MUSIC_PLAYLIST_BUSY_CALM=spotify:playlist:yyyyyyyyyyyy
# ...one MUSIC_PLAYLIST_<MOOD> per mood as needed
```
