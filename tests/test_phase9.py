"""Phase 9 tests: impact engine, cross-domain graph, resilience, twin,
scenario lab, operations copilot.

Offline-safe: pure-logic tests use monkeypatched fetchers; endpoint tests
tolerate both database and degraded modes without fabricating observations.
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


# ----------------------------------------------------------- pure logic

def test_co_occurrence_window_pairs_nearby_only():
    from backend.cross_domain import _time_co_occurrence
    anoms = [
        {"metric": "pm25_ugm3", "observed_bucket": "2026-09-24T10:00:00+00:00",
         "observed_value": 80, "deviation_score": 4.2},
        {"metric": "delay_min", "observed_bucket": "2026-09-24T11:00:00+00:00",
         "observed_value": 9, "deviation_score": 3.1},
        {"metric": "temperature_c", "observed_bucket": "2026-09-24T16:00:00+00:00",
         "observed_value": 35, "deviation_score": 3.5},
    ]
    pairs = _time_co_occurrence(anoms)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p["metric_a"], p["metric_b"]} == {"pm25_ugm3", "delay_min"}
    assert p["co_occurrences"] == 1
    assert p["examples"][0]["values"]["pm25_ugm3"] == 80


def test_scenario_param_validation():
    from backend.scenario_lab import TRAFFIC_DIVERSION, ScenarioParamError, _param
    spec = TRAFFIC_DIVERSION["params"]["diversion_share_pct"]
    assert _param("diversion_share_pct", spec, {"diversion_share_pct": 250}) == 100.0
    assert _param("diversion_share_pct", spec, {"diversion_share_pct": -5}) == 0.0
    assert _param("diversion_share_pct", spec, {}) == 30.0
    assert _param("diversion_share_pct", spec, {"diversion_share_pct": "42"}) == 42.0
    with pytest.raises(ScenarioParamError):
        _param("diversion_share_pct", spec, {"diversion_share_pct": float("nan")})


def test_traffic_diversion_model_math(monkeypatch):
    """Scenario numbers must equal the documented formula over the baseline."""
    from backend import scenario_lab

    monkeypatch.setattr(scenario_lab, "_latest_inputs", lambda city, metrics: {
        "delay_min": {"value": 10.0, "bucket": "b", "n_points": 20, "source": "test"},
        "pm25_ugm3": {"value": 40.0, "bucket": "b", "n_points": 20, "source": "test"},
    })
    out = scenario_lab.run_model("TestCity", "traffic_diversion", {"diversion_share_pct": 50})
    assert out["simulation_label"].startswith("SIMULATED")
    travel = next(r for r in out["rows"] if r["indicator"] == "corridor_travel_time_min")
    # 8 km at 25 km/h = 19.2 min; +50% share * 0.6 = +30% congestion
    assert travel["baseline"] == pytest.approx(19.2, abs=0.01)
    assert travel["scenario"] == pytest.approx(19.2 * 1.3, abs=0.01)
    delay = next(r for r in out["rows"] if r["indicator"] == "remaining_corridor_delay_min")
    assert delay["scenario"] == pytest.approx(10.0 * (1 - 0.5 * 0.8), abs=0.01)
    assert out["baseline_inputs"]["delay_min"]["value"] == 10.0  # real-baseline echo


def test_scenario_run_rejects_unknown_params():
    from backend.scenario_lab import ScenarioParamError, run_model
    with pytest.raises(ScenarioParamError):
        run_model("TestCity", "traffic_diversion", {"bogus_param": 1})
    with pytest.raises(ScenarioParamError):
        run_model("TestCity", "no_such_model", {})


def test_impact_brief_incident_math(monkeypatch):
    """Baseline corridor speed follows the printed formula; advisory flagged."""
    from backend import impact

    anomaly = {
        "city": "TestCity", "source_type": "incident", "metric": "incident_count",
        "observed_bucket": "2026-09-24T10:00:00+00:00", "observed_value": 2,
        "baseline_value": 0.4, "deviation_score": 4.0, "method": "rolling_median_mad",
        "window_hours": 72, "sample_size": 20, "confidence": "medium",
        "limitations": "test",
    }
    monkeypatch.setattr(impact, "_latest_anomaly", lambda city, metric: anomaly)
    monkeypatch.setattr(impact, "fetch_recent_anomalies", lambda city, limit: (True, [anomaly]))
    monkeypatch.setattr(impact, "fetch_normalized_data", lambda **kw: (True, []))
    monkeypatch.setattr(impact, "fetch_metric_series",
                        lambda **kw: (True, [{"bucket": "2026-09-24T09:00:00", "avg_value": 1.0, "n": 5}]))

    brief = impact.build_impact_brief("TestCity", window_hours=72)
    assert brief["status"] == "ok"
    assert brief["advisory"].startswith("Advisory only")
    assert all(iv["advisory"] is True for iv in brief["interventions"])
    est = brief["impact_estimates"]
    speed = next(e for e in est["baseline"] if e["indicator"] == "estimated_corridor_speed_kmh")
    # max(5, 25 - 2*0.35) = 24.3 per the printed formula
    assert speed["baseline"] == pytest.approx(24.3, abs=0.01)
    assert any("max(5" in e["formula"] for e in est["baseline"])
    assert est["coefficients"]["corridor_base_speed_kmh"]["value"] == 25.0
    assert "not operational orders" in brief["note"]


def test_impact_brief_without_anomaly_is_honest(monkeypatch):
    from backend import impact
    monkeypatch.setattr(impact, "_latest_anomaly", lambda city, metric: None)
    brief = impact.build_impact_brief("TestCity")
    assert brief["status"] == "no_anomaly"
    assert "Run detection first" in brief["note"]


def test_cross_domain_graph_classes_and_terminology(monkeypatch):
    from backend import cross_domain

    anomaly_a = {"metric": "pm25_ugm3", "observed_bucket": "2026-09-24T10:00:00+00:00",
                 "observed_value": 80, "deviation_score": 4.2}
    anomaly_b = {"metric": "delay_min", "observed_bucket": "2026-09-24T11:00:00+00:00",
                 "observed_value": 9, "deviation_score": 3.1}
    monkeypatch.setattr(cross_domain, "fetch_recent_anomalies",
                        lambda city, limit: (True, [anomaly_a, anomaly_b]))
    monkeypatch.setattr(cross_domain, "fetch_normalized_data", lambda **kw: (True, []))
    # correlations.analyze_pair pulls its own series; make it insufficient here
    monkeypatch.setattr("backend.correlations.fetch_metric_series", lambda **kw: (True, []))

    report = cross_domain.build_cross_domain_graph("TestCity", window_hours=72)
    assert report["summary"]["co_occurring_pairs"] == 1
    kinds = {e["kind"] for e in report["edges"]}
    assert "co_occurrence" in kinds
    for edge in report["edges"]:
        assert edge["evidence_class"] in {"statistical_association", "hypothesis"}
    for edge_id, ev in report["evidence"].items():
        assert ev["kind"] in {"co_occurrence", "correlation", "co_location", "hypothesis"}
    assert "causation" in report["terminology"]
    assert "NOT claimed" in report["terminology"]["causation"] or "not causation" in report["terminology"]["causation"].lower()
    assert "not causation" in report["note"].lower() or "NOT" in report["note"]


def test_resilience_weights_renormalize_and_explain(monkeypatch):
    from backend import resilience

    class _FakeHealth:
        score, category, contributions = 80.0, "good", [{"metric": "pm25_ugm3"}]

    monkeypatch.setattr("backend.health_score.compute_health_score",
                        lambda city, hours: {"score": 80.0, "category": "good",
                                             "contributions": [{}], "coverage": {}})
    monkeypatch.setattr(resilience, "fetch_recent_anomalies", lambda city, limit: (True, [
        {"observed_bucket": "2026-09-24T10:00:00", "deviation_score": 3.0},
        {"observed_bucket": "2026-09-24T11:00:00", "deviation_score": 6.0},  # severe
        {"observed_bucket": "2026-09-23T10:00:00", "deviation_score": 3.0},
    ]))
    monkeypatch.setattr("backend.events.list_events",
                        lambda **kw: {"events": []})  # no resolved events -> recovery None
    monkeypatch.setattr(resilience, "fetch_history_buckets", lambda city, hours, metrics: (True, [
        {"bucket": "2026-09-24T10:00:00", "metric": "pm25_ugm3", "avg_value": 40.0, "n": 2},
        {"bucket": "2026-09-24T11:00:00", "metric": "delay_min", "avg_value": 3.0, "n": 2},
    ]))

    report = resilience.compute_resilience("TestCity", hours=48)
    assert report["components"]["recovery"]["value"] is None
    assert report["components"]["recovery"]["status"] == "no_data"
    # Weights renormalize over available components only
    used = report["weights_used"]
    assert abs(sum(used.values()) - sum(resilience.COMPONENT_WEIGHTS.values())) < 1e-9
    score = report["resilience_score"]
    assert score is not None and 0 <= score <= 100
    # Hand-compute: stress 80*.3, anomaly 100-20=80*.25, coverage tiny pct*.2 over 2*8=16 expected
    covered = 2
    expected = 48 * len(resilience.EXPECTED_METRICS)
    coverage_pct = min(100.0, covered / expected * 100.0)
    manual = (80.0 * 0.30 + 80.0 * 0.25 + coverage_pct * 0.20) / 0.75
    assert score == pytest.approx(round(manual, 1), abs=0.11)
    assert "NOT a scientifically validated" in report["disclaimer"]
    for comp in report["components"].values():
        assert comp["formula"]


# ----------------------------------------------------------- endpoints

def test_impact_endpoint_contract(client):
    resp = client.get("/api/analytics/impact?city=bengaluru&metric=delay_min")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in {"ok", "no_anomaly"}
    if body["status"] == "ok":
        assert body["advisory"].startswith("Advisory only")
        assert isinstance(body["interventions"], list)
        assert all(iv.get("advisory") is True for iv in body["interventions"])
        est = body["impact_estimates"]
        assert {"baseline", "simulated", "comparison", "coefficients"} <= set(est)
        assert "assumptions" in body and "limitations" in body


def test_cross_domain_endpoint_contract(client):
    resp = client.get("/api/analytics/cross-domain?city=bengaluru&window_hours=72")
    assert resp.status_code == 200
    body = resp.get_json()
    assert {"nodes", "edges", "evidence", "summary", "terminology"} <= set(body)
    for edge in body["edges"]:
        assert {"id", "source", "target", "kind", "evidence_class", "weight", "label"} <= set(edge)
        assert edge["evidence_class"] in {"statistical_association", "hypothesis"}
    assert "NOT claimed" in body["terminology"]["causation"]


def test_resilience_endpoint_contract(client):
    resp = client.get("/api/analytics/resilience?city=bengaluru&hours=72")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["components"]) == {"stress", "anomaly_burden", "recovery", "data_coverage"}
    if body["resilience_score"] is not None:
        assert 0 <= body["resilience_score"] <= 100
        assert body["category"] in {"strong", "moderate", "strained", "weakened"}
    assert "NOT a scientifically validated" in body["disclaimer"]


def test_resilience_trend_clamps_days(client):
    resp = client.get("/api/analytics/resilience/trend?city=bengaluru&days=999")
    assert resp.status_code == 200
    assert resp.get_json()["days"] <= 30


def test_twin_endpoint_contract(client):
    resp = client.get("/api/twin?city=bengaluru&hours=24")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        body = resp.get_json()
        assert body["status"] == "ok"
        for zone in body["zones"]:
            assert {"location", "latitude", "longitude", "metrics", "coverage"} <= set(zone)
            for m in zone["metrics"].values():
                assert {"recent_avg", "previous_avg", "delta_pct", "recent_observations"} <= set(m)
            assert isinstance(zone.get("anomalies_nearby"), list)
            assert isinstance(zone.get("events_nearby"), list)
            for iv in zone.get("advisories", []):
                assert iv["advisory"] is True
        assert "never zero-filled" in body["data_policy"]


def test_scenario_models_catalog(client):
    resp = client.get("/api/scenario-lab/models")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert {m["model_id"] for m in models} == {
        "traffic_diversion", "rainfall_disruption", "air_quality_stress", "resource_allocation",
    }
    for m in models:
        for spec in m["params"].values():
            assert {"min", "max", "default"} <= set(spec)
            assert spec["min"] <= spec["default"] <= spec["max"]


def test_scenario_run_ok_and_validation(client):
    resp = client.post("/api/scenario-lab/run",
                       json={"city": "bengaluru", "model": "traffic_diversion",
                             "params": {"diversion_share_pct": 40}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["simulation_label"].startswith("SIMULATED")
    assert body["params_used"]["diversion_share_pct"] == 40
    for row in body["rows"]:
        assert {"indicator", "baseline", "scenario", "formula"} <= set(row)

    bad_model = client.post("/api/scenario-lab/run", json={"city": "bengaluru", "model": "x"})
    assert bad_model.status_code == 400

    bad_param = client.post("/api/scenario-lab/run",
                            json={"city": "bengaluru", "model": "traffic_diversion",
                                  "params": {"diversion_share_pct": "abc"}})
    assert bad_param.status_code == 400

    unknown_param = client.post("/api/scenario-lab/run",
                                json={"city": "bengaluru", "model": "traffic_diversion",
                                      "params": {"bogus": 1}})
    assert unknown_param.status_code == 400


def test_copilot_contract_and_grounding(client):
    resp = client.post("/api/copilot/ask",
                       json={"city": "bengaluru", "question": "how resilient is the city right now?"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] in {"copilot_tools", "copilot_fallback"}
    assert isinstance(body.get("answer"), str) and body["answer"]
    if body["mode"] == "copilot_tools":
        assert "get_resilience" in body["tools_used"]
        assert any(t.get("tool") == "get_resilience" for t in body["tool_outputs"])

    missing = client.post("/api/copilot/ask", json={})
    assert missing.status_code == 400

    too_long = client.post("/api/copilot/ask", json={"question": "x" * 501})
    assert too_long.status_code == 400


def test_copilot_scenario_question_is_labeled(client):
    resp = client.post("/api/copilot/ask",
                       json={"city": "bengaluru", "question": "what if we divert 40% of traffic?"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] in {"copilot_tools", "copilot_fallback"}
    if body["mode"] == "copilot_tools":
        assert "run_scenario" in body["tools_used"]
        out = next(t for t in body["tool_outputs"] if t.get("tool") == "run_scenario")
        assert out["simulation_label"].startswith("SIMULATED")
        assert "not a prediction" in body["answer"].lower() or "model output" in body["answer"].lower()
