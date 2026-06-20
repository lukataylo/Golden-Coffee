# Coffee Steve Sound Library — credits

The hosted music library ships royalty-free tracks so the player works with zero
setup (Spotify is an optional fallback). All tracks below are by **Kevin MacLeod**
(incompetech.com), licensed under **Creative Commons: By Attribution 4.0**
(https://creativecommons.org/licenses/by/4.0/). Attribution is shown in the
dashboard player UI and reproduced here.

| File | Track | Mood | Use |
|---|---|---|---|
| morning-acoustic.mp3 | Cattails | sunrise_acoustic | Warm acoustic — gentle mornings |
| daytime-focus.mp3 | Local Forecast – Elevator | daytime_focus | Mellow — steady working hours |
| upbeat-lift.mp3 | Carefree | upbeat_lift | Bright feel-good — lift a flat room |
| rush-bossa.mp3 | Bossa Antigua | rush_flow | Easy bossa — keeps the line moving |
| busy-calm.mp3 | Wallpaper | busy_calm | Soft downtempo — talkable when full |
| evening-jazz.mp3 | Hep Cats | evening_warm | Warm swing/jazz — evening wind-down |

Tracks were re-encoded to 112 kbps stereo MP3 to keep the deploy light; the
originals are available at incompetech.com. If you swap a track, update
`manifest.json` (the player and the agent's mood mapping both read it).

The moods map 1:1 to the on-device music model in `agent/music_model.py`, so the
agent's auto-selected mood drives which library track plays.
