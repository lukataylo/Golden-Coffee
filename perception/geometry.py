"""Camera geometry — validation, realistic presets, and auto table layout.

The perception pipeline turns *where* people stand into occupancy, the conversion
funnel, table waits and cleaning cadence. All of that hangs off the polygons in
`perception.run` (entry / queue / counter / seating, plus tables and cleaning
zones). Get the geometry wrong and every downstream metric is quietly wrong.

This module makes geometry first-class:

  * `validate_geometry()` — catches the failure modes that otherwise fail silently
    (missing zones, out-of-frame coords, degenerate/zero-area polygons, tables that
    don't actually sit inside the seating area).
  * `preset()` — believable café layouts generated parametrically, so you can stand
    up real-ish geometry with NO GUI (the only authoring path before this was the
    interactive `draw_zones`, which needs a display).
  * `auto_tables()` — grid N tables into the seating polygon, so venues aren't
    stuck with the hardcoded T1/T2/T3.

All coordinates are normalized (0..1) image space: (0,0) top-left, (1,1)
bottom-right, y increasing downward — the same convention `perception.run` uses to
scale to pixels. Pure stdlib: no cv2, no numpy, importable anywhere.
"""
from __future__ import annotations

import math

# The zones the funnel/occupancy logic in perception.run depends on existing.
REQUIRED_ZONES = ("entry", "queue", "counter", "seating")
# Zone names the schema's Zone enum accepts ("off" = outside any zone).
ALLOWED_ZONES = REQUIRED_ZONES + ("off",)

# Tolerances for validation.
_COORD_EPS = 1e-3        # allow coords a hair outside [0,1] (rounding) before erroring
_MIN_AREA = 1e-4         # normalized area below this is a degenerate polygon


# ---------------------------------------------------------------------------
# polygon helpers (normalized coords)
# ---------------------------------------------------------------------------
def polygon_area(poly: list) -> float:
    """Absolute area of a polygon via the shoelace formula (normalized units)."""
    n = len(poly)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def centroid(poly: list) -> tuple[float, float]:
    """Area-weighted centroid; falls back to vertex mean for degenerate polygons."""
    n = len(poly)
    if n == 0:
        return (0.0, 0.0)
    a = 0.0
    cx = cy = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:  # degenerate — average the vertices
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))


def point_in_poly(pt, poly) -> bool:
    """Ray-casting point-in-polygon (matches perception.run._point_in_poly)."""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _bbox(poly: list) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
class GeometryError(ValueError):
    """Raised by `assert_valid` when geometry has fatal (ERROR-level) problems."""


def _check_poly(label: str, poly) -> list[str]:
    """Return ERROR strings for a single polygon (shape, arity, bounds, area)."""
    errs: list[str] = []
    if not isinstance(poly, (list, tuple)):
        return [f"{label}: polygon must be a list of points, got {type(poly).__name__}"]
    if len(poly) < 3:
        errs.append(f"{label}: needs >= 3 points, has {len(poly)}")
    for k, pt in enumerate(poly):
        if (not isinstance(pt, (list, tuple))) or len(pt) != 2:
            errs.append(f"{label}: point {k} must be [x, y], got {pt!r}")
            continue
        x, y = pt
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
                and math.isfinite(x) and math.isfinite(y)):
            errs.append(f"{label}: point {k} is not finite numbers: {pt!r}")
            continue
        if not (-_COORD_EPS <= x <= 1 + _COORD_EPS and -_COORD_EPS <= y <= 1 + _COORD_EPS):
            errs.append(f"{label}: point {k} {pt!r} is outside the frame (expect 0..1)")
    if len(poly) >= 3 and all(
        isinstance(p, (list, tuple)) and len(p) == 2
        and all(isinstance(c, (int, float)) for c in p) for p in poly
    ):
        if polygon_area(poly) < _MIN_AREA:
            errs.append(f"{label}: polygon is degenerate (near-zero area) — "
                        f"points may be collinear or duplicated")
    return errs


