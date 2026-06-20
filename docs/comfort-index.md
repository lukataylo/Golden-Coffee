# The Comfort Index

The Comfort Index is the single number Coffee Steve is built around: **how nice
does it feel to be in this room right now**, on a 0–100 scale. Everything the
agent does — nudging music, light, temperature and scent — is in service of
keeping this number high without anyone having to think about it.

It is computed canonically in **`shared/comfort.py`** and mirrored exactly in the
dashboard (`dashboard/index.html`, `computeComfort()`), so the server and the UI
always agree. This document is the human-readable version of that one source of
truth.

## The four pillars

The index is a weighted blend of four pillars, each scored 0–100:

| Pillar | Weight | Driven by | Sensor |
|--------|:------:|-----------|--------|
| **Sound** | 0.40 | loudness + acoustic stress | microphone (real) |
| **Light** | 0.30 | scene brightness, daypart-aware | camera (real) |
| **Temperature** | 0.30 | the temperature we hold the room at | thermostat set-point |

**Why these weights.** In hospitality research the *acoustic* environment is the
strongest single driver of how long guests stay and how they rate a space, so
Sound leads. Light and thermal comfort follow and are roughly equal.

The index tracks only signals genuinely tied to the room: **Sound and Light are
*measured*** off the microphone and camera the venue already has; **Temperature**
is the set-point we hold the room at. (Scent was an earlier pillar and has been
retired. Internally the Temperature pillar still uses the field name `air`.)

## The comfort band

Every pillar uses the same shape — a **trapezoidal comfort band**:

```
score
 100 |        ________________
     |       /                \
     |      /                  \
   0 |_____/                    \________
         lo  ideal_lo   ideal_hi  hi      → measured value
```

A café isn't best at one exact value — it's *comfortable across a band* and only
degrades past the edges. The band is 100 across `[ideal_lo, ideal_hi]`, ramps
linearly down to 0 at the outer `lo`/`hi`, and is 0 beyond them.

```python
def band(x, lo, ideal_lo, ideal_hi, hi):
    if ideal_lo <= x <= ideal_hi: return 100
    if x < ideal_lo: return clamp(100 * (x - lo) / (ideal_lo - lo))   # 0 at/below lo
    return clamp(100 * (hi - x) / (hi - ideal_hi))                    # 0 at/above hi
```

## Pillar definitions

### Sound (0.30)
Measured from the microphone, never recorded or transmitted — only two derived
numbers leave the mic:

- **Loudness** — RMS of the waveform → dBFS → approximate dB SPL (a fixed
  calibration offset; relative, but stable). Scored on a band:
  `lo 42 · ideal 52–66 · hi 80` dB. Dead silence (<42 dB) feels awkward; >80 dB
  is strained; a lively-but-relaxed café sits in the 52–66 band.
- **Acoustic stress (0–100)** — how *unpleasant* the soundscape is, independent
  of level: a blend of **over-loudness** (sustained level above ~68 dB),
  **choppiness** (short-term variability — peaky rooms feel tense), and
  **harshness** (share of energy above 2 kHz — clatter/screech skew bright).

```
sound = clamp( band(dB, 42, 52, 66, 80)  −  0.45 × stress , 0, 100 )
```

So a steady 62 dB of chatter scores high; the same average level full of clatter
and spikes is pulled down by the stress term.

### Light (0.25)
Measured from the camera frame (centre 80%, to ignore vignetting): mean luma →
perceptual 0–100 brightness, with a mild gamma so it tracks how bright the room
*looks*. The ideal band shifts with the daypart:

- **Day** (07:00–18:00): `lo 18 · ideal 44–70 · hi 92`
- **Evening** (18:00–07:00): `lo 10 · ideal 30–52 · hi 82`

Gloom (too dark to read) and glare (blown-out) both score low. The light meter
also flags exposure clipping so "genuinely bright" is distinguished from "camera
clipping".

### Air (0.25)
Thermal comfort from the climate set-point, plus humidity when sensed:

```
temp = clamp(100 − 9 × |setpoint_c − 20.5|)        # ±2°C ≈ 82, ±4°C ≈ 64
hum  = band(humidity_rh, 20, 38, 56, 75)            # ideal 38–56 % RH
air  = 0.7 × temp + 0.3 × hum                       # hum term only if RH present
```

20.5 °C is the neutral comfort centre. With no RH sensor, Air is just the
temperature term.

### Scent (0.20)
No ambient scent sensor exists, so this reflects the diffuser set-point: a light,
present aroma is ideal, off is merely fine, overpowering is not.

```
scent = band(intensity, 0, 40, 62, 100)             # ideal 40–62 %
```

## Aggregation

```
overall = Σ (pillar_score × weight)  /  Σ (weight of present pillars)
```

Missing signals **never tank the score**: the overall is re-normalised over the
weights of the pillars that actually have data. A venue with no mic, no humidity
sensor, or no scent diffuser still gets an honest index from what it can measure
(e.g. camera-only → Light alone; mic + camera → Sound + Light blended).

## Labels

| Overall | Label |
|--------:|-------|
| 85–100 | Feels great |
| 70–84  | Comfortable |
| 55–69  | A little off |
| 0–54   | Could be cosier |

## On the dashboard

- The big **Comfort index** card (right rail) shows the overall, the four pillar
  bars, and a plain-English read of the room.
- The **Sound** and **Light** rows show the live measured values inline —
  e.g. `Sound 61dB` (with a `⚠` when acoustic stress ≥ 45) and `Light 58`.
- The **Comfort** chip under the camera mirrors the overall for an at-a-glance read.

## Data flow

```
perception/audio.py   → sound_db, sound_stress  ┐
perception/light.py   → light_level, light_lux  ├─► SceneEvent ─► backend ─► dashboard
shared/comfort.py     → comfort{} breakdown      ┘                            │
                                                  dashboard re-computes overall │
                                       (measured Sound/Light + local Air/Scent set-points)
```

Perception attaches the measured pillars and a server-side comfort breakdown to
every `SceneEvent`. The dashboard recomputes the headline overall so it can fold
in the Air/Scent set-points it controls locally — using the identical band
constants, so Sound and Light always match the server to the point.

## Privacy

The microphone is used **only** to derive loudness and stress numbers — no audio
is recorded, buffered to disk, or sent anywhere. The camera light reading is a
single mean-brightness scalar per frame. Both are consistent with the project's
privacy-by-design stance (see [`privacy.md`](privacy.md)). Audio can be disabled
entirely with `--no-audio`; it is also off automatically in `--privacy-mode`.
