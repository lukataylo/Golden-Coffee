"""Conformance tests for the daily ops-report — these ARE the acceptance tests
written in `ops_report.plain`, plus a few edge cases. They double as the target
the Codeplain-rendered output must satisfy.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from codeplain.ops_report import AVG_TICKET_GBP, build_report, report_for_file


def _write(tmp_path: Path, lines: list[str]) -> str:
    p = tmp_path / "metrics.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def _tick(**kw) -> str:
    base = {"ts": time.time(), "occupancy": 0, "queue_len": 0, "abandoned": 0,
            "entered": 0, "ordered": 0, "tables_waiting": 0, "cleaning_overdue": 0}
    base.update(kw)
    return json.dumps(base)


# ---- the spec's four acceptance tests -------------------------------------
def test_three_valid_ticks_report_samples_three(tmp_path):
    path = _write(tmp_path, [_tick(occupancy=3), _tick(occupancy=5), _tick(occupancy=4)])
    rep = report_for_file(path)
    assert rep["samples"] == 3
    assert rep["peak_occupancy"] == 5


def test_revenue_at_risk_is_walkoffs_times_ticket(tmp_path):
    path = _write(tmp_path, [_tick(abandoned=2), _tick(abandoned=7), _tick(abandoned=10)])
    rep = report_for_file(path)
    assert rep["total_walkoffs"] == 10                      # cumulative -> max
    assert rep["revenue_at_risk_gbp"] == round(10 * AVG_TICKET_GBP, 2) == 45.0


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    path = _write(tmp_path, [_tick(occupancy=2), "this is not json {", _tick(occupancy=4)])
    rep = report_for_file(path)
    assert rep["samples"] == 2


def test_missing_file_yields_empty_report_and_exit_zero():
    rep = report_for_file("/nonexistent/path/metrics.jsonl")
    assert rep["samples"] == 0
    assert rep["peak_occupancy"] == 0
    assert rep["revenue_at_risk_gbp"] == 0.0
    assert rep["busiest_hour"] is None
    # CLI exits 0 on a missing file
    proc = subprocess.run([sys.executable, "-m", "codeplain.ops_report", "/no/such/file"],
                          capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["samples"] == 0


# ---- a few more for confidence --------------------------------------------
def test_conversion_uses_last_tick(tmp_path):
    path = _write(tmp_path, [_tick(entered=10, ordered=9), _tick(entered=4, ordered=1)])
    assert report_for_file(path)["conversion_pct"] == 25      # 1/4 of the LAST tick


def test_conversion_zero_when_entered_zero(tmp_path):
    path = _write(tmp_path, [_tick(entered=0, ordered=0)])
    assert report_for_file(path)["conversion_pct"] == 0


def test_cleaning_alerts_counts_overdue_ticks(tmp_path):
    path = _write(tmp_path, [_tick(cleaning_overdue=0), _tick(cleaning_overdue=1), _tick(cleaning_overdue=2)])
    assert report_for_file(path)["cleaning_alerts"] == 2


def test_accepts_live_metrics_abandons_alias(tmp_path):
    # the backend logs `abandons`; the spec says `abandoned` — both must work
    path = _write(tmp_path, [json.dumps({"ts": time.time(), "occupancy": 6, "abandons": 8})])
    assert report_for_file(path)["total_walkoffs"] == 8


def test_empty_dataset_via_build_report():
    rep = build_report([])
    assert rep["samples"] == 0 and rep["busiest_hour"] is None
