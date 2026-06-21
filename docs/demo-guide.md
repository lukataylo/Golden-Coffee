# 🎬 Demo guide — 3-minute run-of-show

A tight script for judges. The goal: in three minutes, show **one camera → the room
understood → the agent acting → a tamper-proof record** — with a single unmissable hero
moment in the middle.

## Before you start (60 seconds of prep, off the clock)

- Open the **live dashboard**: <https://golden-coffee-production.up.railway.app>
- Open the **scanner PWA** on a phone: <https://golden-coffee-production.up.railway.app/scan/>
- If you're driving it locally, have three terminals ready (hub, `shared.mock_events`,
  `agent.agent`) — or just use the dashboard's **▶ Demo** mode (`?demo=1`), which needs nothing.

## The 3-minute script

**0:00 — The hook (20s).**
> "Every café already has a camera nobody watches. A queue of five loses you the sale of the
> sixth person who walks out, and the *feel* of the room decides whether anyone stays for a
> second coffee. Golden Coffee turns that one camera into a teammate that runs the room — and it
> never stores a face."

**0:20 — The room, understood (30s).** On the dashboard's **Live** view, point at the tiles:
occupancy, queue, the conversion funnel, the **Comfort Index** ("Feels great"). Note these all
come from a single camera feed, with faces blurred on-device.

**0:50 — 🌟 THE HERO MOMENT (40s).** Drive the room into a **rush**. As the queue crosses the
threshold, the **"£ walked away today"** hero chip starts climbing in real time — the running cost
of every customer who gave up on the queue — and the **action feed** fires live, each with a
plain-English rationale:
> *"Walk-offs rising — open a second till. (~£120 walked away today)"* → a **Telegram alert** lands
> on the staff phone.
> Then the ambient stack reacts: **music softens**, **lights brighten to neutral**, **scent
> freshens**, **AC cools** — and on the 3D floor twin the lights visibly warm/dim and the music
> ring pulses.

This is the moment: *the agent read the room and acted, visibly, in seconds.* **Start the hosted
music player first (tap ▶) and the music audibly softens right here — no hardware needed**, the
browser's own audio is the actuator. (With real devices, the lights/AC move too.)

**1:30 — Now the lull (20s).** Drop occupancy. The agent flips the other way: the **on-device
music model** picks a cosier mood, lights warm and dim, and a **quiet-period markdown** marks
down perishables on the menu board — "prices only ever go down, never a surge."

**1:50 — Setup in 2 minutes (30s).** On the phone, open the scanner: pick the **Corner Café**
preset → it loads a live 3D twin → tap **"Use this layout → Push to live."** Now the system is
running on a real venue's geometry, not placeholder zones. *(This is the "works in any café in two
minutes" wedge — manual zone-drawing is the #1 onboarding friction for every retail-CV tool.)*

**2:20 — Trust & the bounties (30s).** Hit **anchor to Walrus** — the anonymized metrics + the
agent's full action log (with rationales) are stored tamper-proof on-chain, returning a public,
verifiable URL. Mention the federation angle: *"cafés learn better thresholds and music from each
other — only ratios and model weights are shared, never a single frame."*

**2:50 — The close (10s).**
> "One camera you already own. Privacy-first perception. An agent that actually acts. Your café —
> but it runs itself."

## The single hero moment, if you only get one

**The rush.** Queue builds → staff gets a Telegram alert to open a second till → the room's
ambience visibly retunes (music down, lights neutral, AC cools) — each step narrated by the
agent's own rationale on screen. It compresses the entire product — perception → decision →
real-world action → human-in-the-loop — into ten seconds.

## Fallbacks (live-demo insurance)

- **No backend / flaky wifi:** the dashboard's `?demo=1` mode is fully self-contained.
- **No devices:** the action feed + 3D twin show every action visually; you don't need real
  hardware for the story to land.
- **Perception laptop struggling:** run `python -m shared.mock_events` instead of the camera —
  the agent and dashboard behave identically.
