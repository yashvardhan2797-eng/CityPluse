"""Graph-dashboard endpoint tests: health score, trend, severity time series.

Offline-safe: DB-backed assertions use whatever mode the environment reports;
no test fabricates observations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import create_app  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_score_shape(client):
    resp = client.get("/api/analytics/health?city=bengaluru&hours=24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["city"] == "Bengaluru"
    assert isinstance(body["score"], (int, float))
    assert 0 <= body["score"] <= 100
    assert body["category"] in {"good", "moderate", "poor", "critical"}
    assert isinstance(body["contributions"], list)
    for c in body["contributions"]:
        assert {"metric", "label", "latest", "penalty", "limit", "status"} <= set(c)
    assert isinstance(body["coverage"], dict)
    assert "note" in body


def test_health_score_bounds_params(client):
    resp = client.get("/api/analytics/health?city=bengaluru&hours=999999")
    assert resp.status_code == 200
    assert resp.get_json()["window_hours"] <= 24 * 30


def test_health_trend_shape(client):
    resp = client.get("/api/analytics/health/trend?city=bengaluru&days=7")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["days"] == 7
    assert isinstance(body["trend"], list)
    for point in body["trend"]:
        assert {"day", "score", "n_points"} <= set(point)
        assert 0 <= point["score"] <= 100


def test_severity_series_shape(client):
    resp = client.get("/api/analytics/severity-series?city=bengaluru&hours=168&bucket=day")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        body = resp.get_json()
        assert body["bucket"] == "day"
        for row in body["series"]:
            assert {"bucket", "severity", "count"} <= set(row)


def test_severity_series_rejects_bad_bucket(client):
    resp = client.get("/api/analytics/severity-series?city=bengaluru&bucket=nonsense")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        # falls back to 'hour' rather than echoing arbitrary input
        assert resp.get_json()["bucket"] == "hour"
