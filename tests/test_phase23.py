"""Phase 2/3 backend tests: validation, generators, analytics, AI fallback, API.

No live network calls: provider HTTP is mocked where needed. Database-backed
tests are skipped automatically when DATABASE_URL is not configured.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import create_app  # noqa: E402
from backend.demo_data import DEMO_CITIES  # noqa: E402
from backend.ingest import _is_live_configured, _run_source  # noqa: E402
from backend.providers.base import (  # noqa: E402
    NormalizedObservation,
    ProviderError,
    validate_observation,
)


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _db_available() -> bool:
    from backend.config import get_settings
    from backend.database import test_connection

    return bool(get_settings().database_url) and test_connection()[0]


DB = pytest.mark.skipif(not _db_available(), reason="DATABASE_URL not configured/reachable")


def _obs(**overrides) -> NormalizedObservation:
    base = dict(
        source_type="weather",
        provider="open-meteo",
        source_id="open-meteo-test-temperature_c",
        city="Bengaluru",
        city_id="bengaluru",
        location_name="Bengaluru (city-wide)",
        latitude=12.9716,
        longitude=77.5946,
        metric="temperature_c",
        value=27.5,
        unit="°C",
        severity="moderate",
        description="Live weather: temperature_c = 27.5 °C",
        recorded_at=datetime.now(timezone.utc),
        source_url=None,
        metadata={},
        is_synthetic=False,
    )
    base.update(overrides)
    return NormalizedObservation(**base)


# ---------------------------------------------------------------- validation

def test_validate_observation_accepts_valid():
    validate_observation(_obs())  # should not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": 95.0},
        {"longitude": -200.0},
        {"severity": "extreme"},
        {"source_type": "traffic"},
        {"recorded_at": datetime(2026, 1, 1)},  # naive datetime
        {"source_id": ""},
        {"is_synthetic": True, "description": "Live reading"},  # mislabeled synthetic
    ],
)
def test_validate_observation_rejects_invalid(overrides):
    with pytest.raises(ProviderError):
        validate_observation(_obs(**overrides))


# ---------------------------------------------------------------- demo generators

def test_demo_generators_are_deterministic_and_labeled():
    from backend.providers.demo_generators import bucket_for

    bucket = bucket_for(offset_hours=3)
    for source_type in ("weather", "air_quality", "transit", "incident"):
        from backend.ingest import _fetch_demo

        first = _fetch_demo(source_type, "bengaluru", bucket=bucket)
        second = _fetch_demo(source_type, "bengaluru", bucket=bucket)
        # incidents may legitimately be empty in a given bucket (0-3 events)
        if source_type != "incident":
            assert first and second
        for a, b in zip(first, second):
            assert a.value == b.value  # deterministic
            assert a.is_synthetic is True
            assert a.description.startswith("Demo:")
            assert a.recorded_at.tzinfo is not None


def test_demo_source_ids_embed_bucket_for_history():
    from backend.providers.demo_generators import bucket_for
    from backend.ingest import _fetch_demo

    b1, b2 = bucket_for(offset_hours=1), bucket_for(offset_hours=2)
    obs1 = _fetch_demo("weather", "bengaluru", bucket=b1)
    obs2 = _fetch_demo("weather", "bengaluru", bucket=b2)
    assert obs1[0].source_id != obs2[0].source_id  # distinct buckets -> distinct ids


# ---------------------------------------------------------------- provider parsing (mocked)

def test_weather_provider_parses_mocked_response():
    from backend.providers import weather

    fake_payload = {
        "current": {
            "time": "2026-09-24T12:00",
            "temperature_2m": 27.4,
            "relative_humidity_2m": 61,
            "precipitation": 0.0,
            "wind_speed_10m": 11.2,
        }
    }
    fake_response = type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: fake_payload})()
    with patch("backend.providers.weather.requests.get", return_value=fake_response):
        observations = weather.fetch_live("bengaluru")

    assert len(observations) == 4
    temp = next(o for o in observations if o.metric == "temperature_c")
    assert temp.value == 27.4
    assert temp.unit == "°C"
    assert temp.recorded_at.tzinfo is not None
    assert temp.source_id.startswith("open-meteo-")


def test_weather_provider_skips_missing_fields():
    from backend.providers import weather

    fake_payload = {"current": {"time": "2026-09-24T12:00", "temperature_2m": 20.0}}
    fake_response = type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: fake_payload})()
    with patch("backend.providers.weather.requests.get", return_value=fake_response):
        observations = weather.fetch_live("bengaluru")
    assert [o.metric for o in observations] == ["temperature_c"]  # missing fields skipped


def test_openaq_provider_parses_mocked_flow():
    from backend.providers import air_quality

    locations = {
        "results": [
            {
                "id": 8118,
                "name": "New Delhi",
                "coordinates": {"latitude": 28.63576, "longitude": 77.22445},
                "sensors": [
                    {"id": 23534, "parameter": {"id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"}}
                ],
            }
        ]
    }
    latest = {
        "results": [
            {"sensorsId": 23534, "value": 62.5, "datetime": {"utc": "2026-09-24T11:30:00Z"}}
        ]
    }

    def fake_get(url, **kwargs):
        response = type("R", (), {})()
        response.raise_for_status = lambda: None
        response.json = lambda: latest if "/latest" in url else locations
        return response

    with patch("backend.providers.air_quality.requests.Session.get", side_effect=fake_get):
        observations = air_quality.fetch_live("delhi", api_key="test-key")

    assert len(observations) == 1
    assert observations[0].metric == "pm25_ugm3"
    assert observations[0].value == 62.5
    assert observations[0].provider == "openaq"
    assert observations[0].severity == "high"  # 62.5 µg/m³


def test_openaq_requires_key():
    from backend.providers import air_quality

    with pytest.raises(ProviderError):
        air_quality.fetch_live("delhi", api_key="")


# ---------------------------------------------------------------- ingest orchestration

def test_is_live_configured_flags():
    class S:
        weather_enabled = True
        openaq_api_key = ""
        transit_gtfs_rt_url = ""
        incidents_socrata_url = ""

    assert _is_live_configured("weather", S) is True
    assert _is_live_configured("air_quality", S) is False
    assert _is_live_configured("transit", S) is False


def test_run_source_falls_back_to_labeled_demo():
    class S:
        weather_enabled = True
        openaq_api_key = ""
        transit_gtfs_rt_url = ""
        incidents_socrata_url = ""
        incidents_field_map = None

    from backend.providers.base import ProviderError as _PE

    with patch("backend.ingest.weather.fetch_live", side_effect=_PE("network down")):
        status = _run_source("weather", ["bengaluru"], S)
    assert status["mode"] == "demo"
    assert "network down" in (status["error"] or "")
    assert status["records_stored"] > 0 or status["configured"] is True


# ---------------------------------------------------------------- anomaly detection

def _series(values):
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        {"bucket": (base - timedelta(hours=len(values) - 1 - i)).isoformat(), "avg_value": v, "n": 3}
        for i, v in enumerate(values)
    ]


def test_anomaly_detection_flags_spike():
    from backend.analytics import detect_metric_anomalies

    baseline = [10.0 + (i % 3) * 0.5 for i in range(24)]
    series = _series(baseline + [45.0])  # obvious spike at the end
    anomalies = detect_metric_anomalies(series, window_hours=72)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["observed_value"] == 45.0
    assert a["score"] > 0
    assert a["method"] in ("rolling_median_mad", "rolling_mean_stdev")
    assert "not imply a cause" in a["limitations"]


def test_anomaly_detection_quiet_on_normal_data():
    from backend.analytics import detect_metric_anomalies

    series = _series([10.0 + (i % 3) * 0.5 for i in range(24)])
    assert detect_metric_anomalies(series, window_hours=72) == []


def test_anomaly_detection_requires_history():
    from backend.analytics import detect_metric_anomalies

    short = _series([10.0, 11.0, 45.0])
    assert detect_metric_anomalies(short, window_hours=72) == []


# ---------------------------------------------------------------- correlations

def test_perfect_positive_correlation():
    from backend.correlations import _pearson, _spearman

    xs = [float(i) for i in range(20)]
    ys = [2.0 * x + 1.0 for x in xs]
    assert _pearson(xs, ys) == pytest.approx(1.0, abs=1e-9)
    assert _spearman(xs, ys) == pytest.approx(1.0, abs=1e-9)


def test_perfect_negative_correlation():
    from backend.correlations import _pearson

    xs = [float(i) for i in range(20)]
    ys = [-x for x in xs]
    assert _pearson(xs, ys) == pytest.approx(-1.0, abs=1e-9)


def test_spearman_handles_ties():
    from backend.correlations import _spearman

    xs = [1.0, 1.0, 2.0, 2.0, 3.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert -1.0 <= _spearman(xs, ys) <= 1.0


# ---------------------------------------------------------------- AI summary

def test_ai_fallback_summary_is_deterministic_and_grounded():
    from backend.ai_summary import build_fallback_summary

    evidence = {
        "city": "Bengaluru",
        "observations": [
            {"metric": "pm25_ugm3", "value": 62.5, "unit": "µg/m³", "synthetic": True,
             "recorded_at": "2026-09-24T10:00:00+00:00", "location": "demo"},
            {"metric": "temperature_c", "value": 27.4, "unit": "°C", "synthetic": True,
             "recorded_at": "2026-09-24T10:00:00+00:00", "location": "demo"},
        ],
        "recent_anomalies": [],
        "notable_associations": [],
    }
    text1 = build_fallback_summary("Bengaluru", evidence)
    text2 = build_fallback_summary("Bengaluru", evidence)
    assert text1 == text2  # deterministic
    assert "62.5" in text1
    assert "synthetic" in text1.lower()


def test_ai_fallback_handles_empty_evidence():
    from backend.ai_summary import build_fallback_summary

    text = build_fallback_summary("Nowhere", {"observations": [], "recent_anomalies": [],
                                              "notable_associations": []})
    assert "No current observations" in text


# ---------------------------------------------------------------- API schemas

def test_health_reports_providers(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    if body["database_reachable"]:
        assert body["providers"] is not None


def test_data_endpoint_schema(client):
    resp = client.get("/api/data?city=bengaluru&hours=24&limit=50")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "records" in body and "pagination" in body
    for record in body["records"]:
        assert "source_type" in record and "recorded_at" in record


def test_data_endpoint_validates_bbox(client):
    resp = client.get("/api/data?bbox=999,999,1000,1000")
    assert resp.status_code == 200  # invalid bbox ignored, not a crash


def test_sources_endpoint_shape(client):
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    body = resp.get_json()
    types = {s["source_type"] for s in body["sources"]}
    assert types == {"weather", "air_quality", "transit", "incident"}


def test_refresh_cooldown(client):
    resp = client.post("/api/refresh")
    # 200 (ran) or 429 (cooldown) are both acceptable; never a crash.
    assert resp.status_code in (200, 429)
    body = resp.get_json()
    assert body.get("skipped") is not None or "sources" in body


def test_analytics_endpoints_respond(client):
    for path in ("/api/analytics/anomalies?city=bengaluru",
                 "/api/analytics/correlations?city=bengaluru",
                 "/api/ai/summary?city=bengaluru"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        body = resp.get_json()
        assert "note" in body or "limitations" in body or "disclaimer" in body


def test_map_endpoint(client):
    resp = client.get("/api/map?city=delhi&hours=24&limit=100")
    assert resp.status_code == 200
    body = resp.get_json()
    for record in body["records"]:
        assert record.get("latitude") is not None