def validate_geometry(cfg: dict) -> tuple[list[str], list[str]]:
    """Validate a geometry config, returning (errors, warnings).

    `cfg` is the `{ "zones": {...}, "tables": {...}, "cleaning": {...} }` shape that
    `perception.run.load_geometry` reads. ERRORS mean the geometry would break the
    pipeline (and should block loading); WARNINGS are likely-mistakes worth flagging
    but not fatal (e.g. a table whose centroid isn't inside the seating area).
    """
    errors: list[str] = []
    warnings: list[str] = []

    zones = cfg.get("zones", {}) or {}
    tables = cfg.get("tables", {}) or {}
    cleaning = cfg.get("cleaning", {}) or {}

    for name in REQUIRED_ZONES:
        if name not in zones:
            errors.append(f"zones.{name}: required zone is missing")
    for name in zones:
        if name not in ALLOWED_ZONES:
            errors.append(f"zones.{name}: unknown zone name "
                          f"(expected one of {', '.join(ALLOWED_ZONES)})")

    for group, label in ((zones, "zones"), (tables, "tables"), (cleaning, "cleaning")):
        for key, poly in group.items():
            if not str(key).strip():
                errors.append(f"{label}: an entry has an empty name")
            errors.extend(_check_poly(f"{label}.{key}", poly))

    # WARNING: tables should sit inside the seating zone (else table monitoring and
    # the dashboard map disagree). Only checkable once seating is a valid polygon.
    seating = zones.get("seating")
    if seating and not _check_poly("zones.seating", seating):
        for tid, poly in tables.items():
            if _check_poly(f"tables.{tid}", poly):
                continue  # already an error; skip the geometric check
            if not point_in_poly(centroid(poly), seating):
                warnings.append(f"tables.{tid}: centroid is outside the seating zone")

    # WARNING: queue and counter usually touch (the line forms at the counter). If
    # their bounding boxes don't overlap at all, the funnel may never see "ordered".
    q, c = zones.get("queue"), zones.get("counter")
    if q and c and not _check_poly("q", q) and not _check_poly("c", c):
        qx0, qy0, qx1, qy1 = _bbox(q)
        cx0, cy0, cx1, cy1 = _bbox(c)
        if qx1 < cx0 or cx1 < qx0 or qy1 < cy0 or cy1 < qy0:
            warnings.append("zones.queue and zones.counter do not overlap — "
                            "the queue should meet the counter so orders register")

    return errors, warnings


def assert_valid(cfg: dict) -> list[str]:
    """Raise GeometryError on any ERROR; return the (non-fatal) warnings."""
    errors, warnings = validate_geometry(cfg)
    if errors:
        raise GeometryError(
            f"{len(errors)} geometry error(s):\n  - " + "\n  - ".join(errors)
        )
    return warnings


def geometry_summary(cfg: dict) -> str:
    """One-line human summary (for CLI/logging)."""
    z = len(cfg.get("zones", {}) or {})
    t = len(cfg.get("tables", {}) or {})
    c = len(cfg.get("cleaning", {}) or {})
    return f"{z} zones, {t} tables, {c} cleaning zones"


