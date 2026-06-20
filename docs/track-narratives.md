# 🏆 Track narratives & pitch strategy — Encode "Vibe Coding" Hackathon

Per-track positioning for Golden Coffee, each grounded in what's actually in the repo and
researched against how each sponsor really judges. **Read the strategy first — it's the fix for
why we didn't place last time.**

> Verify before quoting on stage: the exact **Codeplain prize** (README says "£1,000 + $500 credits"
> — unconfirmed on the public page) and whether **FLock** is a named track at *this* event (it's in
> the repo but wasn't explicit on the Luma snapshot). Don't state prize numbers you can't verify.

---

## 0. Strategy — focus beats breadth (the post-mortem fix)

Last event we spread across five tracks, the live actuation didn't reliably demo, and plumbing
outran the story. **The fix is not more tracks — it's one hero, demoed flawlessly, with the others
as free bonus eligibility.**

- **Hero track:** the **General / "most likely to succeed as a business"** angle. Official Encode
  judging is *creativity, technical skill, usability, startup potential* — and the named community
  partners are **coffee brands (Minor Figures, Origin Coffee)**. We are on-theme by design. Lead here.
- **Demo only ONE loop:** queue → agent decision (plain English) → visible action (Telegram + dashboard).
  90 seconds, driven from a **pre-recorded clip**, every actuator **mockable** so it never blocks.
- **The other four tracks = silent eligibility.** One sentence + a clickable link each on a slide.
  Never live-demo Walrus / FLock / the marketing site / scent+AC. Submit to them (the integrations
  are real), but don't split the pitch.
- **What to cut from the demo entirely:** scent & AC/IR actuation (flakiest), the three.js eye-candy
  as a centrepiece, and any "live API call" that can hang.

**One-sentence pitch:** *Golden Coffee turns the camera you already own into a barista's sixth
sense — it reads the room and acts on it, opening a second till before the queue costs you a sale
and dimming the lights when the rush dies down.*

**30-sec elevator:** *Cafés lose customers to queues they never see and waste money on ambience
nobody needs. Golden Coffee plugs into the camera you already have — privacy-first, faces blurred
on-device — reads occupancy, queues and dwell, and an AI agent acts on it: pings staff to open a
second till before a sale walks out, and tunes music and lighting to the room's energy. Perception
tools watch; automation tools fire blind. We're the loop that joins them — and one prevented
walkout per shift pays for itself.*

**The winning 90-sec demo (scripted to never fail):**
1. **(0–20s) The read** — live dashboard on the existing camera; the "Queue" polygon count ticks up
   and turns amber. *"Faces blurred on-device, no identities — just bodies in a zone."*
2. **(20–55s) The decision** — the Claude agent prints a plain-English rationale: *"Queue at 4,
   dwell rising → projected walkout risk. Recommend: open Till 2."* This judgment, in English, is the
   beat people remember.
3. **(55–90s) The action** — a real Telegram message lands on the phone on screen; then lights warm
   / music shifts as the secondary beat. Reliability rule: pre-recorded clip + mockable actuators —
   if Spotify/IR hangs, the loop still completes via Telegram + dashboard state.

**Judging-criteria map:** Innovation → "perception OR action exists; nobody owns the *loop* for café
ops — we're the join." Execution → real CV (YOLO11+Supervision) → real LLM decision → real Telegram,
end-to-end on stage. Usability → zero new hardware, plain-English rationales, a 2-second-glance
dashboard. Impact → "one prevented walkout per shift pays for the system," named coffee customers.
Presentation → sharp ICP, privacy as moat, a demo that lands every time.

---

## 1. Codeplain — *the strongest sponsor angle we actually have*

**Track in one line.** Build with Codeplain as your *primary* tool: a structured-English `.plain`
spec that Codeplain *renders* into production code + tests, spec (not code) as the single source of
truth, in a public repo. It's the explicit **anti-vibe-coding** track.

**Why we fit uniquely.** Most entries prompt an LLM and call it "spec-driven." We did the thing:
`codeplain/golden_coffee_app.plain` is a real spec that Codeplain rendered into a **live TypeScript
React PWA** — the Golden Coffee mobile app, generated source in `codeplain/dist/`, **deployed and
usable now** at https://dist-gamma-gray-23.vercel.app. iOS-installable, polls the live backend every
5s, degrades offline — all *declared in the spec*. A second module (`ops_report.plain`) proves it
generalizes.

**30-sec demo beat.** Side by side: left, the `.plain` spec (point at the PWA-install + 5s-poll
lines); right, the live app on a phone. Then `cat codeplain/codeplain.log` — functionalities rendered
in ~2 minutes. The reveal: *"the app you're holding was generated from this English spec — change a
sentence, re-render, the app changes."*

**Most defensible claim.** *The English is the program; the TypeScript is a build artifact.*

**Gaps to close (impact/effort):** (1) README section documenting the spec→code workflow + render
command [high/low]; (2) commit the auto-generated **Cypress conformance tests** via
`--copy-conformance-tests` — Codeplain's signature differentiator, currently *not* committed
[high/low]; (3) 60-sec asciinema of a render [med/low]; (4) move MORE of the app behind the spec
(controls, activity log, comfort breakdown) [high/med] — **in progress**; (5) edit a spec definition
live on stage and re-deploy [highest/med].

**Pitch lines.** • "We didn't vibe-code it — we **spec'd** it." • "Change the sentence, change the
app." • "Most demos show code an AI wrote; we'll show the spec — and let you edit it."

---

## 2. Sui / Walrus — *provably-authentic AI accountability*

**Track in one line.** Use Walrus as load-bearing infra — decentralized blob storage with a
verifiable `blobId` — not a file uploader. Walrus's pillars: availability, programmability,
verifiability, privacy. Their hackathons score a "Provably Authentic" category and AI workflows.

**Why we fit uniquely.** Walrus's 2025 hackathon crowned *perma.ws* (verified archives, Provably
Authentic) and *TradeArena* (on-chain AI decision recording). Golden Coffee is their intersection:
`onchain/walrus.py` + `POST /onchain/snapshot` anchor the agent's **full action audit trail with
rationales** + anonymized metrics to Walrus — a tamper-proof record of *"what the AI did to the
physical room,"* privacy-first (aggregates/hashes, never faces). Rides Mysten's own "Walrus as the
memory/accountability layer for AI agents" thesis.

