# Pricing & Positioning Coffee Steve — Research Findings + Recommendation

*Prepared 2026-06-20. Synthesis of four deep-research streams: indie/bootstrapped SaaS pricing,
AI/LLM token economics, café & hospitality software competitor pricing, and positioning strategy.*

---

## TL;DR

- **You do NOT have the token-margin problem that kills most AI startups.** Perception runs
  on-device, the agent's core is a free deterministic policy, and Claude is optional. Your
  gross margin is classic-SaaS 80%+, not the scary AI 50–60%. Your real margin threat is
  **support & onboarding** for non-technical café owners, not API spend.
- **Your real risk is underpricing.** ~80% of YC startups underprice; the universal indie advice
  is "take your candidate price and roughly double it" and "never price it cheap — free or dear."
- **Recommendation: anchor at ~£129/mo per venue** (not £49), against the £150/mo footfall sensor
  (Dor) that does half as much.
- **Positioning: hero the ops ROI ("£ walked away"), garnish with ambiance.** Claim the category
  "AI floor manager / shift copilot." Avoid "CCTV / surveillance / analytics dashboard."
- **Lead monthly to convert, push annual (~2 months free) to survive SMB churn (3–5%/mo).**

---

## 1. The good news: you don't have the token-economics problem most AI startups die from

The "AI products have structurally broken 50–60% margins" narrative comes from products where
**COGS = tokens that scale linearly with usage** (Cursor, ChatGPT Pro, thin AI wrappers losing
money on power users). Coffee Steve is structurally different:

- **Perception (YOLO11) runs on-device** — no cloud inference bill.
- **The agent's core is a deterministic Python policy that runs free/offline** — Claude is
  *optional* reasoning with a rule-based fallback.
- Real per-venue COGS is **hosting (~$5–50/mo) + optional Claude ($0–20/mo) + Clerk auth ($1–2)**.

→ At any sane price you sit on **classic-SaaS 80%+ gross margin**, not AI 50%.

**Your margin threat is support and onboarding** for non-technical café owners (camera setup,
device pairing, hand-holding) — that is the cost line to instrument and cap, not API spend.

**One caveat that does apply:** if you ever make Claude the headline brain (per-event reasoning on
every queue change), meter it from day one and cap "AI mode" behind a higher tier. Keep the free
deterministic engine as the floor so a heavy venue can never blow up your unit economics.

### Token-economics rules of thumb (for if/when AI usage grows)

- Meter per-customer token cost before launching any plan.
- Never sell truly "unlimited" on a usage-cost feature — fair-use caps + rate limits.
- Default to hybrid (base + metered overage); price overage at 2–3× COGS, not 1×.
- Watch the top 10–15% power-user decile — that's where margins die.
- Route → cache → batch → compress before raising prices (routing alone can cut ~85%).
- Stress-test every plan at 3× expected usage and against a model price hike.

---

## 2. The central pricing decision

Two research streams disagreed, and the disagreement is the answer:

- **From pure conservative ROI** (recover 2 coffees/day → ~£300/mo value): **£39–49/mo**.
- **From competitive anchoring**: **~£129/mo** — because **Dor charges $150/mo for footfall data
  *alone*** and **Soundtrack charges $54/mo for music *alone***, and Coffee Steve does both off a
  camera the venue already owns.

The indie-pricing research breaks the tie decisively:

- ~80% of YC companies underprice.
- patio11 / Walling / YC: take your candidate price and roughly **double it**.
- **"Never price it cheap — free or dear."** Cheap plans attract the highest-support,
  fastest-churning customers — exactly the wrong crowd for a high-touch SMB camera product.

→ **£39 is the trap. Anchor at ~£99–129/mo per venue.** Even the conservative £300/mo recovered
makes £129 a >2× return; a busy site clears 5–10×. You are constrained by your own nerve, not by
value. Frame it: *"less than your footfall sensor — and it tunes the room too."*

