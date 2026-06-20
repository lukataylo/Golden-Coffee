# Deploying the dashboard to Vercel (bounty: "Best use of Vercel")

The `dashboard/` is a static site (no build step) and is same-origin/`?ws=`-aware, so
it deploys to Vercel as-is. The **WebSocket backend stays on Railway** — Vercel
serverless can't hold a socket; Vercel only serves the static dashboard.

## Deploy (≈10 min — needs your Vercel login)

```bash
cd dashboard
npx vercel            # first run: log in + link/create a project, accept defaults
npx vercel --prod     # promote to production
```
(Or in the Vercel dashboard: New Project → import the GitHub repo → **Root Directory = `dashboard`**, Framework Preset = **Other**, no build command.)

## The demo link

Point the deployed page at the Railway backend via the `?ws=` override (the page
derives the HTTP base from it automatically, so `/stream`, `/frame.jpg`, `/override`
all retarget too):

```
https://<your-app>.vercel.app/?ws=wss://golden-coffee-production.up.railway.app/ws
```

## Strengthen the claim (optional, ~1–2 h)
Generate a polished **landing page** with **v0** (their flagship product → scores
higher on "best use of Vercel"), export via `npx shadcn@latest add "<v0-url>"` into a
tiny Next.js app, and deploy it alongside with a CTA linking to the live dashboard.
Don't rebuild the three.js dashboard in v0 — wasted effort.

## Gotchas
- Page is `https://`, so the socket must be `wss://` (Railway provides TLS — fine).
- Railway already sends permissive CORS (`allow_origins=["*"]`), so cross-origin
  `/override` POSTs + the MJPEG `/stream` work from the Vercel origin.
