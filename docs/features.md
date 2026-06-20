# ✨ Features

Every Golden Coffee action follows one rule: **it must help the customer or the staff.** No
employee scoring, no demographics, no surge pricing, no using discomfort to move people along.
Below is what's actually built, grounded in the code.

## 🌡️ Comfort Index

A live, single read of how the room *feels*, shown on the dashboard (`computeComfort()` in
`dashboard/index.html`). It blends the current music level, lighting (brightness + warmth),
air/temperature setpoint, and scent intensity into one 0–100 figure with a friendly label
("Feels great"), plus a "comfort through the day" trend. It's the headline that reframes the
product around guest wellbeing rather than money — the number a judge can glance at and *get* it.

## 🎛️ Ambient autopilot

The agent (`agent/policy.py`) tunes four sensory channels to the room and the time of day:

- **🎶 Music** — softens volume when the room is busy and buzzy so it stays talkable; lifts it in
  a flat/low-energy room. (See the music model below for *what* plays.)
- **💡 Lighting** — brightness + warmth, time-aware: bright/neutral in the morning rush,
  warm-neutral midday, dim/warm for the afternoon wind-down; bright/neutral when busy.
- **🌿 Scent** — fresh citrus to keep a full room pleasant; warm vanilla for a cosy lull;
  time-aware otherwise.
- **❄️ Temperature** — a four-component thermal model produces an **absolute °C target**:
  1. **Seasonal baseline** from the outdoor thermometer (warmer baseline in winter, cooler in summer);
  2. **Occupancy load** — cools a sustained-busy room, nudges warmer when near-empty (gated so a
     brief spike doesn't blast the AC);
  3. **Humidity** offset from indoor RH;
  4. **Psychological** offset — a warm, dim, vanilla-scented room *feels* warmer, so the heating
     setpoint can drop to save energy.
  Hysteresis (±0.5 °C) stops it thrashing, and the room silently drifts back to baseline after
  10 quiet minutes.

Every action carries a plain-English **rationale** shown live on the dashboard, and each rule is
**debounced** per-rule so distinct alerts don't mask each other.

## 🎵 On-device music model

`agent/music_model.py` is a small **softmax (multinomial-logistic) classifier** over interpretable
scene features (occupancy, busy/lull flags, queue/rush, room energy, time of day). It scores **six
café moods** and — with hysteresis so it doesn't flip-flop — recommends one, expanding it into a
full directive: mood label, BPM, energy, volume, descriptors, and a Spotify playlist. It runs with
**no network and no API key**, so the MVP keeps working offline. Two modes:

- **Auto** — the model picks the mood from the room's data.
- **Custom** — staff take control (Spotify/YouTube/playlist URL); the agent silences its music actions.

Full write-up: [MUSIC.md](../MUSIC.md).

## 🚨 Rush copilot

Protects speed-of-service from the queue (`agent/policy.py`):

- Queue at/over threshold → **notify staff** to open a second till — *before* customers leave.
- If **walk-offs are rising** while the queue is already long, the alert escalates to **urgent**
  ("Queue at 6 and 2 just walked off — open a second till now").
- The **£ walked away** today is surfaced (avg ticket × abandons) — the ownable headline ("you
  lost ~£120 today to the queue").

Walk-offs alone never trigger an alert (people leave for personal reasons) — only when the queue is
plausibly the cause.

## 🍽️ Table service SLAs

Per-table, per-rule timers with cooldowns:

- **Dirty-table hygiene** — a guest sitting at an uncleared table ≥ 3 min → "clear this table."
- **Order-taking** — `waiting_to_order` ≥ 6 min → "Table T3 has been waiting 6 mins to order."
- **Bill request** — `requested_bill` ≥ 4 min → "bring the bill immediately."
- **Overdue catch-all** — any generic un-served table → serve before they give up.

Urgent ones can route to staff wearables / POS channels in the action payload.

## 🧽 Cleaning cadence

Tracks both **bussing** (vacated tables that need clearing) and **zone cleaning** (e.g. restroom)
by **usage *and* elapsed time** — alerting staff when a zone hits its "overdue" status or tables
pile up.

## 🏷️ Quiet-period markdown (never surge)

After a **sustained 10-minute lull**, the agent marks down a set of perishable items (today's
pastry, sandwiches, etc.) on the menu board with `update_menu_price` — discount scaled to how empty
the room is, and `never_surge: True` enforced per item so prices only ever go **down**. It resets to
base price when the room fills again, and pings staff so the POS rings the right price. There's also
a lighter "fill-the-trough" off-peak promo (`push_discount`) for quiet periods.

## 📈 Footfall forecast

`agent/forecast.py` keeps a simple time-series over occupancy by hour and, debounced to once every
10 minutes, emits a low-priority staffing heads-up when the next hour looks busier — the
recurring-value feature for an owner planning prep and staff.

## 📱 Scan-to-3D PWA (`dashboard/scan/`)

An installable Progressive Web App (service worker + manifest, Three.js vendored offline):

- **Pick a layout** — five ready-made coffee-shop presets (Corner Café, Open Roastery, Grab & Go
  Kiosk, Bistro + Patio, Long Bar Espresso) load straight into a live 3D twin you can orbit.
- **Scan your own (advanced)** — capture/upload a floorplan photo and trace the room outline,
  zones (entry/queue/counter/seating), tables, and restroom by hand.
- **Push to live** — exports the normalized `zones.json` geometry and `POST`s it to `/geometry`, so
  perception and the dashboard immediately use the **real venue layout** instead of placeholder bands.

The same geometry shape powers the dashboard's **3D digital twin** (`dashboard/floor3d.js`): zone
occupancy heat, anonymous track dots, table status, a staff-alert beacon, and the agent's comfort
actions made visible (lights warm/dim, music ring pulses). It falls back to a 2D heatmap if WebGL is
unavailable. Background research: [FLOORMAP_RESEARCH.md](../FLOORMAP_RESEARCH.md).

## 🌐 Federated learning

Golden Coffee treats each venue as a node in a café federation (`agent/agent.py` + `federated/`),
in two layers — **without any footage ever leaving a shop**:

- **Layer 1 — thresholds.** Each round, a venue estimates its own capacity-normalized
  `{lull, high, queue}` ratios from recent scenes, aggregates them with the network (a
  scene-weighted mean), and patches its own absolute thresholds. Sharing *ratios* lets a 10-seat
  espresso bar and a 40-seat café teach each other.
- **Layer 2 — music.** The same round FedAvgs the venue's local music-model fit into the running
  global weights, so federation also tunes *which moods play*.

A `tune_policy` action surfaces it on the feed ("Network learning (4 cafés): busy threshold 8→9…
only ratios + model weights were shared — no footage ever leaves a venue"). For the demo, peer
venues are simulated; the work is ported onto FLock's interface (see [bounties.md](bounties.md)).

## ⛓️ On-chain audit trail

`POST /onchain/snapshot` anchors the anonymized metrics history + the agent's action audit trail
(with rationales) to **Walrus** (Sui ecosystem) and returns a public, verifiable blob URL — a
tamper-proof record of what the café AI did, aggregate numbers only.

## 📊 Accuracy eval

`eval/` benchmarks perception against a vision-LLM judge. On **café-representative footage**
(eye-level, sparse) the count MAE is **≈ 0.17 with 100% within ±1** — the regime our single camera
operates in. Dense aerial/crowd stress cases drag the overall number down (documented honestly in
[`eval/report.md`](../eval/report.md)); the fix is a bigger model + SAHI tiling + real geometry.
