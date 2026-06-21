# Caffe Steve — Web (marketing + auth + onboarding)

A **separate, production-grade Next.js app** for the public site, sign-up, and
onboarding. It is intentionally **decoupled** from the live product (the Python
`backend/` + the static `dashboard/` + `dashboard/scan/` PWA, which run on
Railway). This app deploys **independently to Vercel** and links out to the live
product dashboard.

## Stack
- **Next.js 14 (App Router) + TypeScript + Tailwind CSS**
- **Clerk** for auth, sign-up, sessions, and organizations (multi-venue tenancy)
- Deploys to **Vercel** (root directory = `web/`)

## Routes (segment boundaries — keep ownership clean)
- `app/(marketing)/` — public **"coming soon"** landing + waitlist (`/`)
- `app/(auth)/` — Clerk sign-in / sign-up
- `app/(app)/` — authenticated area: **onboarding wizard** + app shell that links
  to the live dashboard (`https://golden-coffee-production.up.railway.app`)
- `app/api/waitlist/` — waitlist capture endpoint

## Run
```bash
cd web
npm install
cp .env.local.example .env.local   # add Clerk keys
npm run dev                         # http://localhost:3000
```

## Deploy (Vercel)
New Vercel project → import the repo → **Root Directory = `web`** → add the Clerk
env vars → deploy. (The product backend stays on Railway; this app only links to it.)
