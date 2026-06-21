# 📖 Caffe Steve — Docs Wiki

> *Your café, but it runs itself.* — a privacy-first AI ambient + ops copilot for cafés and
> restaurants, driven by a single camera you already own.

New here? Start with the [root README](../README.md) for the pitch and the 2-minute quickstart,
then dive into the pages below.

## Pages

| Page | What's inside |
|---|---|
| 🧭 [architecture.md](architecture.md) | How data flows end to end, the `SceneEvent` + `AgentAction` contracts, and every backend endpoint. |
| ✨ [features.md](features.md) | Every feature explained: Comfort Index, ambient autopilot, rush copilot, tables/cleaning, scan PWA, federated learning. |
| 🎬 [demo-guide.md](demo-guide.md) | A tight 3-minute run-of-show for judges — including the hero moment. |
| 🔒 [privacy.md](privacy.md) | The privacy-first stance: exactly what is and isn't stored. |
| 🏆 [bounties.md](bounties.md) | Each sponsor track (Walrus/Sui, Vercel, FLock, Codeplain) and how it's integrated. |
| 🛠️ [local-setup.md](local-setup.md) | Full local run, environment variables, and connecting real devices. |

## Quick links

- 🔴 **Live dashboard:** <https://golden-coffee-production.up.railway.app>
- 📱 **Floorplan scanner PWA:** <https://golden-coffee-production.up.railway.app/scan/>
- 🧩 **The contract:** [`shared/schemas.py`](../shared/schemas.py)
- 📊 **Accuracy eval:** [`eval/report.md`](../eval/report.md)

## The 10-second mental model

```
📷 one camera  →  perception (privacy-first CV)  →  agent (acts)  →  music · lights · scent · AC · alerts
                          │                              │
                          └────────── SceneEvent ────────┴── AgentAction → live dashboard + Comfort Index
```
