# Caffe Steve — Unit Economics & Hardware Costing

*For the hackathon judges. Prepared 2026-06-20. All figures GBP, ex-VAT.*

Caffe Steve uses a **WHOOP-style membership model**: one flat price, the hardware is
included free, and the customer never makes an upfront purchase. This document shows the
real bill of materials (cheap Xiaomi / Mijia devices) and the margin math behind the
**£99/month** membership.

---

## 1. The included kit — bill of materials (operator COGS)

Every member receives a pre-paired kit that ships ready to plug in. We deliberately spec
**cheap, widely-available Xiaomi / Mijia devices** to keep COGS low and margins SaaS-like.

| # | Device | Model (cheap Xiaomi / Mijia) | What it does | Operator COGS | Retail value shown |
|---|--------|------------------------------|--------------|--------------:|-------------------:|
| 1 | Camera | Xiaomi Smart Camera C300 (2K) | Reads the room — occupancy, queue, dwell. Faces blurred on the on-site computer; no video reaches us. | £22 | £40 |
| 2 | IR aircon controller | Xiaomi Mijia Smart IR Remote (IR blaster) | Controls an IR-remote air-con unit — no rewiring. | £14 | £25 |
| 3 | Smart plug (for lamps) | Xiaomi Mi Smart Plug (Wi-Fi) | Switches a lamp on/off as the room fills and empties. | £9 | £15 |
| 4 | Scent dispenser | Xiaomi Mijia Automatic Aroma Diffuser | Dials one scent up a notch when busy, down when quiet. | £18 | £30 |
| — | Packaging, shipping, spares buffer | — | Pre-paired, ready-to-plug box + courier + ~5% failure spare | £12 | — |
| | **Kit total** | | | **£75** | **£110** |

**Compute note (kept honest):** the vision model (YOLO11) runs on a small always-on
computer in the back-of-house — the café's existing machine, or a ~£100 mini-PC we point
them to. This is a one-time **café-side** cost, **not** in our COGS and **not** in the £99.

---

## 2. Membership economics (per venue)

**Price:** £99 / month on a 12-month membership · or £990 / year prepaid (2 months free).
12-month commitment lets us give the hardware away and still recover it immediately.

### Year 1 (hardware-loaded)

| Line | Annual |
|------|-------:|
| **Revenue** (12 × £99) | **£1,188** |
| Hardware kit (one-time) | −£75 |
| Hosting (Railway) | −£96 |
| AI reasoning (Claude, optional) | −£60 |
| Payment processing (~2.9% + fees) | −£40 |
| Auth (Clerk) + misc infra | −£24 |
| Support allowance | −£48 |
| **Total COGS** | **−£343** |
| **Gross profit** | **£845** |
| **Gross margin** | **71%** |

### Year 2+ (hardware already amortised)

| Line | Annual |
|------|-------:|
| Revenue | £1,188 |
| Total COGS (no hardware) | −£268 |
| **Gross profit** | **£920** |
| **Gross margin** | **77%** |

---

> **A card is required (held, not charged) before we ship the kit.** This is the guard against
> free-hardware abuse. The pilot is still free — the card is only charged if the member continues.

## 3. Why this works (the headline numbers for judges)

- **Hardware payback is ~3 months, blended.** The naive figure is ~1 month (month-1 gross
  contribution ≈ £99 − ~£22 recurring COGS = ~£77 > the £75 kit), but that ignores the free-pilot
  lag and pilots that never convert. Loading the kit for ~70% pilot-to-paid conversion gives an
  **effective hardware cost of ~£107 per paying member** (£75 ÷ 0.70), recovered over **~2–3 months**
  of gross contribution. We size CAC and pilot kit-at-risk *above* gross margin, not inside it.
- **Margins stay SaaS-like (71% → 77%)**, not the 50–60% trap that sinks thin "AI wrapper"
  products — because our compute is on-device (no per-request inference bill) and the AI
  layer is optional, capped, and cheap. See [pricing-and-positioning.md](pricing-and-positioning.md).
- **Zero customer upfront cost** removes the single biggest SMB purchase objection. The café
  risks nothing during the pilot; a card is held (not charged) before we ship, and we recover the
  kit cost within the first few months of a paying member.
- **Churn protection:** the 12-month membership + the installed kit raise switching cost
  versus a pure software subscription, directly countering the 3–5%/mo SMB churn problem.

### Sensitivity (what breaks it)

- If a member churns in **month 1–2** (or the café closes — a real base rate for independents),
  we risk ~£50–75 of kit plus return logistics. Mitigations: a card held before shipping, the
  12-month term, retained title to the Kit, and a prepaid return. On insolvency the kit is often
  unrecoverable, so we **reserve** for it rather than assume full recovery.
- A 3× spike in AI usage adds ~£10/mo COGS → margin dips ~1pt. Fair-use caps + on-device
  routing keep this bounded.
- Hardware price inflation: even at **2× kit COGS (£150)**, Year-1 margin only falls to ~65%.

---

## 4. Comparison — what the café would pay piecing it together

| Capability | DIY (buy separately) | Caffe Steve |
|---|---|---|
| Security camera | £40 one-off | Included |
| Footfall / queue analytics (Dor) | £150/mo + £240 hardware | Included |
| Background-music service | £44/mo | Works with yours |
| AC / heater control | £25 + setup | Included |
| Smart lighting plug | £15 | Included |
| Scent diffuser | £30 | Included |
| Software tying it all together | doesn't exist off-the-shelf | Included |
| **Recurring** | **~£194/mo** | **£99/mo** |
| **Upfront** | **~£350** | **£0** |

Caffe Steve is roughly **half the monthly cost, zero upfront**, and is the only option
that actually unifies perception → action.

*Prices are representative 2026 street prices for cheap Xiaomi/Mijia gear and named
comparables; verify exact SKUs before procurement at scale.*
