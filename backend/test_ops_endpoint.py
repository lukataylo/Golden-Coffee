"""The /ops/report endpoint serves the spec-built daily digest over the live
metrics log. Guard that it wires up and returns the report contract."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app

REPORT_KEYS = {
    "samples", "peak_occupancy", "total_walkoffs", "revenue_at_risk_gbp",
    "busiest_hour", "conversion_pct", "cleaning_alerts",
}


def test_ops_report_endpoint_returns_full_contract():
    client = TestClient(app)
    r = client.get("/ops/report")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert REPORT_KEYS <= set(body["report"]), sorted(REPORT_KEYS - set(body["report"]))