**30-sec demo beat.** `curl -X POST localhost:8000/onchain/snapshot` → real `blobId` + public
`read_url`; open `https://aggregator.walrus-testnet.walrus.space/v1/blobs/<blobId>` in a clean tab —
the audit log renders from the decentralized network, none of our servers involved. *"The blobId is
the content hash — change one byte and it's a different blob. I can't rewrite history."*

**Most defensible claim.** *Every decision our AI makes about a real café is written to Walrus as a
content-addressed blob whose ID is its own cryptographic fingerprint — independently verifiable, and
we cannot rewrite it after the fact.*

**Gaps to close (impact/effort):** (1) host the verifier page *on a Walrus Site* — end-to-end
decentralized [high/low]; (2) **hash-chain** snapshots (each embeds the previous blobId) → tamper-
evident history [high/low]; (3) **Seal** encryption for owner-only fields → programmable access
control [high/med]; (4) wallet-signed + Move on-chain anchor with real `epochs` [med/high].

**Pitch lines.** • "The black-box flight recorder for what an autonomous AI did to the room." •
"We store what the AI *decided*, never who was in frame — verify every byte yourself." • "Provably
authentic AI for the physical world. The blobId is the proof; the café is the demo."

---

## 3. Vercel — *the entire customer-facing layer of a real SaaS*

**Track in one line.** "Best use of Vercel / v0" — ship a real, polished, *live* product on the
Vercel stack (Next.js App Router, v0, AI SDK, edge). Vercel's axes: Highest Quality, Fastest, Best
Use of AI.