### Suggested structure (good-better-best, 3 tiers, hybrid)

| Tier | Price/venue/mo | What | Purpose |
|---|---|---|---|
| **Pulse** | **£79** | Service Copilot: queue alerts, table SLAs, cleaning, footfall forecast, "£ walked away" | Entry; lands the ROI story |
| **Autopilot** ⭐ | **£129** | Everything + Ambiance Autopilot (music/light/scent/temp) + AI (Claude) reasoning | The anchor — where ~60–70% should land |
| **Multi-venue** | **£109/venue** (annual, 3+) | Same + cross-café federated tuning, priority support | Captures small-chain expansion |

- **Lead with monthly, cancel-anytime** to convert the skittish owner (landing already says
  "Free pilot · no card · cancel anytime" — good), then push **annual at ~2 months free (17% off)**.
  SMB churns **3–5%/month**; annual prepay churns ~⅓ as much *and* hands you a cash cushion.
- **No free tier yet.** Freemium is a year-2–3 acquisition channel, not a launch pricing tier. Use
  the time-boxed **free pilot** instead — same acquisition benefit, no perpetual margin bleed.

---

## 3. Positioning: lead with money, let the vibe be the magic trick

The product does two things, and the research is blunt that a **dual value prop kills early SMB
products** — the owner can't categorize it, so they do nothing (the real competitor).

**Make Service Copilot the hero; make Ambiance Autopilot the supporting "wow."**

- Ops is *quantifiable* ("£ walked away" is a number on a P&L); "calmer room" is a feeling.
- Queue abandonment is a wound the owner already watches happen daily (15–30% abandon at peak;
  73% walk after 5 minutes).
- Sell the money; let the room tuning itself be the thing they show off to other owners.

**Category to claim:** *"AI floor manager / shift copilot for cafés"* — familiar, implies action + ROI.

**Category to avoid:** *"CCTV analytics / people-counting / surveillance / BI dashboard"* — reads
creepy and passive, triggers staff-privacy recoil and "another dashboard I'll never open" fatigue.
Always pair the pitch with *"no faces stored, runs on the camera you already own."*

**Position against "doing nothing" and "a dashboard you ignore."** Be **alerts that act**, not
charts that wait: *"It taps you on the shoulder; it doesn't ask you to log in."*

### Three positioning angles

- **A — "The £ Recovery Machine" (RECOMMENDED HERO):** *"Coffee Steve tells you the second you're
  about to lose a sale — and counts the ones you already lost."* Value metric: £ recovered/day.
  Objection: "Are the camera's numbers real?"
- **B — "The Café That Runs Itself" (labor multiplier):** *"One extra pair of eyes on the floor,
  for the price of a coffee a day."* Value metric: owner hours freed + SLA adherence.
  Objection: "I don't trust software to run my floor / staff will feel watched."
- **C — "Atmosphere on Autopilot" (SUPPORTING):** *"Your room reads the crowd and tunes itself."*
  Value metric: dwell time / average spend. Objection: "I can change the playlist myself for free."
  → C is easily self-served and hard to quantify, which is exactly why it's the garnish, not the entrée.

### The ROI story (Angle A, explicit)

- Recover just **2 walked-off drinks/day** (conservative vs 15–30% peak abandonment).
- £3.50 × 2 × 30 = **£210/mo**, + a £4 pastry on half of them ≈ **+£120/mo** → **~£300/mo recovered**.
- At £129/mo that's a **>2× return**; recover 4 drinks/day at a busier site → ~£600/mo, a **>4× return**.
- Deck line: *"If Coffee Steve saves you one coffee a day, it's already paid for itself. Everything
  past that is profit you were pouring down the drain."*
- **Always frame value in cups, never percentages** — the owner thinks in drinks.

---

## 4. The café software "wallet" — what indies already pay (price anchors)

