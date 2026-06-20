/* Golden Coffee — ready-made coffee-shop layouts ("mockups of existing shops").
 *
 * Each preset is { id, name, blurb, geometry } where geometry is the normalized
 * 0..1 zones.json contract consumed by perception.load_geometry and rendered by
 * the live 3D twin (scan3d.js):
 *
 *   { room, zones:{entry,queue,counter,seating[,off]}, tables:{T1..}, cleaning:{restroom} }
 *
 * Contract rules baked in here (see perception/geometry.py):
 *   - required zones: entry, queue, counter, seating  (all present in every preset)
 *   - the ONLY other allowed zone key is "off" — so a patio / second seating area
 *     is modeled as the "off" zone (rendered as an outdoor patch by the twin)
 *   - every polygon has >= 3 points and non-degenerate area, coords in [0,1]
 *   - queue meets the counter so orders register; tables sit in the seating area.
 */
(function () {
  'use strict';

  // Axis-aligned rectangle (clockwise from top-left) — 4 points, valid polygon.
  const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  // Square footprint centred at (cx,cy) with half-size s — for tables / stools.
  const sq = (cx, cy, s) => rect(cx - s, cy - s, cx + s, cy + s);

  const TBL = 0.03;   // café table half-size  (footprint 0.06 -> 4 chairs)
  const STL = 0.022;  // stool half-size       (footprint 0.044 -> 2 stools)

  const PRESETS = [
    // 1 — Corner Café -------------------------------------------------------
    {
      id: 'corner-cafe',
      name: 'Corner Café',
      blurb: 'Cosy neighbourhood corner shop — counter and queue down one wall, a snug cluster of tables, and a tucked-away restroom.',
      geometry: {
        room: rect(0.08, 0.08, 0.92, 0.92),
        zones: {
          counter: rect(0.10, 0.12, 0.30, 0.55),
          queue:   rect(0.30, 0.20, 0.46, 0.60),
          entry:   rect(0.70, 0.80, 0.90, 0.90),
          seating: rect(0.50, 0.45, 0.90, 0.80),
        },
        tables: {
          T1: sq(0.60, 0.55, TBL),
          T2: sq(0.78, 0.55, TBL),
          T3: sq(0.66, 0.71, TBL),
          T4: sq(0.83, 0.71, TBL),
        },
        cleaning: { restroom: rect(0.72, 0.12, 0.88, 0.28) },
      },
    },

    // 2 — Open Roastery -----------------------------------------------------
    {
      id: 'open-roastery',
      name: 'Open Roastery',
      blurb: 'Big open-plan roastery — a central island counter, generous indoor seating and a sunny side patio with 6 tables in all.',
      geometry: {
        room: rect(0.05, 0.06, 0.95, 0.94),
        zones: {
          counter: rect(0.40, 0.42, 0.62, 0.60),  // central island
          queue:   rect(0.40, 0.60, 0.62, 0.72),
          entry:   rect(0.43, 0.86, 0.57, 0.93),
          seating: rect(0.08, 0.12, 0.36, 0.82),  // indoor floor (left)
          off:     rect(0.66, 0.12, 0.92, 0.82),  // patio (right)
        },
        tables: {
          T1: sq(0.16, 0.24, TBL), T2: sq(0.27, 0.42, TBL), T3: sq(0.18, 0.64, TBL),
          T4: sq(0.74, 0.26, TBL), T5: sq(0.84, 0.46, TBL), T6: sq(0.74, 0.66, TBL),
        },
        cleaning: { restroom: rect(0.42, 0.10, 0.58, 0.26) },
      },
    },

    // 3 — Grab & Go Kiosk ---------------------------------------------------
    {
      id: 'grab-go-kiosk',
      name: 'Grab & Go Kiosk',
      blurb: 'Commuter kiosk built for speed — a wide counter and a deep queue lane dominate, with just a couple of stools to perch.',
      geometry: {
        room: rect(0.12, 0.08, 0.88, 0.92),
        zones: {
          counter: rect(0.15, 0.12, 0.85, 0.34),
          queue:   rect(0.20, 0.34, 0.80, 0.70),
          entry:   rect(0.35, 0.84, 0.65, 0.91),
          seating: rect(0.66, 0.72, 0.85, 0.84),
        },
        tables: {
          T1: sq(0.71, 0.78, STL),
          T2: sq(0.79, 0.78, STL),
        },
        cleaning: { restroom: rect(0.15, 0.74, 0.27, 0.86) },
      },
    },

    // 4 — Bistro + Patio ----------------------------------------------------
    {
      id: 'bistro-patio',
      name: 'Bistro + Patio',
      blurb: 'All-day bistro — a long counter on the right wall, a roomy indoor floor of tables and a distinct front patio.',
      geometry: {
        room: rect(0.06, 0.07, 0.94, 0.93),
        zones: {
          counter: rect(0.78, 0.12, 0.90, 0.60),
          queue:   rect(0.64, 0.18, 0.78, 0.58),
          entry:   rect(0.40, 0.86, 0.58, 0.92),
          seating: rect(0.10, 0.40, 0.60, 0.82),  // indoor
          off:     rect(0.10, 0.11, 0.58, 0.34),  // patio (front)
        },
        tables: {
          T1: sq(0.20, 0.55, TBL), T2: sq(0.40, 0.55, TBL), T3: sq(0.30, 0.72, TBL),
          T4: sq(0.22, 0.22, TBL), T5: sq(0.44, 0.22, TBL),
        },
        cleaning: { restroom: rect(0.78, 0.70, 0.90, 0.84) },
      },
    },

    // 5 — Long Bar Espresso -------------------------------------------------
    {
      id: 'long-bar-espresso',
      name: 'Long Bar Espresso',
      blurb: 'Narrow espresso bar — one long counter run with a row of stools down the opposite wall.',
      geometry: {
        room: rect(0.20, 0.05, 0.80, 0.95),
        zones: {
          counter: rect(0.24, 0.12, 0.42, 0.85),  // long bar
          queue:   rect(0.42, 0.12, 0.50, 0.85),
          entry:   rect(0.34, 0.88, 0.62, 0.94),
          seating: rect(0.58, 0.18, 0.76, 0.85),  // stool strip
        },
        tables: {
          T1: sq(0.67, 0.26, STL), T2: sq(0.67, 0.40, STL), T3: sq(0.67, 0.54, STL),
          T4: sq(0.67, 0.68, STL), T5: sq(0.67, 0.80, STL),
        },
        cleaning: { restroom: rect(0.58, 0.06, 0.76, 0.16) },
      },
    },
  ];

  window.GC_PRESETS = PRESETS;
})();
