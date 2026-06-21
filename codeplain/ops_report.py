"""Daily ops-report tool — reference implementation of `ops_report.plain`.

This is the hand-written reference for the Codeplain spec in this folder: it
implements `ops_report.plain` exactly (same keys, same rules, same acceptance
tests) using only the standard library. Its purpose is twofold:

  1. **Validate the spec** — the `.plain` file is the source of truth for the
     Codeplain bounty (rendered via Codeplain once the API key lands). This
     reference proves the spec is complete and buildable, and its tests are the
     spec's acceptance tests, so the rendered output has a conformance target.
  2. **Ship the feature now** — the café's daily one-page operations digest
     (revenue-at-risk, conversion, busiest hour, cleaning alerts). The backend
     serves it live at `GET /ops/report` over the real metrics log.

Run:  python -m codeplain.ops_report data/metrics.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

# [Avg ticket] — the spec constant (GBP). The live dashboard chip uses the
# per-scene avg_ticket_gbp; this CLI tool follows the spec's fixed figure.
AVG_TICKET_GBP = 4.50


def _empty_report() -> dict:
    return {
        "samples": 0,
        "peak_occupancy": 0,
        "total_walkoffs": 0,
        "revenue_at_risk_gbp": 0.0,
        "busiest_hour": None,
        "conversion_pct": 0,
        "cleaning_alerts": 0,
    }


def build_report(ticks: list[dict]) -> dict:
    """Turn a list of validated metric ticks into the one-page report dict."""
    if not ticks:
        return _empty_report()

    peak_occupancy = max(int(t.get("occupancy", 0) or 0) for t in ticks)
    # total walk-offs is the MAX of a cumulative counter. Accept the spec's
    # `abandoned` or the live metrics log's `abandons` (same quantity).
    def _ab(t: dict) -> int:
        v = t.get("abandoned", t.get("abandons", 0))
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    total_walkoffs = max(_ab(t) for t in ticks)
    revenue_at_risk = round(total_walkoffs * AVG_TICKET_GBP, 2)

    # busiest hour: hour-of-day (0–23 from ts) with the highest mean occupancy.
    by_hour_sum: dict[int, float] = defaultdict(float)
    by_hour_n: dict[int, int] = defaultdict(int)
    for t in ticks:
        ts = t.get("ts")
        if ts is None:
            continue
        try:
            hour = datetime.fromtimestamp(float(ts), tz=timezone.utc).hour
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        by_hour_sum[hour] += int(t.get("occupancy", 0) or 0)
        by_hour_n[hour] += 1
    busiest_hour = None
    if by_hour_n:
        busiest_hour = max(by_hour_n, key=lambda h: by_hour_sum[h] / by_hour_n[h])

    # conversion: ordered / entered of the LAST tick, as a whole-number percent.
    last = ticks[-1]
    entered = int(last.get("entered", 0) or 0)
    ordered = int(last.get("ordered", 0) or 0)
    conversion_pct = round(100 * ordered / entered) if entered else 0

    cleaning_alerts = sum(1 for t in ticks if int(t.get("cleaning_overdue", 0) or 0) > 0)

    return {
        "samples": len(ticks),
        "peak_occupancy": peak_occupancy,
        "total_walkoffs": total_walkoffs,
        "revenue_at_risk_gbp": revenue_at_risk,
        "busiest_hour": busiest_hour,
        "conversion_pct": conversion_pct,
        "cleaning_alerts": cleaning_alerts,
    }


def read_ticks(path: str) -> list[dict]:
    """Read a JSONL metrics file; skip malformed lines; missing file -> []."""
    ticks: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # not valid JSON — skip, not fatal
                if isinstance(obj, dict):
                    ticks.append(obj)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return []
    return ticks


def report_for_file(path: str) -> dict:
    return build_report(read_ticks(path))


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) >= 2 else ""
    print(json.dumps(report_for_file(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
