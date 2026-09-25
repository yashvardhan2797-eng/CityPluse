"""Backend smoke tests for CityPulse Phase 1.

These run fully offline: demo mode needs no database or API keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import create_app  # noqa: E402
from backend.demo_data import build_demo_record, get_demo_cities  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------- health

def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["mode"] in ("demo", "database", "demo-fallback")


def test_root_discovery_document(client):
    """Root serves the built dashboard when present, else the discovery doc.

    Deployment builds ship frontend/dist, so the root may legitimately be
    HTML; the discovery JSON contract is asserted only when no build exists.
    """
    import os

    resp = client.get("/")
    assert resp.status_code == 200
    dist_index = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist", "index.html"
    )
    if os.path.isfile(dist_index):
        assert "text/html" in (resp.content_type or "")
    else:
        body = resp.get_json()
        assert body["name"] == "CityPulse API"
        assert "/api/health" in body["endpoints"]


def test_unknown_api_route_returns_json_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Not found"


# ---------------------------------------------------------------- demo data

def test_demo_cities_shape():
    cities = get_demo_cities()
    assert len(cities) >= 5
    ids = {c["id"] for c in cities}
    assert {"bengaluru", "mumbai", "delhi"} <= ids
    for city in cities:
        assert set(city) == {"id", "name", "country", "lat", "lon", "timezone"}


def test_demo_records_have_required_fields():
    for rec in build_demo_record("bengaluru"):
        assert rec["source_type"] in {"air_quality", "transit", "incident", "energy"}
        assert rec["severity"] in {"low", "moderate", "high", "critical"}
        assert -90 <= rec["lat"] <= 90
        assert -180 <= rec["lon"] <= 180
        assert rec["description"].startswith("Demo")


def test_demo_records_fallback_for_unknown_city():
    # Unknown city ids fall back to Bengaluru's sample set, never raise.
    records = build_demo_record("not-a-city")
    assert len(records) > 0


# ---------------------------------------------------------------- endpoints

def test_records_endpoint_demo_mode(client):
    resp = client.get("/api/records?city=delhi")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] in ("demo", "demo-fallback", "database")
    assert isinstance(body["records"], list)
    if body["mode"] != "database":
        assert "Demo mode" in body.get("notice", "") or "demo" in body.get("notice", "").lower()


def test_records_endpoint_invalid_city_safe(client):
    resp = client.get("/api/records?city=../etc/passwd")
    assert resp.status_code == 200  # treated as an unknown id, demo fallback


def test_summary_endpoint_shape(client):
    resp = client.get("/api/summary?city=mumbai")
    assert resp.status_code == 200
    body = resp.get_json()
    # Phase 2+: quality reflects actual provenance (synthetic/mixed/live).
    assert body["summary"]["data_quality"] in {"synthetic", "mixed", "live"}


def test_chart_severity_endpoint(client):
    resp = client.get("/api/chart/severity?city=bengaluru")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["breakdown"].keys()) == {"low", "moderate", "high", "critical"}
    assert sum(body["breakdown"].values()) > 0


def test_cities_endpoint(client):
    resp = client.get("/api/cities")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["cities"]) >= 5


def test_settings_endpoint_leaks_no_secrets(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True).lower()
    assert "password" not in text
    assert "postgresql://" not in text
