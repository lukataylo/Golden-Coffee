# Golden Coffee — Dashboard Redesign Brief

**Goal:** Replace the current dark coffee/gold dashboard with a clean, minimal,
**Apple-grade** interface that reads as *intentionally designed by a human*, not
generated. Four distinct directions are shipped in `dashboard/designs/` for review;
the winner gets wired into the live `dashboard/index.html`.

This brief is the project's `DESIGN.md` — the single source of truth every version
is held to. It synthesizes three research passes (glassmorphism/Vercel libraries,
AI-design "tells", and Claude design-prompt technique incl. the "eBay prompt").

---

## 1. The "eBay prompt", applied

There is no magic copy-paste "eBay prompt". It's a **reference technique**: an
ambiguous prompt ("build a dashboard") returns *the median of every Tailwind
tutorial on GitHub* — the AI-slop look. Naming a **specific, distinctive, real**
reference yanks the output off that median. So each of our four versions commits
fully to **one named reference** (not a blend), and states its 3 borrowed
signatures before any pixel is drawn. We also adopt Anthropic's own
`frontend_aesthetics` guidance: dominant color + sharp accent (never timid,
evenly-distributed palettes), distinctive type, atmosphere over flat fills, and
**one orchestrated load** over scattered micro-interactions.

## 2. Ban list (the AI "tells" — none of these appear)

- ❌ Purple / indigo accents, blue→purple gradients (the #1 tell)
- ❌ Inter / Roboto / Open Sans / Lato as the system face; Space Grotesk as the "fix"
- ❌ Centered hero + the Hero→3-feature-grid→pricing→FAQ skeleton
- ❌ Identical `rounded-2xl shadow-lg p-6` cards; one uniform radius/shadow on everything
- ❌ Emoji used **as icons** (we replace café emoji with a single hairline SVG icon set)
- ❌ Rainbow/decorative gradients with no semantic meaning; colored glows under cards
- ❌ Too many drop shadows (if everything floats, nothing floats)
- ❌ Low-contrast dark mode; corporate filler copy

## 3. Non-negotiable foundations (all four versions)

- **Spacing:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 only. Everything snaps to the 8pt grid.
- **Type scale:** 12 / 14 / 16 / 18 / 24 / 30 / 36+ ; body 16. Weight *extremes* for hierarchy
  (e.g. 300 labels vs 600–700 hero numbers), not 400-vs-600 timidity.
- **Numbers are the hero:** big, confident, **tabular-nums**, right-aligned in columns.
  Small muted label above/below — that contrast *is* the hierarchy.
- **Colour:** one neutral ramp + **one** brand accent (carrying consistent meaning) +
  3 semantic (success / warning / danger). Accent earns its place by meaning something.
- **Charts:** flat, high data-ink — thin/no gridlines, muted axes, no 3D, no chart shadows.
  Consistent colour *meaning* across every chart.
- **Motion:** 150ms micro-interactions, 200–250ms transitions, ease-out
  `cubic-bezier(0,0,0.2,1)`; one staggered page-load reveal. Never linear, never everywhere.
- **Real content:** the live café metrics, real labels, real £ — no lorem energy.
- **Accessibility:** WCAG AA contrast; `prefers-reduced-motion` + `prefers-reduced-transparency`
  fallbacks; focus-visible rings; keep all existing element IDs / `data-action` hooks intact
  so the live WebSocket JS keeps working when a version is promoted.

## 4. Glassmorphism recipe (used where the direction calls for it — never as filler)

Blur **12–20px**, **always** paired with `saturate(150–180%)`; thin top-edge highlight
(the specular "catch-light") via `inset 0 1px 0 rgba(255,255,255,.x)`; hairline border at
8–20% opacity; layered soft shadow (not one heavy drop); ~8% SVG-noise/grain to kill banding;
never more than ~3 stacked glass panels. Put a subtle coloured field *behind* the glass so the
blur has something to refract. Always include `-webkit-backdrop-filter` and a solid fallback.

## 5. The four directions (same information architecture, different visual language)

| # | Name | Named reference (the "eBay") | 3 borrowed signatures | Mood |
|---|------|------------------------------|------------------------|------|
| **1** | **Porcelain** | Apple visionOS Control Center / Apple Health (light) | frosted white liquid-glass tiles · clarity-deference-depth · SF Pro + generous whitespace | bright, calm, premium |
| **2** | **Graphite** | Linear + a transport ops console + visionOS (dark) | true backdrop-blur glass panels · a single warm ember aurora behind glass · sharp tabular data + hairline specular borders | cinematic, focused, nocturnal |
| **3** | **Monograph** | Braun / Dieter Rams + Swiss International + Bloomberg density | near-monochrome paper · oversized numerals + monospace labels · hairline rules, zero decoration | rigorous, editorial, data-first |
| **4** | **Ember** | The warm meditation-app refs + Teenage Engineering | warm cream/sand canvas · amber→terracotta as *material* not decoration · large concentric soft-shadow cards | cosy, tactile, on-brand for a café |

**Shared layout (unchanged IA):** sticky header (brand · Live/Floorplan/Tables segmented
control · clock · connection pill) → revenue-at-risk headline → 4 KPI tiles with sparklines →
stage (live/floor/tables canvas + right rail: Comfort autopilot, Manual override, Agent-actions
feed) → footer (conversion funnel + ethics/privacy).

## 6. Canonical demo data (identical across all four, so they compare like-for-like)

Occupancy **34** (▲ +3) · Queue **5** (▲ +2) · Conversion **68%** (▼ −4pp) · Room energy **72%**.
Revenue at risk **£58** (danger level) — *13 customers left the queue without ordering*.
Funnel: entered 210 · approached 168 · ordered 143 · seated 96 · abandoned 13.
Comfort: Temperature setpoint 20.5°C (cool side) · Lighting 45% · Scent 55% · Music 40% (softened).
Tables: T1 seated 2:10 · T2 waiting 4:30 · T3 overdue 8:12 · T4 empty · T5 seated 1:05 ·
T6 waiting 3:40 (needs bussing). Cleaning: Restroom A *due*, Restroom B *ok*, Counter *overdue*, Patio *ok*.
Agent feed (newest first): soften music (auto, 23s) · open second till (auto, 1m) ·
dim & cosy lighting (manual, 3m) · push 20% off pastries (auto, 6m).
