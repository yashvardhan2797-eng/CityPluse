"""Phase 4 hardening tests: health probe, request-size limit, error envelope, UI contract.

All tests are offline and deterministic — no live providers, no secrets read.
Database-backed assertions degrade gracefully (mode reflects reality).
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


# ------------------------------------------------------------------ health
def test_health_returns_degradable_status(client):
    """Health reports mode + db reachability and never 500s."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in {"ok", "degraded"}
    assert isinstance(body["database_reachable"], bool)
    assert body["mode"] in {"database", "demo"}
    # counts consistent with lists
    assert body["providers_failed"] == len(body["failing_sources"])
    assert isinstance(body["ai_configured"], bool)
    assert "checked_at" in body


def test_health_never_leaks_secrets(client):
    resp = client.get("/health")
    raw = resp.get_data(as_text=True)
    for marker in ("Ghost9875", "postgres://", "postgresql://", "sk-", "sb_publishable_"):
        assert marker not in raw, f"health leaked secret marker: {marker}"


def test_index_discovery_still_works(client):
    """Root serves the built dashboard when present, else the discovery doc."""
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


# ------------------------------------------------- request size limit
def test_oversized_body_rejected(client):
    """MAX_CONTENT_LENGTH rejects oversized payloads with 413."""
    import json as _json

    big_payload = _json.dumps({"city": "bengaluru", "question": "x" * (80 * 1024)})
    resp = client.post(
        "/api/ai/ask",
        data=big_payload,
        content_type="application/json",
    )
    assert resp.status_code == 413


# ------------------------------------------------- error envelope
def test_unknown_route_returns_json_404(client):
    resp = client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert resp.is_json
    assert "error" in resp.get_json()


def test_invalid_companion_input_400(client):
    resp = client.post("/api/ai/ask", json={"city": "bengaluru", "question": ""})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_unknown_city_still_safe(client):
    """Unknown city must not 500 — graceful bounded response."""
    resp = client.get("/api/summary?city=atlantis&hours=24")
    assert resp.status_code in (200, 400, 404)


def test_history_bounds_clamped(client):
    resp = client.get("/api/history?city=bengaluru&hours=99999")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["hours"] <= 720


def test_locations_bounded_metrics(client):
    resp = client.get("/api/analytics/locations?city=bengaluru&hours=336")
    assert resp.status_code == 200


# ------------------------------------------------- UI contract (bundle)
def test_frontend_bundle_has_no_secrets():
    """The production bundle must not contain credential-shaped strings."""
    import re

    bundle_dir = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "assets"
    if not bundle_dir.exists():
        pytest.skip("frontend/dist not built")
    patterns = [
        re.compile(r"sb_publishable_[A-Za-z0-9_\-]+"),
        re.compile(r"Ghost9875"),
        re.compile(r"kuxkfgndowdymmggydbw"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"AIzaSy[A-Za-z0-9_\-]{20,}"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    ]
    for js in bundle_dir.glob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            assert pattern.search(text) is None, f"secret pattern {pattern.pattern} in {js.name}"


# ------------------------------------------------- demo/live provenance
def test_summary_reports_data_quality(client):
    resp = client.get("/api/summary?city=bengaluru&hours=24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["data_quality"] in {"live", "mixed", "demo"}
    assert "generated_at" in body["summary"]
