"""Phase 3 tests: civic event lifecycle, real-time bus, simulation safety, API.

Everything runs fully offline. PostgreSQL access is forced off by the
``isolated_demo_store`` fixture so the in-process demo store is exercised — that
keeps the suite hermetic and guarantees no test writes to a real database.

One read-only integration test runs when DATABASE_URL is reachable; it issues
GETs only and never modifies data.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import create_app  # noqa: E402
from backend import database as db  # noqa: E402
from backend import events, realtime, simulation  # noqa: E402
from backend.events import EventError  # noqa: E402


def _db_reachable() -> bool:
    from backend.config import get_settings
    from backend.database import test_connection

    return bool(get_settings().database_url) and test_connection()[0]


LIVE_DB = pytest.mark.skipif(not _db_reachable(), reason="DATABASE_URL not configured/reachable")


@pytest.fixture(autouse=True)
def isolated_demo_store(monkeypatch):
    """Force demo storage and reset all in-process state before each test."""
    monkeypatch.setattr(db, "database_available", lambda ttl=0: False)
    monkeypatch.setattr("backend.routes.database_available", lambda ttl=0: False)
    events.reset_demo_events()
    simulation.reset_demo_runs()
    realtime.reset_bus()
    yield
    events.reset_demo_events()
    simulation.reset_demo_runs()
    realtime.reset_bus()


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _payload(**overrides):
    base = {
        "city": "bengaluru",
        "source_type": "incident",
        "category": "flooding",
        "severity": "high",
        "title": "Waterlogging on the Outer Ring Road",
        "description": "Sustained waterlogging reported after overnight rain.",
        "latitude": 12.9352,
        "longitude": 77.6875,
        "location_name": "Outer Ring Road",
        "tags": ["rain", "drainage"],
        "evidence": [
            {"kind": "reading", "label": "Rainfall in the last 3 hours",
             "value": 38.5, "unit": "mm", "synthetic": True},
        ],
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------- state machine

def test_transition_matrix_covers_every_status():
    assert set(events.ALLOWED_TRANSITIONS) == set(events.EVENT_STATUSES)
    assert events.ALLOWED_TRANSITIONS["closed"] == ()   # terminal state
    for status, targets in events.ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert target in events.EVENT_STATUSES, (status, target)


def test_allowed_actions_mirror_the_state_machine():
    assert events.allowed_actions("open") == [
        "acknowledge", "start", "resolve", "close",
    ]
    assert events.allowed_actions("in_progress") == ["resolve", "close"]
    # A resolved event offers "reopen" (not "start") even though both target
    # in_progress, so the UI wording matches what the operator is doing.
    assert events.allowed_actions("resolved") == ["reopen", "close"]
    assert events.allowed_actions("closed") == []


# --------------------------------------------------------------- validation

@pytest.mark.parametrize(
    "overrides",
    [
        {"city": "atlantis"},
        {"source_type": "traffic"},
        {"severity": "extreme"},
        {"category": "Has Spaces"},
        {"latitude": 91.0},
        {"longitude": -181.0},
        {"title": ""},
        {"description": ""},
        {"reported_at": "2026-01-01T10:00:00"},          # naive timestamp
        {"reported_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()},
        {"evidence": "not-a-list"},
        {"evidence": [{"label": "missing kind"}]},
        {"tags": ["Has Spaces"]},
    ],
)
def test_create_event_rejects_invalid_payloads(overrides):
    with pytest.raises(EventError):
        events.create_event(_payload(**overrides))


def test_create_event_normalizes_fields():
    event = events.create_event(_payload())
    assert event["status"] == "open"
    assert event["is_active"] is True
    assert event["city"] == "Bengaluru"
    assert event["city_id"] == "bengaluru"
    assert event["created"] is True
    assert event["event_ref"].startswith("CP-")
    assert event["severity"] == "high"
    assert event["evidence"][0]["unit"] == "mm"
    assert event["evidence"][0]["synthetic"] is True
    assert event["tags"] == ["rain", "drainage"]
    assert event["revision"] == 1
    assert event["allowed_actions"][0] == "acknowledge"


def test_evidence_is_capped():
    too_many = [{"kind": "reading", "label": f"n{i}"} for i in range(25)]
    with pytest.raises(EventError):
        events.create_event(_payload(evidence=too_many))



# ---------------------------------------------------------------- lifecycle

def test_full_lifecycle_records_timeline_and_timestamps():
    created = events.create_event(_payload())
    ref = created["event_ref"]

    acked = events.transition_event(ref, "acknowledge", actor="ops-1")
    assert acked["status"] == "acknowledged"
    assert acked["acknowledged_at"] is not None
    assert acked["acknowledged_by"] == "ops-1"
    assert acked["allowed_actions"] == ["start", "resolve", "close"]

    started = events.transition_event(ref, "start", actor="ops-1")
    assert started["status"] == "in_progress"

    resolved = events.transition_event(
        ref, "resolve", actor="ops-2", note="Storm drain cleared"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["resolved_by"] == "ops-2"
    assert resolved["resolution_note"] == "Storm drain cleared"
    assert resolved["is_active"] is False

    closed = events.transition_event(ref, "close", actor="ops-2")
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None
    assert closed["allowed_actions"] == []

    detail = events.get_event(ref)
    actions = [entry["action"] for entry in detail["event"]["timeline"]]
    assert actions == ["created", "acknowledge", "start", "resolve", "close"]
    assert detail["event"]["timeline"][0]["to_status"] == "open"
    assert detail["event"]["timeline"][-1]["from_status"] == "resolved"


def test_illegal_and_noop_transitions_are_rejected():
    ref = events.create_event(_payload())["event_ref"]
    events.transition_event(ref, "close", actor="ops")

    # closed is terminal: every action is rejected with 409 (never a 500).
    with pytest.raises(EventError) as closing:
        events.transition_event(ref, "resolve")
    assert closing.value.status == 409
    assert closing.value.code == "illegal_transition"

    with pytest.raises(EventError) as terminal:
        events.transition_event(ref, "reopen")
    assert terminal.value.code == "illegal_transition"

    # A resolved event may be reopened, and a reopened one cannot be "started".
    other = events.create_event(_payload())["event_ref"]
    events.transition_event(other, "resolve", actor="ops")
    reopened = events.transition_event(other, "reopen", actor="ops")
    assert reopened["status"] == "in_progress"
    assert reopened["resolved_at"] is None

    with pytest.raises(EventError) as noop:
        events.transition_event(other, "start")
    assert noop.value.status == 409
    assert noop.value.code == "no_op_transition"

    with pytest.raises(EventError) as unknown:
        events.transition_event(other, "teleport")
    assert unknown.value.code == "unknown_action"


def test_status_cannot_be_patched_directly():
    ref = events.create_event(_payload())["event_ref"]
    with pytest.raises(EventError) as excinfo:
        events.update_event(ref, {"status": "closed"})
    assert excinfo.value.code == "status_immutable"
    assert excinfo.value.status == 409


def test_update_event_changes_fields_and_bumps_revision():
    created = events.create_event(_payload())
    ref = created["event_ref"]
    updated = events.update_event(
        ref,
        {"severity": "critical", "title": "Waterlogging (escalated)"},
        actor="ops-3",
        expected_revision=created["revision"],
    )
    assert updated["severity"] == "critical"
    assert updated["title"] == "Waterlogging (escalated)"
    assert updated["revision"] == created["revision"] + 1
    assert updated["status"] == "open"          # untouched by a field update

    with pytest.raises(EventError) as stale:
        events.update_event(ref, {"title": "stale write"}, expected_revision=1)
    assert stale.value.code == "revision_conflict"
    assert stale.value.status == 409


def test_missing_event_is_a_404_domain_error():
    with pytest.raises(EventError) as excinfo:
        events.transition_event("CP-20260101-AAAAAA", "acknowledge")
    assert excinfo.value.status == 404


def test_external_key_makes_ingestion_idempotent():
    events.ensure_demo_events()
    before = len(events.list_events()["events"])

    first = events.create_event(_payload(external_key="socrata:abc-123"))
    second = events.create_event(_payload(external_key="socrata:abc-123"))

    assert first["event_ref"] == second["event_ref"]
    assert first["created"] is True
    assert second["created"] is False
    assert len(events.list_events()["events"]) == before + 1


def test_list_events_supports_filters():
    events.ensure_demo_events()
    ref = events.create_event(
        _payload(city="mumbai", severity="critical", source_type="air_quality",
                 external_key="filter-test")
    )["event_ref"]

    by_city = events.list_events(city="mumbai")["events"]
    assert [e["event_ref"] for e in by_city] == [ref]

    by_severity = events.list_events(severities=("critical",))["events"]
    assert ref in [e["event_ref"] for e in by_severity]

    by_status = events.list_events(statuses=("acknowledged",))["events"]
    assert ref not in [e["event_ref"] for e in by_status]

    active_only = events.list_events(statuses=("open", "acknowledged", "in_progress"))
    assert active_only["count"] >= 1


def test_demo_mode_is_labelled_and_seeded():
    payload = events.list_events(city="bengaluru")
    assert payload["mode"] == "demo"
    assert payload["persisted"] is False
    assert payload["count"] >= 2          # seed keeps the demo dashboard usable
    assert all(event["city"] == "Bengaluru" for event in payload["events"])

    counts = events.status_breakdown("bengaluru")
    assert set(counts) == set(events.EVENT_STATUSES)
    assert sum(counts.values()) == payload["count"]

# ------------------------------------------------------------- real-time bus

def test_event_bus_numbers_and_dedupes_notifications():
    bus = realtime.get_bus()
    subscriber_id, channel = bus.subscribe()

    for index in range(3):
        bus.publish({"type": "event.created", "event_ref": f"CP-TEST-{index}"})

    ids = [channel.get_nowait()["notification_id"] for _ in range(3)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 3                     # ids are unique => no duplicates

    # since() replays exactly the unread notifications, once each.
    assert [n["notification_id"] for n in bus.since(ids[0])] == ids[1:]
    assert bus.since(ids[-1]) == []

    bus.unsubscribe(subscriber_id)
    assert bus.subscriber_count() == 0


def test_publish_never_blocks_a_saturated_subscriber():
    bus = realtime.EventBus(max_queue=1)
    subscriber_id, channel = bus.subscribe()
    for index in range(5):
        bus.publish({"type": "event.updated", "seq": index})

    latest = channel.get_nowait()
    assert latest["seq"] == 4                     # newest wins, oldest is dropped
    assert bus.subscriber_count() == 1
    bus.unsubscribe(subscriber_id)


def test_publish_never_raises_on_bad_input():
    bus = realtime.EventBus()
    assert bus.publish(None) == -1                # must not propagate


def test_stream_emits_wellformed_sse_and_unsubscribes():
    bus = realtime.get_bus()
    subscriber_id, channel = bus.subscribe()
    bus.publish({"type": "event.acknowledge", "event_ref": "CP-TEST-1"})

    generator = realtime.stream(subscriber_id, channel, heartbeat_seconds=5, max_seconds=30)
    frame = next(generator)
    assert frame.startswith("event: event.acknowledge\ndata: {")
    assert '"notification_id"' in frame
    assert frame.endswith("\n\n")

    generator.close()
    assert bus.subscriber_count() == 0            # listener cleaned up


def test_format_sse_framing():
    assert realtime.format_sse({"a": 1}) == 'data: {"a":1}\n\n'
    assert realtime.format_sse({"a": 1}, event="x").startswith("event: x\ndata: ")


# --------------------------------------------------------------- simulation

def test_scenario_catalog_is_unambiguously_labelled():
    scenarios = simulation.list_scenarios_public()
    assert len(scenarios) >= 6
    for scenario in scenarios:
        assert scenario["severity"] in events.EVENT_SEVERITIES
        assert scenario["source_type"] in events.EVENT_SOURCE_TYPES
        assert scenario["recommended_actions"]
    for scenario_id in simulation.SCENARIOS_BY_ID:
        assert simulation.generate_run_ref(scenario_id).startswith("SIM-")


def test_simulation_identifiers_can_never_collide_with_live_providers():
    live_ids = (
        "open-meteo-bengaluru-temperature_c",
        "openaq-8118-pm25",
        "gtfs-rt-vehicle-1",
        "city-open-data-bengaluru-0",
    )
    for live_id in live_ids:
        assert not live_id.startswith(simulation.SIMULATION_ID_PREFIX)
        with pytest.raises(EventError) as excinfo:
            simulation._assert_simulation_identifier(live_id)
        assert excinfo.value.code == "simulation_identifier_denied"


def test_scenario_observations_pass_live_provider_validation():
    city = next(c for c in simulation.DEMO_CITIES if c["id"] == "bengaluru")
    for scenario in simulation.SCENARIOS:
        observation = simulation.build_observation(scenario, city, "SIM-TEST-0001")
        assert observation.source_id.startswith(simulation.SIMULATION_ID_PREFIX)
        assert observation.provider == simulation.SIMULATION_PROVIDER
        assert observation.is_synthetic is True
        assert observation.description.startswith("Demo:")
        assert observation.metadata["simulation_run_id"] == "SIM-TEST-0001"
        # Same gate the live providers must pass.
        simulation.validate_observation(observation)


def test_run_scenario_creates_a_labelled_event_and_run():
    payload = simulation.run_scenario("flash_flood", "bengaluru", actor="tester")

    assert payload["mode"] == "demo"
    assert payload["persisted"] is False
    assert payload["run"]["status"] == "running"
    assert payload["run"]["run_ref"].startswith("SIM-")
    assert payload["observation"]["persisted"] is False   # demo mode: not stored
    assert payload["observation"]["error"]

    event = payload["event"]
    assert event["is_simulated"] is True
    assert event["simulation_run_id"] == payload["run"]["run_ref"]
    assert event["tags"] == ["simulation", "flash_flood", "drill", "drainage"]
    assert all(item["synthetic"] is True for item in event["evidence"])
    assert "Scenario drill" in event["description"]


def test_unknown_scenario_is_rejected():
    with pytest.raises(EventError) as excinfo:
        simulation.run_scenario("alien_invasion", "bengaluru")
    assert excinfo.value.status == 404


def test_run_advances_through_the_shared_lifecycle_then_resets():
    started = simulation.run_scenario("water_main_break", "delhi")
    run_ref = started["run"]["run_ref"]

    acknowledged = simulation.advance_run(run_ref, "acknowledge", actor="tester")
    assert acknowledged["event"]["status"] == "acknowledged"

    resolved = simulation.advance_run(run_ref, "resolve", actor="tester", note="Main isolated")
    assert resolved["event"]["status"] == "resolved"
    assert resolved["event"]["resolution_note"] == "Main isolated"

    closed = simulation.advance_run(run_ref, "close", actor="tester")
    assert closed["event"]["status"] == "closed"

    with pytest.raises(EventError) as excinfo:
        simulation.advance_run(run_ref, "resolve")
    assert excinfo.value.code == "no_active_event"

    reset = simulation.reset_run(run_ref)
    assert reset["run"]["status"] == "reset"
    assert "closed_events" in reset and "skipped_events" in reset
    # The drill's event is closed, never deleted.
    assert simulation.run_detail(run_ref) is not None


# -------------------------------------------------------------- HTTP surface

def test_events_endpoint_lists_seeded_demo_events(client):
    response = client.get("/api/events?city=bengaluru")
    assert response.status_code == 200
    body = response.get_json()
    assert body["mode"] == "demo"
    assert body["persisted"] is False
    assert body["count"] >= 2
    first = body["events"][0]
    for key in ("event_ref", "status", "severity", "allowed_actions", "evidence",
                "latitude", "longitude", "reported_at"):
        assert key in first
    assert "Simulated events" in body["note"]


def test_events_create_then_act_via_api(client):
    created = client.post("/api/events", json=_payload())
    assert created.status_code == 201
    event = created.get_json()["event"]
    ref = event["event_ref"]
    assert event["status"] == "open"

    acked = client.post(f"/api/events/{ref}/acknowledge", json={"actor": "api-test"})
    assert acked.status_code == 200
    assert acked.get_json()["event"]["status"] == "acknowledged"
    assert acked.get_json()["event"]["acknowledged_by"] == "api-test"

    resolved = client.post(f"/api/events/{ref}/resolve",
                           json={"note": "Cleared by crew", "actor": "api-test"})
    assert resolved.status_code == 200
    assert resolved.get_json()["event"]["status"] == "resolved"

    # A resolved event cannot be resolved again (no-op => 409, never a crash).
    again = client.post(f"/api/events/{ref}/resolve", json={})
    assert again.status_code == 409
    assert again.get_json()["code"] == "no_op_transition"

    detail = client.get(f"/api/events/{ref}")
    assert detail.status_code == 200
    timeline = detail.get_json()["event"]["timeline"]
    assert [item["action"] for item in timeline] == ["created", "acknowledge", "resolve"]


def test_events_create_validates_input(client):
    response = client.post("/api/events", json=_payload(city="atlantis"))
    assert response.status_code == 400
    assert response.get_json()["code"] == "unknown_city"

    response = client.post("/api/events", json={"title": "no coordinates"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "validation_error"


def test_events_unknown_reference_returns_404(client):
    assert client.get("/api/events/CP-20260101-ZZZZZZ").status_code == 404
    assert client.post("/api/events/CP-20260101-ZZZZZZ/acknowledge", json={}).status_code == 404


def test_events_patch_rejects_status_and_applies_fields(client):
    ref = client.post("/api/events", json=_payload()).get_json()["event"]["event_ref"]

    rejected = client.patch(f"/api/events/{ref}", json={"status": "closed"})
    assert rejected.status_code == 409
    assert rejected.get_json()["code"] == "status_immutable"

    patched = client.patch(f"/api/events/{ref}", json={"severity": "critical"})
    assert patched.status_code == 200
    assert patched.get_json()["event"]["severity"] == "critical"


def test_summary_reports_event_counts(client):
    body = client.get("/api/summary?city=bengaluru").get_json()
    assert "active_events" in body["summary"]
    assert "event_counts" in body["summary"]
    assert set(body["summary"]["event_counts"]) == set(events.EVENT_STATUSES)


def test_simulation_endpoints_run_and_reset(client):
    scenarios = client.get("/api/simulation/scenarios")
    assert scenarios.status_code == 200
    assert scenarios.get_json()["enabled"] is True
    assert len(scenarios.get_json()["scenarios"]) >= 6

    missing = client.post("/api/simulation/run", json={"city": "bengaluru"})
    assert missing.status_code == 400

    started = client.post("/api/simulation/run",
                          json={"scenario_id": "air_quality_spike", "city": "delhi"})
    assert started.status_code == 201
    payload = started.get_json()
    run_ref = payload["run"]["run_ref"]
    assert payload["event"]["is_simulated"] is True

    advanced = client.post(f"/api/simulation/runs/{run_ref}/advance",
                           json={"action": "acknowledge"})
    assert advanced.status_code == 200

    runs = client.get("/api/simulation/runs").get_json()
    assert run_ref in [run["run_ref"] for run in runs["runs"]]

    reset = client.post(f"/api/simulation/runs/{run_ref}/reset", json={})
    assert reset.status_code == 200
    assert reset.get_json()["run"]["status"] == "reset"

    assert client.get("/api/simulation/runs/SIM-NOPE").status_code == 404


def test_poll_endpoint_replays_notifications_without_duplicates(client):
    first = client.get("/api/events/poll?since=0").get_json()
    assert first["transport"] == "poll"
    assert "version" in first and "events" in first

    ref = client.post("/api/events", json=_payload()).get_json()["event"]["event_ref"]
    client.post(f"/api/events/{ref}/acknowledge", json={})

    from backend.realtime import get_bus

    bus = get_bus()
    after = client.get(
        f"/api/events/poll?since={first['last_notification_id']}"
    ).get_json()
    ids = [n["notification_id"] for n in after["notifications"]]
    assert len(ids) == len(set(ids))                  # no duplicate alerts
    assert all(i > first["last_notification_id"] for i in ids)
    assert after["last_notification_id"] == bus.last_notification_id

    nothing_new = client.get(
        f"/api/events/poll?since={bus.last_notification_id}"
    ).get_json()
    assert nothing_new["notifications"] == []


def test_realtime_status_reports_transport(client):
    body = client.get("/api/realtime/status").get_json()
    assert body["transport"] == "sse"
    assert body["stream_path"] == "/api/events/stream"
    assert isinstance(body["subscribers"], int)
    assert "last_notification_id" in body


def test_stream_endpoint_returns_sse_snapshot(client):
    app = client.application
    view = app.view_functions["api.events_stream"]
    with app.test_request_context("/api/events/stream?city=bengaluru"):
        response = view()
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"].startswith("no-cache")
        frame = next(iter(response.response))
        assert frame.startswith("event: stream.ready\ndata: {")
        assert '"version"' in frame
        response.response.close()


def test_stream_reports_503_when_realtime_is_disabled(client, monkeypatch):
    from backend import routes

    class _Settings:
        realtime_enabled = False
        sse_heartbeat_seconds = 20
        sse_max_stream_seconds = 30
        simulation_enabled = True

    monkeypatch.setattr(routes, "get_settings", lambda: _Settings())
    response = client.get("/api/events/stream")
    assert response.status_code == 503
    assert response.get_json()["fallback"] == "/api/events/poll"


# ------------------------------------------------------- live (read-only)

@LIVE_DB
def test_live_database_event_reads(client):
    """Read-only integration check against the configured PostgreSQL database."""
    listed = client.get("/api/events?limit=5")
    assert listed.status_code == 200
    body = listed.get_json()
    assert body["mode"] in ("database", "demo")
    assert isinstance(body["events"], list)

    status = client.get("/api/realtime/status")
    assert status.status_code == 200
    assert status.get_json()["transport"] == "sse"

    runs = client.get("/api/simulation/runs?limit=5")
    assert runs.status_code == 200
    assert isinstance(runs.get_json()["runs"], list)


def test_settings_exposes_event_machine_and_realtime(client):
    body = client.get("/api/settings").get_json()
    assert body["events"]["statuses"] == list(events.EVENT_STATUSES)
    assert body["events"]["transitions"]["closed"] == []
    assert body["realtime"]["transport"] == "sse"
    assert body["realtime"]["stream_path"] == "/api/events/stream"
    assert body["simulation_enabled"] is True

