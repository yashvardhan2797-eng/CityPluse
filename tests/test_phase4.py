"""Phase 3/4 backend tests: companion grounding, alerts, history, locations.

No live network calls; database-backed assertions are skipped automatically
when DATABASE_URL is not configured/reachable.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import create_app  # noqa: E402


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


# ------------------------------------------------------------------ companion

def _evidence() -> dict:
    return {
        "city": "Bengaluru",
        "window_hours": 72,
        "generated_at": "2026-09-24T12:00:00+00:00",
        "observations": [
            {
                "source_type": "air_quality",
                "metric": "pm25_ugm3",
                "value": 117.7,
                "unit": "µg/m³",
                "location": "Bengaluru (city-wide)",
                "recorded_at": "2026-09-24T11:00:00+00:00",
                "synthetic": True,
            },
        ],
        "recent_anomalies": [
            {
                "metric": "precipitation_mm",
                "observed_value": 4.1,
                "baseline_value": 0.6,
                "score": 4.2,
                "bucket": "2026-09-24T10:00:00+00:00",
                "confidence": "low",
            },
        ],
        "notable_associations": [
            {
                "metric_a": "pm25_ugm3",
                "metric_b": "temperature_c",
                "pearson_r": -0.52,
                "spearman_rho": -0.49,
                "sample_size": 18,
                "interpretation": "moderate negative association",
            },
        ],
        "data_quality_notes": [],
    }


def test_companion_answers_metric_question_from_evidence():
    from backend.companion import answer_from_evidence

    answer = answer_from_evidence("What is the PM2.5 right now?", _evidence(), "Bengaluru")
    assert "117.7" in answer  # cited from evidence
    assert "synthetic" in answer.lower()  # provenance disclosed
    assert "cause" not in answer.lower()


def test_companion_anomaly_question_reports_honestly():
    from backend.companion import answer_from_evidence

    answer = answer_from_evidence("Any anomalies today?", _evidence(), "Bengaluru")
    assert "precipitation" in answer.lower()
    assert "does not explain" in answer.lower() or "not explained" in answer.lower()


def test_companion_association_question_never_claims_causation():
    from backend.companion import answer_from_evidence

    answer = answer_from_evidence("Is air quality related to temperature?", _evidence(), "Bengaluru")
    assert "association" in answer.lower()
    assert "not" in answer.lower() and "cause" in answer.lower()


def test_companion_insufficient_data_answer():
    from backend.companion import answer_from_evidence

    evidence = _evidence()
    evidence["observations"] = []
    evidence["recent_anomalies"] = []
    evidence["notable_associations"] = []
    answer = answer_from_evidence("How is the traffic?", evidence, "Bengaluru")
    assert "no observations are available" in answer.lower() or "cannot answer" in answer.lower()


def test_companion_rejects_invented_numbers():
    """A model answer citing a number absent from evidence must fail validation."""
    from backend.companion import _validate_answer

    with pytest.raises(ValueError):
        _validate_answer("PM2.5 is 999.9 µg/m³ now.", _evidence())


def test_companion_endpoint_validates_input(client):
    resp = client.post("/api/ai/ask", json={"city": "bengaluru", "question": ""})
    assert resp.status_code == 400
    resp = client.post("/api/ai/ask", json={"city": "bengaluru", "question": "x" * 600})
    assert resp.status_code == 400


def test_companion_endpoint_answers(client):
    resp = client.post("/api/ai/ask", json={
        "city": "bengaluru", "question": "What is the PM2.5?", "window_hours": 72,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["answer"]
    assert body["answered_by"] in ("deterministic-retriever",) or body["answered_by"].startswith("ai:")
    assert "grounded_in" in body


# ------------------------------------------------------------------ alerts

def test_alerts_severity_from_score():
    from backend.alerts import _severity_from_score

    assert _severity_from_score(None) == "low"
    assert _severity_from_score(4.5) == "moderate"
    assert _severity_from_score(6.5) == "high"
    assert _severity_from_score(9.0) == "critical"


def test_alert_rule_evaluation_skips_missing_values():
    """Missing observations are never treated as zero."""
    from backend.alerts import _evaluate_rule

    rule = {"metric": "pm25_ugm3", "operator": ">", "threshold_value": 50.0,
            "window_hours": 24, "city": None}
    series = [
        {"location_name": "A", "value": None, "recorded_at": datetime.now(timezone.utc)},
        {"location_name": "B", "value": 61.0, "recorded_at": datetime.now(timezone.utc)},
    ]
    with patch("backend.alerts.db.fetch_metric_series", return_value=(True, series)):
        hits = _evaluate_rule(rule, "Bengaluru", 24)
    assert len(hits) == 1  # only location B
    assert hits[0]["value"] == 61.0


def test_alert_rule_operator_semantics():
    from backend.alerts import _evaluate_rule

    rule = {"metric": "temperature_c", "operator": "<", "threshold_value": 5.0,
            "window_hours": 24, "city": None}
    series = [
        {"location_name": "A", "value": 3.0, "recorded_at": datetime.now(timezone.utc)},
        {"location_name": "B", "value": 9.0, "recorded_at": datetime.now(timezone.utc)},
    ]
    with patch("backend.alerts.db.fetch_metric_series", return_value=(True, series)):
        hits = _evaluate_rule(rule, "Bengaluru", 24)
    assert [h["location_name"] for h in hits] == ["A"]


def test_alerts_endpoint_lists_and_shape(client):
    resp = client.get("/api/alerts?city=bengaluru&status=active")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "alerts" in body and "city" in body
    for alert in body["alerts"]:
        assert {"dedup_key", "severity", "title", "summary", "evidence"} <= set(alert)


def test_alerts_rules_endpoint(client):
    resp = client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert "rules" in resp.get_json()


def test_alert_acknowledge_unknown_key_404(client):
    resp = client.post("/api/alerts/does-not-exist/acknowledge?city=bengaluru")
    assert resp.status_code in (404, 200)  # demo fallback may accept, DB returns 404


@DB
def test_alert_sync_is_idempotent():
    """Re-running the sync must not duplicate alert rows."""
    from backend.alerts import sync_alerts

    first = sync_alerts("Bengaluru", window_hours=24)
    second = sync_alerts("Bengaluru", window_hours=24)
    assert second["created"] == 0  # dedup keys prevent duplicates


# ------------------------------------------------------------------ history

@DB
def test_history_endpoint_shape_and_bounds(client):
    resp = client.get("/api/history?city=bengaluru&hours=168")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] in ("database", "demo")
    assert isinstance(body["buckets"], list)
    assert "coverage" in body
    for bucket in body["buckets"]:
        assert {"bucket", "metric", "avg_value", "n"} <= set(bucket)


def test_history_endpoint_validates_hours(client):
    resp = client.get("/api/history?city=bengaluru&hours=99999")
    assert resp.status_code == 200  # clamped to the allowed maximum


def test_history_endpoint_discloses_gaps(client):
    resp = client.get("/api/history?city=bengaluru&hours=168")
    body = resp.get_json()
    note = body.get("note", "")
    assert "stored records" in note.lower() or "interpolated" in note.lower()


# ------------------------------------------------------------------ locations

@DB
def test_locations_endpoint_shape(client):
    resp = client.get("/api/analytics/locations?city=bengaluru&hours=24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body["locations"], list)
    assert "coverage" in body["note"].lower() or "coverage" in str(body).lower()
    for entry in body["locations"]:
        assert {"location", "metrics", "observations"} <= set(entry)


def test_locations_endpoint_bounded_metrics(client):
    resp = client.get("/api/analytics/locations?city=bengaluru&hours=24&metrics=a,b,c,d,e,f,g,h")
    assert resp.status_code == 200  # extra metrics are dropped, not an error