# ---------------------------------------------------------------------------
# auto table layout
# ---------------------------------------------------------------------------
def auto_tables(
    seating_poly: list,
    n: int,
    *,
    cols: int | None = None,
    margin: float = 0.03,
    gap: float = 0.025,
    fill: float = 0.72,
    prefix: str = "T",
) -> dict[str, list]:
    """Grid `n` tables into the bounding box of `seating_poly`.

    Lays out a roughly-square grid, keeps only cells whose centre actually falls
    inside the (possibly non-rectangular) seating polygon, and shrinks each cell to
    a `fill` fraction so tables read as distinct footprints. Returns at most `n`
    tables labelled `{prefix}1..{prefix}n`.
    """
    if n <= 0:
        return {}
    x0, y0, x1, y1 = _bbox(seating_poly)
    x0 += margin; y0 += margin; x1 -= margin; y1 -= margin
    if x1 <= x0 or y1 <= y0:
        return {}
    cols = cols or max(1, round(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))
    cw = (x1 - x0) / cols
    ch = (y1 - y0) / rows
    inset_x = (cw * (1 - fill) + gap) / 2.0
    inset_y = (ch * (1 - fill) + gap) / 2.0

    out: dict[str, list] = {}
    placed = 0
    for r in range(rows):
        for col in range(cols):
            if placed >= n:
                break
            cx0 = x0 + col * cw + inset_x
            cy0 = y0 + r * ch + inset_y
            cx1 = x0 + (col + 1) * cw - inset_x
            cy1 = y0 + (r + 1) * ch - inset_y
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            cx, cy = (cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0
            if not point_in_poly((cx, cy), seating_poly):
                continue
            placed += 1
            out[f"{prefix}{placed}"] = [
                [round(cx0, 4), round(cy0, 4)], [round(cx1, 4), round(cy0, 4)],
                [round(cx1, 4), round(cy1, 4)], [round(cx0, 4), round(cy1, 4)],
            ]
    return out


# ---------------------------------------------------------------------------
# presets — believable café layouts, no GUI required
# ---------------------------------------------------------------------------
def _rect(x0: float, y0: float, x1: float, y1: float) -> list:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# Each preset returns (zones, seating_poly, restroom_poly). Tables are gridded into
# the seating polygon afterwards so table count is a parameter, not baked in.
def _preset_counter_top() -> tuple[dict, list, list]:
    """Counter along the top wall; queue forms just below it toward the till (right);
    door bottom-left; seating fills the lower floor."""
    zones = {
        "counter": _rect(0.08, 0.03, 0.92, 0.18),
        "queue":   _rect(0.34, 0.18, 0.92, 0.36),
        "entry":   _rect(0.00, 0.74, 0.22, 1.00),
    }
    seating = _rect(0.05, 0.40, 0.95, 0.97)
    restroom = _rect(0.00, 0.40, 0.14, 0.70)
    return zones, seating, restroom


def _preset_counter_left() -> tuple[dict, list, list]:
    """Counter down the left wall; queue to its right; door bottom-right; seating
    fills the right side."""
    zones = {
        "counter": _rect(0.03, 0.06, 0.20, 0.86),
        "queue":   _rect(0.20, 0.34, 0.40, 0.86),
        "entry":   _rect(0.78, 0.74, 1.00, 1.00),
    }
    seating = _rect(0.42, 0.06, 0.98, 0.96)
    restroom = _rect(0.84, 0.00, 1.00, 0.22)
    return zones, seating, restroom


def _preset_bands() -> tuple[dict, list, list]:
    """Legacy four vertical bands — back-compat for the people-walking demo clip."""
    zones = {
        "entry":   _rect(0.00, 0.0, 0.25, 1.0),
        "queue":   _rect(0.25, 0.0, 0.50, 1.0),
        "counter": _rect(0.50, 0.0, 0.75, 1.0),
    }
    seating = _rect(0.75, 0.0, 1.00, 1.0)
    restroom = _rect(0.00, 0.55, 0.15, 1.00)
    return zones, seating, restroom


PRESETS = {
    "counter_top": _preset_counter_top,
    "counter_left": _preset_counter_left,
    "bands": _preset_bands,
}


def preset(layout: str = "counter_top", *, tables: int = 4, with_restroom: bool = True) -> dict:
    """Generate a full, valid geometry config for a named café `layout`.

    `tables` tables are auto-laid into the seating area; set `with_restroom=False`
    to omit the cleaning zone. The result is ready for
    `perception.run.load_geometry` and is guaranteed to pass `validate_geometry`
    (asserted here, so a broken preset fails loudly rather than at runtime).
    """
    if layout not in PRESETS:
        raise ValueError(f"unknown preset {layout!r}; choose from {sorted(PRESETS)}")
    zones, seating_poly, restroom_poly = PRESETS[layout]()
    zones = {k: [list(p) for p in v] for k, v in zones.items()}
    zones["seating"] = [list(p) for p in seating_poly]
    cfg = {
        "zones": zones,
        "tables": auto_tables(seating_poly, tables),
        "cleaning": {"restroom": [list(p) for p in restroom_poly]} if with_restroom else {},
    }
    assert_valid(cfg)  # a preset that doesn't validate is a bug
    return cfg


if __name__ == "__main__":  # quick manual check: print each preset + validation
    import json
    for name in PRESETS:
        cfg = preset(name, tables=5)
        errs, warns = validate_geometry(cfg)
        print(f"[{name}] {geometry_summary(cfg)}  errors={len(errs)} warnings={len(warns)}")
        for w in warns:
            print(f"    ! {w}")
    print("\nexample (counter_top):")
    print(json.dumps(preset("counter_top", tables=4), indent=2))