| Category | Comparable | Price/location/mo | Role |
|---|---|---|---|
| Background music | Soundtrack Your Brand | $54 ($29–64) | Budget anchor (vibe side) |
| | Pandora/SiriusXM for Business | $17–30 | Anchor |
| | UK TheMusicLicence (PPL+PRS) | ~£28–42 (from £335/yr) | Legal floor — personal Spotify is non-compliant |
| Footfall / queue | **Dor** (thermal counter) | **$150/sensor** + $300 hw | **Direct competitor — key anchor** |
| | Density | hw $149 + sw ~$95/yr | Competitor |
| | Waitwhile (virtual queue) | $31–49 | Adjacent |
| POS / ops | Toast | $0–110+ (real spend $250–700+) | Wallet context + bundling threat |
| | Square for Restaurants | $0 / $49 / $149 | Context |
| | Lightspeed Restaurant | $69–399 | Context |
| | Toast loyalty/marketing add-on | $185 | Shows add-on WTP |
| Smart ambient | Ecobee SmartBuildings | $2.50/thermostat | Weak/adjacent (temp only) |
| AI hospitality | Hostie / Slang.ai / PolyAI / ClearCOGS | low-hundreds/mo | Adjacent (voice/forecast, not vision+ambient) |

- A modest indie café runs **~$200–$450/mo** in software; one with analytics + loyalty hits
  **$500–$800+/mo**.
- Single-purpose tools already command triple digits (Dor $150, Toast loyalty $185) — proving WTP.
- **No competitor combines vision-based ambient control + service-speed ops. That whitespace is
  Coffee Steve's thesis.**
- Credible price band: **£99–149/mo**. Below ~£79 looks like a toy beside Dor/Toast; above ~£200
  starts competing with the POS line and triggers scrutiny.

---

## 5. The three biggest risks to de-risk before launch

1. **Trust in "£ walked away."** If the number feels invented, the pitch collapses. Keep it
   conservative; let owners verify on the replay ("watch it happen").
2. **Surveillance reflex** from owner or staff — lead privacy-first, unprompted, every time
   ("no faces stored, on the camera you already own").
3. **Dashboard death** — if it becomes one more login, it's churned in 90 days (70% of churn is in
   the first 90 days). Be alert-first; prove recovered-£ inside the first two weeks.

---

## Bottom line

You're not in the token-margin trap — you're in the **underpricing** trap. Hero the ops ROI,
garnish with ambiance, claim "AI floor manager," and **anchor at £129 (not £49)** against the
£150 footfall sensor that does half as much. Lead monthly to convert, push annual to survive SMB churn.

---

### Sources & method

Synthesized from four parallel deep-research agents (web-grounded, June 2026):

- **Indie/bootstrapped SaaS pricing:** Patrick Campbell/ProfitWell, patio11 (Kalzumeus), YC
  (Harris/Seibel), Rob Walling/MicroConf, Madhavan Ramanujam, Kyle Poyar/OpenView, David Skok,
  April Dunford, Paddle, Bessemer, KeyBanc, Benchmarkit.
- **AI/LLM token economics:** a16z, Bessemer State of AI 2025, ICONIQ, Tomasz Tunguz,
  Tanay Jaipuria, Bain Capital Ventures, Growth Unhinged, RouteLLM (ICLR 2025), provider pricing pages.
- **Café/hospitality software pricing:** Soundtrack/CloudCover/Mood/SiriusXM, PPL PRS TheMusicLicence,
  Dor, Density, RetailNext, Waitwhile, Toast, Square, Lightspeed, Ecobee, Hostie/ClearCOGS.
- **Positioning:** April Dunford "Obviously Awesome", Skiplino/Qwaiting (queue abandonment),
  Milliman/Equal Strategy & SoundMachine (music & dwell), Cloud Awards & OpenView (restaurant SaaS ROI).

*Specific conversion-lift figures and some 2026 per-token rates are directional/vendor-sourced —
verify before quoting externally.*
