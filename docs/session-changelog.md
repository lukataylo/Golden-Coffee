# Session changelog — hackathon hardening pass

Branch: `claude/hackathon-loss-analysis-ah0prd`. Everything below is committed,
pushed, and verified (59 unit tests + 106 capability checks + a real-browser e2e
smoke + the web app build — all green).

## The one that mattered most
- **Fixed a demo-killing crash.** `agent/policy.decide()` referenced an undefined
  `energy` variable → `NameError` on *every* scene. The agent couldn't make a single
  decision. This almost certainly broke the original live demo. Fixed; full pipeline
  (backend ← mock ← agent → actions) verified end-to-end.

## Vaporware → real (claimed in the README but never implemented)
- **£-at-risk.** `walkaway_gbp` had been deleted as "fake"; reintroduced properly as a
  real `SceneEvent` funnel field (`abandons`) with a transparent `abandons × avg_ticket`
  derivation. Live hero chip + urgent feed alert + `/metrics` + the Walrus snapshot.
- **Conversion funnel.** Was hardcoded `0`. Now a real `entered → ordered → abandoned`
  funnel with a **visual money-shot bar** (ordered/queue/walked-off) + a live chip.
- **Daily ops digest.** New `GET /ops/report` (CLI + 9 conformance tests = the Codeplain
  spec's acceptance criteria) surfaced as a "Today so far" panel.

## A hardware-free hero moment
- **Audible autopilot.** The agent now drives the **real in-browser audio** — the music
  audibly softens when the room fills and switches track on a mood change (fixed the
  audio manifest mood-id mismatch so moods map 1:1 to the model).
- **Multi-sensory rush beat:** £ climbing → URGENT alert → music softens → 3D twin
  retunes → funnel goes red → digest ticks.

## Differentiators made visible in the demo
- **Walrus (headline bounty):** one-click **⛓ Anchor on-chain** button → opens the
  public, verifiable record. Verified live on the testnet end-to-end.
- **Federated learning (FLock):** "Learned from 4 cafés in the network" feed beat.
- **Closed-loop verification:** "Staff responded · 1m 50s — camera confirmed" beat.

## Bounties: from broken/partial to demonstrable
- **Walrus** — live-verified (store + readback on testnet). 🟢
- **Vercel** — the `web/` Next.js app **didn't build** (`Missing publishableKey`). Made
  Clerk optional so it builds + deploys **zero-config**; added a CI job to guard it. 🟢
- **FLock** — the container was missing `agent.policy`/`agent.discounts` and would crash
  on startup; fixed + added a packaging guard test. 🟡→ packaged & CI-verified.
- **Codeplain** — reference impl of `ops_report.plain` ships + passes the spec's tests;
  the hosted render still needs the API key (honest scope). 🟡

## Demo-day insurance (won't break on stage)
- Falls back to the self-contained demo if the **backend dies mid-pitch** (was: froze
  forever), and resumes live on reconnect. Verified by killing a live backend.
- On-chain button: no double-anchor, 35s timeout. Clean demo re-runs (state resets).
- Spotify SDK load made fail-safe; chip row wraps on mobile.

## Engineering credibility
- **CI** (`.github/workflows/ci.yml`): Python 3.11/3.12 unit + capability evals, FLock
  packaging guard, a **browser e2e** smoke (screenshots as artifacts), and a **web build**
  job. Lean deps; no GPU/camera/keys.
- `requirements-dev.txt`, `scripts/smoke_dashboard.cjs`, `PITCH.md` (single-source pitch).

## Handoff — the only things left (all external)
1. **GitHub → Settings → Pages → Source = "GitHub Actions"** → the live demo URL
   (`https://lukataylo.github.io/Golden-Coffee/?demo=1`) auto-publishes. The Actions
   token can't self-enable Pages, so this one click is required.
2. Add a **`RAILWAY_TOKEN`/`VERCEL_TOKEN`** to deploy the backend + the Vercel front door.
3. Wire **one real light** for the on-stage hero (the audible music covers it otherwise).
4. **Deliver the pitch** from `PITCH.md`.
