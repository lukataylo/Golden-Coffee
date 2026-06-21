# Coffee Steve — the 3-minute pitch (single source of truth)

> **One job on stage: land ONE story, once.** Not five products. The hero is the
> rush → the cost on screen → the room retuning itself. Everything else is proof.

---

## The one-liner

**"Every café already has a camera nobody watches. Coffee Steve turns it into a
teammate that runs the room — and shows you the money you're losing in real time."**

## The problem (15s)

A queue of five loses you the sale of the sixth person who walks out — and nobody's
counting that. The *feel* of the room — music, light, temperature — decides whether
anyone stays for a second coffee. One camera sees all of it; no one is watching.

## The hero moment (40s) — THE thing they remember

Drive the room into a **rush** (live, or `?demo=1`). On screen, in order:

1. The **"£ walked away today"** chip starts **climbing** — real money, in real time,
   as customers give up on the queue. *This is the hook. Pause on it.*
2. An **urgent alert** fires in the feed — *"Walk-offs rising — open a second till
   (~£120 walked away today)"* — and lands on the **staff phone** (Telegram).
3. The room **retunes itself**: with the hosted player running, the **music audibly
   softens** (the browser audio is the actuator — no hardware), on the 3D twin the
   **lights brighten** and the **AC cools**, each step narrated by the agent's own reason.

> *That's the whole product in ten seconds: it sees → it counts the cost → it acts.*

## The flip (20s)

Drop the room to a lull. It flips the other way — a cosier on-device music pick,
lights warm and dim, and perishables marked **down** (prices only ever go down, never
a surge). Every action helps a guest or a staff member. No faces stored, ever.

## Why we win / the proof (30s — say only what they ask about)

- **Privacy-first:** faces blurred on-device; tracking is ephemeral, never identity.
- **Walrus (live):** one click anchors the anonymized metrics + the agent's full action
  log to Walrus on-chain — a tamper-proof, publicly verifiable record. *We can show the
  blob URL.*
- **Federated (FLock):** cafés learn better thresholds + music from each other — only
  ratios and model weights leave a shop, never a frame.
- **It actually works:** 59 unit tests + 106 capability checks green in CI; perception
  is MAE 0.17 / 100% within ±1 on café-representative footage.

## The close (10s)

**"One camera you already own. Privacy-first. An agent that acts — and pays for itself
by catching the sales you're losing. Your café, but it runs itself."**

---

## Run-of-show checklist (have these open BEFORE you start, off the clock)

- [ ] Dashboard open, **demo mode armed** (`?demo=1`) as the safety net.
- [ ] If live: backend up, `shared.mock_events` + `agent.agent` running, WS connected.
- [ ] Phone visible for the **Telegram** alert (or the feed if no bot).
- [ ] **Tap ▶ on the hosted music player before you start** — then the agent audibly
      softens/lifts it live (no hardware). A real light dimming is still the dream upgrade,
      but the audible music already gives you a real "it acted" beat.
- [ ] The **⛓ on-chain button** is in the header — one click anchors to Walrus and opens the
      public proof tab (needs the live backend).
- [ ] Backup: a screen recording of a clean run, in case wifi dies.

## Discipline (what sank us last time)

- **Do NOT** demo the marketing site, pricing, auth, or the scanner unless asked. They
  dilute the hero moment.
- **Freeze scope** 12h out: no rebrands, no new features — only rehearsal + hardening.
- Lead the eval with **0.17 / 100% in-domain**, never the stress-case number.
- If a judge asks "is this real?": run `GET /ops/report` and the Walrus anchor live.

## The single hero, if you only get one beat

**The rush.** £ climbing → staff alerted → the room retunes itself on the twin, each
step narrated. It compresses perception → decision → real-world action → the money,
into one breath.
