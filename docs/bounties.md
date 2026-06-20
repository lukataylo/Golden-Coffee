# 🏆 Bounties & sponsor tracks

How Coffee Steve integrates each sponsor track, grounded in what's actually in the repo. We've
been deliberately honest about status: 🟢 live, 🟡 partial (with exactly what remains).

## 🟢 Sui / Walrus — tamper-proof ops evidence

**Status: live.**

`onchain/walrus.py` + the `POST /onchain/snapshot` endpoint anchor the café's **anonymized metrics
history + the agent's full action audit trail** (with rationales) to **Walrus** decentralized blob
storage in the Sui ecosystem. It uses the public testnet publisher/aggregator over **pure HTTP** —
no wallet, no Move contract, no signing — so it works in a live demo instantly. The call returns a
Walrus `blobId` and a **public read URL anyone can verify**.

- Store: `PUT {publisher}/v1/blobs?epochs=N` → `blobId`
- Read: `GET {aggregator}/v1/blobs/{blobId}`
- CLI: `python -m onchain.walrus store data/metrics.jsonl` / `read <blobId>`

Why it fits: a privacy-first record of *what the AI did to the room* (aggregate numbers only, never
faces) that an owner — or a regulator — can independently check.

## 🟢 Vercel — the front door

**Status: live-ready.**

`web/` is a **separate, production-grade Next.js 14 (App Router) + TypeScript + Tailwind** app for
the public site, sign-up, and onboarding, using **Clerk** for auth, sessions, and organizations
(multi-venue tenancy). It's intentionally **decoupled** from the live product and deploys
**independently to Vercel** (root directory = `web/`), linking out to the Railway-hosted dashboard.

The static `dashboard/` is *also* Vercel-deployable as-is — it's same-origin/`?ws=`-aware, so a
Vercel-hosted page can point at the Railway WebSocket backend:
`https://<app>.vercel.app/?ws=wss://golden-coffee-production.up.railway.app/ws`. Details in
[VERCEL.md](../VERCEL.md).

> Architectural note: the **WebSocket hub must stay on Railway** — Vercel serverless can't hold a
> socket open. Vercel serves the static/marketing surfaces; Railway runs the realtime backend.

## 🟡 FLock — federated learning, ported

**Status: model ported and runnable locally; on-chain packaging documented, not executed.**

Coffee Steve's federation is genuine federated learning with FLock's exact privacy guarantee — raw
venue video never leaves the shop; nodes share only capacity-normalized policy ratios
`{lull, high, queue}` (and music-model weights), aggregated as a scene-weighted mean. We ported this
onto FLock's `FlockModel` interface in **`federated/flock_model.py`**:

| `FlockModel` method | Backed by |
|---|---|
| `init_dataset(path)` | reads FLock's mounted `dataset.json`; synthetic fallback |
| `train(parameters)` | `federated.node.estimate_ratios` (P20/P80 ratios) |
| `aggregate(parameters_list)` | scene-weighted mean of the ratio vectors |
| `evaluate(parameters)` | agreement of the global ratios vs the venue's own labelling on a held-out window |

`flock-sdk==0.0.3` installs cleanly (and is lazy-imported, so the demo runs with or without it).
**Run the proof:** `python -m federated.flock_model` — three simulated venues `train()` locally, the
model `aggregate()`s a global, then `evaluate()`s per venue, printing the params and scores.

**Remaining for the full on-chain claim** (documented in [federated/FLOCK.md](../federated/FLOCK.md),
not done here): a thin `flock_run.py` entry point, a FLock Dockerfile, build/push the image, pin to
IPFS (Pinata), and create + join the FlockTask on-chain.

## 🟡 Codeplain — spec-first development

**Status: spec written; rendering blocked on an API key.**

The Codeplain bounty requires building with Codeplain as the *primary* tool. We chose a discrete,
useful module to build spec-first: the **daily ops-report tool**, specified in structured English at
[`codeplain/ops_report.plain`](../codeplain/ops_report.plain) (it feeds the £-at-risk headline and
the Walrus snapshot). Codeplain isn't self-serve — rendering the `.plain` spec to tested code is
blocked on an API key request to `support@codeplain.ai`. The full plan, commands, and the key-request
email are in [codeplain/README.md](../codeplain/README.md).

## A note on scope

We listed only the tracks that are actually represented in this repo. We deliberately did **not**
claim tracks with no implementation here — see the omissions called out in the project summary. The
status flags above are honest: judges can run the 🟢 items live and the 🟡 items locally today, with
the remaining on-chain/packaging steps written down rather than overstated.