**Why we fit uniquely.** Three independent **live** Vercel surfaces for one product: a production
**Next.js 14 App Router + TS + Tailwind** app (`web/`) with **Clerk** auth + multi-venue org
tenancy; a live **landing page** (https://landing-gamma-eight-53.vercel.app); and the live **iOS
PWA** (https://dist-gamma-gray-23.vercel.app). Vercel is the *front door of an actual business*, not
a demo page.

**30-sec demo beat.** Open the three tabs live; on the web app, **Sign up → Clerk → create a venue
org** in one breath (multi-tenant onboarding works *now*). Close on the dashboard streaming live
data: *"all marketing, auth, and mobile run on Vercel; only the persistent socket lives on Railway."*

**Most defensible claim.** *Every customer-facing surface — marketing, sign-up/onboarding,
multi-venue auth, and the mobile PWA — is already live in production on Vercel, on Next.js 14.*

**Gaps to close (impact/effort):** (1) **rebuild the marketing site in v0** and say so — the track
names v0 [high/low]; (2) **custom domain** across all three [high/low]; (3) a **Vercel AI SDK**
`/api/ask` streaming endpoint ("how busy is my venue?") for the Best-Use-of-AI axis [high/med];
(4) ship those routes on Edge/fluid compute for the Fastest axis [med/low]. **Own the Railway WS** as
correct architecture (serverless can't hold a socket), not a gap.

**Pitch lines.** • "Three live Vercel deployments, one real business — all clickable." • "We don't
deploy a demo to Vercel; we run our product's entire front door on it." • "v0 designed it, App Router
runs it, the AI SDK answers it."

---

## 4. FLock.io — *federated learning you can taste*

**Track in one line.** Genuine on-chain federated learning: parties train locally, share only model
parameters (never raw data), an aggregator runs FedAvg, packaged via `flock-sdk`'s `FlockModel`
(`init_dataset`/`train`/`aggregate`/`evaluate`). Judging weights actually *using* their stack heavily.

**Why we fit uniquely.** The privacy story is one sentence a non-technical judge gets: **cafés
collaboratively learn a comfort policy without ever sharing their video.** `federated/flock_model.py`
is a faithful port — raw footage never leaves the shop; nodes share only capacity-normalized ratios
`{lull, high, queue}`. Because we share *ratios not counts*, a 10-seat bar and a 40-seat café teach
each other. `train()` estimates P20/P80 ratios; `aggregate()` is the scene-weighted mean (FedAvg
weighting); `evaluate()` checks the global policy still calls lull/busy right on a venue's held-out
window. Real FL objective, not a prop.

**30-sec demo beat.** `python -m federated.flock_model` — one screen: 3 venues `train()` locally
(banner: *"raw scene data never leaves the venue — only 3 ratios are shared"*), `aggregate()` →
scene-weighted global, `evaluate()` → per-venue + mean accuracy. Runs with/without `flock-sdk`
(lazy import) so it never fails live.

**Most defensible claim.** *We solve cold-start and privacy at once: a new café gets a working
comfort policy on day one from the federation, and no shop ever exposes a single frame — only three
normalized floats cross the wire.*

**Gaps to close (effort/impact — maths is done, only on-chain packaging remains):** (1) `flock_run.py`
wrapping `GoldenCoffeeModel` in `FlockSDK(model).run()` [~20 lines, do first]; (2) FLock Dockerfile;
(3) `upload_image.sh` → IPFS/Pinata for `MODEL_DEFINITION_HASH`; (4) create + join the FlockTask
on-chain [needs wallet/testnet]. Realistically land 1–3; keep the local demo as guaranteed fallback.

**Pitch lines.** • "Federated learning you can taste — cafés learn the same policy without sharing a
frame." • "Ratios, not raw data — FedAvg for the high street." • "Every shop keeps customers private
and still gets a smarter room."

---

## Sources (key)
Encode Vibe Coding: encodeclub.com/programmes/encode-vibe-coding-hackathon · luma.com/4f1qbg8g ·
Walrus: walrus.xyz · blog.walrus.xyz/haulout-hackathon-winners-2025 · mystenlabs.com/blog/seal-mainnet-launch-privacy-access-control ·
Vercel: next-hackathon-2025.vercel.app · vercel.com/blog/hackathon-winners · github.com/vercel/ai ·
FLock: flock.io · github.com/FLock-io/v1-sdk ·
Codeplain: codeplain.ai · github.com/Codeplain-ai/plain2code_client · tessl.io/blog/why-codeplain-is-betting-on-spec-driven-software-development
